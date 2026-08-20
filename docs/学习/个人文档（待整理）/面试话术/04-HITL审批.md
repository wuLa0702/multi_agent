# HITL审批 面试话术

> 📌 **关联描述点**：`面试/2026-08-12-面试描述点-HITL审批-v1.md`
> 📊 **状态**：待背
> 🔄 **最后更新**：2026-08-14

---

## 一、HITL整体设计

### 问题
什么是人在回路（HITL）？你们是怎么做的？

### 标准版话术（总分总）

【总·30秒】
"HITL是人在回路——在Agent执行过程中，遇到需要人工确认的环节就暂停，等人审批后再继续。我做的不是简单弹窗，是基于interrupt/resume基建的完整审批机制，覆盖需求澄清、高风险审批等四个场景，审批后能从断点精确恢复，不是重新跑。"

【分·90秒】
"四个场景用同一套机制：
1. **需求澄清**：Agent觉得需求不明确，主动问用户，比如'你要调研的是MCP协议还是MCP服务器？'
2. **高风险审批**：调用敏感工具前暂停，比如删除文件、发布报告，等人确认
3. **修订上限**：审核打回超过N轮，找人介入判断，防止无限循环
4. **恢复链路**：审批通过后从断点精确恢复，不是从头重跑

核心机制是：interrupt_on命中 → 触发中断 → SSE推approve事件给前端 → 前端弹审批卡 → 用户点同意/拒绝 → 调审批API → resume从checkpoint恢复继续执行。

为什么要做这个？多Agent系统是黑盒，跑十几分钟出结果，如果中间做错了用户没法干预，只能等跑完再重来。HITL让用户能在关键节点介入，既保证安全又节省时间。"

【总·20秒】
"HITL区分初级和高级——初级是弹窗，高级是interrupt/resume基建上的完整审批机制，支持断点恢复和防伪造，每个环节都踩过真坑。"

### 追问预案

| 追问 | 答题要点 |
|------|---------|
| 哪些操作需要审批？ | 可配置的，interrupt_on按工具名白名单配置，默认关，需要时打开 |
| 用户拒绝了怎么办？ | Agent收到reject，要么换方案，要么告诉用户任务终止 |
| 用户修改参数怎么办？ | 支持edit决策，用户可以修改工具参数后再批准 |
| 审批超时怎么办？ | 有超时机制，超时后默认拒绝或继续等待，可配置 |

### 一句话记忆
**HITL = interrupt中断 + approve审批 + resume断点恢复，四场景一机制。**

---

## 二、技术实现细节

### 问题
HITL的技术实现具体是怎么做的？中断和恢复的原理是什么？

### 标准版话术（总分总）

【总·30秒】
"三层实现：interrupt_on风险分级配置中断点，SSE approve事件通知前端，AsyncSqliteSaver做checkpoint断点恢复。审批通过后用checkpoint_id精确恢复到中断的那个步骤，不是重新跑。"

【分·90秒】
"具体三层：

**① 中断层：interrupt_on风险分级**
- 按工具名配置白名单，比如['delete_file', 'publish_report']
- Agent调用这些工具前，框架自动触发中断，暂停执行
- 可配置化，默认关闭，需要时打开，不影响普通流程

**② 通知层：SSE approve事件**
- 中断发生时，推一个approve事件给前端，带三个关键ID：run_id（本次对话流）、checkpoint_id（恢复用的快照）、call_id（具体哪个工具调用）
- 前端收到后弹审批卡，展示'Agent要执行XX操作，是否同意？'
- 用户点同意/拒绝，调POST /v1/chat/approve接口

**③ 恢复层：checkpoint resume**
- AsyncSqliteSaver每执行一个super-step就落库一次，存完整的执行快照
- 审批通过后，用checkpoint_id找到对应的快照，从断点继续执行
- 不是从头重跑，是精确恢复到中断的那一步，前面的搜索、分析结果都保留"

【总·20秒】
"三层配合：配置决定在哪中断，SSE负责通知用户，checkpoint负责精确恢复——这是完整的审批闭环。"

### 追问预案

