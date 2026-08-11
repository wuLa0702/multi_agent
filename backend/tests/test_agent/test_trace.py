"""推理层 trace 采集单测（阶段一，2026-08-10）。

覆盖 _format_trace_line 纯函数：模型调用 / 工具调用 / 子代理启停 / 忽略事件。
落盘侧（_trace_event → trace logger）由真实跑数验证（阶段二）。
"""

from __future__ import annotations

from src.agent.main_agent import _format_trace_line


class TestFormatTraceLine:
    def test_chat_model_start(self) -> None:
        """模型调用：首条消息摘要 + 条数。"""
        from langchain_core.messages import HumanMessage

        evt = {
            "event": "on_chat_model_start",
            "name": "ChatOpenAI",
            "run_id": "r1",
            "parent_ids": [],
            "data": {"input": [HumanMessage(content="请调研 DeepSeek 模型")]},
        }
        line = _format_trace_line("s1", evt)
        assert line["event"] == "on_chat_model_start"
        assert line["session_id"] == "s1"
        assert "messages=1" in line["summary"]
        assert "DeepSeek" in line["summary"]

    def test_chat_model_start_truncates_long_input(self) -> None:
        """模型输入超长 → 摘要截断（防上下文膨胀 + 密钥纪律）。"""
        from langchain_core.messages import HumanMessage

        evt = {
            "event": "on_chat_model_start",
            "name": "ChatOpenAI",
            "run_id": "r2",
            "parent_ids": [],
            "data": {"input": [HumanMessage(content="x" * 1000)]},
        }
        line = _format_trace_line(None, evt)
        assert "…" in line["summary"]
        assert len(line["summary"]) < 300

    def test_tool_start(self) -> None:
        """工具调用开始：工具名 + input 摘要。"""
        evt = {
            "event": "on_tool_start",
            "name": "internet_search",
            "run_id": "r3",
            "parent_ids": [],
            "data": {"input": {"query": "DeepSeek 模型"}},
        }
        line = _format_trace_line("s2", evt)
        assert line["event"] == "on_tool_start"
        assert line["name"] == "internet_search"
        assert "DeepSeek" in line["summary"]

    def test_tool_end(self) -> None:
        """工具调用结束：output 摘要。"""
        evt = {
            "event": "on_tool_end",
            "name": "internet_search",
            "run_id": "r4",
            "parent_ids": [],
            "data": {"output": "搜索结果标题…"},
        }
        line = _format_trace_line(None, evt)
        assert line["event"] == "on_tool_end"
        assert "搜索结果" in line["summary"]

    def test_subagent_start(self) -> None:
        """子代理启停（lc_agent_name 元数据）。"""
        evt = {
            "event": "on_chain_start",
            "name": "search_agent",
            "run_id": "r5",
            "parent_ids": ["root"],
            "metadata": {"lc_agent_name": "search_agent"},
        }
        line = _format_trace_line("s3", evt)
        assert line["event"] == "on_chain_start"
        assert "subagent_start" in line["summary"]
        assert line["parent_ids"] == ["root"]

    def test_ignored_event(self) -> None:
        """非采集事件 → 空 dict（不落盘）。"""
        assert _format_trace_line("s", {"event": "on_chain_stream"}) == {}
