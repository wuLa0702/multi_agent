"""成本核算/告警单测（设计-成本控制 §8 用例 1-4/8-10）。

覆盖：核算落 ledger / 单价边界 / summary API / 会话隔离 / 软告警落库 / 去重 / 阈值关闭。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.agent.middlewares import token_usage as tu
from src.core import db as core_db
from src.core.config import settings


async def _setup_model_with_price(monkeypatch) -> int:
    """构造带单价的默认模型（直接塞 registry 缓存，绕过 DB seed 单价）。"""
    from src.core.model_registry import get_registry
    from src.schemas.model_config import ModelConfig

    registry = get_registry()
    registry.reset()
    fake = ModelConfig(
        id=1, provider_slug="deepseek", model_name="deepseek-v4-flash",
        base_url="https://api.deepseek.com/v1", api_key_env="DEEPSEEK_API_KEY",
        input_price=0.002, output_price=0.008,
    )
    registry._models_by_id = {1: fake}
    registry._providers_by_slug = {"deepseek": [fake]}
    registry._default = fake
    return 1


class TestCostLedger:
    @pytest.mark.asyncio
    async def test_cost_logged_to_ledger(self, tmp_db_path, monkeypatch) -> None:
        """成本核算：增量 token × 单价 → ledger 落库（§8 用例 1）。"""
        model_id = await _setup_model_with_price(monkeypatch)
        await _init_db(tmp_db_path)

        # 首次：prev=0，used=1000 → 增量 1000 → cost = 1000×0.002/1000 = 0.002
        await tu._log_cost_for_round("s1", model_id, 1000)
        conn = await core_db.get_connection()
        row = await (await conn.execute(
            "SELECT * FROM token_cost_ledger WHERE session_id='s1'"
        )).fetchone()
        await conn.close()
        assert row is not None
        assert row["input_tokens"] == 1000
        assert row["total_cost"] == pytest.approx(0.002)

    @pytest.mark.asyncio
    async def test_price_zero_boundary(self, tmp_db_path, monkeypatch) -> None:
        """单价 0 → cost 0 不报错（§8 用例 2）。"""
        from src.core.model_registry import get_registry
        from src.schemas.model_config import ModelConfig

        registry = get_registry()
        registry.reset()
        registry._models_by_id = {1: ModelConfig(
            id=1, provider_slug="deepseek", model_name="m",
            base_url="x", api_key_env="K", input_price=0, output_price=0,
        )}
        registry._default = registry._models_by_id[1]
        await _init_db(tmp_db_path)
        await tu._log_cost_for_round("s1", 1, 1000)
        conn = await core_db.get_connection()
        row = await (await conn.execute(
            "SELECT total_cost FROM token_cost_ledger WHERE session_id='s1'"
        )).fetchone()
        await conn.close()
        assert row["total_cost"] == 0.0

    @pytest.mark.asyncio
    async def test_ledger_session_isolated(self, tmp_db_path, monkeypatch) -> None:
        """多 session 不混（§8 用例 4）。"""
        await _setup_model_with_price(monkeypatch)
        await _init_db(tmp_db_path, session_ids=("s1", "s2"))
        await tu._log_cost_for_round("s1", 1, 1000)
        await tu._log_cost_for_round("s2", 1, 500)
        conn = await core_db.get_connection()
        cur = await conn.execute(
            "SELECT session_id, COUNT(*) AS n FROM token_cost_ledger GROUP BY session_id"
        )
        rows = await cur.fetchall()
        await conn.close()
        assert {r["session_id"]: r["n"] for r in rows} == {"s1": 1, "s2": 1}


class TestCostAlert:
    @pytest.mark.asyncio
    async def test_alert_logged_over_threshold(self, tmp_db_path, monkeypatch) -> None:
        """累计超阈值 → cost_alerts 落库（§8 用例 8）。"""
        await _setup_model_with_price(monkeypatch)
        await _init_db(tmp_db_path)
        monkeypatch.setattr(settings, "session_cost_warn_threshold", 0.001)
        # 累计 2 次核算（0.002×2=0.004 > 0.001）
        await tu._log_cost_for_round("s1", 1, 1000)
        await tu._log_cost_for_round("s1", 1, 1000)
        conn = await core_db.get_connection()
        row = await (await conn.execute(
            "SELECT * FROM cost_alerts WHERE session_id='s1'"
        )).fetchone()
        await conn.close()
        assert row is not None
        assert "超阈值" in row["message"]

    @pytest.mark.asyncio
    async def test_alert_dedup_same_threshold(self, tmp_db_path, monkeypatch) -> None:
        """同阈值去重：连续核算只告警一次（§8 用例 9）。"""
        await _setup_model_with_price(monkeypatch)
        await _init_db(tmp_db_path)
        monkeypatch.setattr(settings, "session_cost_warn_threshold", 0.001)
        for _ in range(5):
            await tu._log_cost_for_round("s1", 1, 1000)
        conn = await core_db.get_connection()
        row = await (await conn.execute(
            "SELECT COUNT(*) AS n FROM cost_alerts WHERE session_id='s1'"
        )).fetchone()
        await conn.close()
        assert row["n"] == 1

    @pytest.mark.asyncio
    async def test_alert_disabled_when_threshold_zero(self, tmp_db_path, monkeypatch) -> None:
        """阈值=0 不触发（§8 用例 10）。"""
        await _setup_model_with_price(monkeypatch)
        await _init_db(tmp_db_path)
        monkeypatch.setattr(settings, "session_cost_warn_threshold", 0.0)
        await tu._log_cost_for_round("s1", 1, 1000)
        conn = await core_db.get_connection()
        row = await (await conn.execute(
            "SELECT COUNT(*) AS n FROM cost_alerts WHERE session_id='s1'"
        )).fetchone()
        await conn.close()
        assert row["n"] == 0


class TestCostSummaryApi:
    @pytest.mark.asyncio
    async def test_summary_api(self, tmp_db_path, monkeypatch) -> None:
        """GET /v1/cost/summary 聚合（§8 用例 3）。"""
        await _setup_model_with_price(monkeypatch)
        await _init_db(tmp_db_path)
        await tu._log_cost_for_round("s1", 1, 1000)
        await tu._log_cost_for_round("s1", 1, 500)

        from src.api.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/cost/summary", params={"session_id": "s1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "s1"
        assert data["input_tokens"] == 1500
        assert data["total_cost"] == pytest.approx(0.003, abs=1e-4)

    @pytest.mark.asyncio
    async def test_summary_not_found(self, tmp_db_path, monkeypatch) -> None:
        """无成本记录 → 404 COST_NOT_FOUND。"""
        await _setup_model_with_price(monkeypatch)
        await _init_db(tmp_db_path)
        from src.api.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/cost/summary", params={"session_id": "none"})
        assert resp.status_code == 404
        assert "COST_NOT_FOUND" in resp.text


async def _init_db(tmp_db_path, session_ids: tuple[str, ...] = ("s1",)) -> None:
    """初始化 schema 到临时库（conftest tmp_db_path 隔离）+ 建测试 session。

    Args:
        tmp_db_path: conftest fixture——settings.db_path 指向临时库
        session_ids: 预建会话 ID 列表
    """
    from src.core import db as core_db

    conn = await core_db.get_connection()
    from src.db.schema import init_schema

    await init_schema(conn)
    for sid in session_ids:
        await conn.execute(
            "INSERT INTO sessions (id, created_at, updated_at) VALUES (?, 't', 't')", (sid,)
        )
    await conn.commit()
    await conn.close()
