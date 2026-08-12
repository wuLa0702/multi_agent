---
topics: [sop, workflow]
doc_kind: note
created: 2026-08-02
---

# Standard Operating Procedure

> 📋 **规范**：遵循 `docs/规则/文档规范.md`
> 📌 **更新时间**：2026-08-12
> 📝 **版本变更记录**（永久保存，只追加不删除）：
> | 版本 | 日期 | 具体改动 |
> |------|------|---------|
> | v2 | 2026-08-12 | §Workflow (6 steps)：新增 mermaid 流程图（自 llm_wiki_selfbuild SOP 移植，双方规则对齐）；补规范头 |
> | v1 | 2026-08-02 | 初版：6 步工作流表格 + Code Quality |

## Workflow (6 steps)

```mermaid
flowchart LR
    S1["① Create worktree"] --> S2["② Self-check<br/>(spec compliance)"]
    S2 --> S3["③ Peer review"]
    S3 --> S4["④ Merge gate"]
    S4 --> S5["⑤ PR + cloud review"]
    S5 --> S6["⑥ Merge + cleanup"]

    style S1 fill:#e3f2fd,stroke:#1976d2
    style S2 fill:#e8f5e9,stroke:#388e3c
    style S3 fill:#fff3e0,stroke:#f57c00
    style S4 fill:#fce4ec,stroke:#d32f2f
    style S5 fill:#f3e5f5,stroke:#7b1fa2
    style S6 fill:#e0f2f1,stroke:#00796b
```

| Step | What | Skill |
|------|------|-------|
| 1 | Create worktree | `worktree` |
| 2 | Self-check (spec compliance) | `quality-gate` |
| 3 | Peer review | `request-review` / `receive-review` |
| 4 | Merge gate | `merge-gate` |
| 5 | PR + cloud review | (merge-gate handles) |
| 6 | Merge + cleanup | (SOP steps) |

## Code Quality

- Biome: `pnpm check` / `pnpm check:fix`
- Types: `pnpm lint`
- File limits: 200 lines warn / 350 hard cap
