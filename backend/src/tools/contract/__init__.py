"""工具契约域：工具"长什么样"——输出信封、双通道装配、错误归一。

**为什么独立成域**（2026-10-15 目录收拢）：这三个模块此前平铺在 `tools/` 一级，
与"护栏""实现""通道"混在一起。它们共属一条链——**约定工具的产出形态**：

```
result.py     定义契约    ToolResult 三态信封（ok / degraded / error）+ render
     ↓
adapter.py    落实契约    拆成 (content 给 LLM, artifact 给程序) 双通道 → BaseTool
     ↓
error_map.py  归一入契约  异常 / HTTP 状态 → ToolErrorCode（`ToolResult.error_code` 的唯一来源）
```

| 模块 | 代表符号 | 给谁 |
|---|---|---|
| `result.py` | `ToolResult` / `render` / `exhausted_result` | 所有 `impl/` 工具 + 下游（审计/SSE/编排） |
| `adapter.py` | `as_lc_tool` / `artifact_of` | `registry.py`（装配挂载形态时包在最外层） |
| `error_map.py` | `classify_exception` / `code_for_http_status` | `result.py`（填 `retryable`）+ `runtime/audit.py` |

> 设计依据：`docs/决策/2026-10-14-设计-工具中心阶段2输出侧-v1.md`｜
> 目录讨论见 `docs/临时/2026-10-14-汇总-工具中心分支开发笔记-v1.md`
"""
