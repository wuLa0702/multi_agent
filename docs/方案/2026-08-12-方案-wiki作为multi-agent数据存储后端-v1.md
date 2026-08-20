# 方案-wiki 作为 multi-agent 数据存储后端 v1（转正）

> 📋 **规范**：遵循 `docs/规则/文档规范.md`、`docs/规则/文档治理规则.md`
> 📌 **更新时间**：2026-08-12
> 📝 **版本变更记录**（永久保存，只追加不删除）：
> | 版本 | 日期 | 具体改动 |
> |------|------|---------|
> | v1.2 | 2026-08-12 | §4.6 新增「Agent 触发时机与提示词引导」——ReAct 自主查/写 + 触发矩阵 + 「默认只查不写」+ 提示词引导主动沉淀 + 触发链路示例 |
> | v1.1 | 2026-08-12 | §3 新增「双通道澄清」（MCP vs REST：Agent 自动走 MCP、前端手动走 REST）；§4.5 新增「前端保存通道」（选中对话/文件/产物保存到 wiki，挂 SessionList/FileRefChip）；§5 计划加 P1.5 前端阶段 |
> | v1.3 | 2026-08-20 | 转正：评审通过移入 docs/方案/（已实施 P0 查 + P1 写 + P1.5 前端保存，报表实测项 20 推迟）|
> | v1 | 2026-08-12 | 初版：现状盘点（multi_agent 存储出口 + wiki 接入入口）+ 打通方案（MCP 网关主线，查/写/存三路线）+ 分阶段计划 + 自省 |

> **目录**：
> - §1 目标与定位
> - §2 现状盘点（两端事实）
> - §3 打通方案（MCP 网关主线）
> - §4 三路线（查 / 写 / 存）
> - §5 分阶段计划
> - §6 风险与自省
> - §7 待你决策

> **关联**（双向）：`docs/架构/参考-后端接口.md` ｜ `docs/架构/后端功能全景.md` ｜ `docs/架构/多agent项目-架构目录.md`（MCP 层）｜ wiki 侧：`docs/架构/参考-后端接口.md`、`docs/学习/面试/2026-08-12-学习-项目追问链-v1.md`（wiki 知识库定位）｜ `docs/索引.md`

---

## §1 目标与定位

**目标**：把 `llm_wiki_selfbuild`（单 Agent wiki 语义化存储）作为 multi_agent 的**数据存储后端（可选能力）**——multi_agent 的 Agent 能读/写 wiki 知识库，复用 wiki 的"文档编译成 wiki + 图关系 + 三角定位查询"能力，而不是在 multi_agent 里另造一套存储。

**定位**：**可选接入**——不是取代 multi_agent 现有 SQLite Store（会话/记忆），而是补充"**长期知识库**"维度。multi_agent 现有记忆体系管"跨会话回忆"，wiki 管"结构化知识沉淀"。

**一句话**：Agent 要查知识 → 调 wiki 工具；Agent 要沉淀调研结果 → 写 wiki 页面；两者通过 **MCP 协议**打通。

## §2 现状盘点（两端事实）

### 2.1 multi_agent 侧（接入方）

| 能力 | 现状 | 文件 |
|------|------|------|
| MCP 网关 | ✅ **已有**：`MultiServerMCPClient`，支持 `sse`/`streamable_http`/`stdio` 三传输，多 server + 安全包装降级 | `backend/src/mcp/client.py` |
| MCP 配置表 | ✅ `mcp_servers`（name/transport/url/command/headers/is_active）| `backend/src/db/schema.py:78` |
| 存储出口 | ✅ SQLite（会话/记忆/成本），`SqliteStore` 跨会话回忆 | `backend/src/agent/memory/store.py` |
| 已有 MCP 连接 | ✅ 已连博查搜索等外部 server | `mcp_servers` 配置 |

**结论**：multi_agent **零代码改造**即可接入一个外部 MCP server——只要在 `mcp_servers` 表插一行 wiki 的 HTTP 端点。

### 2.2 wiki 侧（被接入方）

