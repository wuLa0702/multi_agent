"""跨会话记忆读写（P1 Store，SqliteStore 持久化，2026-08-04）。

写入：对话结束后**先经 LLM 抽取**（extract_memory_fact）——判断这段对话是否有
长期记忆价值（用户事实/偏好/决策），有则把**抽取的一句话事实**写入全局记忆
（namespace=("memory","global")，跨会话共享），无则跳过。
检索：对话开始时取最近 N 条注入 SystemMessage（chat.py 调用）。

⚠️ 2026-08-04 修正（用户评审发现）：原实现把整段回复写入（仅长度过滤），
导致所有对话全文进记忆库、注入时污染上下文。改为 LLM 抽取式——
**存的是"值得记住的事实"，不是对话全文**。
"""

from __future__ import annotations

import logging
import time

from langgraph.store.base import BaseStore

from src.agent.prompts import MEMORY_EXTRACT_PROMPT
from src.core.paths import MEMORY_TASKS_ARCHIVE_FILE, MEMORY_TASKS_FILE
from src.llm.adapter import LLMAdapter

logger = logging.getLogger(__name__)

# 记忆 namespace（全局共享——跨会话回忆）
MEMORY_NAMESPACE = ("memory", "global")

# 噪音阈值：抽取出的记忆过短不写入（无意义碎片过滤）
MEMORY_MIN_LEN = 5
# 单条记忆最大长度（截断，防库膨胀）
MEMORY_MAX_LEN = 500
# 对话开始注入的记忆条数
MEMORY_INJECT_LIMIT = 5



async def extract_memory_fact(
    adapter: LLMAdapter | None,
    user_message: str,
    assistant_reply: str,
) -> str | None:
    """LLM 判断并抽取长期记忆事实；无记忆价值返回 None（统一走 LLMAdapter.chat）。

    Args:
        adapter: LLMAdapter 实例（注入式，测试用 LLMAdapter(model=fake)）；
            None → 默认 LLMAdapter()（get_chat_model 工厂）
        user_message: 本条用户消息
        assistant_reply: 本条助手回复全文

    Returns:
        抽取的一句话事实（中文 ≤50 字）；无价值/异常 → None（宁可不记不错记）

    Raises:
        无——LLM 调用异常统一降级返回 None（记忆是旁路能力，不阻断对话）
    """
    try:
        adapter = adapter or LLMAdapter()
        prompt = MEMORY_EXTRACT_PROMPT.format(user=user_message[:500], assistant=assistant_reply[:1500])
        text = (await adapter.chat(prompt)).strip()
    except Exception:  # noqa: BLE001 —— 抽取失败降级：不阻断对话
        logger.exception("记忆抽取失败（跳过本次记忆）")
        return None

    # 输出解析：含"无" → 无记忆价值；否则取首行作为事实
    if not text or "无" in text[:10]:
        return None
    fact = text.split("\n")[0].strip().strip('"\'')
    if not fact or len(fact) < MEMORY_MIN_LEN:
        return None
    return fact[:MEMORY_MAX_LEN]


async def save_conversation_memory(store: BaseStore, text: str) -> None:
    """把**已抽取的记忆事实**写入全局记忆（截断 + 时间戳 key）。

    注意：调用方应先用 extract_memory_fact 抽取——本函数只存"值得记住的事实"，
    不接收对话全文（2026-08-04 修正：防全量对话进记忆库）。

    Args:
        store: langgraph store（lifespan 初始化的 SqliteStore）
        text: 已抽取的记忆事实（一句话）
    """
    if store is None:
        return
    if len(text) < MEMORY_MIN_LEN:
        logger.debug("记忆跳过：事实过短（%d 字 < 阈值 %d）", len(text), MEMORY_MIN_LEN)
        return
    key = f"mem-{int(time.time() * 1000)}"
    await store.aput(
        MEMORY_NAMESPACE,
        key,
        {"content": text[:MEMORY_MAX_LEN], "ts": int(time.time())},
    )
    logger.info("记忆写入：%s（%d 字）", key, len(text))


