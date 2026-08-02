# multi-agent 项目说明书

> 多 Agent 学习项目：deepagents 主线 + LangGraph 演进预留；OpenSandbox 云端沙箱；FastAPI 流式后端。
> 设计决策与拍板记录：见 `docs/架构/多agent项目-架构目录-v1.md`（v2.3，权威蓝图）。

## 项目定位
- **学习目标**：手写核心逻辑 + 多 Agent 工程化落地（面试导向）
- **核心拍板**（详见架构文档 §6）：
  - Agent 层：deepagents 搭建主体，`agent/graph/` 预留 LangGraph 手写主图（演进平行智能体）
  - 沙箱：OpenSandbox（阿里开源），**不本地部署，连云端**
  - 前端：React 19 + shadcn/ui（复用 wiki-ui-v2）
  - 部署：CI runner 远程 + 路径自适应
  - 环境：`.env.dev / .env.prod` 双配置，同一套 docker-compose 切换

## 技术栈
Python 3.11+ · FastAPI (ASGI/SSE) · LangGraph + langchain-deepagents · FastMCP · OpenSandbox SDK · Redis + SQLite · LangSmith

## 目录结构（后端）
```
backend/src/
├── api/          # Web 层：FastAPI 入口、SSE 流式、鉴权、中间件
├── agent/        # Agent 层 ★核心：deepagents 主 Agent + 子 Agent YAML + graph 演进预留
│   ├── subagents/    # 声明式子 Agent（YAML）
│   ├── memory/       # Redis 短期 + SQLite 长期 + 用户画像
│   ├── middlewares/  # 中间件栈（日志/重试/PII）
│   └── skills/       # Skill 体系（SKILL.md + 渐进式加载）
├── mcp/          # MCP 网关层：FastMCP server + 工具注册表
├── sandbox/      # 沙箱层：adapter + opensandbox 实现（连云端）
├── core/         # 基建：config / paths / logging / errors / security
├── llm/          # LLM 适配层：deepseek/豆包/智谱 多 provider
├── db/           # 数据访问层（参数化 SQL）
└── models/       # 全项目 Pydantic 实体（禁裸 dict）
```
依赖单向：`api → agent → {mcp, sandbox, memory, db}`，禁止反向。

## 核心约束
1. **密钥只进 `.env.dev` / `.env.prod`**（已 gitignore），永不入库、不进聊天
2. 环境切换用 APP_ENV：`dev`（读 .env.dev）/ `prod`（读 .env.prod），**禁止叠加读取多个 .env**
3. 路径自适应：dev 用项目 `data/`、`logs/`；prod 用云端 `/data`、`/logs`（`core/paths.py`）
4. 沙箱/Redis 连云端（OpenSandbox server + Redis，见 docker-compose.yml）
5. 所有工具调用做路径前缀校验（防越权）；LLM 调用必须 timeout + retry

## 开发命令
```bash
# 依赖安装
pip install -r requirements.txt        # 或 pip install -e .

# 本地起依赖服务（redis + opensandbox，连云端）
docker compose --env-file .env.dev up -d redis opensandbox

# 启动后端（dev）
uvicorn src.api.main:app --reload --port 8000    # backend/ 下执行

# 测试
pytest backend/tests
```

## 开发纪律
- 核心逻辑（Agent 编排/Graph/State）手写，样板代码 AI 提速（见 `.claude/rules/02-hands-on-training.md`）
- Bug 先定位根因再修；先红后绿；提交前先给计划等确认
- 踩坑记入 `docs/learnings/`；修改架构决策先更新架构文档版本表

## 文档规范（docs/ 下所有文档强制）
- **中文文件名**（如 `docs/方案/方案-后端基础架构-v1.md`），附件图片/OCR 除外
- 每个文档顶部必须含规范头：📋 规范引用 + 📌 更新时间 + 📝 版本变更记录（永久保存、写细节）+ 目录
- 格式规则唯一载体：`docs/文档规范.md`（改规则只改它，不在各文档里重复抄规则）
- 每次更新维护固定动作：更新时间 → 版本变更记录追加（具体到二级标题）→ 文件名版本号（大改升级）
- 详见 `docs/文档规范.md`
