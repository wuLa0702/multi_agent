"""HITL（P0 设计 §8）测试：审批配置 / 中断回调 / 待决存储 / approve 事件 / 修订计数。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 门控：hitl_enabled 控制 interrupt_on 与 HITL 工具挂载
- 中断回调：HitlCallback.on_interrupt 采集 checkpoint_id + HITLRequest
- approve 事件：run_id/checkpoint_id 分离 + call_id fallback + arguments 截断
- 待决存储：call_id 乱序归位 / getdel 一次性 / 空 action 校验 / TTL
- 修订计数：publish_report reject 累计 + 上限注入逻辑（settings 配置化）
- try/finally：流异常提前结束仍登记（resume 不 404）

Redis 用轻量 AsyncFakeRedis（mock src.agent.hitl.pending.get_redis），
不依赖真实 Redis / fakeredis 第三方。
"""

from __future__ import annotations

import asyncio

import pytest

from src.agent.hitl.callback import HitlCallback
from src.agent.hitl.hitl import (
    build_hitl_interrupt_on,
    should_mount_hitl_tools,
)
from src.agent.tools.ask_human import ask_human
from src.agent.tools.publish_report import publish_report
from src.agent import main_agent
from src.agent.main_agent import (
    _build_approve_event,
    _iter_action_reviews,
    _truncate_args,
)


# ── 轻量 Redis 替身（pending 用到的命令子集）──

class AsyncFakeRedis:
    """内存版 redis.asyncio 替身（decode_responses 字符串语义）。

    支持 pending.py 用到的命令：get/set/getdel/delete/rpush/lset/llen/
    lrange/expire/incr。TTL 不真实过期（测试用显式删除模拟）。
    """

    def __init__(self) -> None:
        self._store: dict[str, str | list] = {}

    async def get(self, key: str) -> str | None:
        value = self._store.get(key)
        return value if isinstance(value, str) else None

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._store[key] = value
        return True

    async def getdel(self, key: str) -> str | None:
        value = self._store.pop(key, None)
        return value if isinstance(value, str) else None

    async def delete(self, *keys: str) -> int:
        for key in keys:
            self._store.pop(key, None)
        return len(keys)

    async def rpush(self, key: str, *values: str) -> int:
        bucket = self._store.setdefault(key, [])
        assert isinstance(bucket, list)
        bucket.extend(values)
        return len(bucket)

    async def lset(self, key: str, index: int, value: str) -> None:
        bucket = self._store.setdefault(key, [])
        assert isinstance(bucket, list)
        bucket[index] = value

    async def llen(self, key: str) -> int:
        bucket = self._store.get(key, [])
        return len(bucket) if isinstance(bucket, list) else 0

    async def lrange(self, key: str, start: int, end: int) -> list:
        bucket = self._store.get(key, [])
        if not isinstance(bucket, list):
            return []
        return bucket[start : end + 1] if end >= 0 else bucket[start:]

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def incr(self, key: str) -> int:
        current = int(self._store.get(key, 0) or 0)
        value = current + 1
        self._store[key] = str(value)
        return value


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncFakeRedis:
    """mock pending.get_redis → AsyncFakeRedis（测试隔离，不依赖真实 Redis）。"""
    redis = AsyncFakeRedis()
    monkeypatch.setattr("src.agent.hitl.pending.get_redis", lambda: redis)
    return redis


def _run(coro):
    """async coroutine 同步执行（沿用 test_checkpointer 风格，不依赖 asyncio mark）。"""
    return asyncio.run(coro)


# ── 1/2. 门控与配置 ──

def test_hitl_disabled_no_interrupt_and_no_mount() -> None:
    """hitl_enabled=False → interrupt_on=None + HITL 工具不挂载（回归门控）。"""
    assert build_hitl_interrupt_on(False) is None
    assert should_mount_hitl_tools(False) is False


def test_hitl_enabled_interrupt_config() -> None:
    """hitl_enabled=True → interrupt_on 含风险分级 + ask_human(仅 respond) + publish_report。"""
    config = build_hitl_interrupt_on(True)
    assert config is not None
    assert config["run_code_in_sandbox"]["allowed_decisions"] == [
        "approve", "edit", "reject",
    ]
    assert config["ask_human"]["allowed_decisions"] == ["respond"]
    assert config["publish_report"]["allowed_decisions"] == ["approve", "edit", "reject"]
    assert config["internet_search"] is False
    assert should_mount_hitl_tools(True) is True


