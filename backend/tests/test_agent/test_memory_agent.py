"""memory_agent + 后台队列测试（记忆抽取子代理方案 §5）。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 队列：入队流转 / 指纹幂等去重 / LRU 上限 / 失败不冒泡 / 审计行
- memory_agent：构建结构（独立 StateBackend + 5 工具 + 权限 deny）
- 工具：write_store 幂等（已存在跳过）/ 未知类型 ValueError
- 降级：memory_agent_enabled=false 走单次抽取（chat 集成）
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.agent.memory import agent as memory_agent
from src.agent.memory.queue import MemoryTask, MemoryTaskQueue
from src.core.config import settings


# ── 队列 ──

def _task(session: str = "s1", msg: str = "hi") -> MemoryTask:
    return MemoryTask(
        session_id=session, user_message=msg, assistant_text="ok",
        fingerprint=f"{session}|{msg}",
    )


def test_enqueue_and_duplicate_rejected() -> None:
    """入队 + 指纹幂等：相同指纹不重复入队。"""
    q = MemoryTaskQueue()
    assert q.enqueue(_task()) is True
    assert q.enqueue(_task()) is False, "相同指纹应去重"
    assert q.stats["pending"] == 1


def test_enqueue_lru_bounds(monkeypatch) -> None:
    """LRU 上限：超过 _SEEN_MAX 逐出最旧（防内存泄漏）。

    注：队列上限（_MAX_QUEUE=100）先于 LRU 上限触发——monkeypatch 缩小
    _SEEN_MAX 走真实 enqueue 路径（LRU 逐出在入队成功后执行）。
    """
    from src.agent.memory import queue as queue_mod

    monkeypatch.setattr(queue_mod, "_SEEN_MAX", 5)
    q = queue_mod.MemoryTaskQueue()
    for i in range(15):
        q.enqueue(_task(session=f"s{i}"))
    assert len(q._seen) == 5, "LRU 超限应逐出到上限"
    assert "s0|hi" not in q._seen, "最旧指纹应被逐出（可重新入队）"
    assert "s14|hi" in q._seen, "最新指纹保留"


@pytest.mark.asyncio
async def test_worker_consumes_and_records(audit_records) -> None:
    """worker 消费：任务流转（pending→running→completed）+ 审计行。"""
    q = MemoryTaskQueue()
    q.enqueue(_task())

    async def consumer(task):
        return "已写入 user_profile"

    worker = asyncio.create_task(q.run_worker(consumer))
    await asyncio.sleep(0.1)   # 给 worker 消费时间
    worker.cancel()

    assert q.stats["completed"] == 1 and q.stats["running"] == 0
    events = [json.loads(r.getMessage()) for r in audit_records]
    assert [e["event"] for e in events] == ["enqueue", "start", "completed"]
    assert events[-1]["layer"] == "memory_agent"
    assert "已写入 user_profile" in events[-1]["detail"]


@pytest.mark.asyncio
async def test_worker_failure_not_bubbles(audit_records) -> None:
    """worker 失败：不冒泡（后台任务），failed 计数 + 审计。"""
    q = MemoryTaskQueue()
    q.enqueue(_task())

    async def consumer(task):
        raise RuntimeError("抽取炸了")

    worker = asyncio.create_task(q.run_worker(consumer))
    await asyncio.sleep(0.1)
    worker.cancel()

    assert q.stats["failed"] == 1, "失败入 failed 计数"
    events = [json.loads(r.getMessage()) for r in audit_records]
    assert events[-1]["event"] == "failed"


# ── memory_agent 构建 ──

def test_build_memory_agent_structure(mocker) -> None:
    """构建：CompiledSubAgent——独立 StateBackend + 5 工具 + 写全 deny。"""
    captured: dict = {}
    mock_create = mocker.patch(
        "src.agent.memory.agent.create_deep_agent",
        side_effect=lambda **kwargs: captured.update(kwargs) or object(),
    )
    from deepagents.backends import StateBackend

    result = memory_agent.build_memory_agent(object())

    assert mock_create.call_count == 1
    assert isinstance(captured["backend"], StateBackend), "独立内存 backend"
    assert len(captured["tools"]) == 5, "工具集最小化（5 个）"
    tool_names = {t.__name__ for t in captured["tools"]}
    assert tool_names == {"search_memory", "read_memory_file", "write_store",
                          "write_wiki", "send_notification"}
    assert captured["permissions"][0].mode == "deny", "文件写全 deny"
    assert list(result) == ["name", "description", "runnable"], "CompiledSubAgent 三字段"


def test_fingerprint_stable() -> None:
    """对话指纹：相同输入稳定（幂等基础）。"""
    f1 = memory_agent._fingerprint("s1", "msg", "reply")
    f2 = memory_agent._fingerprint("s1", "msg", "reply")
    assert f1 == f2 and len(f1) == 16


# ── 工具：write_store 幂等 ──

@pytest.mark.asyncio
async def test_write_store_idempotent(mocker) -> None:
    """幂等：内容已存在 → 跳过（第二次不写）。"""
    store = SimpleNamespace(
        asearch=mocker.AsyncMock(return_value=[SimpleNamespace(value={"content": "事实X"})]),
        aput=mocker.AsyncMock(),
    )
    mocker.patch("src.agent.main_agent.get_store", return_value=store)

    result = await memory_agent.write_store("facts", "事实X")

    assert result == "已存在，跳过（幂等）"
    store.aput.assert_not_called(), "已存在不应写入"


@pytest.mark.asyncio
async def test_write_store_writes_new(mocker) -> None:
    """新事实：写入对应 namespace。"""
    store = SimpleNamespace(
        asearch=mocker.AsyncMock(return_value=[]),
        aput=mocker.AsyncMock(),
    )
    mocker.patch("src.agent.main_agent.get_store", return_value=store)
    mocker.patch("src.agent.memory.agent.save_typed_memory", new=mocker.AsyncMock())

    result = await memory_agent.write_store("user_profile", "新偏好")

    assert result == "已写入 user_profile"


@pytest.mark.asyncio
async def test_write_store_unknown_type(mocker) -> None:
    """未知类型 → ValueError（白名单）。"""
    mocker.patch("src.agent.main_agent.get_store", return_value=SimpleNamespace())
    with pytest.raises(ValueError, match="未知记忆类型"):
        await memory_agent.write_store("unknown", "x")


@pytest.mark.asyncio
async def test_write_store_no_store_degrades(mocker) -> None:
    """store 未初始化 → 降级提示（不抛错）。"""
    mocker.patch("src.agent.main_agent.get_store", return_value=None)
    result = await memory_agent.write_store("facts", "x")
    assert "记忆库未初始化" in result


# ── 开关 ──

def test_memory_agent_switch_default_on() -> None:
    """默认开关：memory_agent_enabled=True（学习 demo 主诉求）。"""
    assert settings.memory_agent_enabled is True


# ── P1：search_memory 类型感知查重 + read_memory_file backend 接入 ──

@pytest.mark.asyncio
async def test_search_memory_typed_results(mocker) -> None:
    """P1：查重返回含类型条目（[user_profile] 格式）——子代理去重协议。"""
    store = SimpleNamespace(
        asearch=mocker.AsyncMock(
            side_effect=[
                [SimpleNamespace(value={"content": "用户喜欢中文"})],   # user_profile
                [SimpleNamespace(value={"content": "deepagents 是框架"})],  # facts
            ]
        )
    )
    mocker.patch("src.agent.main_agent.get_store", return_value=store)

    result = await memory_agent.search_memory("中文")

    assert "[user_profile] 用户喜欢中文" in result, "含类型前缀"
    assert "无匹配" not in result


@pytest.mark.asyncio
async def test_read_memory_file_backend(mocker) -> None:
    """P1：读记忆文件经 backend（aread /memories/）——辅助抽取真实可用。"""
    fake_backend = SimpleNamespace(
        aread=mocker.AsyncMock(return_value={"content": "# 任务\n- [ ] 进行中"})
    )
    mocker.patch("src.core.backend.create_backend", return_value=fake_backend)

    result = await memory_agent.read_memory_file("tasks.md")

    assert "进行中" in result, "读到文件内容"
    fake_backend.aread.assert_called_once_with("/memories/tasks.md"), "虚拟路径"


@pytest.mark.asyncio
async def test_read_memory_file_rejects_escape(mocker) -> None:
    """P1：路径逃逸拒绝（00-security）。"""
    mocker.patch("src.core.backend.create_backend")
    assert "路径不合法" in await memory_agent.read_memory_file("../x.md")
    assert "路径不合法" in await memory_agent.read_memory_file("/etc/passwd")


# ── P2：send_notification 降级真实化（本地通知文件）──

@pytest.mark.asyncio
async def test_send_notification_writes_local_file(mocker, tmp_path) -> None:
    """P2：通知落 data/notifications.log（可审计可查）。"""
    mocker.patch("src.core.paths.get_app_dir", return_value=tmp_path)

    result = await memory_agent.send_notification("重要记忆已写入")

    assert "已记录到本地通知文件" in result
    content = (tmp_path / "notifications.log").read_text(encoding="utf-8")
    assert "重要记忆已写入" in content, "通知内容落盘"


# ── P3：质量评估 ──

def test_score_memory_quality_dimensions() -> None:
    """P3：评分维度（信息量/类型/唯一性）。"""
    assert memory_agent.score_memory_quality("短", "facts") < 3, "过短低质"
    long_fact = "用户偏好：中文回复，技术栈 Python/React，喜欢简洁风格（2026 年确认）"
    assert memory_agent.score_memory_quality(long_fact, "user_profile") >= 3, "长+数字高质"
    # 唯一性：重复条目多 → 扣分
    score_base = memory_agent.score_memory_quality("事实内容含数字 2026", "facts")
    score_dup = memory_agent.score_memory_quality("事实内容含数字 2026", "facts", duplicates=3)
    assert score_dup < score_base, "重复条目扣分"
    assert 1 <= memory_agent.score_memory_quality("x", "facts", duplicates=9) <= 5, "分数限幅"
