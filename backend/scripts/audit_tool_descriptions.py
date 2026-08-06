"""工具描述 token 审计（上下文工程开发计划 #8，2026-08-05）。

统计全部工具描述长度（token 估算：字符数/4）——不只 MCP 注册工具，
**deepagents 内置文件工具也进上下文**（ls/read/write/edit/delete/glob/grep），
一并统计。长描述可拆"摘要+详情"（同 Skill 渐进披露思路）。

运行（backend/ 下）：
    python scripts/audit_tool_descriptions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mcp.registry import TOOL_REGISTRY  # noqa: E402

# deepagents 内置文件工具描述（固定常量——FilesystemMiddleware 工具）
_BUILTIN_FILE_TOOLS: dict[str, str] = {
    "ls": "List files and directories",
    "read_file": "Read a file",
    "write_file": "Write a file",
    "edit_file": "Edit a file",
    "delete": "Delete a file",
    "glob": "Find files by pattern",
    "grep": "Search file contents",
}


def audit_tool_descriptions() -> dict:
    """统计全部工具描述长度（token 估算：字符数/4）。

    Returns:
        {"tool_name": {"desc_len": N, "chars": M, "source": "internal|mcp"},
         "total_chars": X}
    """
    result: dict = {}
    for name, tool in TOOL_REGISTRY.items():
        desc = getattr(tool, "description", "")
        result[name] = {"desc_len": len(desc) // 4, "chars": len(desc), "source": "mcp"}
    for name, desc in _BUILTIN_FILE_TOOLS.items():
        result[name] = {"desc_len": len(desc) // 4, "chars": len(desc), "source": "internal"}
    result["total_chars"] = sum(v["chars"] for v in result.values() if isinstance(v, dict))
    return result


if __name__ == "__main__":
    stats = audit_tool_descriptions()
    print(f"共 {len(stats) - 1} 个工具描述，总字符 {stats['total_chars']}（估算 token {stats['total_chars'] // 4}）")
    for name, info in sorted(stats.items()):
        if name == "total_chars":
            continue
        flag = " ⚠️ 长描述" if info["chars"] > 200 else ""
        print(f"  [{info['source']}] {name}: {info['chars']} 字符 / ~{info['desc_len']} token{flag}")