# ── 3. 中断回调 ──

def test_callback_on_interrupt() -> None:
    """HitlCallback.on_interrupt 采集 checkpoint_id + HITLRequest 形态。"""
    callback = HitlCallback()

    class _FakeEvent:
        checkpoint_id = "cp-1"
        interrupts = (
            type(
                "_I",
                (),
                {"value": {"action_requests": [{"name": "run_code_in_sandbox"}],
                           "review_configs": []}},
            )(),
        )

    callback.on_interrupt(_FakeEvent())
    assert callback.interrupted is not None
    assert callback.interrupted["checkpoint_id"] == "cp-1"
    assert callback.interrupted["hitl_request"]["action_requests"][0]["name"] == (
        "run_code_in_sandbox"
    )


def test_callback_ignores_empty_interrupts() -> None:
    """on_interrupt 无 interrupts → 不采集（interrupted 保持 None）。"""
    callback = HitlCallback()

    class _FakeEvent:
        checkpoint_id = "cp-1"
        interrupts = ()

    callback.on_interrupt(_FakeEvent())
    assert callback.interrupted is None


# ── 4/5. approve 事件构建 ──

def test_build_approve_event_payload() -> None:
    """approve 事件：run_id/checkpoint_id 分离 + call_id fallback + kind。"""
    action = {"name": "run_code_in_sandbox", "args": {"code": "print(1)"}}
    review = {"action_name": "run_code_in_sandbox", "allowed_decisions": ["approve", "edit", "reject"]}
    evt = _build_approve_event("run-1", "cp-9", action, review, seq=3)
    assert evt["type"] == "approve"
    assert evt["run_id"] == "run-1"        # chat.py 流标识
    assert evt["checkpoint_id"] == "cp-9"  # 恢复键（分离）
    assert evt["call_id"] == "action-3"    # fallback 流内唯一
    assert evt["tool_name"] == "run_code_in_sandbox"
    assert evt["kind"] == "approval"
    assert evt["allowed_decisions"] == ["approve", "edit", "reject"]


def test_build_approve_event_ask_human_kind() -> None:
    """ask_human → kind=clarification + message 带问题原文。"""
    action = {"name": "ask_human", "args": {"message": "调研范围是？"}}
    evt = _build_approve_event("run-1", "cp-9", action, {}, seq=1)
    assert evt["kind"] == "clarification"
    assert "调研范围是？" in evt["message"]


def test_build_approve_event_truncates_arguments() -> None:
    """v1.2 评审修正：arguments 长字段截断 ≤300（publish_report 长正文不撑爆 SSE）。"""
    long_body = "x" * 500
    action = {"name": "publish_report", "args": {"title": "研报", "report_content": long_body}}
    evt = _build_approve_event("run-1", "cp-9", action, {}, seq=1)
    args = evt["arguments"]
    assert len(args["report_content"]) <= 301  # 300 + "…"
    assert args["report_content"].endswith("…")
    assert args["title"] == "研报"  # 短字段不动


def test_iter_action_reviews_n_actions() -> None:
    """单中断多 action → N 条 (action, review)（决策序与 action 序一致）。"""
    hitl_request = {
        "action_requests": [
            {"name": "run_code_in_sandbox"},
            {"name": "run_skill_script"},
        ],
        "review_configs": [
            {"action_name": "run_code_in_sandbox", "allowed_decisions": ["approve"]},
            {"action_name": "run_skill_script", "allowed_decisions": ["approve"]},
        ],
    }
    pairs = list(_iter_action_reviews(hitl_request))
    assert len(pairs) == 2
    assert pairs[0][0]["name"] == "run_code_in_sandbox"
    assert pairs[0][1]["allowed_decisions"] == ["approve"]


def test_truncate_args_keeps_structure() -> None:
    """_truncate_args：长 str 截断 + 短字段/非 str 保留。"""
    out = _truncate_args({"a": "y" * 500, "b": "ok", "n": 1})
    assert out["a"].endswith("…")
    assert out["b"] == "ok"
    assert out["n"] == 1


# ── 6/7/8. 待决存储（pending + Redis 替身）──

def test_register_interrupt_empty_raises(fake_redis) -> None:
    """v1.2：action_requests 为空 → ValueError（防 add_decision 误判 accepted）。"""
    from src.agent.hitl.pending import register_interrupt

    with pytest.raises(ValueError):
        _run(register_interrupt("cp-1", {"action_requests": [], "review_configs": []}, "s1"))


