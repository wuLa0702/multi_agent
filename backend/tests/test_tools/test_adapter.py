"""输出适配层单测（阶段 2.2.0）：`as_lc_tool` 把 `ToolResult` 拆成双通道。

契约见 `docs/决策/2026-10-14-设计-工具中心阶段2输出侧-v1.md` §4。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from src.tools.adapter import as_lc_tool
from src.tools.result import ToolResult, render


def _sample(code: str, max_chars: int = 100, flag: bool = False) -> ToolResult:
    """示例工具：签名带类型 / 默认值，供 schema 推断断言。"""
    return ToolResult(
        status="ok",
        message=f"code={code} max_chars={max_chars} flag={flag}",
        data={"code": code},
        tool="sample",
    )


def _call(tool: BaseTool, args: dict[str, Any]) -> ToolMessage:
    """按 tool_call 协议调用工具，取回 ToolMessage。"""
    return tool.invoke(
        {"name": tool.name, "args": args, "id": "c1", "type": "tool_call"}
    )


class TestMountedShape:
    """挂载形态：名称 / 双通道声明 / 描述 / schema。"""

    def test_name_and_response_format(self) -> None:
        """工具名取自入参 name；必须声明 content_and_artifact（否则元组被当 content）。"""
        mounted = as_lc_tool(_sample, name="sample")
        assert isinstance(mounted, BaseTool)
        assert mounted.name == "sample"
        assert mounted.response_format == "content_and_artifact"

    def test_description_from_docstring(self) -> None:
        """描述取自原函数 docstring（回归锁：防再现「描述为空」事故，阶段 1.3）。"""
        mounted = as_lc_tool(_sample, name="sample")
        assert mounted.description
        assert "示例工具" in mounted.description

    def test_args_schema_follows_signature(self) -> None:
        """入参 schema 由原签名推断（参数名 / 类型 / 默认值不丢）。"""
        props = convert_to_openai_tool(as_lc_tool(_sample, name="sample"))["function"][
            "parameters"
        ]["properties"]
        assert set(props) == {"code", "max_chars", "flag"}
        assert props["max_chars"]["default"] == 100
        assert props["flag"]["default"] is False

    def test_wraps_exposes_original(self) -> None:
        """`functools.wraps` 生效：`__wrapped__` 指向原函数（签名穿透的前提）。"""
        mounted = as_lc_tool(_sample, name="sample")
        assert mounted.func.__wrapped__ is _sample


class TestDualChannel:
    """双通道：content 给 LLM、artifact 给程序。"""

    def test_content_is_rendered_text(self) -> None:
        """content == `render(result)`，不是元组字符串化。"""
        message = _call(as_lc_tool(_sample, name="sample"), {"code": "x"})
        assert message.content == "code=x max_chars=100 flag=False"
        assert "(" not in message.content  # 元组未被 stringify

    def test_artifact_carries_full_envelope(self) -> None:
        """artifact 带 status / error_code / retryable / data 四键（程序侧唯一能看到三态处）。"""
        message = _call(as_lc_tool(_sample, name="sample"), {"code": "x"})
        assert message.artifact == {
            "status": "ok",
            "error_code": "",
            "retryable": False,
            "data": {"code": "x"},
        }

    def test_artifact_keeps_error_semantics(self) -> None:
        """error 态：错误码与可重试性必须带到 artifact（阶段 2.3 审计 / SSE 靠它）。"""

        def failing(code: str) -> ToolResult:
            """必失败的示例工具。"""
            return ToolResult(
                status="error",
                message="请求超时",
                error_code="timeout",
                retryable=True,
                tool="failing",
            )

        artifact = _call(as_lc_tool(failing, name="failing"), {"code": "x"}).artifact
        assert artifact["status"] == "error"
        assert artifact["error_code"] == "timeout"
        assert artifact["retryable"] is True
        assert artifact["data"] is None

    def test_artifact_data_none_when_absent(self) -> None:
        """无 data → `artifact["data"] is None`（如实表达「无结构化载荷」，不假装空 dict）。"""

        def no_data(code: str) -> ToolResult:
            """无 data 的工具。"""
            return ToolResult(status="ok", message="done", tool="no_data")

        artifact = _call(as_lc_tool(no_data, name="no_data"), {"code": "x"}).artifact
        assert artifact["data"] is None
        assert artifact["status"] == "ok"

    def test_artifact_does_not_duplicate_message_or_tool(self) -> None:
        """`message` / `tool` 不重复携带：前者已在 content，后者即 ToolMessage.name。"""
        message = _call(as_lc_tool(_sample, name="sample"), {"code": "x"})
        assert set(message.artifact) == {"status", "error_code", "retryable", "data"}
        assert message.name == "sample"

    def test_status_is_not_tool_status(self) -> None:
        """`ToolMessage.status` 是**执行**状态（success/error），与三态 `status` 不同名同物。

        三态语义经 `render()` 进 content、经 artifact 的 data 走旁路——
        不要把它和 ToolMessage.status 混为一谈（审计取值见阶段 2.3）。
        """
        message = _call(as_lc_tool(_sample, name="sample"), {"code": "x"})
        assert message.status == "success"


class TestThreeStatesThroughAdapter:
    """三态经工具通道后的 content 渲染。"""

    def _run(self, result: ToolResult) -> str:
        def impl(code: str) -> ToolResult:
            """三态示例。"""
            return result

        return _call(as_lc_tool(impl, name="impl"), {"code": "x"}).content

    def test_ok(self) -> None:
        assert self._run(ToolResult(status="ok", message="搜索完成")) == "搜索完成"

    def test_degraded(self) -> None:
        got = self._run(ToolResult(status="degraded", message="输出已截断"))
        assert got == "（部分结果）输出已截断"

    def test_error(self) -> None:
        got = self._run(
            ToolResult(status="error", message="链接非法", error_code="invalid_arg")
        )
        assert got == "失败原因：链接非法"
