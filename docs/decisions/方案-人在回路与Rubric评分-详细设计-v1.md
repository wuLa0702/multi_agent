# 人在回路（HITL）与 Rubric 评分——详细设计 v1（官方两页 → 项目预研 · 评审稿）

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-06
> 📝 **版本变更记录**（永久保存，只追加不删除）：
> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1 | 2026-08-06 | 初版：基于官方两页文档（human-in-the-loop + rubric，2026-08-04 快照）与 deepagents 0.7.1 源码核对的预研设计——§0 预研结论（HITL 基建就绪可预先开发 / Rubric 有国产模型结构化输出风险需 P0 验证）；§2 官方能力梳理（HITL 决策类型/条件中断/恢复/文件权限 interrupt + Rubric 配置/verdicts/事件）；§3 项目现状对接点（checkpointer/resume_run_id/approve 事件已就绪清单）；§4 预想场景映射（代码评审/报告生成/来源真实性 × HITL/Rubric 分工）；§5 设计决策（D1-D8：审批分级配置/审批 API/事件协议/Rubric 模板库）；§6 权衡与 P0 验证计划（Rubric grader response_format 死穴 + astream_events interrupt 恢复形态）；§7 完整核心代码（HITL 接线 + Rubric 挂载 + 模板库）；§8 测试设计；§9 验收与风险 |

> **目录**：
> - §0 结论：预研结论（先读这里）
> - §1 总·背景、目标与范围
> - §2 分·官方能力梳理
> - §3 分·项目现状对接点
> - §4 分·预想场景 → 能力映射
> - §5 分·设计决策
> - §6 分·权衡与 P0 验证计划
> - §7 分·完整核心代码
> - §8 分·测试设计
> - §9 总·验收清单与风险自检

> **关联文档**：
> - 官方文档：`https://docs.langchain.com/oss/python/deepagents/human-in-the-loop`、`https://docs.langchain.com/oss/python/deepagents/rubric`
> - 既有基建：`backend/src/agent/main_agent.py`（checkpointer / resume / 演进预留注释）、`backend/src/api/chat.py`（resume_run_id）、`backend/src/schemas/events.py`（approve 事件契约）、`backend/src/core/permissions.py`（权限模板）
> - 模型栈验证：`docs/学习/子代理-官方能力对比与差距分析-v1.md` §7.4（response_format 国产模型三态全挂——本文档 §6.1 风险同源）
> - 文档规范：`docs/文档规范.md`（v4：设计方案必含核心代码）

---

## 0. 结论：预研结论 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

> **核心理解（co-creator 定调）**：**人类决定"能不能做"，AI 打分决定"做得好不好"**——
> HITL 是执行权闸门（工具副作用前人类审批），Rubric 是质量闸门（交付前 LLM-as-judge 自评迭代）。

| 能力 | 预研结论 | 理由 |
|------|----------|------|
| **HITL 审批** | ✅ **基建已就绪，推荐预先开发**（P1） | checkpointer / resume_run_id / approve 事件类型全部已落地（§3），只差 interrupt_on 配置 + 审批决策 API |
| **Rubric 评分** | ⚠️ **P0 验证先行，验证通过再开发**（P1） | grader 内部用 response_format 结构化输出——国产模型三态全挂（上轮 §7.4 实证），RubricMiddleware 大概率直接 grader_error，必须先 10 分钟验证（§6.1） |

**预想场景（无业务先预研，业务后接入）**：代码评审、报告生成、数据来源真实性判断（防 AI 乱说话）——三场景的 HITL/Rubric 分工见 §4。

---

## 1. 总：背景、目标与范围

### 1.1 背景

官方新增两页能力：**HITL（human-in-the-loop）**——敏感工具执行前人类审批（approve/edit/reject/respond 四种决策）；**Rubric（grading rubrics）**——声明"什么是完成"，LLM-as-a-judge 评分子代理驱动 agent 自评迭代直到达标或迭代上限。

本项目目前没有业务场景，但可以预想重要场景（代码评审、生成报告、数据来源真实性判断），**先预先开发通用能力，后续接入具体业务**。

### 1.2 目标

