# 持久化能力开发计划（评审稿）— Checkpointer 断点 + Store 记忆

> 📋 **规范**：遵循 `docs/规则/文档规范.md`
> 📌 **更新时间**：2026-08-04
> 📝 **版本变更记录**（永久保存，只追加不删除）：

> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1.3 | 2026-08-04 | §B.2 记忆写入策略改 **LLM 抽取式**（✅ 已实现：只存抽取事实非对话全文，修复"全量存"缺陷）；§3.3 补 LLM 抽取学习点 |
> | v1.2 | 2026-08-04 | 吸收评审修订：§2.0 挂载改同步 SqliteSaver（缺陷 1）；§A 恢复健壮性 + SSE 增量（缺陷 3/隐患 3）；§B memory/store 并行关系 + backend 前置 + Store 选型表（缺陷 2）；§C 新增高风险隐患缓解（写锁/thread_id 封装/细节优化） |
> | v1.1 | 2026-08-04 | §1.3 范围澄清（删 Redis 误导、标注单用户不扩多租户/云）；§2 新增「核心代码速览」（Checkpointer 三段 + Store 两段） |
> | v1 | 2026-08-04 | 初版：总分总结构持久化能力计划（Checkpointer 断点恢复 + Store 长期记忆） |

> **目录**：
> - §1 总：现状分析与目标
> - §2 分：开发计划（A Checkpointer / B Store / C 技术要点）
> - §3 总：里程碑、风险与学习点
>
> **关联文档**（本计划只聚焦存储，其他功能链接引用）：
> - 架构：`docs/架构/多agent项目-架构目录.md`（§2 目录树 / §2.1 能力落地位置对照）
> - 后端路线：`docs/归档/2026-08-04-后端开发计划-v1.md`（P0-P2 mock 真实化）
> - 接口：`docs/架构/参考-后端接口.md`

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
| Checkpointer 断点持久化（SQLite） | 向量库选型与 embedding 服务（P2 语义记忆的可选增强，可后置） |
| resume_run_id 真实现 + 审批真恢复 | 用户体系 / 多租户——**个人学习项目明确不做**：加 user_id 字段简单，但传播面广（所有表 / API 鉴权 / Agent 上下文 / checkpointer thread_id / store 分区 / 前端登录），单用户无此需求 |
| Store 长期记忆（文件记忆 + 语义记忆两层次） | 云上部署与水平扩展——单机部署（个人项目），无此需求 |
| thread_id ↔ session_id 映射约定 | Redis 记忆——**说明**：对话持久化始终在 SQLite（长期正确做法），Redis 仅作缓存（当前只用于 health），**不迁移** |

---

## 2. 分：开发计划

### 2.0 核心代码速览（先看代码，再看细节）

> 完整落地见 A/B 改造点；本速览为直观理解（API 与 langgraph-checkpoint-sqlite 3.1.0 / deepagents 一致）。

#### Checkpointer 核心三段（v1.2 修正：同步 SqliteSaver，方式 A）

```python
# ① 编译时挂载（main_agent.py）——图从无状态变有状态
# ⚠️ 必须用【同步】SqliteSaver（非 aio）：create_deep_agent 是同步初始化，
#    全局懒加载不在 async 上下文，aio 版连接无法持有（评审缺陷 1）
from langgraph.checkpoint.sqlite import SqliteSaver   # 非 aio.SqliteSaver！
saver = SqliteSaver.from_conn_string(str(get_checkpointer_path()))
saver.setup()                        # 建表 + 启用 WAL（缓解并发写锁）
_agent = create_deep_agent(
    model=get_chat_model(),
    checkpointer=saver,              # ← 框架内部自动兼容 async 流式调用
    middleware=[...],
)

# ② 每次执行必带 thread_id（stream_agent_tokens 内部封装，见 C.2）——⚠️ 不传直接报错
config = {"configurable": {"thread_id": session_id}}   # thread_id == session_id
async for evt in agent.astream_events(
    {"messages": messages}, version="v2", context=context, config=config
):

# ③ 审批恢复（chat.py resume 分支）——checkpoint_id 精确恢复挂起点
#    （含归属校验与失效兜底，见 A.2）
config = {"configurable": {"thread_id": session_id, "checkpoint_id": resume_run_id}}
```

#### Store 核心两段（v1.2 修正：memory 与 store 是并行能力，非递进）

```python
# ① 挂载 store（main_agent.py）——结构化键值记忆（持久化选 SqliteStore）
from langgraph.store.sqlite import SqliteStore
store = SqliteStore.from_conn_string(str(get_store_path()))
_agent = create_deep_agent(
    model=...,
    store=store,                     # 语义记忆：键值 + 检索（独立能力）
    # memory=[...] 需先落地 backend 文件系统（见 B.1 前置约束），P1 再启用
)

# ② 记忆写入 / 检索
await store.aput(("memory", session_id), "facts", {"事实": "..."})
results = await store.asearch(("memory", session_id))
```

---

### A. Checkpointer 断点持久化（P0，优先）

> 目标：对话图状态持久化到 SQLite，审批中断可精确恢复。

