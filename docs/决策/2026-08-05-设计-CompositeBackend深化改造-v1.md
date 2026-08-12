# CompositeBackend 深化改造方案 v1（存储 · 安全 · 多会话 · 子代理全维度）

> 📋 **规范**：遵循 `docs/规则/文档规范.md`
> 📌 **更新时间**：2026-08-04
> 📝 **版本变更记录**（永久保存，只追加不删除）：
> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1 | 2026-08-04 | 初版：基于 CompositeBackend 设计 v2.0（已实施）+ deepagents 官方 Permissions 体系的深化改造评审稿——§2 架构调整、§3 权限分层（上层 Permissions / 下层 PolicyBackend / 逃逸面边界）、§4 会话隔离、§5 兼容方案、§6 完整代码、§7 验收测试、§8 优先级与风险自检 |

> **目录**：
> - §1 总：背景、现状盘点与深化目标
> - §2 分·模块一：架构调整（会话级 Backend 深化 + 缓存治理）
> - §3 分·模块二：权限分层（上层 Permissions + 下层 PolicyBackend + 逃逸面边界 + 审计）
> - §4 分·模块三：会话隔离（隔离矩阵 + 子代理隔离）
> - §5 分·模块四：兼容方案（环境开关矩阵 + demo 兼容）
> - §6 分·完整可运行代码（backend.py 全量 / main_agent.py 挂载 / 权限模板 / loader 透传 / config 增量）
> - §7 分·验收测试用例集合（6 组 + 关键用例代码）
> - §8 总：改造优先级（P0/P1/P2）+ 风险自检清单 + 后续
> - 附录：v2.0 设计文档同步修订清单（v2 → v3）

> **关联文档**：
> - 设计 v2.0（本方案的基础）：`docs/决策/CompositeBackend文件存储-设计-v2.md`
> - 持久化计划：`docs/决策/2026-08-04-持久化能力开发计划-Checkpointer与Store-v1.md`
> - 架构：`docs/架构/多agent项目-架构目录.md`（§2 目录树 / §2.1 能力落地位置对照）
> - 路径：`docs/归档/2026-08-02-方案-后端基础架构-v1.md`（路径自适应）

---

## 1. 总：背景、现状盘点与深化目标

### 1.1 背景

第三版《CompositeBackend 文件存储设计文档》（v2.0，已实施落地：`core/backend.py` 会话级工厂 +
`main_agent.py` 会话缓存 + 只读强制）已修复两大架构硬缺陷，但仍有三层未闭合：

1. **上层安全未挂载**：deepagents 官方 `Permissions` 声明式规则体系**完全没有配置**——
   技能只读仅靠 backend 层 `ReadOnlyBackend` 代码拦截，缺 agent 工具层的声明式 deny、
   缺高危文件写入的人工中断审批（interrupt）、缺子代理独立权限覆盖；
2. **下层兜底缺失**：无 Backend Policy Hooks——MCP 自定义工具、OpenSandbox 沙箱 shell
   存在逃逸面（不经 backend 的文件 IO 无拦截无审计），全链路文件操作无统一审计日志；
3. **隔离未闭环**：子 Agent 与主会话共用 backend（deepagents `SubAgentMiddleware` 继承），
   无子代理专属临时内存 Backend；会话级 Agent 缓存无容量治理（无上限增长）、
   会话删除未联动文件清理与缓存失效。

### 1.2 现状盘点（代码级核实，2026-08-04）

| 项 | 现状代码 | 深化落点 |
|----|---------|---------|
| 会话级 Backend | ✅ `create_backend(thread_id)` 工厂（backend.py:72） | 补底层策略包装 + 开关 |
| 技能只读（backend 层） | ✅ `ReadOnlyBackend` 拦截写（backend.py:34） | 统一进 `PolicyBackend` 策略化 |
| 会话缓存 | ✅ `_agents` dict + 双重检查锁（main_agent.py:121） | **补 LRU 容量上限**（P0） |
| 内存模式开关 | ✅ `settings.memory_workspace`（config.py:120） | 补策略层/子代理隔离开关 |
| Checkpointer / Store | ✅ AsyncSqliteSaver / AsyncSqliteStore（lifespan 管理） | 不变（interrupt 审批依赖 checkpointer） |
| 审批断点恢复 | ✅ `resume_run_id` + checkpoint 恢复（chat.py:107） | 与 interrupt 权限自动衔接 |
| **上层 Permissions** | ❌ `create_deep_agent(permissions=...)` 未传 | **P0 挂载** |
| **底层 Policy Hooks** | ❌ 不存在 | **P1 开发** |
| **子代理独立 backend** | ❌ 继承主 backend（graph.py:663-672 核实） | P1 权限覆盖 → P2 内存 backend |
| 会话删除联动 | ❌ DELETE /v1/sessions 未清理缓存与文件 | **P0 联动** |

### 1.3 深化目标

1. **修复架构硬缺陷**（P0）：会话级 Backend 全链路闭环——上层 Permissions 挂载 + 缓存容量治理
   + 会话销毁联动清理（文件隔离已在 v2.0 落地，本方案补治理与安全闭环）
2. **补齐安全闭环**（P0/P1）：双层防护——
   - 上层：官方 `FilesystemPermission` 声明式规则（技能目录写 deny、高危路径 interrupt 审批、子代理独立覆盖）
   - 下层：`PolicyBackend` 拦截钩子（兜底经 backend 协议的所有路径访问 + 统一审计日志）
3. **完善隔离机制**（P1/P2）：子代理专属临时内存 Backend——P1 子代理权限覆盖（原生支持），
   P2 `CompiledSubAgent` 预编译绑独立 `StateBackend`（原生支持，无需 fork deepagents）
4. **兼容兜底方案**（P0）：环境开关矩阵——`MEMORY_WORKSPACE` 一键切内存 StateBackend、
   `BACKEND_POLICY_ENABLED` 策略层总开关、`SUBAGENT_ISOLATION` 子代理隔离开关
5. **配套工程落地**：完整可运行代码（§6）+ 验收测试（§7）+ 优先级与风险自检（§8）
   + v2.0 设计文档同步修订（附录，v2 → v3）

### 1.4 范围

