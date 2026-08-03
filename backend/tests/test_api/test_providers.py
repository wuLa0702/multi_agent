"""GET /v1/providers 端点测试：厂商显示名 + 二级模型列表（前端下拉数据源）。

覆盖（20-testing.md：正常 / 边界）：
- 正常：3 厂商按序返回，含显示名（豆包）与模型列表
- 安全：响应不含 api_key 字段（密钥只在 .env）
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app


@pytest.mark.asyncio
async def test_providers_endpoint_lists_providers_with_models(seeded_registry) -> None:
    """正常：返回厂商（显示名）+ 模型列表，默认模型标记。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/providers")

    assert resp.status_code == 200
    body = resp.json()
    providers = body["providers"]
    assert [p["slug"] for p in providers] == ["deepseek", "ark", "zhipu"]
    assert [p["name"] for p in providers] == ["DeepSeek", "豆包", "智谱"]

    ark = next(p for p in providers if p["slug"] == "ark")
    assert [m["name"] for m in ark["models"]] == [
        "doubao-seed-evolving",
        "Doubao-Seed-2.0-Code",
    ]
    assert all(m["is_default"] is False for m in ark["models"][1:])
    assert ark["models"][0]["is_default"] is True


@pytest.mark.asyncio
async def test_providers_endpoint_never_exposes_api_key(seeded_registry) -> None:
    """安全：响应不含 api_key / api_key_env / base_url（密钥只在 .env）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/providers")

    raw = resp.text
    assert "api_key" not in raw.lower(), "响应不得泄露密钥信息"
    assert "base_url" not in raw.lower(), "响应不得泄露 API 地址"