#### A.1 依赖与存储位置（v1.2 修正：同步 SqliteSaver）

- ⚠️ **必须用同步 `langgraph.checkpoint.sqlite.SqliteSaver`**（非 aio 版）——评审缺陷 1：
  `create_deep_agent` 是**同步初始化**函数，全局懒加载（get_agent）不在 async 上下文，
  aio 版连接无法正常持有（连接提前关闭/读写阻塞）；官方规范两种合法挂载：
  - **方式 A（推荐，适配单例）**：全局创建同步 SqliteSaver → `checkpointer=saver` 直接传入，
    框架内部自动兼容 async 流式调用（已验证：`create_deep_agent` 的 checkpointer 参数接受 `BaseCheckpointSaver`）
  - 方式 B（备选）：不全局挂载，仅在 `astream_events` 的 config 里传 saver 实例
- 存储：`data/checkpoints.db`（`core/paths.py` 加 `get_checkpointer_path()`，路径自适应，目录自动创建）
- `saver.setup()` 建表 + 启用 **WAL 模式**（缓解并发写锁，见 C.1）
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

#### A.5 恢复健壮性（v1.2 新增，评审缺陷 3）

恢复不能只传 checkpoint_id，必须做**快照链上下文校验**：

| 异常场景 | 校验 | 兜底 |
|---------|------|------|
| checkpoint_id 不属于当前 thread_id（脏数据） | langgraph 校验（checkpoint 按 thread 隔离查询） | 捕获 → 404 `RESUME_NOT_FOUND` → 前端提示「断点已失效，可重新开始」 |
| 快照链被截断 / 旧 checkpoint 过期删除 | 恢复前确认 checkpoint 存在且属于该 thread | 同上友好降级，不抛内部异常 |
| 校验失败一律转业务错误码 | `chat.py` resume 分支 try/except 包裹 | SSE `error` 事件（code=RESUME_NOT_FOUND, retryable=false） |

#### A.6 SSE 增量事件（v1.2 新增，评审隐患 3）

resume 恢复时**旧事件会完整重放**给前端 → 消息重复渲染/重复弹窗。缓解：
- `tool_call`：陈旧 running 不覆盖已完成状态（**已有保护**，resume 重放天然过滤）
- `token`/`subagent` 重放：前端按 message id / node key 幂等（subagent 按 name+seq 定位已有）；
  后端可选：resume 响应中带 `resumed_checkpoint_id`，前端对已渲染内容去重
- 验收：中断恢复后前端无重复消息、无重复弹窗

#### A.7 验收

- 中断 → resume → 从断点继续（日志/工具调用不重复）
- 刷新进程后（重启后端）仍能恢复（SQLite 持久化非内存）
- 多会话并发互不干扰（thread_id 隔离）
- 脏 checkpoint_id 恢复 → 友好错误提示不 500

### B. Store 长期记忆（P1）

> 目标：跨会话记忆——新会话能回忆此前关键事实。
> ⚠️ v1.2 修正（评审缺陷 2）：**memory 与 store 是并行能力，不是两层递进记忆**：
> - `memory` 参数 = **文件型渐进记忆**（AGENTS.md），属于 backend 文件后端体系
> - `store` 参数 = **独立结构化键值存储**（键值 + 语义检索），与文件记忆互不依赖

#### B.0 前置约束（评审缺陷 2，必须先落地）

`MemoryMiddleware` 构造签名**强依赖 `backend: BackendProtocol`**（已验证源码）——
记忆文件读写走 backend 文件 API。项目当前用 deepagents 默认 StateBackend（进程内存），
**直接启用 MemoryMiddleware 会出现文件读写路径异常**。

- **P1 第一步：落地 `core/backend.py`**——封装 FilesystemBackend（或 StateBackend + 文件落盘
  CompositeBackend），记忆目录 `data/memory/` 映射 backend 文件路径
- 之后再启用 `memory=[...]`

#### B.1 文件记忆（MemoryMiddleware，backend 前置后启用）

- deepagents 原生 `MemoryMiddleware`：基于 AGENTS.md 的渐进记忆——对话关键事实写入记忆文件，后续会话自动注入
- 存储位置：`data/memory/`（backend 文件系统管理）
- 改造点：`main_agent.py` 加 `memory=[str(get_memory_dir())]` + backend
- **噪音控制**（细节优化）：记忆写入阈值——仅当对话出现「明确事实/用户偏好/关键决策」时写入（简化版：用户消息含偏好关键词 或 assistant 输出含决策性内容；后续可接 LLM 抽取）
- 验收：会话 A 提到事实 X → 新会话 B 问 X → Agent 能回忆

#### B.2 语义记忆（Store，独立能力可先行）

- `create_deep_agent(store=BaseStore)`——langgraph store 存结构化记忆（键值 + 检索）
- **存储选型对比表**（评审决策点）：
  | 选型 | 持久化 | 场景 | 结论 |
  |------|--------|------|------|
  | `InMemoryStore` | ❌ 进程内存 | 仅调试/开发 | 不用于生产 |
  | `SqliteStore` | ✅ SQLite | 单机持久化 | **推荐**（复用 checkpoint-sqlite 包） |
  | `RedisStore` | ✅ Redis | 高并发备选 | 个人项目不启用 |
