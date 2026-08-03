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
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from src.agent.subagents.loader import load_subagents
from src.mcp.tools.sandbox_tool import run_code_in_sandbox

DEFAULT_SYSTEM_PROMPT = """你是一名资深研究员，负责开展深入调研，并输出一份精炼的研究报告。

你有搜索子代理（search_agent）可委派联网搜索任务，获取最新资料后再撰写报告。

## `search_agent`

将搜索请求交给它，它会返回结构化搜索结果（标题/链接/摘要）。

## `run_code_in_sandbox`

在隔离沙箱中执行 Python 代码并返回输出（适合跑测试/验证脚本，不影响本地环境）。
"""


def build_agent(
    model: BaseChatModel,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
):
    """构建 deepagents 主 Agent（搜索子代理 + 沙箱执行工具）。

    子代理来自 agent/subagents/*.yaml（loader 解析），工具来自
    mcp/tools + registry——新增子代理 = 加 YAML，新增工具 = 注册表登记。

    注意：不配置 checkpointer——流式路径（astream_events）无 thread_id
    可传，提前配置会报错；resume 功能接入时再配（见模块 docstring）。

    Args:
        model: ChatOpenAI 实例（get_chat_model 工厂产出）
        system_prompt: 系统提示词

    Returns:
        deepagents 编译后的 Agent（LangGraph CompiledStateGraph）
    """
    return create_deep_agent(
        model=model,
        system_prompt=system_prompt,
        subagents=load_subagents(),
        tools=[run_code_in_sandbox],
    )


async def stream_agent_tokens(
    agent, messages: list[BaseMessage]
) -> AsyncIterator[str]:
    """流式执行 Agent，产出对话文本增量。

    实现：astream_events v2 监听 on_chat_model_stream，只取文本 chunk
    （工具调用 chunk 的 text 为空，天然过滤；deepagents 内部 todo 工具
    参数走 tool_call_chunks，不会误发成 token 事件）。

    Args:
        agent: build_agent 的产物
        messages: LangChain 消息列表（含历史，按时间正序）

    Yields:
        模型生成文本增量（每片非空）
    """
    async for evt in agent.astream_events({"messages": messages}, version="v2"):
        if evt.get("event") != "on_chat_model_stream":
            continue
        chunk = evt.get("data", {}).get("chunk")
        if chunk is None:
            continue
        text = getattr(chunk, "text", None)
        if text:
            yield text
