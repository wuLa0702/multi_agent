"""API 层错误响应统一出口：把手写 raise 与未捕获异常都归一为**扁平** ErrorResponse。

## 为什么需要这层

三处默认行为都与契约（`docs/架构/参考-后端接口.md` §3.3）不符，
详见 `docs/临时/2026-10-16-汇总问题-v1.md`：

| 问题 | 默认行为 | 契约要求 |
|------|----------|----------|
| **B1** | `HTTPException.detail` 被再包一层 → `{"detail": {...}}` | 扁平 `{error, detail, code}` |
| **B4** | 未捕获异常 → **纯文本** `Internal Server Error` | 500 + ErrorResponse |
| **B4** | Pydantic 校验失败 → 422 + `{"detail": [ ... ]}` 列表 | 400 + ErrorResponse |
| **B6** | `detail="裸字符串"` → `{"detail": "..."}` 只有 1 个字段 | 三字段齐备 |

**契约与前端零改动** —— 跑偏的是后端实现（前端 `client.ts` 一直按扁平解析）。

## 用法

路由内统一 `raise api_error(404, "SESSION_NOT_FOUND", "…")`；
应用装配时 `install_error_handlers(app)` 一次。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.audit import current_trace_id
from src.schemas.errors import ErrorResponse

logger = logging.getLogger(__name__)

#: 未知异常对外统一文案（**不外泄堆栈与内部细节**）
INTERNAL_ERROR_MESSAGE = "服务器内部错误，请稍后重试"

#: 错误信封的三字段名（`_flatten` 判定用）
_ENVELOPE_KEYS = frozenset({"error", "detail", "code"})

#: 状态码 → 无显式错误码时的兜底码
_DEFAULT_CODES = {400: "BAD_REQUEST", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def api_error(
    status_code: int,
    code: str,
    detail: str,
    *,
    error: str | None = None,
) -> StarletteHTTPException:
    """构造携带**扁平** ErrorResponse 的异常（推荐所有路由用它）。

    Args:
        status_code: HTTP 状态码
        code: 错误码（契约 §7）
        detail: 具体原因（可含字段级提示）
        error: 人类可读短描述；缺省回落到 `detail`

    Returns:
        交给 `raise` 的 HTTPException（`install_error_handlers` 会原样摊平输出）
    """
    envelope = ErrorResponse(error=error or detail, detail=detail, code=code)
    return StarletteHTTPException(status_code=status_code, detail=envelope.model_dump())


def _default_code(status_code: int) -> str:
    """无显式错误码时按状态码给兜底码。"""
    return _DEFAULT_CODES.get(status_code, "INTERNAL" if status_code >= 500 else "HTTP_ERROR")


def _flatten(detail: Any, status_code: int) -> dict[str, Any]:
    """把任意 `HTTPException.detail` 归一为**扁平三字段**。

    兼容三种历史写法（B6）：
    - 已是三字段 dict（`api_error()` 产出）→ 原样用
    - 裸字符串（`{error, detail, code}` 首批改造前的写法）→ 包成三字段
    - 其它类型 → 转文本放 `detail`

    Args:
        detail: `HTTPException.detail` 的原始值
        status_code: 用于推断兜底错误码

    Returns:
        可直接作为响应体的扁平 dict
    """
    if isinstance(detail, dict) and _ENVELOPE_KEYS <= detail.keys():
        return {
            "error": detail["error"],
            "detail": detail["detail"],
            "code": detail["code"],
        }
    text = detail if isinstance(detail, str) else str(detail)
    return {"error": text, "detail": text, "code": _default_code(status_code)}


def _validation_detail(exc: RequestValidationError) -> str:
    """Pydantic 校验错误 → 单行中文（取第一条，避免列表刷屏）。"""
    errors = exc.errors()
    if not errors:
        return "请求参数非法"
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
    msg = str(first.get("msg", "参数非法"))
    return f"{loc}：{msg}" if loc else msg


def _internal_detail() -> str:
    """500 的对外 detail：带 trace_id 便于用户报障时定位（**不带堆栈**）。"""
    trace_id = current_trace_id()
    return (
        f"{INTERNAL_ERROR_MESSAGE}（trace_id: {trace_id}）"
        if trace_id
        else INTERNAL_ERROR_MESSAGE
    )


def install_error_handlers(app: FastAPI) -> None:
    """注册 3 个异常处理器（**应用装配阶段调用一次**）。

    ⚠️ 必须在首次请求前注册——Starlette 在第一次请求后冻结中间件栈，
    之后再 `add_exception_handler` 会抛 `RuntimeError`。

    Args:
        app: FastAPI 应用实例

    Note:
        注册 `Exception` 处理器不会阻止异常继续向上冒泡（Starlette 有意为之，
        让 ASGI server 也能记日志）——故 uvicorn 仍会记一条
        `Exception in ASGI application`，与本模块的 `logger.exception` 并存。
    """

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """HTTPException → 扁平 ErrorResponse（摊平 FastAPI 的 `{"detail": …}` 外壳）。"""
        return JSONResponse(
            status_code=exc.status_code,
            content=_flatten(exc.detail, exc.status_code),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Pydantic 校验失败 → **400** + 扁平 ErrorResponse（默认是 422 + detail 列表）。"""
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="参数非法", detail=_validation_detail(exc), code="BAD_REQUEST"
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def _handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        """未捕获异常 → 500 + 扁平 ErrorResponse（**堆栈只进日志**）。"""
        logger.exception("未捕获异常：%s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=INTERNAL_ERROR_MESSAGE, detail=_internal_detail(), code="INTERNAL"
            ).model_dump(),
        )
