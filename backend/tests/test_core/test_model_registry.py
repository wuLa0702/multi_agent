"""ModelRegistry 单测：加载/查询/默认回落/空库报错。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- load：seed + 缓存全量（get_model / list_providers / is_loaded）
- get_default_model：默认厂商（settings.llm_provider）与指定厂商
- reset：清空缓存
- 错误：空库加载抛 ConfigError；未加载时 get_default_model 抛 ConfigError
"""

from __future__ import annotations

import pytest

from src.core.config import settings
from src.core.errors import ConfigError
from src.core.model_registry import ModelRegistry


@pytest.fixture
async def registry(tmp_db_path) -> ModelRegistry:
    """隔离 DB 上加载 seed 的注册表。"""
    from src.core import db as core_db

    r = ModelRegistry()
    conn = await core_db.get_connection()
    try:
        await r.load(conn)
    finally:
        await conn.close()
    yield r


@pytest.mark.asyncio
async def test_load_populates_cache(registry) -> None:
    """正常：load 后按 ID 查模型、列出厂商（含显示名）。"""
    assert registry.is_loaded() is True

    providers = registry.list_providers()
    assert {p.slug for p in providers} == {"deepseek", "ark", "zhipu"}
    ark = next(p for p in providers if p.slug == "ark")
    assert ark.name == "豆包"

    first_model = ark.models[0]
    cfg = registry.get_model(first_model.id)
    assert cfg is not None
    assert cfg.provider_slug == "ark"
    assert cfg.model_name == "doubao-seed-evolving"
    assert cfg.api_key_env == "ARK_API_KEY"


@pytest.mark.asyncio
async def test_get_default_model_for_provider(registry) -> None:
    """正常：指定厂商取默认模型（seed 第一个模型）。"""
    cfg = registry.get_default_model("ark")
    assert cfg.model_name == "doubao-seed-evolving"

    cfg_deepseek = registry.get_default_model("deepseek")
    assert cfg_deepseek.model_name == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_get_default_model_uses_settings_provider(registry) -> None:
    """正常：不传厂商时按 settings.llm_provider（deepseek）取默认。"""
    assert settings.llm_provider == "deepseek"
    cfg = registry.get_default_model()
    assert cfg.provider_slug == "deepseek"


@pytest.mark.asyncio
async def test_get_model_unknown_returns_none(registry) -> None:
    """边界：未知 model_id 返回 None（校验层转 400）。"""
    assert registry.get_model(99999) is None


@pytest.mark.asyncio
async def test_reset_clears_cache(registry) -> None:
    """边界：reset 后 is_loaded=False，查询为空。"""
    registry.reset()
    assert registry.is_loaded() is False
    assert registry.list_providers() == []
    assert registry.get_model(1) is None


@pytest.mark.asyncio
async def test_load_all_providers_disabled_raises(tmp_db_path) -> None:
    """错误：全部厂商禁用（过滤后无可用模型）→ ConfigError。

    说明：load() 内部先 seed 幂等填充，空库会被重新填充而非报错；
    真正触发 ConfigError 的是 seed 后仍无可用模型（全禁用）。
    """
    from src.core import db as core_db
    from src.db import model_repository

    r = ModelRegistry()
    conn = await core_db.get_connection()
    try:
        await model_repository.seed_defaults(conn)  # 先 seed 填充（load 前表才有数据可禁用）
        await conn.execute("UPDATE providers SET is_active = 0")
        await conn.commit()
        with pytest.raises(ConfigError, match="注册表为空"):
            await r.load(conn)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_default_unloaded_raises() -> None:
    """错误：未加载注册表调用 get_default_model → ConfigError（提示先加载）。"""
    r = ModelRegistry()
    with pytest.raises(ConfigError):
        r.get_default_model()
