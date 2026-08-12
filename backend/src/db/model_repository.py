"""模型配置仓储：providers / models 表读写（真相源 = SQLite）。

模式（20-testing.md / repository.py 同款）：
- 显式传 conn，写操作 commit，行 → Pydantic 模型
- seed_defaults 首次启动填充：providers 表为空时插入默认厂商与模型

密钥不入库：providers.api_key_env 只存 .env 变量名（如 DEEPSEEK_API_KEY），
adapter 构造模型时从 settings 按名读取。
"""

from __future__ import annotations

import aiosqlite

from src.schemas.model_config import ModelConfig, ModelInfo, ProviderWithModels

# ── 默认 seed 数据（首次启动填充；新增模型/厂商 = 改这里或走管理接口）──
# 单价：元/千 token（2026-08-12 实测预填，来源官方定价）
# deepseek：输入 1 元/1M、输出 2 元/1M（flash）；3/6（pro）——api-docs.deepseek.com/quick_start/pricing
# 豆包 doubao-seed-evolving：约 6/30 元/1M（Seed 2.1 Pro 官方 ¥6/¥30）
# 豆包 Doubao-Seed-2.0-Code：官方 ¥3.2/¥16 每 1M
# glm-4-plus：官方约 ¥50/¥50 每 1M
_DEFAULT_PROVIDERS: list[dict] = [
    {
        "slug": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "models": [
            {"name": "deepseek-v4-flash", "input_price": 0.001, "output_price": 0.002},
            {"name": "deepseek-v4-pro", "input_price": 0.003, "output_price": 0.006},
        ],
    },
    {
        "slug": "ark",
        "name": "豆包",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key_env": "ARK_API_KEY",
        "models": [
            {"name": "doubao-seed-evolving", "input_price": 0.006, "output_price": 0.030},
            {"name": "Doubao-Seed-2.0-Code", "input_price": 0.0032, "output_price": 0.016},
        ],
    },
    {
        "slug": "zhipu",
        "name": "智谱",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "ZHIPU_API_KEY",
        "models": [
            {"name": "glm-4-plus", "input_price": 0.050, "output_price": 0.050},
        ],
    },
]


def _now_iso() -> str:
    """当前 UTC 时间（ISO 格式，与 repository.py 同约定）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


async def seed_defaults(conn: aiosqlite.Connection) -> None:
    """首次启动填充默认厂商与模型（providers 表非空则跳过）。

    Args:
        conn: 已初始化 schema 的 SQLite 连接

    Raises:
        aiosqlite.Error: 写入失败
    """
    row = await conn.execute("SELECT COUNT(*) AS n FROM providers")
    async with row as cur:
        found = (await cur.fetchone())["n"]
    if found:
        return

    now = _now_iso()
    for i, p in enumerate(_DEFAULT_PROVIDERS):
        cur = await conn.execute(
            """INSERT INTO providers
               (slug, name, base_url, api_key_env, is_active, sort_order, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
            (p["slug"], p["name"], p["base_url"], p["api_key_env"], i, now, now),
        )
        provider_id = cur.lastrowid
        assert provider_id is not None
        for j, model_spec in enumerate(p["models"]):
            model_name = model_spec["name"] if isinstance(model_spec, dict) else model_spec
            in_price = model_spec.get("input_price", 0.0) if isinstance(model_spec, dict) else 0.0
            out_price = model_spec.get("output_price", 0.0) if isinstance(model_spec, dict) else 0.0
            await conn.execute(
                """INSERT INTO models
                   (provider_id, name, is_default, is_active, sort_order,
                    input_price, output_price, created_at, updated_at)
                   VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                # 真实单价（元/千 token，2026-08-12 预填官方定价；厂商调价时改 _DEFAULT_PROVIDERS）
                (provider_id, model_name, 1 if j == 0 else 0, j, in_price, out_price, now, now),
            )
    await conn.commit()


def _row_to_model(row: aiosqlite.Row) -> ModelInfo:
    """providers/models 联查行 → ModelInfo。"""
    return ModelInfo(
        id=row["model_id"],
        provider_id=row["provider_id"],
        name=row["model_name"],
        is_default=bool(row["is_default"]),
        is_active=bool(row["is_active"]),
    )


_PROVIDER_JOIN_SQL = """
SELECT p.id AS provider_id, p.slug, p.name AS provider_name,
       p.base_url, p.api_key_env, p.is_active AS provider_active,
       m.id AS model_id, m.name AS model_name, m.is_default, m.is_active,
       m.input_price, m.output_price
FROM providers p
LEFT JOIN models m ON m.provider_id = p.id
WHERE p.is_active = 1 AND (m.id IS NULL OR m.is_active = 1)
ORDER BY p.sort_order, m.sort_order
"""


async def list_providers_with_models(conn: aiosqlite.Connection) -> list[ProviderWithModels]:
    """全量厂商 + 模型（公开视图：不含 base_url/api_key_env 密钥字段）。

    Args:
        conn: SQLite 连接

    Returns:
        厂商列表（含各自模型），无数据时为空列表
    """
    cur = await conn.execute(_PROVIDER_JOIN_SQL)
    rows = await cur.fetchall()

    providers: dict[int, ProviderWithModels] = {}
    order: list[int] = []
    for row in rows:
        pid = row["provider_id"]
        if pid not in providers:
            providers[pid] = ProviderWithModels(
                id=pid,
                slug=row["slug"],
                name=row["provider_name"],
                is_active=bool(row["provider_active"]),
                models=[],
            )
            order.append(pid)
        if row["model_id"] is not None:
            providers[pid].models.append(_row_to_model(row))
    return [providers[pid] for pid in order]


async def list_model_configs(conn: aiosqlite.Connection) -> list[ModelConfig]:
    """全量模型完整配置（内部视图：含 base_url/api_key_env，仅供注册表）。

    Args:
        conn: SQLite 连接

    Returns:
        模型配置列表（按 provider sort_order + model sort_order）
    """
    cur = await conn.execute(_PROVIDER_JOIN_SQL)
    rows = await cur.fetchall()
    return [
        ModelConfig(
            id=row["model_id"],
            provider_slug=row["slug"],
            model_name=row["model_name"],
            base_url=row["base_url"],
            api_key_env=row["api_key_env"],
            input_price=float(row["input_price"] or 0),
            output_price=float(row["output_price"] or 0),
        )
        for row in rows
        if row["model_id"] is not None
    ]
