"""eval_harness 纯函数单测（设计-评估体系-v1：A1/A2 规则 + judge 解析 + 报告聚合）。

纪律：LLM 全部 mock（20-testing）——本文件只测纯函数；真实链路（run_one_task）
属集成评估（P1-d 跑数），不在此 mock。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# eval_harness 在 backend/scripts/（非包），直接按路径加载
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from eval_harness import (  # noqa: E402 - 路径引导后导入
    build_report,
    render_markdown,
)
from src.core.paths import get_eval_assets_dir  # noqa: E402


# ── 报告聚合 ──
class TestBuildReport:
    def test_summary_math(self) -> None:
        """汇总正确：完成率/A1/B1 均值。"""
        m1 = _metric(task_id="t1", completed=True, citations_compliant=2, citations_total=4,
                     completeness_score=4.0, tool_calls=2, duration_ms=100)
        m2 = _metric(task_id="t2", completed=True, citations_compliant=0, citations_total=0,
                     completeness_score=2.0, tool_calls=4, duration_ms=300)
        m3 = _metric(task_id="t3", completed=False, errors=["fail"])
        report = build_report("run1", "abc123", [m1, m2, m3])
        s = report["summary"]
        assert s["completion_rate"] == pytest.approx(2 / 3)
        assert s["avg_citation_compliance"] == pytest.approx((0.5 + 0.0 + 0.0) / 3)
        assert s["avg_completeness"] == pytest.approx(2.0)
        assert s["total_duration_ms"] == 400
        assert report["git_commit"] == "abc123"
        assert report["config"] == "multi"  # v1.2：固定多 Agent

    def test_empty_metrics(self) -> None:
        """空任务集不除零崩溃。"""
        report = build_report("run0", "x", [])
        assert report["summary"]["completion_rate"] == 0.0

    def test_render_markdown_contains_rows(self) -> None:
        """Markdown 渲染含表头与任务行。"""
        report = build_report("run1", "abc123", [_metric(task_id="t1", completed=True)])
        md = render_markdown(report)
        assert "| 任务 |" in md
        assert "| t1 |" in md
        assert "abc123" in md


def _metric(
    task_id: str,
    completed: bool = False,
    citations_compliant: int = 0,
    citations_total: int = 0,
    sources_reachable: int = 0,
    sources_checked: int = 0,
    completeness_score: float = 0.0,
    veracity_score: float = 0.0,
    tool_calls: int = 0,
    duration_ms: int = 0,
    errors: list[str] | None = None,
):
    from eval_harness import TaskMetrics

    return TaskMetrics(
        task_id=task_id,
        completed=completed,
        citations_compliant=citations_compliant,
        citations_total=citations_total,
        sources_reachable=sources_reachable,
        sources_checked=sources_checked,
        completeness_score=completeness_score,
        veracity_score=veracity_score,
        tool_calls=tool_calls,
        duration_ms=duration_ms,
        errors=errors or [],
    )


def test_tasks_asset_exists() -> None:
    """任务集资产存在且 10 条格式合法（P0-a 防回归）。"""
    import json

    p = get_eval_assets_dir() / "tasks.jsonl"
    assert p.exists(), "评估任务集资产缺失"
    tasks = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(tasks) == 10
    assert all(t.get("id") and t.get("query") and t.get("difficulty") for t in tasks)
    assert all("来源编号" in t["query"] for t in tasks), "query 必须内置引用编号要求（A1 前提）"
    assert all("以联网搜索" in t["query"] for t in tasks), (
        "query 必须约束工具偏好（2026-08-10 跑偏修复：搜索为主，沙箱仅必要验证）"
    )
    assert all("禁止在沙箱内联网抓取" in t["query"] for t in tasks), (
        "query 必须禁止沙箱自写爬虫（2026-08-10 trace 定位：模型绕过搜索自写 curl/urllib 抓取循环 50 轮）"
    )
    assert all("最终回复必须直接输出" in t["query"] for t in tasks), (
        "query 必须明确交付形式（2026-08-10 trace 定位：模型反复编辑沙箱报告文件不输出文本，撞 recursion 50）"
    )