| 在本方案内 | 不在本方案内 |
|-----------|-------------|
| 上层 Permissions 挂载（主 agent + 子代理） | 云上多机部署 / 多租户 |
| PolicyBackend 底层拦截 + 审计（JSONL） | Store 语义记忆检索深化（B.2） |
| 会话缓存 LRU + 会话删除联动 | MemoryMiddleware 启用（B.1，后续） |
| 子代理权限覆盖（P1）/ 编译子代理内存 backend（P2） | LangGraph 手写主图整体演进（路线预留） |
| 环境开关矩阵 + demo 兼容 | 沙箱后端（OpenSandbox 独立执行层，边界见 §3.3） |

---

## 2. 分·模块一：架构调整（会话级 Backend 深化）

### 2.1 架构总览（深化后分层）

```
请求流 → main_agent.get_agent(thread_id) → 会话级 Agent 缓存（LRU，P0）
                │
                └─ create_deep_agent(
                     backend=create_backend(thread_id),        ← 会话级组合存储（v2.0 已落）
                     permissions=build_permissions(...),       ← 上层：声明式规则（P0 新增）
                     subagents=...                             ← P1 权限覆盖 / P2 独立 backend
                   )
                         │
        CompositeBackend（5 虚拟路由，外层类型不变）
          default     → PolicyBackend(FilesystemBackend(workspace/{thread_id}))
          /memories/  → PolicyBackend(FilesystemBackend(memory/))          ← 下层：拦截钩子 + 审计（P1）
          /skills/static/ → PolicyBackend(FilesystemBackend(skill-resources/), 只读策略)
          /skills/market/ → PolicyBackend(FilesystemBackend(skill_md/),        只读策略)
          /exports/   → PolicyBackend(FilesystemBackend(exports/))
                         │
                  两层拦截顺序（写操作）：
                  FilesystemMiddleware 工具层 → Permissions deny/interrupt（上层，先）
                  PolicyBackend 钩子层 → 策略 deny + 审计日志（下层，兜底）
```

**分层职责**（谁拦什么）：

| 层 | 机制 | 拦截对象 | 失败表现 |
|----|------|---------|---------|
| 上层 | FilesystemPermission 声明式 | agent 的文件工具调用（write/edit/delete） | 工具返回权限错误（agent 可感知，不中断 run）；interrupt → 挂起等人工审批 |
| 下层 | PolicyBackend 钩子 | 所有经 backend 协议的路径访问（含未来新增文件类工具、MCP 桥接 backend 的场景） | 抛 PermissionError + 审计日志（兜底，不依赖 agent 配合） |
| 边界 | 工具调用审计中间件（P1） | MCP 自定义工具 / 沙箱 run_code 调用 | 只审计不拦截（真实边界，见 §3.3） |

### 2.2 会话级 Backend（v2.0 已落，本方案增量）

`create_backend(thread_id)` 保留，增量为 **PolicyBackend 策略包装**（§3.2）与开关透传（§5）。

### 2.3 会话级 Agent 缓存治理（P0 新增）

现状：`_agents: dict[str, object]` 无上限——长时间运行后会话越多内存越涨，且无逐出策略。

**方案：有界 LRU 缓存**（`OrderedDict` + 现有双重检查锁扩展）：

```python
_AGENT_CACHE_MAX = 32          # 会话缓存上限：单机单用户场景 32 个并发会话足够
_agents: "OrderedDict[str, object]" = OrderedDict()

def get_agent(thread_id: str = "default"):
    with _agents_lock:
        agent = _agents.pop(thread_id, None)     # LRU 刷新（先移除）
        if agent is not None:
            _agents[thread_id] = agent
            return agent
        agent = _build_agent(thread_id)          # 原构建逻辑抽离（锁外构建，锁内放回）
        _agents[thread_id] = agent
        while len(_agents) > _AGENT_CACHE_MAX:   # 超限逐出最久未用
            evicted, _ = _agents.popitem(last=False)
            logger.info("Agent 缓存逐出（LRU）：thread=%s", evicted)
        return agent
```

- 锁外构建、锁内放回：构建 compile 是纯内存操作，短暂重复构建可接受（双检锁退化保护）
- 逐出仅清内存图（编译图无状态）；**文件与磁盘不逐出**——工作区文件由会话删除
  `cleanup_workspace` 联动清理（§4.3），防止 LRU 误删活跃会话文件
- `rebuild_agent(thread_id)` 语义不变（Skill 变更热刷新）

### 2.4 会话删除联动（P0 新增）

`DELETE /v1/sessions/{id}`（api/sessions.py）新增两动作：

```
rebuild_agent(thread_id)       # 1. 失效缓存图（下次请求重建）
cleanup_workspace(thread_id)   # 2. 清理会话工作区临时文件（已实现，backend.py:100）
```

- 两动作均幂等；会话不存在时静默通过
- `cleanup_workspace` 保留 mtime 30 天策略（v2.0 设计），会话删除时全量清理不按天数

### 2.5 依赖与约束（架构调整不改动项）

- `CompositeBackend` 外层类型**保持不变**（策略包装在 routes 内部）——`FilesystemMiddleware`
  的 `isinstance(CompositeBackend)` 判断（artifacts_root / 路由作用域校验）不受影响
- `artifacts_root="/"` 大文件 offload 落 default backend → 天然会话隔离（workspace/{thread_id}）
- `_configurable_model` middleware / checkpointer / store 生命周期全部不动

---

## 3. 分·模块二：权限分层（双层防护）

### 3.1 上层：原生 Permissions 声明式规则（P0）

**官方机制核实**（deepagents 0.7.1 源码）：

| 事实 | 出处 |
|------|------|
| `FilesystemPermission(operations, paths, mode)`，`operations` 仅 `read`/`write` 两粒度（write 覆盖 write_file/edit_file/delete/upload） | middleware/filesystem.py:95,246 |
| 工具→操作映射：ls/read_file/glob/grep=read；write_file/edit_file/delete=write | middleware/_fs_interrupt.py:38 |
| `create_deep_agent(permissions=...)` → FilesystemMiddleware（REQUIRED 中间件，不可剥离） | graph.py:277,808 |
| `interrupt` 模式自动合成 `interrupt_on`（when 谓词精确触发；决策 approve/edit/reject/respond 四种） | middleware/_fs_interrupt.py:156 |
| 子代理 `spec["permissions"]` **整体替换**父级规则（不是叠加） | graph.py:663-664 |
| 权限路径必须 `/` 开头、禁 `..`、禁 `~`；建议限定在 CompositeBackend 路由前缀内 | middleware/filesystem.py:258,409 |
| 执行型 backend（SandboxBackendProtocol）+ 权限未限定路由 → NotImplementedError；本项目 default=FilesystemBackend **无执行能力** → 不触发 | middleware/filesystem.py:1436 |

