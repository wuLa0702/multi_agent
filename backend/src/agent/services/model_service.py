"""模型数据服务——模型仓储中转（api 禁直调 db/）。"""

from __future__ import annotations

from src.db import connection as db_conn
from src.db import model_repository


async def update_model_price(
    model_id: int, input_price: float, output_price: float
) -> bool:
    """更新模型单价（连接托管）；失败（模型不存在）返回 False。"""
    async with db_conn.connection() as conn:
        return await model_repository.update_model_price(
            conn, model_id, input_price, output_price
        )
