# deepagents Profiles 详细设计 v2（官方文档梳理 + 适用性评估 · 决策记录：经讨论无需开发）

> 📋 **规范**：遵循 `docs/2026-08-02-文档规范.md`
> 📌 **更新时间**：2026-08-06
> 📝 **版本变更记录**（永久保存，只追加不删除）：
> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v2 | 2026-08-06 | 全文重定位为**决策记录**（经讨论无需开发）：新增 §0 结论（开头着重强调不落地 + 触发条件）；§1.2 目标 / §1.3 范围改为决策记录定位；§4.4 新增讨论澄清（国产模型 OpenAI 兼容非冲突 + 三个冲突定性表）；§5.1 新增 D0 结论决策、§5.4 补"P0/P1/P2 标记作废"注记；§6 补"YAML 化 = 工程化"讨论结论；§7.1 改名"（全量，留档）"并补不写入仓库注记；§9.1 验收清单改为"未来落地时执行"；新增 §10 讨论纪要（2026-08-06 问答全景）；§2 / §3 / §8 内容不变 |
> | v1 | 2026-08-06 | 初版：基于官方 Profiles 文档（docs.langchain.com/oss/python/deepagents/profiles）的完整梳理与落地设计——§2 官方能力梳理（两类 Profile / 注册 key / 合并语义 / 解析顺序 / 配置文件 / 插件）；§3 项目现状对接点；§4 关键设计发现（ChatOpenAI 恒推导 provider=openai 陷阱 / 构建期解析边界 / ProviderProfile 不适用）；§5 设计决策（key 策略 / 注册模块 / 字段落地映射 / 不做清单）；§6 边界与取舍；§7 完整核心代码（profiles.py + 接线 + 测试）；§8 测试设计；§9 验收与风险自检 |

> **目录**：
> - §0 结论：经讨论无需开发（先读这里）
> - §1 总·背景、目标与范围
> - §2 分·官方能力梳理（Profiles 是什么）
> - §3 分·项目现状对接点
> - §4 分·关键设计发现（本设计成立的前提）
> - §5 分·设计决策
> - §6 分·边界与取舍
> - §7 分·完整核心代码（留档）
> - §8 分·测试设计
> - §9 总·验收清单与风险自检（未来落地时执行）
> - §10 分·讨论纪要（2026-08-06）

> **关联文档**：
> - 官方文档：`https://docs.langchain.com/oss/python/deepagents/profiles`（2026-08-04 快照）
> - 模型选择机制：`docs/decisions/2026-08-06-计划-上下文工程开发-v2.md`（#9 窗口场景与模型选择解耦）
> - 接线点源码：`backend/src/agent/main_agent.py`（_build_agent / _configurable_model）、`backend/src/llm/adapter.py`（_build_chat_model）、`backend/src/core/model_registry.py`
> - 架构蓝图：`docs/架构/2026-08-02-多agent项目-架构目录-v1.md`
> - 文档规范：`docs/2026-08-02-文档规范.md`（v4：设计方案必含核心代码）

---

## 0. 结论：经讨论无需开发 🔴 v2

> 🔴 **结论（2026-08-06 讨论拍板）**：本项目**不开发、不接入** deepagents Profiles。
> 本文档保留为**决策记录 + 官方能力学习梳理**；设计章节（§5-§7）留档，供未来触发条件满足时复用。

**为什么不做**（详细论证见 §4.4、§6、§10）：

| # | 结论 | 一句话理由 |
|---|------|-----------|
| 1 | 根本冲突：构建期 vs 运行期 | profile 在 `create_deep_agent` **构建期**按"构建传入的模型"解析一次；本项目是**运行时决定模型**（middleware 每次调用换模型）——profile 只能作用于默认模型，运行时切换完全不参与 |
| 2 | key 语义错位 | 三厂商全走 ChatOpenAI → 推导恒为 "openai"，真实厂商映射不到 key；provider 级 "openai" 会误伤全部模型 |
| 3 | 收益不成立 | "按模型配 prompt/工具"已有现成答案：`build_system_prompt` 分层 + ChatContext 运行时注入（更动态）；YAML 化不带来工程化，反而引入第三套配置面（§6） |

**保留价值**：官方能力完整梳理（§2）继续作为学习笔记；若 **P2 子代理模型隔离**落地（不同模型不同行为），profiles 是官方正解，本文档 §5-§7 设计可直接复用（触发条件见 §10.3）。

**明确不做的动作**：不新建 `src/agent/profiles.py`、不接 main.py lifespan、§7 代码不写入仓库（仅留档）。

---

## 1. 总：背景、目标与范围 🔴 v2

### 1.1 背景

项目主线是 deepagents（本机 0.7.1，profiles 模块实测存在）。官方 Profiles 功能是"按模型调优 harness 行为"的正式机制——不修改 `create_deep_agent` 调用点，即可对某个厂商/某个模型追加 prompt 片段、改工具描述、删工具、增减 middleware、调子代理。