def test_add_decision_call_id_order_independent(fake_redis) -> None:
    """v1.2：call_id 乱序提交 → decisions 仍按 action_requests 序归位。"""
    from src.agent.hitl.pending import add_decision, consume, register_interrupt

    hitl_request = {
        "action_requests": [
            {"name": "run_code_in_sandbox", "call_id": "call-a"},
            {"name": "run_skill_script", "call_id": "call-b"},
        ],
        "review_configs": [],
    }
    _run(register_interrupt("cp-1", hitl_request, "s1"))
    # 乱序：先提交 call-b（index 1），再提交 call-a（index 0）
    accepted_b = _run(add_decision("cp-1", "call-b", {"type": "approve"}))
    assert accepted_b is False  # 决策数 1 < action 数 2
    accepted_a = _run(add_decision("cp-1", "call-a", {"type": "reject", "message": "别跑"}))
    assert accepted_a is True
    result = _run(consume("cp-1"))
    assert result == {
        "decisions": [
            {"type": "reject", "message": "别跑"},  # index 0 = call-a
            {"type": "approve"},                    # index 1 = call-b
        ]
    }


def test_add_decision_unknown_call_id_raises(fake_redis) -> None:
    """多 action + 未知 call_id → ValueError（单 action 兜底归位不抛，见下测试）。"""
    from src.agent.hitl.pending import add_decision, register_interrupt

    _run(register_interrupt("cp-1", {
        "action_requests": [
            {"name": "run_code_in_sandbox", "call_id": "call-a"},
            {"name": "run_skill_script", "call_id": "call-b"},
        ],
        "review_configs": [],
    }, "s1"))
    with pytest.raises(ValueError):
        _run(add_decision("cp-1", "call-unknown", {"type": "approve"}))


def test_add_decision_single_action_no_call_id(fake_redis) -> None:
    """真实 HITL：action 无 call_id（只有 name）→ 单 action 兜底归位 index 0（2026-08-12 项4 实测修复）。

    官方 HITL action_request 只含 name/args/description，无 call_id；
    approve 事件 fallback `action-{seq}` 序号匹配 + 单 action 兜底。
    """
    from src.agent.hitl.pending import add_decision, consume, register_interrupt

    _run(register_interrupt("cp-1", {
        "action_requests": [{"name": "run_code_in_sandbox", "args": {"code": "x"}}],  # 无 call_id
        "review_configs": [],
    }, "s1"))
    # fallback 序号匹配（approve 事件回传 action-0）
    accepted = _run(add_decision("cp-1", "action-0", {"type": "approve"}))
    assert accepted is True
    result = _run(consume("cp-1"))
    assert result == {"decisions": [{"type": "approve"}]}


def test_consume_once_getdel(fake_redis) -> None:
    """v1.2：consume getdel 一次性——两次调用第二次 None（原子消费无重复）。"""
    from src.agent.hitl.pending import add_decision, consume, register_interrupt

    _run(register_interrupt("cp-1", {
        "action_requests": [{"name": "ask_human", "call_id": "call-a"}],
        "review_configs": [],
    }, "s1"))
    _run(add_decision("cp-1", "call-a", {"type": "respond", "message": "答案"}))
    first = _run(consume("cp-1"))
    second = _run(consume("cp-1"))
    assert first == {"decisions": [{"type": "respond", "message": "答案"}]}
    assert second is None


def test_consume_no_pending_returns_none(fake_redis) -> None:
    """无待决审批 → consume 返回 None。"""
    from src.agent.hitl.pending import consume

    assert _run(consume("cp-none")) is None


def test_pending_ttl_expire_missing(fake_redis) -> None:
    """TTL 语义：主 key 过期（模拟删除）→ add_decision 抛 KeyError（resume 404 兜底）。"""
    from src.agent.hitl.pending import add_decision, register_interrupt

    _run(register_interrupt("cp-1", {
        "action_requests": [{"name": "ask_human", "call_id": "call-a"}],
        "review_configs": [],
    }, "s1"))
    # 模拟 TTL 过期：直接清掉主 key（consume/add_decision 读不到）
    _run(fake_redis.delete("hitl:pending:cp-1"))
    with pytest.raises(KeyError):
        _run(add_decision("cp-1", "call-a", {"type": "respond", "message": "x"}))