1. 官方两页能力完整梳理（§2），不翻原文
2. 项目现状盘点：哪些基建已就绪、差什么（§3）
3. 预想场景 → HITL/Rubric 分工映射（§4）
4. 预先开发设计（§5/§7）：HITL 通用审批 + Rubric 模板库，业务无关
5. 明确 P0 验证项（§6）：Rubric 在国产模型栈的可行性（吸取 response_format 教训）

### 1.3 范围

| 在本设计内 | 不在本设计内 |
|-----------|-------------|
| HITL 后端全链路（interrupt_on 配置 / 审批 API / approve 事件） | 前端审批卡片 UI（P2，事件契约先定） |
| Rubric 挂载设计 + 预置模板库（3 场景） | Rubric SSE 流式事件（P2，P1 用日志 + 摘要） |
| 预想场景的通用能力（业务无关） | 具体业务接入（后续逐个接入） |
| P0 验证计划与验证脚本 | LangSmith eval 批量评估集成 |

---

## 2. 分：官方能力梳理

### 2.1 HITL：interrupt_on 配置 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- `interrupt_on` 参数：工具名 → 配置（`True` 默认四决策 / `False` 不审批 / `InterruptOnConfig` 自定义）
- 设置后自动挂载 `HumanInTheLoopMiddleware`；中断未返回结果时 `PatchToolCallsMiddleware` 自动修复消息历史
- **Checkpointer 是硬前置**（中断 → 恢复需持久化状态）；恢复必须用**同一 thread_id**
- 条件中断：`InterruptOnConfig(when=predicate)`——按 ToolCallRequest 参数决定是否中断（如只审工作区外路径写操作）；需 langchain>=1.3.3

### 2.2 HITL：四种决策类型 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

| 决策 | 语义 | 用途 |
|------|------|------|
| ✅ `approve` | 原参数执行 | 批准动作 |
| ✏️ `edit` | 改参数后执行（edited_action 含 name+args） | 修改收件人/路径等 |
| ❌ `reject` | 跳过执行 + 反馈给 agent（message 决定 agent 下一步） | 拒绝 + 指示（"不要重试，改为归档"） |
| 💬 `respond` | 人类消息直接作为工具结果（跳过执行） | 只用于 ask_user 类工具，**不可用于副作用工具**（会被模型当成功结果） |

- **多工具批量中断**：同轮多个待审工具合并为一次 interrupt（action_requests 数组），决策**按顺序一一对应**
- reject 的 message 是质量关键：明确"放弃 / 追问 / 换更安全方案"

### 2.3 HITL：中断处理与恢复 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

```
result = agent.invoke(..., config=config, version="v2")
if result.interrupts:
    interrupt_value = result.interrupts[0].value
    action_requests = interrupt_value["action_requests"]      # 待审动作
    review_configs = interrupt_value["review_configs"]        # 各工具允许决策
    decisions = [{"type": "reject", "message": "..."}]        # 按序一一对应
    result = agent.invoke(Command(resume={"decisions": decisions}), config=config)
```

### 2.4 HITL：子代理与文件权限 interrupt <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- 子代理可有**独立 interrupt_on**（覆盖主 agent 配置）；子代理触发中断处理方式相同
- 工具内可 `interrupt()` 直接暂停（如 request_approval 工具）
- **文件权限 interrupt（deepagents>=0.6.8，本机 0.7.1 ✓）**：permissions 规则 `mode="interrupt"`——写/编辑命中规则路径即触发同一套中断（如 `/secrets/**`），与 interrupt_on 合并为一次审批。**比 interrupt_on 更声明式，项目权限模板可直接扩展**

### 2.5 HITL：最佳实践 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- 按风险分级配置（高危全决策 / 中危 approve+reject / 低危不审批）
- 恢复必须同一 thread_id；决策顺序与 action_requests 一一对应
- edit 要保守（大改可能让模型重评估反复执行）

### 2.6 Rubric：RubricMiddleware 配置 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- **beta 功能（deepagents>=0.6.5，本机 0.7.1 ✓）**，API 可能变
- 配置参数：`model`（必填，grader 用模型——通常比工作模型便宜）/ `system_prompt`（自定义评分指令）/ `tools`（grader 证据收集工具：跑测试、读文件）/ `max_iterations`（默认 3）/ `on_evaluation`（每次评分回调，含 RubricEvaluation dict）
- 调用时传 `rubric` 字符串（换行 checklist）启动自评循环；**不传 rubric 中间件不运行**

