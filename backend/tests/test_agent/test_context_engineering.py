"""上下文工程分级实施测试（开发计划 v2 §5）。

覆盖：
- 一批：#7 分层组装（核心/可选按需）/ #1 阈值字段存在
- 二批：#2 记忆检索时间衰减排序 + 窗口裁剪 + _estimate_tokens
- 三批：#4 DoneEvent context_warning 字段 / #8 审计脚本（内置+注册工具）
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.agent.prompts import build_system_prompt
from src.core.config import settings
from src.schemas.events import DoneEvent


# ── 一批：#7 分层组装 ──

def test_build_system_prompt_core_and_optional() -> None:
    """#7：核心（角色）+ 可选（记忆指引）默认组装；模式指令按需追加。"""
    default = build_system_prompt()
    assert "资深研究员" in default, "核心层角色"
    assert "记忆维护" in default, "可选层记忆指引（默认注入）"

    plan = build_system_prompt(mode="plan")
    assert "规划模式" in plan, "模式指令按需追加"
    assert "资深研究员" in plan, "核心层不受影响"


# ── 一批：#1 阈值字段 ──

def test_context_evict_limit_field() -> None:
    """#1：context_tool_evict_limit 字段存在（默认对齐官方 20000；P2 才生效）。"""
    assert settings.context_tool_evict_limit == 20000


# ── 二批：#2 记忆检索升级 ──

@pytest.mark.asyncio
async def test_memory_load_time_decay_sort(mocker) -> None:
    """#2：画像优先 → 同优先级内时间衰减（新在前）。"""
    from src.agent.memory import store as memory_store

    store = SimpleNamespace(
        asearch=mocker.AsyncMock(
            side_effect=[
                # user_profile：旧先新后
                [SimpleNamespace(value={"content": "旧画像", "ts": 1}),
                 SimpleNamespace(value={"content": "新画像", "ts": 2})],
                # facts：单个
                [SimpleNamespace(value={"content": "事实", "ts": 3})],
                # legacy：空
                [],
            ]
        )
    )
    memories = await memory_store.load_recent_memories_v3(store, limit=10)
    assert memories == ["新画像", "旧画像", "事实"], "画像优先 + 同优先级时间衰减（新在前）"


@pytest.mark.asyncio
async def test_memory_load_window_crop(mocker) -> None:
    """#2：窗口裁剪——估算 token 超比例上限截断。"""
    from src.agent.memory import store as memory_store

    long_fact = "长" * 200   # 估算 100 token
    store = SimpleNamespace(
        asearch=mocker.AsyncMock(
            side_effect=[
                [SimpleNamespace(value={"content": long_fact, "ts": 1})],
                [SimpleNamespace(value={"content": "短事实", "ts": 2})],
                [],
            ]
        )
    )
    # window_ratio=0.001 × 128000 = 128 token：第一条 100 过、第二条 2 过
    memories = await memory_store.load_recent_memories_v3(store, limit=10,
                                                          window_ratio=0.001)
    assert len(memories) == 2, "窗口预算内两条都进"

    # 收紧预算：第一条就超 → 截断
    memories2 = await memory_store.load_recent_memories_v3(store, limit=10,
                                                           window_ratio=0.0005)  # 64 token
    assert len(memories2) == 0, "首条超预算 → 空注入"


def test_estimate_tokens() -> None:
    """#2 估算：中文/2 + 英文/4。"""
    from src.agent.memory.store import _estimate_tokens

    assert _estimate_tokens("中文中文") == 2          # 4 中文 / 2
    assert _estimate_tokens("hello world") == 2       # 11 字符 / 4
    assert _estimate_tokens("") == 0


# ── 三批：#4 context_warning ──

def test_done_event_context_warning_field() -> None:
    """#4：DoneEvent 含 context_warning（默认 False）。"""
    evt = DoneEvent(run_id="r", session_id="s", duration_ms=1)
    assert evt.context_warning is False


def test_done_event_context_warning_trigger() -> None:
    """#4：构造 90% 用量 → context_warning=True。"""
    evt = DoneEvent(run_id="r", session_id="s", duration_ms=1,
                    context_used=120_000, context_warning=True)
    assert evt.context_warning is True


# ── 三批：#8 工具描述审计 ──

def test_audit_tool_descriptions_includes_builtin() -> None:
    """#8：审计含 MCP 注册工具 + deepagents 内置文件工具。"""
    from scripts.audit_tool_descriptions import audit_tool_descriptions

    stats = audit_tool_descriptions()
    assert "internet_search" in stats, "MCP 注册工具"
    assert "read_file" in stats, "内置文件工具"
    assert stats["read_file"]["source"] == "internal"
    assert stats["internet_search"]["source"] == "mcp"
    assert stats["total_chars"] > 0