本项目已有自己的"运行时模型切换"（SQLite 模型注册表 + `_configurable_model` middleware 每次调用换模型），与 Profiles 的"模型级调优"天然互补。但两者之间存在**关键错位**（§4）：项目所有模型都是 ChatOpenAI 实例（自定义 base_url 走 OpenAI 兼容协议），deepagents 从实例推导 provider **恒为 "openai"**——profile key 的设计必须建立在这个事实上。

本文档 = 官方能力完整梳理（§2）+ 对接现状（§3）+ 三个关键发现（§4）+ 落地设计（§5/§6）+ 可运行核心代码（§7）。

### 1.2 目标 🔴 v2

1. 把官方 Profiles 文档翻译成"字段 × 语义 × 注意点"的完整梳理，不再每次查原文（学习价值，永久保留）
2. 评估本项目是否适用——**结论：不适用，无需开发**（§0 / §4.4 / §10 完整论证）
3. 留档一份"未来若需要可直接复用"的设计蓝图（§5-§7，触发条件见 §0 / §10.3）
4. 明确边界：profile 是构建期静态调优，请求级差异仍走既有 ChatContext 机制

### 1.3 范围 🔴 v2

| 在本文档内 | 不在本文档内 |
|-----------|-------------|
| 官方能力完整梳理（§2，学习笔记） | **落地开发（经讨论不做，§0）** |
| 适用性评估 + 决策记录（§4 / §10） | ProviderProfile 落地（§4.3 论证不适用） |
| 留档设计蓝图（§5-§7，未来复用） | YAML 配置管理（HarnessProfileConfig，§5.5 / §6 论证不做） |
| 与既有运行时模型切换的分工边界 | 插件 entry point 分发（单项目无此需求） |

---

## 2. 分：官方能力梳理（Profiles 是什么）

> 来源：官方 Profiles 文档。本地 deepagents 0.7.1 源码已核对 API 存在性与内置 profile 清单。

### 2.1 两类 Profile 🟠 v1

| 维度 | HarnessProfile（主角） | ProviderProfile（本项目不用） |
|------|------------------------|------------------------------|
| 管什么 | **模型构造完成后**的 harness 行为：prompt 组装、工具可见性、middleware 栈、通用子代理 | **模型构造时**的 kwargs：`init_kwargs` / `pre_init` / `init_kwargs_factory` |
| 触发条件 | 传 `provider:model` 字符串**或**预配置模型实例都生效 | **只**在传 `provider:model` 字符串时生效（内部走 init_chat_model） |
| 典型场景 | 某模型 prompt 风格 / 删工具 / 剥 middleware | 厂商集成的默认构造参数（temperature、header 注入） |
| 官方定位 | "tune how the harness behaves for a particular model" | "narrower companion API……Most callers don't need them" |

### 2.2 HarnessProfile 字段表（7 字段） 🟠 v1

| 字段 | 类型 | 语义 | 注意点 |
|------|------|------|--------|
| `base_system_prompt` | str | 替换 deepagents 内置 base prompt（System prompt 的 `base` key） | 覆盖后失去官方 base 指引，需自行补全 |
| `system_prompt_suffix` | str | 追加在组装结果**最后**（位于调用方 suffix 之后） | 作用于主 agent + 声明式子代理 + 通用子代理，三处全中 |
| `tool_description_overrides` | Mapping[str, str] | 按工具名覆盖工具描述 | 键是工具名 |
| `excluded_tools` | frozenset[str] | 从工具集删除指定工具（按名匹配） | **后置过滤**：能删用户工具也能删 middleware 注入的工具 |
| `excluded_middleware` | frozenset[type \| str] | 从默认栈剥掉指定 middleware | 三种形态：类 / 字符串名 / `module:Class` import ref（懒加载，只用于可信配置）；**FilesystemMiddleware / SubAgentMiddleware / 权限中间件不可剥**（抛 ValueError，要隐藏工具用 excluded_tools） |
| `extra_middleware` | Sequence \| Callable | 追加 middleware 到每个应用此 profile 的栈 | 可惰性工厂；序列化受限（见 §2.5） |
| `general_purpose_subagent` | GeneralPurposeSubagentProfile | 关 / 改名 / 换 prompt 通用子代理 | 字段级合并；`system_prompt` 与 `base_system_prompt` 同时设时，子代理专属 prompt 优先 |

**prompt 组装顺序（关键，官方原文）**：调用方 `system_prompt=` **始终在最前**，`system_prompt_suffix` **始终在最后**——与选哪个模型无关。本项目 `build_system_prompt()` 传的是 `system_prompt=`，落在最前；profile 的 suffix 落在最后，两者互不干扰。

### 2.3 注册 key 与解析 🟠 v1

