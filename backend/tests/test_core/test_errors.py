"""core/errors.py 异常四分类单测（计划-容错处理 v1.2，P1-a）。

覆盖：四分类 category / 错误码 / retryable 兼容属性 / 判定口诀边界。
"""

from __future__ import annotations

import pytest

from src.core.errors import (
    AppError,
    BusinessError,
    ConfigError,
    NonRetryableError,
    RetryableError,
    SystemError,
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
