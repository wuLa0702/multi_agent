# multi-agent 🐱

多 Agent 系统学习项目：**deepagents 主线 + LangGraph 演进预留 + OpenSandbox 云端沙箱 + FastAPI 流式后端**。

> 面试导向 · 手写核心逻辑 · 从 LLM Wiki 单体 Agent 升级到多 Agent 工程化

## 项目地图

| 入口 | 说明 |
|------|------|
| 📐 [架构蓝图](docs/架构/多agent项目-架构目录-v1.md) | 权威设计文档（决策记录/目录树/前置清单） |
| 📖 [学习问题清单](docs/学习/harness 学习.md) | 最初的口述问题 |
| 📝 [问题梳理与回答](docs/学习/harness 学习-梳理.md) | 29 问 → 8 主题，全部有答案 |
| 🤖 [Agent 操作手册](AGENTS.md) | 给 AI 开发者的行动指南 |
| ⚙️ [工程规则](.claude/rules/) | 安全/风格/API/测试/手写纪律 |
| 🪤 [踩坑经验](docs/learnings/) | 经验沉淀（先查再动手） |

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境（复制模板，填入密钥）
cp .env.example .env.dev     # 本地开发（APP_ENV=dev）

# 3. 起依赖服务（Redis + OpenSandbox 云端）
docker compose --env-file .env.dev up -d redis opensandbox

# 4. 启动后端
cd backend && uvicorn src.api.main:app --reload --port 8000
```

## 当前状态

- ✅ 依赖清单 + 环境配置骨架（config/paths 双环境）
- ✅ docker-compose 编排（redis + opensandbox + backend 占位）
- ✅ 文档体系（CLAUDE.md / rules / AGENTS.md / learnings）
- ⏳ v3 接口签名细化（State / SSE 事件表 / MCP 注册 / 记忆接口 / 子 Agent YAML）

## 技术栈

Python 3.11+ · FastAPI (ASGI/SSE) · LangGraph · langchain-deepagents · FastMCP · OpenSandbox · Redis · SQLite · LangSmith