- **key 两种粒度**：provider 级（`"openai"` → 该厂商全部模型）/ 模型级（`"openai:gpt-5.5"` → 仅该模型）
- **解析时合并**：provider 级 + 模型级同时存在 → 逐字段合并，模型级未设字段继承 provider 级，设了则覆盖
- **同名重注册 = 叠加合并**，不是替换（§2.4 的合并语义表）
- **预配置实例的查找顺序**（本项目走这条路，0.7.1 源码 `harness_profiles.py:1256-1319` 核对）：
  1. 从实例推导 `provider:identifier` 后精确匹配（`get_model_provider` → `_get_ls_params()["ls_provider"]`；`get_model_identifier` → `model_name` 或 `model` 字段）
  2. identifier 本身含 `:` 时才做 identifier-only 匹配（防裸 identifier 误中 provider 级 profile）
  3. provider-only 兜底
- **无通配符**：不存在"匹配所有 provider"的 key；想全局生效的调整应放在 `create_deep_agent` 调用点，不放 profile
- 每个子代理会**用自己的模型**重跑一次 profile 解析

### 2.4 合并语义表 🟠 v1

| 字段 | 合并行为 |
|------|----------|
| `base_system_prompt` / `system_prompt_suffix` | 新值覆盖；未设则继承 |
| `tool_description_overrides` | 按 key 逐条合并；同 key 新值覆盖 |
| `excluded_tools` / `excluded_middleware` | **集合并集** |
| `extra_middleware` | 按名合并：同名新实例在原位置替换，新名字追加 |
| `general_purpose_subagent` | 字段级合并（未设字段继承） |
| `init_kwargs`（provider） | 按 key 逐条合并；同 key 新值覆盖 |
| `pre_init`（provider） | 链式：先已存在，后追加 |
| `init_kwargs_factory`（provider） | 工厂链式，每次 resolve 时输出合并 |

### 2.5 配置文件与插件 🟠 v1

- **HarnessProfileConfig**：YAML/JSON 背书的声明式子集（prompt 文本、工具描述覆盖、excluded_tools/excluded_middleware、通用子代理编辑），持有 `to_dict` / `from_dict` / `from_harness_profile`；`register_harness_profile` 两类都收，无需手动转换
- **序列化限制**：非空 `extra_middleware`、`__main__` 或函数作用域内声明的 middleware 类 → `from_harness_profile` 抛 ValueError；类形态 excluded_middleware 序列化为 public alias（有 `serialized_name`）或 `module:Class` ref
- **插件分发**：`importlib.metadata` entry point（组名 `deepagents.harness_profiles` / `deepagents.provider_profiles`），目标为零参 callable；加载顺序 = 内置 → entry-point 插件 → 用户直接注册，全部走同一叠加语义

### 2.6 内置 profile（0.7.1 实测） 🟠 v1

- harness 级：anthropic opus-4.7 / sonnet-4.6 / haiku-4.5、openai codex、nvidia nemotron-3-ultra——**全是模型级 key**
- provider 级：openai / openrouter / nvidia（模型构造 kwargs）
- 与本项目关系：内置 anthropic/nvidia 与我们的 provider 无关；openai 的 harness profile 是模型级（`openai:codex-*`），**不会匹配**我们的 model_name（deepseek-v4-flash 等）——无冲突，无需处理

---

## 3. 分：项目现状对接点

### 3.1 现有模型选择机制 🟠 v1

- 真相源 = SQLite `providers/models` 表（seed：deepseek-v4-flash / deepseek-v4-pro / doubao-seed-evolving / Doubao-Seed-2.0-Code / glm-4-plus），lifespan 时 `get_registry().load(conn)` 加载进内存缓存（`core/model_registry.py`）
- `llm/adapter.py: get_chat_model(model_id)`：按 DB 模型 ID 构造 ChatOpenAI（base_url / api_key / model_name 全来自 DB 配置；temperature=0.7 / timeout=60s / max_retries=2 在 `_build_chat_model` 集中）
- 运行期切换：`main_agent.py` 的 `_configurable_model` middleware（`@wrap_model_call`）每次模型调用按 `ChatContext.model_id` 换模型实例（`request.override(model=...)`），agent 图本身单例复用不重建

### 3.2 现有组装点 🟠 v1

`_build_agent(thread_id)`（main_agent.py:248）：`create_deep_agent(model=默认模型, system_prompt=build_system_prompt() 分层组装, subagents=YAML loader 同模型, middleware=[_configurable_model, TokenUsage, ToolAudit, interpreter…], tools=内部+外部 MCP, context_schema=ChatContext, checkpointer/store/memory/backend/permissions…)`。

### 3.3 接线点 🟠 v1

`api/main.py` lifespan：`get_registry().load(conn)` 成功之后（与 MCP client 同 try 块，失败不阻断降级）。Profiles 注册**必须**在 registry load 之后（存在性校验依赖注册表）。

---

## 4. 分：关键设计发现（本设计成立的前提） 🔴 v2

### 4.1 ⚠️ ChatOpenAI 实例一律推导 provider="openai" 🟠 v1

0.7.1 源码 `_models.py` 核对：`get_model_provider()` 取 `model._get_ls_params()["ls_provider"]`，而 langchain-openai 的 ChatOpenAI 类**硬编码** ls_provider="openai"——与 base_url 指向谁无关。