**权限标准模板**（新建 `core/permissions.py`，代码见 §6.3）：

| 规则 | operations | paths | mode | 说明 |
|------|-----------|-------|------|------|
| 技能目录只读 | `["write"]` | `["/skills/**"]` | `deny` | 声明式强制，agent 工具层直接拒绝（替代纯文档约定） |
| 高危文件写审批 | `["write"]` | `["/memories/private/**", "/memories/secrets/**"]` | `interrupt` | 人工审批：SSE approve 事件 → 前端审批 → resume_run_id 恢复（checkpointer 已就绪） |
| 子代理覆盖 | 见 §3.4 | | | 整体替换父级 |

**审批闭环**（interrupt 模式与现有能力衔接，全部已具备）：

```
Agent 调用 write_file("/memories/private/x.md")
  → FilesystemMiddleware 匹配 interrupt 规则 → 图挂起（interrupt_on 自动生成）
  → SSE approve 事件（schemas/events.py）→ 前端审批面板
  → 审批后 resume_run_id 重连（chat.py:107 已实现）→ checkpoint 恢复继续
```

### 3.2 下层：Backend Policy Hooks（P1，兜底 + 审计）

**为什么需要**：上层 Permissions 只拦截 FilesystemMiddleware 的 7 个工具。任何「不经
FilesystemMiddleware 的 backend 访问」都会绕过上层——本方案在 backend 协议层加第二道闸。

**`PolicyBackend`**（核心手写逻辑，`core/backend.py`，代码见 §6.2）：

- 包装任意 `BackendProtocol`，暴露**完整协议方法**（写 4 个 + 读 4 个 + 其余 `__getattr__` 委托）
- 写操作（write/edit/delete/upload_files）先过策略决策，再执行；拒绝 → `PermissionError` + 审计
- 读操作（read/ls/glob/grep）可选审计（默认关闭防刷屏）
- 策略 = 路径前缀 × 操作 × allow/deny 的有序规则集（手写决策循环，先匹配先生效）
- **统一审计**：所有写 + 拒绝操作记 `logging.getLogger("audit")`（JSONL 文件，见 §3.4）

**策略模板**（backend 层兜底，与上层互补）：

| 路由 | 兜底策略 | 语义 |
|------|---------|------|
| `/skills/static/`、`/skills/market/` | `deny` 全部写 | 技能目录只读（上层规则漏配时仍拦截） |
| default（workspace） | `allow` 全部 + 审计 | 工作区是 agent 主活动区，只审计不拦截 |
| `/memories/`、`/exports/` | `allow` + 审计 | 记忆/导出是设计允许的写入目标 |

**与 ReadOnlyBackend 的关系**：`ReadOnlyBackend` 被 `PolicyBackend(skills 只读策略)` 统一替代
（同一拦截语义 + 审计能力）；`ReadOnlyBackend` 类保留（旧引用兼容，测试可继续用）。

### 3.3 逃逸面边界（如实标注）

| 逃逸面 | 机制 | 是否能被 backend 层拦截 | 缓解（本方案） |
|--------|------|----------------------|---------------|
| 自定义 MCP 工具（_SafeTool 包装，client.py:27） | 工具直接调外部 server，文件 IO 发生在工具内部 | ❌ 不经 backend，backend 层物理不可达 | ① 工具注入白名单（mcp_servers 表 active 开关已存在）② 工具调用审计中间件（P1，§3.4）记录 name/args |
| OpenSandbox 沙箱 shell（run_code_in_sandbox） | 代码在**容器内**执行，文件系统与宿主机隔离 | ❌ 容器内 IO 不经 backend（这是隔离的设计意图） | ① 沙箱本身即隔离边界（dev 连本地 docker / prod 连云端）② 工具调用审计记录每次执行 |
| 未来新增文件类工具（若直接持有 backend） | 经 backend 协议 | ✅ **PolicyBackend 兜底拦截**（本方案核心价值） | 新工具接入时天然受策略约束 |

> **结论**：`PolicyBackend` 兜底的真实覆盖 = 「所有经 backend 协议的路径访问」；MCP/沙箱
> 逃逸用「工具审计 + 注入白名单」缓解，不承诺物理拦截（诚实标注，防评审误判为万能闸）。

### 3.4 审计日志（P1，统一全链路）

**通道**：`logging.getLogger("audit")`——日志 handler 唯一配置点仍在 `core/logging.py`
（04-logging.md 铁律），业务侧不建 handler：

```
core/logging.py 新增：audit logger → logs/file_access_audit.jsonl（UTF-8，每日滚动，50MB 上限）
```

**审计记录字段**（JSON 行）：

```json
{"ts": "2026-08-04T10:00:00+08:00", "thread_id": "abc", "layer": "policy_backend",
 "op": "write", "path": "/skills/market/x.md", "decision": "deny", "detail": "技能目录只读"}
{"ts": "...", "thread_id": "abc", "layer": "tool_call", "tool": "run_code_in_sandbox",
 "args": {"filename": "script.py", "code_len": 1234}, "decision": "audit"}
```

- `layer=policy_backend`：PolicyBackend 钩子层（写全量 + 拒绝）
- `layer=permissions`：上层 deny/interrupt 触发（FilesystemMiddleware 无原生审计钩子，
  P1 在中间件外层包装或由工具审计中间件捕获返回的权限错误——标注为实施细节）
- `layer=tool_call`：工具调用审计中间件（P1 新增，见 §6.4）——覆盖 MCP 工具与沙箱工具

### 3.5 子代理权限覆盖（P1，原生支持）

- `search_agent.yaml` 增 `permissions:` 字段（YAML 声明，loader 透传，代码见 §6.5）
- 模板：搜索子代理无文件需求 → 写全拒绝：`[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")]`
- 语义：整体替换父级规则（graph.py:663 核实）——子代理权限**独立配置**，父级规则对子代理不生效
- 声明优先级：主 agent 规则管主 agent；子代理规则管子代理；互不泄漏

---

## 4. 分·模块三：会话隔离

### 4.1 隔离矩阵（thread_id 维度）

