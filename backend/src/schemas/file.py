"""文件引用对象（安全机制 D2：对象限制 + 路径校验，防任意路径回显）。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.core.permissions import validate_workspace_path


class FileRef(BaseModel):
    """agent 返回文件引用：path 必须工作区内相对路径（无穿越/外部协议）。"""

    name: str = Field(description="文件名")
    path: str = Field(description="工作区内相对路径")
    content_type: str = "text/plain"
    size: int = 0

    @field_validator("path")
    @classmethod
    def _check_path(cls, v: str) -> str:
        if not validate_workspace_path(v):
            raise ValueError(f"文件路径越权：{v}")
        return v
