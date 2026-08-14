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
