"""系统配置 REST 路由（2026-08-04 后端开发计划 P1，设置页开关持久化）。

- GET /v1/settings   读取全部配置（key/value，JSON 值）
- PUT /v1/settings   批量写入（前端开关自动保存）
- POST /v1/frontend/logs  前端日志批量上报（落盘 logs/frontend.log，UTF-8）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.agent.services import settings_service
from src.core.logging import setup_logging
from src.core.paths import get_frontend_log_path

router = APIRouter(tags=["settings"])

setup_logging()  # 幂等：日志配置唯一入口（04-logging 规范）
logger = logging.getLogger(__name__)


class SettingsResponse(BaseModel):
    """全部配置（key → JSON 值字符串）。"""

    status: str = "ok"
    settings: dict[str, str]


class SettingsUpdateRequest(BaseModel):
    """批量更新配置。"""

    settings: dict[str, str] = Field(description="key → value（value 存 JSON 字符串）")


class LogEntry(BaseModel):
    """前端日志条目。"""

    level: str = "info"
    source: str = "frontend"
    message: str = ""
    stack: str | None = None
    url: str | None = None
    ts: int | None = None


class LogsRequest(BaseModel):
    """前端批量日志。"""

    entries: list[LogEntry] = Field(default_factory=list)


@router.get("/v1/settings", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    """读取全部系统配置（空表返回空 dict，前端用默认值）。"""
    values = await settings_service.get_all_settings()
    return SettingsResponse(settings=values)


@router.put("/v1/settings")
async def put_settings(req: SettingsUpdateRequest):
    """批量写入配置（INSERT OR REPLACE，幂等；前端开关变更即保存）。"""
    await settings_service.upsert_settings(req.settings)
    return {"status": "ok", "updated": list(req.settings.keys())}


@router.post("/v1/frontend/logs")
async def post_frontend_logs(req: LogsRequest) -> dict[str, object]:
    """前端日志批量上报 → 落盘 logs/frontend.log（UTF-8，04-logging 规范）。

    前端 logger.ts 的 flush 批量队列对接此接口（占位已留）。
    """
    if not req.entries:
        return {"status": "ok", "written": 0}

    log_file = get_frontend_log_path()
    lines: list[str] = []
    for e in req.entries:
        # 单行 JSON，避免多行日志破坏可读性
        payload = {
            "level": e.level,
            "source": e.source,
            "message": e.message[:2000],
            "url": e.url,
            "ts": e.ts,
        }
        if e.stack:
            payload["stack"] = e.stack[:2000]
        lines.append(json.dumps(payload, ensure_ascii=False))

    try:
        with Path(log_file).open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return {"status": "ok", "written": len(lines)}
    except OSError as exc:
        logger.warning("前端日志落盘失败：%s", exc)
        return {"status": "degraded", "written": 0, "detail": str(exc)}
