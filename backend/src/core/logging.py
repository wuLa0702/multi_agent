"""日志配置：UTF-8 输出 + 时间/大小双滚动 + 2 周保留。

规则（.claude/rules/04-logging.md）：
- 编码：文件 handler **显式** `encoding="utf-8"`（Windows 默认 GBK 会乱码）
- 分割：每天 00:00 滚动一次；单文件超过 50MB 立即滚动
- 保留：滚动文件保留 14 个（约 2 周，每天 1 个 + 大小分割余量）
- 唯一配置点：业务模块禁止自建 handler，统一走 setup_logging()

用法（main.py 模块顶部调用一次）：
    from src.core.logging import setup_logging
    setup_logging()
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import time
from pathlib import Path

from src.core.paths import get_log_dir

# ── 常量（04-logging.md 约定值）──
MAX_BYTES = 50 * 1024 * 1024   # 单文件 50MB
BACKUP_COUNT = 14              # 保留 2 周
LOG_ENCODING = "utf-8"         # 硬性：UTF-8，禁止依赖系统默认编码
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class SizeTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """每天滚动 + 单文件超限即滚动的组合 Handler（继承 TimedRotatingFileHandler）。

    - `when="midnight"`：每天 00:00 滚动（后缀 .YYYY-MM-DD）
    - shouldRollover 追加大小判断：当前文件 ≥ 50MB 时也滚动
    """

    def __init__(
        self,
        filename: str | Path,
        max_bytes: int = MAX_BYTES,
        backup_count: int = BACKUP_COUNT,
        encoding: str = LOG_ENCODING,
    ) -> None:
        self.max_bytes = max_bytes
        super().__init__(
            filename,
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding=encoding,
        )

    def shouldRollover(self, record: logging.LogRecord) -> int:
        """时间到或大小超限，都滚动。"""
        if super().shouldRollover(record):
            return 1
        if self.stream is None:
            return 0
        try:
            self.stream.seek(0, 2)  # 移到文件尾拿当前字节数
            return int(self.stream.tell() + len(record.getMessage())) >= self.max_bytes
        except (OSError, AttributeError):
            return 0

    def doRollover(self) -> None:
        """滚动失败容错（Windows 多进程持有句柄）。

        uvicorn --reload 下 reloader 父进程与 spawn 子进程同时打开同一日志文件，
        跨天滚动时 rename 会被占用文件的进程拒绝（WinError 32）。
        滚动非致命：失败一次即放弃本次滚动、把下次滚动时间推到明天并重开文件流，
        避免每条日志都触发滚动失败 → 每次 emit 都打一条 "Logging error" traceback 刷屏。
        """
        try:
            super().doRollover()
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "日志滚动失败（文件被其他进程占用，WinError %s），放弃本次滚动，下次再试",
                exc.errno,
            )
            # super().doRollover() 中断时文件流已被关闭且 rolloverAt 未推进：
            # 重开流继续写当前文件，并把滚动时间推到下一个周期，避免重复尝试
            self.rolloverAt = self.computeRollover(int(time.time()))
            if not self.delay and self.stream is None:
                self.stream = self._open()


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化根 logger：文件 handler（UTF-8 双滚动）+ 控制台 handler。

    幂等：重复调用直接返回已配置的根 logger。
    接管 uvicorn 系 logger（清空其默认 handler），统一走本配置，
    避免 stderr 重复输出与控制台 GBK 乱码。
    """
    root = logging.getLogger()
    if getattr(root, "_multilog_configured", False):
        return root

    root.setLevel(level)

    # 文件 handler：UTF-8 + 双滚动（logs/multi-agent.log，路径自适应）
    log_dir = get_log_dir()
    file_handler = SizeTimedRotatingFileHandler(
        log_dir / "multi-agent.log",
        max_bytes=MAX_BYTES,
        backup_count=BACKUP_COUNT,
        encoding=LOG_ENCODING,
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    # 控制台 handler：显式 UTF-8（Windows 控制台/重定向默认 GBK）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding=LOG_ENCODING)
        except (AttributeError, OSError):
            pass  # 非文本流（如已关闭）跳过
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # 接管 uvicorn 系 logger：清空默认 handler，propagate 到 root 统一输出
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    root._multilog_configured = True  # type: ignore[attr-defined]
    return root
