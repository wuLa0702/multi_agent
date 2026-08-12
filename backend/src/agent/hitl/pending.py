"""待决审批存储（P0 HITL 设计 §5.3/§5.4）：checkpoint_id → 中断 + 已收决策。

- **Redis 存储（v1.1 评审拍板，替代 v1 内存 dict）**：get_redis()（redis.asyncio，
  decode_responses=True，core/redis.py）；多进程/重启不丢
- key 设计：`hitl:pending:{checkpoint_id}` = JSON{session_id, action_requests,
  review_configs}（SET EX 600）；`hitl:pending:{checkpoint_id}:decisions` = LIST
  按 action index 占位写入（v1.2：list 保序 + call_id 匹配配合——分 key 简化 TTL，
  保持现状不合并）
- 中断时登记，approve 端点按 call_id 逐条写入决策，决策数 == action 数 →
  accepted=True；resume 消费即删（getdel 原子，防并发双读）
- 修订计数（v1.2）：`hitl:revise:{session_id}` 会话级 INCR——publish_report
  reject 时累加，resume 判断是否达配置上限
- Redis 不可达 → 异常上抛（approve 路由转 503；测试 mock get_redis）
- 过期 → 404 友好提示（前端提示重开，同 RESUME_NOT_FOUND 处理）

## Redis 存储 JSON 示例

**主 key** `hitl:pending:{checkpoint_id}`（中断上下文，SET EX 600）：
```json
{
  "session_id": "sess-42",
  "action_requests": [
    {"name": "run_code_in_sandbox", "args": {"code": "print(1)"}, "call_id": "call-a"},
    {"name": "ask_human", "args": {"message": "调研范围是？"}, "call_id": "call-b"}
  ],
  "review_configs": [
    {"action_name": "run_code_in_sandbox", "allowed_decisions": ["approve", "edit", "reject"]},
    {"action_name": "ask_human", "allowed_decisions": ["respond"]}
  ]
}
```

**decisions LIST** `hitl:pending:{checkpoint_id}:decisions`（按 action index 占位，RPUSH/LSET）：
```json
// index 0 = call-a（决策数 == action 数 → accepted=true）
[
  {"type": "reject", "message": "别跑这段代码"},
  {"type": "respond", "message": "2026 年市场规模 + 头部玩家格局"}
]
// 四种决策形状：
// {"type": "approve"}
// {"type": "reject", "message": "拒绝理由"}
// {"type": "edit", "edited_action": {"name": "run_code_in_sandbox", "args": {"code": "print(2)"}}}
// {"type": "respond", "message": "人类回答（仅 ask_human）"}
```

**修订计数 key** `hitl:revise:{session_id}`（publish_report 被拒累加，INCR EX 3600）：
```json
2   // 超过 settings.publish_review_max_revisions → resume 注入停止提示
```
"""

from __future__ import annotations

import json

from src.core.redis import get_redis

_PENDING_TTL_SECONDS = 600          # 10 分钟（人类决策窗口）
_PENDING_PREFIX = "hitl:pending:"   # key 前缀（防与其他业务键冲突）
_REVISE_PREFIX = "hitl:revise:"     # 修订计数前缀（会话级）
_REVISE_TTL_SECONDS = 3600          # 修订窗口 1h（覆盖单个研究任务）


def _key(checkpoint_id: str) -> str:
    """主 key（中断上下文 JSON）。"""
    return f"{_PENDING_PREFIX}{checkpoint_id}"


def _decisions_key(checkpoint_id: str) -> str:
    """决策 list key（按 action index 占位写入，保序）。"""
    return f"{_PENDING_PREFIX}{checkpoint_id}:decisions"


def _revise_key(session_id: str) -> str:
    """会话修订计数 key。"""
    return f"{_REVISE_PREFIX}{session_id}"


async def register_interrupt(checkpoint_id: str, hitl_request: dict, session_id: str) -> None:
    """中断发生时登记（流内检测到中断后调用，设计 §5.5）。

    Args:
        checkpoint_id: 中断点 checkpoint_id（GraphInterruptEvent 提供）
        hitl_request: {"action_requests": [...], "review_configs": [...]}
        session_id: 会话 ID（存入主 key——approve 端点据此定位会话级修订计数）

    Raises:
        ValueError: action_requests 为空（v1.2 评审修正：空中断无审批对象，
            不登记——避免 add_decision 空 action 误判 accepted=True）
        RedisError: Redis 不可达（调用方转 503）
    """
    actions = hitl_request.get("action_requests", [])
    if not actions:
        raise ValueError("action_requests 为空，拒绝登记审批中断")
    body = {
        "session_id": session_id,
        "action_requests": actions,
        "review_configs": hitl_request.get("review_configs", []),
    }
    redis = get_redis()
    await redis.set(_key(checkpoint_id), json.dumps(body), ex=_PENDING_TTL_SECONDS)
    await redis.delete(_decisions_key(checkpoint_id))  # 幂等：重复中断清空旧决策


