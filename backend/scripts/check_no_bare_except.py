"""裸 except 捕获检测（计划-容错处理 v1.2 P1-d）。

06-structure-optimization §4 禁令：禁止超大范围 try-except 裸捕获
（`except Exception` 包整段业务）掩盖真实故障——捕获必须精确到异常类型、
必须处理（记录/转换/降级）。

检测规则：
- `except Exception` / `except BaseException`（裸捕获）：标记
  - 有 `# noqa: BLE001` 注释（显式声明）→ 提示（人工确认降级合理）
  - 无注释 → 违规（FAIL）
- 精确捕获（except XxxError / except KeyError 等）→ 合规

用法：
    python scripts/check_no_bare_except.py                 # 扫描 src/
    python scripts/check_no_bare_except.py src/api/chat.py # 指定文件/目录
    python scripts/check_no_bare_except.py --strict        # 无注释也 FAIL（默认仅提示）
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

# 裸捕获类型（except Exception / BaseException）
_BARE_TYPES = {"Exception", "BaseException"}


def scan_file(path: Path) -> list[tuple[int, str, bool]]:
    """扫描单文件：返回 [(行号, 异常类型, 是否有 noqa 声明)]。

    Args:
        path: Python 文件

    Returns:
        裸捕获清单（行号 / except 类型 / 是否显式 noqa 声明）
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    findings: list[tuple[int, str, bool]] = []

    class _Visitor(ast.NodeVisitor):
        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.type is None or getattr(node.type, "id", None) in _BARE_TYPES:
                # 定位 except 行：取 node 前最近的 try 行号（用 ast.get_source_segment 或 lineno）
                lineno = node.lineno
                line = ""
                if path.exists():
                    lines = path.read_text(encoding="utf-8").splitlines()
                    if lineno - 1 < len(lines):
                        line = lines[lineno - 1]
                has_noqa = "# noqa: BLE001" in line
                findings.append((lineno, node.type.id if node.type else "bare", has_noqa))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return findings


def scan_path(target: Path) -> int:
    """扫描目录/文件，输出报告并返回违规计数。

    Args:
        target: 文件或目录

    Returns:
        违规数（无 noqa 声明的裸捕获）
    """
    files = [target] if target.is_file() else sorted(target.rglob("*.py"))
    violations = 0
    for f in files:
        if "__pycache__" in str(f):
            continue
        findings = scan_file(f)
        for lineno, exc_type, has_noqa in findings:
            status = "⚠️ noqa 声明" if has_noqa else "❌ 违规"
            print(f"{f.relative_to(target.parents[1] if target.is_file() else target)}:{lineno} {status} except {exc_type}")
            if not has_noqa:
                violations += 1
    return violations


def main() -> int:
    """CLI 入口：--target / --strict。"""
    parser = argparse.ArgumentParser(description="裸 except 捕获检测")
    parser.add_argument("target", type=Path, nargs="?", default=SRC_DIR, help="扫描目标（文件/目录，缺省 src/）")
    args = parser.parse_args()
    violations = scan_path(args.target)
    if violations:
        print(f"\n共 {violations} 处无声明裸捕获（需精确化）")
        return 1
    print("\n无裸捕获违规（noqa 声明的降级点需人工确认合理）")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):  # 04-logging：入口统一 UTF-8（Windows GBK 乱码）
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
