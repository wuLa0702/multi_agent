"""附件上传 REST 路由（2026-08-04 P2，评审拍板：独立上传接口）。

- POST /v1/uploads  multipart 单文件上传 → 落盘 data/uploads/ → 返回 file_id
- GET  /v1/uploads/{file_id}  按 ID 取文件（下载/预览）
- DELETE /v1/uploads/{file_id} 删除

限制：单文件 ≤10MB；文件名 sanitize（防路径穿越）；file_id 用 UUID 防枚举。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.core.paths import get_uploads_dir

router = APIRouter(prefix="/v1/uploads", tags=["uploads"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class UploadResponse(BaseModel):
    """上传成功响应。"""

    file_id: str
    name: str
    size: int


class ErrorResponse(BaseModel):
    """统一错误响应。"""

    error: str
    detail: str
    code: str


def _error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail=ErrorResponse(error="ErrorResponse", detail=detail, code=code).model_dump(),
    )


def _sanitize_name(name: str) -> str:
    """文件名安全化：去路径分隔符，仅保留文件名部分。"""
    import os

    base = os.path.basename(name.replace("\\", "/"))
    return base[:120] or "file"


@router.post("", response_model=UploadResponse)
async def upload_file(file: UploadFile) -> UploadResponse:
    """单文件上传（multipart field 名 file）。"""
    if not file.filename:
        raise _error(400, "BAD_REQUEST", "缺少文件名")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise _error(400, "FILE_TOO_LARGE", f"文件超过 10MB 限制（{len(content)} 字节）")

    file_id = uuid.uuid4().hex
    safe_name = _sanitize_name(file.filename)
    dest = get_uploads_dir() / f"{file_id}_{safe_name}"
    dest.write_bytes(content)

    return UploadResponse(file_id=file_id, name=safe_name, size=len(content))


@router.get("/{file_id}")
async def get_upload(file_id: str) -> FileResponse:
    """按 ID 取文件（下载）。"""
    uploads = get_uploads_dir()
    # 只匹配 {file_id}_ 前缀的文件，防路径穿越（file_id 本身是 hex 白名单）
    if not all(c in "0123456789abcdef" for c in file_id) or len(file_id) != 32:
        raise _error(404, "FILE_NOT_FOUND", f"文件不存在：{file_id}")
    matches = list(uploads.glob(f"{file_id}_*"))
    if not matches:
        raise _error(404, "FILE_NOT_FOUND", f"文件不存在：{file_id}")
    return FileResponse(matches[0], filename=matches[0].name[len(file_id) + 1 :])


@router.delete("/{file_id}")
async def delete_upload(file_id: str) -> dict[str, str]:
    """删除文件。"""
    if not all(c in "0123456789abcdef" for c in file_id) or len(file_id) != 32:
        raise _error(404, "FILE_NOT_FOUND", f"文件不存在：{file_id}")
    matches = list(get_uploads_dir().glob(f"{file_id}_*"))
    if not matches:
        raise _error(404, "FILE_NOT_FOUND", f"文件不存在：{file_id}")
    matches[0].unlink(missing_ok=True)
    return {"status": "ok"}