| 数据 | 存储 | 隔离粒度 | 说明 |
|------|------|---------|------|
| 工作区文件（default） | `data/workspace/{thread_id}/` | **会话级** ✅ | v2.0 已落；大文件 offload（large_tool_results）也落此处 |
| 技能（/skills/static + market） | 全局共享 + **全局只读** | 全局（所有会话共享读） | 只读强制：上层 deny + 下层策略双保险 |
| 记忆（/memories/） | `data/memory/` 全局共享 | 全局（所有会话共享读写） | v2.0 拍板：记忆是全局资产（跨会话长期记忆）；高危子目录 interrupt 审批 |
| 导出（/exports/） | `data/exports/` 全局 | 全局共享写 | 导出文件带 thread 前缀命名（v2.0 约定） |
| checkpoint | `data/checkpoints.db`（thread_id 执行线） | **会话级** ✅ | langgraph 按 thread_id 隔离执行线 |
| Store 记忆 | `data/store.db`（namespace 维度） | 全局 | 语义记忆全局共享 |

> **深化说明**：本方案不改变 `/memories/` 全局共享语义（v2.0 拍板），只补「高危子目录
> interrupt 审批」防敏感记忆被静默改写。若未来需要会话级记忆子目录，在
> `get_memory_dir() / thread_id` 上加路由即可，本方案预留此演进点（§8 后续）。

### 4.2 子代理隔离（P1 → P2 两阶段）

**现状**：`SubAgentMiddleware(backend=backend)` 子代理继承主 backend（graph.py:663-672 核实），
子代理文件与主会话同目录——单机场景可接受（v2.0 已标注），但违背「子 Agent 不污染主会话」目标。

**P1（本方案落地，原生、零风险）**：子代理权限覆盖（§3.5）——搜索子代理无文件操作能力，
从工具层就断掉污染路径。

**P2（演进，原生支持无需 fork）**：`CompiledSubAgent` 预编译绑独立 `StateBackend`：

```python
# deepagents graph.py 核实：subagents 声明含 "runnable" → CompiledSubAgent 按原样使用
# （自带 FilesystemMiddleware 与 backend，不继承父级）→ 子代理文件落自己的内存状态
subagent_isolated = create_deep_agent(
    model=get_chat_model(),
    system_prompt="…子代理提示词…",
    tools=[internet_search],
    backend=StateBackend(),   # 子代理专属临时内存 backend：文件存 graph state，随 run 生命周期
    permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
)
# 主 agent 挂载：
subagents=[CompiledSubAgent(runnable=subagent_isolated, description="…", system_prompt="…"), ...]
```

- **隔离效果**：子代理写文件 → 落子代理图状态（内存临时），主会话工作区零污染；
  断点 resume 时子代理状态随主 state 一并 checkpoint 恢复（StateBackend 存 state，天然兼容）
- **权衡**（如实标注）：编译子代理模型在编译时绑定（不随 `_configurable_model` 运行时切换）；
  多 provider 场景需按 provider 重建缓存。单 provider 场景无感
- **开关**：`settings.subagent_isolation`（默认 False → P1 权限覆盖；True → P2 编译子代理）
- **学习点**：CompiledSubAgent 独立 backend 是 deepagents 原生机制——LangGraph 手写主图
  演进路线（02-hands-on-training）可在此基础上做「每子代理独立 StateBackend + 显式数据流」，
  与官方机制互为印证

### 4.3 会话销毁联动（P0，§2.4）

```
DELETE /v1/sessions/{id}
  → rebuild_agent(thread_id)       # 缓存失效（LRU 空间释放）
  → cleanup_workspace(thread_id)   # 工作区文件清理（防堆积）
```

---

## 5. 分·模块四：兼容方案（环境开关矩阵）

### 5.1 开关矩阵

| 环境变量（Settings 字段） | 默认 | 语义 | 用途 |
|--------------------------|------|------|------|
| `MEMORY_WORKSPACE`（memory_workspace） | `False` | True → default 切 StateBackend（内存临时，重启清空） | **dev 测试一键内存模式**（v2.0 已实现，本方案确认保留） |
| `BACKEND_POLICY_ENABLED`（backend_policy_enabled） | `True` | False → PolicyBackend 透明直通（不包装不审计） | 测试隔离/性能对比/策略层问题排查 |
| `SUBAGENT_ISOLATION`（subagent_isolation） | `False` | True → P2 编译子代理独立内存 backend | 子代理隔离开关（默认 P1 权限覆盖） |
| `SKILL_RESOURCES_DIR` | 缺省项目根 skill-resources/ | 静态技能目录路径覆盖 | v2.0 已有，保留 |

### 5.2 组合模式（demo/测试/生产三场景）

| 场景 | MEMORY_WORKSPACE | BACKEND_POLICY_ENABLED | SUBAGENT_ISOLATION | 行为 |
|------|-----------------|----------------------|-------------------|------|
| demo 脚本/单测（重启清空语义） | `True` | `False` | `False` | default=StateBackend，策略直通——与旧 demo 行为完全一致 |
| 本地真实开发 | `False` | `True` | `False` | 磁盘持久 + 双层防护（P1 子代理权限覆盖） |
| 生产 | `False` | `True` | `True` | 磁盘持久 + 双层防护 + 子代理真隔离（P2 落地后） |

### 5.3 兼容性保证

- `create_backend(thread_id)` / `get_agent(thread_id)` / `rebuild_agent` 签名不变——调用方零改动
- `ReadOnlyBackend` 类保留——旧测试/引用不破坏
- 策略层总开关 `False` 时 `PolicyBackend` 返回内层实例本身（透明直通，零开销）
- demo 脚本（agent_demo 类）不感知任何新参数

---

## 6. 分·完整可运行代码

### 6.1 `core/paths.py`（现状已齐备，无需改动）

已核实：`get_workspace_dir / get_memory_dir / get_static_skills_dir / get_skill_md_dir /
get_exports_dir` 全部存在且自动初始化（paths.py:68-123）。**本方案无新路径函数**。

### 6.2 `core/backend.py`（深化版全量）

