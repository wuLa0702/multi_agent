# tools/ — 工具中心

> 一个概念一个目录。设计依据：`docs/决策/2026-10-14-设计-工具中心落地-v1.md`

## 职责

工具的定义、治理与调用入口。**不含** Agent 编排（→ `agent/`）。

## 结构

| 路径 | 职责 |
|------|------|
| `registry.py` | **唯一真相源**：`ToolSpec` + `TOOL_REGISTRY`（工具目录 + 元数据） |
| `audit.py` | 工具调用审计（`ToolAuditMiddleware` / `security_audit` / `log_security_blocked`） |
| `channels/` | **接入协议**：`base.py` 三协议登记 ｜ `mcp_client.py` 出站 ｜ `mcp_server.py` 入站 |
| `impl/` | **工具实现**（按域分包）：search / fetch / sandbox / skill / wiki / report / hitl |
| `market/` | **工具进货**：Skill 市场适配（Smithery）+ 安装管理（写 `mcp_servers` 表 → 热刷新） |

## 依赖

```
api → agent → tools
api → tools.market (Skill 市场 API)
tools.impl → sandbox / core        （工具实现依赖沙箱适配层与底座）
tools.channels.mcp_client → 外部 MCP server（第三方 SDK 封装）
tools.market → db / tools.channels.mcp_client
```

禁令：
- `tools/` 不依赖 `api/`、`agent/`（只能被上层调用）
- 工具实现**禁直接** `new` 第三方实例（SDK 统一在 `llm/` / `channels/` / `core/` 封装）

## 元数据口径

`ToolSpec` 字段含义与归属见 `.claude/rules/07-tool-center.md` §1。

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-10-14 | 初建：`mcp/registry.py`+`agent/tools/`+`agent/middlewares/tool_audit.py`+`skills/` 收拢至此 |
