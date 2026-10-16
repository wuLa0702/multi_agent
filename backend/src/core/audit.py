"""审计**唯一写入入口**：所有审计行必经 `emit()`。

## 为什么必须唯一入口

只要还有一处绕过它，方言就会重新长出来——历史遗留的
`agent/memory/agent.py` 那句**纯文本行**（不是 JSON）就是绕过品：
下游按 JSON 解析审计时会在它那里炸。
故本模块同时配一条**反绕过锁测试**（AST 扫全仓直调 `audit_logger.info`）。

## 统一事件模型（设计稿 §3）

核心字段 7 个，**每行必有**：

| 字段 | 本批次（批次 1） | 说明 |
|---|---|---|
| `ts` | ✅ 有值 | **毫秒**精度（原只到秒 → 同秒多事件无法排序） |
| `trace_id` | ⚠️ **空串占位** | 生成点在批次 2 的请求入口中间件；**刻意分步，不是 bug** |
| `seq` | ⚠️ 仍递增 | 同上：同一 trace 内序号，批次 2 起才有跨请求意义 |
| `layer` | ✅ | 事件来源层（原两处缺失 → 补齐） |
| `event` | ✅ | **点分命名** `<layer>.<动作>`（合并原 `decision`/`event`/`phase` 三套方言） |
| `status` | ✅ 可空 | 结果（`ok`/`degraded`/`error`/`denied`），复用 `ToolResult` 口径 |
| `session_id` | ✅ | 原 `thread_id` 改名（二者本就是同一值，见设计稿 §3.1） |

## 不做什么

- ❌ **不参与决策**：审计是旁路，只记不拦（记录后业务照常走）
- ❌ 不记录内容正文（prompt/response、文件内容、记忆正文）——见设计稿 §3.5 边界
"""

from __future__ import annotations

import itertools
import json
import logging
from contextvars import ContextVar
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit")

#: 核心字段（保留名）——层自有字段**不得重名**，由 `emit()` 校验
CORE_FIELDS: frozenset[str] = frozenset(
    {"ts", "trace_id", "seq", "layer", "event", "status", "session_id"}
)

# trace_id / session_id：由请求入口中间件（批次 2）或长驻消费者 bind
_TRACE_ID: ContextVar[str] = ContextVar("audit_trace_id", default="")
_SESSION_ID: ContextVar[str] = ContextVar("audit_session_id", default="")
_ORPHAN: ContextVar[bool] = ContextVar("audit_orphan", default=False)

# 🔴 seq 必须存【可变对象】而不是 int：
#    contextvars 是**按任务隔离**的，子任务各持一份副本。存 int 的话，请求内并发
#    （并行子代理 / 多个 create_task）会各自从同一值起算 → 产生**重复 seq** →
#    PG 的 `UNIQUE(trace_id, seq)` + `ON CONFLICT DO NOTHING` 会把第二条**静默丢弃**。
#    存 `itertools.count` 对象则子任务复制的是**同一个对象的引用**，
#    `next()` 在无 await 的临界段内由 GIL 保证原子 → 全 trace 唯一且单调。
_SEQ: ContextVar[itertools.count | None] = ContextVar("audit_seq", default=None)


def bind_context(
    trace_id: str, *, session_id: str = "", orphan: bool = False
) -> None:
    """绑定审计上下文到**当前 context**（并重置 seq 计数器）。

    调用方两处（设计稿 §4.2）：
    - **请求入口中间件**（批次 2）：每请求 bind 一次
    - **长驻消费者**（记忆队列 worker）：取出任务后 bind —— ⚠️ 这一步不可省：
      worker 是 lifespan 创建的**长驻任务**，其 context 是进程启动时的，
      **不会**自动继承某个请求的 trace_id（`create_task` 只复制创建那一刻的 context）

    Args:
        trace_id: 贯穿 ID（空串 = 未绑定，行里如实写空，**不编造**）
        session_id: 会话（弱关联字段，可空）
        orphan: 是否孤儿（无上游触发，如定时任务）
    """
    _TRACE_ID.set(trace_id)
    _SESSION_ID.set(session_id)
    _ORPHAN.set(orphan)
    _SEQ.set(itertools.count(1))


def current_trace_id() -> str:
    """当前 trace_id（未绑定 → 空串）。"""
    return _TRACE_ID.get()


def is_configured() -> bool:
    """审计流是否已配置（`setup_logging()` 已给 `audit` logger 挂 handler）。

    调用场景（`core/backend.py` 的拒绝分支）：审计**未配置**时，拦截这件事
    在审计流里留不下痕——此时补记一条**模块日志 warning**，避免"拒绝了但没人知道"。
    把"是否已配置"的判定收在本模块，避免各写入点各自去摸 `audit_logger.handlers`。

    Returns:
        True = 审计流可用（正常路径，`emit()` 能落盘）
    """
    return bool(audit_logger.handlers)


def _next_seq() -> int:
    """取下一个序号；未 bind 过时惰性初始化（保证单测可直接用 emit）。"""
    counter = _SEQ.get()
    if counter is None:
        counter = itertools.count(1)
        _SEQ.set(counter)
    return next(counter)


def build_record(
    layer: str,
    event: str,
    *,
    status: str | None = None,
    session_id: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """构造一行审计（不落盘）——拆出来便于单测与"先构造后写"的顺序保证。

    Args:
        layer: 事件来源层（如 `tool_call` / `file_access` / `sandbox`）
        event: 事件名，**点分命名** `<layer>.<动作>`
        status: 结果；无结果语义时不传（**不编造**）
        session_id: 显式会话（None → 取 context；两者都没有则留空）
        **fields: 层自有字段（不得与核心字段重名）

    Returns:
        扁平 dict（核心字段在前，层自有字段平铺其后）

    Raises:
        ValueError: `fields` 含核心字段保留名——**必须当场暴露**，
            静默丢弃会让审计行悄悄少字段且无人察觉
    """
    duplicated = CORE_FIELDS.intersection(fields)
    if duplicated:
        raise ValueError(
            f"审计字段与核心字段重名：{sorted(duplicated)}"
            "（核心字段不可覆盖；层自有字段请换名）"
        )
    record: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "trace_id": current_trace_id(),
        "seq": _next_seq(),
        "layer": layer,
        "event": event,
        "status": status,
        "session_id": session_id if session_id is not None else _SESSION_ID.get(),
    }
    if _ORPHAN.get():
        record["orphan"] = True
    record.update(fields)
    return record


def emit(
    layer: str,
    event: str,
    *,
    status: str | None = None,
    session_id: str | None = None,
    **fields: Any,
) -> None:
    """写一行审计（**全项目唯一入口**）。

    Args:
        layer: 事件来源层
        event: 点分事件名
        status: 结果（可空）
        session_id: 显式会话（None → 取 context）
        **fields: 层自有字段

    Raises:
        ValueError: `fields` 与核心字段重名（**编程错误，必须暴露**）

    Note:
        **除上述 ValueError 外绝不抛异常**：审计是旁路能力，写失败不能让业务崩
        （设计稿 §4.1「失败重试」；此处对应"底账写失败"场景）。
    """
    try:
        record = build_record(
            layer, event, status=status, session_id=session_id, **fields
        )
    except ValueError:
        raise  # 编程错误：当场暴露，不吞（吞了等于悄悄少记字段）
    try:
        audit_logger.info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 —— 旁路能力：写失败只告警，绝不断业务
        logger.error("审计写入失败（不影响业务）", exc_info=True)
