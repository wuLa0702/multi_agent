"""Token 用量统计中间件：图执行完成自动计算全量消息 token 并存库。

2026-08-04 评审改版（替代 CallbackHandler 方案）：
- 嵌入 DeepAgent 中间件栈（create_deep_agent middleware 列表），
  `aafter_agent` 钩子在每次图执行（含 ReAct 多轮）结束后触发
- state["messages"] 是**当前会话全量消息**（含历史）——算的是"当前上下文占用"，
  语义上正是前端进度条要显示的值（CallbackHandler 算的是"本轮消耗"，语义不符）
- 存库（sessions.context_used）→ 前端直接查表，无需流式结束手动读取
- token 估算：chars/4（评审拍板近似，后续可换真实 tokenizer）

⚠️ 必须实现 async 版（aafter_agent）：项目走 astream 异步上下文，
sync 钩子（after_agent）在异步上下文不会触发（与 _configurable_model 同款教训）。
"""

from __future__ import annotations

import logging

from langchain.agents.middleware import AgentMiddleware

logger = logging.getLogger(__name__)

# 上下文上限（评审拍板常量；后续可接 models 表 context_window 字段）
DEFAULT_CONTEXT_WINDOW = 128_000

# chars/4 近似估算（中英文混合约 4 字符 ≈ 1 token）
_CHARS_PER_TOKEN = 4.0


class TokenUsageMiddleware(AgentMiddleware):
    """上下文用量统计中间件（编译时单例，session 从 runtime.context 取）。

    Attributes:
        context_window: 上下文上限（默认 128k）
    """

    def __init__(self, context_window: int = DEFAULT_CONTEXT_WINDOW) -> None:
        super().__init__()
        self.context_window = context_window

    async def aafter_agent(self, state, runtime) -> None:
        """图执行结束钩子：计算全量消息 token 并写入 sessions.context_used。

        Args:
            state: AgentState——messages 为当前会话全量消息（含历史）
            runtime: Runtime——context 携带请求级 ChatContext（含 session_id）

        Returns:
            None（直接落库，不改 state）
        """
        try:
            messages = state.get("messages") or []
            used = int(sum(len(getattr(m, "content", "") or "") for m in messages) / _CHARS_PER_TOKEN)

            # session_id 从请求级 context 取（中间件是编译时单例，不能存实例属性）
            context = getattr(runtime, "context", None)
            session_id = getattr(context, "session_id", None) if context is not None else None
            if not session_id:
                logger.debug("TokenUsageMiddleware: 无 session_id，跳过落库")
                return

            await _save_context_used(session_id, used, self.context_window)
        except Exception:  # noqa: BLE001 —— 统计是旁路能力，失败不阻断对话
            logger.exception("TokenUsageMiddleware: 用量落库失败（不影响对话）")


async def _save_context_used(session_id: str, used: int, total: int) -> None:
    """把用量写入 sessions 表（连接自开自关，避开请求连接生命周期）。"""
    from src.core import db as core_db

    conn = await core_db.get_connection()
    try:
        await conn.execute(
            "UPDATE sessions SET context_used = ? WHERE id = ?",
            (min(used, total), session_id),
        )
        await conn.commit()
    finally:
        await conn.close()
