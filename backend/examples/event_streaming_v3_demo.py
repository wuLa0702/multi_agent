"""学习 Demo：v3 声明式投影消费（引入方案学习点 P0）。

思维方式：不手写 `if evt.get("event") != ...` 事件过滤，按投影声明式消费
（stream.messages / stream.tool_calls / stream.subagents 独立句柄）。

⚠️ 实测结论（2026-08-05）：v3 messages 投影为 **message 粒度**（整条消息），
且本模型栈无 content-block 协议——生产链路 token 仍走 v2 chunk 流
（main_agent.stream_agent_events 已校准）。本脚本仅演示 v3 API 形态。

运行（backend/ 下）：
    python examples/event_streaming_v3_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deepagents import create_deep_agent  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from conftest import FakeDeepAgentModel  # noqa: E402


async def main() -> None:
    """v3 投影消费最小演示：messages / tool_calls / subagents 三投影独立迭代。"""
    model = FakeDeepAgentModel(responses=["你好，这是 v3 投影演示"])
    agent = create_deep_agent(model=model, system_prompt="演示")

    stream = await agent.astream_events(
        {"messages": [{"role": "user", "content": "hi"}]}, version="v3"
    )
    print("== stream 投影属性 ==")
    print([a for a in dir(stream) if not a.startswith("_")])

    print("\n== messages 投影（注意：message 粒度，非逐 token）==")
    async for message in stream.messages:
        print("  text:", await message.text)

    print("\n== tool_calls / subagents（Fake 模型无工具调用/子代理 → 空）==")
    print("  tool_calls:", len([c async for c in stream.tool_calls]))
    print("  subagents:", len([s async for s in stream.subagents]))


if __name__ == "__main__":
    asyncio.run(main())
