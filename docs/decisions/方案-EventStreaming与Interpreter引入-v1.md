# Event Streaming 与 Interpreter 引入方案 v1（学习 Demo · 评审稿）

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-05
> 📝 **版本变更记录**（永久保存，只追加不删除）：
> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1.1 | 2026-08-05 | §7 新增**完整核心代码章节**（文档规范 v4 新规则：设计方案必含核心代码）——事件分发器全量 / SSE 事件模型 / _event_stream 增量 / 解释器挂载 / config 字段；§3.1 代码片段标注指向 §7；§6.2 风险清单补 1 条（v3 投影 API 实测前置已在实施风险，补"核心代码以实测为准"） |
> | v1 | 2026-08-05 | 初版：基于版本可行性核实的引入方案——§2 现状盘点与版本核实（v3 在 langchain_core 1.3.14 支持且源码标注 beta；quickjs 可装）；§3 设计（event-streaming v3 迁移 + SSE 契约补齐 + interpreters + 两者结合 + 安全边界）；§4 兼容回退；§5 测试；§6 优先级；§7 风险自检；附录版本核实记录 |

> **目录**：
> - §1 总：背景、目标与范围
> - §2 分·现状盘点与版本可行性核实
> - §3 分·设计（v3 迁移 / SSE 补齐 / Interpreters / 结合点 / 安全边界 / 配置）
> - §4 分·兼容与回退
> - §5 分·测试设计
> - §6 总：优先级（P0/P1/P2）与风险自检
> - §7 分·完整核心代码（事件分发器 / SSE 事件模型 / chat 增量 / 解释器挂载 / config）
> - 附录：版本核实记录

> **关联文档**：
> - 官方 event-streaming：https://docs.langchain.com/oss/python/deepagents/event-streaming（v3 typed-projection，beta）
> - 官方 interpreters：https://docs.langchain.com/oss/python/deepagents/interpreters（QuickJS，beta）
> - SSE 契约 v3：`docs/方案/后端接口对接文档`（事件类型定稿：token/tool_call/approve/summarize/subagent/done/error）
> - 沙箱能力计划：`docs/decisions/方案-沙箱能力开发计划-v1.md`（执行层，本方案安全边界复用）

---

## 1. 总：背景、目标与范围

### 1.1 背景

**定位**：学习 Demo——用户明确"通过工程实践学习新技术和思维方式"，非生产刚需。
两个官方 beta 能力（均已核实可落地）：

1. **Event Streaming（v3 typed-projection）**：Deep Agents 在 LangGraph 流式之上的
   子代理级扩展——`stream.subagents` 独立流句柄（递归嵌套）、`stream.tool_calls`、
   `stream.messages`。思维方式：**从"手写事件过滤"到"按投影声明式消费"**。
2. **Interpreters（QuickJS）**：图内代码执行——`eval` 工具 + PTC（程序化工具调用）
   + `task()` 动态子代理。思维方式：**编排从"模型轮次"移到"代码"**——模型思考
   "做什么"，代码执行"怎么做"（循环/分支/并行批次）。

当前项目：streaming 用 `astream_events v2` 只出 token（`stream_agent_tokens`，
其余事件全丢弃）；SSE 契约 v3 的 `tool_call/subagent/approve` 事件**已定稿未实现**；
无解释器。

### 1.2 目标

1. **v3 迁移（P0）**：`stream_agent_tokens` 从"只出 token"升级为事件分发器——
   token / tool_call / subagent 三投影，回归不破坏现有 SSE 协议
2. **SSE 契约补齐（P1）**：`tool_call`、`subagent` 事件落地（契约 v3 定稿的
   空白补上）；`approve` 仍留后续（与 interrupt 权限联动，本次不激活）
3. **Interpreters 引入（P2）**：QuickJS `eval` 工具 + PTC 只读白名单 +
   `task()` 动态子代理（batch 扇出 demo）
4. **学习目标显性化**：每个 P 级对应一个"新思维方式"学习点（§3 标注），
   配套最小 Demo 用例（§5）

### 1.3 范围

