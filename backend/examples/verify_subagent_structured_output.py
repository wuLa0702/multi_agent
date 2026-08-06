"""P1-2 前置验证：response_format 在国产模型（OpenAI 兼容）上的实际行为。

验证背景：docs/学习/子代理-官方能力对比与差距分析-v1.md §5.2 风险——
国产模型大概率不支持 provider 原生 structured output，需实测确认默认
策略与显式 ToolStrategy 的实际行为后再正式开发。

📌 2026-08-06 实测结论（deepseek-v4-flash / doubao-seed-evolving）：
  - 官方 response_format 三条策略（裸 schema→AutoStrategy / ToolStrategy /
    ProviderStrategy）在国产模型上**全部 400**：
      · ToolStrategy 路径：langchain factory.py:1388 强制 tool_choice="any"，
        国产模型拒绝（deepseek 序列化错误 / doubao InvalidParameter /
        思考模式拒绝 tool_choice="required"）
      · ProviderStrategy 路径：deepseek "This response_format type is
        unavailable now"
  - ✅ 唯一可用形态：调用层直传 response_format={"type": "json_object"}
    （DeepSeek 原生兼容 OpenAI JSON mode；无 schema 保证，仅保证是 JSON）
  - 结论：P1-2 不按官方 response_format 落地；降级方案 = prompt 约束
    JSON 输出 + 父 agent 容错解析（详见差距分析 §5.2 / §7.4）

本脚本保留为可复跑的最小验证（三态 + tool_choice 矩阵 + json_object）。

用法（backend/ 下）：
  python -m examples.verify_subagent_structured_output
  或 .venv\\Scripts\\python.exe examples\\verify_subagent_structured_output.py

安全：只读 .env.dev；密钥只判断存在与否，绝不打印。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # 日志规范 04：统一 UTF-8 输出

from pydantic import BaseModel, Field  # noqa: E402


class DemoResult(BaseModel):
    """最小验证 schema：summary + score。"""

    summary: str = Field(description="一句话摘要")
    score: float = Field(description="0~1 置信度")


def _load_env_dev() -> dict[str, str]:
    """读取 backend 上级 .env.dev（只读，不打印密钥值）。"""
    env_file = Path(__file__).resolve().parents[2] / ".env.dev"
    env: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


async def _run_case(label: str, model, response_format) -> None:
    """单态验证：create_agent + 一次 ainvoke，报告结果与 JSON 可用性。"""
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage

    print(f"\n=== {label} ===")
    try:
        agent = create_agent(model=model, tools=[], response_format=response_format)
    except Exception as exc:  # 构建期报错也是有效结论
        print(f"  [构建失败] {type(exc).__name__}: {exc}")
        return
    try:
        resp = await agent.ainvoke(
            {"messages": [HumanMessage("用一句话总结：Python 的 GIL 是什么？给个置信度。")]}
        )
        content = str(resp["messages"][-1].content)
        print(f"  [回复] {content[:200]}")
        # 尝试按 schema 解析（ToolStrategy 应返回合法 JSON）
        try:
            parsed = DemoResult.model_validate_json(content)
            print(f"  [解析] ✅ JSON 合法：summary={parsed.summary[:30]!r} score={parsed.score}")
        except Exception as exc:
            print(f"  [解析] ❌ 非合法 JSON：{type(exc).__name__}")
    except Exception as exc:
        print(f"  [调用失败] {type(exc).__name__}: {str(exc)[:300]}")


async def _probe_tool_choice(model, tools: list[dict]) -> None:
    """tool_choice 矩阵探针：any / required / None（定位根因）。"""
    print("\n=== tool_choice 矩阵（定位 ToolStrategy 根因）===")
    for choice in ("any", "required", None):
        try:
            resp = await model.ainvoke(
                "用一句话总结：Python 的 GIL 是什么？", tools=tools, tool_choice=choice
            )
            print(f"  tool_choice={choice!r} → ✅ tool_calls={len(resp.tool_calls)}")
        except Exception as exc:
            print(f"  tool_choice={choice!r} → ❌ {type(exc).__name__}: {str(exc).splitlines()[0][:110]}")


async def _probe_json_object(model) -> None:
    """json_object 直连探针（DeepSeek 原生 JSON mode 兼容性）。"""
    print("\n=== response_format=json_object 直连 ===")
    try:
        resp = await model.ainvoke(
            "返回 JSON：{\"summary\": \"一句话\", \"score\": 0.9}",
            response_format={"type": "json_object"},
        )
        print(f"  → ✅ {str(resp.content)[:80]}")
    except Exception as exc:
        print(f"  → ❌ {type(exc).__name__}: {str(exc).splitlines()[0][:110]}")


async def main() -> None:
    env = _load_env_dev()
    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        if not env.get(key):
            raise SystemExit(f".env.dev 缺 {key}，无法验证（当前仅支持 deepseek 验证）")

    from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model=env["DEEPSEEK_MODEL"],
        api_key=env["DEEPSEEK_API_KEY"],
        base_url=env["DEEPSEEK_BASE_URL"],
        temperature=0.0,
        timeout=30,
        max_retries=1,
    )
    print(f"验证模型：{env['DEEPSEEK_MODEL']}（key 存在={bool(env['DEEPSEEK_API_KEY'])}）")
    print(f"model.profile = {model.profile}（None → AutoStrategy 决议为 ToolStrategy）")

    await _run_case("① 裸 schema（AutoStrategy 默认路径）", model, DemoResult)
    await _run_case("② 显式 ToolStrategy", model, ToolStrategy(schema=DemoResult))
    await _run_case("③ 显式 ProviderStrategy", model, ProviderStrategy(schema=DemoResult))

    probe_tools = [{
        "type": "function",
        "function": {
            "name": "structured_out",
            "description": "返回 JSON",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    }]
    await _probe_tool_choice(model, probe_tools)
    await _probe_json_object(model)


if __name__ == "__main__":
    asyncio.run(main())
