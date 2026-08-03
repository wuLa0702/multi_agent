"""日志配置测试：UTF-8 编码 + 大小滚动 + 保留数（04-logging.md 规则）。

覆盖：
1. 正常路径：文件 handler 显式 UTF-8 编码
2. 边界条件：超过 max_bytes 触发滚动生成备份文件
3. 错误路径：滚动文件保留数不超过 backupCount + 1
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.core.logging import SizeTimedRotatingFileHandler


def test_handler_encoding_is_utf8(tmp_path: Path) -> None:
    """文件 handler 必须显式 UTF-8（Windows 默认 GBK 会乱码）。"""
    handler = SizeTimedRotatingFileHandler(tmp_path / "test.log")
    try:
        assert handler.encoding == "utf-8"
    finally:
        handler.close()


def test_size_rollover_creates_backup(tmp_path: Path) -> None:
    """单文件超过 max_bytes 时滚动，生成备份文件。"""
    handler = SizeTimedRotatingFileHandler(
        tmp_path / "app.log", max_bytes=300, backup_count=2
    )
    logger = logging.getLogger("test_roll_size")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    for i in range(10):
        logger.info("记录 %d：" + "x" * 200, i)  # 每条 >300B，必触发滚动
    logger.removeHandler(handler)
    handler.close()

    files = list(tmp_path.glob("app.log*"))
    backups = [f for f in files if f.name != "app.log"]
    assert backups, "应至少生成 1 个滚动备份文件"


def test_backup_count_respected(tmp_path: Path) -> None:
    """滚动文件保留数 ≤ backupCount + 1（当前文件）。"""
    handler = SizeTimedRotatingFileHandler(
        tmp_path / "app.log", max_bytes=300, backup_count=2
    )
    logger = logging.getLogger("test_roll_keep")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    for i in range(60):
        logger.info("记录 %d：" + "x" * 200, i)  # 多次滚动
    logger.removeHandler(handler)
    handler.close()

    files = list(tmp_path.glob("app.log*"))
    assert len(files) <= 3, f"保留数超限: {len(files)}"
