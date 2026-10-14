"""Skill 市场层：外部市场适配 + 本地安装管理（工具中心的"进货"入口）。

装一个 MCP server 类技能 → 写 `mcp_servers` 表 → `McpClientManager.reload()` → 新工具进 Agent。

依赖单向：`api → tools.market → {db, tools.channels.mcp_client}`。
"""
