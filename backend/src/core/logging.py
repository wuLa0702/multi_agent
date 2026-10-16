"""日志配置：structlog 结构化输出 + UTF-8 编码 + 时间/大小双滚动 + 2 周保留。

规则（.claude/rules/04-logging.md）：
- 编码：文件 handler **显式** `encoding="utf-8"`（Windows 默认 GBK 会乱码）
- 分割：每天 00:00 滚动一次；单文件超过 50MB 立即滚动
- 保留：滚动文件保留 14 个（约 2 周，每天 1 个 + 大小分割余量）
- 唯一配置点：业务模块禁止自建 handler，统一走 setup_logging()

结构化（2026-10-16 接入，依据 .claude/rules/08-dependency-policy.md）：
- **渲染与字段注入交给 structlog**（第三方成熟实现），不再自研注入逻辑
- `add_trace_id` processor 把审计 `trace_id`（`core/audit.py` 的 ContextVar）
  注入**每一条**主日志 → 主日志与审计底账 / trace / LangSmith 靠同一 ID 关联
  （此前主日志是唯一**没有** trace_id 的流，排障链在此断掉）
- **业务代码零改动**：29 个模块仍用 `logging.getLogger(__name__)`，其记录经
  `ProcessorFormatter.foreign_pre_chain` 走同一条 processor 链
- 输出仍为**人类可读文本**；换 JSON 只需替换 `_build_formatter` 末尾的 renderer

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

import structlog

from src.core.audit import current_trace_id
from src.core.paths import get_log_dir

# ── 常量（04-logging.md 约定值）──
MAX_BYTES = 50 * 1024 * 1024   # 单文件 50MB
BACKUP_COUNT = 14              # 保留 2 周
LOG_ENCODING = "utf-8"         # 硬性：UTF-8，禁止依赖系统默认编码
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
NO_TRACE_ID = "-"              # trace_id 未绑定（启动期 / 长驻 worker / 脚本）的占位

MAIN_LOG_FILENAME = "multi-agent.log"
AUDIT_LOG_FILENAME = "file_access_audit.jsonl"
TRACE_LOG_FILENAME = "agent_trace.jsonl"


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


def add_trace_id(logger: object, method_name: str, event_dict: dict) -> dict:
    """structlog processor：把审计 `trace_id` 注入每一条日志记录。

    数据源是 `core/audit.py` 的 `_TRACE_ID` ContextVar（由请求入口
    `TraceIdMiddleware` 绑定）。未绑定（启动期 / 长驻 worker / 脚本）填 `-`，
    **不编造**——留空会让人误以为"忘了接"，占位符一眼看出"本就没有"。

    底层函数，按规范豁免（纯字段注入，无业务逻辑）。

    Args:
        logger: structlog 传入的 logger（本 processor 不使用）
        method_name: 日志方法名（本 processor 不使用）
        event_dict: 当前事件字典

    Returns:
        补上 `trace_id` 字段的事件字典
    """
    event_dict["trace_id"] = current_trace_id() or NO_TRACE_ID
    return event_dict


def _shared_processors() -> list:
    """structlog 处理器链（**structlog 原生调用与 stdlib 外来记录共用**）。

    Returns:
        依次为：合并上下文字段 / 补 logger 名 / 补日志级别 / 补时间戳 / 注入 trace_id
    """
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt=LOG_DATE_FORMAT, utc=False),
        add_trace_id,
    ]


def _build_formatter() -> structlog.stdlib.ProcessorFormatter:
    """主日志 formatter：processor 链 → 文本渲染。

    `foreign_pre_chain` 是业务代码零改动的关键——stdlib 记录（29 个模块的
    `logging.getLogger(__name__)`）先过该链补齐字段，再统一渲染。

    ⚠️ **`exception_formatter` 必须显式指定 `plain_traceback`**（实测教训）：
    ConsoleRenderer 默认会在检测到 `rich` 时改用**方框美化 traceback**——
    一条异常膨胀到 40+ 行、文件日志的 grep 能力被毁；且两个 venv 是否装了
    `rich` 不同 → **日志格式随环境漂移**。显式指定后输出与环境无关。

    换 JSON（云端 / 日志采集器场景）只需把末尾 renderer 换成
    `structlog.processors.JSONRenderer(ensure_ascii=False)`，链无需改动。

    Returns:
        可挂到任意 stdlib handler 的 formatter
    """
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(
                colors=False,
                pad_event_to=0,   # 关掉事件名 padding：中文列宽与字符数不等，padding 后参差
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ],
    )


def _configure_structlog() -> None:
    """structlog 全局配置：让 `structlog.get_logger()` 与 stdlib 共用同一条链。

    现有代码全部走 stdlib，本步是为**新增代码**提供统一入口；两者输出形态一致。
    """
    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def _configure_root(root: logging.Logger, log_dir: Path, level: int) -> None:
    """配置 root：文件 handler（UTF-8 双滚动）+ 控制台 handler，均用 structlog 渲染。

    Args:
        root: 根 logger
        log_dir: 日志目录（dev 项目 `logs/`，prod `/logs`）
        level: 根 logger 级别
    """
    root.setLevel(level)

    file_handler = SizeTimedRotatingFileHandler(
        log_dir / MAIN_LOG_FILENAME,
        max_bytes=MAX_BYTES,
        backup_count=BACKUP_COUNT,
        encoding=LOG_ENCODING,
    )
    file_handler.setFormatter(_build_formatter())

    # 控制台显式 UTF-8（Windows 控制台/重定向默认 GBK，会乱码）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding=LOG_ENCODING)
        except (AttributeError, OSError):
            pass  # 非文本流（如已关闭）跳过
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(_build_formatter())

    root.addHandler(file_handler)
    root.addHandler(console_handler)


def _takeover_uvicorn() -> None:
    """接管 uvicorn 系 logger：清空默认 handler，propagate 到 root 统一输出。

    不接管会出现两套格式（uvicorn 自带格式 + 本配置），且控制台 GBK 乱码。
    """
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


def _configure_jsonl_stream(name: str, path: Path) -> None:
    """注册一条**独立成流**的 JSONL logger（不混入主日志）。

    formatter 直接透传 `%(message)s`：业务侧（`core/audit.py` / `middlewares/trace.py`）
    已构造完整扁平 JSON 行，再经 structlog 渲染会变成"JSON 套字符串"。
    故该类流**不走 structlog**，`propagate=False` 独立成流。

    Args:
        name: logger 名（`audit` / `trace`）
        path: 落盘文件（同样享受双滚动 + 14 份保留）
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return
    handler = SizeTimedRotatingFileHandler(
        path,
        max_bytes=MAX_BYTES,
        backup_count=BACKUP_COUNT,
        encoding=LOG_ENCODING,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化根 logger：structlog 渲染 + 文件/控制台双 handler + 两条 JSONL 独立流。

    幂等：重复调用直接返回已配置的根 logger。

    Args:
        level: 根 logger 级别（默认 INFO）

    Returns:
        已配置的根 logger
    """
    root = logging.getLogger()
    if getattr(root, "_multilog_configured", False):
        return root

    log_dir = get_log_dir()
    _configure_structlog()
    _configure_root(root, log_dir, level)
    _takeover_uvicorn()

    # 两条独立流（JSONL 透传，见 _configure_jsonl_stream）：
    # - audit：统一审计（core/audit.py::emit() 唯一入口）→ file_access_audit.jsonl
    # - trace：推理层调用链（middlewares/trace.py）→ agent_trace.jsonl
    _configure_jsonl_stream("audit", log_dir / AUDIT_LOG_FILENAME)
    _configure_jsonl_stream("trace", log_dir / TRACE_LOG_FILENAME)

    root._multilog_configured = True  # type: ignore[attr-defined]
    return root
