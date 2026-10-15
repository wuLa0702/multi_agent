"""横切能力装配点：把分散的中间件按**显式顺序**组装成一条链（阶段 3 收口）。

## 为什么需要这一层

改造前，中间件清单硬编码在 `main_agent._build_agent` 里，带来两个耦合：

1. **新增一个横切能力 = 必须改编排层**（`main_agent.py`）——横切能力本不该
   牵动编排逻辑
2. **顺序靠注释维持**（原文注释："审计在外层，网关在内层"）——没有程序化约束，
   重排一次就靠人肉复核

本模块把装配收口到一处：**新增横切能力只改这里**，`main_agent` 不再动；
顺序在本文件里**显式成列表**，谁在外谁在内一眼可见。

## 为什么实现仍分散在三个目录（这是对的）

能力位置由**职责归属**决定，不为了"集中"而搬家：

| 中间件 | 位置 | 为什么在这 |
|---|---|---|
| `RedactMiddleware` | `llm/redact.py` | 出站脱敏属 LLM 边界 |
| `ToolAuditMiddleware` / `ToolGatewayMiddleware` | `tools/` | 工具审计/调度属工具中心 |
| `TokenUsageMiddleware` / `InterpreterMiddleware` / `TraceMiddleware` | `agent/middlewares/` | Agent 层横切 |

**要收口的是装配，不是实现**——把实现也集中到一个目录，反而会破坏分层。

## 模型选择中间件为何由参数注入

`_configurable_model` 定义在 `main_agent.py`（按请求上下文选模型，属编排层职责）。
若本模块直接 import 它 → `main_agent → builder → main_agent` **循环导入**。
故改为**参数注入**：编排层把自己的模型中间件递进来，本模块负责把它排在链首。

设计依据：`docs/决策/2026-10-15-设计-阶段3横切与阶段4编排-v1.md` §「装配点收口」。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.agent.middlewares.interpreter import build_interpreter_middleware
from src.agent.middlewares.token_usage import TokenUsageMiddleware
from src.agent.rubrics.rubrics import build_rubric_middleware
from src.llm.redact import RedactMiddleware
from src.tools.guardrails.audit import ToolAuditMiddleware
from src.tools.guardrails.gateway import ToolGatewayMiddleware


def build_middlewares(model_middleware: Callable[..., Any] | Any) -> list[Any]:
    """组装 Agent 中间件链（**唯一装配点**；顺序显式声明）。

    Args:
        model_middleware: 模型选择中间件（`main_agent._configurable_model`）。
            由编排层注入而非本模块 import——避免 main_agent 反向循环导入

    Returns:
        中间件列表，**顺序即语义**（见下方逐条注释）。同类型钩子按列表顺序组合，
        **前面的在外层**（langchain 约定：first in list as outermost）

    Note:
        顺序约束（改动前务必确认）：
        - 模型选择在**最外层**：先定模型，后续所有环节才有一致的模型上下文
        - 出站脱敏紧随其后：模型已定 → 对本次入站消息脱敏 → 再交给下游
        - 工具审计在网关**外层**：即使被网关拦（短路），审计也已先留痕
    """
    middlewares: list[Any] = [
        # ① 模型选择（按 ChatContext.model_id 运行时切换）——最外层，先定模型
        model_middleware,
        # ② 出站脱敏（阶段 3）：模型已定 → 脱敏本次入站消息后交下游
        RedactMiddleware(),
        # ③ 上下文用量统计：图执行完算全量 token 并落库
        TokenUsageMiddleware(),
        # ④ 工具审计（P1）：MCP/沙箱逃逸面统一留痕，只记不拦——必须在网关外层
        ToolAuditMiddleware(),
        # ⑤ 工具调度中心（阶段 1.1）：调用前 args_schema 校验，失败短路为错误
        #    ToolMessage 不中断 run。在内层：审计先留痕，网关后校验
        ToolGatewayMiddleware(),
    ]
    # ⑥ 解释器（P2，2026-08-05 解耦）：构建细节在 middlewares/interpreter.py
    middlewares += build_interpreter_middleware()
    # ⑦ Rubric 自评（P1，2026-08-06 设计 §5.4）：rubric_enabled 门控，构建细节在 rubrics.py
    middlewares += build_rubric_middleware()
    return middlewares
