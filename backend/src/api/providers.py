"""厂商/模型列表：GET /v1/providers（前端模型下拉的数据源）。

数据真相源：SQLite providers/models 表（lifespan 加载进注册表，见
core/model_registry.py）；API key 永不返回（密钥只存 .env）。
2026-08-12 成本评审 2.3：加 PATCH 模型单价入口（用户自定义模型成本核算）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from src.agent.services import model_service
from src.core import db as core_db
from src.core.model_registry import get_registry
from src.schemas.model_config import ProvidersResponse

router = APIRouter(prefix="/v1", tags=["providers"])


class ModelPriceUpdate(BaseModel):
    """模型单价更新请求（成本评审 2.3：input/output 单价，元/千 token）。"""

    input_price: float = Field(default=0.0, ge=0, description="输入单价（元/千 token）")
    output_price: float = Field(default=0.0, ge=0, description="输出单价（元/千 token）")


@router.get("/providers", summary="列出可用厂商与模型（前端模型下拉数据源）")
async def list_providers() -> ProvidersResponse:
    """返回厂商列表（含显示名与二级模型列表）。

    Returns:
        {providers: [{id, slug, name, is_active, models: [{id, name, is_default}]}]}
    """
    return ProvidersResponse(providers=get_registry().list_providers())


@router.patch("/providers/models/{model_id}/price", summary="更新模型单价（成本核算档位）")
async def update_model_price(
    model_id: int = Path(..., description="模型 ID"),
    req: ModelPriceUpdate = ...,
) -> dict:
    """更新模型单价（成本评审 2.3：用户自定义模型成本核算入口）。

    更新后需 reload 注册表使单价生效（成本核算读 registry 缓存）。

    Returns:
        {"status": "ok", "model_id": int}

    Raises:
        HTTPException(404): 模型不存在
    """
    ok = await model_service.update_model_price(
        model_id, req.input_price, req.output_price
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"error": "模型不存在", "detail": f"model_id={model_id} 未找到", "code": "MODEL_NOT_FOUND"},
        )
    conn = await core_db.get_connection()
    try:
        await get_registry().load(conn)  # reload 使单价生效（成本核算读 registry 缓存）
    finally:
        await conn.close()
    return {"status": "ok", "model_id": model_id}