```python
"""Agent Backend 工厂：会话级组合存储 + 双层权限（2026-08-04 深化 v3）。

分层（写操作拦截顺序）：
  上层——FilesystemPermission 声明式规则（main_agent.py 配置，§3.1）：
        /skills/** 写 deny；高危路径 interrupt 人工审批；子代理独立覆盖
  下层——PolicyBackend 拦截钩子（本文件，§3.2）：
        兜底拦截所有经 backend 协议的路径访问（防上层漏配/未来新工具直写），
        统一审计日志（写全量 + 拒绝，audit logger → JSONL）
  ReadOnlyBackend 由 PolicyBackend(skills 只读策略) 统一替代（类保留兼容）

开关（config.py）：
  MEMORY_WORKSPACE         True → default 切 StateBackend（dev 测试兼容）
  BACKEND_POLICY_ENABLED   False → PolicyBackend 透明直通（测试/排查）
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

from src.core.config import settings
from src.core.paths import (
    get_exports_dir,
    get_memory_dir,
    get_skill_md_dir,
    get_static_skills_dir,
    get_workspace_dir,
)

audit_logger = logging.getLogger("audit")

WORKSPACE_CLEANUP_DAYS = 30


# ── 下层：Policy Hooks（核心手写逻辑：策略决策 + 审计，不依赖上层工具层）──

@dataclass(frozen=True)
class BackendPolicyRule:
    """backend 层拦截规则：路径前缀 × 操作 × 决策。

    Attributes:
        path_prefix: 虚拟路径前缀（如 "/skills/"）；path.startswith 匹配
        operations: 适用操作集合（"write" 覆盖 write/edit/delete/upload_files）
        mode: "deny" 拒绝 + 审计；"allow" 放行（审计仍可记）
    """

    path_prefix: str
    operations: frozenset[str] = frozenset({"write"})
    mode: Literal["allow", "deny"] = "deny"


@dataclass(frozen=True)
class BackendPolicy:
    """有序规则集：先匹配先生效（第一条命中即返回）。

    Attributes:
        name: 策略名（审计日志用）
        rules: 规则元组（有序）
        audit_reads: 读操作是否审计（默认 False 防刷屏）
    """

    name: str
    rules: tuple[BackendPolicyRule, ...] = ()
    audit_reads: bool = False

    def decide(self, op: str, path: str) -> Literal["allow", "deny"]:
        """策略决策：返回 allow/deny。

        Args:
            op: 操作（write/read）
            path: 虚拟路径（如 "/skills/market/x.md"）

        Returns:
            "deny" 或 "allow"
        """
        for rule in self.rules:
            if op in rule.operations and path.startswith(rule.path_prefix):
                return rule.mode
        return "allow"


# ── 策略模板（backend 层兜底）──

SKILL_READONLY_POLICY = BackendPolicy(
    name="skills-readonly",
    rules=(BackendPolicyRule("/skills/", frozenset({"write"}), "deny"),),
)
WORKSPACE_POLICY = BackendPolicy(name="workspace")          # 允许 + 写审计
MEMORY_POLICY = BackendPolicy(name="memories")              # 允许 + 写审计
EXPORT_POLICY = BackendPolicy(name="exports")               # 允许 + 写审计


class PolicyBackend:
    """策略拦截后端：包装内层 backend，读写先过策略再执行（兜底防线）。

    与上层 Permissions 的区别：上层拦截 agent 的 7 个文件工具调用（工具层），
    本类拦截所有经 backend 协议的路径访问（协议层）——上层规则漏配、
    未来新增文件类工具直写 backend 时，仍在此被策略兜底并审计。

    Attributes:
        _inner: 被包装的 backend（FilesystemBackend 等）
        _policy: 策略规则集
        _thread_id: 审计字段（会话定位）
    """

    _WRITE_METHODS = ("write", "edit", "delete", "upload_files")
    _READ_METHODS = ("read", "ls", "glob", "grep")

    def __init__(self, inner, policy: BackendPolicy, *, thread_id: str = "") -> None:
        self._inner = inner
        self._policy = policy
        self._thread_id = thread_id

    def __getattr__(self, name: str):
        """非读写协议方法（als 等）委托内层；写读方法已在方法级拦截（防 __getattr__ 绕过）。"""
        return getattr(self._inner, name)

    # ── 写操作：先决策再执行 ──

    def write(self, *args, **kwargs):
        self._guard("write", args[0] if args else "")
        return self._inner.write(*args, **kwargs)

    def edit(self, *args, **kwargs):
        self._guard("write", args[0] if args else "")
        return self._inner.edit(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard("write", args[0] if args else "")
        return self._inner.delete(*args, **kwargs)

    def upload_files(self, *args, **kwargs):
        self._guard("write", args[0] if args else "")
        return self._inner.upload_files(*args, **kwargs)

    # ── 读操作：默认仅审计（audit_reads 开启时）──

    def read(self, *args, **kwargs):
        if self._policy.audit_reads:
            self._audit("read", args[0] if args else "", "allow")
        return self._inner.read(*args, **kwargs)

    def ls(self, *args, **kwargs):
        return self._inner.ls(*args, **kwargs)

    def glob(self, *args, **kwargs):
        return self._inner.glob(*args, **kwargs)

    def grep(self, *args, **kwargs):
        return self._inner.grep(*args, **kwargs)

    # ── 内部：决策 + 审计 ──

    def _guard(self, op: str, path: str) -> None:
        decision = self._policy.decide(op, path)
        self._audit(op, path, decision)
        if decision == "deny":
            logger = audit_logger if audit_logger.handlers else logging.getLogger(__name__)
            logger.warning(
                "backend 策略拦截：%s %s（thread=%s，policy=%s）——拒绝",
                op, path, self._thread_id, self._policy.name,
            )
            raise PermissionError(f"策略拒绝：{self._policy.name} 禁止 {op} {path}")

    def _audit(self, op: str, path: str, decision: str) -> None:
        audit_logger.info(
            "backend_access thread=%s layer=policy_backend op=%s path=%s decision=%s policy=%s",
            self._thread_id, op, path, decision, self._policy.name,
        )


def _wrap(inner, policy: BackendPolicy, thread_id: str):
    """策略层包装：BACKEND_POLICY_ENABLED=False 时透明直通（零开销，测试/排查用）。"""
    if not settings.backend_policy_enabled:
        return inner
    return PolicyBackend(inner, policy, thread_id=thread_id)


def create_backend(thread_id: str, *, memory_workspace: bool | None = None) -> CompositeBackend:
    """按会话构建组合 backend（default 路由绑 thread_id 目录，会话文件隔离）。

    Args:
        thread_id: 会话 ID（== session_id，backend 文件根绑定它）
        memory_workspace: 覆盖内存模式（缺省读 settings.memory_workspace）

    Returns:
        CompositeBackend——default=workspace/{thread_id}（或 StateBackend），
        路由：/memories/、/skills/static/（只读策略）、/skills/market/（只读策略）、/exports/，
        全部经 PolicyBackend 策略包装（兜底 + 审计）
    """
    use_memory = settings.memory_workspace if memory_workspace is None else memory_workspace
    default = (
        StateBackend()
        if use_memory
        else _wrap(
            FilesystemBackend(root_dir=get_workspace_dir() / thread_id, virtual_mode=True),
            WORKSPACE_POLICY, thread_id,
        )
    )
    return CompositeBackend(
        default=default,
        routes={
            "/memories/": _wrap(
                FilesystemBackend(root_dir=get_memory_dir(), virtual_mode=True),
                MEMORY_POLICY, thread_id,
            ),
            "/skills/static/": _wrap(
                FilesystemBackend(root_dir=get_static_skills_dir(), virtual_mode=True),
                SKILL_READONLY_POLICY, thread_id,
            ),
            "/skills/market/": _wrap(
                FilesystemBackend(root_dir=get_skill_md_dir(), virtual_mode=True),
                SKILL_READONLY_POLICY, thread_id,
            ),
            "/exports/": _wrap(
                FilesystemBackend(root_dir=get_exports_dir(), virtual_mode=True),
                EXPORT_POLICY, thread_id,
            ),
        },
    )


def cleanup_workspace(thread_id: str, older_than_days: int = WORKSPACE_CLEANUP_DAYS) -> int:
    """清理会话工作区过期临时文件（mtime 超期删除，返回删除数）。见 v2.0 设计 §2.4。

    Args:
        thread_id: 会话 ID
        older_than_days: 超过该天数的文件删除

    Returns:
        删除的文件数
    """
    workspace = get_workspace_dir() / thread_id
    if not workspace.exists():
        return 0
    cutoff = time.time() - older_than_days * 86400
    removed = 0
    for f in workspace.rglob("*"):
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                removed += 1
            except OSError:
                logging.getLogger(__name__).warning("清理失败：%s", f)
    logging.getLogger(__name__).info("workspace 清理：thread=%s 删除 %d 个过期文件", thread_id, removed)
    return removed
```

