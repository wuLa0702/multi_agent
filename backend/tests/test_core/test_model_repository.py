"""model_repository 单测：seed 幂等 + 厂商/模型列表查询。

覆盖（20-testing.md：正常 / 边界）：
- seed_defaults：首次填充 3 厂商 + 5 模型；二次调用幂等（不重复）
- list_providers_with_models：排序、显示名（豆包）、默认模型标记
"""

from __future__ import annotations

import pytest

from src.db import model_repository


@pytest.fixture
async def conn():
    """本用例 schema 上的 PG 连接（schema 由 conftest 的 autouse pg_schema 建好）。"""
    from src.db import connection as db_conn

    async with db_conn.connection() as c:
        yield c


@pytest.mark.asyncio
async def test_seed_defaults_fills_providers(conn) -> None:
    """正常：首次 seed 填充 3 厂商，DeepSeek/豆包各 2 模型、智谱 1 模型。"""
    await model_repository.seed_defaults(conn)

    providers = await model_repository.list_providers_with_models(conn)
    assert [p.slug for p in providers] == ["deepseek", "ark", "zhipu"]
    assert [p.name for p in providers] == ["DeepSeek", "豆包", "智谱"]

    models_by_slug = {p.slug: p.models for p in providers}
    assert [m.name for m in models_by_slug["deepseek"]] == [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ]
    assert [m.name for m in models_by_slug["ark"]] == [
        "doubao-seed-evolving",
        "Doubao-Seed-2.0-Code",
    ]
    assert [m.name for m in models_by_slug["zhipu"]] == ["glm-4-plus"]


@pytest.mark.asyncio
async def test_seed_defaults_idempotent(conn) -> None:
    """边界：重复 seed 不重复插入（providers 表非空即跳过）。"""
    await model_repository.seed_defaults(conn)
    await model_repository.seed_defaults(conn)

    providers = await model_repository.list_providers_with_models(conn)
    assert len(providers) == 3
    assert sum(len(p.models) for p in providers) == 5


@pytest.mark.asyncio
async def test_seed_defaults_marks_first_model_default(conn) -> None:
    """正常：每个厂商第一个模型是默认（is_default），用于无 model_id 请求。"""
    await model_repository.seed_defaults(conn)

    providers = await model_repository.list_providers_with_models(conn)
    for p in providers:
        defaults = [m for m in p.models if m.is_default]
        assert len(defaults) == 1, f"{p.slug} 应恰有一个默认模型"
        assert defaults[0].name == p.models[0].name

# ── 按需声明：本模块测试需要数据库（2026-10-15 起 pg_schema 不再 autouse）──
@pytest.fixture(autouse=True)
def _needs_db(pg_schema) -> None:
    """本模块每个用例都要独立 PG schema（隔离 + 用完即删）。"""
    return None
