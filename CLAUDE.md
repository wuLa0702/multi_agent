# multi-agent 项目说明书

> 多 Agent 学习项目：deepagents 主线 + LangGraph 演进预留；OpenSandbox 云端沙箱；FastAPI 流式后端。
> 设计决策与拍板记录：见 `docs/架构/多agent项目-架构目录.md`（v2.3，权威蓝图）。

## 项目定位
- **学习目标**：手写核心逻辑 + 多 Agent 工程化落地（面试导向）
- **核心拍板**（详见架构文档 §6）：
  - Agent 层：deepagents 搭建主体，`agent/graph/` 预留 LangGraph 手写主图（演进平行智能体）
  - 沙箱：OpenSandbox（阿里开源），**本地开发连本地 Docker，生产连云端**
  - 前端：React 19 + shadcn/ui（复用 wiki-ui-v2）
  - 部署：CI runner 远程 + 路径自适应
  - 环境：`.env.dev / .env.prod` 双配置，同一套 docker-compose 切换

## 技术栈
Python 3.11+ · FastAPI (ASGI/SSE) · LangGraph + langchain-deepagents · FastMCP · OpenSandbox SDK · Redis + SQLite · LangSmith

## 目录结构（后端）
> 完整项目结构（前后端唯一真相源）见 `docs/架构/多agent项目-架构目录.md` §2 目录树。
> 本文件不再内嵌结构树——结构变更只改架构文档一处。
依赖单向：`api → agent → {mcp, sandbox, memory, db}`，禁止反向。

## 核心约束
1. **密钥只进 `.env.dev` / `.env.prod`**（已 gitignore），永不入库、不进聊天
2. 环境切换用 APP_ENV：`dev`（读 .env.dev）/ `prod`（读 .env.prod），**禁止叠加读取多个 .env**
3. 路径自适应：dev 用项目 `data/`、`logs/`；prod 用云端 `/data`、`/logs`（`core/paths.py`）
4. 沙箱/Redis：本地开发连本地 Docker（`scripts/dev.sh` 一键起 compose 资源，redis 6398 / opensandbox 8080），生产连云端
5. 所有工具调用做路径前缀校验（防越权）；LLM 调用必须 timeout + retry

## 开发命令
```bash
# 依赖安装
pip install -r requirements.txt        # 或 pip install -e .

# 本地起依赖服务（redis + opensandbox，连云端）
docker compose --env-file .env.dev up -d redis opensandbox

# 启动后端（dev）
uvicorn src.api.main:app --reload --port 8010    # backend/ 下执行

# 一键启动全部（Docker 资源 + 前端 5176 + 后端 8010）
bash scripts/dev.sh                            # Git Bash
scripts\dev.bat                                # Windows cmd 直跑（等价包装）
scripts\dev-restart.bat                        # 后端快重启（改后端代码时）

# 测试
pytest backend/tests
```

## 开发纪律
- 核心逻辑（Agent 编排/Graph/State）手写，样板代码 AI 提速（见 `.claude/rules/02-hands-on-training.md`）
- Bug 先定位根因再修；先红后绿；提交前先给计划等确认
- 踩坑记入 `docs/踩坑/`；修改架构决策先更新架构文档版本表

## 文档规范（docs/ 下所有文档强制）
- **中文文件名**（如 `docs/归档/2026-08-02-方案-后端基础架构-v1.md`），附件图片/OCR 除外
- 每个文档顶部必须含规范头：📋 规范引用 + 📌 更新时间 + 📝 版本变更记录（永久保存、写细节）+ 目录
- 格式规则唯一载体：`docs/规则/文档规范.md`（改规则只改它，不在各文档里重复抄规则）
- 每次更新维护固定动作：更新时间 → 版本变更记录追加（具体到二级标题）→ 文件名版本号（大改升级）
- 详见 `docs/规则/文档规范.md`


<!-- CAT-CAFE-GOVERNANCE-START -->
> Pack version: 1.4.1 | Provider: claude

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
- SOP: See docs/规则/SOP.md for the 6-step workflow
<!-- CAT-CAFE-GOVERNANCE-END -->