### 6.3 `core/permissions.py`（上层权限模板，新建）

```python
"""Permissions 权限标准模板：技能只读 + 高危写入审批 + 子代理覆盖。

基于 deepagents 官方 FilesystemPermission（deepagents 0.7.1 核实）：
- operations 仅 read/write 两粒度（write 覆盖 write_file/edit_file/delete/upload_files）
- 路径必须 "/" 开头、禁 ".."；建议限定在 CompositeBackend 路由前缀内
- 规则有序：先匹配先生效（deny /skills/** 必须放最前）
- interrupt → 自动合成 interrupt_on（approve/edit/reject/respond），
  审批后经 resume_run_id 恢复（checkpointer 已就绪，chat.py:107）
"""

from __future__ import annotations

from deepagents import FilesystemPermission

# ── 主 Agent 权限模板 ──

def build_main_permissions() -> list[FilesystemPermission]:
    """主 Agent 声明式权限：

    - /skills/** 写 deny：技能目录只读（agent 工具层直接拒绝）
    - /memories/private/**、/memories/secrets/** 写 interrupt：高危记忆
      文件写入挂起，人工审批后恢复

    Returns:
        FilesystemPermission 列表（传给 create_deep_agent(permissions=...)）
    """
    return [
        FilesystemPermission(
            operations=["write"],
            paths=["/skills/**"],
            mode="deny",
        ),
        FilesystemPermission(
            operations=["write"],
            paths=["/memories/private/**", "/memories/secrets/**"],
            mode="interrupt",
        ),
    ]


# ── 子代理权限模板（整体替换父级规则，graph.py:663 核实）──

def build_subagent_permissions(subagent_name: str) -> list[FilesystemPermission]:
    """子代理独立权限（默认空 = 继承父级；返回列表 = 整体替换）。

    Args:
        subagent_name: 子代理名（subagents/*.yaml 的 name）

    Returns:
        FilesystemPermission 列表；未知子代理返回 []（继承父级）
    """
    if subagent_name == "search_agent":
        # 搜索子代理无文件需求：写全拒绝（读保留——SkillsMiddleware 读技能不受影响）
        return [FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")]
    return []
```

### 6.4 `agent/middlewares/tool_audit.py`（工具调用审计中间件，P1 新建）

```python
"""工具调用审计中间件：记录每次工具调用的 name + 关键参数（P1）。

覆盖边界（§3.3）：MCP 自定义工具、沙箱 run_code_in_sandbox 等不经 backend
的文件 IO——backend 层物理不可达，统一在此记审计（只审计不拦截）。
写操作关键字段：file_path / path / code 长度等（args 全量记录防泄漏：截断 300 字符）。
"""

from __future__ import annotations

import logging

from langchain.agents.middleware import AgentMiddleware

audit_logger = logging.getLogger("audit")

# 需要完整记录 args 的工具（写操作/执行类）；其余只记工具名
_SENSITIVE_TOOLS = {"run_code_in_sandbox", "write_file", "edit_file", "delete", "upload_files"}


class ToolAuditMiddleware(AgentMiddleware):
    """工具调用审计：工具执行前记录 name/args（截断），经 audit logger 落 JSONL。"""

    async def before_model(self, state, context, *args, **kwargs):
        return state

    # 注：AgentMiddleware 的工具调用前钩子随版本差异；实施时按
    # deepagents 0.7.1 AgentMiddleware 钩子签名适配（before_tool 或事件流
    # 监听二选一），本文件为设计占位——§8 风险项 5 已标注
    ...
```

> 实施注记：AgentMiddleware 钩子签名以 0.7.1 安装版本为准，实施第一步写适配单测
> （§7 用例 T6），防钩子签名漂移。

### 6.5 `agent/subagents/loader.py` 增量（permissions 透传）

```python
# _parse_subagent_yaml 的 spec 构造增加 permissions 透传：
from src.core.permissions import build_subagent_permissions

    spec: SubAgent = {
        "name": data["name"],
        "description": data["description"],
        "system_prompt": data["system_prompt"],
        "tools": [get_tool(name) for name in data.get("tools", [])],
    }
    # 子代理权限（P1）：YAML 显式声明优先，缺省走模板（无模板 = 继承父级）
    if "permissions" in data:
        spec["permissions"] = data["permissions"]
    else:
        perms = build_subagent_permissions(data["name"])
        if perms:
            spec["permissions"] = perms
    return spec
```

`search_agent.yaml` 可显式声明（模板缺省已覆盖，显式声明用于可读性）：

```yaml
permissions:
  - operations: [write]
    paths: ["/**"]
    mode: deny
```

### 6.6 `agent/main_agent.py` 增量

