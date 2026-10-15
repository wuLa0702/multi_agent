"""出站脱敏（阶段 3，2026-10-15）：发往远程 LLM 前把敏感信息替换掉。

## 为什么落点改了（原设计前提是错的）

规则 `07-tool-center` §4 原写「出站脱敏 → `llm/adapter.py`」。**实测推翻**：

- `LLMAdapter.chat()` 只被两处使用——生成会话标题（`agent/tasks/assistant.py`）、
  记忆抽取（`agent/memory/store.py`）
- **主 Agent 的对话走 `get_chat_model()` → langchain agent loop**，
  **不经过 `LLMAdapter`**

→ 若只在 adapter 脱敏，**主对话完全没脱**，而它恰是用户内容流向远程 LLM 的主通道。

## 正确落点：两个接入点，一个纯函数

| 路径 | 接入点 | 覆盖 |
|---|---|---|
| **主对话**（主通道） | `RedactMiddleware.awrap_model_call`（模型调用边界收口） | 主 agent 每一轮模型调用 |
| **辅助调用** | `LLMAdapter.chat()` 调用本模块 `redact()` | 标题生成 / 记忆抽取 |

脱敏逻辑本身只写一份（`redact()`），两个接入点都调它——**禁各写一套**。

## 边界（本模块不做）

- ❌ 脱敏**入站**内容（模型回复）
- ❌ 改写**存储**（历史消息照原样落库，只处理**即将出站**的这一份）
- ❌ 脱敏工具内部处理（那是工具的事，如审计的 `code → code_len`）
- ❌ 脱**绝对路径**（路径是任务上下文，脱了模型看不懂在说哪个文件——co-creator 2026-10-15 拍板）
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain.agents.middleware import AgentMiddleware

logger = logging.getLogger(__name__)

# ── 规则表（唯一载体；新增规则只改这里）────────────────────────────
# 顺序：先长且特征强的模式（密钥），再身份类。替换后的掩码不含数字/@，
# 故不会与其他规则互相吞噬 → redact() 幂等。
_MASK = "[已脱敏:{label}]"

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 密钥 / Token（三类写法：AWS / OpenAI 风格 / HTTP Bearer）
    ("KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("KEY", re.compile(r"sk-[A-Za-z0-9_\-]{16,}")),
    ("KEY", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}")),
    # 身份证（18 位，末位可为 X）——边界断言防切碎长数字串
    ("ID", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    # 手机号（11 位，1 开头 + 3-9）
    ("PHONE", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    # 邮箱
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
)


def redact(text: str) -> tuple[str, dict[str, int]]:
    """把文本里的敏感信息替换为掩码（**底层函数，按规范豁免**：纯文本处理）。

    Args:
        text: 待处理的原文

    Returns:
        `(脱敏后文本, {标签: 命中次数})`——计数供调用方记日志（**日志只记条数
        与类别，不记原文**，否则日志本身成泄漏源）。无命中时计数为空 dict
    """
    hits: dict[str, int] = {}
    out = text
    for label, pattern in _RULES:
        out, count = pattern.subn(_MASK.format(label=label), out)
        if count:
            hits[label] = hits.get(label, 0) + count
    return out, hits


def redact_message_content(content: Any) -> tuple[Any, dict[str, int]]:
    """按消息内容形态脱敏（str 直脱；list[block] 逐块脱 text 字段）。

    langchain 消息的 `content` 可能是 `str`，也可能是 content-block 列表
    （多模态）。非文本形态原样返回、不计数——**不猜结构**。

    Args:
        content: 消息的 content 字段

    Returns:
        `(处理后的 content, 命中计数)`
    """
    if isinstance(content, str):
        return redact(content)
    if isinstance(content, list):
        merged: dict[str, int] = {}
        blocks: list[Any] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                new_text, hits = redact(block["text"])
                block = {**block, "text": new_text}
                for key, count in hits.items():
                    merged[key] = merged.get(key, 0) + count
            blocks.append(block)
        return blocks, merged
    return content, {}


def _summarize_hits(hits: dict[str, int]) -> str:
    """命中计数 → 日志片段（只类别 + 条数）。"""
    return ", ".join(f"{label}×{count}" for label, count in sorted(hits.items()))


class RedactMiddleware(AgentMiddleware):
    """出站脱敏中间件（**主对话路径**）：模型调用前对消息文本脱敏。

    为什么必须在这里而不是 adapter：主 Agent 的模型调用不经 `LLMAdapter.chat()`
    （见模块 docstring）。`awrap_model_call` 是模型调用边界唯一的收口点——
    一处接入即覆盖主 agent 的每一轮模型调用。

    旁路纪律：脱敏失败**不得阻断对话**（降级为原文出站 + error 日志），
    与 trace / 审计同款——横切能力绝不冒泡。
    """

    async def awrap_model_call(self, request, handler):  # noqa: ANN001 - 框架签名
        """按开关脱敏入站消息，再交 handler 执行模型调用。"""
        try:
            from src.core.config import settings

            if not settings.redact_enabled:
                return await handler(request)
            messages = getattr(request, "messages", None) or []
            count = 0
            redacted: list[Any] = []
            for message in messages:
                content = getattr(message, "content", None)
                new_content, hits = redact_message_content(content)
                if hits:
                    count += sum(hits.values())
                    message = message.model_copy(update={"content": new_content})
                redacted.append(message)
            if not count:
                return await handler(request)
            logger.info("出站脱敏：%d 处", count)
            return await handler(request.override(messages=redacted))
        except Exception:  # noqa: BLE001 —— 横切能力旁路，失败不阻断对话
            logger.error("出站脱敏失败（按原文出站，不阻断）", exc_info=True)
            return await handler(request)
