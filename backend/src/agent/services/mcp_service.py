"""MCP 配置变更后的**热刷新唯一入口**：重建工具缓存 + 失效 Agent 单例。

**为什么收口成一处**（2026-10-15 修 G1）：改 MCP 配置共有三条路径，
此前各写各的，行为互不一致（实测）：

| 路径 | `reload()` | `rebuild_agent()` |
|---|---|---|
| 市场安装 / 启停 / 卸载（`api/skills.py`） | ✅ | ✅ |
| 连接启停（`api/mcp_servers.py` PATCH） | ✅ | ❌ **缺** |
| 连接删除（`api/mcp_servers.py` DELETE） | ❌ **缺** | ❌ **缺** |

后果：**"数据库改了，老会话不生效"**——`get_agent()` 按 thread_id 缓存编译图
（`agent/main_agent.py`），不失效就永远用旧工具清单；删除连接更糟，工具仍在图里，
模型会去调一个已不存在的 server。

**为什么必须两件事都做**：
- `reload()` 刷新 `McpClientManager` 的工具缓存（下次构建图时拿到新清单）
- `rebuild_agent()` 清掉**已存在会话**的编译图缓存（否则老会话仍持旧图）

只做前者 = 假热刷新。三条路径统一调 `refresh_agent_tools()`，杜绝再次漂移。

> 分层：本模块属编排层数据服务域（`agent/services/`，同 `session_service` 调
> `rebuild_agent` 的既有模式）——**不能**把 `rebuild_agent` 写进
> `tools/channels/mcp_client.py`，那会让能力层反向依赖编排层（`test_layering.py` 会红）。
"""

from __future__ import annotations

import logging

from src.db import connection as db_conn
from src.tools.channels.mcp_client import get_mcp_client_manager

logger = logging.getLogger(__name__)


async def refresh_agent_tools() -> None:
    """MCP 配置变更后热刷新：先重载工具缓存，再失效 Agent 单例。

    **失败不阻断管理操作**：热刷新是"让新配置生效"的旁路动作，刷新失败不该让
    管理 API 报错（用户改的是配置，配置本身已落库成功）。故整段降级为告警日志，
    但仍**保证** Agent 缓存被失效——即使工具清单暂时滞后，也不留旧图。

    ⚠️ 顺序不可颠倒：必须先 `reload()` 再重建图。反过来的话，重建出的图会读到
    **还没刷新**的旧工具缓存。

    Raises:
        无。热刷新失败只记告警日志（调用方无需 try/except）。
    """
    try:
        # 连接自开自关（reload 需要读 mcp_servers 表）
        async with db_conn.connection() as conn:
            await get_mcp_client_manager().reload(conn)
    except Exception:  # noqa: BLE001 —— 旁路能力失败降级，不阻断管理操作（规则 06 §4）
        logger.warning(
            "MCP 工具热刷新失败（降级：配置已落库，工具清单可能滞后一轮）",
            exc_info=True,
        )
    # 函数内延迟 import：main_agent 是编排层顶层模块，且它亦 import 各服务
    # （模块级 import 会拉长启动依赖链 + 有循环风险）
    from src.agent.main_agent import rebuild_agent

    rebuild_agent()
