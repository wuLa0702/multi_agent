"""Token 用量统计 + 成本核算中间件：图执行完成自动计算并落库。

2026-08-04 评审改版（替代 CallbackHandler 方案）：
- 嵌入 DeepAgent 中间件栈（create_deep_agent middleware 列表），
  `aafter_agent` 钩子在每次图执行（含 ReAct 多轮）结束后触发
- state["messages"] 是**当前会话全量消息**（含历史）——context_used 算"当前占用"
  （前端进度条语义）；成本核算用**本轮增量**（执行后 − 执行前差量近似）
- 存库（sessions.context_used）+ 成本流水（token_cost_ledger）+ 告警（cost_alerts）
- token 估算：chars/4（评审拍板近似，后续可换真实 tokenizer）
- 2026-08-11 成本控制 §4.1/§5.1：单价×增量 token 落流水，超阈值软告警落库

⚠️ 必须实现 async 版（aafter_agent）：项目走 astream 异步上下文，
sync 钩子（after_agent）在异步上下文不会触发（与 _configurable_model 同款教训）。
"""

from __future__ import annotations

import logging
import time

from langchain.agents.middleware import AgentMiddleware

logger = logging.getLogger(__name__)

# 上下文上限（评审拍板常量；后续可接 models 表 context_window 字段）
DEFAULT_CONTEXT_WINDOW = 128_000

# chars/4 近似估算（中英文混合约 4 字符 ≈ 1 token）
_CHARS_PER_TOKEN = 4.0


def _now_utc_str() -> str:
    """当前 UTC 时间字符串（ISO 格式，成本流水/告警 created_at）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


class TokenUsageMiddleware(AgentMiddleware):
    """上下文用量 + 成本核算中间件（编译时单例，session 从 runtime.context 取）。

    Attributes:
        context_window: 上下文上限（默认 128k）
    """

    def __init__(self, context_window: int = DEFAULT_CONTEXT_WINDOW) -> None:
        super().__init__()
        self.context_window = context_window

    async def aafter_agent(self, state, runtime) -> None:
        """图执行结束钩子：更新 context_used + 成本核算落流水 + 告警检查。

        成本口径（设计 §4.1）：本轮增量 = 执行后 used − 执行前（DB context_used 旧值）
        差量近似；P2 接 langchain usage_metadata（真实 token，若国产模型返回）。

        Args:
            state: AgentState——messages 为当前会话全量消息（含历史）
            runtime: Runtime——context 携带请求级 ChatContext（含 session_id/model_id）

        Returns:
            None（直接落库，不改 state）
        """
        try:
            messages = state.get("messages") or []
            used = int(sum(len(getattr(m, "content", "") or "") for m in messages) / _CHARS_PER_TOKEN)

            context = getattr(runtime, "context", None)
            session_id = getattr(context, "session_id", None) if context is not None else None
            if not session_id:
                logger.debug("TokenUsageMiddleware: 无 session_id，跳过")
                return

            await _save_context_used(session_id, used, self.context_window)
            # 成本核算：本轮增量 → 单价 → 流水 + 告警（旁路，失败不影响）
            model_id = getattr(context, "model_id", None) if context is not None else None
            await _log_cost_for_round(session_id, model_id, used)
        except Exception:  # noqa: BLE001 —— 统计是旁路能力，失败不阻断对话
            logger.exception("TokenUsageMiddleware: 用量/成本落库失败（不影响对话）")


async def _save_context_used(session_id: str, used: int, total: int) -> None:
    """把用量写入 sessions 表（连接自开自关，避开请求连接生命周期）。"""
    from src.core import db as core_db

    conn = await core_db.get_connection()
    try:
        await conn.execute(
            "UPDATE sessions SET context_used = ? WHERE id = ?",
            (min(used, total), session_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def _get_previous_used(conn, session_id: str) -> int:
    """读 sessions.context_used 旧值（本轮增量差量起点）。

    Args:
        conn: SQLite 连接
        session_id: 会话 ID

    Returns:
        上次落库的 context_used（无记录 → 0）
    """
    from src.db import session_repo

    return await session_repo.get_context_used(conn, session_id)


async def _log_cost_for_round(session_id: str, model_id: int | None, used: int) -> None:
    """本轮成本核算：增量 token × 单价 → 落流水 → 累计超阈值告警。

    底层函数，按规范豁免（通用统计封装）。

    Args:
        session_id: 会话 ID
        model_id: 模型 ID（None → 默认模型）
        used: 执行后全量 context_used
    """
    from src.core import db as core_db
    from src.core.model_registry import get_registry

    conn = await core_db.get_connection()
    try:
        prev = await _get_previous_used(conn, session_id)
        delta = max(used - prev, 0)
        if delta <= 0:
            return
        cfg = _resolve_model_config(model_id)
        if cfg is None:
            return  # 注册表未加载/无模型 → 跳过核算
        # P0 近似：增量未拆输入/输出，全记输入价（P2 接 usage_metadata 拆分）
        cost = round(delta * cfg.input_price / 1000, 6)
        from src.db import cost_repository

        await cost_repository.insert_cost_ledger(
            conn, session_id, cfg.id, delta, 0, cost, 0.0, cost
        )
        await conn.commit()
        await _check_cost_alert(conn, session_id)
    finally:
        await conn.close()


def _resolve_model_config(model_id: int | None):
    """解析模型配置（显式 model_id → 默认模型；注册表未加载返回 None）。

    底层函数，按规范豁免（通用解析封装）。

    Args:
        model_id: 模型 ID（None → 默认模型）

    Returns:
        ModelConfig 或 None（注册表未加载/无模型）
    """
    from src.core.model_registry import get_registry

    registry = get_registry()
    cfg = registry.get_model(model_id) if model_id is not None else None
    if cfg is not None:
        return cfg
    try:
        return registry.get_default_model()
    except Exception:  # noqa: BLE001 - 注册表未加载，跳过核算
        return None


async def _check_cost_alert(conn, session_id: str) -> None:
    """累计成本超阈值 → 分级告警落库（2026-08-12 成本评审 2.2 方案 A）。

    分级告警：阈值按倍数递增（5/10/20...）每级告警一次——避免"只告警一次后
    成本飙到 100 元失联"，也避免每次核算都打扰。触发级别 = 当前累计成本
    跨越的最高档位。

    底层函数，按规范豁免（通用统计封装）。

    Args:
        conn: SQLite 连接
        session_id: 会话 ID
    """
    from src.core.config import settings

    from src.db import cost_repository

    base = settings.session_cost_warn_threshold
    if base <= 0:
        return
    total_cost = await cost_repository.sum_session_cost(conn, session_id)
    if total_cost < base:
        return
    # 达到的最高档位（1×/2×/4×/8×... 倍数递增）
    level = 1
    while total_cost >= base * (2**level):
        level += 1
    threshold = base * (2 ** (level - 1))
    highest = await cost_repository.highest_alert_threshold(conn, session_id)
    if highest is not None and threshold <= highest + 1e-9:
        return  # 该档位（及以下）已告警过——分级去重
    await cost_repository.insert_cost_alert(conn, session_id, threshold, total_cost)
    await conn.commit()
