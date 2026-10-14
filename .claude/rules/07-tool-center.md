# 工具中心规范

> 📋 **规范来源**：`docs/决策/2026-10-14-设计-工具中心职责边界-v1.md`（评审稿）
> 📌 **双位置**：本文件 `.claude/rules/`（**权威，自动加载**）＋ `docs/规则/工具中心规范.md`（镜像，内容一致，冲突以本文件为准）
> 📌 **适用范围**：`backend/src/agent/tools/`、`backend/src/mcp/`、工具参数与输出

## 1. 工具定义（唯一真相源）

- **唯一登记处** = `mcp/registry.py::TOOL_REGISTRY`；新增工具**只改这一处**
- 一条 `ToolSpec`：`name / fn / domain / description` 必填；`is_idempotent / risk_level / size / fallback_to / requires_approval` 按需
- 消费方全部从该表派生，**禁止再出现第二份工具清单**：

| 消费方 | 派生函数 |
|--------|----------|
| 主 Agent 挂载 | `tools_for_main()` |
| HITL 门控（编排层按 `hitl_enabled` 追加） | `hitl_tools()` |
| 子代理 YAML 查表 | `get_tool(name)` |

- **禁止**在 `main_agent.py` 等处硬编码工具清单

## 2. 输入规范（写工具参数 schema 时必守）

1. **必填默认必填**：选填参数显式 `= None`，并在 description 说明缺省语义
2. **能枚举就绝不裸 str**：用 `Enum` / `Literal` 约束取值
3. **否定约束双写**：description 写"禁止 …" ＋ JSON Schema 层 `not`/`pattern`
4. **命名所见即所得**：人看得懂、LLM 也看得懂，无歧义
5. **格式只用标准常量**：时间等格式一律 `core/constants.py`（如 `TIMESTAMP_FORMAT`），禁止工具内自定义
6. **参数粒度**：一个工具只做一件事；强事务/整体动作 = 大工具（`size="big"`），可自由编排的原子操作 = 小工具

## 3. 输出规范

- 工具**必须返回结构化数据**，禁止裸 `str` 拼接（阶段 2 起逐步改造）
- 统一经输出适配器归一出参：空值/错误码归一、单位归一
- 协议字段（status / code）**校验失败即报错**，不做"修复"（修复只适用内容里的 LLM 产物）

## 4. 边界（不属工具中心，勿在本层实现）

| 事项 | 归属 |
|------|------|
| 出站脱敏（发远程 LLM 前） | `llm/adapter.py` |
| 高威胁操作审批流 | `agent/hitl/` |
| `trace_id` 生成与贯穿 | 请求入口中间件 |
| 幂等的实现（去重表 / 唯一键） | 工具实现 / 业务层 |
| 降级到哪个备选 | 编排层（按 `fallback_to` / `domain`） |

> 注册表只**声明**（`is_idempotent` / `risk_level` / `fallback_to`），不**执行**这些策略。