| 能力 | 现状 | 文件 |
|------|------|------|
| MCP server | ✅ 已实现，支持 stdio + `--http`（8010 端口）| `src/mcp_server.py` |
| 暴露工具（只读）| ✅ `wiki_search` / `wiki_read` / `wiki_list` / `wiki_graph` / `wiki_lint` | `src/mcp_server.py` |
| 写能力 | ⚠️ `WriteTool` 存在但**未暴露到 MCP**（MCP server 只读）| `src/tools/` |
| 知识库 | ✅ wiki_pages + page_links + 图关系（三角定位查询）| `src/db/schema.py` |

**结论**：wiki 的 MCP server **已能查**（5 只读工具），**写需加工具**（WriteTool 已存在，暴露到 MCP 即可）。

## §3 打通方案（MCP 网关主线）

```
multi_agent                          wiki（llm_wiki_selfbuild）
┌──────────────┐                    ┌──────────────────────┐
│ Agent 主图    │   MCP 协议          │ MCP server（--http）  │
│   └─ 工具调用  │ ◄────────────────► │   8010 端口           │
│      └ MultiServerMCPClient        │   ├ wiki_search       │
│         └ mcp_servers 表           │   ├ wiki_read         │
│            └ "wiki" server 行      │   ├ wiki_list         │
│                                   │   ├ wiki_graph        │
│                                   │   ├ wiki_lint         │
│                                   │   └ wiki_write（可选）│
└──────────────┘                    └──────────────────────┘
```

**配置步骤**（multi_agent 侧，`mcp_servers` 表插一行）：
```
name:     wiki
transport: streamable_http（或 sse）
url:      http://127.0.0.1:8011/mcp  （wiki mcp_server --http --port 8011，避开 multi_agent 8010）
headers:  {}（本地无鉴权；生产可加 token）
is_active: 1
```

**连接后效果**：multi_agent 的 Agent 自动获得 `wiki_search` / `wiki_read` / `wiki_graph` 等工具（带 `wiki_` 前缀防冲突），通过既有的 `_SafeTool` 安全包装（降级不中断）。

### ⚠️ 双通道澄清（MCP vs REST，2026-08-12 补充）

> 用户疑问："双方是通过 MCP 客户端和服务端互相交互传输数据的么？"——**不是互相，是两条通道各自单向**：

| 通道 | 谁调谁 | 用途 | 技术 |
|------|--------|------|------|
| **MCP 通道** | multi_agent Agent（client）→ wiki（server）| Agent 运行时自动查/写知识 | MCP 协议（工具调用）|
| **REST 通道** | multi_agent 后端 → wiki | **前端手动保存**（用户点按钮）| HTTP REST（/v1/pages 等）|

- **MCP 是"Agent 工具"协议**：机器↔机器，Agent 在对话中调 wiki 工具（wiki_search/wiki_write）
- **前端保存走 REST**：人↔系统，用户选中对话/文件 → 点保存 → multi_agent 后端调 wiki `/v1/pages`——**不该走 MCP**（MCP 工具是 Agent 上下文里的，不是 UI 按钮的通道）
- 两者最终都写入 wiki，但入口和语义不同

## §4 三路线（查 / 写 / 存）

### 路线 A：查（wiki 当知识库）✅ 首选，零改造

- **现状即可通**：wiki mcp_server 已暴露 5 只读工具，multi_agent 插配置行即可
- **典型场景**：Agent 调研时 `wiki_search` 查已有知识 → `wiki_read` 读页面 → `wiki_graph` 看关联
- **价值**：multi_agent 复用 wiki 的编译质量 + 图关系，不重复造存储

### 路线 B：写（Agent 产出入 wiki）🟡 需加一个工具

- **现状缺口**：wiki `WriteTool` 存在但未暴露到 MCP
- **改动**：wiki mcp_server 加 `wiki_write` 工具（复用 `WriteTool`，带路径校验 + 页面规范）
- **典型场景**：multi_agent 调研完成 → 把研报/结论写回 wiki 沉淀 → 下次直接查
- **风险**：写权限需谨慎（防 Agent 乱写）→ 加路径白名单 + 页面格式校验

