# eval 评估资产目录（系统内置，入库）

> 依据：`docs/decisions/2026-08-10-设计-评估体系-v1.md`（P0-a）。

| 文件 | 用途 | 说明 |
|------|------|------|
| `tasks.jsonl` | 评估任务集 | 10 个研究任务（3 easy + 4 medium + 3 hard），query 内置引用编号要求（A1 指标前提），fact_points 预填（P2 事实准确率用） |

## 实施说明（设计偏离记录）

- 设计文档 §3 原写 `data/eval/tasks.jsonl`，实施时发现 `data/` 为运行时产物（gitignore，红线不入库）——**任务集是人工标注的入库资产**，改放 `backend/assets/eval/`（与 builtin skills 同一资产层规范，§3.5）；**报告输出**仍走 `data/eval/reports/`（运行时产物，不入库，面试素材以文档形式沉淀）。