### 2.7 Rubric：verdicts 与事件 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

| Verdict | 含义 | 回环？ |
|---------|------|--------|
| `satisfied` | 全部标准通过 | 否（终止） |
| `needs_revision` | 至少一条不通过，反馈注入 agent 重跑 | 是 |
| `max_iterations_reached` | 达迭代上限仍不达标 | 否 |
| `failed` | rubric 格式非法/无法评估 | 否 |
| `grader_error` | grader 自身异常（超时/凭据/结构化响应损坏） | 否 |

- `RubricEvaluation`：grading_run_id / iteration / result / explanation / criteria（逐条 {name, passed, gap}）
- 事件：v3 `stream.custom` 的 `rubric_evaluation_start/end`（需 CustomTransformer）；**`on_evaluation` 回调是 invoke/stream 通用的观测途径**（本项目 P1 选它，规避 v3 迁移）
- 跨调用持久化：同一 thread_id + checkpointer → rubric 跨 invoke 保持（中断后恢复同 loop）

### 2.8 Rubric：0.7.1 源码核对（关键风险） <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- `RubricMiddleware` 已导出 ✓；grader 经 `create_agent(..., response_format=GraderResponse)` 构建——**走结构化输出**，且有 `_StructuredOutputStrategy` 自动探测（ToolStrategy vs ProviderStrategy）
- ⚠️ **这正是国产模型死穴**（差距分析 §7.4 实证：response_format 三态全挂）→ grader 在 deepseek/豆包/智谱上极可能 `grader_error`。**必须 P0 验证（§6.1）**

---

## 3. 分：项目现状对接点

| 基建 | 现状 | 与本文档关系 |
|------|------|-------------|
| Checkpointer（AsyncSqliteSaver） | ✅ 已接（lifespan 管理，main_agent.init_checkpointer） | HITL 硬前置 ✓ |
| resume 恢复（resume_run_id + checkpoint_id） | ✅ 已接（chat.py：resume 必须带 session_id；RESUME_NOT_FOUND 兜底；message 与 resume_run_id 互斥） | 审批恢复的通道 ✓（缺 decisions 参数） |
| approve 事件类型 | ⚠️ 协议已定义（10-api.md：token/tool_call/approve/...），events.py 注释"后续阶段按契约补齐" | **本次实现** |
| 权限模板（build_main_permissions / build_subagent_permissions） | ✅ 已接（主 agent + 子代理，P0 声明式规则） | 扩展 `mode="interrupt"` 规则（§5.1） |
| 沙箱工具集（run_code_in_sandbox 等） | ✅ 已挂载 | 高危工具审批对象（§5.1） |
| ChatContext / ChatRequest 模型 | ✅ 已接 | 扩展 rubric 透传（§5.4） |
| SSE 事件流（astream_events v2） | ✅ 主链路 | HITL interrupt 检测点（§5.3，⚠️ V2 验证） |
| 结构化输出在国产模型 | ❌ 实证不可用（§7.4 上轮） | Rubric 可行性风险（§6.1） |

**差距清单**：① interrupt_on 配置 ② 审批决策 API（decisions 参数）③ approve 事件实现 ④ RubricMiddleware 挂载 + rubric 透传 + 模板库 ⑤ 两个 P0 验证。

---

## 4. 分：预想场景 → 能力映射

> 无业务场景，预想三个重要场景做**通用能力预研**；以下映射即后续业务接入的模板。

| 预想场景 | HITL（人类决定能不能做） | Rubric（AI 打分做得好不好） |
|----------|--------------------------|------------------------------|
| **代码评审** | 沙箱执行/文件写入前审批（高危动作闸门） | 评审报告按检查清单打分（完整性/证据引用/严重度分级），不达标迭代 |
| **生成报告** | 对外发送/发布前审批（approve/reject + edit 修改） | 报告必须覆盖全部章节 + 引用来源，grader 逐节打分迭代 |
| **数据来源真实性判断（防 AI 乱说话）** | 关键断言写盘/对外输出前审批 | 输出必须带可核验来源、无未验证断言——grader 带证据工具（internet_search）核验后打分 |