### 路线 C：存（会话/记忆入 wiki）❌ 存疑，不推荐

- **现状**：multi_agent 已有 `SqliteStore`（跨会话回忆），wiki 是知识库不是消息库
- **问题**：把会话历史塞 wiki 违背 wiki 定位（wiki 管"知识"，不管"对话"）；双写复杂、迁移难
- **结论**：**不做**。会话/记忆保持 multi_agent 本地 SQLite，wiki 只当知识库

### §4.5 前端保存通道（手动保存到 wiki）🆕 2026-08-12 补充

> 用户指出："光后端有接口没有用，前端缺一个'选中对话/文件/产物，保存到 wiki'功能。"——补前端入口。

**交互**：用户在 multi_agent 前端选中对话 / 文件 / 产物 → 点「保存到 wiki」→ 填页面标题（可选）→ 确认 → 写入 wiki。

**挂载点**（multi_agent 前端，已有组件）：
- **对话**：`SessionList.tsx`（对话列表每项加"保存到 wiki"按钮）→ 导出该会话的最终回答/研报
- **产物（文件引用）**：`FileRefChip.tsx`（文件引用 chip 加保存动作）→ 导出该文件内容
- **文件/下载**：若前端有产物下载区，同样加按钮

**链路（REST，不走 MCP）**：
```
前端点「保存到 wiki」
  → multi_agent 后端新接口 POST /v1/export/wiki（body: {type, id/content, title?}）
  → multi_agent 后端调 wiki REST POST /v1/pages/{path}（PageUpdateRequest）
  → wiki 写入 wiki_pages → 返回页面路径 → 前端提示「已保存到 wiki: {path}」
```

**关键点**：
- 走 **REST**（用户手动操作），不走 MCP（Agent 工具通道）
- multi_agent 后端新增一个 `wiki_export` 服务（REST 客户端，统一封装 wiki 地址/鉴权），api 层调它
- 页面标题规范：对话 → `对话-{会话标题}`；文件 → 原文件名；产物 → `产物-{类型}-{时间}`
- 前端复用 wiki 的 `wiki_list` 能力在保存后刷新（或简单提示路径）

**待决策**：前端「保存」入口放哪几处（对话列表 / 文件 chip / 产物区），是否全部做。

### §4.6 Agent 触发时机与提示词引导 🆕 2026-08-12 补充

> 用户疑问："Agent 什么时候查、什么时候写？"——答：**Agent 是 deepagents ReAct 循环，工具是它的可调用能力，时机由 Agent 在对话中自主判断**（每轮推理 → 决定调哪个工具 → 看结果 → 再推理）。工具的 `description` 就是"触发条件说明书"，Agent 按描述判断该不该调。

**触发矩阵**：

| Agent 遇到什么 | 会调哪个工具 | 判断依据 |
|----------------|-------------|----------|
| 任务要"查已有资料/基于知识库" | `wiki_search` / `wiki_read` | 工具描述"检索 wiki 知识库" |
| 任务要"看知识关联/图关系" | `wiki_graph` | 描述"查页面关联关系" |
| 任务要"沉淀调研结论/写报告到知识库" | `wiki_write`（P1 后）| 描述"把内容写入 wiki 页面" |

**关键：Agent 默认"只查不写"**——ReAct 里写是额外动作，模型倾向少做。若希望 Agent **主动沉淀**，需二选一：
1. **提示词引导**（推荐，零代码）：系统提示词加"调研/对话完成后，把有价值的结论用 wiki_write 写入知识库"——让"写"成为任务的默认收尾动作
2. **工具描述强化**：`wiki_write` 的 description 写清触发场景（"当需要沉淀研报/结论时调用"）

**触发链路**（以"调研→沉淀"为例）：
```
用户：「调研 MCP 生态，结论存到知识库」
  → Agent 推理 1：查已有 → 调 wiki_search → 得已有知识
  → Agent 推理 2：网络搜索补充 → 调 internet_search
  → Agent 推理 3：整理结论 → 调 wiki_write（提示词引导触发）→ 写 wiki
  → Agent 推理 4：回复用户「已存到 wiki: xxx」
```