- 写入时机：**LLM 抽取式记忆（v1.3 ✅ 已实现）**——对话结束后 LLM 判断本段对话
  是否有长期记忆价值（用户事实/偏好/决策），有则抽取一句话事实存入，无则跳过
  - 实现：`agent/memory_store.py::extract_memory_fact`（抽取提示词 + 输出解析，
    LLM 异常降级 None——宁可不记不错记）；chat.py 先抽取再存
  - ⚠️ 修正背景：原简化版"assistant 回复摘要存 store"导致**所有对话全文进记忆库**
    （仅长度过滤）→ 记忆被普通问答填满、注入时污染上下文。用户评审发现后改抽取式
- 验收：重启后端后记忆仍在（SqliteStore 持久化）；普通问答不新增记忆、事实性对话新增

#### B.3 与现有分层关系

- 依赖单向不变：`api → agent → {mcp, sandbox, memory, db}`——memory 层补实
- 架构文档 `agent/memory/` 占位目录落地（state_store Redis 短期 + vector_store 长期——向量库选型后置，先用文件/键值记忆）

### C. 高风险落地隐患与缓解（v1.2 重写，评审意见）

#### C.1 SQLite 并发写锁（最严重，单机多浏览器并发必踩）

多浏览器并发对话同时触发断点落库 → `database is locked` 高频报错。三层缓解：

1. **WAL 模式 + busy timeout**：`SqliteSaver.setup()` 启用 WAL（读写不互斥），连接设 `busy_timeout=5000`
2. **协程并发限流**：`async.Semaphore(4)` 包裹 `stream_agent_tokens`（对话流并发上限 4，超出排队）
3. **长期备选**：记忆缓存走 Redis，checkpoint 仍落 SQLite（单机不启用）

#### C.2 thread_id 兜底封装（杜绝漏传 500）

`stream_agent_tokens` **内部自动**从 `context.session_id` 拼装 config：

```python
async def stream_agent_tokens(agent, messages, context=None):
    config = None
    if context is not None and context.session_id:
        config = {"configurable": {"thread_id": context.session_id}}
    async for evt in agent.astream_events(
        {"messages": messages}, version="v2", context=context, config=config
    ):
        ...
```

- 上层 `chat.py` 零感知（不手动传 config），前端传参遗漏也不会 500

#### C.3 SSE 增量事件重放（见 A.6）

#### C.4 细节优化清单（评审）

| # | 项 | 说明 |
|---|----|------|
| 1 | **requirements.txt 版本锁定** | `langgraph-checkpoint-sqlite==3.1.0`、`langgraph-checkpoint==4.1.1` 显式锁定，防环境迁移不兼容 |
| 2 | **Store 选型表** | 见 B.2（InMemory 调试 / SqliteStore 推荐 / RedisStore 备选） |
| 3 | **MemoryMiddleware 噪音控制** | 见 B.1（写入阈值规则，避免每轮写冗余事实） |
| 4 | **资源生命周期** | 连接池管理（SqliteSaver 单例复用）；`get_checkpointer_path()` 自动建目录；**过期 checkpoint 清理**（保留每 thread 最近 N 个 / 30 天，防 DB 无限膨胀） |
| 5 | **日志埋点** | 断点保存 / 恢复 / 记忆读写关键日志（logging.getLogger(__name__)），方便排查会话恢复异常 |
| 6 | **与 TokenUsageMiddleware 联动** | Checkpointer 完整读取 thread 全部 messages → 前端 XX/128k 上下文展示更准（替代现 chars/4 估算的写入源，见接口文档 v1.2） |
| 7 | **目录落地 + 初始化脚本** | `agent/memory/` 规范落地；新增 `scripts/init_data.py` 自动创建 `data/checkpoints.db`、`data/memory/` |

#### C.5 技术要点（横切）

1. **thread_id 必传**：统一由 C.2 封装，调用方零感知
2. **同步 Saver 在 async 流式**：sync SqliteSaver 由框架内部调度兼容（方式 A 已验证）
3. **并发安全**：WAL + Semaphore 限流（C.1）
4. **schema/迁移**：checkpoint 表由 Saver 自管（自动建表），业务表零改动
5. **测试策略**：mock LLM + tmp_path——①中断 → resume 恢复状态一致 ②重启后恢复 ③多线程并发 ④脏 checkpoint_id 友好降级
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
6. **LLM 抽取式记忆（v1.3 ✅ 已实现）**：对话 → LLM 判断"值得长期记忆吗" → 抽取一句话事实（用户事实/偏好/决策）→ 存 store。核心是"什么值得记住"的判断——全量存会污染上下文，抽取式是真实 Agent 产品的标准做法

> 📌 **评审结论预期**：计划按「断点 → 文件记忆 → 语义记忆」三阶段推进，
> P0 解决审批恢复真实性问题（当前伪恢复），P1/P2 补记忆能力。
> 依赖已就绪（checkpoint-sqlite 已装），无架构级改动，风险集中在 thread_id 与中断恢复协议对齐。
