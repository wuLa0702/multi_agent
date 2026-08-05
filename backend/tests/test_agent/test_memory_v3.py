"""记忆体系 v3 测试（方案 §8.5）：类型化抽取链路 / 注入布局 / 任务归档 / 短对话跳过。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 注入布局：memory 单文件虚拟路径 + v3 指引（AGENTS 禁写用户记忆）
- 类型化抽取：短对话跳过 / 启发式分类 / 类型白名单
- 归档：超限归档 / 未超限不动 / tasks.md 不存在跳过
- 兼容：旧 global namespace 注入兼容（load_recent_memories_v3 合并读取）
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.agent import main_agent, memory_store
from src.agent.memory_store import (
    TASKS_ARCHIVE_KEEP,
    archive_completed_tasks,
    extract_memory_typed,
    save_typed_memory,
)


# ── P0：注入布局 ──

def test_memory_mounted_single_source(mocker) -> None:
    """P0：memory=['/memories/AGENTS.md'] 单文件虚拟路径（v3 决策，防磁盘路径）。"""
    mocker.patch("src.agent.main_agent.get_chat_model", return_value=object())
    mocker.patch("src.agent.main_agent.load_subagents", return_value=[])
    mock_create = mocker.patch(
        "src.agent.main_agent.create_deep_agent", side_effect=lambda *a, **k: object()
    )

    main_agent._build_agent("t1")

    _, kwargs = mock_create.call_args
    assert kwargs["memory"] == ["/memories/AGENTS.md"], "v3：单文件注入"
    # 防磁盘路径：虚拟路径以 / 开头合法；禁 Windows 盘符与 data/ 磁盘相对路径
    assert not any(p.startswith(("C:", "D:")) or "data/" in p
                   for p in kwargs["memory"]), "禁止磁盘路径（virtual_mode 拒绝）"
    assert "记忆维护（v3" in kwargs["system_prompt"], "v3 指引已注入"
    assert "禁止写入用户记忆" in kwargs["system_prompt"], "AGENTS 禁写用户记忆约定"


# ── P1：类型化抽取 ──

@pytest.mark.asyncio
async def test_extract_typed_skips_short_conversation(mocker) -> None:
    """v3.1：短对话（turn_count < 2）跳过抽取（省 token）。"""
    mocker.patch.object(
        memory_store, "extract_memory_fact",
        new=mocker.AsyncMock(return_value="应该抽取但被跳过"),
    )
    assert await extract_memory_typed("你好", "你好！", turn_count=1) is None


@pytest.mark.asyncio
async def test_extract_typed_classifies_user_profile(mocker) -> None:
    """启发式分类：用户相关关键词 → user_profile。"""
    mocker.patch.object(
        memory_store, "extract_memory_fact",
        new=mocker.AsyncMock(return_value="用户喜欢用中文回复"),
    )
    entry = await extract_memory_typed("我喜欢用中文回复", "好的，记住了", turn_count=3)
    assert entry == {"type": "user_profile", "fact": "用户喜欢用中文回复"}


@pytest.mark.asyncio
async def test_extract_typed_classifies_facts(mocker) -> None:
    """无用户关键词 → facts。"""
    mocker.patch.object(
        memory_store, "extract_memory_fact",
        new=mocker.AsyncMock(return_value="deepagents 是 langchain 的 agent 框架"),
    )
    entry = await extract_memory_typed("deepagents 是什么", "deepagents 是……", turn_count=3)
    assert entry["type"] == "facts"


@pytest.mark.asyncio
async def test_save_typed_memory_namespace(mocker) -> None:
    """类型化写入：落对应 namespace（user_profile/facts）。"""
    store = SimpleNamespace(
        aput=mocker.AsyncMock(),
        asearch=mocker.AsyncMock(return_value=[]),
    )
    await save_typed_memory(store, "user_profile", "用户偏好中文")
    ns, key, value = store.aput.call_args.args
    assert ns == ("memory", "user_profile")
    assert value["content"] == "用户偏好中文"

    await save_typed_memory(store, "facts", "一个客观事实")
    assert store.aput.call_args.args[0] == ("memory", "facts")


@pytest.mark.asyncio
async def test_save_typed_memory_unknown_type(mocker) -> None:
    """未知类型 → ValueError（白名单校验）。"""
    store = SimpleNamespace(aput=mocker.AsyncMock())
    with pytest.raises(ValueError, match="未知记忆类型"):
        await save_typed_memory(store, "unknown", "x")


@pytest.mark.asyncio
async def test_load_recent_memories_v3_merges_namespaces(mocker) -> None:
    """注入兼容：user_profile + facts + 旧 global 合并，画像优先。"""
    store = SimpleNamespace(
        asearch=mocker.AsyncMock(
            side_effect=[
                [SimpleNamespace(value={"content": "画像A", "ts": 1})],
                [SimpleNamespace(value={"content": "事实B", "ts": 2})],
                [SimpleNamespace(value={"content": "旧数据C", "ts": 3})],
            ]
        )
    )
    memories = await memory_store.load_recent_memories_v3(store, limit=5)
    assert memories == ["画像A", "事实B", "旧数据C"], "画像优先排序"


# ── P1：任务归档 ──

class _FakeMemoryBackend:
    """/memories/ 路由 fake：aread/awrite 记录（tasks.md 内容可注入）。"""

    def __init__(self, tasks_content: str, archive_content: str = "") -> None:
        self._files = {"/memories/tasks.md": tasks_content,
                       "/memories/tasks_archive.md": archive_content}
        self.writes: list[tuple[str, str]] = []

    async def aread(self, path: str) -> dict:
        return {"content": self._files.get(path, "")}

    async def awrite(self, path: str, content: str) -> None:
        self._files[path] = content
        self.writes.append((path, content))


def _tasks_with_done(n_done: int) -> str:
    lines = ["- [ ] 进行中任务"]
    lines += [f"- [x] 已完成任务 {i}" for i in range(n_done)]
    return "\n".join(lines) + "\n"


@pytest.mark.asyncio
async def test_archive_moves_overflow() -> None:
    """超限归档：已完成 >20 → 保留最近 20，更早移 archive。"""
    backend = _FakeMemoryBackend(_tasks_with_done(TASKS_ARCHIVE_KEEP + 5))
    archived = await archive_completed_tasks(backend)
    assert archived == 5
    tasks_content = dict(backend.writes)["/memories/tasks.md"]
    assert tasks_content.count("- [x]") == TASKS_ARCHIVE_KEEP, "保留最近 20 条"
    assert "- [ ] 进行中任务" in tasks_content, "未完成保留"
    arch_content = dict(backend.writes)["/memories/tasks_archive.md"]
    assert "已完成任务 0" in arch_content and "已完成任务 4" in arch_content, "更早的已归档"


@pytest.mark.asyncio
async def test_archive_no_overflow_unchanged() -> None:
    """未超限：tasks.md 不动（无写入）。"""
    backend = _FakeMemoryBackend(_tasks_with_done(TASKS_ARCHIVE_KEEP - 1))
    assert await archive_completed_tasks(backend) == 0
    assert backend.writes == [], "未超限不应写入"


@pytest.mark.asyncio
async def test_archive_missing_tasks_file_skipped() -> None:
    """tasks.md 不存在/读失败 → 跳过（旁路能力不报错）。"""
    backend = _FakeMemoryBackend("")
    assert await archive_completed_tasks(backend) == 0
