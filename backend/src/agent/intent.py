"""意图分类——简单直连快通道（方案 v2.1，2026-08-13）。

决定请求走「快通道」（简单概念题 → 主 LLM 单轮直答，不建 agent/不挂工具/不拆子代理）
还是「完整链路」（挂搜索/子代理/publish_report）。

兜底原则：**不确定就走完整链路**（规则只拦截"确定简单"的），避免误伤复杂问题。
"""

from __future__ import annotations

# 判简单：概念问答/解释类关键词
_SIMPLE_KEYWORDS = (
    "解释", "是什么", "什么是", "区别", "为什么", "定义", "简述", "介绍", "说一下", "讲讲",
    "怎么回事", "什么意思", "原理", "怎么理解", "讲讲看",
)
# 判复杂：研究/分析/生成类关键词（含事实查询——如"天气"需要搜索）
_COMPLEX_KEYWORDS = (
    "调研", "分析", "报告", "生成", "评估", "写论文", "整理", "研究",
    "天气", "搜索", "查一下", "最新", "对比.*优劣", "总结一下.*方面",
    "翻译", "代码", "执行", "运行",
)


def classify_intent(text: str) -> str:
    """判断请求意图：simple=快通道 / complex=完整链路。

    Args:
        text: 用户请求文本

    Returns:
        "simple" 或 "complex"（底层函数，按规范豁免）
    """
    text = (text or "").strip()
    if not text:
        return "complex"
    # 复杂信号优先（命中复杂词 → 完整链路，哪怕也像概念题）
    if any(k in text for k in _COMPLEX_KEYWORDS):
        return "complex"
    # 简单信号 + 短问题 → 快通道
    if any(k in text for k in _SIMPLE_KEYWORDS) and len(text) < 60:
        return "simple"
    # 兜底：不确定 → 完整链路
    return "complex"
