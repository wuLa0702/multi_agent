"""write_wiki 工具：Agent 运行时把内容写入 wiki 知识库（P1.5/P1，2026-08-13）。

走 REST（`wiki/export_service` 调 wiki POST /v1/pages/{path}）——Agent 工具通道
（MCP 需 wiki 侧暴露 wiki_write，暂用 REST 直连，双通道语义见 wiki 设计 §3）。

失败降级为错误信息，不中断 run。输出为 `ToolResult` 信封（阶段 2.2.8）。

2026-10-15（修 P13）：原先 import `src.agent.services.wiki_export_service`
（编排层）——**能力层反向依赖上层**，违反 06 §2。客户端已下沉为 `src/wiki/`
能力域，此处改为向下取用。
"""

from __future__ import annotations

from src.core.errors import ToolErrorCode
from src.tools.contract.result import ToolResult
from src.wiki.export_service import WikiExportError, export_to_wiki

_TOOL_NAME = "write_wiki"


def write_wiki(path: str, content: str, title: str = "") -> ToolResult:
    """把内容写入 wiki 知识库页面。

    Args:
        path: wiki 页面路径（如 调研结论-xxx / 知识-xxx）
        content: 页面正文（Markdown）
        title: 页面标题（缺省用 path）

    Returns:
        成功 → `ok` 信封（`data` 带 path）；内容为空 → `error: invalid_arg`；
        wiki 侧故障 → `error: upstream_error`
    """
    if not content.strip():
        return ToolResult(
            status="error",
            message="写入失败：内容为空",
            error_code=ToolErrorCode.INVALID_ARG,
            tool=_TOOL_NAME,
        )
    try:
        result = export_to_wiki(path, content, title or path)
    except WikiExportError as exc:
        return ToolResult(
            status="error",
            message=f"写入 wiki 失败：{exc}",
            error_code=ToolErrorCode.UPSTREAM_ERROR,
            tool=_TOOL_NAME,
        )
    written_path = result.get("path") or path
    return ToolResult(
        status="ok",
        message=f"已写入 wiki: {written_path}",
        data={"path": written_path},
        tool=_TOOL_NAME,
    )
