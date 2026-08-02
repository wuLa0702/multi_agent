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

- 一个类 ≤ 200 行；一个函数 ≤ 50 行
- 文件 > 750 行关注（标记拆分候选）；> 1000 行必须拆分
- 拆分按职责垂直切分，公共工具抽独立模块，原文件留 Facade 保持接口不变
