"""文件引用对象（安全机制 D2：对象限制 + 路径校验，防越权路径回显）。

2026-08-12 评审修正：
- 加 session_id 字段（必填）——validate_workspace_path 完整校验需会话级隔离
- path 明确为"相对 workspace/{session_id}/ 的相对路径"（评审中 3：基准明确）
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from src.core.permissions import validate_workspace_path


class FileRef(BaseModel):
    """agent 返回文件引用：path 相对 workspace/{session_id}/，会话内合法。

    Attributes:
        name: 文件名
        session_id: 所属会话 ID（必填——防跨会话越权回显）
        path: 相对 workspace/{session_id}/ 的相对路径（禁穿越/外部协议/绝对）
        content_type: MIME 类型
        size: 文件大小
    """

    name: str = Field(description="文件名")
    session_id: str = Field(description="所属会话 ID（会话级隔离）")
    path: str = Field(description="相对 workspace/{session_id}/ 的相对路径")
    content_type: str = "text/plain"
    size: int = 0

    @model_validator(mode="after")
    def _check_path(self) -> "FileRef":
        if not validate_workspace_path(self.path, self.session_id):
            raise ValueError(f"文件路径越权：{self.path}（会话 {self.session_id}）")
        return self