## §5 分阶段计划

| 阶段 | 内容 | 产出 | 工作量 |
|------|------|------|--------|
| **P0** | multi_agent `mcp_servers` 表插 wiki 行 + 验证工具注入 | Agent 能 `wiki_search`/`wiki_read` | 小（配置 + 验证）|
| **P1** | wiki mcp_server 加 `wiki_write` 工具（路径白名单 + 校验）| Agent 能写 wiki | 中 |
| **P1.5** | **前端保存通道**：multi_agent 后端 `POST /v1/export/wiki` + 前端「保存到 wiki」按钮（对话/文件/产物）| 用户手动保存到 wiki | 中 |
| **P2** | 生产配置：跨机部署、鉴权 token、wiki --http 常驻 | 云上打通 | 中 |
| **P3**（可选）| multi_agent 记忆体系与 wiki 知识库联动（记忆抽取 → 沉淀 wiki）| 记忆 → 知识闭环 | 大 |

## §6 风险与自省

### 6.1 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| wiki mcp_server --http 无鉴权暴露 | 🟠 中 | 本地绑定 127.0.0.1；生产加 token header |
| 写工具被 Agent 误用（乱写页面）| 🟠 中 | 路径白名单 + 页面格式校验 + 审计 |
| wiki 与 multi_agent 端口冲突 | 🔴 高 | **已核实：两端都默认 8010**——wiki mcp_server 需 `--port 8011` 并行 |
| 两项目依赖漂移（MCP 协议版本）| 🟡 低 | 锁定 MCP SDK 版本 |

> 🔴 **端口核查（已核实 2026-08-12）**：multi_agent 后端 `uvicorn --port 8010`，wiki mcp_server 默认 HTTP **也是 8010**——**冲突**。启动 wiki MCP 需显式 `--port 8011`（`python src/mcp_server.py --http --port 8011`），multi_agent `mcp_servers.url` 对应填 `http://127.0.0.1:8011/mcp`。

### 6.2 自省（为什么这么设计）

1. **为什么用 MCP 而非 REST/共享库**：multi_agent 已有 MCP 网关，wiki 已有 MCP server，两端**天然可通，零新架构**；REST 要自定义 HTTP 工具层，共享库是紧耦合反模式
2. **为什么"查"首选**：wiki 的只读工具已完备，插配置行即通——**最小改动验证价值**，验证后再投入"写"
3. **为什么不做"存"**：存储职责要单一——wiki 管知识，SQLite 管会话/记忆；避免"什么都能存"导致的数据混乱
4. **为什么文档放 multi_agent**：接入发起方是 multi_agent（Agent 获得 wiki 工具），描述的是 multi_agent 的动作；wiki 侧只做关联指针（双向链接）
5. **为什么前端保存走 REST 而非 MCP**：MCP 是"Agent 上下文里的工具"，不是 UI 按钮的通道——前端按钮是用户操作，走 HTTP REST 语义清晰（一次请求写一个页面），MCP 留给 Agent 运行时

## §7 待你决策

| # | 决策点 | 选项 | 我的建议 |
|---|--------|------|----------|
| 1 | 接入目的（路线）| A 查 / B 写 / C 存 | **A 先行**，验证后 B；C 不做 |
| 2 | 传输方式 | streamable_http / sse / stdio | **streamable_http**（wiki --http 支持）|
| 3 | 文档放哪 | 已在 multi_agent（本文件）| ✅ 已定 |
| 4 | 端口冲突核查 | 8010 vs 8010？| ✅ 已核实：wiki 改 `--port 8011` |
| 5 | 前端保存入口 | 对话列表 / 文件 chip / 产物区 | **全部做**（P1.5）或先对话 |

---

> 📌 **维护**：本设计评审通过 → `git mv` 转正 `docs/方案/`；实施后更新 `docs/功能更新日志.md`。