**直接后果**（本项目 deepseek / ark / zhipu 三个厂商全走 ChatOpenAI）：
- profile 推导的 provider 恒为 `"openai"`，identifier = model_name（ChatOpenAI 的 model 参数，即 DB 配置的模型名）
- **模型级 key 只能是 `openai:<model_name>`**（如 `openai:deepseek-v4-flash`）
- DB 里的 provider slug（deepseek / ark / zhipu）**不能**用作 profile key——推导永远到不了这些 slug
- 注册 provider 级 `"openai"` = 命中本项目**全部**模型（危险，禁止；也是本项目唯一能"全局生效"的 key——而全局调整官方建议放 create_deep_agent 调用点，见 §2.3）

### 4.2 ⚠️ Profile 是构建期解析，运行期换模型不重解析 🟠 v1

- HarnessProfile 在 `create_deep_agent` **构建期**解析（针对构建时传入的模型实例），影响的是 prompt 组装 / 工具可见性 / middleware 栈 / 子代理配置——全部是**构建期静态决定**
- 本项目运行期换模型走 `_configurable_model` 的 `request.override(model=...)`，**不会触发 profile 重解析**
- 结论：profile 生效对象 = **构建时传入的默认模型**；用户会话中途切模型，prompt/工具/middleware 仍是默认模型的 profile
- 评估：与现状一致不倒退——现有 `build_system_prompt()` 也是静态组装，请求级差异（mode 代理模式）经 ChatContext 注入。若未来要"按模型换 profile"：会话重建（`rebuild_agent` 已有）或 ChatContext 扩展，列为 P2 演进（§6）

### 4.3 ProviderProfile 不适用于本项目 🟠 v1

- ProviderProfile 只在传 `provider:model` 字符串时生效；本项目永远传预配置实例（DB 驱动构造）
- 模型构造参数已集中且唯一：`llm/adapter.py:_build_chat_model`（temperature/timeout/max_retries）——这正是 ProviderProfile 想管的东西，**本项目已有唯一真相源，不引入第二套**
- `pre_init`（密钥校验）/ `init_kwargs_factory`（运行时派生 kwargs）的场景本项目由 adapter + registry 承担

### 4.4 讨论澄清：格式误解与冲突定性（2026-08-06） 🔴 v2

**先澄清一个"伪冲突"——国内模型格式**：deepseek / 智谱 / 火山 ark 都提供 **OpenAI 兼容的 chat completions 接口**——这正是项目用 `ChatOpenAI` 一个类通吃三家（只换 base_url/api_key）的原因。"推导为 openai"是**协议层伪标识**（`_get_ls_params()` 类名硬编码，与 base_url 无关），不是把它们当成 OpenAI 模型。国产模型对 OpenAI 协议是**兼容子集**（如无 content-block 协议支持，main_agent 注释已提），但 profile 只调 prompt/工具/middleware，不走这些特性——**格式不是冲突**。

**真冲突共 3 个**：

| # | 冲突 | 性质 | 后果 |
|---|------|------|------|
| 1 | 构建期 vs 运行期 | 根本冲突 | profile 只作用于构建时默认模型；运行时切换完全不参与（§4.2） |
| 2 | key 语义错位 | 设计层 | 只能写 `openai:<model_name>`；provider 级 "openai" 误伤全部模型（§4.1/§5.2） |
| 3 | 未来兼容风险 | 运维层 | deepagents 升级若新增 provider 级 "openai" profile，静默命中全部模型（§9.2） |

---

## 5. 分：设计决策 🔴 v2

### 5.1 决策总览 🔴 v2

| # | 决策 | 理由 |
|---|------|------|
| D0 | **（2026-08-06 拍板）不落地开发**，本文档转为决策记录 | §0 / §4.4 / §10：构建期 vs 运行期根本冲突 + key 语义错位 + 收益已被现成机制覆盖；触发条件见 §0 / §10.3 |
| D1 | 只用 HarnessProfile，不用 ProviderProfile | §4.3：传实例场景下不生效；构造参数已有唯一真相源 |
| D2 | key 一律模型级 `openai:<model_name>` | §4.1：推导恒为 openai；DB slug 用不上 |
| D3 | 禁止注册 provider 级 `"openai"` | 会命中全部模型（含内置 openai codex 之外的全部厂商） |
| D4 | 注册模块 `src/agent/profiles.py`，lifespan registry.load 后调用 | 存在性校验依赖注册表；幂等、进程重启重注册 |
| D5 | `_PROFILE_TABLE` 以 DB model_name 为主键，注册前校验模型真实存在 | 防幽灵 key（表删了模型、profile 还在注册） |
| D6 | P0 只用 `system_prompt_suffix` / `tool_description_overrides` / `excluded_tools` / `general_purpose_subagent`；`base_system_prompt` / `excluded_middleware` / `extra_middleware` 观望 | 后三者动官方默认栈/官方 base，风险大，P2 再议（§5.4） |
| D7 | 不做 YAML 配置管理 / 插件 entry point | 项目配置真相源是 SQLite + 代码，第三套真相源违反"唯一真相源"精神；单项目无插件分发需求 |
| D8 | profile 只管构建期静态调优；请求级差异（mode/模型）仍走 ChatContext + middleware | §4.2 边界；per-request profile 官方无此能力 |

