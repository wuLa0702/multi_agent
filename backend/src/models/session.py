"""会话实体：短期记忆的会话元数据。

规范（记忆：数据模型规范化）：全项目 Pydantic 实体模型，禁裸 dict。
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now_utc() -> datetime:
    """统一 UTC 感知时间（避免 naive/aware 混用报错）。"""
    return datetime.now(timezone.utc)


class Session(BaseModel):
    """一个会话（对应前端对话列表的一项）。

    Attributes:
        id: 会话 ID（UUID 字符串）
        title: 会话标题（首条消息后自动生成）
        created_at: 创建时间（UTC）
        updated_at: 最后更新时间（UTC）
    """

    id: str = Field(description="会话 ID（UUID）")
    title: str = Field(default="新会话", description="会话标题")
    created_at: datetime = Field(default_factory=_now_utc, description="创建时间")
    updated_at: datetime = Field(default_factory=_now_utc, description="最后更新时间")
