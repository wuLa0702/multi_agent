"""路径自适应：本机 / 云端 / 其他机器均可运行，不写死常量路径。

策略（v2.2 拍板）：环境由 APP_ENV 驱动（dev / prod），数据目录与日志目录
运行时探测——本机开发用工作区目录，云端容器用 /data、/logs 挂载卷。

用法：
    from src.core.paths import get_app_dir, get_log_dir
    app_dir = get_app_dir()      # 数据目录
    log_dir = get_log_dir()      # 日志目录
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from src.core.config import settings

# ── 环境探测 ──

def is_cloud() -> bool:
    """是否云端容器环境。

    判定只信 APP_ENV=prod（docker compose --env-file .env.prod 注入）；
    /data 挂载卷探测仅作为 Linux 容器的辅助确认（Windows 上 /data 解析
    为盘符根目录，不可靠，直接跳过）。
    """
    if settings.app_env.lower() == "prod":
        return True
    if sys.platform == "win32":
        return False
    return Path("/data").is_dir()  # docker-compose 挂载 /data → 云端

def is_frozen() -> bool:
    """是否打包运行（PyInstaller 等，暂未启用）。"""
    return bool(getattr(os, "frozen", False))

# ── 目录解析 ──

def get_app_dir() -> Path:
    """应用数据目录：云端 /data，本地 {项目根}/data。"""
    if is_cloud():
        base = Path("/data")
    else:
        base = Path(__file__).resolve().parents[3] / "data"  # backend/src/core → 项目根
    base.mkdir(parents=True, exist_ok=True)
    return base

def get_log_dir() -> Path:
    """日志目录：云端 /logs，本地 {项目根}/logs。"""
    if is_cloud():
        base = Path("/logs")
    else:
        base = Path(__file__).resolve().parents[3] / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base

def get_db_path() -> Path:
    """SQLite 数据库文件路径（长期记忆）。"""
    if settings.db_path and settings.db_path != "./data/wiki.db":
        p = Path(settings.db_path)
    else:
        p = get_app_dir() / "wiki.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def get_workspace_dir() -> Path:
    """沙箱/任务工作目录：云端 /data/workspace，本地 {项目根}/data/workspace。"""
    base = get_app_dir() / "workspace"
    base.mkdir(parents=True, exist_ok=True)
    return base

def get_skills_dir() -> Path:
    """Skill 存放根目录：云端 /data/skills，本地 {项目根}/data/skills。"""
    base = get_app_dir() / "skills"
    base.mkdir(parents=True, exist_ok=True)
    return base

def get_skill_md_dir() -> Path:
    """SKILL.md 类 skill 目录（deepagents SkillsMiddleware 扫描源）。"""
    base = get_skills_dir() / "skill_md"
    base.mkdir(parents=True, exist_ok=True)
    return base

def get_checkpointer_path() -> Path:
    """Checkpointer 数据库路径（P0 断点持久化）：data/checkpoints.db，父目录自动创建。"""
    p = get_app_dir() / "checkpoints.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def get_store_path() -> Path:
    """Store 记忆数据库路径（P1 语义记忆）：data/store.db，父目录自动创建。"""
    p = get_app_dir() / "store.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def get_memory_dir() -> Path:
    """记忆文件目录（v2.0 /memories/ 路由）：data/memory/，父目录自动创建。"""
    base = get_app_dir() / "memory"
    base.mkdir(parents=True, exist_ok=True)
    return base

def get_exports_dir() -> Path:
    """导出报告目录（v2.0 /exports/ 路由）：data/exports/，父目录自动创建。"""
    base = get_app_dir() / "exports"
    base.mkdir(parents=True, exist_ok=True)
    return base

def get_static_skills_dir() -> Path:
    """内置静态技能目录（v2.0 /skills/static/ 路由，Agent 只读）。

    SKILL_RESOURCES_DIR 环境变量优先（兼容旧配置，零破坏）；缺省
    backend/assets/skills/builtin/（2026-08-05 Skill 体系方案 B：资产层入
    backend，命名 builtin 表达内置；原项目根 skill-resources/ 迁入）；
    不存在时自动初始化 README 模板（启动自检容错）。
    """
    env = os.getenv("SKILL_RESOURCES_DIR")
    base = (
        Path(env)
        if env
        else Path(__file__).resolve().parents[2] / "assets" / "skills" / "builtin"
        # parents[2] = backend（本文件在 backend/src/core/ 下：parents[0]=src/core,
        # parents[1]=src, parents[2]=backend）——测试断言默认路径，防层级回归
    )
    base.mkdir(parents=True, exist_ok=True)
    if not (base / "README.md").exists():
        (base / "README.md").write_text(
            "# builtin skills\n\n内置静态技能目录（Agent 只读）。", encoding="utf-8"
        )
    return base

def get_uploads_dir() -> Path:
    """用户上传文件目录（2026-08-04 P2 附件上传）：data/uploads/。"""
    base = get_app_dir() / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


# ── 数据库文件名（集中维护——main_agent 测试注入场景/tests 断言拼同名文件）──
# 2026-08-06 结构优化：文件名散落 main_agent + 3 个测试文件，统一收敛常量，
# 文件名改名只改本处（文件名联动纪律，见计划-后端结构优化实施 T4）。

CHECKPOINTER_DB_FILE = "checkpoints.db"
STORE_DB_FILE = "store.db"


def get_notifications_log() -> Path:
    """本地通知日志文件：data/notifications.log（memory_agent 通知落盘）。"""
    return get_app_dir() / "notifications.log"


def get_frontend_log_path() -> Path:
    """前端日志上报落盘文件：logs/frontend.log（api/settings.py 日志上报）。"""
    return get_log_dir() / "frontend.log"


# ── 记忆文件虚拟路径（/memories/ 路由——集中维护，禁止散落硬编码）──
# 2026-08-05 结构重构：main_agent MEMORY_SOURCES / 归档函数原硬编码虚拟路径，
# 统一收敛本模块，用函数获取（路径唯一维护点）。

MEMORY_AGENTS_FILE = "/memories/AGENTS.md"
MEMORY_TASKS_FILE = "/memories/tasks.md"
MEMORY_DECISIONS_FILE = "/memories/decisions.md"
MEMORY_TASKS_ARCHIVE_FILE = "/memories/tasks_archive.md"


def get_memory_sources() -> list[str]:
    """记忆注入源（MemoryMiddleware sources）。

    记忆体系 v3 决策：AGENTS.md 单文件全量注入（官方 MemoryMiddleware，
    零自建）；tasks/decisions 为分类承载文件（agent 按需读），不进注入。

    Returns:
        虚拟路径列表（/memories/ 路由语义，非磁盘路径）
    """
    return [MEMORY_AGENTS_FILE]