### 5.2 key 策略 🟠 v1

- key 格式：`openai:<model_name>`，`<model_name>` 与 DB models 表 `model_name` 字段一致（如 `openai:deepseek-v4-flash`）
- 模型在 DB 中改名的联动：`_PROFILE_TABLE` 的 key 同步改（注册前存在性校验会告警漏改）
- 同模型跨厂商重名（如 ark 与 deepseek 都有同名模型名）：key 冲突无法区分——本项目 seed 无重名，文档标注此限制

### 5.3 注册模块与时机 🟠 v1

- `src/agent/profiles.py` 暴露 `register_all_model_profiles() -> int`（新增注册数，幂等）
- 调用点：`api/main.py` lifespan 内 `get_registry().load(conn)` 之后（同 try 块，失败不阻断——降级无 profile）
- 状态：模块级 `_registered_keys` 集合去重；进程重启重新注册（无持久化，注册表本身是内存态，一致）

### 5.4 HarnessProfile 字段落地映射 🔴 v2

| 字段 | 决策 | 用法 / 理由 |
|------|------|-------------|
| `system_prompt_suffix` | ✅ P0 主力 | 按模型族注入行为约束（弱模型简洁/强模型详尽），落在组装最末，与 `build_system_prompt()` 不冲突 |
| `tool_description_overrides` | ✅ P0 可选 | 弱模型简化描述、强模型补充参数说明 |
| `excluded_tools` | ✅ P0 可选 | 弱模型删重工具（如 `run_command_in_sandbox`）；能删内部工具也能删 middleware 注入工具 |
| `general_purpose_subagent` | ✅ P0 可选 | 弱模型 `enabled=False` 关通用子代理省 token（与 subagents YAML 的模型隔离呼应） |
| `base_system_prompt` | ⏳ P2 观望 | 覆盖官方 base 需自行补全指引，现阶段保留官方 base |
| `excluded_middleware` | ⏳ P2 观望 | 默认栈（Filesystem/SubAgent/权限）不可剥；剥自有中间件需验证与 TokenUsage/ToolAudit/interpreter 的顺序 |
| `extra_middleware` | ⏳ P2 观望 | 与项目自有中间件栈叠加顺序需验证；序列化受限（§2.5） |

> ⚠️ 注（2026-08-06 经讨论不落地）：上表 P0/P1/P2 标记**作废**，仅作未来落地参考；当前不实施任何字段。

### 5.5 不做清单 🟠 v1

- ❌ ProviderProfile（§4.3）
- ❌ HarnessProfileConfig YAML 管理（§5.1 D7）
- ❌ 插件 entry point（D7）
- ❌ provider 级 "openai" 注册（D3）
- ❌ per-request 动态 profile（§4.2，P2 演进候选）

---

## 6. 分：边界与取舍 🔴 v2

**两条调优轴线的分工**：

| 轴线 | 机制 | 粒度 | 生命周期 | 管什么 |
|------|------|------|----------|--------|
| 模型族静态调优 | HarnessProfile（本文档） | 模型级 key | 构建期一次解析 | prompt suffix / 工具可见性 / 子代理开关 |
| 请求级差异 | ChatContext + `_configurable_model` middleware | 每次请求/每次调用 | 运行期 | 模型选择（model_id）、代理模式（mode）、上下文场景（context_profile） |

**为什么这样切**：profile 是官方"不改调用点按模型调 harness"的机制，天然匹配**模型族**差异（deepseek-v4-flash 与 deepseek-v4-pro 的行为差异是静态的）；而单次对话里用户手动切模型属于**请求级**差异，已有 middleware 机制，不需要 profile 参与。

**关于"YAML 化 = 工程化标准化"（2026-08-06 讨论澄清）**：这个直觉**对了一半**。YAML 只是序列化外壳（HarnessProfileConfig = 它的声明式子集），工程化的价值不来自 YAML 本身，而来自"配置有唯一真相源、可管理、可审计"——本项目已用**更动态**的方式实现：SQLite 表 + API 管理 + 运行时生效。引入 yaml 配置文件反而成为**第三套配置面**（SQLite / 代码 / yaml 并立），违背"唯一真相源"纪律。

**演进选项（P2）**：
1. 会话内切模型后按新模型 profile 重建 agent——`rebuild_agent(thread_id)` 已有，重建成本是纯内存 compile，可行但会丢执行中状态，需评估
2. 把"按模型族的 prompt 约束"从 profile 下沉为 ChatContext 字段（现 mode 注入同款）——绕开构建期限制，但等于放弃 profile 的官方机制，两套并存增加维护面
3. 官方支持 per-request profile 解析后再接（观望，无时间表）

