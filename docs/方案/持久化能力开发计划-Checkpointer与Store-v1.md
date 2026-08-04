# 持久化能力开发计划（评审稿）— Checkpointer 断点 + Store 记忆

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-04
> 📝 **版本变更记录**（永久保存，只追加不删除）：

> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1 | 2026-08-04 | 初版：总分总结构持久化能力计划（Checkpointer 断点恢复 + Store 长期记忆） |

> **目录**：
> - §1 总：现状分析与目标
> - §2 分：开发计划（A Checkpointer / B Store / C 技术要点）
> - §3 总：里程碑、风险与学习点
>
> **关联文档**（本计划只聚焦存储，其他功能链接引用）：
> - 架构：`docs/架构/多agent项目-架构目录-v1.md`（§2 目录树 / §2.1 能力落地位置对照）
> - 后端路线：`docs/方案/后端开发计划-v1.md`（P0-P2 mock 真实化）
> - 接口：`docs/方案/后端接口对接文档-v1.md`

---

## 1. 总：现状分析与目标

### 1.1 现状盘点（2026-08-04 实测）

| 能力 | 现状 | 代码证据 |
|------|------|---------|
| **Checkpointer** | ❌ **无**——编译图无状态，进程内单例只构建一次，无断点持久化 | `agent/main_agent.py:116`「编译图无状态（无 checkpointer）」 |
| **resume_run_id** | ❌ **接口占位 501**——参数已定义但 handler 直接返回"尚未实现" | `api/chat.py:104`「resume_run_id（审批断点恢复）尚未实现」 |
| **审批恢复** | ⚠️ **伪恢复**——approve 后前端重开流（重新发消息模式），未真正从挂起图恢复 | `api/chat.py` resume 分支 501 |
| **Store 记忆** | ❌ **无**——`agent/memory/` 空目录占位；`create_deep_agent(store=...)` 未使用 | `agent/memory/` 无文件 |
| **Redis** | ⚠️ 仅 health 检查连接池，未用于记忆 | `core/redis.py` |
| **依赖（已装未用）** | ✅ `langgraph-checkpoint` 4.1.1 + `langgraph-checkpoint-sqlite` 3.1.0（SqliteSaver）+ `langgraph-runtime-inmem` 0.31.1 | pip list 实测 |

**结论：项目确实缺乏持久化能力**——对话图执行状态不可恢复、无跨会话记忆。

### 1.2 为什么重要

1. **审批恢复的真实性**：当前 approve/reject 后前端"重新发流"，已完成步骤会重跑（浪费 token、结果可能漂移）；Checkpointer 才能从 interrupt 挂起点**精确恢复**
2. **记忆能力**：多 Agent 产品差异化核心——新会话能否回忆此前关键事实
3. **LangGraph 核心学习点（面试导向）**：Checkpointer 状态快照/恢复机制、interrupt/resume 生命周期是本项目手写学习路线的关键一环（见 `.claude/rules/02-hands-on-training.md`）

### 1.3 范围与边界

| 在本计划内 | 不在本计划内 |
|-----------|-------------|
| Checkpointer 断点持久化（SQLite） | 向量库选型与 embedding 服务 |
| resume_run_id 真实现 + 审批真恢复 | Redis 记忆重构（维持现状） |
| Store 长期记忆（文件记忆 + 语义记忆两层次） | 用户体系 / 多租户隔离 |
| thread_id ↔ session_id 映射约定 | 云上部署与水平扩展 |

---

## 2. 分：开发计划

### A. Checkpointer 断点持久化（P0，优先）

> 目标：对话图状态持久化到 SQLite，审批中断可精确恢复。

#### A.1 依赖与存储位置

- 复用已装的 `langgraph_checkpoint.sqlite.aio.SqliteSaver`（async 版，与项目异步流式匹配）
- 存储：`data/checkpoints.db`（`core/paths.py` 加 `get_checkpointer_path()`，路径自适应）
- checkpoint 表由 SqliteSaver **自动建表自管**（checkpoints/checkpoint_blobs/checkpoint_writes），业务 schema 不动

#### A.2 改造点

| 文件 | 改动 |
|------|------|
| `agent/main_agent.py` | `create_deep_agent(checkpointer=SqliteSaver(...))`——编译图从无状态变有状态 |
| `agent/main_agent.py` `stream_agent_tokens` | **必须传 `config={"configurable": {"thread_id": session_id}}`**——⚠️ 关键坑：不传 thread_id 会直接报错（main_agent 注释已预警，这是当初不加 checkpointer 的原因） |
| `api/chat.py` | resume_run_id 真实现：`resume_run_id` = checkpoint id → `astream(..., config={"configurable": {"thread_id": session_id, "checkpoint_id": resume_run_id}})` |
| `core/paths.py` | 加 `get_checkpointer_path()` |

#### A.3 thread_id ↔ session_id 映射约定（核心设计）

```
session_id（业务会话 UUID）== thread_id（LangGraph 图执行线）
```

- 每会话一条执行线，checkpoint 按 thread_id 分组存快照链
- 审批中断（interrupt 挂起）→ checkpoint 落库 → 前端 resume 携带 `resume_run_id`（checkpoint id）→ 从精确断点恢复
- 复用现有 `session_id` 无需新字段；审批断点恢复的 `pendingRunId`（localStorage）语义对齐

