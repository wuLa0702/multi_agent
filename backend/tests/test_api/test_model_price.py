"""模型单价 API 测试（成本评审 2.3，2026-08-12）。

覆盖：PATCH 更新单价生效 / 404 / 负值校验。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.db import connection as db_conn


@pytest.fixture
async def seeded():
    """临时库 + seed 默认模型。"""
    from src.core.model_registry import get_registry

    registry = get_registry()
    registry.reset()
    async with db_conn.connection() as conn:
        await registry.load(conn)
    yield registry
    registry.reset()


class TestModelPriceApi:
    @pytest.mark.asyncio
    async def test_update_price_ok(self, seeded) -> None:
        """PATCH 单价 → 注册表 reload 后生效。"""
        model_id = seeded._models_by_id[1].id if hasattr(seeded, "_models_by_id") and 1 in seeded._models_by_id else 1
        # 用 registry 实际第一个模型
        cfg = seeded.get_default_model()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/v1/providers/models/{cfg.id}/price",
                json={"input_price": 0.005, "output_price": 0.01},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        # reload 后单价生效
        cfg2 = seeded.get_model(cfg.id)
        assert cfg2.input_price == 0.005
        assert cfg2.output_price == 0.01

    @pytest.mark.asyncio
    async def test_update_price_404(self, seeded) -> None:
        """不存在模型 → 404 MODEL_NOT_FOUND。"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/v1/providers/models/999999/price",
                json={"input_price": 0.005, "output_price": 0.01},
            )
        assert resp.status_code == 404
        assert "MODEL_NOT_FOUND" in resp.text

    @pytest.mark.asyncio
    async def test_update_price_negative_rejected(self, seeded) -> None:
        """负单价 → 400（ge=0 校验；2026-10-16 起 Pydantic 校验统一返回 400）。"""
        cfg = seeded.get_default_model()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/v1/providers/models/{cfg.id}/price",
                json={"input_price": -1, "output_price": 0.01},
            )
        assert resp.status_code == 400
        assert resp.json()["code"] == "BAD_REQUEST"

# ── 按需声明：本模块测试需要数据库（2026-10-15 起 pg_schema 不再 autouse）──
@pytest.fixture(autouse=True)
def _needs_db(pg_schema) -> None:
    """本模块每个用例都要独立 PG schema（隔离 + 用完即删）。"""
    return None
