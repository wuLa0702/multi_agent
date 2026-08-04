"""轻量辅助任务测试（标题生成，2026-08-04：LLM 单次调用 + 失败降级）。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 有价值：fake LLM 返回标题 → 返回标题（截断 ≤20 字）
- 无价值：空输出 → None
- 异常：LLM 抛错 → 由调用方容错（generate_title 不吞异常，抛给上层）
"""

from __future__ import annotations

import pytest

from src.llm.adapter import LLMAdapter


class _FakeLLM:
    """fake LLM：返回预设内容。"""

    def __init__(self, content: str, raise_error: bool = False) -> None:
        self._content = content
        self._raise = raise_error

    async def ainvoke(self, messages):
        if self._raise:
            raise RuntimeError("llm down")
        return type("R", (), {"content": self._content})()


def _adapter(content: str = "", raise_error: bool = False) -> LLMAdapter:
    """LLMAdapter(model=fake) 注入（统一走 adapter.chat 的真实路径）。"""
    return LLMAdapter(model=_FakeLLM(content, raise_error))


@pytest.mark.asyncio
async def test_generate_title_valuable() -> None:
    """正常：fake LLM 返回标题 → 返回清洗后的标题。"""
    from src.agent.assistant_tasks import generate_title

    title = await generate_title(_adapter('"如何学习 LangGraph"'), "如何学习 LangGraph，有什么路线吗？")
    assert title == "如何学习 LangGraph"


@pytest.mark.asyncio
async def test_generate_title_empty() -> None:
    """边界：LLM 空输出 → None（调用方回退规则截断）。"""
    from src.agent.assistant_tasks import generate_title

    title = await generate_title(_adapter(""), "测试消息")
    assert title is None


@pytest.mark.asyncio
async def test_generate_title_truncated() -> None:
    """边界：超长标题截断 ≤20 字。"""
    from src.agent.assistant_tasks import TITLE_MAX_LEN, generate_title

    long_title = "这是一个非常非常非常非常非常长的会话标题用来测试截断逻辑"
    title = await generate_title(_adapter(long_title), "测试")
    assert len(title) <= TITLE_MAX_LEN


@pytest.mark.asyncio
async def test_generate_title_llm_error_propagates() -> None:
    """错误：LLM 异常向上抛（由调用方 _generate_title_in_background 容错回退）。"""
    from src.agent.assistant_tasks import generate_title

    with pytest.raises(RuntimeError):
        await generate_title(_adapter(raise_error=True), "测试")