| 追问 | 答题要点 |
|------|---------|
| checkpoint存的是什么？ | 完整的Agent状态：对话历史、工具调用结果、当前执行位置，恢复时直接加载 |
| super-step是什么？ | Agent的一次完整思考+行动循环，每完成一个就落一次库 |
| 审批接口为什么用REST不用SSE？ | 审批是客户端→服务器的操作，SSE是单向推送，REST POST更简单清晰 |
| 多用户场景下审批怎么隔离？ | 单用户项目，按thread_id隔离会话，每个会话有独立的审批状态 |

### 一句话记忆
**interrupt_on配置中断 + SSE approve通知 + checkpoint resume恢复 = 三层审批闭环。**

---

## 三、踩过的坑（主动讲，证明实战）

### 问题
做HITL的时候遇到过什么问题？怎么解决的？

### 标准版话术（总分总）

【总·30秒】
"踩过三个真坑，都是实证发现的：astream_events不产中断事件、伪造checkpoint会静默新跑、call_id缺失导致恢复失败。每个都修了，现在HITL是实测通过的。"

【分·90秒】
"三个坑具体是：

**坑1：astream_events不产on_interrupt事件**
- 一开始以为用官方的astream_events就能捕获中断，结果发现这个API根本不产生on_interrupt事件
- 解决：改用GraphCallbackHandler，在图执行的回调里采集中断状态，实证验证可行
- 教训：官方文档说的功能不一定真的有，要实测验证

**坑2：伪造checkpoint_id会静默新跑**
- 如果用户传一个不存在的checkpoint_id，框架不报错，而是静默开一个新会话从头跑
- 这很危险——用户以为是恢复，其实是新跑，状态全丢了
- 解决：加checkpoint_exists校验，不存在就返回RESUME_NOT_FOUND错误，不静默新跑
- 教训：恢复操作必须校验快照存在性，不能默认成功

**坑3：call_id缺失导致恢复失败**
- 官方HITL的action_request只含name/args/description，**不带call_id**——但我们的测试数据带了call_id，代码就假设它一定存在、直接拿它定位；真实链路一跑匹配不到action，恢复走不下去
- 解决：双管齐下——① `_find_action_index`三级fallback（显式call_id → `action-{seq}`序号 → 单action兜底index 0），不依赖call_id一定存在；② 中断上下文+决策落Redis，resume时`getdel`原子读出decisions按序喂回框架
- 教训：关键ID不能假设一定存在；测试数据形态≠真实框架形态，必须实测验证（同坑1方法论）"

【总·20秒】
"这三个坑让HITL从'能跑'变成'可靠'——每个坑都是实证发现的，不是纸上谈兵，这也是我觉得这个功能有高级感的原因。"

### 追问预案

| 追问 | 答题要点 |
|------|---------|
| 怎么发现这些坑的？ | 写测试用例实测，每个场景都跑一遍，不是只看文档 |
| 还有其他坑吗？ | 审批状态存内存的话重启会丢，后来改存Redis/数据库，多进程也不丢 |
| 怎么保证恢复后状态一致？ | checkpoint存完整快照，包括对话历史和工具结果，恢复时全量加载 |

### 一句话记忆
**三个实证坑：事件不产出→换回调、伪造快照静默新跑→加校验、call_id缺失→加fallback。**

---

## 四、核心概念辨析：super-step / checkpoint / checkpoint_id / run_id

> 面试被追问"checkpoint 存的是什么？颗粒度多大？resume 传哪个 ID？"之前先吃透这里。
> 依据：LangGraph checkpoint 官方语义（每 super-step 存一份快照）+ 本项目实现
> （backend/src/api/chat.py、agent/hitl/hitl.py）。

### 问题
super-step、checkpoint、checkpoint_id、run_id 分别是什么？颗粒度怎么理解？resume 到底从哪恢复？

### 标准版话术（总分总）

【总·30秒】
"三个概念别搞混：super-step 是执行段，checkpoint 是执行段结束时存的完整状态快照，checkpointer 是把它写进库的存储组件。checkpoint 的颗粒度不是每个节点一次、也不是每个对话一次，而是每个 super-step 一次。"

