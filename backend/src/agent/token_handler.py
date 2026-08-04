"""Token 用量统计：自定义 CallbackHandler（2026-08-04 P2 核心学习点）。

评审拍板：官方标准扩展方式（BaseCallbackHandler），不侵入 deepagents 底层源码。
- on_llm_end 拦截每次模型调用的 token_usage（prompt_tokens / completion_tokens）
- 实例按请求创建（一次 run 一个 handler），流结束由 API 层读取累计值
- 挂载方式：astream_events 的 config callbacks（LangGraph 会传播给内部模型链）

流程：LLM 调用 → on_llm_end → 累加 → API 层读取 → SSE done 事件携带 → 前端渲染
"""

from __future__ import annotations

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


class TokenUsageHandler(BaseCallbackHandler):
    """统计一次 run 的 token 消耗（prompt + completion 累加）。"""

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0

    @property
    def total_tokens(self) -> int:
        """本轮累计总消耗（prompt + completion）。"""
        return self.prompt_tokens + self.completion_tokens

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:  # noqa: ARG002
        """每次模型调用结束回调：解析 OpenAI 兼容 token_usage 并累加。

        注意：多轮 agent 循环（ReAct）每次模型调用都会触发，
        这里做累加而非覆盖——得到一次 run 的总消耗。
        """
        if not response.llm_output:
            return
        usage = response.llm_output.get("token_usage") or {}
        self.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
