# Git 提交规范

> 2026-08-02 审核通过（co-creator 拍板），落盘为工程规则。
> 适用范围：multi_agent 项目全部 git 提交（含 AI 代提交）。

## 1. 提交信息格式

```
<type>: <中文摘要，动词开头，≤50 字>

- 要点 1：具体做了什么
- 要点 2：涉及哪些文件/模块
...

Why: 为什么做这件事（背景 / 取舍 / 关联需求）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

**示例**：

```
docs: 架构目录 v2.3 拍板：Docker 编排落地 + 资源限额

- docker-compose.yml 新建（redis + opensandbox 服务，backend 占位）
- 资源限额适配 2核4g：redis 256m / sandbox 512m / backend 1g
- .env 补 SANDBOX_PORT / REDIS_PASSWORD

Why: co-creator 拍板环境容器化，同一套 compose 双环境切换。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

## 2. Type 分类表

| type | 用途 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat: 增加 SSE 流式接口` |
| `fix` | 修 bug | `fix: 修复 Redis 6399 误连生产` |
| `docs` | 文档 | `docs: 前端方案 v2 拍板回填` |
| `test` | 测试 | `test: 补 SSE 事件协议单测` |
| `refactor` | 重构（行为不变） | `refactor: 拆 sandbox 适配层` |
| `perf` | 性能优化 | `perf: 记忆检索改增量计算` |
| `chore` | 杂项（依赖/配置/构建） | `chore: 升级 langchain 依赖` |
| `ci` | CI/部署配置 | `ci: 加 GitHub Actions 部署` |

## 3. 摘要与正文规则

| 规则 | 要求 |
|------|------|
| 语言 | 中文为主，术语可英文（SSE / Redis） |
| 摘要 | 动词开头（增加/修复/更新/重构/删除），≤50 字，说**做了什么**，不说怎么做 |
| 正文要点 | 列关键改动，具体到文件/模块；body 必须写 `Why:` 段 |
| 粒度 | **一个提交一件事**；≤1 commit 可回滚；文档与代码分开提交 |
| 干净 | 禁止夹带无关修改（提交代码时混入 .env 改动 = 事故） |

## 4. 提交前 Checklist

- [ ] `git status` 无意外文件（密钥/日志/临时文件）
- [ ] 密钥扫描：`git diff --cached` 里无 api_key/token/密码字样
- [ ] 代码改动 → `pytest` 全绿；文档改动 → 版本变更记录已更新
- [ ] 大改/跨模块 → 先给计划等确认；普通改动 → 提交后汇报
- [ ] 提交后 `git log --oneline -3` 复核信息无误

## 5. 推送策略

| 场景 | 动作 |
|------|------|
| 本地提交 | 常态，直接做 |
| 推送远程 | **需明确指令**（云上部署需推送时再推） |
| force push | 禁止，除非明确指令（不可回滚） |

## 6. 红线（禁止入库）

- 🔴 密钥类：`.env.dev` / `.env.prod` / API Key / token（已 gitignore，双重检查）
- 🔴 运行时产物：`logs/`、`data/`、`.venv`、`__pycache__`、`dist/`
- 🔴 临时文件：`*.tmp`、OCR 中间产物
- 🟡 大二进制：图片附件仅 `docs/图片和附件/`（>5MB 用外链/LFS，暂不涉及）

## 7. 分支模型（单人简化版）

```
main      ← 稳定版（上云部署后启用）
develop   ← 日常开发（当前在此分支，直接提交）
feature/xxx ← 大功能可选开分支，完成后 merge 回 develop
```
