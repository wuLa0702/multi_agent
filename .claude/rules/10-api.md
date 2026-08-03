# API 开发规范

## 路由规范
- 业务路由使用 `/v1/` 前缀；健康检查/根路径不前缀
- 路由名 snake_case

```python
@app.post("/v1/chat/stream")
async def chat_stream(req: ChatRequest): ...
```

## 请求/响应模型
- 全部 Pydantic v2 BaseModel（`src/schemas/`，禁裸 dict；2026-08-03 随架构目录 v2.6 由 models/ 更名）
- POST 用请求体，GET 用查询参数
- 响应含 `status` 字段；错误统一 `ErrorResponse`（error/detail/code）

## SSE 事件协议（多 Agent 关键）
- 事件类型固定（与前端对齐，v3 定稿）：`token` / `tool_call` / `approve` / `summarize` / `subagent` / `done` / `error`
- 事件 payload 用 Pydantic 模型序列化，前后端共享 types
- resume 断点：Checkpointer 持久化，中断可恢复

## HTTP 状态码
- 200 成功 / 400 参数错误 / 403 权限拒绝 / 404 不存在 / 500 内部错误

## CORS
- dev 允许本地前端；prod 白名单（.env CORS_ORIGINS）
