"""工具静态检查：参数注解 / 歧义命名 / docstring（阶段 1.3，工具中心规范 §1–§2）。

**开发期脚本**——不运行代码、不进运行时、不被 Agent 调用；放 `scripts/` 而非
`src/`（与 `check_no_bare_except.py` 同族）。

只查**静态查得到**的三件事：
1. 工具函数参数缺类型注解
2. 参数名歧义（`data` / `info` / `value` …，规范 §2.4「命名所见即所得」）
3. 工具函数缺 docstring

**查不了**（靠规则 + review）：该不该用枚举、否定约束写得对不对、粒度划得对不对。

用法（backend/ 下）：
    python scripts/lint_tools.py                      # 扫 src/tools/impl
    python scripts/lint_tools.py src/tools/impl/x.py  # 指定文件
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "tools" / "impl"

# 歧义参数名（规范 §2.4）
AMBIGUOUS_NAMES = frozenset({
    "data", "info", "value", "val", "param", "params", "args", "kwargs",
    "tmp", "obj", "item", "x", "y", "z", "d", "e",
})
# 豁免参数（框架注入 / 约定俗成）
_EXEMPT_ARGS = frozenset({"self", "cls", "config"})


def scan_file(path: Path) -> list[tuple[int, str]]:
    """扫单文件 → [(行号, 违规说明)]。仅查公开函数（`_` 开头的辅助豁免）。

    Args:
        path: Python 文件

    Returns:
        违规清单（行号 / 说明）
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        for arg in node.args.args:
            if arg.arg in _EXEMPT_ARGS:
                continue
            if arg.annotation is None:
                findings.append((node.lineno, f"{node.name}: 参数 `{arg.arg}` 缺类型注解"))
            if arg.arg in AMBIGUOUS_NAMES:
                findings.append((node.lineno, f"{node.name}: 参数 `{arg.arg}` 命名歧义"))
        if ast.get_docstring(node) is None:
            findings.append((node.lineno, f"{node.name}: 缺 docstring"))
    return findings


def main() -> int:
    """CLI 入口：位置参数 target（文件或目录，缺省 src/tools/impl）。

    Returns:
        0=无违规；1=有违规
    """
    parser = argparse.ArgumentParser(description="工具静态检查")
    parser.add_argument(
        "target", type=Path, nargs="?", default=SRC_DIR, help="扫描目标（文件/目录）"
    )
    args = parser.parse_args()

    files = [args.target] if args.target.is_file() else sorted(args.target.rglob("*.py"))
    violations = 0
    for f in files:
        if "__pycache__" in str(f):
            continue
        for lineno, msg in scan_file(f):
            print(f"{f.name}:{lineno} ❌ {msg}")
            violations += 1
    print(f"\n共 {violations} 处违规" if violations else "\n无违规")
    return 1 if violations else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):  # 04-logging：入口统一 UTF-8
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
