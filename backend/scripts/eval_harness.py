"""评估管道：多 Agent 研报质量评估（设计-评估体系-v1 §4，v1.2 无 single/multi 对照）。

用法：
    python scripts/eval_harness.py --tasks data/eval/tasks.jsonl
    python scripts/eval_harness.py --tasks data/eval/tasks.jsonl --concurrency 3
产出：data/eval/reports/{run_id}.json + .md（含 git_commit 版本指纹，支持纵向对比）

设计要点（docs/decisions/2026-08-10-设计-评估体系-v1.md）：
- 指标：A1 引用编号合规率 / A2 来源可达率（HTTP）/ C 过程 / D 成本（规则自动）
- B 类质量分：LLM-judge 盲评（复用 rubrics.py 模板 + 纯文本解析，规避国产模型
  response_format 三态全挂——P1-2 实证教训）
- 并发：信号量上限（默认 3，防限流）；失败自动重试 1 次
- 报告：git_commit 指纹 → 同任务集不同版本纵向对比（§5.2）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx  # 顶部导入（v1.1 评审修正：不做延迟导入）

# ── sys.path 引导（与 scripts/agent_demo.py 同约定）：backend/ 加入路径 ──
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent.rubrics.rubrics import RUBRIC_TEMPLATES  # noqa: E402 - sys.path 引导后导入
from src.core.paths import get_eval_assets_dir, get_eval_report_dir  # noqa: E402

# 评分规则（领域能力，2026-08-11 抽取 → src/agent/rubrics/scoring.py）：
# A 类规则指标（引用合规/来源可达）+ B 类 LLM-judge——eval_harness 只编排调用
from src.agent.rubrics.scoring import (  # noqa: E402
    MAX_REPORT_CHARS,
    count_compliant_citations,
    extract_sources,
    judge_report,
    verify_source_url,
)

logger = logging.getLogger(__name__)


@dataclass
class TaskMetrics:
    """单任务评估结果（设计 §2 四类指标）。"""

    task_id: str
    completed: bool = False            # C1
    tool_calls: int = 0
    tool_success: int = 0              # C2 = tool_success / tool_calls
    duration_ms: int = 0               # D1
    context_used: int = 0              # D2
    citations_total: int = 0
    citations_compliant: int = 0       # A1 = compliant / total
    sources_checked: int = 0
    sources_reachable: int = 0         # A2 = reachable / checked
    completeness_score: float = 0.0    # B1（LLM-judge 1-5，盲评）
    veracity_score: float = 0.0        # B2
    errors: list[str] = field(default_factory=list)

    def a1_ratio(self) -> float:
        """引用编号合规率（§2 A1——只查编号格式+范围，P1 升级语义匹配）。"""
        return self.citations_compliant / self.citations_total if self.citations_total else 0.0

    def a2_ratio(self) -> float:
        """来源可达率（§2 A2——HTTP 可达性，unknown 不计入分母）。"""
        return self.sources_reachable / self.sources_checked if self.sources_checked else 0.0


# ── 单任务执行（复用 chat SSE 契约，mock 不适用——eval 走真实链路）──
async def collect_stream(
    client: httpx.AsyncClient, api_base: str, message: str
) -> tuple[str, int, int, int]:
    """调用 /v1/chat/stream 收集完整流（token 拼接 + 工具调用计数 + done 元数据）。

    Args:
        client: 共享 httpx 客户端
        api_base: 后端地址
        message: 任务 query

    Returns:
        (report_text, tool_calls, duration_ms, context_used)

    Raises:
        RuntimeError: error 事件 / 非 200 响应
    """
    report_chunks: list[str] = []
    tool_calls = 0
    duration_ms = 0
    context_used = 0
    async with client.stream(
        "POST",
        f"{api_base}/v1/chat/stream",
        json={"message": message},
        timeout=httpx.Timeout(300.0, connect=15.0),
    ) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"chat stream HTTP {resp.status_code}")
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "token":
                report_chunks.append(event.get("text", ""))
            elif etype == "tool_call":
                tool_calls += 1
            elif etype == "done":
                duration_ms = int(event.get("duration_ms") or 0)
                context_used = int(event.get("context_used") or 0)
            elif etype == "error":
                raise RuntimeError(f"SSE error event: {event.get('detail', event)}")
    return "".join(report_chunks), tool_calls, duration_ms, context_used


async def run_one_task(
    task: dict,
    api_base: str,
    semaphore: asyncio.Semaphore,
    client: httpx.AsyncClient,
    judge_model_id: int | None = None,
) -> TaskMetrics:
    """跑一个研究任务：chat 调用 → 收集产出 + trace → 算四类指标。

    失败自动重试 1 次（v1.1 评审修正：偶发错误不污染结果）。

    Args:
        task: tasks.jsonl 单条（id/query/expected_sections/...）
        api_base: 后端地址（默认 http://127.0.0.1:8010）
        semaphore: 并发信号量（默认 3，防限流/成本爆炸）
        client: 共享 httpx 客户端
        judge_model_id: judge 模型 ID（None → 默认）

    Returns:
        TaskMetrics：四类指标聚合
    """
    metrics = TaskMetrics(task_id=task["id"])
    async with semaphore:
        for attempt in (1, 2):
            try:
                report, tool_calls, duration_ms, context_used = await collect_stream(
                    client, api_base, task["query"]
                )
                metrics.tool_calls = tool_calls
                metrics.duration_ms = duration_ms
                metrics.context_used = context_used
                if not report.strip():
                    raise RuntimeError("empty report")
                # A1：引用编号合规率（sources = 文末提取的 URL 列表）
                # ⚠️ 解包顺序：count 返回 (compliant, total)——2026-08-10
                # 首跑曾写反（字段互换，task-005 出现 38/35 幻觉），回归测试见
                # test_task_metrics_a1_assignment_order
                sources = extract_sources(report)
                metrics.citations_compliant, metrics.citations_total = (
                    count_compliant_citations(report, sources)
                )
                # A2：来源可达性抽查（前 SOURCE_SAMPLE_SIZE 条）
                for url in sources[:SOURCE_SAMPLE_SIZE]:
                    status = await verify_source_url(client, url)
                    if status == "unknown":
                        continue
                    metrics.sources_checked += 1
                    if status == "reachable":
                        metrics.sources_reachable += 1
                # B1/B2：LLM-judge 盲评（judge 不接收任务配置标签）
                metrics.completeness_score, metrics.veracity_score, _ = await judge_report(
                    report, judge_model_id
                )
                metrics.completed = True
                break
            except Exception as exc:  # noqa: BLE001 - 网络/解析异常统一记 errors 重试
                metrics.errors.append(f"attempt{attempt}: {exc}")
    return metrics


# ── 汇总报告 ──
def build_report(run_id: str, git_commit: str, metrics_list: list[TaskMetrics]) -> dict:
    """聚合为报告 dict（写 reports/{run_id}.json + .md）。

    v1.2：固定多 Agent 配置（无 single/multi 对照）；记录 git_commit 版本指纹
    支持纵向对比（同配置优化前后两次评估对照）。

    Returns:
        报告 dict：run_id/git_commit/汇总 + 逐任务明细
    """
    n = len(metrics_list) or 1
    done = [m for m in metrics_list if m.completed]
    return {
        "run_id": run_id,
        "git_commit": git_commit,
        "config": "multi",  # 主线固定多 Agent（v1.2 拍板：不做 single 对照）
        "summary": {
            "tasks": len(metrics_list),
            "completion_rate": len(done) / n,
            "avg_citation_compliance": sum(m.a1_ratio() for m in metrics_list) / n,
            "avg_source_reachability": sum(m.a2_ratio() for m in metrics_list) / n,
            "avg_completeness": sum(m.completeness_score for m in metrics_list) / n,
            "avg_veracity": sum(m.veracity_score for m in metrics_list) / n,
            "avg_tool_calls": sum(m.tool_calls for m in metrics_list) / n,
            "total_duration_ms": sum(m.duration_ms for m in metrics_list),
            "total_context_used": sum(m.context_used for m in metrics_list),
        },
        "per_task": [m.__dict__ for m in metrics_list],
    }


def render_markdown(report: dict) -> str:
    """报告 dict → Markdown（.md 落盘，供人工阅读/纵向对比）。"""
    s = report["summary"]
    lines = [
        f"# 评估报告 {report['run_id']}（config={report['config']} @ {report['git_commit']}）",
        "",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| 任务数 | {s['tasks']} |",
        f"| 完成率 | {s['completion_rate']:.0%} |",
        f"| 引用编号合规率 | {s['avg_citation_compliance']:.1%} |",
        f"| 来源可达率 | {s['avg_source_reachability']:.1%} |",
        f"| 章节完整度 (1-5) | {s['avg_completeness']:.2f} |",
        f"| 来源可靠性 (1-5) | {s['avg_veracity']:.2f} |",
        f"| 平均工具调用 | {s['avg_tool_calls']:.1f} |",
        f"| 总耗时 (ms) | {s['total_duration_ms']} |",
        f"| 总 Token | {s['total_context_used']} |",
        "",
        "## 逐任务明细",
        "",
        "| 任务 | 完成 | 引用合规 | 来源可达 | 完整度 | 可靠性 | 工具调用 | 耗时ms |",
        "|------|------|----------|----------|--------|--------|----------|--------|",
    ]
    for m in report["per_task"]:
        a1 = m["citations_compliant"] / m["citations_total"] if m["citations_total"] else 0.0
        a2 = m["sources_reachable"] / m["sources_checked"] if m["sources_checked"] else 0.0
        lines.append(
            f"| {m['task_id']} | {'✅' if m['completed'] else '❌'} | "
            f"{a1:.0%} | {a2:.0%} | {m['completeness_score']} | "
            f"{m['veracity_score']} | {m['tool_calls']} | {m['duration_ms']} |"
        )
    return "\n".join(lines)


def get_git_commit() -> str:
    """取当前 HEAD 短哈希作为报告版本指纹（§5.2 纵向对比依据）。"""
    result = subprocess.run(  # noqa: S603 - 本地脚本取版本号
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or "unknown"


async def main() -> None:
    """CLI 入口：--tasks / --concurrency / --api-base（固定多 Agent 配置，v1.2）。"""
    parser = argparse.ArgumentParser(description="多 Agent 研报质量评估管道")
    parser.add_argument(
        "--tasks", type=Path, default=DEFAULT_TASKS,
        help=f"任务集 JSONL（缺省: assets/eval/tasks.jsonl）",
    )
    parser.add_argument(
        "--concurrency", type=int, default=5,
        help="并发上限（2026-08-10 评估实证：后端 Semaphore(10) 排队饱和，5 不浪费）",
    )
    parser.add_argument("--api-base", default="http://127.0.0.1:8010")
    parser.add_argument("--judge-model-id", type=int, default=None, help="judge 模型 ID（缺省默认主模型）")
    args = parser.parse_args()

    if not args.tasks.exists():
        raise SystemExit(f"任务集不存在: {args.tasks}")
    tasks = [
        json.loads(line)
        for line in args.tasks.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    run_id = uuid.uuid4().hex[:8]
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient() as client:
        metrics = await asyncio.gather(
            *(run_one_task(t, args.api_base, semaphore, client, args.judge_model_id) for t in tasks)
        )
    report = build_report(run_id, get_git_commit(), metrics)
    out_dir = get_eval_report_dir()
    (out_dir / f"{run_id}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / f"{run_id}.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"报告: {out_dir / run_id}")


if __name__ == "__main__":
    asyncio.run(main())
