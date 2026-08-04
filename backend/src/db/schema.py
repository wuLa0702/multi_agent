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
-- 会话表（短期记忆地基；is_pinned：置顶，2026-08-04 后端开发计划 P0）
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '新会话',
    is_pinned   INTEGER NOT NULL DEFAULT 0,
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

-- 外部 MCP server 连接配置（McpClientManager 消费；stdio 时 url 为空）
-- source/source_url/version/installed_at：Skill Market 安装来源追踪
CREATE TABLE IF NOT EXISTS mcp_servers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    transport   TEXT NOT NULL DEFAULT 'sse',   -- sse / streamable_http / stdio
    url         TEXT NOT NULL DEFAULT '',      -- HTTP endpoint（stdio 时为空）
    command     TEXT NOT NULL DEFAULT '',      -- stdio 可执行文件
    args        TEXT NOT NULL DEFAULT '[]',    -- stdio 参数（JSON 数组）
    headers     TEXT NOT NULL DEFAULT '{}',    -- HTTP headers（JSON 对象，含 auth token）
    is_active   INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'manual',  -- manual / smithery（来源市场）
    source_url  TEXT NOT NULL DEFAULT '',        -- 市场条目页 URL
    version     TEXT NOT NULL DEFAULT '',        -- 版本号（市场条目 qualifiedName）
    installed_at TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 已安装 Skill 记录（Skill Market 安装管理；mcp_server 与 skill_md 两类共用）
CREATE TABLE IF NOT EXISTS installed_skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    skill_type  TEXT NOT NULL DEFAULT 'mcp_server',  -- mcp_server / skill_md
    source      TEXT NOT NULL DEFAULT 'manual',      -- manual / smithery
    source_url  TEXT NOT NULL DEFAULT '',
    version     TEXT NOT NULL DEFAULT '',
    install_path TEXT NOT NULL DEFAULT '',           -- skill_md 本地目录 / mcp_server 的 mcp_servers.id
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skills_source
    ON installed_skills(source);
"""


# 旧库迁移：mcp_servers 新增的 Skill Market 列（已存在则跳过）
_MCP_SERVERS_NEW_COLUMNS: list[tuple[str, str]] = [
    ("source", "TEXT NOT NULL DEFAULT 'manual'"),
    ("source_url", "TEXT NOT NULL DEFAULT ''"),
    ("version", "TEXT NOT NULL DEFAULT ''"),
    ("installed_at", "TEXT NOT NULL DEFAULT ''"),
]

# 旧库迁移：sessions 新增列（2026-08-04 后端开发计划 P0）
_SESSIONS_NEW_COLUMNS: list[tuple[str, str]] = [
    ("is_pinned", "INTEGER NOT NULL DEFAULT 0"),
]


async def init_schema(conn: aiosqlite.Connection) -> None:
    """幂等执行建表 SQL（CREATE IF NOT EXISTS，可反复调用）。

    Args:
        conn: 已配置行工厂的 SQLite 连接（:memory: 或文件均可）

    Raises:
        aiosqlite.Error: 建表失败（连接已关闭/损坏）
    """
    await conn.executescript(_SCHEMA_SQL)
    await _migrate_columns(conn, "mcp_servers", _MCP_SERVERS_NEW_COLUMNS)
    await _migrate_columns(conn, "sessions", _SESSIONS_NEW_COLUMNS)
    await conn.commit()


async def _migrate_columns(
    conn: aiosqlite.Connection,
    table: str,
    columns: list[tuple[str, str]],
) -> None:
    """对旧库安全加列（ALTER TABLE ADD COLUMN，已存在则捕获跳过）。

    SQLite 无 ADD COLUMN IF NOT EXISTS；逐列 try/except OperationalError
    （duplicate column name）实现幂等，不影响新库（CREATE 已含这些列）。
    """
    for col_name, col_def in columns:
        try:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        except aiosqlite.OperationalError:
            pass  # 列已存在（新库或已迁移过的库）