---

## 7. 分：完整核心代码 🔴 v2

### 7.1 `backend/src/agent/profiles.py`（全量，留档） 🔴 v2

> ⚠️ 留档说明（2026-08-06 经讨论不落地）：以下代码**不写入仓库**，仅作未来复用参考；若 P2 子代理模型隔离落地，按 §7.2 接线即可启用。

```python
"""deepagents HarnessProfile 注册模块（Profiles 详细设计 §5/§7 落地）。

关键前提（设计文档 §4）：
- 项目所有模型都是 ChatOpenAI 实例（自定义 base_url 走 OpenAI 兼容协议），
  deepagents 从实例推导 provider 一律得 "openai"（_get_ls_params 的
  ls_provider，langchain-openai 硬编码），identifier = model_name（ChatOpenAI
  的 model 参数）→ 模型级 profile key 只能是 `openai:<model_name>`。
- 禁止注册 provider 级 "openai"：会命中本项目全部模型（设计 §5.1 D3）。
- profile 在 create_deep_agent **构建期**解析（针对构建时传入的模型实例）；
  运行期 _configurable_model 换模型不重解析 → profile 只做"构建时默认模型"
  的静态调优，请求级差异走 ChatContext（设计 §4.2/§6）。
- 注册时机：lifespan 模型注册表加载后（main.py 调用 register_all_model_profiles），
  幂等；进程重启重新注册，无持久化状态。
"""

from __future__ import annotations

import logging

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)

from src.core.model_registry import get_registry

logger = logging.getLogger(__name__)

# 模型标识符 → HarnessProfile 构造参数（本项目唯一真相源，改这里即可）。
# key 一律模型级 `openai:<model_name>`（<model_name> 与 DB models 表
# model_name 一致；DB 改名必须同步改这里——注册前校验会告警漏改）。
_PROFILE_TABLE: dict[str, dict] = {
    # 轻量模型：关通用子代理（省 token）+ 简洁约束 + 删重工具
    "openai:deepseek-v4-flash": {
        "system_prompt_suffix": "回答保持简洁，先给结论再给理由。",
        "general_purpose_subagent": GeneralPurposeSubagentProfile(enabled=False),
        "excluded_tools": {"run_command_in_sandbox"},
    },
    # 旗舰模型：保留通用子代理，仅微调工具描述
    "openai:deepseek-v4-pro": {
        "tool_description_overrides": {
            "run_code_in_sandbox": "在云端沙箱执行 Python 代码并返回输出（网络隔离）。",
        },
    },
}

# 已注册 key 去重（模块级；进程重启后重新注册，无跨进程状态）
_registered_keys: set[str] = set()


def register_all_model_profiles() -> int:
    """把 _PROFILE_TABLE 全部注册进 deepagents profile 注册表（幂等）。

    在 lifespan 模型注册表加载后调用；DB 中不存在的模型跳过（防幽灵 key
    ——registry 未加载或模型缺失时都不注册）。

    Returns:
        本次新增注册数（重复调用返回 0）
    """
    registry = get_registry()
    if not registry.is_loaded():
        logger.warning("模型注册表未加载，跳过 Profiles 注册（lifespan 后补齐）")
        return 0

    added = 0
    for key, fields in _PROFILE_TABLE.items():
        if key in _registered_keys:
            continue
        if not _model_exists(registry, key):
            logger.warning("Profiles 跳过不存在的模型 key=%s（DB 无此 model_name）", key)
            continue
        register_harness_profile(key, HarnessProfile(**fields))
        _registered_keys.add(key)
        added += 1
        logger.info("Profiles 注册：%s", key)
    return added


def _model_exists(registry, key: str) -> bool:
    """key 形如 `openai:<model_name>`；按 model_name 反查 DB 模型配置。

    经 ModelInfo.id → registry.get_model(id) 取权威 ModelConfig，
    不依赖 ModelInfo.name 与 model_name 的等价性假设。
    """
    _, _, model_name = key.partition(":")
    for provider in registry.list_providers():
        for info in provider.models:
            cfg = registry.get_model(info.id)
            if cfg is not None and cfg.model_name == model_name:
                return True
    return False
```

### 7.2 `backend/src/api/main.py` 接线（lifespan 内） 🟠 v1

```python
# 文件顶部导入区追加：
from src.agent.profiles import register_all_model_profiles

# lifespan 内 registry.load 之后（与 MCP client 同 try 块，失败不阻断降级）：
        try:
            await get_registry().load(conn)
            register_all_model_profiles()  # Profiles 注册（幂等；失败不阻断——降级无 profile）
            await get_mcp_client_manager().connect_all(conn)
        except Exception:
            logging.exception("注册表/MCP 加载失败——运行时模型回落 .env，agent 仅用内部工具")
```

### 7.3 `backend/tests/test_agent/test_profiles.py`（全量） 🟠 v1

