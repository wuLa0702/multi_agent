"""wiki 对接能力域：multi_agent ↔ wiki（llm_wiki_selfbuild）的 REST 双向通道。

**为什么独立成域**（2026-10-15，修 P13 分层违规）：本客户端原先放在
`agent/services/`（编排层），但 **`tools/impl/wiki.py`（能力层）也要用它**——
能力层 import 编排层 = 方向反了，违反 `06-structure-optimization` §2
「只能上层调下层」。下沉为能力域后，编排层 / 入口层 / 工具层都**向下**取用：

```
api/export.py ─┐
agent/memory/ ─┼─→ wiki/（本域）──→ wiki 系统 REST API
tools/impl/  ──┘
```

| 模块 | 方向 | 端点 |
|---|---|---|
| `export_service.py` | 写 | `POST /v1/pages/{path}` |
| `read_service.py` | 读 | `GET /v1/pages/{path}` |

⚠️ 与 `tools/impl/wiki.py`（`write_wiki` 工具）的分工：**本域是外部系统客户端**，
那个是**暴露给 Agent 的工具**（工具调用本域）。别混。

> 依据：`docs/决策/2026-08-15-设计-记忆检索V3接线与Wiki写通道-v1.md`（通道设计）｜
> 迁移记录见 `docs/临时/2026-10-14-汇总-工具中心分支开发笔记-v1.md` P13
"""
