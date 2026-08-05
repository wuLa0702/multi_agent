"""日志配置测试：UTF-8 编码 + 大小滚动 + 保留数 + audit 注册（04-logging.md 规则）。

覆盖：
1. 正常路径：文件 handler 显式 UTF-8 编码
2. 边界条件：超过 max_bytes 触发滚动生成备份文件
3. 错误路径：滚动文件保留数不超过 backupCount + 1
4. v3：setup_logging 注册 audit logger（JSONL / 透传 formatter / propagate=False）
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.core.logging import SizeTimedRotatingFileHandler, setup_logging


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


def test_setup_logging_registers_audit_handler(tmp_path: Path, monkeypatch) -> None:
    """v3：setup_logging 注册 audit logger——JSONL 文件 + 透传 formatter + propagate=False。

    ⚠️ 全局日志状态快照/恢复：setup_logging 是单配置点，测试后必须还原
    root handlers / _multilog_configured / audit handlers，防污染其他用例。
    """
    root = logging.getLogger()
    had_flag = getattr(root, "_multilog_configured", False)
    root_handlers = list(root.handlers)
    audit = logging.getLogger("audit")
    audit_handlers = list(audit.handlers)
    audit.propagate = True  # 还原时恢复到测试前状态（记录于 finally）

    monkeypatch.setattr("src.core.paths.get_log_dir", lambda: tmp_path)
    try:
        root._multilog_configured = False  # 强制重新配置
        audit.handlers.clear()
        setup_logging()

        assert audit.handlers, "audit logger 应注册 handler"
        handler = audit.handlers[0]
        assert isinstance(handler, SizeTimedRotatingFileHandler)
        assert str(handler.baseFilename).endswith("file_access_audit.jsonl")
        assert handler.formatter._fmt == "%(message)s", "formatter 应透传业务侧完整 JSON"
        assert audit.propagate is False, "审计独立成流，不得混入 root"
    finally:
        root._multilog_configured = had_flag
        root.handlers.clear()
        root.handlers.extend(root_handlers)
        audit.handlers.clear()
        audit.handlers.extend(audit_handlers)
