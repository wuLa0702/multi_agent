"""主 Agent：deepagents 对话编排（搜索子代理 + OpenSandbox 沙箱工具）。

能力布局（蓝图 §4，与 agent_demo.py 同源）：
- 业务工具定义：src/tools/impl/ 按域分包（search.py 搜索域 / sandbox.py 沙箱域），
  经 src/tools/registry.py 注册表暴露
- 声明式子代理：src/agent/subagents/*.yaml（loader.py 解析，tools 名查 registry）

演进预留（接口文档 §2 重后端内聚）：
- checkpointer：断点恢复（resume_run_id）接入后再配——当前阶段 API 层
  无 resume，且 MemorySaver 要求 astream/invoke 必带 config.thread_id，
  提前配置会让流式调用直接报错（thread_id 缺失）
- interrupt_on：审批挂起（approve 事件）接入后配置
- skills：SKILL.md 渐进式加载
- MCP 协议化：registry 已有清单，FastMCP server（server.py）接入后同源暴露

当前目标：start → token×N → done 流式闭环（接口文档 §5），
对话中 agent 可按需委派搜索子代理 / 调用沙箱工具。

运行时模型切换（2026-08-03，官方 deepagents models 文档模式）：
- agent 单例复用：编译图无状态（无 checkpointer），进程内只构建一次
- 每次模型调用经 _configurable_model middleware 按 ChatContext.model_id 选模型
  （request.override(model=...) 只替换本次调用，不动 agent 本体）
- 模型配置真相源 = PostgreSQL（providers/models 表，lifespan 加载进注册表）；
  请求不带 model_id → 默认模型
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import threading
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from deepagents import create_deep_agent
from langchain.agents.middleware import wrap_model_call
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from src.agent.hitl.callback import HitlCallback
from src.agent.hitl.hitl import build_hitl_interrupt_on, should_mount_hitl_tools
from src.agent.hitl.pending import register_interrupt
from src.agent.middlewares.builder import build_middlewares
from src.agent.prompts import build_system_prompt
from src.agent.subagents.loader import load_subagents
from src.core.backend import create_backend
from src.core.config import settings
from src.core.paths import get_memory_sources, get_skill_md_dir
from src.core.permissions import build_main_permissions
from src.llm.adapter import get_chat_model
from src.tools.channels.mcp_client import get_mcp_client_manager
from src.tools.registry import hitl_tools, tools_for_main

from src.agent.middlewares.trace import trace_event  # 推理层 trace（决策 #4：agent/middlewares/trace.py）

logger = logging.getLogger(__name__)

@dataclass
class ChatContext:
    """请求级运行时上下文（context_schema）：模型选择 + 代理模式 + 会话定位。

    Attributes:
        model_id: 数据库模型 ID（providers/models 表，GET /v1/providers
            返回）；None → 默认模型（settings.llm_provider 厂商的默认模型）
        mode: 代理模式（default/plan/agent/auto，2026-08-04 P1）
            —— 先浅后深：仅注入 system_prompt 指令，不改编排
        session_id: 当前会话 ID——TokenUsageMiddleware 落库定位用
            （中间件是编译时单例，会话信息必须经请求级 context 传入）
    """

    model_id: int | None = None
    mode: str = "default"
    session_id: str | None = None
    context_profile: str = "standard"   # #9 窗口场景（small/standard/large——先场景后映射模型，与模型选择解耦）


@wrap_model_call
async def _configurable_model(request, handler):
    """模型调用拦截：按请求上下文 model_id 动态选模型（运行时切换）+ 主链路缓存。

    每次模型调用（含主 agent 多轮）都经此换模型；context 缺省或
    model_id 为空时用默认模型。`request.override(model=...)` 仅替换
    本次调用的模型实例，agent 本体保持单例复用。

    主链路缓存（2026-08-12 成本评审 1.2 扩展）：llm_cache_enabled=True 时，
    相同 (messages 序列化, model_name) 命中 → 直接返回缓存 ModelResponse
    （绕过 LLM）；未命中 → 调 handler 后写入。model 不同不共享缓存。

    注意：必须是 async 函数——项目走 astream_events（异步流式），
    wrap_model_call 装饰同步函数时只提供同步钩子，异步上下文会抛错
    （官方示例用同步 invoke，异步场景需 async 版本）。
    """
    model_id = None
    context = getattr(request.runtime, "context", None) if request.runtime else None
    if context is not None:
        model_id = getattr(context, "model_id", None)
    model = get_chat_model(model_id=model_id)

    from src.core.config import settings

    if settings.llm_cache_enabled:
        cached = await _main_path_cache_get(request, model)
        if cached is not None:
            return cached
        result = await handler(request.override(model=model))
        await _main_path_cache_set(request, model, result)
        return result
    return await handler(request.override(model=model))


async def _main_path_cache_get(request, model) -> object | None:
    """主链路缓存查询：相同 (messages, model) 命中 → 返回缓存 ModelResponse。

    底层函数，按规范豁免（通用缓存封装）。

    Args:
        request: ModelRequest（含 messages 完整输入）
        model: ChatOpenAI 实例（model_name 做缓存键维度）

    Returns:
        命中 → ModelResponse(result=cached AIMessage)；未命中/缓存不可用 → None
    """
    from langchain.agents.middleware import ModelResponse
    from langchain_core.messages import AIMessage
    from src.llm.cache import get_cached

    model_name = getattr(model, "model_name", "") or "default"
    prompt = _serialize_messages(request.messages)
    cached = get_cached(prompt, model_name, _get_cache_ttl())
    if cached is None:
        return None
    return ModelResponse(result=AIMessage(content=cached))


async def _main_path_cache_set(request, model, result) -> None:
    """主链路缓存写入：调 handler 后缓存响应文本。

    底层函数，按规范豁免（通用缓存封装）。

    Args:
        request: ModelRequest
        model: ChatOpenAI 实例
        result: ModelResponse（含 result AIMessage）
    """
    from src.llm.cache import set_cached

    model_name = getattr(model, "model_name", "") or "default"
    content = getattr(result, "result", None)
    text = getattr(content, "content", None) or ""
    if text:
        set_cached(_serialize_messages(request.messages), model_name, str(text))


def _serialize_messages(messages) -> str:
    """messages → 缓存键字符串（消息 role+content 扁平化）。

    底层函数，按规范豁免（通用序列化封装）。
    """
    parts = []
    for m in messages or []:
        parts.append(f"{getattr(m, 'type', 'msg')}:{getattr(m, 'content', '')}")
    return "\n".join(parts)


def _get_cache_ttl() -> int:
    """缓存 TTL（settings.llm_cache_ttl，避免函数内重复 import）。"""
    from src.core.config import settings

    return settings.llm_cache_ttl


# 会话级 Agent 缓存（v2.0 设计：CompositeBackend 会话隔离 + v3 有界 LRU）：
# 每会话（thread_id）一个编译图 + 独立 backend 文件根——废弃全局单例
# （多会话文件混存是 v1 硬缺陷，见 docs/decisions/CompositeBackend文件存储-设计-v3.md §2.1）
# v3.0 治理（深化方案 §2.3）：OrderedDict 有界 LRU——超限逐出最久未用会话，
# 只逐内存图不删磁盘文件（工作区文件由 DELETE 会话联动清理）；逐出经 popitem(last=False)。
_agents: "OrderedDict[str, object]" = OrderedDict()
_agents_lock = threading.Lock()  # 双重检查锁（会话维度）：防止并发首次构建重复建图
# 会话缓存上限（单机单用户场景 32 个并发会话足够；compile 是纯内存操作）
_AGENT_CACHE_MAX = 32

# Checkpointer（P0 断点持久化，2026-08-04；2026-10-15 PG 迁移）：
# ⚠️ 实测修正（评审方式 A 需适配 async）：sync Saver 在 async astream 下
# **静默失败**（langgraph 3.x async 执行路径要求 Async* 版本）。这条教训随
# SQLite → PG 一并沿用——必须 AsyncPostgresSaver。
# 正确架构：Checkpointer 由 **lifespan 管理生命周期**（与 Redis 连接池同模式）——
# main.py 启动时 await init_checkpointer()，关闭时 close_checkpointer()。
# 未初始化（测试/脚本未跑 lifespan）→ 构建不带 checkpointer，降级无断点模式。
_checkpointer = None

# 对话流并发限流（计划文档 C.1-2）：原为「单机多浏览器并发对话同时写
# SQLite 断点会撞写锁」而设，Semaphore 限制同时执行的流数量，超出排队。
# ⚠️ 2026-10-15 PG 迁移：PG 支持真正并发写，该前提已消失；取值暂不动
# （见 core/config.py::stream_concurrency 注释），后续按实测再调。
# 2026-08-10 拍板：硬编码 4 → settings.stream_concurrency（本地 .env.dev=10，
# 云端 .env.prod=2，环境保存可调）。
# 2026-08-11 决策 #3：模块级固定值 → 函数工厂（惰性创建，settings 变化可重建，
# 不关心底层只关心获取）。
_stream_semaphore: asyncio.Semaphore | None = None


def get_stream_semaphore() -> asyncio.Semaphore:
    """对话流并发信号量（函数工厂：惰性创建 + settings 变化重建）。

    ⚠️ 重建语义：settings.stream_concurrency 变化时重建（测试/环境切换场景）；
    生产运行中 settings 不变，重建仅发生在请求开始获取时，不影响已排队等待者
    （旧信号量释放后自然结束）。

    Returns:
        当前并发上限的信号量
    """
    global _stream_semaphore
    # getattr 防御：测试会注入 nullcontext 替身（无 _value），工厂不炸
    current = getattr(_stream_semaphore, "_value", None)
    if _stream_semaphore is None or current != settings.stream_concurrency:
        _stream_semaphore = asyncio.Semaphore(settings.stream_concurrency)
    return _stream_semaphore


async def init_checkpointer(dsn=None, *, search_path=None) -> None:
    """初始化断点持久化（lifespan 启动调用，幂等）。

    AsyncPostgresSaver + 独立 PG 连接（async 执行路径必需）：
    - 连接参数照 langgraph 官方约定（autocommit + prepare_threshold=0 + dict_row）
    - 断点表建在 pg_langgraph_schema（与业务表同库不同 schema，隔离关注点）
    - 连接生命周期跟随进程（与 core/redis.py 同模式）

    Args:
        dsn: 覆盖连接串（测试隔离用；缺省 settings.pg_dsn）
        search_path: 覆盖 schema（测试「每用例独立 schema」用；
            缺省 settings.pg_langgraph_schema）
    """
    global _checkpointer
    if _checkpointer is not None:
        return
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row

    from src.db import connection as db_conn

    conn = await db_conn.connect_with_schema(
        dsn,
        search_path=search_path or settings.pg_langgraph_schema,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    _checkpointer = AsyncPostgresSaver(conn)
    await _checkpointer.setup()


async def close_checkpointer() -> None:
    """关闭断点连接（lifespan 关闭调用，幂等）。"""
    global _checkpointer
    if _checkpointer is None:
        return
    try:
        await _checkpointer.conn.close()
    finally:
        _checkpointer = None


async def checkpoint_exists(thread_id: str, checkpoint_id: str) -> bool:
    """校验 checkpoint 是否存在（resume 潜伏 bug 修复，P0 设计 §5.4）。

    langgraph 对无效 checkpoint_id 静默从空状态开始（§3.3-③ 实证）——resume
    前主动校验，避免"看起来成功实际重开"的状态丢失。测试/脚本未初始化
    checkpointer 时跳过校验（返回 True）。

    Args:
        thread_id: 会话 ID（checkpoint 按 thread 隔离）
        checkpoint_id: resume_run_id（approve 事件透传的真实 checkpoint_id）

    Returns:
        True=checkpoint 存在（或 checkpointer 未初始化）；False=不存在
    """
    if _checkpointer is None:
        return True
    config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
            "checkpoint_id": checkpoint_id,
        }
    }
    try:
        if hasattr(_checkpointer, "aget_tuple"):
            return (await _checkpointer.aget_tuple(config)) is not None
    except Exception:  # noqa: BLE001 —— 校验失败视为不存在（宁可报错不静默重开）
        return False
    return True


def has_checkpointer() -> bool:
    """当前是否挂了 Checkpointer（决定「谁负责恢复对话历史」，C01 修复 2026-09-11）。

    挂了 Checkpointer 时**执行历史由图状态承载**，chat.py 只传增量；未挂
    （测试/脚本未跑 lifespan）→ 降级由 DB 重建全量历史。

    Returns:
        True=图持久化执行历史（新消息模式只传增量）；False=降级模式（传 DB 全量历史）
    """
    return _checkpointer is not None


async def delete_thread_checkpoints(thread_id: str) -> bool:
    """删除某会话（thread）的全部断点（S01：删除会话联动清理，2026-09-11）。

    ⚠️ 只删**执行状态**断点；长期 Store（跨会话记忆）**不删**——记忆独立于
    会话生命周期（co-creator 拍板）。checkpointer 未初始化 → 视为无需清理。

    Args:
        thread_id: 会话 ID（== thread_id）

    Returns:
        True=已删除或无需清理；False=删除失败（已降级记录，不抛）
    """
    if _checkpointer is None:
        return True
    try:
        await _checkpointer.adelete_thread(thread_id)
        return True
    except Exception:  # noqa: BLE001 —— 断点清理是旁路，失败不阻断会话删除
        logger.warning("断点清理失败（会话删除继续）：thread=%s", thread_id, exc_info=True)
        return False


# Store 长期记忆（P1，2026-08-04；2026-10-15 PG 迁移 → PostgresStore），
# 生命周期由 lifespan 管理（与 checkpointer 同模式）；未初始化 → 降级无记忆。
_store = None


def get_store():
    """当前 store 实例（记忆读写用）；未初始化返回 None。"""
    return _store


async def init_store(dsn=None, *, search_path=None) -> None:
    """初始化记忆存储（lifespan 启动调用，幂等）。

    AsyncPostgresStore + 独立 PG 连接：
    - ⚠️ 实测修正（同 Checkpointer 教训）：Store 的 sync 版不支持 async 方法
      （aput/asearch 抛 NotImplementedError），async 执行路径必须用 Async* 版
    - 记忆表建在 pg_langgraph_schema（与业务表同库不同 schema）
    - 连接参数照 langgraph 官方约定（autocommit + prepare_threshold=0 + dict_row）

    Args:
        dsn: 覆盖连接串（测试隔离用；缺省 settings.pg_dsn）
        search_path: 覆盖 schema（测试「每用例独立 schema」用；
            缺省 settings.pg_langgraph_schema）
    """
    global _store
    if _store is not None:
        return
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from psycopg.rows import dict_row

    from src.db import connection as db_conn

    conn = await db_conn.connect_with_schema(
        dsn,
        search_path=search_path or settings.pg_langgraph_schema,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    _store = AsyncPostgresStore(conn)
    await _store.setup()


async def close_store() -> None:
    """关闭记忆连接（lifespan 关闭调用，幂等）。"""
    global _store
    if _store is None:
        return
    try:
        await _store.conn.close()
    finally:
        _store = None


def get_agent(thread_id: str = "default"):
    """按会话懒构建 deepagents 编译图（v2.0 会话级缓存 + v3 有界 LRU）。

    每会话（thread_id）独立编译图 + 独立 backend 文件根（create_backend(thread_id)，
    会话文件隔离——v2 硬缺陷 1 修复）；compile 是内存操作，单机会话数少可接受。
    构建仅做内存图装配（无网络 I/O）；模型每次调用经 _configurable_model
    middleware 按 ChatContext.provider 动态选择，图本身不绑定具体 provider。

    v3.0 LRU（深化方案 §2.3）：命中即刷新（pop 后放回，保持最近使用序）；
    超 _AGENT_CACHE_MAX 逐出最久未用（popitem(last=False)）。逐出只清内存图，
    磁盘工作区文件由 DELETE /v1/sessions 联动清理（防 LRU 误删活跃会话文件）。

    Args:
        thread_id: 会话 ID（== session_id）；demo/无会话场景默认 "default"

    Returns:
        deepagents 编译后的 Agent（LangGraph CompiledStateGraph）
    """
    with _agents_lock:
        agent = _agents.pop(thread_id, None)  # LRU 刷新（先移除再放回，保持使用序）
        if agent is not None:
            _agents[thread_id] = agent
            return agent
        agent = _build_agent(thread_id)
        _agents[thread_id] = agent
        while len(_agents) > _AGENT_CACHE_MAX:
            evicted, _ = _agents.popitem(last=False)
            logger.info("Agent 缓存逐出（LRU）：thread=%s", evicted)
        return agent


def _build_agent(thread_id: str):
    """构建单个会话的编译图（get_agent 的构建体抽离，v3）。

    Args:
        thread_id: 会话 ID（== session_id，backend 文件根绑定它）

    Returns:
        deepagents 编译后的 Agent（LangGraph CompiledStateGraph）
    """
    # 工具 = 内部工具 + 外部 MCP 工具（lifespan 连接收集，见 src/tools/channels/mcp_client.py）
    # 内部工具清单唯一来源 = tools/registry.py（阶段 0.1：杜绝硬编码清单漂移）
    internal_tools = tools_for_main()
    # HITL 工具（P0 设计 §5.1）：hitl_enabled 门控挂载——ask_human（需求澄清/
    # 中途确认，respond 决策）+ publish_report（输出审核交付闸门）。关 HITL 时
    # 不挂载，避免模型调用永远抛错/无审批出口的工具。
    if should_mount_hitl_tools(settings.hitl_enabled):
        internal_tools += hitl_tools()
    mcp_tools = get_mcp_client_manager().get_tools()
    model = get_chat_model()  # 默认 provider 兜底（middleware 会覆盖）；P2 编译子代理共用
    # 中间件链（阶段 3 收口）：装配与顺序集中在 middlewares/builder.py——
    # 新增横切能力只改那里，本文件不再动。模型选择中间件作为参数注入
    # （它定义在本模块，builder 直接 import 会循环）。
    middleware = build_middlewares(_configurable_model)
    return create_deep_agent(
        model=model,
        system_prompt=build_system_prompt(),  # 分层组装（核心+可选；动态记忆由 chat 注入）
        # 子代理统一预编译 + 容错包装（loader._compile_guarded：StateBackend +
        # 重试 + 错误摘要回传；2026-08-20 容错落地，原 SUBAGENT_ISOLATION 开关并入）
        subagents=load_subagents(model=model),
        tools=internal_tools + mcp_tools,
        middleware=middleware,
        # HITL 审批（P1，2026-08-06 设计 §5.1）：hitl_enabled 门控——沙箱/文件/
        # 技能等副作用工具执行前人类审批（按风险分级，见 agent/hitl/hitl.py）；
        # checkpointer 已接（硬前置）；审批恢复链路待 P0-V2 验证后接 chat.py
        interrupt_on=build_hitl_interrupt_on(settings.hitl_enabled),
        context_schema=ChatContext,
        # SKILL.md 渐进式加载：走 backend 虚拟路径 /skills/market/
        # （v2.0：SkillsMiddleware 经 backend 读文件，虚拟路径路由到
        # data/skills/skill_md——真实路径会被 virtual_mode 越权拒绝）
        skills=["/skills/market/"],
        # Checkpointer（P0 断点持久化）：AsyncPostgresSaver 由 lifespan
        # 初始化（init_checkpointer）；未初始化（测试/脚本）→ 不传，
        # 降级无断点模式。astream 必须带 thread_id（stream_agent_tokens
        # 内部封装），否则直接报错
        checkpointer=_checkpointer,
        # Store 长期记忆（P1）：AsyncPostgresStore 由 lifespan 初始化（init_store）；
        # 未初始化 → 降级无记忆。记忆注入/写入在 chat.py（memory_store 封装）
        store=_store,
        # 文件记忆（记忆体系 v3）：AGENTS.md 单文件全量注入（官方
        # MemoryMiddleware，虚拟路径语义）；tasks/decisions 分类承载按需读
        memory=get_memory_sources(),  # 虚拟路径由 paths.py 集中维护（禁散落硬编码）
        # 会话级 Backend（v2.0）：文件根绑定 thread_id 目录，会话隔离
        backend=create_backend(thread_id),
        # 上层声明式权限（P0 深化）：/skills/** 写 deny 等模板，见 core/permissions.py
        permissions=build_main_permissions(),
    )


def rebuild_agent(thread_id: str | None = None) -> None:
    """失效 Agent 缓存，下次请求重建（Skill Market 安装/卸载后调用）。

    Args:
        thread_id: 指定会话失效；None → 清空全部会话缓存

    纯内存标记操作（编译图无状态），并发安全：get_agent 的双重检查锁
    保证同一时刻只有一个线程在重建。
    """
    with _agents_lock:
        if thread_id is None:
            _agents.clear()
        else:
            _agents.pop(thread_id, None)


def build_agent(model: BaseChatModel | None = None, thread_id: str = "default"):
    """获取主 Agent（历史签名兼容：model 参数已弃用，走会话级缓存）。

    Args:
        model: 兼容旧调用方；单例模式下忽略（模型经 middleware 运行时选择）
        thread_id: 会话 ID（== session_id，会话文件隔离）

    Returns:
        deepagents 编译后的 Agent（LangGraph CompiledStateGraph）
    """
    return get_agent(thread_id)


def _build_stream_config(
    context: ChatContext | None,
    checkpoint_id: str | None,
    hitl_callback: HitlCallback | None,
) -> dict:
    """构建 astream_events config（线程/断点/子图/限流/回调）。

    Args:
        context: 请求级上下文（session_id → thread_id）
        checkpoint_id: resume 模式精确快照
        hitl_callback: HITL 中断采集回调（None 不挂）

    Returns:
        langchain config dict
    """
    config = None
    if context is not None and context.session_id:
        config = {"configurable": {"thread_id": context.session_id}}
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id
    # stream_subgraphs：子代理/子图事件（v3 subagents 投影的 v2 等价物）
    # recursion_limit：settings.agent_recursion_limit（2026-08-10 评估实证
    # 默认 25 研究任务易撞限——见 测试报告-评估体系首跑）
    config = {
        **(config or {}),
        "stream_subgraphs": True,
        "recursion_limit": settings.agent_recursion_limit,
    }
    if hitl_callback is not None:
        # HITL 中断检测唯一途径（设计 §3.3-② 实证：astream_events 不产 on_interrupt）
        config["callbacks"] = [hitl_callback]
    return config


def _tool_outcome(output: Any) -> tuple[str, str | None, str, bool]:
    """工具输出 → `(生命周期 status, 结果三态, 归一错误码, 可重试)`（阶段 2.3.2/4 批次 3）。

    三态取自工具输出的 **artifact 结构化通道**（阶段 2 双通道落地，
    见 `tools/contract/adapter.py::artifact_of`）——`ToolMessage.status` 只有
    success/error，`degraded` 会被它压成 success，故必须从 artifact 取。
    `retryable` 同源：它是"这次失败能不能救"的运行时事实（阶段 4 批次 3 接的
    真实读者，此前写了无人读）。

    Args:
        output: `on_tool_end` 的 `data.output`（真实链路为 `ToolMessage`）

    Returns:
        `(status, result_status, error_code, retryable)`：
        有信封 → 生命周期按三态映射（`error`→`error`，其余 `completed`），
        三态/错误码/可重试原样带出；无信封（非 ToolMessage，如测试替身）→
        三态 `None` + 空错误码 + `retryable=False` + `completed`，**不猜**
    """
    artifact = getattr(output, "artifact", None)
    if not isinstance(artifact, dict):
        return "completed", None, "", False
    result_status = artifact.get("status") or None
    error_code = str(artifact.get("error_code") or "")
    lifecycle = "error" if result_status == "error" else "completed"
    return lifecycle, result_status, error_code, bool(artifact.get("retryable"))


def _tool_output_text(output: Any) -> str:
    """工具输出 → 给前端展示的文本。

    真实链路 `data.output` 是 `ToolMessage`——取 `.content`（给 LLM 的中文文本），
    而不是 `str(ToolMessage)`（那是 repr，前端会显示一坨对象字面量）。
    """
    content = getattr(output, "content", None)
    return content if isinstance(content, str) else str(output)


def _dispatch_stream_event(
    evt: dict, session_id: str | None, seq: int
) -> tuple[int, dict | None]:
    """单事件分发：trace + 事件构建（token/tool_call/subagent）。

    Args:
        evt: astream_events 原始事件 dict
        session_id: 会话 ID（推理层 trace 定位）
        seq: 当前事件序号

    Returns:
        (新 seq, 待 yield 事件 dict 或 None)
    """
    event_type = evt.get("event")
    if event_type == "on_chat_model_stream":
        chunk = evt.get("data", {}).get("chunk")
        text = getattr(chunk, "text", None) if chunk is not None else None
        if text:
            seq += 1
            return seq, {"type": "token", "text": text, "id": seq}
    elif event_type == "on_tool_start":
        trace_event(session_id, evt)  # 推理层 trace
        seq += 1
        return seq, {
            "type": "tool_call",
            "tool": evt.get("name", ""),
            "status": "running",
            # 形状与 on_tool_end 一致（前端不必判键存在）；结果还没出来 → 三态留空
            "result_status": None,
            "error_code": "",
            "retryable": False,
            "input": _truncate(str(evt.get("data", {}).get("input", ""))),
            "output": None,
            "id": seq,
        }
    elif event_type == "on_tool_end":
        trace_event(session_id, evt)  # 推理层 trace
        seq += 1
        output = evt.get("data", {}).get("output", "")
        lifecycle, result_status, error_code, retryable = _tool_outcome(output)
        return seq, {
            "type": "tool_call",
            "tool": evt.get("name", ""),
            "status": lifecycle,
            "result_status": result_status,
            "error_code": error_code,
            "retryable": retryable,
            "input": "",
            "output": _truncate(_tool_output_text(output)),
            "id": seq,
        }
    elif event_type in ("on_chain_start", "on_chain_end") and evt.get(
        "metadata", {}
    ).get("lc_agent_name"):
        # 子代理事件：deepagents 子代理经 with_config 注入
        # lc_agent_name（_compile_spec 约定，subagents.py:437）——
        # 子图链事件携带该 metadata 即子代理启停。
        # ⚠️ 待浏览器实测校准：Fake 模型不出工具调用，子代理不触发，
        # 事件形态（字段名/嵌套深度）需真实链路验证
        trace_event(session_id, evt)  # 推理层 trace
        seq += 1
        return seq, {
            "type": "subagent",
            "name": evt["metadata"]["lc_agent_name"],
            "status": "started" if event_type == "on_chain_start" else "completed",
            "depth": 0,
            "id": seq,
        }
    elif event_type == "on_chat_model_start":
        # 推理层 trace：模型调用（含子代理内部——parent_ids 层级可区分）
        trace_event(session_id, evt)
    return seq, None


async def _register_interrupt_if_needed(
    hitl_callback: HitlCallback | None, session_id: str | None
) -> dict | None:
    """中断登记（try/finally 保证——异常提前结束也登记）。

    中断已落 checkpoint，登记缺失会让 resume 404。

    Args:
        hitl_callback: HITL 中断采集回调
        session_id: 会话 ID

    Returns:
        中断信息 dict（未中断返回 None）
    """
    if hitl_callback is not None and hitl_callback.interrupted:
        info = hitl_callback.interrupted
        await register_interrupt(
            info["checkpoint_id"], info["hitl_request"], session_id or ""
        )
        return info
    return None


async def stream_agent_events(
    agent,
    messages: list[BaseMessage],
    context: ChatContext | None = None,
    checkpoint_id: str | None = None,
    hitl_callback: HitlCallback | None = None,
    run_id: str = "",
    graph_input: Any = None,
) -> AsyncIterator[dict]:
    """事件流（引入方案 P0 校准版）：token + tool_call + subagent + approve 事件。

    ⚠️ 实测校准（2026-08-05，方案 §6.2 风险项 2.3）：v3 messages 投影为
    message 粒度（整条消息，非逐 chunk），且本模型栈（OpenAI 兼容 adapter）
    无 content-block 协议支持——v3 直接出 token 会摧毁打字机效果。
    校准：单次 v2 事件流多事件分发——token 走 on_chat_model_stream（逐 chunk），
    tool_call 走 on_tool_start/on_tool_end，subagent 走 stream_subgraphs 子图链。
    v3 声明式投影保留为 examples/ 学习脚本（不接生产链路）。

    HITL（P0 设计 §5.5）：hitl_callback（GraphCallbackHandler）经 config["callbacks"]
    采集中断；流循环 try/finally 保证中断登记（异常提前结束也登记——中断已落
    checkpoint，登记缺失会让 resume 404）；finally 之后产 approve 事件并终止流。

    产出事件（SSE 协议 v3 对齐）：
      {"type": "token",     "text": ..., "id": 序号}
      {"type": "tool_call", "tool": ..., "status": "running|completed|error",
       "input": ..., "output": ..., "id": 序号}
      {"type": "subagent",  "name": ..., "status": "started|completed|failed",
       "depth": 0, "id": 序号}
      {"type": "approve",   "run_id"/"checkpoint_id"/"call_id"/"tool_name"/... }

    Args:
        agent: build_agent 的产物
        messages: LangChain 消息列表（含历史）；resume 模式传空列表
        context: 请求级上下文（session_id → thread_id config 封装）
        checkpoint_id: resume 模式从精确快照继续
        hitl_callback: HITL 中断采集回调（None 不挂；挂载后 config 加 callbacks）

    Yields:
        事件 dict（SSE 层据此分发）

    Raises:
        Exception: checkpoint_id 无效/不属于该 thread（API 层转 RESUME_NOT_FOUND）
    """
    config = _build_stream_config(context, checkpoint_id, hitl_callback)
    session_id = context.session_id if context else None  # 修订计数定位（v1.2）
    seq = 0
    async with get_stream_semaphore():  # 并发限流：同时执行的流数量上限
        interrupted = None
        # 审批恢复（P0 设计 §5.4）：graph_input 为 Command(resume=...) 时直接作
        # astream_events 输入（§3.3-① 实证可行）；否则默认 {"messages": messages}
        input_payload = graph_input if graph_input is not None else {"messages": messages}
        try:
            async for evt in agent.astream_events(
                input_payload, version="v2", context=context, config=config
            ):
                seq, event = _dispatch_stream_event(evt, session_id, seq)
                if event is not None:
                    yield event
        finally:
            # v1.2 评审修正：try/finally 保证登记——无论正常/异常结束，只要回调
            # 采到中断（中断已落 checkpoint），必须写 Redis，否则 resume 404
            interrupted = await _register_interrupt_if_needed(hitl_callback, session_id)
        # finally 之后产 approve 事件（generator 不能在 finally 内 yield）→ 终止流
        if interrupted is not None:
            for action, review in _iter_action_reviews(interrupted["hitl_request"]):
                seq += 1
                yield _build_approve_event(
                    run_id=run_id,  # chat.py 流 run_id（v1.1：与 checkpoint 分离）
                    checkpoint_id=interrupted["checkpoint_id"],
                    action=action,
                    review=review,
                    seq=seq,
                )


def _truncate(text: str, limit: int = 300) -> str:
    """事件字段截断（密钥纪律 + 防上下文膨胀；同 ToolAudit 脱敏口径）。"""
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _iter_action_reviews(hitl_request: dict):
    """HITLRequest → (action, review) 逐条（按序一一对应）。

    Args:
        hitl_request: {"action_requests": [...], "review_configs": [...]}

    Yields:
        (action_request, review_config) 二元组（review 缺省给空 dict）
    """
    configs = {c.get("action_name"): c for c in hitl_request.get("review_configs", [])}
    for action in hitl_request.get("action_requests", []):
        yield action, configs.get(action.get("name"), {})


def _build_approve_event(
    run_id: str, checkpoint_id: str, action: dict, review: dict, seq: int
) -> dict:
    """approve 事件构建（对齐前端 B2 契约 + run_id/checkpoint_id 分离，设计 §5.2）。

    Args:
        run_id: chat.py 本次流 run_id（流标识，前端区分多次中断）
        checkpoint_id: 中断点 checkpoint_id（resume 恢复键，前端透传）
        action: action_request（name/args）
        review: review_config（allowed_decisions）
        seq: 流内事件序号

    Returns:
        SSE 事件 dict（approve）
    """
    allowed = review.get("allowed_decisions", ["approve", "reject"])
    name = action.get("name", "")
    args = action.get("args", {}) or {}
    if name == "ask_human":
        message = f"澄清：{str(args.get('message', ''))[:200]}"
    elif name == "publish_report":
        message = f"交付审核：{str(args.get('title', ''))[:100]}"
    else:
        message = f"工具 {name} 需要审批"
    return {
        "type": "approve",
        "run_id": run_id,
        "checkpoint_id": checkpoint_id,  # v1.1 新增独立字段
        "call_id": action.get("call_id") or f"action-{seq}",  # v1.2：fallback 流内唯一
        "tool_name": name,
        "arguments": _truncate_args(args),  # v1.2 评审修正：脱敏截断
        "message": message,
        "allowed_decisions": allowed,
        "kind": "clarification" if name == "ask_human" else "approval",
        "id": seq,
    }


def _truncate_args(args: dict, limit: int = 300) -> dict:
    """待审参数脱敏截断（v1.2 评审修正，对齐 §5.2「脱敏截断 ≤300」）。

    publish_report 的 report_content 可能很长——不截断会撑爆 SSE 事件；
    逐字符串字段截断到 limit（保留 dict 结构），嵌套 dict 顶层字段已覆盖
    主要场景（report_content/title/message 均为顶层 str）。

    Args:
        args: 工具调用参数 dict
        limit: 单字段截断上限

    Returns:
        截断后的 dict（长字符串字段 + "…" 后缀）
    """
    truncated: dict = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > limit:
            truncated[key] = value[:limit] + "…"
        else:
            truncated[key] = value
    return truncated


async def stream_agent_tokens(
    agent,
    messages: list[BaseMessage],
    context: ChatContext | None = None,
    checkpoint_id: str | None = None,
) -> AsyncIterator[str]:
    """流式执行 Agent，产出对话文本增量（v2 兼容层，EVENT_STREAM_V3=false 回退）。

    实现：astream_events v2 监听 on_chat_model_stream，只取文本 chunk
    （工具调用 chunk 的 text 为空，天然过滤；deepagents 内部 todo 工具
    参数走 tool_call_chunks，不会误发成 token 事件）。

    上下文用量：由中间件栈内的 TokenUsageMiddleware 自动统计落库
    （2026-08-04 评审改版——替代原 CallbackHandler 手动读取方案），
    此处无需任何配置传递。

    断点持久化（P0）：thread_id config **内部封装**（计划文档 C.2）——
    ChatContext.session_id == thread_id（每会话一条执行线）；调用方零感知，
    杜绝漏传 thread_id 导致的 500。并发限流用 _stream_semaphore（C.1-2）。
    checkpoint_id：审批断点恢复（resume 模式）时传入——从精确快照继续执行，
    已完成步骤不重跑（计划文档 A）。

    Args:
        agent: build_agent 的产物
        messages: LangChain 消息列表（含历史，按时间正序）；resume 模式传空列表
            （checkpoint 状态接管，输入被忽略）
        context: 请求级上下文（provider 选择）；None → 默认 provider
        checkpoint_id: 恢复的快照 ID（resume 模式）；None → 新消息模式

    Yields:
        模型生成文本增量（每片非空）

    Raises:
        Exception: checkpoint_id 无效/不属于该 thread（由 API 层捕获转
            RESUME_NOT_FOUND 友好错误）
    """
    config = None
    if context is not None and context.session_id:
        config = {"configurable": {"thread_id": context.session_id}}
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id

    async with get_stream_semaphore():  # 并发限流：同时执行的流数量上限
        async for evt in agent.astream_events(
            {"messages": messages}, version="v2", context=context, config=config
        ):
            if evt.get("event") != "on_chat_model_stream":
                continue
            chunk = evt.get("data", {}).get("chunk")
            if chunk is None:
                continue
            text = getattr(chunk, "text", None)
            if text:
                yield text