**通用化抽象**：HITL 一律挂在"**有副作用的工具动作**"上（沙箱执行/写文件/对外发送），与业务无关；Rubric 一律挂在"**交付物质量**"上（评审/报告/断言），以模板库形式预置（§5.5），业务接入 = 选模板 + 挂工具。

---

## 5. 分：设计决策

### 5.1 D1：HITL 审批分级配置（interrupt_on + 权限 interrupt 双轨） <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- **interrupt_on 按工具风险分级**（代码常量，`src/agent/hitl.py`）：

| 工具 | 配置 | 理由 |
|------|------|------|
| `run_code_in_sandbox` | approve + edit + reject | 任意代码执行，高危 |
| `run_command_in_sandbox` | approve + reject（不许 edit） | 命令执行，中高危 |
| `upload_workspace_file` / `download_sandbox_file` | approve + reject | 文件进出，中危 |
| `run_skill_script` | approve + reject | 技能脚本执行，中危 |
| `internet_search` 及全部只读工具 | False（不审批） | 无副作用 |

- **权限 interrupt 双轨**：`build_main_permissions` 模板加 `mode="interrupt"` 规则（如 `/secrets/**` 写）——命中即与 interrupt_on 合并审批（声明式，覆盖配置文件路径）
- 配置开关：`settings.hitl_enabled`（默认 False，预先开发完默认关，业务接入时开）

### 5.2 D2：审批决策 API（复用 /v1/chat/stream） <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- `ChatRequest` 扩展 `decisions: list[Decision] | None`（Pydantic 模型：type: approve/edit/reject/respond + message + edited_action）
- 语义：`resume_run_id` 模式 + `decisions` → **审批恢复**（中断点继续）；`resume_run_id` 无 decisions → 既有断点续聊
- 校验：decisions 非空时必须有 resume_run_id；decision type 非法 → 400
- 映射：`Command(resume={"decisions": [...]})` 作为输入传给 astream_events（⚠️ V2 验证：astream_events 接受 Command input 的形态）

### 5.3 D3：approve 事件实现 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- 事件类型沿用协议（`approve`），payload 补齐：`action_requests`（name/args）+ `review_configs`（allowed_decisions）+ `interrupt_id`（前端恢复时回传）
- 检测点：astream_events 的 interrupt 事件（langgraph 提供 on_interrupt 类事件；⚠️ V2 验证具体形态）→ 转换 approve SSE 事件并**终止本次流**（等人类决策）
- 前端（P2）据 approve 事件渲染审批卡片 → 用户决策 → 带 decisions 重新 POST

### 5.4 D4/D5：Rubric 挂载与透传 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- `settings.rubric_enabled` 门控（默认 False）+ `RubricMiddleware(model=get_chat_model(), max_iterations=3)` 构建期挂载（会话缓存 agent 单例，与其它中间件同栈）
- grader model **必须传实例**（国产模型 base_url，同 P1-1 教训）；grader 证据工具 P1 不挂（无安全白名单），P2 评估
- `ChatRequest.rubric: str | None` → 透传 input state `{"messages": ..., "rubric": ...}`；不传不触发

### 5.5 D6/D7：Rubric 事件与模板库 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- P1 观测：`on_evaluation` 回调 → 日志 + 响应 done 事件携带 rubric 摘要（verdict/iteration/criteria）；P2 再上完整 SSE（规避 v3 stream.custom 迁移）
- **预置模板库** `src/agent/rubrics.py`（纯文本 checklist，可组合）：
  - `code_review`：覆盖功能正确性/边界/安全/风格/证据行号
  - `report_completeness`：覆盖全部要求章节/数据引用/结论可追溯
  - `source_veracity`：**防 AI 乱说话**——每条断言必须有可核验来源、禁止未验证推断、区分事实与推测
- 业务接入 = 选模板（可覆盖/扩展）+ 挂证据工具

### 5.6 D8：不做清单 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- ❌ 前端审批卡片 UI（P2，事件契约先定）
- ❌ Rubric SSE 流式事件（P2）
- ❌ grader 证据工具（P2，需安全白名单设计）
- ❌ LangSmith eval 集成（独立课题）
- ❌ 具体业务接入（后续逐个）

---

## 6. 分：权衡与 P0 验证计划

### 6.1 V1（必做）：RubricMiddleware 在国产模型的可行性 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

