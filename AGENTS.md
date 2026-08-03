# AGENTS.md — Agent 全局操作手册

> 本项目由 AI 与人类协作开发。本文档是**所有 Agent 的第一行动指南**（deepagents 体系：本文件同时作为主 Agent 的操作手册）。

## 你是谁
你是 multi-agent 项目的开发 Agent。项目是**学习项目**（面试导向），核心价值 = 你能讲清每个架构决策的 Why。

## 工作流程（6 步）
1. **读蓝图画图**：动手前先读 `docs/架构/多agent项目-架构目录-v1.md`（权威蓝图，v2.3）
2. **读规则**：`CLAUDE.md` + `.claude/rules/`（安全/风格/API/测试/手写纪律）
3. **查经验**：`docs/learnings/`（踩坑记录，先查再动手）
4. **实现**：核心逻辑手写（Graph/State），样板 AI 提速
5. **验证**：先红后绿，pytest 全绿才算完成
6. **沉淀**：踩坑写入 docs/learnings/，决策变更更新架构文档版本表

## 硬约束（违反 = 严重问题）
- **密钥零容忍**：只在 .env.dev/.env.prod，不入 git、不进聊天、不打印
- **环境切换**：APP_ENV=dev/prod 二选一，禁止叠加读 .env
- **依赖单向**：api → agent → {mcp, sandbox, memory, db}
- **write_todos 绝不摘要**：任务清单原文保留，只做状态推进
- **提交前确认**：先给计划等人类确认；提交格式/推送策略/红线见 `.claude/rules/03-git-commit.md`（本地提交常态，推送需明确指令）

## 关键文件索引
| 文件 | 作用 |
|------|------|
| `docs/架构/多agent项目-架构目录-v1.md` | 架构蓝图（决策记录 §6 / 前置清单 §7） |
| `docs/学习/harness 学习.md` | 原始学习问题清单 |
| `docs/学习/harness 学习-梳理.md` | 问题梳理与回答（29 问 → 8 主题） |
| `docker-compose.yml` | 环境编排（redis + opensandbox） |
| `backend/src/core/config.py` | 配置中心（双 .env 驱动） |
| `backend/src/core/paths.py` | 路径自适应 |

## 多 Agent 专项纪律
- 子 Agent 只回结构化结论（schema 校验），防污染主上下文
- 并行任务设上限（Send API + 沙箱并发限额）
- trace 贯穿：请求追踪 ID + LangSmith trace group
- 长任务：write_todos 原文随任务下发，压缩绝不做 todo 摘要


<!-- CAT-CAFE-GOVERNANCE-START -->
> Pack version: 1.4.1 | Provider: codex

## Clowder AI Governance Rules (Auto-managed)

### Hard Constraints (immutable)
- **Clowder AI runtime ports**: frontend 3003 and API 3004 are reserved by Clowder AI. Avoid using these ports for this project's dev servers.
- **Redis port 6399** is Clowder AI's production Redis. Never connect to it from external projects. Use 6398 for dev/test.
- **No self-review**: The same individual cannot review their own code. Cross-family review preferred.
- **Identity is constant**: Never impersonate another cat. Identity is a hard constraint.

### Collaboration Standards
- A2A handoff uses five-tuple: What / Why / Tradeoff / Open Questions / Next Action
- Vision Guardian: Read original requirements before starting. AC completion ≠ feature complete.
- Review flow: quality-gate → request-review → receive-review → merge-gate
- Skills are available via symlinked cat-cafe-skills/ — load the relevant skill before each workflow step
- Shared rules: See cat-cafe-skills/refs/shared-rules.md for full collaboration contract

### Quality Discipline (overrides "try simplest approach first")
- **Bug: find root cause before fixing**. No guess-and-patch. Steps: reproduce → logs → call chain → confirm root cause → fix
- **Uncertain direction: stop → search → ask → confirm → then act**. Never "just try it first"
- **"Done" requires evidence** (tests pass / screenshot / logs). Bug fix = red test first, then green

### Knowledge Engineering
- Documents use YAML frontmatter (feature_ids, topics, doc_kind, created)
- Three-layer info architecture: CLAUDE.md (≤100 lines) → Skills (on-demand) → refs/
- Backlog: BACKLOG.md (hot) → Feature files (warm) → raw docs (cold)
- Feature lifecycle: kickoff → discussion → implementation → review → completion
- SOP: See docs/SOP.md for the 6-step workflow
<!-- CAT-CAFE-GOVERNANCE-END -->
