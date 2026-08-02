# 测试规范

## 结构
```
backend/tests/
├── conftest.py          # 共享 Fixture（mock LLM / tmp_path / :memory:）
├── test_agent/          # Agent 核心：Graph/State/子 Agent
├── test_api/            # API：SSE 流式 / 事件协议
├── test_mcp/            # MCP 网关
└── test_sandbox/        # 沙箱适配层
```

## 原则
- pytest，禁 unittest；文件名/函数名 `test_` 开头；一个测试一个行为
- LLM 全部 mock，不实际调 API
- 文件系统用 `tmp_path`，数据库用 `:memory:`
- 每个测试文件覆盖：正常 / 边界（空、大、特殊字符）/ 错误（越权、不存在）/ LLM 异常（超时、空回复）

## 多 Agent 专项测试
- 子 Agent 结构化输出 schema 校验（解析失败用例）
- 并行子任务（Send API）并发上限测试
- 压缩 summarizer：**绝不对任务清单做摘要**的断言
- 断点 resume：interrupt 后恢复状态一致性

## 运行
```bash
pytest backend/tests -v
# 提交前必须全绿
```
