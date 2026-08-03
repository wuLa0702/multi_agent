"""SQLite 建表 SQL 集中管理（DAO 只调用，不拼 SQL）。

规范（12-backend.md）：所有 SQL 写在 schema.py，DAO 层只调用不拼接。
表：
- sessions(id TEXT PK, title, created_at, updated_at) — 会话元数据
- messages(id INTEGER PK AUTOINCREMENT, session_id FK, role, content, created_at) — 消息流
- providers(id PK, slug UNIQUE, name, base_url, api_key_env, is_active, sort_order) — 厂商配置
- models(id PK, provider_id FK, name, is_default, is_active, sort_order) — 厂商下具体模型
- 索引：messages(session_id)、messages(session_id, created_at) — 会话维度查询
- WAL 模式在连接层（core/db.py）PRAGMA 开启，这里只建表
"""

from __future__ import annotations

import aiosqlite

_SCHEMA_SQL = """
-- 会话表（短期记忆地基）
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '新会话',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 消息表（长期记忆地基）
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages(session_id);

CREATE INDEX IF NOT EXISTS idx_messages_session_created
    ON messages(session_id, created_at);

-- 厂商配置（模型元数据真相源；API key 不入库，按 api_key_env 读 .env）
CREATE TABLE IF NOT EXISTS providers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    api_key_env TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 模型配置（provider 下具体模型，二级选择）
CREATE TABLE IF NOT EXISTS models (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL,
    name        TEXT NOT NULL,
    is_default  INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE,
    UNIQUE(provider_id, name)
);

CREATE INDEX IF NOT EXISTS idx_models_provider
    ON models(provider_id);
"""


async def init_schema(conn: aiosqlite.Connection) -> None:
    """幂等执行建表 SQL（CREATE IF NOT EXISTS，可反复调用）。

    Args:
        conn: 已配置行工厂的 SQLite 连接（:memory: 或文件均可）

    Raises:
        aiosqlite.Error: 建表失败（连接已关闭/损坏）
    """
    await conn.executescript(_SCHEMA_SQL)
    await conn.commit()