| 在本方案内 | 不在本方案内 |
|-----------|-------------|
| v2→v3 流式迁移（token/tool_call/subagent 投影） | approve 事件 + interrupt 权限激活（依赖前端审批面板，后续） |
| SSE 协议补 tool_call/subagent 事件 | summarize 事件（契约定稿项，无场景） |
| QuickJS eval 工具 + PTC 只读白名单 + task() 动态子代理 demo | PTC 暴露文件/沙箱工具（**安全红线：只读白名单**） |
| 解释器与沙箱的分工边界（图内计算 vs 环境执行） | CodeInterpreter 模式改造（thread/turn/call 多模式对比留学习笔记） |

---

## 2. 分·现状盘点与版本可行性核实

### 2.1 项目 streaming 现状（三层，代码级）

| 层 | 文件 | 现状 |
|----|------|------|
| 流式源头 | `main_agent.py:353` `stream_agent_tokens` | `astream_events(version="v2")` 监听 `on_chat_model_stream`，**只 yield token**——工具调用/子代理/图状态事件全被 `continue` 丢弃 |
| SSE 消费 | `chat.py:250` `_event_stream` | start → token×N → done/error；`ToolAuditMiddleware` 记工具调用（走中间件层） |
| 事件协议 | `schemas/events.py` | StartEvent/TokenEvent/DoneEvent/ErrorEvent 已实现；契约 v3 的 tool_call/subagent/approve **定稿未实现**（注释"后续阶段"） |

### 2.2 版本可行性核实（2026-08-05 本地实测）

| 项 | 核实结果 | 结论 |
|----|---------|------|
| v3 event-streaming | langchain_core 1.3.14 `astream_events` 签名含 `Literal["v1","v2","v3"]`（base.py:1352/1361）+ `stream_events` typed projection（:1662）；**源码 1549 行标注 "The 'v3' API is in beta"** | ✅ 可用（beta 确认） |
| interpreters | `pip install --dry-run deepagents[quickjs]` → `langchain-quickjs 0.3.5` + `quickjs-rs 0.2.5` + `wasmtime 47.0.1`（Python 3.14 有 wheel） | ✅ 可安装（beta） |
| 与现有能力冲突 | v3 是 langchain 层 API（deepagents 图即 Runnable）；现有 checkpointer/resume 链路不依赖 v2 事件格式 | ✅ 迁移面可控（两个函数） |

### 2.3 学习点定义（本方案的核心诉求）

| P 级 | 新思维方式 | 对应工程实践 |
|------|-----------|-------------|
| P0 | **声明式投影消费**——不再手写 `if evt.get("event") != ...` 分支过滤，按 `stream.messages/tool_calls/subagents` 投影独立消费 | stream_agent_tokens 重写 |
| P1 | **树形可观测**——子代理是"树节点"（嵌套、生命周期 status、独立句柄），前端按树渲染 | SSE subagent 事件 + 前端卡片 |
| P2 | **编排进代码**——循环/分支/并行批次由解释器代码驱动，模型只做"做什么"的决策 | PTC 并行搜索聚合 + task() 批量扇出 |

---

## 3. 分·设计

### 3.1 Event Streaming v3 迁移（P0）

**改造点 1：`main_agent.py` `stream_agent_tokens` → 事件分发器**

```python
async def stream_agent_events(
    agent,
    messages: list[BaseMessage],
    context: ChatContext | None = None,
    checkpoint_id: str | None = None,
) -> AsyncIterator[dict]:
    """v3 事件流（学习点：声明式投影消费——按投影取数，不手写事件过滤）。

    产出三类事件（SSE 协议 v3 对齐）：
      {"type": "token", "text": ...}
      {"type": "tool_call", "tool": ..., "input": ..., "status": "start|end", "output": ...}
      {"type": "subagent", "name": ..., "status": "started|completed|failed"}
    """
    config = ...  # 同现状（thread_id/checkpoint_id 封装不变）
    async with _stream_semaphore:
        stream = await agent.astream_events(
            {"messages": messages}, version="v3", context=context, config=config
        )
        # v3：按投影消费（messages / tool_calls / subagents），并发交错由投影句柄隔离
        async for message in stream.messages:
            yield {"type": "token", "text": message.text}
        async for call in stream.tool_calls:
            yield {"type": "tool_call", "tool": call.tool_name, "input": call.input,
                   "status": "completed" if call.completed else "running",
                   "output": call.output}
        async for subagent in stream.subagents:
            yield {"type": "subagent", "name": subagent.name, "status": subagent.status}
```

