"""LLM 输出 JSON 的语法兜底解析（`core/json_repair.py`）。

覆盖（规则 20-testing：正常 / 边界 / 错误）：
1. **正常**：合法 JSON → 严格解析，`repaired=False`（零开销路径）
2. **修复**：尾逗号 / 单引号 / Markdown 包裹 / 截断 / 未闭合字符串 → `repaired=True`
3. **错误**：纯垃圾 / 空串 / 纯空白 → 抛 `JsonSyntaxError`（不能被"修"成字符串）
4. **边界**：合法空串 `""` → 走严格路径（证明"修复返回空串=失败"的判定不误伤）
5. **集成**：`json_extract` 修复过 → `degraded`
6. **边界守卫**：我们自己写的 JSON（DB / Redis）不得使用本模块

依据：`docs/临时/2026-10-16-汇总问题-v1.md` **B15**。
"""

from __future__ import annotations

import pytest

from src.core.json_repair import JsonParseResult, JsonSyntaxError, loads
from src.tools.impl.json_extract import json_extract


# ── 1. 正常路径：严格解析 ──────────────────────────────────────────────────


def test_valid_json_takes_strict_path() -> None:
    """合法 JSON → `repaired=False`（走 json.loads，不触发兜底）。"""
    result = loads('{"a": 1, "b": [2, 3]}')
    assert isinstance(result, JsonParseResult)
    assert result.repaired is False
    assert result.value == {"a": 1, "b": [2, 3]}


# ── 2. 修复路径（参数化）──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1,}', {"a": 1}),                       # 尾逗号
        ("{'a': 1}", {"a": 1}),                        # 单引号
        ('```json\n{"a": 1}\n```', {"a": 1}),          # Markdown 代码块
        ('{"a": {"b": 1', {"a": {"b": 1}}),            # 截断（补右括号）
        ('{"a": "abc}', {"a": "abc"}),                 # 未闭合字符串
    ],
)
def test_syntax_issues_are_repaired(raw: str, expected: dict) -> None:
    """语法瑕疵 → 修复成功，且 `repaired=True`（调用方据此降级）。"""
    result = loads(raw)
    assert result.repaired is True
    assert result.value == expected
    assert result.raw_error, "修复时应保留原始解析错误摘要"


# ── 3. 错误路径：修不了就抛 ───────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["not json at all", "", "   \n\t "])
def test_unrepairable_raises(raw: str) -> None:
    """完全不是 JSON → `JsonSyntaxError`，**不得**被"修"成字符串。"""
    with pytest.raises(JsonSyntaxError):
        loads(raw)


def test_error_carries_raw_reason() -> None:
    """异常里带原始解析错误摘要（排障用）。"""
    with pytest.raises(JsonSyntaxError) as excinfo:
        loads("这不是 JSON")
    assert excinfo.value.raw_error
    assert excinfo.value.category == "non-retryable"


# ── 4. 边界：合法空串不能误判 ─────────────────────────────────────────────


def test_legal_empty_string_is_not_a_failure() -> None:
    """合法 JSON `""` → 严格解析成功（空串≠失败，只有"修复返回空串"才是失败）。"""
    result = loads('""')
    assert result.repaired is False
    assert result.value == ""


# ── 5. 集成：json_extract 修复过 → degraded ───────────────────────────────


def test_json_extract_ok_when_clean() -> None:
    """干净 JSON → `ok`，`repaired=False`。"""
    result = json_extract('{"a": 1}', "a")
    assert result.status == "ok"
    assert result.data["repaired"] is False
    assert result.data["value"] == 1


def test_json_extract_degraded_when_repaired() -> None:
    """语法被修过 → `degraded`（提示 LLM：数据不完全可信）。"""
    result = json_extract('{"a": 1,}', "a")
    assert result.status == "degraded"
    assert result.data["repaired"] is True
    assert result.data["value"] == 1


def test_json_extract_error_when_unrepairable() -> None:
    """修不了 → `error` 信封（不抛异常，走既有错误码口径）。"""
    result = json_extract("not json", "")
    assert result.status == "error"
    assert result.error_code == "invalid_arg"
    assert "解析失败" in result.message


# ── 6. 边界守卫：不修"我们自己写的" JSON ──────────────────────────────────


def test_internal_json_sources_do_not_use_repair() -> None:
    """DB / Redis 里的 JSON 是我们自己写的 —— 坏了必须炸，**不接修复**。

    否则会把上游 bug（写坏数据 / 序列化出错）永久掩盖。
    """
    from pathlib import Path

    for relative in ("backend/src/agent/hitl/pending.py", "backend/src/tools/channels/mcp_client.py"):
        source = Path(relative).read_text(encoding="utf-8")
        assert "json_repair" not in source, f"{relative} 不应使用 json_repair（内部数据必须严格解析）"