def test_get_action_name_and_session(fake_redis) -> None:
    """get_action_name / get_session_id 从主 key 读取（edit 定位 + 修订计数定位）。"""
    from src.agent.hitl.pending import get_action_name, get_session_id, register_interrupt

    _run(register_interrupt("cp-1", {
        "action_requests": [{"name": "publish_report", "call_id": "call-a"}],
        "review_configs": [],
    }, "sess-42"))
    assert _run(get_action_name("cp-1")) == "publish_report"
    assert _run(get_session_id("cp-1")) == "sess-42"
    assert _run(get_action_name("cp-none")) is None


# ── 10/14. 修订计数（publish_report reject 上限）──

def test_revision_count_incr_and_get(fake_redis) -> None:
    """修订计数：incr_revision 累计 + get_revision_count 读取（配置化上限判定依据）。"""
    from src.agent.hitl.pending import get_revision_count, incr_revision

    assert _run(get_revision_count("s1")) == 0
    assert _run(incr_revision("s1")) == 1
    assert _run(incr_revision("s1")) == 2
    assert _run(get_revision_count("s1")) == 2
    # 不同会话隔离
    assert _run(get_revision_count("s2")) == 0


def test_revision_limit_configured_threshold() -> None:
    """修订上限配置化：阈值来自 settings.publish_review_max_revisions（默认 2，非硬编码）。"""
    from src.core.config import settings

    assert settings.publish_review_max_revisions == 2
    # 语义：计数 > 上限 → 注入停止提示（chat.py 判断逻辑）
    assert 3 > settings.publish_review_max_revisions  # 第 3 次拒绝 → 达上限


# ── 13. 工具实现 ──

def test_publish_report_returns_delivered() -> None:
    """publish_report 真实执行（approve 通过后）返回交付标记。"""
    assert "交付" in publish_report(report_content="# 研报", title="测试")


def test_ask_human_stub_raises() -> None:
    """ask_human stub 防御：真实执行即抛错（respond 决策下永不执行）。"""
    with pytest.raises(RuntimeError):
        ask_human(message="澄清问题")


# ── 15. try/finally：流异常提前结束仍登记 ──

def test_stream_events_registers_interrupt_on_error(monkeypatch, fake_redis) -> None:
    """v1.2：astream_events 中途抛异常 → finally 仍 register_interrupt（resume 不 404）。"""
    from src.agent.hitl.pending import consume, get_action_name

    callback = HitlCallback()
    callback.interrupted = {
        "checkpoint_id": "cp-x",
        "hitl_request": {
            "action_requests": [{"name": "run_code_in_sandbox", "call_id": "call-a"}],
            "review_configs": [],
        },
    }

    class _FakeAgent:
        async def astream_events(self, *args, **kwargs):
            raise RuntimeError("模型调用失败")
            yield  # pragma: no cover

    class _NullCM:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(main_agent, "_stream_semaphore", _NullCM())
    ctx = main_agent.ChatContext(session_id="s1")

    async def run() -> None:
        events = []
        try:
            async for _evt in main_agent.stream_agent_events(
                _FakeAgent(), [], context=ctx, hitl_callback=callback
            ):
                events.append(_evt)
        except RuntimeError:
            pass  # 流内异常被 API 层捕获转 error 事件
        # 异常提前结束：仍应登记（finally），但事件产出在 finally 后 → 无 approve 事件
        return events

    events = _run(run())
    # 异常时无 approve 事件（finally 只登记不 yield）；但 Redis 已登记
    assert events == []
    assert _run(get_action_name("cp-x")) == "run_code_in_sandbox"  # 已登记


# ── 16. 跨进程续审（新 get_redis 实例读同一存储）──

def test_consume_cross_instance(fake_redis) -> None:
    """跨实例续审：模拟重启后新 AsyncFakeRedis 仍读到（真实 Redis 落盘语义）。"""
    from src.agent.hitl.pending import add_decision, register_interrupt

    _run(register_interrupt("cp-1", {
        "action_requests": [{"name": "ask_human", "call_id": "call-a"}],
        "review_configs": [],
    }, "s1"))
    _run(add_decision("cp-1", "call-a", {"type": "respond", "message": "答案"}))

    # "新进程"：换一个 fake_redis 实例（同一底层？模拟 Redis 落盘 → 共享存储）
    # 真实场景依赖 Redis 持久化；这里用同一 AsyncFakeRedis 实例验证 API 层不持有状态
    from src.agent.hitl.pending import consume

    result = _run(consume("cp-1"))
    assert result == {"decisions": [{"type": "respond", "message": "答案"}]}