> ⚠️ **实施前置**：v3 投影的精确 API（`stream.messages` 是属性还是协程、tool_calls
> 的字段名、异步消费方式）需在实施第一步用最小脚本实测（§6.2 风险项 1）——
> 官方示例同步版用 `agent.stream_events(..., version="v3")`，异步版需对照
> langchain_core 1.3.14 实际签名适配。完整代码见 §7.1。

**兼容策略**：`stream_agent_tokens`（v2，只出 token）**保留**为兼容层
（`EVENT_STREAM_V3=false` 时回退），chat.py 默认切 v3——一键回退，风险可控。

**改造点 2：`chat.py` `_event_stream`**：消费新事件类型 → 对应 SSE 事件分发；
`full_text_parts` 只从 token 事件聚合（落库逻辑不变）。

### 3.2 SSE 契约补齐（P1）：tool_call / subagent 事件

```python
# schemas/events.py 新增（契约 v3 定稿字段）
class ToolCallEvent(SSEEvent):
    type: str = "tool_call"
    tool: str          # 工具名（如 run_code_in_sandbox）
    status: str        # running / completed / error
    input: str         # 入参截断（≤300，密钥纪律，同 ToolAudit 脱敏）
    output: str | None = None

class SubagentEvent(SSEEvent):
    type: str = "subagent"
    name: str          # 子代理名（search_agent）
    status: str        # started / completed / failed
```

- 前端：tool_call 事件驱动"工具调用进度条"；subagent 事件驱动"子代理卡片"
  （开始/完成状态），嵌套子代理用 name 前缀区分（学习点：树形可观测）
- `approve` 事件仍留后续（interrupt 权限激活时随审批链路一起做——沙箱/权限
  方案已预留 `INTERRUPT_PERMISSIONS_ENABLED` 开关）

### 3.3 Interpreters 引入（P2）

**依赖**：`pip install deepagents[quickjs]`（核实可装：langchain-quickjs 0.3.5
+ quickjs-rs 0.2.5 + wasmtime）

**挂载**（`main_agent.py` middleware 栈，开关门控）：

```python
from langchain_quickjs import CodeInterpreterMiddleware

# 中间件栈追加（EVENT_STREAM/INTERPRETER_ENABLED 开关，默认关——学习 demo 按需开）
CodeInterpreterMiddleware(
    memory_limit=64 * 1024 * 1024,   # 官方默认 64MB
    timeout=5.0,                     # 单次 eval 超时 5s
    max_result_chars=4000,
    ptc=["internet_search"],         # 🔴 只读白名单：绝不含文件/沙箱工具（PTC 绕审批）
    mode="turn",                     # 轮内持久（learning：turn/call 对比可玩）
),
```

**能力演示（学习点：编排进代码）**：
- `eval` 工具：图内 JS 计算（排序/分组/聚合，省模型轮次）
- PTC：并行 3 路搜索再聚合——`tools.webSearch` 在 JS 里 `Promise.all`
- `task()` 动态子代理：批量扇出（对 N 个 item 逐个派 reviewer 子代理）

### 3.4 安全边界（硬约束）

| 边界 | 设计 | 依据 |
|------|------|------|
| **PTC 白名单只读** | `ptc=["internet_search"]`——**绝不暴露文件工具/沙箱工具**；官方明示 PTC 调用不走正常工具路径，`interrupt_on` 审批不生效 | 官方 interpreters 安全章节 + 我们权限体系（Permissions/PolicyBackend）不受 PTC 影响的前提 |
| **QuickJS 进程内边界** | 解释器代码默认无文件/网络/shell/时钟访问（官方隔离默认）；`eval` 工具调用本身进 ToolAudit 审计（layer=tool_call） | 官方 "capability-scoped execution layer, not host-memory isolation boundary" |
| **执行分层不变** | 解释器 = 图内计算/编排；**真执行（环境/文件）仍走沙箱**——两套执行不混 | 沙箱能力计划 §3.3 双层模型 |
| **密钥纪律** | eval 代码内容经 ToolAudit 脱敏截断（同 run_code code→code_len）；PTC 只读工具无密钥参数 | 00-security.md |

