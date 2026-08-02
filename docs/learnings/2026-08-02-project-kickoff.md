# 2026-08-02 项目启动：环境策略 / Docker 编排 / 文档体系

## 背景
从零搭建多 Agent 学习项目（multi_agent）。蓝图来自 `docs/多agent项目-架构目录-v1.md`（v2.2 → v2.3）。

## 关键决策（Why）
1. **OpenSandbox 不本地部署**（v2.2）：已有云环境 → 本地/生产都连云端沙箱。
   - 原因：沙箱是重资源（容器+镜像+预热池），云端跑省本地资源；本地只跑应用代码便于排查
2. **配置驱动切换**：同一套 docker-compose，`.env.dev` / `.env.prod` 双配置，APP_ENV 决定加载哪个。
   - 坑：最初写成 `env_file=(".env.dev", ".env.prod", ".env")` **叠加读取** → prod 覆盖 dev 值 → 改为动态单选
3. **路径自适应**（`core/paths.py`）：dev 本地 `data/`、prod 云端 `/data`。
   - 坑：Windows 上 `Path("/data").is_dir()` 会命中盘符根目录 → 误判云端 → 修复：Windows 直接返回 False

## 踩坑记录
| 坑 | 根因 | 修复 |
|----|------|------|
| config 叠加读 .env 导致值被覆盖 | pydantic-settings env_file 元组按序加载后覆盖前 | APP_ENV 环境变量动态选单个文件 |
| Windows 误判云端环境 | /data 探测在 Windows 解析为盘符根目录 | sys.platform == "win32" 直接短路 |
| OpenSandbox SDK 包名写错 | 直觉写 opensandbox-sdk | WebSearch 查证 → `opensandbox`（server 是 `opensandbox-server`） |

## 文档体系（本次确立）
- `CLAUDE.md` — 项目说明书（agent 第一入口）
- `.claude/rules/` — 工程化规则（安全/风格/API/测试/手写纪律）
- `AGENTS.md` — Agent 全局操作手册（deepagents 体系）
- `docs/learnings/` — 经验沉淀（本文件）
- `docs/` — 学习文档（harness 学习原始问题 + 梳理 + 架构蓝图）

## 安全纪律（确立）
密钥（LangSmith / OpenSandbox）只进 .env，gitignore 锁定，聊天不回显完整值。