【分·90秒】
"拆开讲：

**① super-step（超步，执行段）**
- 从当前状态连续跑节点、直到'停'为止的一段执行
- 停的条件：自然终止（没节点可跑了）或 撞上 interrupt（命中 interrupt_on，工具执行前暂停）
- 不数节点——一个 super-step 可能跑 0/1/多个节点，全看什么时候停

**② checkpoint（检查点/快照，状态数据本身）**
- 每次 super-step 结束，checkpointer 存一份完整快照：消息历史 + channel 值 + 版本信息 + metadata + pending writes
- 颗粒度 = 每个 super-step 一个 checkpoint_id；一次对话是一串 checkpoint（thread 串起）
- '一个对话一个 checkpoint' 的直觉，其实是'thread 最新一个 checkpoint 代表当前状态'

**③ checkpointer（AsyncSqliteSaver，存储机制）**
- 负责把快照落库；resume 时按 checkpoint_id 精确加载某一份快照继续跑

**④ ID 关系链路（从大到小）**
- thread_id/session_id = 会话（整个聊天，跨多轮）
- run_id = 会话里的一次对话（一条用户消息触发的一轮执行，本项目每次 chat 请求 uuid 生成）
- checkpoint_id = 这一轮里的某个中间快照（super-step 粒度，resume 恢复键）
- call_id = 具体哪个工具调用（多 action 顺序匹配键）"

【总·20秒】
"层级一句话：会话里有多次对话，一次对话里有多个 super-step，每个 super-step 结束落一个 checkpoint——resume 就是精确加载某一份 checkpoint 快照，不是重跑。"

### 关系链路（背这张图）

```
thread_id/session_id（会话）
  └─ run_id（一次对话流，uuid/次请求）
       ├─ super-step①（执行段：跑到停）──> checkpoint①（快照）
       ├─ super-step②（执行段：跑到停）──> checkpoint②（快照）
       └─ … 直到自然终止或撞上 interrupt
resume = 传 thread_id + checkpoint_id，加载那一个停点的快照继续
```

### 快照里有什么（追问"checkpoint 存的是什么"）

| 字段 | 含义 |
|------|------|
| channel_values | 各状态通道当前值（消息列表/中间变量）|
| channel_versions / versions_seen | 版本号，保证恢复时不重复、不丢更新 |
| metadata | 时间戳等元信息 |
| pending writes | 未写入的挂起更新（interrupt 现场）|

### 一句话记忆
**super-step 是"跑到停的执行段"，checkpoint 是"停点时存的完整快照"，checkpointer 是"写库的组件"；会话>对话>快照，resume 用 checkpoint_id 精确加载某一停点。**

### 追问预案

| 追问 | 答题要点 |
|------|---------|
| checkpoint 每个节点都存吗？ | 不，每个 super-step 存一次；一个 super-step 可能含多个（并行）节点，合起来存一份 |
| 一次对话几个 checkpoint？ | 一串——每个 super-step 一个，最新那个代表当前状态 |
| resume 传的是 run_id 还是 checkpoint_id？ | 本项目字段名是 resume_run_id，但语义上是 checkpoint_id（chat.py 里 checkpoint_exists + checkpoint_id=req.resume_run_id），别被字段名带偏 |
| run_id 和 thread_id 什么关系？ | thread_id 是会话（跨轮），run_id 是会话里一轮执行（本项目每次 chat 流一个 uuid）|

---

## 五、恢复流程核心链路（代码级支撑）

> 面试被问"审批通过后到底怎么恢复"时，从 6 跳链路里挑关键讲。
> 源码位置：frontend/src/lib/stores/chatStore.ts、backend/src/api/chat.py、
> backend/src/agent/main_agent.py、backend/src/agent/hitl/pending.py。

### 本质一句话
**resume = 拿 checkpoint_id 让 LangGraph 加载那一个停点的快照 + 用 Command(resume) 把审批决策喂回去**，被中断的工具在恢复后才真正执行。

### 核心链路图（start 事件之后）