### 3.5 配置

```python
# config.py 新增（全默认关——学习 demo 显式开启）
event_stream_v3: bool = False          # True = chat 走 v3 事件分发（False 回退 v2 token 流）
interpreter_enabled: bool = False      # True = 挂载 CodeInterpreterMiddleware
interpreter_ptc: str = "internet_search"  # PTC 白名单（逗号分隔，默认只读工具）
```

---

## 4. 分·兼容与回退

| 开关 | 行为 |
|------|------|
| `EVENT_STREAM_V3=false`（默认） | 现状 v2 token 流——零改动回归 |
| `EVENT_STREAM_V3=true` | v3 事件分发（token/tool_call/subagent）——SSE 协议向后兼容（token 事件格式不变，新事件是增量） |
| `INTERPRETER_ENABLED=false`（默认） | 不挂解释器中间件——现状 |
| `INTERPRETER_ENABLED=true` | 挂载（学习 demo 开启） |

- **SSE 兼容性**：前端现有逻辑只认 start/token/done/error——新增 tool_call/subagent
  事件是增量事件（前端不认则忽略），不破坏现有渲染；前端升级是渐进式
- **回退**：任一开关 false 即回到现状；v2 `stream_agent_tokens` 保留不删

---

## 5. 分·测试设计

| 组 | 用例 | 断言 |
|----|------|------|
| **v3 迁移（P0）** | mock LLM（FakeDeepAgentModel）流式 + v3 事件 → token 事件序列与 v2 一致 | token 文本序列等价（回归红线） |
| | 工具调用场景（mock 工具执行）→ tool_call 事件含 tool/status/input | 事件字段 |
| | v3 开关 false → 回退 v2 路径（stream_agent_tokens 原行为） | 回归 |
| **SSE 补齐（P1）** | _event_stream 消费 token/tool_call/subagent → 对应 SSE 事件模型序列化 | 事件类型与契约 v3 字段 |
| | tool_call input 截断 ≤300（脱敏） | 长度断言 |
| **Interpreters（P2）** | CodeInterpreterMiddleware 挂载后 agent 构建成功（mock LLM 兼容 bind_tools） | 构建无异常 |
| | PTC 白名单生效：eval 代码调 tools.webSearch 并行 3 路（mock 工具） | 调用次数=3、结果聚合 |
| | 🔴 PTC 白名单红线：白名单不含文件/沙箱工具（配置校验单测） | 配置断言 |
| | eval 工具调用进 ToolAudit 审计行（layer=tool_call） | audit_records |
| **回退** | 开关矩阵 4 组合全绿 | 回归 |

> 学习 demo 配套：`examples/` 下 3 个最小脚本（v3 投影消费 / PTC 并行聚合 /
> task() 批量扇出），各配 README 说明"新思维方式是什么"——面试可讲可演示。

---

## 6. 总：优先级与风险自检

### 6.1 优先级

| 优先级 | 项 | 内容 | 依赖 |
|--------|----|------|------|
| **P0** | v3 迁移 | stream_agent_tokens → 事件分发器 + 开关 + token 回归 | 无（langchain_core 已支持） |
| **P1** | SSE 补齐 | ToolCallEvent/SubagentEvent + _event_stream 分发 + 前端卡片 | P0 |
| **P2** | Interpreters | 依赖安装 + middleware 挂载 + PTC 只读白名单 + task() demo | P0（子代理流展示顺路） |
| **P2** | 学习配套 | examples/ 3 脚本 + 学习笔记（docs/learnings/） | P0-P2 |

### 6.2 风险自检清单

- [ ] **v3 API 实测前置（最高风险）**：官方示例是同步 `stream_events`，异步版
      投影消费形态需实施第一步最小脚本实测——**先写 10 行冒烟脚本验证 v3 投影
      可用，再动 stream_agent_tokens**（不猜 API）；§7 核心代码为设计形态，
      **以实测校准为准**（投影字段名/协程形态可能调整）
- [ ] **v3 beta**：langchain_core 源码标注 beta（base.py:1549）——开关默认关、
      v2 保留，beta 升级兼容面被开关隔离
