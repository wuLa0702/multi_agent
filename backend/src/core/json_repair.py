"""LLM 输出 JSON 的语法兜底解析（**只修语法，不改语义**）。

## 为什么需要

LLM 产出的 JSON 经常有语法瑕疵：尾逗号、单引号、Markdown 代码块包裹、
输出被截断。`json.loads` 对此一律抛 `JSONDecodeError` → **一次调用直接失败**。
本模块在严格解析失败后用第三方 `json-repair` 兜底。

依据：`.claude/rules/07-tool-center.md` §3 ——「协议字段校验失败即报错，不做修复
（**修复只适用内容里的 LLM 产物**）」；`.claude/rules/08-dependency-policy.md` §1
—— 通用能力优先第三方。

## 边界（重要）

| ✅ 修 | ❌ 不修 |
|---|---|
| 补括号 / 去尾逗号 / 换单引号 / 剥代码块 / 补截断 | **字段补全 / 类型转换 / 单位归一 / 控制字符** |
| **模型产出的** JSON | **我们自己写的** JSON（DB 行 / Redis body）——那些坏了是真 bug，必须炸 |

## 为什么不能静默

修复成功会打 `warning` 日志（`trace_id` 由 B9 自动注入，可直接对到审计底账）。
静默修复会把上游 bug（prompt 写坏 / 输出截断）永久藏起来。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import json_repair

from src.core.errors import AppError

logger = logging.getLogger(__name__)

#: `json-repair` 对"完全不是 JSON"的输入返回**空字符串**（实测）。
#: 合法的 JSON 空串 `""` 会在**严格解析阶段**就成功，不会走到兜底分支，
#: 故这里可以放心把空串当作失败信号。
_REPAIR_FAILED = ""

#: 日志回显的原文长度上限（防超长文本刷屏）
_RAW_PREVIEW = 80


class JsonSyntaxError(AppError):
    """两轮都失败：不是 JSON，修复也救不回来（不可重试）。

    Attributes:
        raw_error: 原始 `JSONDecodeError` 的字符串形式（排障用）
    """

    def __init__(self, message: str, *, raw_error: str = "") -> None:
        super().__init__(message, code="INVALID_JSON", category="non-retryable")
        self.raw_error = raw_error


@dataclass(frozen=True)
class JsonParseResult:
    """解析结果。调用方据 `repaired` 决定是否降级。

    Attributes:
        value: 解析出的 Python 对象
        repaired: 是否走了 `json-repair` 兜底（True = 原文语法非法，被修过）
        raw_error: 原始解析错误摘要（`repaired=True` 时有值）
    """

    value: Any
    repaired: bool = False
    raw_error: str = ""


def loads(raw: str) -> JsonParseResult:
    """解析 JSON 文本；语法非法时用 `json-repair` 兜底。

    **三段式**：严格解析 → 兜底修复 → 失败抛错。绝大多数输入走第一段，零开销。

    Args:
        raw: JSON 文本（通常来自 LLM 输出）

    Returns:
        `JsonParseResult`；`repaired=True` 表示走过兜底修复

    Raises:
        JsonSyntaxError: 严格解析失败**且**修复结果不可用
    """
    try:
        return JsonParseResult(value=json.loads(raw))
    except json.JSONDecodeError as exc:
        first_error = exc

    repaired = json_repair.loads(raw)
    if repaired is None or repaired == _REPAIR_FAILED:
        raise JsonSyntaxError(
            f"JSON 解析失败且无法修复：第 {first_error.lineno} 行"
            f"第 {first_error.colno} 列 {first_error.msg}",
            raw_error=str(first_error),
        ) from first_error

    logger.warning(
        "JSON 语法修复成功（%s）；原文前 %d 字：%s",
        first_error,
        _RAW_PREVIEW,
        raw[:_RAW_PREVIEW],
    )
    return JsonParseResult(value=repaired, repaired=True, raw_error=str(first_error))
