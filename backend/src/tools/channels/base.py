"""接入协议通道：MCP / REST / A2A 三协议的统一登记。

工具中心的**入口层**——外部系统通过哪种协议调我们的工具（入站），
或我们通过哪种协议接外部工具（出站）。

现状（2026-10-14）：

| 协议 | 状态 | 实现位置 |
|------|------|---------|
| **mcp** | ✅ 双向已实现 | 出站 `mcp_client.py` / 入站 `mcp_server.py` |
| **rest** | ⏳ 占位 | 待有真实需求时填充 |
| **a2a** | ⏳ 占位 | 待有真实需求时填充 |

⚠️ **占位必须显式失败**：`available()` 返回 False，**不得静默返回 True**——
占位若"假装通过"，上层会以为这条路通了；落在校验类接口上就是**静默放行的安全洞**。

> 设计依据：`docs/决策/2026-10-14-设计-工具中心落地-v1.md` §3.4。
> 三个协议**并列**——MCP 不因历史原因享受特殊目录。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolChannel:
    """接入协议通道描述（一个协议一条）。

    Attributes:
        name: 协议名（mcp / rest / a2a）
        available: 是否已实现可用（False = 占位，**不得当作已通**
            ——占位若"假装通过"，上层会误判）
        direction: 支持方向（inbound=别人调我们 / outbound=我们接别人 / both）
        note: 说明（实现位置或待办）
    """

    name: str
    available: bool
    direction: Literal["inbound", "outbound", "both"]
    note: str


CHANNELS: tuple[ToolChannel, ...] = (
    ToolChannel(
        "mcp",
        True,
        "both",
        "出站 tools/channels/mcp_client.py；入站 tools/channels/mcp_server.py",
    ),
    ToolChannel("rest", False, "inbound", "占位未实现——待第二个协议的真实需求出现时填充"),
    ToolChannel("a2a", False, "both", "占位未实现——待第二个协议的真实需求出现时填充"),
)


def available_channels() -> list[ToolChannel]:
    """当前**已实现可用**的通道（占位通道不返回）。

    Returns:
        可用的 ToolChannel 列表（现状仅 mcp）
    """
    return [c for c in CHANNELS if c.available]
