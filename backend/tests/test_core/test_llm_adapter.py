"""llm/adapter.py 单测：get_chat_model 各路径（注册表加载 / env 回落 / 未知 ID）。

修复回归：2026-08-10 评估脚本触发 env 回落路径 bug——_build_chat_model
签名无 provider 参数但调用处传入（注册表未加载进程必炸）。
"""

from __future__ import annotations

import pytest

from src.core import model_registry
from src.core.config import Settings, settings
from src.llm.adapter import get_chat_model


class TestGetChatModelEnvFallback:
    @pytest.fixture(autouse=True)
    def _registry_not_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认注册表未加载（env 回落路径前置）。"""
        monkeypatch.setattr(model_registry.get_registry(), "is_loaded", lambda: False)

    def test_env_fallback_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """注册表未加载 → env 回落构造成功（回归：provider 参数事故）。

        pydantic 实例禁 setattr 非字段 → patch 类级方法（staticmethod）。
        """
        monkeypatch.setattr(
            Settings,
            "provider_config",
            staticmethod(
                lambda: {"model": "fake-model", "base_url": "https://fake.test/v1", "api_key": "k"}
            ),
        )
        model = get_chat_model()
        assert model.model_name == "fake-model"
        assert model.openai_api_base == "https://fake.test/v1"

    def test_env_fallback_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env 回落且密钥为空 → 构造期抛错（ChatOpenAI 构造时校验凭据）。

        现状行为：底层 OpenAIError（与注册表路径的 ValueError 文案不一致，
        但均为"失败"语义——本次只修 provider 参数事故，不扩大行为变更）。
        """
        import openai

        monkeypatch.setattr(
            Settings,
            "provider_config",
            staticmethod(lambda: {"model": "m", "base_url": "https://x", "api_key": ""}),
        )
        with pytest.raises((openai.OpenAIError, ValueError)):
            get_chat_model()


class TestGetChatModelErrors:
    def test_unknown_model_id(self) -> None:
        """未知 model_id → ValueError。"""
        with pytest.raises(ValueError, match="未知模型"):
            get_chat_model(model_id=999999)
