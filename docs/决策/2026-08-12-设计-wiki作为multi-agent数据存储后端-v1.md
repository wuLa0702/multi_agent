# 设计-wiki 作为 multi-agent 数据存储后端 v1

> 📋 **规范**：遵循 `docs/规则/文档规范.md`、`docs/规则/文档治理规则.md`
> 📌 **更新时间**：2026-08-12
> 📝 **版本变更记录**（永久保存，只追加不删除）：
> | 版本 | 日期 | 具体改动 |
> |------|------|---------|
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

## §5 分阶段计划

| 阶段 | 内容 | 产出 | 工作量 |
|------|------|------|--------|
| **P0** | multi_agent `mcp_servers` 表插 wiki 行 + 验证工具注入 | Agent 能 `wiki_search`/`wiki_read` | 小（配置 + 验证）|
| **P1** | wiki mcp_server 加 `wiki_write` 工具（路径白名单 + 校验）| Agent 能写 wiki | 中 |
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

## §7 待你决策

| # | 决策点 | 选项 | 我的建议 |
|---|--------|------|----------|
| 1 | 接入目的（路线）| A 查 / B 写 / C 存 | **A 先行**，验证后 B；C 不做 |
| 2 | 传输方式 | streamable_http / sse / stdio | **streamable_http**（wiki --http 支持）|
| 3 | 文档放哪 | 已在 multi_agent（本文件）| ✅ 已定 |
| 4 | 端口冲突核查 | 8010 vs 8010？| 需验证后定 |

---

> 📌 **维护**：本设计评审通过 → `git mv` 转正 `docs/方案/`；实施后更新 `docs/功能更新日志.md`。
