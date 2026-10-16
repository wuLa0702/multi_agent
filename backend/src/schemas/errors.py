"""统一错误响应模型（契约 §3.3 的**唯一载体**）。

背景（2026-10-16，见 `docs/临时/2026-10-16-汇总问题-v1.md` B3）：
此前同一条契约在 `api/` 层有 **6 种**写法——`chat.py` / `sessions.py` /
`mcp_servers.py` / `uploads.py` 各定义一份类，`skills.py` / `providers.py` /
`context_usage.py` 直接手写裸 dict。四份类当时恰好一致，但**改一份就漂移**，
且没有任何机制会报错。

按 `.claude/rules/06-structure-optimization.md` §2「Pydantic 模型统一放
`src/schemas/`」与 `.claude/rules/10-api.md`「错误统一 ErrorResponse」收归此处。
"""

from __future__ import annotations

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """统一错误响应（契约 §3.3，**扁平三字段**）。

    注意「扁平」是硬要求：`ErrorResponse` 必须**直接**作为 HTTP 响应体，
    不能塞进 `HTTPException.detail` 让 FastAPI 多包一层
    （那会变成 `{"detail": {...}}`，前端读不到 `error` / `code`——见 B1）。
    统一经 `api/error_handlers.py::api_error()` 抛出即可避免。

    Attributes:
        error: 人类可读错误信息
        detail: 具体原因（可含字段级提示）
        code: 错误码（契约 §7；与 `core/errors.py` 的异常分级口径对齐）
    """

    error: str
    detail: str
    code: str
