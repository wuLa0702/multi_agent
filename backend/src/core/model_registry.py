"""模型注册表：DB 配置 → 进程内缓存（运行时模型选择的真相源）。

- lifespan 启动时 seed + 加载（main.py）；测试可 reset + 重新 load
- 同步读接口（get_model / get_default_model / list_providers）供
  adapter 每次模型调用查询（字典查，零开销）
- 查询一律只读缓存；配置变更走管理接口后 reload（预留）

模式参考：src/mcp/registry.py（工具注册表：名 → 实现）。
"""

from __future__ import annotations

import threading

from src.core.config import settings
from src.core.errors import ConfigError
from src.db import model_repository
from src.schemas.model_config import ModelConfig, ProviderWithModels

_registry: "ModelRegistry | None" = None
_registry_lock = threading.Lock()


class ModelRegistry:
    """模型配置内存缓存（providers + models 的只读镜像）。"""

    def __init__(self) -> None:
        self._providers: list[ProviderWithModels] = []
        self._by_slug: dict[str, ProviderWithModels] = {}
        self._models_by_id: dict[int, ModelConfig] = {}
        self._loaded = False

    # ── 加载/重置（async：读 SQLite）──

    async def load(self, conn) -> None:
        """全量重载：seed（幂等）→ 读取 → 重建缓存。

        Args:
            conn: 已初始化 schema 的 SQLite 连接

        Raises:
            ConfigError: 缓存重建后无任何可用模型
        """
        await model_repository.seed_defaults(conn)
        providers = await model_repository.list_providers_with_models(conn)
        configs = await model_repository.list_model_configs(conn)

        by_slug: dict[str, ProviderWithModels] = {}
        models_by_id: dict[int, ModelConfig] = {}
        for p in providers:
            by_slug[p.slug] = p
        for cfg in configs:
            models_by_id[cfg.id] = cfg

        if not models_by_id:
            raise ConfigError("模型注册表为空：providers/models 表无可用数据")

        self._providers = providers
        self._by_slug = by_slug
        self._models_by_id = models_by_id
        self._loaded = True

    def reset(self) -> None:
        """清空缓存（测试隔离 / 重载前）。"""
        self._providers = []
        self._by_slug = {}
        self._models_by_id = {}
        self._loaded = False

    # ── 只读查询（同步，每次模型调用走这里）──

    def is_loaded(self) -> bool:
        """注册表是否已加载（lifespan 后为 True）。"""
        return self._loaded

    def get_model(self, model_id: int) -> ModelConfig | None:
        """按 DB 模型 ID 查完整配置；不存在返回 None。"""
        return self._models_by_id.get(model_id)

    def get_default_model(self, provider_slug: str | None = None) -> ModelConfig:
        """默认模型：provider_slug 缺省 → settings.llm_provider。

        Args:
            provider_slug: 厂商标识；None → 进程默认厂商

        Returns:
            默认模型的完整配置

        Raises:
            ConfigError: 厂商不存在或该厂商无默认模型
        """
        slug = (provider_slug or settings.llm_provider).lower()
        provider = self._by_slug.get(slug)
        if provider is None:
            raise ConfigError(f"provider={slug} 不在模型注册表")
        for m in provider.models:
            if m.is_default:
                return self._models_by_id[m.id]
        raise ConfigError(f"provider={slug} 无默认模型")

    def list_providers(self) -> list[ProviderWithModels]:
        """厂商 + 模型全量（GET /v1/providers 数据源）。"""
        return self._providers


def get_registry() -> ModelRegistry:
    """进程内单例（线程安全懒创建）。"""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ModelRegistry()
    return _registry
