"""消息实体：会话内的单条消息（role + content）。"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now_utc() -> datetime:
    """统一 UTC 感知时间。"""
    return datetime.now(timezone.utc)


class Message(BaseModel):
    """一条对话消息。

    Attributes:
        id: 消息 ID（自增，未落库时为 None）
        session_id: 所属会话 ID
        role: user / assistant / system / tool
        content: 消息内容
        created_at: 发送时间（UTC）
    """

    id: int | None = Field(default=None, description="消息 ID（自增，未落库时为 None）")
    session_id: str = Field(description="所属会话 ID")
    role: str = Field(description="user / assistant / system / tool")
    content: str = Field(description="消息内容")
    created_at: datetime = Field(default_factory=_now_utc, description="发送时间")
