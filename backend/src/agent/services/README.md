# agent/services/ — 数据服务层

> 📌 2026-08-12 结构重构新增（结构性优化规则 §2 跨层禁令：api 禁直调 db/）。

## 职责

api → **agent/services** → db 的中转层：连接托管 + 仓储调用 + 关联联动。
api 只做编排，不碰 `src.db`、不写 SQL。

## 模块 × 服务

| 文件 | 服务函数 | 仓储依赖 | 说明 |
|------|----------|----------|------|
| `session_service.py` | create/get/list/update/delete_session、list_messages | `db/session_repo` | 会话 CRUD + 删除联动（缓存重建/工作区清理/沙箱销毁）|
| `model_service.py` | update_model_price | `db/model_repository` | 模型单价（成本核算入口）|
| `settings_service.py` | get_all_settings、upsert_settings | `db/settings_repository` | 用户可改配置 |
| `skill_service.py` | list_installed_skills、update_mcp_server_active、delete_mcp_server | `db/skill_repository` | 技能/MCP 管理（删除含关联清理）|
| `cost_service.py` | summary、list_alerts | `db/cost_repository` | 成本只读查询 |

## 依赖方向

`api/` → `agent/services/` → `db/`（唯一 SQL 出口）；`core/` 为公共底座（连接）。

## 异常场景

- 连接获取失败：向上抛（api 层统一转 500）
- 记录不存在：返回 None / False（api 层转 404，如 MODEL_NOT_FOUND / SESSION_NOT_FOUND）
- 删除联动（cleanup/sandbox）：幂等，失败不阻断删除

## 变更记录

- 2026-08-12：初建 5 服务（`155caf1`）；chat.py 函数内 db 访问记 T2b 待专项
