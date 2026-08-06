"""memory_agent 子代理：记忆管理员（记忆抽取子代理方案 §3.1/§3.2/§7.2）。

CompiledSubAgent 预编译——独立 StateBackend（隔离实践）+ 专属工具集
（工具集最小化：只挂记忆工具，不给文件/沙箱工具）。

依赖注入（评审问题 1 定案，方案 B）：工具内部 get_store() 运行时解析——
子代理编译时 store 未初始化（lifespan 异步），闭包注入不可行；
每次调用取当前实例（单例查询开销可忽略）。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import StateBackend
from langchain_core.language_models import BaseChatModel

from src.agent.memory.store import MEMORY_NAMESPACES, save_typed_memory
from src.agent.prompts import MEMORY_AGENT_PROMPT

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit")

# 工具集最小化（挂载层面单一约束，v1.1 诚实表述）：只挂记忆工具
_MEMORY_TOOLS = ("search_memory", "read_memory_file", "write_store",
                 "write_wiki", "send_notification")


def _fingerprint(session_id: str, user_message: str, assistant_text: str) -> str:
    """对话指纹（幂等去重：相同对话不重复抽取）。

    Args:
        session_id: 会话 ID
        user_message: 用户消息
        assistant_text: 助手回复

    Returns:
        指纹（sha256 前 16 位）
    """
    raw = f"{session_id}|{user_message}|{assistant_text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


async def search_memory(keyword: str) -> str:
    """查历史记忆（去重用，只读）——P1 类型感知查重（v2.0 补齐）。

    返回含类型的匹配条目（"[user_profile] 内容"格式）——子代理据
    "已存在相似内容"跳过写入，与 write_store 幂等衔接成完整去重协议。

    Args:
        keyword: 检索关键词

    Returns:
        匹配的记忆条目（含类型）列表；无 → "无匹配"
    """
    from src.agent.main_agent import get_store

    store = get_store()   # 方案 B：运行时解析（编译时不注入）
    if store is None:
        return "记忆库未初始化（降级：跳过查重）"
    try:
        matched: list[str] = []
        for mem_type, namespace in MEMORY_NAMESPACES.items():
            items = await store.asearch(namespace, limit=50)
            for item in items:
                content = item.value.get("content", "")
                if keyword and keyword in content:
                    matched.append(f"[{mem_type}] {content}")
        return "\n".join(matched) if matched else "无匹配"
    except Exception:  # noqa: BLE001 —— 记忆检索旁路能力，失败不阻断
        return "记忆检索失败（跳过查重）"


async def read_memory_file(path: str) -> str:
    """读记忆文件（辅助抽取，只读 /memories/）——P1 backend 接入（v2.0）。

    Args:
        path: /memories/ 下文件相对名（禁 ../ 与绝对路径）

    Returns:
        文件内容；校验失败 → 提示
    """
    if path.startswith("/") or ".." in path.split("/"):
        return "记忆文件路径不合法（仅 /memories/ 相对路径）。"
    from src.core.backend import create_backend

    try:
        result = await create_backend("default").aread(f"/memories/{path}")
        return (result or {}).get("content", "") if isinstance(result, dict) else str(result)
    except Exception:  # noqa: BLE001 —— 文件读失败降级
        return f"读取 {path} 失败（文件可能不存在）。"


async def write_store(memory_type: str, fact: str, related: str = "") -> str:
    """写 Store（幂等 + P3 轻量关联链 + 质量审计——只审计不拦截）。

    依赖注入方案 B：get_store() 动态取——编译时不注入 store 实例，
    运行时解析保证工具始终可用。

    Args:
        memory_type: user_profile / facts（白名单）
        fact: 抽取事实
        related: 关联的既有记忆内容摘要（P3 轻量关联链，v2.1 接入）

    Returns:
        写入结果描述（"已写入" / "已存在，跳过" / "记忆库未初始化"）

    Raises:
        ValueError: 未知记忆类型
    """
    from src.agent.main_agent import get_store

    store = get_store()
    if store is None:
        return "记忆库未初始化（降级：跳过写入）"
    if memory_type not in MEMORY_NAMESPACES:
        raise ValueError(f"未知记忆类型：{memory_type}")
    # 幂等：内容精确查重（P1 search_memory 语义查重在前，此处兜底）
    items = await store.asearch(MEMORY_NAMESPACES[memory_type], limit=50)
    for item in items:
        if item.value.get("content") == fact:
            return "已存在，跳过（幂等）"
    # P3 质量评估：只审计不拦截（v2.1 定位）——低分也写，审计标注供整理参考
    quality = score_memory_quality(fact, memory_type)
    if quality < 3:
        audit_logger.info(
            "memory_agent 低质记忆审计 type=%s quality=%d fact=%s",
            memory_type, quality, fact[:80],
        )
    await save_typed_memory(store, memory_type, fact, related=related)
    suffix = f"，关联：{related[:20]}" if related else ""
    return f"已写入 {memory_type}{suffix}"


async def write_wiki(page: str, content: str) -> str:
    """写 Wiki（文档记忆，指定命名空间）——P2 接入，先日志占位。

    Args:
        page: Wiki 页面名
        content: 页面内容

    Returns:
        写入结果（P2 前占位）
    """
    return f"write_wiki({page})：P2 接入 Wiki 系统后可用（当前占位）。"


async def send_notification(message: str) -> str:
    """发通知——P2 降级真实化（v2.0）：写入本地通知文件（可审计可查）。

    无外部通知通道（邮件/IM 未接入）——落 `data/notifications.log`（UTF-8
    追加）；外部通道接入时替换写入端（单点）。

    Args:
        message: 通知内容

    Returns:
        通知结果（"已记录到本地通知文件"）
    """
    from src.core.paths import get_notifications_log

    try:
        log_file = get_notifications_log()
        line = f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}\n"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)
        return "已记录到本地通知文件（data/notifications.log）。"
    except OSError as exc:
        return f"通知写入失败：{exc}"


def build_memory_agent(model: BaseChatModel) -> dict:
    """预编译 memory_agent（CompiledSubAgent：独立 StateBackend + 工具集最小化）。

    Args:
        model: 编译用模型（memory_agent_model 配置——独立小模型决策，
            默认空=主模型兜底，用户拍板 2026-08-05）

    Returns:
        CompiledSubAgent 声明（runnable 形态）
    """
    tools = [search_memory, read_memory_file, write_store, write_wiki, send_notification]
    runnable = create_deep_agent(
        model=model,
        name="memory_agent",
        system_prompt=MEMORY_AGENT_PROMPT,
        tools=tools,
        backend=StateBackend(),   # 独立内存 backend（隔离：不碰主会话文件）
        permissions=[
            FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
        ],
    )
    return {
        "name": "memory_agent",
        "description": "后台记忆管理员（抽取/去重/分类/存储）——纯后台任务，不返回用户",
        "runnable": runnable,
    }


# ── P3：质量评估（v2.0 设计 + 轻量实现，§6.5）──

def score_memory_quality(fact: str, memory_type: str, *, duplicates: int = 0) -> int:
    """记忆质量评分（1-5）：信息量 / 类型适配 / 唯一性。

    P3 轻量版（纯函数可单测）：低分（<3）→ 不写入或标注低质（审计）；
    定期整理时优先裁剪低分。模型质量评估（LLM 打分）标注后续。

    Args:
        fact: 记忆事实
        memory_type: user_profile / facts
        duplicates: 查重发现的相似条目数

    Returns:
        1-5 分（<3 = 低质）
    """
    score = 1
    # 信息量：长度（5-50 字为佳）+ 实体密度（含数字/专名加分）
    length = len(fact)
    if length >= 8:
        score += 1
    if length >= 15:
        score += 1
    import re

    if re.search(r"[0-9]", fact) or re.search(r"[A-Z]{2,}", fact):
        score += 1   # 数字/专名 = 信息量信号
    # 类型适配：facts 客观事实 +1（画像已含用户信号）
    if memory_type == "facts":
        score += 1
    # 唯一性：重复条目多 → 扣分
    score -= min(duplicates, 2)
    return max(1, min(5, score))
