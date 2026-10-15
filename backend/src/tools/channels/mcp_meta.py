"""MCP 工具的**治理元数据**：声明类型 + 进程内缓存（同步可读）。

## 为什么需要它

MCP 拉回来的工具**只有名字和 schema**——没有风险等级、没有"要不要审批"。
不治理 = 高危外部工具绕开审批（安全漏洞）；让远端返回 = 自定义扩展协议
（换服务即崩）。故治理声明**存在本地表** `mcp_tool_meta`，第三方 server 只管干活
（拍板 D2 选①；依据 `docs/决策/2026-10-15-设计-工具动态注册两方案对比-v1.md` §8.1）。

## 为什么是"缓存"而不是"每次查表"

`get_agent` / `_build_agent` 是**同步**函数（装配编译图时读治理声明），而 DB 是异步。
故走 `McpClientManager` 同款模式：**lifespan 异步预加载进内存**（`api/main.py`），
之后同步读。**不能**把 `get_agent` 改成 async——那会牵动请求链路一大片（定案 X3）。

## 匹配键

`(server_name, tool_name)`，其中 `tool_name` 是**远端原始名**（不含前缀）。
挂载名由 `McpToolPolicy.qualified_name` 算出（`{server}_{tool}`，对齐
`MultiServerMCPClient(tool_name_prefix=True)`）——存原名而非全名，
改前缀配置时旧记录不失效（定案 X2）。

## 未登记 = 不挂载（fail-closed）

`policy_for()` 查不到 → 该工具**不挂给 Agent**（默认拒绝，定案 X1）。
理由同 `channels/base.py`：「占位若'假装通过'，落在校验类接口上就是**静默放行的安全洞**」。
未登记清单由管理 API 暴露（待登记清单），把"多一步"变成"看得见的一步"。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from psycopg import AsyncConnection

from src.core.retry import DEFAULT_DELAYS, DEFAULT_RETRIES
from src.tools.registry import RetryPolicy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpToolPolicy:
    """一条 MCP 工具的治理声明（`mcp_tool_meta` 表一行）。

    Attributes:
        server_name: MCP server 名（对应 `mcp_servers.name`）
        tool_name: 远端**原始**工具名（不含 server 前缀）
        risk_level: 风险级（人读标签 + 审批依据的参考，同 `ToolSpec` 口径）
        requires_approval: 是否需 HITL 审批
        allowed_decisions: 审批允许的决策集（`requires_approval=True` 时必填）
        is_idempotent: 是否幂等——**重试门控**（写操作 False）
        retry: 重试参数（`{"retries": n, "delays": [...]}`）；None = 不重试
        note: 备注（人工核对用）
    """

    server_name: str
    tool_name: str
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_approval: bool = False
    allowed_decisions: tuple[str, ...] = ()
    is_idempotent: bool = False
    retry: dict[str, Any] | None = None
    note: str = ""

    @property
    def qualified_name(self) -> str:
        """挂载名 = `{server}_{tool}`（对齐 `tool_name_prefix=True`）。"""
        return f"{self.server_name}_{self.tool_name}"

    def to_retry_policy(self) -> RetryPolicy | None:
        """治理声明 → `RetryPolicy`（None = 不重试）。

        `extra_exceptions` 恒为空：MCP 协议层异常由 `_SafeTool` 兜底转字符串，
        不会以异常形式逃逸到这里；额外声明异常类也无从按名解析（DB 存的是 JSON）。
        """
        if not self.retry:
            return None
        return RetryPolicy(
            retries=int(self.retry.get("retries", DEFAULT_RETRIES)),
            delays=tuple(self.retry.get("delays") or DEFAULT_DELAYS),
            extra_exceptions=(),
        )


# ── 进程内缓存（lifespan 预加载；之后的读是同步的）──

_policies: dict[str, McpToolPolicy] = {}  # key = qualified_name
_loaded: bool = False


def _parse_json(raw: Any, default: Any) -> Any:
    """JSON 容错解析：空值/坏值 → default（一行脏数据不该拖垮整次加载）。"""
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _row_to_policy(row: dict) -> McpToolPolicy:
    """DB 行 → `McpToolPolicy`（`allowed_decisions` / `retry` 为 JSON 列）。"""
    return McpToolPolicy(
        server_name=row["server_name"],
        tool_name=row["tool_name"],
        risk_level=row["risk_level"],
        requires_approval=bool(row["requires_approval"]),
        allowed_decisions=tuple(_parse_json(row["allowed_decisions"], [])),
        is_idempotent=bool(row["is_idempotent"]),
        retry=_parse_json(row["retry"], None),
        note=row["note"],
    )


async def load_policies(conn: AsyncConnection) -> int:
    """预加载治理元数据进内存（lifespan 调用；可重复调用，幂等覆盖）。

    Args:
        conn: PG 连接

    Returns:
        载入的策略条数

    Raises:
        无。读表失败**不清空**已有缓存（保持上一次可用状态），只记告警——
        治理元数据读不到不该让 agent 起不来（规则 06 §4：降级 + 日志留痕）。
    """
    global _loaded
    from src.db import mcp_meta_repository as repo

    try:
        rows = await repo.list_meta_rows(conn)
    except Exception:  # noqa: BLE001 —— 降级：读不到就沿用旧缓存
        logger.warning("MCP 治理元数据加载失败（沿用上次缓存）", exc_info=True)
        return len(_policies)

    policies: dict[str, McpToolPolicy] = {}
    for row in rows:
        policy = _row_to_policy(row)
        policies[policy.qualified_name] = policy
    _policies.clear()
    _policies.update(policies)
    _loaded = True
    logger.info("MCP 治理元数据已加载 %d 条", len(_policies))
    return len(_policies)


def policy_for(qualified_name: str) -> McpToolPolicy | None:
    """按**挂载名**查治理声明；未登记 → None（调用方据此拒绝挂载）。

    Args:
        qualified_name: 挂载名（`{server}_{tool}`）

    Returns:
        治理声明；未登记返回 None
    """
    return _policies.get(qualified_name)


def all_policies() -> list[McpToolPolicy]:
    """全部治理声明（按挂载名排序；供审批配置与待登记清单使用）。"""
    return [_policies[k] for k in sorted(_policies)]


def registered_names() -> set[str]:
    """已登记的挂载名集合（供"待登记清单"做差集）。"""
    return set(_policies)


def is_loaded() -> bool:
    """是否已预加载过（区分"表里没数据"与"还没加载"）。

    调用方需要它做**降级判断**：未加载（如单测/脚本直接建图，没走 lifespan）
    与已加载但表空，是两种情形——前者不该被当成"用户没配治理"而静默拒绝全部工具。
    """
    return _loaded


def reset() -> None:
    """清空缓存（测试隔离；同 `McpClientManager.reset`）。"""
    global _loaded
    _policies.clear()
    _loaded = False