```python
# 1) 导入权限模板
from src.core.permissions import build_main_permissions

# 2) 会话缓存 LRU 化（替换现有 _agents dict + get_agent，§2.3）：
#    _agents: "OrderedDict[str, object]" = OrderedDict()
#    _AGENT_CACHE_MAX = 32
#    get_agent 内部：pop 刷新 / 超限 popitem(last=False) 逐出（锁内）

# 3) _build_agent 抽离（原 get_agent 构建体），create_deep_agent 增加：
_agents[thread_id] = create_deep_agent(
    ...
    backend=create_backend(thread_id),          # 不变（内部已含 PolicyBackend）
    permissions=build_main_permissions(),       # ← P0 新增：上层声明式规则
    ...
)

# 4) P2 子代理隔离（settings.subagent_isolation=True 时，loader 返回
#    CompiledSubAgent 列表而非 SubAgent 列表——loader 内做分支，main_agent 零改动）
```

### 6.7 `core/config.py` 增量

```python
    # ── 安全分层（2026-08-04 深化 v3）──
    # 策略层总开关：False = PolicyBackend 透明直通（测试隔离/性能对比/排查）
    backend_policy_enabled: bool = True
    # 子代理隔离：False(默认) = P1 权限覆盖（原生）；True = P2 编译子代理独立内存 backend
    subagent_isolation: bool = False
```

### 6.8 `core/logging.py` 增量（audit logger 注册）

```python
# setup_logging() 内新增（04-logging.md：handler 唯一配置点）：
_audit = logging.getLogger("audit")
if not _audit.handlers:
    _audit_file = log_dir / "file_access_audit.jsonl"
    _audit_handler = logging.FileHandler(_audit_file, encoding="utf-8")
    _audit_handler.setFormatter(logging.Formatter(
        '{"ts": "%(asctime)s", "level": "%(levelname)s", "msg": "%(message)s"}',
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    ))
    _audit.setLevel(logging.INFO)
    _audit.addHandler(_audit_handler)
    _audit.propagate = False
```

---

## 7. 分·验收测试用例集合

### 7.1 用例矩阵（6 组全覆盖）

| 组 | 用例 | 断言 | 层 |
|----|------|------|-----|
| **T1 路由隔离** | write("/note.txt") → workspace/{thread_id}/note.txt | 落盘路径正确 | backend |
| | write("/memories/m.md") → data/memory/m.md | 路由分发正确 | backend |
| | write("/exports/r.md") → data/exports/r.md | 路由分发正确 | backend |
| **T2 权限拦截·上层** | agent 工具层写 /skills/market/x.md | 工具返回权限错误（deny，不抛异常不中断） | agent |
| | permissions interrupt 规则命中 | 图挂起：astream 产出 approve 事件；resume_run_id 恢复后继续 | agent+api |
| | 子代理（search_agent）写文件 | 子代理工具层拒绝（独立权限整体替换父级） | agent |
| **T3 权限拦截·下层** | PolicyBackend.write("/skills/static/x.md") | PermissionError + audit 日志含 decision=deny | backend |
| | PolicyBackend.write("/skills/market/x.md") | PermissionError（上层漏配时兜底） | backend |
| | PolicyBackend.write(workspace 内路径) | 放行 + audit 记录 decision=allow | backend |
| **T4 会话隔离** | thread A/B 各写 default → 各落 workspace/A/、workspace/B/ | 互不污染 | backend |
| | 多协程并发写不同 thread_id（asyncio.gather） | 各落各自目录，无交叉 | backend |
| | 大文件 offload（large_tool_results） | 落 workspace/{thread_id}（会话隔离 ✅） | agent |
| **T5 子代理隔离** | P2 开关开：编译子代理写文件 | 主会话工作区无文件；子代理 state 内可读回 | agent |
| | P2 开关关（默认）：子代理权限覆盖生效 | 子代理写被工具层拒绝（T2 子代理用例） | agent |
| **T6 越权防护** | backend write("../escape.txt") | virtual_mode 规范化/拒绝（v2.0 已有） | backend |
| | PolicyBackend 对非路由前缀路径写 | 策略允许（default 语义）或按策略 deny——断言决策与审计一致 | backend |
| | ToolAuditMiddleware 记录 run_code_in_sandbox 调用 | audit 日志含 tool=run_code_in_sandbox | agent |
| **T7 dev 内存切换** | MEMORY_WORKSPACE=true → default 为 StateBackend | 写后读回，无磁盘文件（重启清空语义） | backend |
| | BACKEND_POLICY_ENABLED=false → 无 PolicyBackend | 类型直通（type(inner) 检查）+ 无审计输出 | backend |
| | demo 脚本全链路（内存模式 + 策略直通） | 与 v2.0 之前行为一致 | 集成 |

### 7.2 关键用例代码

```python
# tests/test_core/test_backend.py（新增：T3/T7 下层拦截 + 开关）

def test_policy_backend_denies_skills_write(tmp_path):
    """T3：下层策略兜底——技能目录写 → PermissionError + 审计。"""
    inner = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    wrapped = PolicyBackend(inner, SKILL_READONLY_POLICY, thread_id="t1")
    with pytest.raises(PermissionError, match="技能目录只读|skills-readonly"):
        wrapped.write("/skills/market/x.md", "content")
    # 审计已记（caplog 捕获 audit logger）
    assert "decision=deny" in caplog.text


def test_policy_backend_allows_workspace_write(tmp_path):
    """T3：工作区写放行 + 审计。"""
    inner = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    wrapped = PolicyBackend(inner, WORKSPACE_POLICY, thread_id="t1")
    assert wrapped.write("/note.txt", "hello") is not None   # 放行
    assert "decision=allow" in caplog.text


def test_policy_backend_disabled_transparent(monkeypatch, tmp_path):
    """T7：BACKEND_POLICY_ENABLED=false → 直通无包装。"""
    monkeypatch.setattr(settings, "backend_policy_enabled", False)
    inner = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    assert _wrap(inner, SKILL_READONLY_POLICY, "t1") is inner


def test_create_backend_memory_mode(monkeypatch):
    """T7：MEMORY_WORKSPACE=true → default 为 StateBackend（写后读回，无磁盘）。"""
    monkeypatch.setattr(settings, "memory_workspace", True)
    backend = create_backend("demo")
    backend.write("/note.txt", "hello")
    assert backend.read("/note.txt")["content"] == "hello"   # 内存语义
```

