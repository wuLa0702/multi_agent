# tools/ — 工具中心

> 一个概念一个目录。设计依据：`docs/决策/2026-10-14-设计-工具中心落地-v1.md`

## 职责

工具的定义、治理与调用入口。**不含** Agent 编排（→ `agent/`）。

## 结构

> 2026-10-15 收拢：一级 7 个平铺文件收进 `contract/` + `runtime/`（纯移动，零行为变更）。
> （`guardrails/` 于 2026-10-16 更名为 `runtime/` —— 名实相符：`audit` 只记录不拦截。）
> 分层口径：**声明 → 契约 → 护栏 → 实现 → 通道/进货**。

| 路径 | 职责 |
|------|------|
| `registry.py` | **唯一真相源**（声明）：`ToolSpec` + `TOOL_REGISTRY` + `RetryPolicy` + `fallback_for()`——留在一级，它是工具中心门面 |
| `contract/` | **契约**（工具"长什么样"）：`result.py` 三态信封 ｜ `adapter.py` → `content_and_artifact` 双通道 ｜ `error_map.py` 异常/HTTP → 归一错误码 |
| `runtime/` | **运行时横切**（调用进/出的约束）：`validators.py` 入口校验 ｜ `audit.py` 审计两行制 ｜ `gateway.py` 异常回灌 LLM 的摘要口径 |
| `impl/` | **工具实现**（按域分包）：search / fetch / sandbox / skill / wiki / report / hitl / **util**（通用：calc · clock · json_extract） |
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

## 模板索引（新增工具照着抄）

三个通用工具（2026-10-16 新增）刻意覆盖三种实现粒度，**都是能直接用的真工具**，不是样例：

| 参照 | 形态 | 什么时候抄它 | 文件 |
|------|------|-------------|------|
| `current_time` | **最简骨架** | 一个参数、一次外部调用、一条失败分支 | `impl/clock.py` |
| `calculate` | **纯函数 + 严格校验** | 无 IO、纯计算、输入需白名单校验（防注入） | `impl/calc.py` |
| `json_extract` | **完整处理链** | 要解析、要归一、要多级错误提示 | `impl/json_extract.py` |

**新增工具 Checklist（6 条）**

1. 参数注解 `Annotated[..., Field(description=…)]` —— 守卫见 `tests/test_tools/test_tool_params.py`
2. 业务失败**返回** `ToolResult(status="error", …)`，**不抛异常**
3. 三态选对：`ok` / `degraded`（部分结果）/ `error`
4. `data` 放程序字段，`message` 放给 LLM 的中文文本
5. 在 `registry.py::_IMPL_SPECS` 加一行 —— **`description` 是 LLM 看到的唯一来源**
   （`_with_output_adapter` 会用它覆写 docstring；docstring 只留给人看，**别两处各写一份**）
6. 补测试 `backend/tests/test_tools/test_<模块>.py`（正常 / 边界 / 错误）

> **别重复造**：deepagents 的 `FilesystemMiddleware` 已内置
> `ls / read_file / write_file / edit_file / delete / glob / grep`。

> **技能（skill）≠ 工具**：技能放 `backend/assets/skills/builtin/<name>/`（内置、只读、随代码发布）
> 或 `data/skills/skill_md/<name>/`（市场安装、可增删）。脚本跑在**沙箱**里，
> 只用标准库、用 stdout / 退出码通信。范例：`assets/skills/builtin/research-report/`（完整）、
> `text-stats/`（最小）。

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-10-16 | **新增「模板索引」节**（3 个通用工具作三种粒度参照 + 新增工具 6 条 Checklist）｜`guardrails/` → `runtime/` 陈旧引用修正 ｜ `impl/` 补 `util` 域 ｜ **B13 修复**：`ToolSpec.description` 成为 LLM 可见描述的唯一来源（`_with_output_adapter` 覆写 docstring） |
| 2026-10-15 | **一级收拢**：`result/adapter/error_map` → `contract/`；`validators/audit/gateway` → `guardrails/`；`registry.py` 留一级。补记此前漏记的 `adapter.py`/`result.py`/`error_map.py`/`gateway.py`/`validators.py` 五个模块（阶段 1.0 建表时它们尚未存在） |
| 2026-10-14 | 初建：`mcp/registry.py`+`agent/tools/`+`agent/middlewares/tool_audit.py`+`skills/` 收拢至此 |