```python
"""Profiles 注册模块测试（设计文档 §7.3/§8）。

策略：monkeypatch register_harness_profile 捕获调用参数——不依赖 deepagents
内部 API（_get_harness_profile 是私有），也不污染进程内全局 profile 注册表
（注册是叠加态，无官方 reset）。存在性守卫依赖 seeded_registry fixture
（conftest 已有：reset → load tmp DB → yield → reset）。
"""

import pytest

from src.agent import profiles


@pytest.fixture(autouse=True)
def _reset_state():
    """每个用例重置模块级状态（_PROFILE_TABLE 与已注册集合），隔离用例间。

    注意：用例会重绑定 _PROFILE_TABLE（如幽灵 key 用例），必须在 teardown
    恢复原引用，否则污染后续用例。
    """
    saved_table, saved_keys = profiles._PROFILE_TABLE, profiles._registered_keys
    profiles._PROFILE_TABLE, profiles._registered_keys = dict(saved_table), set()
    yield
    profiles._PROFILE_TABLE, profiles._registered_keys = saved_table, saved_keys


async def test_register_all_idempotent(monkeypatch, seeded_registry):
    """重复调用只注册一次：第二次返回 0，register_harness_profile 调用数不变。"""
    calls = []
    monkeypatch.setattr(
        profiles, "register_harness_profile",
        lambda key, profile: calls.append((key, profile)),
    )
    expected = len(profiles._PROFILE_TABLE)
    assert profiles.register_all_model_profiles() == expected
    assert profiles.register_all_model_profiles() == 0
    assert len(calls) == expected  # 第二次幂等，未重复注册


async def test_register_skips_unknown_model(monkeypatch, seeded_registry):
    """DB 不存在的模型 key 跳过（幽灵 key 守卫）：不注册、返回 0。"""
    calls = []
    monkeypatch.setattr(
        profiles, "register_harness_profile",
        lambda key, profile: calls.append((key, profile)),
    )
    profiles._PROFILE_TABLE = {"openai:ghost-model-not-in-db": {"system_prompt_suffix": "x"}}
    assert profiles.register_all_model_profiles() == 0
    assert calls == []


def test_register_skips_when_registry_not_loaded(monkeypatch):
    """注册表未加载（registry.is_loaded()=False）→ 跳过且告警，不注册。"""
    calls = []
    monkeypatch.setattr(
        profiles, "register_harness_profile",
        lambda key, profile: calls.append((key, profile)),
    )
    assert profiles.register_all_model_profiles() == 0
    assert calls == []


async def test_register_passes_harness_profile_fields(monkeypatch, seeded_registry):
    """注册参数是 HarnessProfile 实例，字段与 _PROFILE_TABLE 一致（关键断言）。"""
    captured = {}
    monkeypatch.setattr(
        profiles, "register_harness_profile",
        lambda key, profile: captured.update({key: profile}),
    )
    profiles.register_all_model_profiles()
    key = "openai:deepseek-v4-flash"
    assert key in captured
    profile = captured[key]
    assert profile.system_prompt_suffix == "回答保持简洁，先给结论再给理由。"
    assert profile.excluded_tools == {"run_command_in_sandbox"}
    assert profile.general_purpose_subagent.enabled is False
```

> ⚠️ 前提核对：`seeded_registry` 的 tmp DB 走 `seed_defaults`，模型名与 §3.1 的 seed 一致（deepseek-v4-flash 等）；若 seed 数据变更，`_PROFILE_TABLE` 的 key 与 `test_register_passes_harness_profile_fields` 断言需同步。

### 7.4 调用链说明 🟠 v1

```
进程启动
  └─ api/main.py lifespan
      ├─ init_checkpointer() / init_store()
      ├─ get_registry().load(conn)          # 模型注册表就绪
      ├─ register_all_model_profiles()      # ★ 本文档新增：读 _PROFILE_TABLE →
      │    └─ deepagents.register_harness_profile("openai:<model_name>", HarnessProfile(...))
      │         └─ 全局 profile 注册表（进程内，幂等叠加）
      └─ get_mcp_client_manager().connect_all(conn)

会话请求（运行期，与 profiles 无交互）
  └─ get_agent(thread_id) → _build_agent → create_deep_agent(model=默认模型, ...)
       └─ deepagents 构建期解析：默认模型实例 → openai:<model_name> → 命中 profile
            └─ 应用 system_prompt_suffix / excluded_tools / general_purpose_subagent
  └─ _configurable_model middleware：请求级换模型（不触发 profile 重解析）
```

---

## 8. 分：测试设计 🟠 v1

| # | 用例 | 类别 | 断言 | 依赖 |
|---|------|------|------|------|
| 1 | 重复注册幂等 | 正常 | 第二次返回 0，注册调用数不变 | seeded_registry + monkeypatch |
| 2 | 幽灵 key 跳过 | 错误（配置漂移） | 返回 0，无注册调用，warning 日志 | seeded_registry + monkeypatch |
| 3 | 注册表未加载降级 | 边界 | 返回 0，无注册调用 | monkeypatch（不加载 registry） |
| 4 | 字段透传正确 | 正常 | HarnessProfile 实例字段与 _PROFILE_TABLE 一致 | seeded_registry + monkeypatch |
| 5 | 启动冒烟（手动） | 集成 | 日志出现 `Profiles 注册：openai:deepseek-v4-flash`；切到该模型的对话行为符合 profile（如通用子代理不再触发） | 真实起服务 + 浏览器 |

