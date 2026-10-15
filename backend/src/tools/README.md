# tools/ — 工具中心

> 一个概念一个目录。设计依据：`docs/决策/2026-10-14-设计-工具中心落地-v1.md`

## 职责

工具的定义、治理与调用入口。**不含** Agent 编排（→ `agent/`）。

## 结构

> 2026-10-15 收拢：一级 7 个平铺文件收进 `contract/` + `guardrails/`（纯移动，零行为变更）。
> 分层口径：**声明 → 契约 → 护栏 → 实现 → 通道/进货**。

| 路径 | 职责 |
|------|------|
| `registry.py` | **唯一真相源**（声明）：`ToolSpec` + `TOOL_REGISTRY` + `RetryPolicy` + `fallback_for()`——留在一级，它是工具中心门面 |
| `contract/` | **契约**（工具"长什么样"）：`result.py` 三态信封 ｜ `adapter.py` → `content_and_artifact` 双通道 ｜ `error_map.py` 异常/HTTP → 归一错误码 |
| `guardrails/` | **护栏**（调用进/出的约束）：`validators.py` 入口校验 ｜ `audit.py` 审计两行制 ｜ `gateway.py` 异常回灌 LLM 的摘要口径 |
| `impl/` | **工具实现**（按域分包）：search / fetch / sandbox / skill / wiki / report / hitl |
| `channels/` | **接入协议**：`base.py` 三协议登记 ｜ `mcp_client.py` 出站 ｜ `mcp_server.py` 入站 |
| `market/` | **工具进货**：Skill 市场适配（Smithery）+ 安装管理（写 `mcp_servers` 表 → 热刷新） |

> ⚠️ 与 `agent/hitl/` 分工：**人在回路审批**归编排层；本目录 `guardrails/` 只管**自动化**的校验与留痕。

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
| 2026-10-15 | **一级收拢**：`result/adapter/error_map` → `contract/`；`validators/audit/gateway` → `guardrails/`；`registry.py` 留一级。补记此前漏记的 `adapter.py`/`result.py`/`error_map.py`/`gateway.py`/`validators.py` 五个模块（阶段 1.0 建表时它们尚未存在） |
| 2026-10-14 | 初建：`mcp/registry.py`+`agent/tools/`+`agent/middlewares/tool_audit.py`+`skills/` 收拢至此 |
