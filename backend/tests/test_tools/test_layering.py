"""分层不变量测试：能力层 / 底座层 **不得** 反向依赖编排层（入口层）。

**为什么立这条锁**（2026-10-15，修 P13）：`tools/impl/wiki.py`（能力层）长期
`import src.agent.services.wiki_export_service`（编排层）——违反
`06-structure-optimization` §2「只能上层调下层」。这类违规**静态可见**，
但此前没有任何自动检查拦它，靠人工 review 才在阶段 4 收口时偶然发现。

本测试用 AST 扫全部 import，把「层级方向」变成可执行断言：
**再有人从能力层往上 import，测试直接红**。

扫描范围（除 `api/` `agent/` 外的全部 src 子包）——注意**不止** `tools/`，
`tests/test_tools/` 只是它当前的存放位置。

豁免：无。若确实需要上层能力，正解是**把被依赖的部分下沉**（P13 就是这么修的：
wiki REST 客户端由 `agent/services/` 下沉为 `wiki/` 能力域），不是开豁免口子。
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

# 上层包（其余 src 子包一律视为下层，**自动派生**——新增能力域无需改本测试）
UPPER_LAYERS = {"api", "agent"}

# 下层包**禁止** import 的上层包
FORBIDDEN_UPWARD = tuple(f"src.{pkg}" for pkg in sorted(UPPER_LAYERS))


def _lower_layers() -> list[str]:
    """src/ 下除上层（api / agent）外的全部子包。

    **自动派生**而非硬编码清单：新增能力域（如 2026-10-15 的 `wiki/`）
    自动纳入扫描——避免"清单忘了更新 → 新域永远不被检查"。
    """
    return sorted(
        p.name
        for p in SRC.iterdir()
        if p.is_dir() and p.name not in UPPER_LAYERS and p.name != "__pycache__"
    )


def _iter_py_files(package: str):
    """遍历某下层包的全部 .py（跳过 __pycache__）。"""
    root = SRC / package
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" not in str(path):
            yield path


def _imported_modules(path: Path) -> set[str]:
    """AST 取一个文件 import 的全部模块名（含 `from X import y` 的 X）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _violations() -> list[tuple[Path, str]]:
    """返回 [(文件, 违规模块名)]——能力层/底座层反向 import 上层的全部位置。"""
    found: list[tuple[Path, str]] = []
    for package in _lower_layers():
        for path in _iter_py_files(package):
            for module in _imported_modules(path):
                if module.startswith(FORBIDDEN_UPWARD):
                    found.append((path, module))
    return found


def test_no_upward_import_from_lower_layers() -> None:
    """能力层 / 底座层不得 import `src.agent` 或 `src.api`（06 §2 跨层禁令）。"""
    bad = _violations()
    detail = "\n".join(f"  {p.relative_to(SRC)} → {m}" for p, m in bad)
    assert not bad, (
        "发现反向依赖（能力层/底座层 import 上层）：\n"
        f"{detail}\n"
        "正解：把被依赖的部分下沉到能力层（见 P13 wiki 客户端下沉为 src/wiki/），"
        "而非开豁免。"
    )


def test_scanner_covers_expected_layers() -> None:
    """扫描面自检：防路径写错导致"永远绿"。"""
    layers = _lower_layers()
    assert set(layers) >= {"tools", "sandbox", "llm", "db", "core", "schemas"}, (
        f"下层包派生结果异常：{layers}"
    )
    scanned = sum(len(list(_iter_py_files(p))) for p in layers)
    assert scanned > 20, f"只扫到 {scanned} 个文件，疑似扫描路径失效"


def test_wiki_domain_is_scanned() -> None:
    """回归锁（P13）：wiki/ 能力域必须被扫到——它是修反向依赖的产物。

    若本域被挪走或改名而测试清单未跟，此断言会红，提示同步
    （自动派生的意义正在于此：域消失即扫描面变化，可见）。
    """
    assert "wiki" in _lower_layers()
    assert len(list(_iter_py_files("wiki"))) >= 3, "wiki/ 至少 __init__ + 读 + 写"
