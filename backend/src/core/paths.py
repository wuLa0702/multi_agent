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

def get_uploads_dir() -> Path:
    """用户上传文件目录（2026-08-04 P2 附件上传）：data/uploads/。"""
    base = get_app_dir() / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base
