"""deepagents 快速 Demo（项目标准版）：配置全部来自配置中心（.env.dev → src.core.config）。

结构（与生产 main_agent 同源，蓝图 §4）：
- 业务工具：src/mcp/tools/ 按域分包（search.py 搜索 / sandbox_tool.py 沙箱），
  注册进 src/mcp/registry.py——新增工具 = 注册表登记
- 声明式子代理：src/agent/subagents/*.yaml（loader.py 解析，tools 名查 registry）
- main()：先模拟调用一次 OpenSandbox（create → 写文件 → 执行 → 销毁，链路验证），
  再跑主 agent（研究员人设，与生产 main_agent 共用）编排调研报告 + 沙箱代码执行演示

运行（两种方式均可）：
    python backend/scripts/agent_demo.py      # 直接脚本（文件内自动引导 sys.path）
    cd backend && python scripts/agent_demo.py

密钥零硬编码：DEEPSEEK / BOCHA / SANDBOX / LangSmith 均从 .env.dev 读取，不进代码。
"""

import os
import sys
from pathlib import Path

from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver

# ── sys.path 引导：直接脚本运行（python agent_demo.py）时 sys.path[0] =
# 脚本所在目录（src/agent/），`src` 包不可解析，把 backend/ 显式加入；
# 模块方式（python -m src.agent.agent_demo）运行时 backend/ 已在路径上，此分支不生效。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deepagents import create_deep_agent

from src.agent.main_agent import DEFAULT_SYSTEM_PROMPT
from src.agent.subagents.loader import load_subagents
from src.core.config import settings
from src.llm.adapter import get_chat_model
from src.mcp.tools.sandbox_tool import run_code_in_sandbox
from src.sandbox.adapter import OpenSandboxAdapter

# ── LangSmith 链路追踪 ──
# .env.dev 的键只被 pydantic-settings 读取，不会自动注入 os.environ；
# langchain 的 tracing 读环境变量，故由配置中心读取后显式注入。
os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_API_KEY", settings.langchain_api_key)
os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)

# 沙箱适配器（惰性：import 不创建沙箱，调用时才连本地 docker / 云端）——
# 步骤 1 模拟调用用；agent 工具走 mcp/tools/sandbox_tool.py 的 run_code_in_sandbox
sandbox_adapter = OpenSandboxAdapter()


# ══════════════════════════════════════════════════════════════════════
# 预留能力（co-creator 添加，注释态待启用——最小化改动保留，勿删）
# ══════════════════════════════════════════════════════════════════════

# 日志中间件（deepagents wrap_tool_call，跨工具调用横切日志）
#
# import tool
# from langchain.agents.middleware import wrap_tool_call

# 天气组件（示例工具）
#
# @tool
# def get_weather(city: str) -> str:
#     """Get the weather in a city."""
#     return f"The weather in {city} is sunny."

# 工具调用日志中间件（启用时配合 wrap_tool_call）
#
# call_count = [0]  # Use list to allow modification in nested function
#
# @wrap_tool_call
# def log_tool_calls(request, handler):
#     """Intercept and log every tool call - demonstrates cross-cutting concern."""
#     call_count[0] += 1
#     tool_name = request.name if hasattr(request, "name") else str(request)
#
#     print(f"[Middleware] Tool call #{call_count[0]}: {tool_name}")
#     print(f"[Middleware] Arguments: {request.args if hasattr(request, 'args') else 'N/A'}")
#
#     # Execute the tool call
#     result = handler(request)
#
#     # Log the result
#     print(f"[Middleware] Tool call #{call_count[0]} completed")
#
#     return result


# ══════════════════════════════════════════════════════════════════════
# 主 agent 人设（真相源：src/agent/main_agent.py——生产与 demo 共用）
# ══════════════════════════════════════════════════════════════════════
# DEFAULT_SYSTEM_PROMPT：资深研究员，可委派搜索子代理 + 调用沙箱工具。

# Checkpointer is REQUIRED for human-in-the-loop
checkpointer = MemorySaver()
# FilesystemBackend 工作目录（demo 用，路径自适应 dev data/）：
# 项目根 data/agent_demo_ws（parents[2]=项目根，路径自适应）——agent 的写文件/读文件都限定在此目录，不碰项目其他文件
root_dir = Path(__file__).resolve().parents[2] / "data" / "agent_demo_ws"
root_dir.mkdir(parents=True, exist_ok=True)
(root_dir / "skills").mkdir(exist_ok=True)
backend = FilesystemBackend(root_dir=str(root_dir))


def main() -> None:
    """运行 demo：先模拟调用一次 OpenSandbox（链路验证），再跑主 agent 编排。

    步骤 1 为确定性沙箱链路验证（create → 写文件 → 执行 → 销毁，不依赖 LLM）；
    步骤 2 为 agent 编排演示（搜索子代理委派 + 沙箱代码执行工具）。
    """
    # Windows 控制台默认 GBK，UTF-8 内容（emoji/中文）print 会炸——统一 UTF-8 输出
    # （04-logging.md：入口处 reconfigure sys.stdout / sys.stderr）
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    # ── 1. 模拟调用一次 OpenSandbox（本地 docker，端口 8080）──
    print("═" * 64)
    print("步骤 1/2：模拟调用 OpenSandbox（create → 写文件 → 执行 → 销毁）")
    print("═" * 64)
    output = sandbox_adapter.run_code('print("Hello from OpenSandbox!")')
    print(f"[沙箱输出] {output}")

    # ── 2. 主 agent（研究员）编排：搜索子代理 + 沙箱执行工具 ──
    print("═" * 64)
    print("步骤 2/2：主 agent 编排（搜索子代理委派 + 沙箱代码执行）")
    print("═" * 64)
    # 统一入口（llm/adapter.py）：get_chat_model() 返回当前默认 provider（默认 deepseek）
    # 的 ChatOpenAI 实例——base_url / api_key / model / timeout / retry 全部封装
    agent = create_deep_agent(
        model=get_chat_model(),
        subagents=load_subagents(),
        tools=[run_code_in_sandbox],
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        memory=[
            "./AGENTS.md"
        ],
        interrupt_on={
            "write_file": True,  # Default: approve, edit, reject
            "read_file": False,  # No interrupts needed
            "edit_file": True,  # Default: approve, edit, reject
        },
        skills=[str(root_dir / "skills")],
        checkpointer=checkpointer,  # Required!
    )

    # Checkpointer（MemorySaver）要求 invoke 必带 config.thread_id（会话隔离键）
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "什么是 LangGraph？"}]},
        config={"configurable": {"thread_id": "demo-research"}},
    )
    print(result["messages"][-1].content)

    # 官网 demo 的代码执行场景：agent 通过 run_code_in_sandbox 在隔离沙箱中建包跑 pytest
    # （独立 thread_id：两个演示场景互不串历史）
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "用 run_code_in_sandbox 工具创建一个小的 Python 包并运行 pytest，把测试结果告诉我。",
                }
            ]
        },
        config={"configurable": {"thread_id": "demo-sandbox-code"}},
    )
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