> 说明：不写"解析命中"单测——deepagents 的解析器是私有 `_get_harness_profile`，且构建期断言需跑 create_deep_agent 全链路（重）；解析链已在 §4.1 用源码核对，冒烟用例兜底。

---

## 9. 总：验收清单与风险自检 🔴 v2

### 9.1 验收清单（当前不执行：经讨论不落地，以下为"未来落地时"的执行清单） 🔴 v2

- [ ] `backend/src/agent/profiles.py` 落地，`_PROFILE_TABLE` 按模型族填写
- [ ] main.py lifespan 接线，启动日志出现 Profiles 注册行
- [ ] `pytest backend/tests/test_agent/test_profiles.py` 全绿
- [ ] 冒烟：默认模型带 profile 的会话，prompt 尾部出现 suffix；被 excluded_tools 删除的工具不再被调用
- [ ] 运行时切模型不崩、行为与 profile 无关（§4.2 边界生效）

### 9.2 风险自检

| 风险 | 等级 | 缓解 |
|------|------|------|
| deepagents 升级改变 profile API / 解析推导（`_get_ls_params` 或 `model_name` 字段） | 中 | §2 梳理标注 0.7.1 实测；升级后跑用例 1-4 + 冒烟复核 §4.1 推导 |
| provider 级 "openai" 被误注册（含第三方插件） | 中 | D3 明确禁止；entry point 插件会叠加注册（§2.5）——发现行为异常先查注册表 |
| `base_system_prompt` 覆盖后丢失官方指引 | 低 | P2 观望，现阶段不启用 |
| `_PROFILE_TABLE` 与 DB seed 漂移（模型改名/下线） | 低 | 存在性校验告警 + 用例 2 兜底 |
| 内置 openai codex profile 与自定义模型名撞 key | 低 | 模型级 key 用 DB model_name，内置 key 是 codex-*，无交集 |

---

## 10. 分：讨论纪要（2026-08-06，co-creator 问答全景） 🔴 v2

> 决策记录惯例：保存"为什么当时不做"的完整上下文，供未来重新评估时读取。

### 10.1 提出的疑问与澄清

| # | 疑问 | 澄清 |
|---|------|------|
| 1 | 冲突是不是很多？ | 真冲突 3 个（§4.4）；其中"国内模型格式"不是冲突（见 #2） |
| 2 | 国内模型不一定支持 OpenAI 格式？ | **误解**。deepseek/智谱/ark 都提供 OpenAI 兼容 chat completions 接口——这正是项目用 ChatOpenAI 一把通吃三家（只换 base_url）的原因；"推导为 openai"是协议层伪标识（`_get_ls_params()` 类名硬编码），不是把它们当 OpenAI 模型。国产模型是兼容子集（如无 content-block 协议），但 profile 只调 prompt/工具/middleware，不走这些特性 |
| 3 | provider 级与模型级 key 谁大？ | **provider 级更大**：命中该厂商全部模型；模型级只命中一个。同时注册时模型级字段覆盖、未设字段继承 provider 级（CSS 类比：`p{}` 全局 vs `#id{}` 覆盖） |
| 4 | YAML 化 = 工程化标准化？ | **半对**：YAML 只是序列化外壳；工程化 = 唯一真相源 + 可管理可审计，本项目已用 SQLite + API + 运行时生效实现（更动态）；加 yaml = 第三套配置面（§6） |
| 5 | 到底能不能做？ | 能做，但它解决的不是本项目当前问题——构建期静态 vs 运行期动态的根本错位（§4.2） |

### 10.2 三个选项评估

| 选项 | 内容 | 评估 |
|------|------|------|
| A 不落地 | 文档转决策记录/学习笔记，不写代码 | ✅ **采纳**：冲突真实存在、收益已被现成机制覆盖（build_system_prompt 分层 + ChatContext 运行时注入） |
| B 最小落地 | 只为默认模型注册 suffix/工具裁剪 | 可做但收益小；留作 P2 子代理模型隔离的前置练习 |
| C 重构拥抱 | 模型切换改为重建 agent（rebuild_agent 已有），profile 变真相源 | 大改对抗现有运行期架构，否决 |

### 10.3 触发条件（何时重新评估本文档）

1. **P2 子代理模型隔离落地**（如搜索子代理用便宜模型、主 agent 用旗舰模型）→ 每个 agent 按自己的模型调行为，profiles 是官方正解，§5-§7 设计直接复用
2. deepagents 未来支持 per-request profile 解析 → 重新评估与运行期切换的整合
3. 需要"模型族级"工具/中间件差异，且不再满足于默认模型静态调优
