# 编码风格

## 命名规范

| 元素 | 规范 | 示例 |
|------|------|------|
| 文件/函数/变量 | `snake_case` | `main_agent.py` / `planner.py` |
| 类 | `PascalCase` | `class AgentHarness:` |
| 常量 | `UPPER_SNAKE` | `ALLOWED_PREFIXES` |
| API 路由 | `/v1/` 前缀 | `/v1/chat/stream` |

## 类型注解

所有函数签名必须含类型注解：

```python
def plan(self, goal: str, context: dict[str, Any]) -> list[Task]:
    ...
```

## 文档字符串

模块 / 类 / 公开函数必须有 docstring（功能 + Args + Returns + Raises）。

## 导入顺序

标准库 → 第三方 → 项目内部，每组空一行。

## 错误处理

- 自定义异常类，不直接 `raise Exception`
- 异常分级（可重试/不可重试），统一 `core/errors.py`
- LLM 调用超时 + 重试（`llm/retry.py`）

## 代码组织

- 一个类 ≤ 200 行；文件 > 750 行关注（标记拆分候选）；> **800** 行必须拆分（有效业务代码行口径，见 `06-structure-optimization.md` §1）
- **函数长度铁律（2026-08-04 确立，chat.py 171 行事故教训；2026-08-11 回写 800/80 强制）**：
  - 非底层函数 **> 80 行 → 必须拆分解耦**（强制，不再"考虑"）
  - **> 160 行 → 拆分失败信号**（拆解后仍 >160 必须继续拆，质量底线）
  - **底层函数豁免**：全局通用工具 / 基础算法 / 通用解析封装——docstring 声明"底层函数，按规范豁免"；业务逻辑 / Agent 编排 / 流程控制不豁免
  - **宁愿多文件多函数，保持结构清晰、松耦合、适合单测**——顶层路由/处理器只做编排，
    业务步骤抽独立函数（如 chat.py 的 `_resolve_session` / `_prepare_new_messages` / `_event_stream`）
- 拆分按职责垂直切分，公共工具抽独立模块，原文件留 Facade 保持接口不变
- 拆分后用 AST 扫描验证（遍历函数行数），新代码提交前必须过线（≤80 行）