#### A.4 审批闭环升级（伪恢复 → 真恢复）

```
现在（伪）：approve → POST approve 202 → 前端重开流（message 模式）→ 重跑
升级后（真）：approve → POST approve 202 → 前端 resume_run_id=checkpoint_id
              → astream 从 interrupt 挂起点继续 → 已完成步骤不重跑
```

#### A.5 验收

- 中断 → resume → 从断点继续（日志/工具调用不重复）
- 刷新进程后（重启后端）仍能恢复（SQLite 持久化非内存）
- 多会话并发互不干扰（thread_id 隔离）

### B. Store 长期记忆（P1）

> 目标：跨会话记忆——新会话能回忆此前关键事实。分两层次渐进。

#### B.1 层次一：文件记忆（MemoryMiddleware）

- deepagents 原生 `MemoryMiddleware`（`memory=["..."]` 参数）：基于 AGENTS.md 的渐进记忆——对话关键事实写入记忆文件，后续会话自动注入
- 存储位置：`data/memory/`（get_app_dir() 下，路径自适应）
- 改造点：`main_agent.py` 加 `memory=[str(get_memory_dir())]`
- 验收：会话 A 提到事实 X → 新会话 B 问 X → Agent 能回忆

#### B.2 层次二：语义记忆（Store）

- `create_deep_agent(store=BaseStore)`——langgraph store 存结构化记忆（键值 + 检索）
- 存储选型（评审决策点）：`InMemoryStore`（简单、进程内存）vs `SqliteStore`（持久化，复用 checkpoint-sqlite 包）vs Redis（现有连接）
- 写入时机：对话关键事实抽取（简化版：assistant 回复摘要存 store，后续可接 LLM 抽取）
- 验收：重启后端后记忆仍在（选持久化 store）

#### B.3 与现有分层关系

- 依赖单向不变：`api → agent → {mcp, sandbox, memory, db}`——memory 层补实
- 架构文档 `agent/memory/` 占位目录落地（state_store Redis 短期 + vector_store 长期——向量库选型后置，先用文件/键值记忆）

### C. 技术要点（横切）

1. **thread_id 必传**：所有 astream/invoke 调用统一 `config={"configurable": {"thread_id": session_id}}`——遗漏即报错（已预警）
2. **async Saver**：项目走异步流式，用 `aio.SqliteSaver`（async 版本）；连接管理与请求生命周期
3. **并发安全**：多会话并发执行——SqliteSaver 线程/协程安全需验证（官方文档确认）
4. **schema/迁移**：checkpoint 表由 Saver 自管（自动建表），业务表零改动
5. **测试策略**：mock LLM + tmp_path——①中断 → resume 恢复状态一致 ②重启后恢复 ③多线程并发
6. **契约同步**：resume 真实现后，接口文档 v1.2 的「resume_run_id 501」标注改 ✅

---

## 3. 总：里程碑、风险与学习点

### 3.1 建议节奏（每阶段独立验收）

```
阶段一 P0（Checkpointer）  → 断点落库 + resume 真实现 + 审批真恢复（后端 2-3 提交）
阶段二 P1（文件记忆）      → MemoryMiddleware + data/memory/（1-2 提交）
阶段三 P2（语义记忆）      → store 接入 + 关键事实存储（1-2 提交，选型先拍板）
每阶段：pytest 全绿 + 浏览器实测（审批中断恢复 / 跨会话回忆）+ 契约同步
```

### 3.2 风险与依赖

| 风险 | 缓解 |
|------|------|
| astream 不带 thread_id 直接报错 | 统一封装 stream_agent_tokens（config 内部拼装，调用方零感知） |
| interrupt 恢复与 SSE 事件对齐（恢复时重放旧事件 vs 只发增量） | P0 先行对齐事件协议（tool_call 陈旧 running 不覆盖已有保护已存在） |
| SqliteSaver 并发写锁 | 用官方 aio.SqliteSaver + 连接池；压测多会话并发 |
| store 选型（InMemory/SQLite/Redis） | 评审决策点先行拍板（建议 SqliteStore 持久化） |
| MemoryMiddleware 记忆写入过频/噪音 | 配置写入阈值 + 后续接 LLM 抽取 |

### 3.3 学习点（面试 / 手写训练路线标注）

1. **LangGraph Checkpointer 机制**：状态快照（checkpoint 序列）+ 恢复原理——图执行状态如何在中断/恢复间保持一致
2. **interrupt / resume 生命周期**：审批挂起 → 快照落库 → checkpoint_id 恢复 → 从断点继续（不重跑已完成节点）
3. **thread_id 设计**：执行线隔离——同会话多轮共用一条线，checkpoint 按线分组
4. **MemoryMiddleware 记忆写入时机**：渐进记忆如何决定"什么值得记住"（写入触发条件）
5. **Store 与 Checkpointer 分工**：Checkpointer = 执行状态（如何走到这），Store = 知识沉淀（学到了什么）——两者的本质区别

> 📌 **评审结论预期**：计划按「断点 → 文件记忆 → 语义记忆」三阶段推进，
> P0 解决审批恢复真实性问题（当前伪恢复），P1/P2 补记忆能力。
> 依赖已就绪（checkpoint-sqlite 已装），无架构级改动，风险集中在 thread_id 与中断恢复协议对齐。
