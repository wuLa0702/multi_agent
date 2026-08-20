"""intent 分类单测（简单直连快通道，方案 v2.1，2026-08-13）。"""

from src.agent.intent import classify_intent


def test_simple_concept():
    assert classify_intent("解释一下 LangGraph 工作原理") == "simple"
    assert classify_intent("什么是 ReAct") == "simple"
    assert classify_intent("为什么用多 Agent") == "simple"


def test_complex_research():
    assert classify_intent("调研 MCP 生态并生成研报") == "complex"
    assert classify_intent("今天北京天气怎么样") == "complex"  # 需搜索
    assert classify_intent("分析一下成本数据并写报告") == "complex"


def test_fallback_complex():
    # 无关键词 + 长问题 → 不确定走完整链路
    assert classify_intent("帮我想一个能够落地的多 Agent 学习路线，包含阶段划分和每个阶段的产出物，最好能持续三个月") == "complex"
    assert classify_intent("") == "complex"