```python
# tests/test_agent/test_permissions.py（新增：T2 上层规则）

def test_main_permissions_deny_skills_write():
    """T2：权限模板——/skills/** 写 deny（规则序：deny 在最前）。"""
    perms = build_main_permissions()
    assert perms[0].mode == "deny"
    assert perms[0].paths == ["/skills/**"]


def test_subagent_permissions_replace_parent():
    """T2：子代理权限整体替换父级（graph.py:663 语义）。"""
    assert build_subagent_permissions("search_agent")[0].mode == "deny"
    assert build_subagent_permissions("unknown_agent") == []   # 继承父级


async def test_interrupt_permission_fires_approve_event(...):
    """T2：interrupt 规则 → 图挂起产出 approve 事件（mock LLM，见 conftest）。"""
    ...
```

```python
# tests/test_agent/test_main_agent.py（增量：T4/T5）

def test_agent_cache_lru_eviction():
    """T4：缓存超限逐出最久未用（LRU）。"""
    for i in range(_AGENT_CACHE_MAX + 5):
        get_agent(f"t{i}")
    assert len(_agents) == _AGENT_CACHE_MAX
    assert "t0" not in _agents and f"t{_AGENT_CACHE_MAX + 4}" in _agents
```

---

## 8. 总：改造优先级与风险自检

### 8.1 优先级

| 优先级 | 项 | 内容 | 依赖 |
|--------|----|------|------|
| **P0** | 上层 Permissions 挂载 | core/permissions.py + main_agent 传 permissions + loader 透传 + YAML 模板 | 无（纯新增配置） |
| **P0** | 会话缓存 LRU 治理 | OrderedDict + 上限逐出（get_agent 改造） | 无 |
| **P0** | 会话删除联动 | sessions.py DELETE → rebuild_agent + cleanup_workspace | 无 |
| **P1** | 下层 PolicyBackend + 审计 | backend.py 深化 + audit logger（logging.py 注册）+ 开关 | P0 权限模板（复用规则语义） |
| **P1** | 工具调用审计中间件 | ToolAuditMiddleware（MCP/沙箱边界覆盖） | 无（钩子签名适配） |
| **P1** | 子代理权限覆盖 | 模板 + loader 透传（§6.5） | P0 上层挂载 |
| **P2** | 子代理独立内存 backend | CompiledSubAgent + StateBackend + SUBAGENT_ISOLATION 开关 | P1 之后（学习点：LangGraph 手写演进） |
| **P2** | 审计查询能力 | audit JSONL 简单查询脚本/API | P1 审计落地后 |

**P0 范围说明**：会话级 Backend 与只读强制已在 v2.0 落地；本方案 P0 = 把「安全闭环」补完
（上层规则 + 缓存治理 + 删除联动），P1 = 兜底与审计，P2 = 真隔离迭代。

### 8.2 风险自检清单（评审逐条）

- [ ] **权限路由作用域**：permissions 路径限定在 CompositeBackend 路由前缀（/skills/、/memories/ 等）
      ——已满足（default=FilesystemBackend 无执行能力，`_all_paths_scoped_to_routes` 不触发 NotImplementedError，§3.1）
- [ ] **规则顺序**：deny /skills/** 放最前（先匹配先生效）；新增规则必须审阅顺序
- [ ] **interrupt 与现有 interrupt_on 冲突**：权限 interrupt 由 create_deep_agent 自动合成
      interrupt_on（graph.py:808 核实），与手动 interrupt_on 合并——实施时验证不覆盖
- [ ] **子代理权限替换语义**：YAML 显式 permissions 是「整体替换」非叠加——文档与模板注释已标注；
      防误以为子代理能继承父级 deny
- [ ] **ToolAuditMiddleware 钩子签名**：AgentMiddleware 钩子随 deepagents 版本漂移——
      实施第一步写适配单测（T6），不猜签名（00-security 纪律：验证后再集成）
- [ ] **StateBackend 子代理与断点**：子代理文件存 state → checkpointer 恢复时子代理状态随主
      state 一并恢复（兼容 ✅）；但文件是「随 run 生命周期」的临时数据——P2 设计意图即是临时
- [ ] **审计刷屏**：读操作默认不审计；写审计为 JSONL 滚动（50MB/天滚动，14 份保留，04-logging.md）
- [ ] **PolicyBackend 委托完整性**：写/读方法显式拦截（防 __getattr__ 绕过，同 ReadOnlyBackend 教训）；
      als 等异步方法经 __getattr__ 委托——验收 T3 用异步用例补测
- [ ] **开关矩阵回归**：3 组合（§5.2）各跑 T7 用例——demo 兼容不破坏
- [ ] **密钥纪律**：本方案不引入任何新密钥/环境变量值；audit 日志禁记密钥类字段（args 截断 300 字符）
- [ ] **先红后绿**：每个 P 级改动用 §7 用例先行（fail）→ 实现 → 通过；提交前 pytest 全绿
- [ ] **主仓库纪律**：实施改代码须开 worktree（家规铁律）；本方案文档提交走 develop 直接提交

### 8.3 后续（演进预留）

1. **MemoryMiddleware 启用**（B.1）：backend 会话级 + 权限就绪后配置
2. **LangGraph 手写主图**：子代理节点显式绑定独立 StateBackend（P2 编译子代理机制
   与手写路线互为印证，02-hands-on-training 演进路线）
3. **会话级记忆子目录**（可选演进）：`/memories/{thread_id}/` 路由化（当前保持全局共享）
4. **审计可视化**：audit JSONL → 简单查询 API（管理面）

---

## 附录：v2.0 设计文档同步修订清单（v2 → v3）

审批通过后执行（任务归属：本方案实施批次）：

| 动作 | 内容 |
|------|------|
| `git mv` 升级文件名 | `CompositeBackend文件存储-设计-v2.md` → `CompositeBackend文件存储-设计-v3.md`（05-docs-placement：git mv 保留历史） |
| 版本记录 | 追加 v3.0：§2.8 权限分层章节新增；§2.6 子代理隔离升级（P1 权限覆盖 → P2 CompiledSubAgent）；§2.1 交叉引用 PolicyBackend；§2.2 ReadOnlyBackend 统一进策略层说明 |
| 新增章节 | §2.8 双层权限（上层 FilesystemPermission 模板 + 下层 PolicyBackend 钩子 + 逃逸面边界 + 审计 JSONL）——内容同步本方案 §3 |
| 升级章节 | §2.6 子代理隔离：标注「已支持 P2 原生路径 CompiledSubAgent 独立 backend（graph.py 'runnable' 分支核实）」 |
| 更新目录/关联文档 | 目录加 §2.8；关联文档加本方案文档 |
