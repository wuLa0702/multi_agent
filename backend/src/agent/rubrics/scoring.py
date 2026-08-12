"""研报质量评分执行层（2026-08-11 抽取：评分规则从 eval_harness 收口为领域能力）。

背景：评分规则原内嵌 `scripts/eval_harness.py`（工具脚本），不合适——评分是
"产出物怎么打分"的领域能力，应一处定义、多方复用：
- 离线评估（eval_harness）调用
- 运行时 Rubric 自评（RubricMiddleware，rubric_enabled 打开后）复用同一套标准
- 行业调研产出自评打分（后续场景）复用

本模块 = 评分执行层：
- A 类规则指标：引用编号合规率 / 来源可达率（确定性计算）
- B 类质量分：LLM-as-judge（复用 rubrics.py RUBRIC_TEMPLATES + 纯文本解析，
  规避国产模型 response_format 三态全挂——P1-2 实证教训）
"""

from __future__ import annotations

import re
from html import unescape

import httpx

from src.agent.rubrics.rubrics import RUBRIC_TEMPLATES
from src.llm.adapter import get_chat_model

# ── A 类规则指标：引用编号合规率（只查合规，不做语义匹配）──
CITATION_RE = re.compile(r"[\[【](\d{1,2})[\]】]")  # 研报中 [1] 式引用标注
URL_RE = re.compile(r"https?://[^\s)\]\"'<>]+")  # 来源 URL 提取
SOURCE_SAMPLE_SIZE = 5  # A2 来源抽查上限
MAX_REPORT_CHARS = 4000  # judge 输入截断（长报告防上下文爆）


def count_compliant_citations(report_text: str, sources: list[str]) -> tuple[int, int]:
    """统计合规引用数：引用标注编号是否在 sources 列表范围内。

    ⚠️ 范围合规 ≠ 内容对应：sources 有 5 条、报告引 [3]，编号合规但第 3 条
    来源可能与引用内容无关——P1 升级为 LLM 语义匹配抽查。

    Args:
        report_text: 研报全文
        sources: 来源 URL 列表（从报告文末提取）

    Returns:
        (compliant, total) 引用编号合规率 = compliant / total
    """
    refs = {int(m) for m in CITATION_RE.findall(report_text)}
    if not refs:
        return 0, 0
    compliant = sum(1 for r in refs if 1 <= r <= len(sources))
    return compliant, len(refs)


def extract_sources(report_text: str) -> list[str]:
    """从报告文末提取来源 URL 列表（去重保序）。

    Args:
        report_text: 研报全文

    Returns:
        URL 列表（去重，保持出现顺序）
    """
    seen: list[str] = []
    for url in URL_RE.findall(report_text):
        url = url.rstrip(".,;:，。；：")
        if url not in seen:
            seen.append(url)
    return seen


async def verify_source_url(client: httpx.AsyncClient, url: str) -> str:
    """检查来源 URL 是否可访问（HTTP 可达性——LLM 不联网无法验 URL）。

    Args:
        client: 复用连接池的 httpx 客户端
        url: 来源 URL

    Returns:
        "reachable"（2xx/3xx）/ "unreachable"（超时/4xx/5xx）/ "unknown"（网络异常，不计入统计）
    """
    try:
        resp = await client.get(url, timeout=10.0, follow_redirects=True)
        return "reachable" if resp.status_code < 400 else "unreachable"
    except (httpx.TimeoutException, httpx.NetworkError):
        return "unreachable"
    except Exception:  # noqa: BLE001 - DNS/SSL 等网络异常统一记 unknown，不污染统计
        return "unknown"


# ── B 类：LLM-as-judge（纯文本 + 规则解析，规避 response_format 三态全挂）──
JUDGE_PROMPT_TEMPLATE = """你是研报质量评估员。对以下研报按两个维度打分（1-5 分，整数），
只输出两行，格式严格如下：
完整度: <1-5>
可靠性: <1-5>

评分标准：
- 完整度：{completeness_rubric}
- 可靠性：{veracity_rubric}

研报内容：
{report}
"""


def parse_judge_output(text: str) -> tuple[float, float]:
    """解析 judge 纯文本输出为 (completeness, veracity)。失败 → (0.0, 0.0)。

    坑（P1-2 实证）：国产模型 response_format 三态全挂 → judge 输出不强制 JSON，
    用正则解析；解析失败降级为 0 分（调用侧记入 errors）。
    """
    m_c = re.search(r"完整度:\s*([1-5])", text)
    m_v = re.search(r"可靠性:\s*([1-5])", text)
    if not (m_c and m_v):
        return 0.0, 0.0
    return float(m_c.group(1)), float(m_v.group(1))


async def judge_report(report_text: str, model_id: int | None = None) -> tuple[float, float, str]:
    """LLM-as-judge 盲评：复用 rubrics.py 模板打分（B1/B2）。

    Args:
        report_text: 研报全文（截断后送入）
        model_id: judge 模型 ID（None → 默认主模型；建议异 provider 消风格偏好）

    Returns:
        (completeness, veracity, judge_text) 分数 + 原始输出（供解析失败排查）
    """
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        completeness_rubric=RUBRIC_TEMPLATES["report_completeness"],
        veracity_rubric=RUBRIC_TEMPLATES["source_veracity"],
        report=report_text[:MAX_REPORT_CHARS],
    )
    model = get_chat_model(model_id=model_id)
    judge_text = await model.ainvoke(prompt)  # type: ignore[union-attr]
    text = judge_text.content if hasattr(judge_text, "content") else str(judge_text)
    return (*parse_judge_output(text), text)


def clean_html(html: str, max_chars: int = 8000) -> str:
    """HTML → 纯文本（fetch_url 共用；去 script/style/标签 + 压缩空白 + 截断）。

    Args:
        html: 原始 HTML
        max_chars: 输出截断上限

    Returns:
        清洗后的纯文本（≤ max_chars 字符）
    """
    _tag_re = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>")
    text = _tag_re.sub(" ", html)
    text = unescape(text)
    text = re.compile(r"\s+").sub(" ", text).strip()
    return text[:max_chars]
