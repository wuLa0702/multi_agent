"""core/errors.py 单测：异常四分类（计划-容错处理 v1.2，P1-a）+ 工具归一错误码（阶段 2.1）。

覆盖：四分类 category / 错误码 / retryable 兼容属性 / 判定口诀边界；
工具错误码取值规范 / 可重试集合与设计一致。
"""

from __future__ import annotations

import re

import pytest

from src.core.errors import (
    RETRYABLE_TOOL_ERRORS,
    AppError,
    BusinessError,
    ConfigError,
    NonRetryableError,
    RetryableError,
    SystemError,
    ToolErrorCode,
    is_retryable_tool_error,
)


class TestErrorCategories:
    """四分类 category + 错误码。"""

    def test_retryable_category(self) -> None:
        err = RetryableError("网络超时")
        assert err.category == "retryable"
        assert err.retryable is True
        assert err.code == "RETRYABLE"

    def test_non_retryable_category(self) -> None:
        err = NonRetryableError("参数错误")
        assert err.category == "non-retryable"
        assert err.retryable is False
        assert err.code == "BAD_REQUEST"

    def test_business_category(self) -> None:
        """业务异常（v1.2 新增）：规则限制，改了输入也不一定过。"""
        err = BusinessError("每日调用次数用完")
        assert err.category == "business"
        assert err.retryable is False
        assert err.code == "BUSINESS"

    def test_system_category(self) -> None:
        """系统异常（v1.2 新增）：未知内部错误，不暴露细节。"""
        err = SystemError("未预期异常")
        assert err.category == "system"
        assert err.retryable is False
        assert err.code == "INTERNAL"

    def test_config_error_subclass(self) -> None:
        """ConfigError 归属不可重试。"""
        err = ConfigError("LLM API Key 未配置")
        assert isinstance(err, NonRetryableError)
        assert err.category == "non-retryable"
        assert err.code == "CONFIG_ERROR"


class TestAppErrorCompatibility:
    """retryable 参数向后兼容（旧代码传 True/False 不破）。"""

    def test_legacy_retryable_true(self) -> None:
        """旧代码只传 retryable=True（不传 category）→ 映射可重试。"""
        err = AppError("x", retryable=True)
        assert err.category == "retryable"
        assert err.retryable is True

    def test_legacy_retryable_false(self) -> None:
        """旧代码只传 retryable=False → 映射不可重试。"""
        err = AppError("x", retryable=False)
        assert err.category == "non-retryable"
        assert err.retryable is False

    def test_default_system(self) -> None:
        """默认 category=system（未知错误兜底）。"""
        err = AppError("裸异常")
        assert err.category == "system"
        assert err.retryable is False

    def test_category_wins_over_retryable(self) -> None:
        """显式 category 优先于 retryable（设计 §5.1）。"""
        err = AppError("x", category="business", retryable=True)
        assert err.category == "business"
        assert err.retryable is False


class TestBoundarySamples:
    """边界判定口诀示例（v1.2 评审明确）。"""

    def test_business_vs_non_retryable(self) -> None:
        """'次数用尽'（业务，等额度）vs '参数格式错'（不可重试，改参数）——分类不同。"""
        quota_exhausted = BusinessError("调用次数用完")
        bad_param = NonRetryableError("参数格式错")
        assert quota_exhausted.category == "business"
        assert bad_param.category == "non-retryable"

    def test_isinstance_hierarchy(self) -> None:
        """异常分级可 isinstance 匹配（降级策略分发用）。"""
        assert isinstance(RetryableError("x"), AppError)
        assert isinstance(BusinessError("x"), AppError)
        assert isinstance(SystemError("x"), AppError)
        # BusinessError 不应被当作 NonRetryable（语义区分）
        assert not isinstance(BusinessError("x"), NonRetryableError)
        assert not isinstance(SystemError("x"), RetryableError)


def _declared_codes() -> dict[str, str]:
    """取出 `ToolErrorCode` 上声明的全部错误码（排除 dunder）。"""
    return {k: v for k, v in vars(ToolErrorCode).items() if not k.startswith("_")}


class TestToolErrorCode:
    """工具归一错误码（阶段 2.1）：取值规范 + 可重试映射与设计一致。"""

    def test_nine_codes_as_designed(self) -> None:
        """设计 §3 列了 9 个码，一个不多一个不少。"""
        assert len(_declared_codes()) == 9

    def test_codes_are_lowercase_snake(self) -> None:
        """取值一律小写 snake_case（下游按字符串比较，大小写不一致即静默失配）。"""
        for name, value in _declared_codes().items():
            assert re.fullmatch(r"[a-z][a-z_]*", value), f"{name}={value} 不符合小写 snake_case"

    def test_codes_unique(self) -> None:
        """码值不重复（重复即两个语义撞同一字符串）。"""
        values = list(_declared_codes().values())
        assert len(values) == len(set(values))

    def test_retryable_set_matches_design(self) -> None:
        """可重试集合恰为超时 / 限流 / 上游故障三个（设计 §3 + 06 §4）。"""
        assert RETRYABLE_TOOL_ERRORS == {"timeout", "rate_limited", "upstream_error"}

    def test_retryable_set_is_subset_of_codes(self) -> None:
        """不变量：可重试集合里的码必须都在 `ToolErrorCode` 中登记（防拼写漂移）。"""
        assert RETRYABLE_TOOL_ERRORS <= set(_declared_codes().values())

    @pytest.mark.parametrize(
        ("error_code", "expected"),
        [
            ("timeout", True),
            ("rate_limited", True),
            ("upstream_error", True),
            ("invalid_arg", False),
            ("not_configured", False),
            ("denied", False),
            ("unpaid", False),
            ("not_found", False),
            ("internal", False),
        ],
    )
    def test_is_retryable_tool_error(self, error_code: str, expected: bool) -> None:
        """逐码判定：仅瞬时故障类可重试（输入 / 权限 / 配置问题重试无意义）。"""
        assert is_retryable_tool_error(error_code) is expected

    def test_unknown_code_is_not_retryable(self) -> None:
        """未知码兜底不可重试（拿不准就不重试，宁可降级）。"""
        assert is_retryable_tool_error("no_such_code") is False
        assert is_retryable_tool_error("") is False