**风险同源**（差距分析 §7.4 实证）：RubricMiddleware 的 grader 用 `response_format=GraderResponse` 结构化输出 + 策略自动探测——国产模型（deepseek/豆包/智谱）response_format 三态全挂。**若不验证直接开发，rubric 大概率全部 `grader_error`**（官方 verdict 表里专门列了这个失败态）。

**验证方案**（复用 `verify_subagent_structured_output.py` 模式，10 分钟）：
1. `RubricMiddleware(model=get_chat_model(...))` 挂到最小 agent（checkpointer 用 MemorySaver）
2. 传一个简单 rubric（"回答是一句话；回答提到光合作用"）
3. 观察：`grader_error`（预计）还是 `satisfied`/`needs_revision`
4. 若失败，看 rubric.py 的 `_StructuredOutputStrategy` 探测是否留了降级口（源码 302-435 行逻辑）
5. 结论决定：Rubric P1 开发 or 降级为 P2（等 OpenAI 系模型 or 官方修复）or 自研评分（并列执行体 LLM-as-judge，绕过 response_format——用 prompt 约束 + 解析，同降级方案 A 模式）

### 6.2 V2（必做）：astream_events 下 interrupt 检测与 Command(resume) 恢复形态 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- 官方示例全用 `agent.invoke` + `result.interrupts`；本项目主链路是 `astream_events`——中断在流中如何暴露（on_interrupt 事件？）、`Command(resume=...)` 能否作为 astream_events 输入，需最小 demo 实测（Fake 模型不出工具调用 → 需真实模型或构造中断路径）
- 失败预案：审批恢复改用 `agent.astream(Command(resume=...), config, stream_mode="messages")` 或 invoke 分支（流式降级为一次性返回）

### 6.3 权衡总结 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

| 能力 | 价值 | 成本/风险 | 结论 |
|------|------|-----------|------|
| HITL | 高（执行权闸门，防乱执行；基建已就绪） | 低（interrupt_on 配置 + 审批 API + 事件） | ✅ P1 开发（V2 验证先行） |
| Rubric | 高（质量闸门，防乱说话；与 HITL 互补） | 中（beta API + 国产模型结构化输出风险） | ⚠️ V1 验证通过才 P1 开发，否则 P2/自研降级 |
| 前端审批 UI | 中 | 中 | P2（事件契约先定） |

---

## 7. 分：完整核心代码

> ⚠️ 参考形态（评审通过后落地）；按 01-coding-style：函数 ≤80 行、类型注解、docstring。

### 7.1 `backend/src/agent/hitl.py`（HITL 配置，全量） <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

```python
"""HITL 审批配置（人在回路设计 §5.1）：按工具风险分级的 interrupt_on。

- 高危（任意代码执行）→ approve+edit+reject；中危 → approve+reject；
  只读/无副作用工具 → False 不审批
- settings.hitl_enabled 门控：默认关，业务接入时开
- 文件权限 interrupt（mode="interrupt"）由 core/permissions.py 模板扩展（§5.1）
"""

from __future__ import annotations

from langchain.agents.middleware import InterruptOnConfig

# 工具名 → interrupt_on 配置（True=默认四决策 / False=不审批 / 配置=自定义）
HITL_INTERRUPT_ON: dict[str, bool | InterruptOnConfig] = {
    # 沙箱执行域：可执行任意代码/命令，高危
    "run_code_in_sandbox": InterruptOnConfig(
        allowed_decisions=["approve", "edit", "reject"]
    ),
    "run_command_in_sandbox": InterruptOnConfig(
        allowed_decisions=["approve", "reject"]
    ),
    # 文件同步域：工作区进出，中危
    "upload_workspace_file": InterruptOnConfig(allowed_decisions=["approve", "reject"]),
    "download_sandbox_file": InterruptOnConfig(allowed_decisions=["approve", "reject"]),
    # 技能执行域：脚本执行，中危
    "run_skill_script": InterruptOnConfig(allowed_decisions=["approve", "reject"]),
    # 只读/搜索：无副作用，不审批
    "internet_search": False,
}


def build_hitl_interrupt_on(enabled: bool) -> dict[str, bool | InterruptOnConfig] | None:
    """构建 interrupt_on（hitl_enabled 门控；禁用 → None 不挂载审批）。

    Args:
        enabled: settings.hitl_enabled

    Returns:
        启用 → HITL_INTERRUPT_ON；禁用 → None（create_deep_agent 不配 interrupt_on）
    """
    return HITL_INTERRUPT_ON if enabled else None
```

