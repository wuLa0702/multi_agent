"""面试演示脚本（计划 3，2026-08-11）：5 分钟展示多 Agent 研究全流程。

两种模式：
1. 现场（默认）：POST /v1/chat/stream 真实跑一个研究任务，流式展示
   token 流 / 工具调用 / 子代理启停 / done 指标——面试现场真跑
2. 回放（--replay FILE）：重放预存的 SSE 事件文件（兜底——现场
   LLM 慢/网络不稳时切换，不尴尬）

展示口径（面试剧本见 docs/学习/2026-08-11-学习-demo演示剧本-v1.md）：
- 哪个 Agent 在干活（subagent 事件）
- 用了什么工具（tool_call 事件）
- 花了多少钱（done 的 context_used + 本地价格估算）
- 产出什么（token 流聚合 + 引用合规展示）

用法：
    python scripts/demo_interview.py                          # 现场跑默认任务（task-003）
    python scripts/demo_interview.py --query "调研 XX 并产出研报"  # 自定义任务
    python scripts/demo_interview.py --replay demo_trace.jsonl   # 回放兜底
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

# sys.path 引导（与 eval_harness 同约定）：backend/ 加入路径
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.paths import get_eval_assets_dir  # noqa: E402

# 展示用价格估算（deepseek-v4-flash 目录价，元/百万 token；仅演示口径）
_PRICE_PER_MTOKEN = 2.0
_DEFAULT_TASK = get_eval_assets_dir() / "tasks.jsonl"

# 终端着色（演示可读性）
_CYAN, _GREEN, _YELLOW, _RED, _RESET = "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"


def _print_tag(tag: str, text: str, color: str = "") -> None:
    """带标签打印（demo 展示口吻）。"""
    print(f"{color}▍{tag}{_RESET} {text}")


def run_live(api_base: str, message: str, session_id: str | None) -> None:
    """现场模式：POST /v1/chat/stream 流式展示。"""
    payload: dict = {"message": message}
    if session_id:
        payload["session_id"] = session_id

    _print_tag("任务", message, _CYAN)
    started = time.time()
    tool_count = 0
    subagent_count = 0
    tokens = 0

    with httpx.stream(
        "POST",
        f"{api_base}/v1/chat/stream",
        json=payload,
        timeout=httpx.Timeout(600.0, connect=15.0),
    ) as resp:
        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                evt = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            etype = evt.get("type")
            if etype == "start":
                _print_tag("开始", f"run_id={evt['run_id']} session={evt['session_id']}", _GREEN)
            elif etype == "token":
                tokens += 1
                print(evt.get("text", ""), end="", flush=True)
            elif etype == "tool_call":
                tool_count += 1
                print()
                _print_tag(
                    f"工具 {tool_count}",
                    f"{evt.get('tool')} [{evt.get('status')}]",
                    _YELLOW,
                )
            elif etype == "subagent":
                subagent_count += 1
                print()
                _print_tag(
                    f"子代理 {subagent_count}",
                    f"{evt.get('name')} [{evt.get('status')}]",
                    _CYAN,
                )
            elif etype == "done":
                elapsed = time.time() - started
                cost = (evt.get("context_used") or 0) / 1_000_000 * _PRICE_PER_MTOKEN
                print()
                print()
                _print_tag("完成", f"耗时 {elapsed:.0f}s · token {evt.get('context_used')} · "
                                   f"估算成本 ¥{cost:.3f} · 工具 {tool_count} 次 · 子代理 {subagent_count} 次", _GREEN)
            elif etype == "error":
                print()
                _print_tag("错误", f"{evt.get('detail')}", _RED)


def replay(trace_file: Path) -> None:
    """回放模式：重放预存 SSE 事件文件（兜底，不依赖现场 LLM）。

    Args:
        trace_file: SSE 事件 JSONL（demo_trace 目录，`data: {...}` 行或裸 JSON 行）
    """
    _print_tag("回放", f"{trace_file}", _CYAN)
    lines = trace_file.read_text(encoding="utf-8").splitlines()
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        if raw.startswith("data: "):
            raw = raw[6:]
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            continue
        etype = evt.get("type")
        if etype == "token":
            print(evt.get("text", ""), end="", flush=True)
        elif etype in ("tool_call", "subagent", "start", "done", "error"):
            print()
            _print_tag(etype, json.dumps(evt, ensure_ascii=False)[:120], _YELLOW)


def main() -> None:
    """CLI 入口：--query / --session-id / --api-base / --replay。"""
    parser = argparse.ArgumentParser(description="多 Agent 面试演示脚本")
    parser.add_argument("--query", default="", help="演示任务 query（缺省取 task-003）")
    parser.add_argument("--session-id", default=None, help="复用已有会话（缺省自动新建）")
    parser.add_argument("--api-base", default="http://127.0.0.1:8010")
    parser.add_argument("--replay", type=Path, default=None, help="回放模式：预存 SSE 事件文件")
    args = parser.parse_args()

    if args.replay is not None:
        replay(args.replay)
        return

    query = args.query
    if not query:
        # 缺省演示任务：task-003（MCP 生态——历史 4.0 满分样本，输出稳定）
        for line in _DEFAULT_TASK.read_text(encoding="utf-8").splitlines():
            task = json.loads(line)
            if task["id"] == "task-003":
                query = task["query"]
                break
    if not query:
        raise SystemExit("未找到演示任务（assets/eval/tasks.jsonl）")
    run_live(args.api_base, query, args.session_id)


if __name__ == "__main__":
    main()
