"""通用工具域测试：calculate / current_time / json_extract（2026-10-16 新增）。

这三个既是**能用的工具**，也是**模板**（三种实现粒度各一）：

| 工具 | 形态 | 本文件覆盖 |
|------|------|-----------|
| `current_time` | 最简骨架 | 正常 / 指定时区 / 非法时区 |
| `calculate` | 纯函数 + 严格校验 | 正常 / 优先级 / 除零 / **注入尝试** / 超大指数 |
| `json_extract` | 完整处理链 | 正常 / 数组下标 / 缺键提示 / 非法 JSON / 超长降级 |

规则 20-testing：正常 / 边界 / 错误三类齐备。
"""

from __future__ import annotations

import pytest

from src.core.errors import ToolErrorCode
from src.tools.impl.calc import calculate
from src.tools.impl.clock import current_time
from src.tools.impl.json_extract import json_extract


# ── calculate ──────────────────────────────────────────────────────────────


class TestCalculate:
    def test_basic_arithmetic(self) -> None:
        """正常路径：四则运算结果正确。"""
        result = calculate("(1 + 2) * 3")
        assert result.status == "ok"
        assert result.data["result"] == 9
        assert result.message == "(1 + 2) * 3 = 9"

    def test_operator_precedence_and_power(self) -> None:
        """正常路径：优先级与幂运算（2**10 = 1024，不是 2*10）。"""
        assert calculate("2 + 3 * 4").data["result"] == 14
        assert calculate("2**10").data["result"] == 1024
        assert calculate("7 // 2").data["result"] == 3
        assert calculate("-5 + 2").data["result"] == -3

    def test_integer_result_has_no_trailing_zero(self) -> None:
        """边界：整数值不显示 `.0`（4/2 → "2" 而非 "2.0"）。"""
        assert calculate("4 / 2").message.endswith("= 2")

    def test_division_by_zero_is_error_envelope(self) -> None:
        """错误路径：除零 → error 信封（不抛异常）。"""
        result = calculate("1 / 0")
        assert result.status == "error"
        assert result.error_code == ToolErrorCode.INVALID_ARG
        assert "除数" in result.message

    @pytest.mark.parametrize(
        "payload",
        [
            "__import__('os').system('echo pwned')",  # 函数调用
            "open('/etc/passwd')",  # 函数调用
            "a + 1",  # 变量（Name 节点）
            "'abc' + 'def'",  # 字符串字面量
            "[1, 2][0]",  # 下标
            "1 if 1 else 2",  # 三元表达式
        ],
    )
    def test_non_whitelisted_syntax_rejected(self, payload: str) -> None:
        """错误路径（安全）：白名单之外的语法一律拒绝 —— **绝不 eval**。"""
        result = calculate(payload)
        assert result.status == "error"
        assert result.error_code == ToolErrorCode.INVALID_ARG

    def test_huge_exponent_rejected(self) -> None:
        """边界（防 DoS）：指数超上限 → error，不会把进程算死。"""
        result = calculate("9**9999")
        assert result.status == "error"
        assert "指数" in result.message

    def test_empty_expression(self) -> None:
        """边界：空表达式 → error 信封。"""
        assert calculate("   ").status == "error"


# ── current_time ───────────────────────────────────────────────────────────


class TestCurrentTime:
    def test_local_timezone(self) -> None:
        """正常路径：不传时区 → 用本机时区，返回 ok + 结构化字段。"""
        result = current_time()
        assert result.status == "ok"
        assert result.data["iso"]
        assert result.data["date"]
        assert result.data["weekday"]

    def test_explicit_timezone(self) -> None:
        """正常路径：指定 IANA 时区 → 返回该时区时间，且带时区名。"""
        result = current_time("Asia/Shanghai")
        assert result.status == "ok"
        assert "Asia/Shanghai" in result.data["timezone"]
        assert result.data["iso"].endswith("+0800")

    def test_unknown_timezone_is_error(self) -> None:
        """错误路径：非法时区名 → error 信封（附可用写法提示）。"""
        result = current_time("Mars/Olympus")
        assert result.status == "error"
        assert result.error_code == ToolErrorCode.INVALID_ARG
        assert "IANA" in result.message


# ── json_extract ───────────────────────────────────────────────────────────

_SAMPLE = '{"results": [{"title": "甲", "tags": ["x", "y"]}, {"title": "乙"}], "total": 2}'


class TestJsonExtract:
    def test_nested_key(self) -> None:
        """正常路径：点号取嵌套键。"""
        result = json_extract(_SAMPLE, "results[0].title")
        assert result.status == "ok"
        assert result.data["value"] == "甲"

    def test_array_index_chain(self) -> None:
        """正常路径：数组下标可链式（results[0].tags[1]）。"""
        assert json_extract(_SAMPLE, "results[0].tags[1]").data["value"] == "y"

    def test_empty_path_returns_whole_document(self) -> None:
        """边界：空路径 → 返回整个文档。"""
        result = json_extract(_SAMPLE, "")
        assert result.status == "ok"
        assert result.data["value"]["total"] == 2

    def test_missing_key_hints_available_keys(self) -> None:
        """错误路径：键不存在 → error 且**列出可用键**（LLM 据此自我纠正）。"""
        result = json_extract(_SAMPLE, "results[0].nope")
        assert result.status == "error"
        assert result.error_code == ToolErrorCode.NOT_FOUND
        assert "title" in result.message, "应提示该层可用键"

    def test_index_out_of_range(self) -> None:
        """错误路径：下标越界 → error，提示当前长度。"""
        result = json_extract(_SAMPLE, "results[9]")
        assert result.status == "error"
        assert "越界" in result.message

    def test_invalid_json_points_at_position(self) -> None:
        """错误路径：JSON 语法错 → 报行列，不是一句泛泛的 invalid。"""
        result = json_extract('{"a": 1,}', "")
        assert result.status == "error"
        assert "第" in result.message and "列" in result.message

    def test_invalid_path_syntax(self) -> None:
        """错误路径：路径语法非法（空段 / 非数字下标）。"""
        assert json_extract(_SAMPLE, "a..b").status == "error"
        assert json_extract(_SAMPLE, "a[x]").status == "error"

    def test_oversized_result_is_degraded(self) -> None:
        """边界：结果超长 → degraded（明确"不完整"，而不是假装没事）。"""
        big = '{"blob": "' + "x" * 5000 + '"}'
        result = json_extract(big, "")
        assert result.status == "degraded"
        assert result.data["truncated"] is True