async def load_recent_memories(store: BaseStore, limit: int = MEMORY_INJECT_LIMIT) -> list[str]:
    """取最近 N 条记忆内容（供 SystemMessage 注入）。

    Args:
        store: langgraph store
        limit: 注入条数上限

    Returns:
        记忆内容列表（新→旧）
    """
    if store is None:
        return []
    try:
        items = await store.asearch(MEMORY_NAMESPACE, limit=limit)
    except Exception:  # noqa: BLE001 —— 记忆检索是旁路能力，失败不阻断对话
        logger.exception("记忆检索失败（跳过注入）")
        return []
    return [str(item.value.get("content", "")) for item in items if item.value]


# ── v3 类型化扩展（记忆体系 §3.1/§8.3：用户画像/事实常识分 namespace）──

# 类型化 namespace（v3：替代单 global——写入按类型落库）
MEMORY_NAMESPACES = {
    "user_profile": ("memory", "user_profile"),   # 用户画像（长期）
    "facts": ("memory", "facts"),                 # 事实/常识（长期）
}
# 兼容：旧 global 数据（v1 写入）注入时一并读取
_LEGACY_NAMESPACE = ("memory", "global")
# 类型白名单（LLM 输出校验；未知类型 → facts 兜底）
_TYPE_WHITELIST = {"user_profile", "facts"}
# 短对话跳过阈值（v3.1：对话轮次 < 2 跳过抽取，省 token）
MEMORY_MIN_TURNS = 2
# 已完成任务归档保留条数（v3.1：配置化）
TASKS_ARCHIVE_KEEP = 20


async def extract_memory_typed(
    user_message: str, assistant_text: str, *, turn_count: int = 0
) -> dict | None:
    """LLM 抽取 + 类型分类（v3：一次调用输出 {type, fact}）。

    性能控制（v3.1）：对话太短（turn_count < MEMORY_MIN_TURNS）→ 跳过抽取。

    Args:
        user_message: 用户消息
        assistant_text: 助手回复
        turn_count: 本对话轮次（<2 → 跳过，短对话无记忆沉淀）

    Returns:
        {"type": "user_profile"|"facts", "fact": 一句话事实}；
        无记忆价值/对话过短 → None；类型未知 → facts 兜底 + 审计
    """
    if turn_count < MEMORY_MIN_TURNS:
        logger.debug("记忆抽取跳过：对话过短（turn_count=%d）", turn_count)
        return None
    fact = await extract_memory_fact(None, user_message, assistant_text)
    if not fact:
        return None
    # 类型判断：简单启发式——用户相关（我/我的/喜欢/偏好）→ user_profile，否则 facts
    # （P2 演进：LLM 结构化输出 type 字段；当前启发式零额外 token）
    if any(kw in user_message for kw in ("我", "我的", "喜欢", "偏好", "习惯", "请记住")):
        memory_type = "user_profile"
    else:
        memory_type = "facts"
    return {"type": memory_type, "fact": fact[:MEMORY_MAX_LEN]}


async def save_typed_memory(store: BaseStore, memory_type: str, fact: str) -> None:
    """类型化写入（对应 namespace，v3 §8.3）。

    Args:
        store: langgraph store（lifespan 初始化的 SqliteStore）
        memory_type: user_profile / facts（白名单校验）
        fact: 抽取的一句话事实

    Raises:
        ValueError: 未知类型（白名单外）
    """
    namespace = MEMORY_NAMESPACES.get(memory_type)
    if namespace is None:
        raise ValueError(f"未知记忆类型：{memory_type}，可选 {sorted(_TYPE_WHITELIST)}")
    if store is None:
        return
    if len(fact) < MEMORY_MIN_LEN:
        logger.debug("记忆跳过：事实过短（%d 字 < 阈值 %d）", len(fact), MEMORY_MIN_LEN)
        return
    key = f"mem-{int(time.time() * 1000)}"
    await store.aput(
        namespace,
        key,
        {"content": fact[:MEMORY_MAX_LEN], "ts": int(time.time())},
    )
    logger.info("记忆写入（%s）：%s（%d 字）", memory_type, key, len(fact))