async def add_decision(checkpoint_id: str, call_id: str, decision: dict) -> bool:
    """approve 端点追加一条决策（v1.2 评审修正：按 call_id 定位 action index）。

    decisions 以 LIST 存 JSON，按 action_requests 顺序占位写入——多 action
    顺序强保证，不依赖前端提交顺序（前端逐卡提交时乱序也正确归位）。

    Args:
        checkpoint_id: 中断点 checkpoint_id
        call_id: 工具调用 id（approve 事件回传值，定位 action index）
        decision: {"type": action, "message": note, "edited_action": ...}

    Returns:
        True=决策数已达 action 数（前端可 resume）；False=还需继续审批

    Raises:
        KeyError: 无待决审批（checkpoint_id 未登记/已过期）
        ValueError: call_id 未在 action_requests 中匹配
    """
    redis = get_redis()
    body_raw = await redis.get(_key(checkpoint_id))
    if body_raw is None:
        raise KeyError(checkpoint_id)
    body = json.loads(body_raw)
    actions = body["action_requests"]
    index = _find_action_index(actions, call_id)
    if index is None:
        raise ValueError(f"call_id={call_id} 未匹配到待审 action")
    await _set_decision_at(redis, checkpoint_id, index, decision)
    # accepted 判定：数"实际已填决策"（排除 null 占位）——占位补全不能算决策数
    decision_raws = await redis.lrange(_decisions_key(checkpoint_id), 0, -1)
    filled = sum(1 for d in decision_raws if d != "null")
    return filled >= len(actions)


def _find_action_index(actions: list[dict], call_id: str) -> int | None:
    """在 action_requests 中定位 index（兼容真实 HITL action 无 call_id 的情况）。

    实测（2026-08-12 项4 真实链路）：官方 HITL action_request 只含
    name/args/description，**无 call_id**；approve 事件侧 fallback 生成
    `action-{seq}`。匹配优先级：
      1. action 显式 call_id == 目标（若有）
      2. call_id 形如 `action-{seq}` → 按序号取
      3. 单 action → 直接 index 0（name 兜底，单 action 场景正确归位）

    Args:
        actions: action_requests（action_request 含 call_id/name；真实场景无 call_id）
        call_id: approve 事件回传值（action 显式 id 或 fallback `action-{seq}`）

    Returns:
        匹配的 index；无匹配 → None
    """
    # 1. 显式 call_id 匹配（若 action 携带）
    for i, action in enumerate(actions):
        if action.get("call_id") == call_id:
            return i
    # 2. fallback `action-{seq}` → 序号匹配（approve 事件生成的口径）
    if call_id.startswith("action-"):
        seq = call_id[len("action-"):]
        if seq.isdigit():
            idx = int(seq)
            if 0 <= idx < len(actions):
                return idx
    # 3. 单 action 兜底（真实 HITL 场景：action 无 call_id，name 即唯一）
    if len(actions) == 1:
        return 0
    return None


async def _set_decision_at(redis, checkpoint_id: str, index: int, decision: dict) -> None:
    """把决策写入 decisions LIST 的指定 index（保序占位，幂等）。

    Args:
        redis: Redis 客户端
        checkpoint_id: 中断点 checkpoint_id
        index: 目标 index（0-based）
        decision: 决策 dict（JSON 序列化）
    """
    key = _decisions_key(checkpoint_id)
    # 保证 LIST 长度 >= index+1（不足补 None 占位，保持 index 语义）
    current = await redis.llen(key)
    for _ in range(current, index + 1):
        await redis.rpush(key, "null")
    await redis.lset(key, index, json.dumps(decision))
    await redis.expire(key, _PENDING_TTL_SECONDS)


async def consume(checkpoint_id: str) -> dict | None:
    """resume 时消费待决审批（一次性，读后即删）。

    v1.2 评审修正：主 key 用 `redis.getdel()` 原子消费（get+del 一步，Redis
    6.2+）——防并发 resume 双读到同一决策；decisions LIST 读后删，若 getdel
    后进程中断残留 LIST，靠 TTL 过期兜底（主 key 已删不会重复消费）。

    Args:
        checkpoint_id: resume_run_id（approve 事件透传值）

    Returns:
        {"decisions": [...]}（Command(resume) 输入形态）；无待决 → None
    """
    redis = get_redis()
    body_raw = await redis.getdel(_key(checkpoint_id))  # 原子 get + del
    if body_raw is None:
        return None
    decision_raws = await redis.lrange(_decisions_key(checkpoint_id), 0, -1)
    await redis.delete(_decisions_key(checkpoint_id))  # 消费即删（残留靠 TTL）
    decisions = [json.loads(d) for d in decision_raws if d != "null"]
    return {"decisions": decisions}


async def get_action_name(checkpoint_id: str) -> str | None:
    """待决审批对应的工具名（edit 决策定位用）。

    Args:
        checkpoint_id: 中断点 checkpoint_id

    Returns:
        首个 action 的工具名；无待决 → None
    """
    redis = get_redis()
    body_raw = await redis.get(_key(checkpoint_id))
    if body_raw is None:
        return None
    body = json.loads(body_raw)
    actions = body.get("action_requests", [])
    return actions[0].get("name") if actions else None


async def get_session_id(checkpoint_id: str) -> str | None:
    """待决审批对应的会话 ID（approve 端点定位修订计数用，v1.2）。

    Args:
        checkpoint_id: 中断点 checkpoint_id

    Returns:
        会话 ID；无待决 → None
    """
    redis = get_redis()
    body_raw = await redis.get(_key(checkpoint_id))
    if body_raw is None:
        return None
    body = json.loads(body_raw)
    return body.get("session_id")


async def incr_revision(session_id: str) -> int:
    """会话级发布修订计数 +1（approve 端点收到 publish_report reject 时调用，v1.2）。

    Args:
        session_id: 会话 ID

    Returns:
        自增后的计数
    """
    redis = get_redis()
    key = _revise_key(session_id)
    count = await redis.incr(key)
    await redis.expire(key, _REVISE_TTL_SECONDS)
    return count


async def get_revision_count(session_id: str) -> int:
    """读会话修订计数（resume 时判断是否达上限，v1.2）。

    Args:
        session_id: 会话 ID

    Returns:
        当前计数（无记录 → 0）
    """
    redis = get_redis()
    raw = await redis.get(_revise_key(session_id))
    return int(raw) if raw else 0
