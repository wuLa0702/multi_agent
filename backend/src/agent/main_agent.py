"""主 Agent：deepagents 对话编排（搜索子代理 + OpenSandbox 沙箱工具）。

能力布局（蓝图 §4，与 agent_demo.py 同源）：
- 业务工具定义：src/mcp/tools/ 按域分包（search.py 搜索域 / sandbox_tool.py 沙箱域），
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

import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass

from deepagents import create_deep_agent
from langchain.agents.middleware import wrap_model_call
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from src.agent.subagents.loader import load_subagents
from src.llm.adapter import get_chat_model
from src.mcp.tools.sandbox_tool import run_code_in_sandbox

DEFAULT_SYSTEM_PROMPT = """你是一名资深研究员，负责开展深入调研，并输出一份精炼的研究报告。

你有搜索子代理（search_agent）可委派联网搜索任务，获取最新资料后再撰写报告。

## `search_agent`

将搜索请求交给它，它会返回结构化搜索结果（标题/链接/摘要）。

## `run_code_in_sandbox`

在隔离沙箱中执行 Python 代码并返回输出（适合跑测试/验证脚本，不影响本地环境）。
"""


@dataclass
class ChatContext:
    """请求级运行时上下文（context_schema）：携带模型选择。

    Attributes:
        model_id: 数据库模型 ID（providers/models 表，GET /v1/providers
            返回）；None → 默认模型（settings.llm_provider 厂商的默认模型）
    """

    model_id: int | None = None


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


# 模块级单例：编译图无状态（无 checkpointer），进程内只构建一次
_agent = None
_agent_lock = threading.Lock()


def get_agent():
    """线程安全懒加载单例：deepagents 编译图（首次调用时构建一次）。

    构建仅做内存图装配（无网络 I/O）；模型每次调用经
    _configurable_model middleware 按 ChatContext.provider 动态选择，
    单例本身不绑定具体 provider。
    """
    global _agent
    if _agent is None:
        with _agent_lock:
            if _agent is None:
                _agent = create_deep_agent(
                    model=get_chat_model(),  # 默认 provider 兜底（middleware 会覆盖）
                    system_prompt=DEFAULT_SYSTEM_PROMPT,
                    subagents=load_subagents(),
                    tools=[run_code_in_sandbox],
                    middleware=[_configurable_model],
                    context_schema=ChatContext,
                )
    return _agent


def build_agent(model: BaseChatModel | None = None):
    """获取主 Agent（历史签名兼容：model 参数已弃用，走进程单例）。

    Args:
        model: 兼容旧调用方；单例模式下忽略（模型经 middleware 运行时选择）

    Returns:
        deepagents 编译后的 Agent（LangGraph CompiledStateGraph）
    """
    return get_agent()


async def stream_agent_tokens(
    agent, messages: list[BaseMessage], context: ChatContext | None = None
) -> AsyncIterator[str]:
    """流式执行 Agent，产出对话文本增量。

    实现：astream_events v2 监听 on_chat_model_stream，只取文本 chunk
    （工具调用 chunk 的 text 为空，天然过滤；deepagents 内部 todo 工具
    参数走 tool_call_chunks，不会误发成 token 事件）。

    Args:
        agent: build_agent 的产物
        messages: LangChain 消息列表（含历史，按时间正序）
        context: 请求级上下文（provider 选择）；None → 默认 provider

    Yields:
        模型生成文本增量（每片非空）
    """
    async for evt in agent.astream_events(
        {"messages": messages}, version="v2", context=context
    ):
        if evt.get("event") != "on_chat_model_stream":
            continue
        chunk = evt.get("data", {}).get("chunk")
        if chunk is None:
            continue
        text = getattr(chunk, "text", None)
        if text:
            yield text