async def load_recent_memories_v3(
    store: BaseStore,
    limit: int = MEMORY_INJECT_LIMIT,
    *,
    window_ratio: float = 0.1,
    window_tokens: int = 128_000,
) -> list[str]:
    """取最近记忆（上下文工程 #2 升级：画像优先 + 时间衰减 + 窗口 ≤10% 裁剪）。

    排序：画像优先（priority 0）→ 同优先级内时间衰减（ts 新→旧）；
    裁剪：注入 token 估算 ≤ window_ratio × window_tokens（v2 澄清：简单估算，
    精确放 P2）。

    Args:
        store: langgraph store
        limit: 基础条数上限
        window_ratio: 注入占上下文比例上限（0.1 = 10%）
        window_tokens: 上下文窗口大小（默认 128k）

    Returns:
        记忆内容列表（画像优先、新→旧、窗口裁剪后）
    """
    if store is None:
        return []
    try:
        profile = await store.asearch(MEMORY_NAMESPACES["user_profile"], limit=limit)
        facts = await store.asearch(MEMORY_NAMESPACES["facts"], limit=limit)
        legacy = await store.asearch(_LEGACY_NAMESPACE, limit=limit)
    except Exception:  # noqa: BLE001 —— 记忆检索是旁路能力，失败不阻断对话
        logger.exception("记忆检索失败（跳过注入）")
        return []
    merged = (
        [(item.value.get("content", ""), 0, item.value.get("ts", 0)) for item in profile if item.value]
        + [(item.value.get("content", ""), 1, item.value.get("ts", 0)) for item in facts if item.value]
        + [(item.value.get("content", ""), 2, item.value.get("ts", 0)) for item in legacy if item.value]
    )
    # 画像优先 → 同优先级内时间衰减（新在前）
    merged.sort(key=lambda x: (x[1], -x[2]))
    # 窗口裁剪：估算 token ≤ 比例上限（按序累计，超限截断）
    budget = int(window_ratio * window_tokens)
    result: list[str] = []
    used = 0
    for content, _, _ in merged:
        used += _estimate_tokens(content)
        if used > budget:
            break
        result.append(content)
    return result[:limit]


def _estimate_tokens(text: str) -> int:
    """简单 token 估算（v2 澄清：学习 demo 够用，精确放 P2）。

    规则：中文字符数 / 2 + 英文/数字字符数 / 4（粗估）。

    Args:
        text: 待估算文本

    Returns:
        估算 token 数
    """
    import re

    cjk = len(re.findall(r"[一-鿿]", text))
    other = len(text) - cjk
    return cjk // 2 + other // 4


async def archive_completed_tasks(
    backend, keep: int = TASKS_ARCHIVE_KEEP
) -> int:
    """已完成任务超限归档（记忆体系 §4.4/§8.4，v3.1 会话结束触发）。

    tasks.md 已完成（- [x]）保留最近 keep 条，更早追加到 tasks_archive.md
    （归档文件不注入，agent 按需读）；未完成（- [ ]）原样保留。

    Args:
        backend: /memories/ 路由 backend（create_backend 产物）
        keep: 已完成保留条数（缺省 TASKS_ARCHIVE_KEEP=20）

    Returns:
        归档条数（0 = 无超限/tasks.md 不存在）
    """
    if backend is None:
        return 0
    try:
        result = await backend.aread(MEMORY_TASKS_FILE)
        content = (result or {}).get("content", "") if isinstance(result, dict) else ""
    except Exception:  # noqa: BLE001 —— tasks.md 不存在/读失败 → 跳过（记忆是旁路能力）
        return 0
    if not content:
        return 0
    lines = content.splitlines()
    open_tasks = [ln for ln in lines if ln.strip().startswith("- [ ]")]
    done_tasks = [ln for ln in lines if ln.strip().startswith("- [x]")]
    if len(done_tasks) <= keep:
        return 0
    archived = done_tasks[: len(done_tasks) - keep]      # 更早的已完成
    keep_done = done_tasks[len(done_tasks) - keep:]      # 最近 keep 条
    await backend.awrite(MEMORY_TASKS_FILE, "\n".join(open_tasks + keep_done) + "\n")
    try:
        arch_result = await backend.aread(MEMORY_TASKS_ARCHIVE_FILE)
        arch_content = (
            (arch_result or {}).get("content", "") if isinstance(arch_result, dict) else ""
        )
    except Exception:  # noqa: BLE001
        arch_content = ""
    archive_block = "# 任务归档\n" + "\n".join(archived) + "\n"
    await backend.awrite(
        MEMORY_TASKS_ARCHIVE_FILE,
        (arch_content.rstrip() + "\n\n" if arch_content else "") + archive_block,
    )
    logger.info("任务归档：%d 条已完成任务移入 tasks_archive.md", len(archived))
    return len(archived)
