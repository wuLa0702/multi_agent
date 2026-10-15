# 测试规范

## 结构
```
backend/tests/
├── conftest.py          # 共享 Fixture（mock LLM / tmp_path / PG 独立 schema）
├── fixtures/            # 共享测试数据
├── test_agent/          # Agent 核心：Graph/State/子 Agent
├── test_api/            # API：SSE 流式 / 事件协议
├── test_core/           # 底座：重试 / 安全 / 常量
├── test_mcp/            # MCP 网关
├── test_sandbox/        # 沙箱适配层
└── test_skills/         # Skill 市场与安装
```

## 原则
- pytest，禁 unittest；文件名/函数名 `test_` 开头；一个测试一个行为
- LLM 全部 mock，不实际调 API
- 文件系统用 `tmp_path`；数据库用 compose PG + **每用例独立 schema**（`:memory:` 已废弃，PG 无内存模式）——**按需请求** `pg_schema` / `reset_agent_singleton`（**非 autouse**：纯函数测试不拉 PG，避免全量耗时翻数倍）
- 每个测试文件覆盖：正常 / 边界（空、大、特殊字符）/ 错误（越权、不存在）/ LLM 异常（超时、空回复）

## 改动的测试范围（2026-10-15 co-creator 拍板）

| 场景 | 跑什么 |
|------|--------|
| **日常改动**（常态） | **只跑与改动相关的测试文件**（受影响模块 + 其直接上游）——不必每次全量 |
| **阶段性收尾 / 合并回主分支前** | **全量** `pytest backend/tests`，必须全绿 |

**Why**：大改期项目频繁变动，每次全量（约 60s）收益低且易被无关红分散注意力；
按改动面选测试文件效率更高、聚焦更准。**代价**：跨模块副作用可能漏——故收尾那次全量不可省。

> ⚠️ 与旧文「提交前必须全绿（全量）」的差异：旧文按"每次提交"要求全量，
> 现改为"日常相关 + 收尾全量"。**未跑全量时，汇报里要写清跑的是哪几个文件**
> （不得声称"测试全绿"）。

## 多 Agent 专项测试
- 子 Agent 结构化输出 schema 校验（解析失败用例）
- 并行子任务（Send API）并发上限测试
- 压缩 summarizer：**绝不对任务清单做摘要**的断言
- 断点 resume：interrupt 后恢复状态一致性

## 运行
```bash
pytest backend/tests -v                       # 全量：阶段性收尾 / 合并前
pytest backend/tests/test_core/test_retry.py  # 相关：日常改动（按改动面选文件）
```
