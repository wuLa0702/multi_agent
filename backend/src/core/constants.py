"""跨文件共用常量（集中维护，禁止散落硬编码/多处重复定义）。

归属判定（结构优化规范 §4.1）：
- 跨文件共用 → 本模块（"用两次就抽"）
- 单文件私有 → 留在文件头部模块级常量
- 跨环境差异（端口/路径根/超时配置）→ core/config.py（env 配置）
- 文件名/路径 → core/paths.py（路径唯一维护点）

分组说明：
- PAGINATION_*：分页契约（对齐 参考-后端接口 §3.4：limit 默认 50，上限 200）
- TRUNCATE_*：日志/事件字段截断（main_agent _truncate 默认 300，ToolAudit 同口径）
"""

from __future__ import annotations

# ── 分页（接口契约 §3.4）──
PAGINATION_LIMIT_MAX = 200  # 历史消息拉取上限（chat.py / 参考-后端接口 §3.4）
PAGINATION_LIMIT_DEFAULT = 50  # 分页默认每页条数

# ── 截断（防上下文膨胀 + 密钥纪律）──
TRUNCATE_LIMIT = 300  # 事件字段/审计截断长度（main_agent _truncate、ToolAudit 同口径）
