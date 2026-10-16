"""错误响应契约守卫：所有 REST 错误必须是**扁平** `{error, detail, code}`（契约 §3.3）。

## 为什么单列一个文件

2026-10-16 前的错误路径有**三种形态**（嵌套 `detail` / 纯文本 500 / 裸字符串 detail），
而当时的 API 测试**把错误形态锁死了**——`test_sessions.py` 断言
`resp.json()["detail"]["code"]`。结果：**测试全绿，契约早已跑偏**
（见 `docs/临时/2026-10-16-汇总问题-v1.md` B1/F3）。

本文件用**最小 app**（不依赖 DB / Redis）直接测 3 个处理器，作为防回归守卫。

覆盖：
1. 正常路径：`api_error()` 抛出的信封 → 扁平三字段
2. 边界：裸字符串 detail（历史写法）→ 仍归一为三字段
3. 错误路径：Pydantic 校验失败 → 400（非 422）
4. 错误路径：未捕获异常 → 500 + JSON（旧行为是**纯文本**，非 JSON）
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.testclient import TestClient

from src.api.error_handlers import api_error, install_error_handlers

#: 契约 §3.3 的三字段（响应体必须**恰好**是这三个，多一个少一个都算跑偏）
ENVELOPE_KEYS = {"error", "detail", "code"}


def _make_app() -> FastAPI:
    """最小 app：只装错误处理器 + 四条会失败的探针路由（不依赖 DB / Redis）。"""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/probe/envelope")
    async def _envelope() -> dict:
        raise api_error(404, "SESSION_NOT_FOUND", "会话不存在")
        return {}  # pragma: no cover —— 仅满足返回类型

    @app.get("/probe/bare-string")
    async def _bare_string() -> dict:
        raise HTTPException(status_code=400, detail="裸字符串错误")
        return {}  # pragma: no cover

    @app.get("/probe/validate")
    async def _validate(limit: int = Query(default=1, le=10)) -> dict:
        return {"limit": limit}

    @app.get("/probe/crash")
    async def _crash() -> dict:
        raise RuntimeError("探针：内部异常")
        return {}  # pragma: no cover

    return app


def test_api_error_body_is_flat() -> None:
    """正常路径：`api_error()` 的响应体是扁平三字段——FastAPI 不得再包一层 detail。"""
    client = TestClient(_make_app())
    resp = client.get("/probe/envelope")

    assert resp.status_code == 404
    body = resp.json()
    assert set(body) == ENVELOPE_KEYS, f"应恰好三字段，实际 {sorted(body)}"
    assert body["code"] == "SESSION_NOT_FOUND"
    assert body["detail"] == "会话不存在"


def test_bare_string_detail_is_normalized() -> None:
    """边界：裸字符串 detail（改造前的历史写法）→ 仍归一为三字段。"""
    client = TestClient(_make_app())
    resp = client.get("/probe/bare-string")

    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["detail"] == "裸字符串错误"
    assert body["code"] == "BAD_REQUEST", "无显式错误码时按状态码兜底"


def test_validation_error_is_400_flat() -> None:
    """错误路径：Pydantic 校验失败 → 400（**不再是 FastAPI 默认的 422**）+ 扁平三字段。"""
    client = TestClient(_make_app())
    resp = client.get("/probe/validate", params={"limit": 99})

    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["code"] == "BAD_REQUEST"


def test_unhandled_exception_is_500_json() -> None:
    """错误路径：未捕获异常 → 500 + JSON 三字段（旧行为是纯文本、非 JSON）。"""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    resp = client.get("/probe/crash")

    assert resp.status_code == 500
    body = resp.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["code"] == "INTERNAL"
    assert "Traceback" not in body["detail"], "堆栈只进日志，不得外泄给客户端"
