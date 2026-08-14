"""POST /v1/export/wiki 单测（P1.5 wiki 保存通道，2026-08-13）。"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client(monkeypatch):
    """mock wiki 导出服务（endpoint 直接 import 了函数，patch 其导入名）。"""

    async def _fake(path, content, title=None, page_type=None):
        return {"status": "ok", "path": path}

    monkeypatch.setattr("src.api.export.export_to_wiki", _fake)
    return TestClient(app)


def test_export_wiki_ok(client):
    r = client.post(
        "/v1/export/wiki",
        json={"path": "对话-测试", "content": "# 测试\n内容", "title": "测试页面"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["path"] == "对话-测试"


def test_export_wiki_empty_content(client):
    r = client.post("/v1/export/wiki", json={"path": "x", "content": "   "})
    assert r.status_code == 400


@pytest.fixture
def read_client(monkeypatch):
    """mock wiki 读服务（双向链路读方向，2026-08-13）。"""

    async def _fake(path):
        return {
            "path": path,
            "title": "测试页面",
            "content": "# 测试\n内容",
            "page_type": "concept",
            "tags": ["test"],
        }

    monkeypatch.setattr("src.api.export.get_page_from_wiki", _fake)
    return TestClient(app)


def test_read_wiki_page_ok(read_client):
    """GET /v1/export/wiki/pages/{path} → 200 读回页面。"""
    r = read_client.get("/v1/export/wiki/pages/对话-测试")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["page"]["title"] == "测试页面"
    assert "测试" in body["page"]["content"]
    assert body["page"]["page_type"] == "concept"


def test_read_wiki_page_not_found(read_client, monkeypatch):
    """页面不存在 → 404（业务错误，非重试）。"""

    from src.agent.services.wiki_read_service import WikiPageNotFoundError

    async def _nf(path):
        raise WikiPageNotFoundError(f"wiki 页面不存在：{path}")

    monkeypatch.setattr("src.api.export.get_page_from_wiki", _nf)
    r = read_client.get("/v1/export/wiki/pages/不存在")
    assert r.status_code == 404
