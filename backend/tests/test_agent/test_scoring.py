"""评分执行层单测（2026-08-11 抽取：src/agent/rubrics/scoring.py）。

覆盖：A 类规则指标（引用合规/来源提取/URL 可达）+ B 类 judge 解析。
真实链路（judge_report 调 LLM）属集成评估，不在此 mock——本文件测纯函数。
"""

from __future__ import annotations

import httpx
import pytest

from src.agent.rubrics.scoring import (
    CITATION_RE,
    count_compliant_citations,
    extract_sources,
    parse_judge_output,
    verify_source_url,
)


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


def test_citation_re_pattern_sanity() -> None:
    """引用正则覆盖中英文括号。"""
    assert CITATION_RE.findall("a[1]b【2】c") == ["1", "2"]


def test_a1_assignment_order() -> None:
    """回归：count_compliant_citations 解包赋值顺序（2026-08-10 字段互换事故）。

    曾写反（citations_total 先收）导致 a1_ratio 可 >1（task-005 38/35 幻觉）；
    若再写反，本用例 a1_ratio() 会断言失败。
    """
    from src.agent.rubrics.scoring import count_compliant_citations as cnt

    compliant, total = cnt("a[1] b[2] c[3]", ["u1", "u2"])
    assert compliant == 2  # 合规 2 条（[1][2] 在范围内）
    assert total == 3  # 引用共 3 条