- [ ] **PTC 审批绕行（红线）**：PTC 白名单只允许只读工具（internet_search）；
      配置校验单测兜底；文件/沙箱工具绝不入白名单
- [ ] **QuickJS 进程内执行**：解释器不是隔离边界——评估代码不可信时
      memory_limit/timeout 是最后防线；真执行仍走沙箱（分层不变）
- [ ] **mock LLM 兼容**：FakeDeepAgentModel 需支持 v3 流式消费形态（实施时
      验证 _astream 是否满足 v3 content-block 协议；不满足则 v3 测试用
      v2 事件等价断言过渡）
- [ ] **依赖新增**：langchain-quickjs/quickjs-rs/wasmtime 三个新包（beta）——
      开关门控 + 独立 requirements 段（quickjs 可选 extra）
- [ ] **先红后绿**：每 P 级先用例后实现；提交前 pytest 全绿；改代码开分支
      （家规：feature/xxx 从 develop 拉）
- [ ] **文档纪律**：本方案审批后实施；学习笔记落 docs/learnings/

### 6.3 后续

1. approve 事件 + interrupt 权限激活（SSE 契约最后一块空白，依赖前端审批面板）
2. interpreter mode 三态（thread/turn/call）对比实验 → docs/learnings/
3. 动态子代理从 `task()` demo 走向真实批量场景（N 文件审查）——届时评估
   子代理并发上限（同沙箱 pool_max 思路）

---

## 7. 分·完整核心代码（文档规范 v4：设计方案必含核心代码）

> ⚠️ v3 投影 API 为 beta——以下代码为**设计形态**，实施第一步用最小冒烟脚本
> 实测后校准（§6.2 风险项 1），投影字段名以 langchain_core 1.3.14 实际为准。

### 7.1 `main_agent.py`：事件分发器（v2 → v3 迁移，P0 核心）

```python
"""（main_agent.py 增量：替换 stream_agent_tokens 的内部实现，签名兼容扩展）"""

from collections.abc import AsyncIterator


async def stream_agent_events(
    agent,
    messages: list[BaseMessage],
    context: ChatContext | None = None,
    checkpoint_id: str | None = None,
) -> AsyncIterator[dict]:
    """v3 事件流（学习点：声明式投影消费——按投影取数，不手写事件过滤）。

    产出三类事件（SSE 协议 v3 对齐）：
      {"type": "token",     "text": ...}
      {"type": "tool_call", "tool": ..., "input": ..., "status": "running|completed|error",
       "output": ...}
      {"type": "subagent",  "name": ..., "status": "started|completed|failed"}

    Args:
        agent: build_agent 的产物
        messages: 消息列表（resume 模式传空，checkpoint 接管）
        context: 请求级上下文（session_id → thread_id config 封装，同现状）
        checkpoint_id: resume 模式从精确快照继续

    Yields:
        事件 dict（SSE 层据此分发）
    """
    config = None
    if context is not None and context.session_id:
        config = {"configurable": {"thread_id": context.session_id}}
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id

    async with _stream_semaphore:  # 并发限流不变（SQLite 写锁缓解）
        stream = await agent.astream_events(
            {"messages": messages}, version="v3", context=context, config=config
        )
        # 投影消费：消息 / 工具调用 / 子代理（互相独立，交错由投影句柄隔离）
        async for message in stream.messages:
            text = getattr(message, "text", None)
            if text:
                yield {"type": "token", "text": text}
        async for call in stream.tool_calls:
            yield {
                "type": "tool_call",
                "tool": call.tool_name,
                "input": str(call.input)[:300],   # 截断（密钥纪律，同 ToolAudit）
                "status": "completed" if call.completed else "error" if call.error else "running",
                "output": call.output if call.completed else None,
            }
        async for subagent in stream.subagents:
            yield {"type": "subagent", "name": subagent.name, "status": subagent.status}
            # 嵌套子代理：subagent.subagents 递归（学习点：树形可观测）
            async for nested in subagent.subagents:
                yield {"type": "subagent", "name": nested.name, "status": nested.status}


async def stream_agent_tokens(agent, messages, context=None, checkpoint_id=None):
    """v2 兼容层（EVENT_STREAM_V3=false 回退）：只出 token，原实现不变保留。

    实现：astream_events v2 监听 on_chat_model_stream（现状代码，不删）。
    """
    ...  # 原实现原样保留
```

