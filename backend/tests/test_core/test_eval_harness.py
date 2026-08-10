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
    CITATION_RE,
    build_report,
    count_compliant_citations,
    extract_sources,
    parse_judge_output,
    render_markdown,
    verify_source_url,
)
from src.core.paths import get_eval_assets_dir  # noqa: E402


# ── A1 引用编号合规率 ──
class TestCountCompliantCitations:
    def test_normal(self) -> None:
        """编号都在范围内 → 全合规。"""
        report = "模型参数 [1] 为 7B，上下文 [2] 128k。"
        assert count_compliant_citations(report, ["u1", "u2"]) == (2, 2)

    def test_out_of_range(self) -> None:
        """编号越界 → 不合规（编号在范围内 ≠ 内容对应，P0 只查合规）。"""
        report = "见来源 [5]。"
        assert count_compliant_citations(report, ["u1", "u2"]) == (0, 1)

    def test_no_citation(self) -> None:
        """无引用标注 → (0, 0)。"""
        assert count_compliant_citations("无引用的报告", ["u1"]) == (0, 0)

    def test_duplicate_refs_deduped(self) -> None:
        """重复引用同一编号 → 去重后计 1。"""
        report = "A [1] B [1] C [1]。"
        assert count_compliant_citations(report, ["u1"]) == (1, 1)

    def test_full_width_brackets(self) -> None:
        """全角括号【1】同样识别。"""
        report = "见【1】。"
        assert count_compliant_citations(report, ["u1"]) == (1, 1)


# ── 来源 URL 提取 ──
class TestExtractSources:
    def test_normal(self) -> None:
        text = "来源：[https://a.com/1](链接)、https://b.com/x。"
        assert extract_sources(text) == ["https://a.com/1", "https://b.com/x"]

    def test_dedup_preserve_order(self) -> None:
        assert extract_sources("https://a.com https://b.com https://a.com") == [
            "https://a.com",
            "https://b.com",
        ]

    def test_strip_trailing_punct(self) -> None:
        assert extract_sources("见 https://a.com。") == ["https://a.com"]

    def test_empty(self) -> None:
        assert extract_sources("无链接") == []


# ── A2 来源可达性（mock httpx）──
class TestVerifySourceUrl:
    @pytest.mark.asyncio
    async def test_reachable(self) -> None:
        """2xx → reachable。"""

        class FakeResp:
            status_code = 200

        client = _FakeClient(FakeResp())
        assert await verify_source_url(client, "https://a.com") == "reachable"

    @pytest.mark.asyncio
    async def test_unreachable_status(self) -> None:
        """4xx/5xx → unreachable。"""

        class FakeResp:
            status_code = 404

        client = _FakeClient(FakeResp())
        assert await verify_source_url(client, "https://a.com") == "unreachable"

    @pytest.mark.asyncio
    async def test_timeout_unreachable(self) -> None:
        """超时 → unreachable。"""
        client = _FakeClient(httpx_timeout=True)
        assert await verify_source_url(client, "https://a.com") == "unreachable"

    @pytest.mark.asyncio
    async def test_network_error_unknown(self) -> None:
        """其他网络异常（DNS/SSL）→ unknown，不计入统计。"""
        client = _FakeClient(httpx_error=True)
        assert await verify_source_url(client, "https://a.com") == "unknown"


class _FakeClient:
    """最小 httpx 客户端替身（仅测 verify_source_url 分支）。"""

    def __init__(self, resp=None, httpx_timeout: bool = False, httpx_error: bool = False) -> None:
        self._resp = resp
        self._timeout = httpx_timeout
        self._error = httpx_error

    async def get(self, url: str, timeout=None, follow_redirects: bool = False):
        if self._error:
            raise ConnectionError("DNS failed")
        if self._timeout:
            import httpx

            raise httpx.TimeoutException("timeout")
        return self._resp


# ── B 类 judge 输出解析 ──
class TestParseJudgeOutput:
    def test_normal(self) -> None:
        assert parse_judge_output("完整度: 4\n可靠性: 3\n") == (4.0, 3.0)

    def test_missing_line(self) -> None:
        """缺一行 → (0, 0)（调用侧记 errors）。"""
        assert parse_judge_output("完整度: 4\n") == (0.0, 0.0)

    def test_garbage(self) -> None:
        """乱码输出 → (0, 0)。"""
        assert parse_judge_output("随便说点什么") == (0.0, 0.0)

    def test_out_of_range(self) -> None:
        """分数超出 1-5 → 不匹配 → (0, 0)。"""
        assert parse_judge_output("完整度: 9\n可靠性: 5\n") == (0.0, 0.0)


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


def test_citation_re_pattern_sanity() -> None:
    """引用正则覆盖中英文括号。"""
    assert CITATION_RE.findall("a[1]b【2】c") == ["1", "2"]


def test_task_metrics_a1_assignment_order() -> None:
    """回归：count_compliant_citations 解包赋值顺序（2026-08-10 字段互换事故）。

    曾写反（citations_total 先收）导致 a1_ratio 可 >1（task-005 38/35 幻觉）；
    若再写反，本用例 a1_ratio() 会断言失败。
    """
    from eval_harness import TaskMetrics

    m = TaskMetrics(task_id="t")
    # 模拟 run_one_task 的真实解包模式：(compliant, total) = count(...)
    m.citations_compliant, m.citations_total = count_compliant_citations(
        "a[1] b[2] c[3]", ["u1", "u2"]
    )
    assert m.citations_compliant == 2  # 合规 2 条（[1][2] 在范围内）
    assert m.citations_total == 3  # 引用共 3 条
    assert m.a1_ratio() == pytest.approx(2 / 3)