```
start 事件（resumed=true）← chat.py:612
   │
   ▼ _emit_agent_events（chat.py:420）
   │  graph_input = Command(resume=decisions)   ← 关键①：决策喂回
   │  checkpoint_id = req.resume_run_id          ← 关键②：恢复键
   ▼ stream_agent_events（main_agent.py:614）
   │  config = {thread_id, checkpoint_id, callbacks:[HitlCallback]}
   │  input_payload = Command(resume=decisions)
   ▼ agent.astream_events(input_payload, config) ← 关键③：LangGraph 加载快照继续
   │  └ 框架内部：加载该 checkpoint → 被中断节点重跑 → consume 决策 → 工具真正执行
   ▼ token / tool_call / approve 事件继续推 SSE
```

### 6 跳核心代码

**Hop 0｜前端 resume 入口（审批卡确认 / 刷新弹窗殊途同归）**
```ts
// chatStore.ts:217
async resume(runId: string) {
  set({ pendingApprovals: [], pendingRunId: null });
  localStorage.removeItem(PENDING_RUN_KEY);
  startStream({ session_id: get().sessionId, resume_run_id: runId });
}
```

**Hop 1｜后端 resume 准备——决策读出 + 快照校验**
```python
# chat.py:374-417  _resolve_resume_context
is_resume = bool(req.resume_run_id)
if is_resume:
    resume_input = await consume(req.resume_run_id)   # Redis getdel 原子消费决策
if is_resume and resume_input is None:
    if not await checkpoint_exists(session_id, req.resume_run_id):
        yield error(RESUME_NOT_FOUND); return          # 防伪造快照静默新跑
```

**Hop 2｜决策包成 Command(resume)，连同 checkpoint_id 交给框架**
```python
# chat.py:461-470  _emit_agent_events
graph_input = Command(resume=resume_input) if resume_input else None
async for event in stream_agent_events(
    agent, lc_messages, context=chat_context,
    checkpoint_id=req.resume_run_id,   # 恢复键：精确快照
    hitl_callback=hitl_callback, run_id=run_id, graph_input=graph_input,
):
```

**Hop 3｜真正执行：astream_events 以 Command(resume) 作输入**
```python
# main_agent.py:657-668  stream_agent_events
config = _build_stream_config(context, checkpoint_id, hitl_callback)
input_payload = graph_input if graph_input is not None else {"messages": messages}
async for evt in agent.astream_events(input_payload, version="v2", context=context, config=config):
    seq, event = _dispatch_stream_event(evt, session_id, seq)
    if event is not None:
        yield event
```

**Hop 4｜config：checkpoint_id 进 configurable（"从哪恢复"的钥匙）**
```python
# main_agent.py:508-511  _build_stream_config
config = {"configurable": {"thread_id": context.session_id}}
if checkpoint_id:
    config["configurable"]["checkpoint_id"] = checkpoint_id
```

**Hop 5｜框架内部（黑盒，理解语义）**
拿到 configurable.checkpoint_id → 从 SQLite 加载快照 → 含 interrupt 的节点重跑 →
Command(resume) 的 decisions 成为 interrupt() 的返回值 → 挂起的工具真正执行 →
继续出 token；又命中 interrupt_on → 再暂停产新 approve 事件。

**Hop 6｜恢复后再中断也登记（finally 保证，防断点丢失）**
```python
# main_agent.py:672-686
finally:
    interrupted = await _register_interrupt_if_needed(hitl_callback, session_id)
if interrupted is not None:
    for action, review in _iter_action_reviews(interrupted["hitl_request"]):
        yield _build_approve_event(
            run_id=run_id,
            checkpoint_id=interrupted["checkpoint_id"],   # 新 checkpoint_id
            ...
        )
```

### 支撑数据流（Redis 侧）
consume()（pending.py:192）是恢复的数据源：getdel 原子读出 {"decisions": [...]}，
形态正好是 Command(resume=...) 需要的输入。读后即删 → 防并发双读；
主 key 过期（TTL 600s）→ 前端 404 提示重开。

### 一句话记忆
**consume 出决策 → Command(resume=决策) → astream_events(checkpoint_id) → 框架加载快照、重跑中断节点、真正执行工具。**
