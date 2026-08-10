"""主 Agent：deepagents 对话编排（搜索子代理 + OpenSandbox 沙箱工具）。

能力布局（蓝图 §4，与 agent_demo.py 同源）：
- 业务工具定义：src/agent/tools/ 按域分包（search.py 搜索域 / sandbox_tool.py 沙箱域），
  经 src/mcp/registry.py 注册表暴露
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
- 模型配置真相源 = SQLite（providers/models 表，lifespan 加载进注册表）；
  请求不带 model_id → 默认模型
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass

from deepagents import create_deep_agent
from langchain.agents.middleware import wrap_model_call
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from src.agent.hitl.hitl import build_hitl_interrupt_on
from src.agent.middlewares.interpreter import build_interpreter_middleware
from src.agent.middlewares.token_usage import TokenUsageMiddleware
from src.agent.middlewares.tool_audit import ToolAuditMiddleware
from src.agent.rubrics.rubrics import build_rubric_middleware
from src.agent.prompts import build_system_prompt
from src.agent.subagents.loader import load_subagents
from src.core.backend import create_backend
from src.core.config import settings
from src.core.paths import (
    get_checkpointer_path,
    get_memory_sources,
    get_skill_md_dir,
    get_store_path,
    CHECKPOINTER_DB_FILE,
    STORE_DB_FILE,
)
from src.core.permissions import build_main_permissions
from src.llm.adapter import get_chat_model
from src.mcp.client import get_mcp_client_manager
from src.agent.tools.sandbox_tool import (
    download_sandbox_file,
    run_code_in_sandbox,
    run_command_in_sandbox,
    upload_workspace_file,
)
from src.agent.tools.skill_tool import run_skill_script

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
    """模型调用拦截：按请求上下文 model_id 动态选模型（运行时切换）。

    每次模型调用（含主 agent 多轮）都经此换模型；context 缺省或
    model_id 为空时用默认模型。`request.override(model=...)` 仅替换
    本次调用的模型实例，agent 本体保持单例复用。

    注意：必须是 async 函数——项目走 astream_events（异步流式），
    wrap_model_call 装饰同步函数时只提供同步钩子，异步上下文会抛错
    （官方示例用同步 invoke，异步场景需 async 版本）。
    """
    model_id = None
    context = getattr(request.runtime, "context", None) if request.runtime else None
    if context is not None:
        model_id = getattr(context, "model_id", None)
    model = get_chat_model(model_id=model_id)
    return await handler(request.override(model=model))


# 会话级 Agent 缓存（v2.0 设计：CompositeBackend 会话隔离 + v3 有界 LRU）：
# 每会话（thread_id）一个编译图 + 独立 backend 文件根——废弃全局单例
# （多会话文件混存是 v1 硬缺陷，见 docs/decisions/CompositeBackend文件存储-设计-v3.md §2.1）
# v3.0 治理（深化方案 §2.3）：OrderedDict 有界 LRU——超限逐出最久未用会话，
# 只逐内存图不删磁盘文件（工作区文件由 DELETE 会话联动清理）；逐出经 popitem(last=False)。
_agents: "OrderedDict[str, object]" = OrderedDict()
_agents_lock = threading.Lock()  # 双重检查锁（会话维度）：防止并发首次构建重复建图
# 会话缓存上限（单机单用户场景 32 个并发会话足够；compile 是纯内存操作）
_AGENT_CACHE_MAX = 32

# Checkpointer（P0 断点持久化，2026-08-04）：
# ⚠️ 实测修正（评审方式 A 需适配 async）：sync SqliteSaver 在 async astream 下
# 静默失败（langgraph 3.x async 执行路径要求 AsyncSqliteSaver/aiosqlite）。
# 正确架构：AsyncSqliteSaver 由 **lifespan 管理生命周期**（与 Redis 连接池同模式）——
# main.py 启动时 await init_checkpointer()，关闭时 close_checkpointer()。
# 未初始化（测试/脚本未跑 lifespan）→ 构建不带 checkpointer，降级无断点模式。
_checkpointer: AsyncSqliteSaver | None = None

# 对话流并发限流（计划文档 C.1-2）：单机多浏览器并发对话同时断点落库
# 会触发 SQLite 写锁，Semaphore 限制同时执行的流数量，超出排队。
# 2026-08-10 拍板：硬编码 4 → settings.stream_concurrency（本地 .env.dev=10，
# 云端 .env.prod=2，环境保存可调）
_stream_semaphore = asyncio.Semaphore(settings.stream_concurrency)


async def init_checkpointer(db_path=None) -> None:
    """初始化断点持久化（lifespan 启动调用，幂等）。

    AsyncSqliteSaver + aiosqlite 连接（async 执行路径必需）：
    - WAL + busy_timeout=5000：缓解并发写锁（计划文档 C.1-1）
    - 连接生命周期跟随进程（与 core/redis.py 同模式）

    Args:
        db_path: 覆盖数据库路径（测试隔离用 tmp；缺省 data/checkpoints.db）
    """
    global _checkpointer
    if _checkpointer is not None:
        return
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    # ⚠️ 修复（2026-08-04 浏览器实测发现）：不能用 hasattr(__truediv__) 判断
    # 目录——Path 文件也有 __truediv__，会把 get_checkpointer_path() 的完整
    # 文件路径误拼成 .../checkpoints.db/checkpoints.db（unable to open）。
    # 正确判断：is_dir()（仅存在的目录为 True，如测试传 tmp_path）。
    target = db_path if db_path is not None else get_checkpointer_path()
    if db_path is not None and db_path.is_dir():
        target = db_path / CHECKPOINTER_DB_FILE
    conn = await aiosqlite.connect(str(target))
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    _checkpointer = AsyncSqliteSaver(conn)
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


# Store 长期记忆（P1，2026-08-04）：SqliteStore 持久化（评审选型拍板），
# 生命周期由 lifespan 管理（与 checkpointer 同模式）；未初始化 → 降级无记忆。
_store = None


def get_store():
    """当前 store 实例（记忆读写用）；未初始化返回 None。"""
    return _store


async def init_store(db_path=None) -> None:
    """初始化记忆存储（lifespan 启动调用，幂等）。

    ⚠️ 实测修正（同 Checkpointer 教训）：SqliteStore 不支持 async 方法
    （aput/asearch 抛 NotImplementedError），async 执行路径必须用
    AsyncSqliteStore（aiosqlite 连接）。
    """
    global _store
    if _store is not None:
        return
    import aiosqlite
    from langgraph.store.sqlite.aio import AsyncSqliteStore

    target = db_path if db_path is not None else get_store_path()
    if db_path is not None and db_path.is_dir():  # 传目录（tmp_path）→ 拼 store.db
        target = db_path / STORE_DB_FILE
    # isolation_level=None：autocommit 连接——AsyncSqliteStore 内部自行管理事务，
    # 默认 isolation 会触发 "cannot start a transaction within a transaction"
    conn = await aiosqlite.connect(str(target), isolation_level=None)
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    _store = AsyncSqliteStore(conn)
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
    # 工具 = 内部工具 + 外部 MCP 工具（lifespan 连接收集，见 src/mcp/client.py）
    # 沙箱域工具（P1 挂载：命令执行 + 文件同步，能力计划 §3.2/§3.3）
    internal_tools = [
        run_code_in_sandbox,
        run_command_in_sandbox,
        upload_workspace_file,
        download_sandbox_file,
        # 技能域（Skill 体系 P1）：技能脚本执行闭环（读文件→沙箱→执行一步封装）
        run_skill_script,
    ]
    mcp_tools = get_mcp_client_manager().get_tools()
    model = get_chat_model()  # 默认 provider 兜底（middleware 会覆盖）；P2 编译子代理共用
    middleware = [
        _configurable_model,
        # 上下文用量：图执行完自动算全量 messages token 并存库
        # （2026-08-04 评审改版：中间件替代 CallbackHandler，前端查表）
        TokenUsageMiddleware(),
        # 工具调用审计（P1）：MCP/沙箱逃逸面统一审计，只记不拦
        ToolAuditMiddleware(),
    ]
    # 解释器（P2，2026-08-05 解耦）：挂载逻辑在 middlewares/interpreter.py——
    # main_agent 只做编排，不内嵌中间件构建细节（顺序保持 ToolAudit 在前，
    # 本函数返回追加在后——eval 先经审计链）
    middleware += build_interpreter_middleware()
    # Rubric 自评（P1，2026-08-06 设计 §5.4）：rubric_enabled 门控构建——
    # 同解释器模式：main_agent 只编排，构建细节在 rubrics.py
    middleware += build_rubric_middleware()
    return create_deep_agent(
        model=model,
        system_prompt=build_system_prompt(),  # 分层组装（核心+可选；动态记忆由 chat 注入）
        # P2 子代理隔离：SUBAGENT_ISOLATION=True 时 loader 用同一 model 预编译子代理
        subagents=load_subagents(model=model if settings.subagent_isolation else None),
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
        # Checkpointer（P0 断点持久化）：AsyncSqliteSaver 由 lifespan
        # 初始化（init_checkpointer）；未初始化（测试/脚本）→ 不传，
        # 降级无断点模式。astream 必须带 thread_id（stream_agent_tokens
        # 内部封装），否则直接报错
        checkpointer=_checkpointer,
        # Store 长期记忆（P1）：SqliteStore 由 lifespan 初始化（init_store）；
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


async def stream_agent_events(
    agent,
    messages: list[BaseMessage],
    context: ChatContext | None = None,
    checkpoint_id: str | None = None,
) -> AsyncIterator[dict]:
    """事件流（引入方案 P0 校准版）：token + tool_call + subagent 三类事件。

    ⚠️ 实测校准（2026-08-05，方案 §6.2 风险项 2.3）：v3 messages 投影为
    message 粒度（整条消息，非逐 chunk），且本模型栈（OpenAI 兼容 adapter）
    无 content-block 协议支持——v3 直接出 token 会摧毁打字机效果。
    校准：单次 v2 事件流多事件分发——token 走 on_chat_model_stream（逐 chunk），
    tool_call 走 on_tool_start/on_tool_end，subagent 走 stream_subgraphs 子图链。
    v3 声明式投影保留为 examples/ 学习脚本（不接生产链路）。

    产出事件（SSE 协议 v3 对齐）：
      {"type": "token",     "text": ..., "id": 序号}
      {"type": "tool_call", "tool": ..., "status": "running|completed|error",
       "input": ..., "output": ..., "id": 序号}
      {"type": "subagent",  "name": ..., "status": "started|completed|failed",
       "depth": 0, "id": 序号}

    Args:
        agent: build_agent 的产物
        messages: LangChain 消息列表（含历史）；resume 模式传空列表
        context: 请求级上下文（session_id → thread_id config 封装）
        checkpoint_id: resume 模式从精确快照继续

    Yields:
        事件 dict（SSE 层据此分发）

    Raises:
        Exception: checkpoint_id 无效/不属于该 thread（API 层转 RESUME_NOT_FOUND）
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

    seq = 0
    async with _stream_semaphore:  # 并发限流：SQLite 写锁缓解
        async for evt in agent.astream_events(
            {"messages": messages}, version="v2", context=context, config=config
        ):
            event_type = evt.get("event")
            if event_type == "on_chat_model_stream":
                chunk = evt.get("data", {}).get("chunk")
                text = getattr(chunk, "text", None) if chunk is not None else None
                if text:
                    seq += 1
                    yield {"type": "token", "text": text, "id": seq}
            elif event_type == "on_tool_start":
                seq += 1
                yield {
                    "type": "tool_call",
                    "tool": evt.get("name", ""),
                    "status": "running",
                    "input": _truncate(str(evt.get("data", {}).get("input", ""))),
                    "output": None,
                    "id": seq,
                }
            elif event_type == "on_tool_end":
                seq += 1
                yield {
                    "type": "tool_call",
                    "tool": evt.get("name", ""),
                    "status": "completed",
                    "input": "",
                    "output": _truncate(str(evt.get("data", {}).get("output", ""))),
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
                seq += 1
                yield {
                    "type": "subagent",
                    "name": evt["metadata"]["lc_agent_name"],
                    "status": "started" if event_type == "on_chain_start" else "completed",
                    "depth": 0,
                    "id": seq,
                }


def _truncate(text: str, limit: int = 300) -> str:
    """事件字段截断（密钥纪律 + 防上下文膨胀；同 ToolAudit 脱敏口径）。"""
    if len(text) > limit:
        return text[:limit] + "…"
    return text


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

    async with _stream_semaphore:  # 并发限流：SQLite 写锁缓解
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