### 7.2 main_agent 接线（HITL + Rubric 增量） <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

```python
# main_agent.py _build_agent 内增量（设计 §5.1/§5.4）：

from src.agent.hitl import build_hitl_interrupt_on
from src.agent.rubrics import RUBRIC_TEMPLATES, build_rubric_middleware

    return create_deep_agent(
        model=model,
        ...
        # HITL（P1，人在回路设计 §5.1）：hitl_enabled 门控；checkpointer 已接（硬前置）
        interrupt_on=build_hitl_interrupt_on(settings.hitl_enabled),
        # Rubric（P1，设计 §5.4）：rubric_enabled 门控；grader 传实例（国产 base_url）
        middleware=middleware + build_rubric_middleware(),
        ...
    )
```

```python
# src/agent/rubrics.py（模板库 + 中间件构建，设计 §5.4/§5.5）

"""Rubric 评分模板库与中间件构建（Rubric 设计 §5.4/§5.5）。

- 模板 = 换行 checklist（官方 rubric 字符串形态），业务接入时选模板/覆盖/扩展
- grader model 必须传实例（国产模型自定义 base_url——同 P1-1 教训）
- ⚠️ P0 验证（设计 §6.1）：RubricMiddleware grader 走 response_format 结构化输出，
  国产模型三态全挂风险——验证通过前 build_rubric_middleware 返回 []（不挂载）
"""

from __future__ import annotations

from src.core.config import settings

RUBRIC_TEMPLATES: dict[str, str] = {
    "code_review": (
        "- 覆盖功能正确性与边界条件\n"
        "- 指出安全问题（注入/越权/密钥泄露）与证据行号\n"
        "- 风格与可维护性建议（有具体依据）\n"
        "- 结论给出严重度分级（P0/P1/P2）"
    ),
    "report_completeness": (
        "- 覆盖用户要求的全部章节\n"
        "- 关键数据有来源引用\n"
        "- 结论可追溯（从数据到结论路径清晰）\n"
        "- 无未经验证的主张"
    ),
    "source_veracity": (
        "- 每条断言都有可核验的来源（URL/文档/代码位置）\n"
        "- 区分事实与推测（推测必须明确标注）\n"
        "- 无编造的数据、引用或统计数字\n"
        "- 无「可能/大概」式的无依据断言"
    ),
}


def build_rubric_middleware() -> list:
    """构建 RubricMiddleware（rubric_enabled 门控；P0 验证通过前返回空列表）。

    Returns:
        启用且验证通过 → [RubricMiddleware]；否则 []（不挂载）
    """
    if not settings.rubric_enabled:
        return []
    if not settings.rubric_verified:  # P0 验证开关（V1 通过后置 True）
        return []
    from deepagents import RubricMiddleware
    from src.llm.adapter import get_chat_model

    return [
        RubricMiddleware(
            model=get_chat_model(),  # grader 传实例（国产 base_url）
            max_iterations=3,
            on_evaluation=_log_evaluation,
        )
    ]


def _log_evaluation(ev: dict) -> None:
    """on_evaluation 回调：日志记录（P1 观测；P2 升级为 SSE 事件）。"""
    import logging

    logging.getLogger(__name__).info(
        "rubric iteration=%s result=%s explanation=%s",
        ev.get("iteration"), ev.get("result"), ev.get("explanation"),
    )
```

### 7.3 chat.py 审批 API 增量（设计 §5.2/§5.3） <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

```python
# schemas/message.py（或 chat 请求模型）增量：

class ReviewDecision(BaseModel):
    """单条审批决策（与 action_requests 顺序一一对应，设计 §5.2）。"""

    type: Literal["approve", "edit", "reject", "respond"]
    message: str | None = Field(default=None, description="reject/respond 反馈给 agent")
    edited_action: dict[str, Any] | None = Field(
        default=None, description="edit 时的新参数（含 name+args）"
    )

# ChatRequest 增量：decisions: list[ReviewDecision] | None
```