### 7.2 `schemas/events.py`：SSE 事件模型补齐（P1）

```python
"""（schemas/events.py 增量：契约 v3 定稿的 tool_call/subagent 事件落地）"""


class ToolCallEvent(SSEEvent):
    """工具调用事件（契约 v3）：前端驱动"工具调用进度条"。"""

    type: str = "tool_call"
    tool: str          # 工具名（如 run_code_in_sandbox）
    status: str        # running / completed / error
    input: str         # 入参截断 ≤300（密钥纪律，同 ToolAudit 脱敏）
    output: str | None = None


class SubagentEvent(SSEEvent):
    """子代理生命周期事件（契约 v3）：前端驱动"子代理卡片"。"""

    type: str = "subagent"
    name: str          # 子代理名（search_agent）
    status: str        # started / completed / failed
```

### 7.3 `chat.py`：`_event_stream` 增量（P1）

```python
"""（chat.py _event_stream 增量：消费 v3 事件分发）"""

        # start 事件后、done 前——按事件类型分发 SSE（v3 开关开启时）
        if settings.event_stream_v3:
            async for event in stream_agent_events(
                agent, lc_messages, context=chat_context,
                checkpoint_id=req.resume_run_id,
            ):
                if event["type"] == "token":
                    full_text_parts.append(event["text"])
                    yield {"data": TokenEvent(text=event["text"]).model_dump_json()}
                elif event["type"] == "tool_call":
                    yield {"data": ToolCallEvent(**event).model_dump_json()}
                elif event["type"] == "subagent":
                    yield {"data": SubagentEvent(**event).model_dump_json()}
        else:
            # v2 回退：现状 stream_agent_tokens 路径（原样保留）
            async for text in stream_agent_tokens(...):
                ...
```

### 7.4 `main_agent.py`：解释器挂载（P2）

```python
"""（main_agent.py 增量：middleware 栈追加，INTERPRETER_ENABLED 门控）"""

from langchain_quickjs import CodeInterpreterMiddleware

    def _build_agent(thread_id: str):
        middleware = [
            _configurable_model,
            TokenUsageMiddleware(),
            ToolAuditMiddleware(),
        ]
        if settings.interpreter_enabled:   # 学习 demo 显式开启
            middleware.append(
                CodeInterpreterMiddleware(
                    memory_limit=64 * 1024 * 1024,   # 官方默认 64MB
                    timeout=5.0,                     # 单次 eval 5s
                    max_result_chars=4000,
                    # 🔴 PTC 只读白名单：绝不含文件/沙箱工具（PTC 绕 interrupt_on 审批）
                    ptc=[t.strip() for t in settings.interpreter_ptc.split(",") if t.strip()],
                    mode="turn",                     # 轮内持久（学习：turn/call 对比）
                )
            )
        return create_deep_agent(
            ...,
            middleware=middleware,
            ...
        )
```

### 7.5 `core/config.py`：字段（§3.5，全默认关）

```python
    # ── Event Streaming / Interpreter（2026-08-05 引入方案，学习 demo）──
    event_stream_v3: bool = False        # True = chat 走 v3 事件分发（False 回退 v2 token 流）
    interpreter_enabled: bool = False    # True = 挂载 CodeInterpreterMiddleware
    interpreter_ptc: str = "internet_search"  # PTC 白名单（逗号分隔；🔴 只允许只读工具）
```

---

## 附录：版本核实记录（2026-08-05）

| 核实项 | 命令/位置 | 结果 |
|--------|----------|------|
| Python 版本 | `.venv` python --version | 3.14.5 |
| v3 支持 | langchain_core/runnables/base.py:1352,1361（`Literal["v1","v2","v3"]`）、:1662（stream_events）、:1549（"v3 API is in beta"） | ✅ 支持，beta |
| quickjs 可装 | `pip install --dry-run deepagents[quickjs]` | ✅ langchain-quickjs 0.3.5 + quickjs-rs 0.2.5 + wasmtime 47.0.1（Py3.14 wheel 齐全） |
| deepagents 自身 | graph.py 无 stream_events（v3 是 langchain 层 API） | 迁移面=main_agent/chat 两函数 |
