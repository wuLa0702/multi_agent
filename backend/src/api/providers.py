"""厂商/模型列表：GET /v1/providers（前端模型下拉的数据源）。

数据真相源：SQLite providers/models 表（lifespan 加载进注册表，见
core/model_registry.py）；API key 永不返回（密钥只存 .env）。
"""

from __future__ import annotations

from fastapi import APIRouter

from src.core.model_registry import get_registry
from src.schemas.model_config import ProvidersResponse

router = APIRouter(prefix="/v1", tags=["providers"])


@router.get("/providers", summary="列出可用厂商与模型（前端下拉数据源）")
async def list_providers() -> ProvidersResponse:
    """返回厂商列表（含显示名与二级模型列表）。

    Returns:
        {providers: [{id, slug, name, is_active, models: [{id, name, is_default}]}]}
    """
    return ProvidersResponse(providers=get_registry().list_providers())