```python
# chat.py 校验 + 恢复（增量示意）：

    if req.decisions and not req.resume_run_id:
        raise HTTPException(400, "decisions（审批决策）必须搭配 resume_run_id 使用")
    # 恢复输入：审批恢复 → Command(resume={"decisions": [...]})（⚠️ V2 验证形态）
    # 流内 interrupt 检测（⚠️ V2 验证）：检测到中断 → 发 approve 事件 → 结束本次流
```

### 7.4 调用链说明 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

```
【HITL 审批流】
用户请求 → astream_events（工具命中 interrupt_on）→ 中断
  → approve SSE 事件（action_requests + review_configs）→ 本次流结束
  → 前端渲染审批卡片（P2）→ 用户决策
  → POST /v1/chat/stream {resume_run_id, decisions}
  → Command(resume={"decisions": [...]}) 恢复 → 继续流

【Rubric 自评流】
用户请求（rubric 字段）→ agent 输出 → grader 按 rubric 打分
  → needs_revision → 反馈注入重跑（≤ max_iterations）
  → satisfied / max_iterations_reached / failed / grader_error
  → on_evaluation 日志（P1）→ done 事件带 rubric 摘要
```

---

## 8. 分：测试设计

| # | 用例 | 类别 | 断言 |
|---|------|------|------|
| 1 | hitl_enabled=False → interrupt_on=None | 边界 | create_deep_agent 未收 interrupt_on（回归） |
| 2 | hitl_enabled=True → interrupt_on 含 run_code_in_sandbox 且 allowed_decisions 正确 | 正常 | 配置透传 |
| 3 | 审批决策校验：decisions 无 resume_run_id | 错误 | 400 |
| 4 | decisions type 非法 | 错误 | 400（Pydantic Literal 校验） |
| 5 | resume 恢复：mock 中断 → decisions=[approve] → Command(resume) 参数正确（⚠️ V2 后落地） | 正常 | 恢复调用形态 |
| 6 | 中断 → approve 事件 payload 完整（action_requests/review_configs） | 正常 | SSE 事件契约 |
| 7 | rubric_enabled=False / rubric_verified=False → 不挂 RubricMiddleware | 边界 | middleware 栈无 Rubric |
| 8 | rubric 模板库存在且为换行 checklist | 正常 | 三模板内容断言 |
| 9 | （V1 通过后）RubricMiddleware 挂载 + rubric 透传 input state | 正常 | input 含 rubric 键 |

> 说明：HITL/Rubric 全 mock（create_deep_agent / astream_events）；审批恢复的流式形态依赖 V2 验证结果。

---

## 9. 总：验收清单与风险自检

### 9.1 验收清单 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

- [ ] **P0-V1**：Rubric 国产模型验证脚本出结论（通过 → rubric_verified=True / 不通过 → Rubric 降级 P2 或自研）
- [ ] **P0-V2**：astream_events 中断检测 + Command(resume) 恢复形态实测出结论
- [ ] HITL：hitl.py 配置 + main_agent 接线 + chat.py decisions 校验 + approve 事件（V2 通过后）
- [ ] `pytest backend/tests` 全绿（新增 §8 用例 1-9）
- [ ] 浏览器实测（业务接入时）：沙箱工具触发审批卡片 → 决策 → 恢复

### 9.2 风险自检 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v1</span>

| 风险 | 等级 | 缓解 |
|------|------|------|
| Rubric grader 国产模型 response_format 全挂（源码已确认走结构化输出） | **高** | P0-V1 验证先行；降级路径：自研 LLM-as-judge（prompt 约束 + 解析，同降级方案 A）或 P2 等模型/官方 |
| astream_events 中断/恢复形态与官方 invoke 示例不同 | 中 | P0-V2 实测；预案：审批恢复走 astream(stream_mode="messages") 或 invoke 分支 |
| Rubric beta API 变动 | 中 | 0.7.1 实测标注；升级后回归 §8 用例 7-9 |
| HITL 开启后对话体验变化（频繁审批打断） | 低 | 按风险分级配置（只读不审）；hitl_enabled 默认关，业务接入时按场景调 |
| 审批编辑（edit）导致模型反复执行 | 低 | 官方建议保守编辑；编辑路径 P2 默认不开（先 approve/reject） |
