"""反绕过锁：审计写入**必须**经 `core.audit.emit()`（工作单 T1.8）。

## 为什么立这条锁

"消方言"不是改字段名，而是**让所有写入必经同一个门口**——
只要还有一处绕过 `emit()`，方言就会重新长出来。
历史遗留的 `agent/memory/agent.py` 那句**纯文本行**就是绕过品：
它混在 JSON 审计流里，按 JSON 解析的下游会在它那里炸（批次 1 才修掉）。

锁的形态：**AST 扫全仓**，出现对 `audit` logger 的直调 → 红。

## 手法说明

与 `tests/test_tools/test_layering.py`（分层不变量）同款：
源码级断言 + **扫描面自检**（防路径写错导致"永远绿"）。
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

#: 唯一允许直调 audit logger 的文件——`emit()` 自己的落盘实现
WHITELIST = {SRC / "core" / "audit.py"}

#: 直调的两种形态
_AUDIT_LOGGER_NAME = "audit_logger"


def _iter_py_files():
    """遍历 `src/` 全部 .py（跳过 __pycache__）。"""
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" not in str(path):
            yield path


def _direct_audit_writes(path: Path) -> list[int]:
    """找出文件里对 audit logger 的**直调**（返回行号列表）。

    覆盖两种绕过形态：
    1. `audit_logger.info(...)`            —— 模块级 logger 变量
    2. `logging.getLogger("audit").info(…)` —— 现场取 logger
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in {"info", "warning", "error", "debug"}:
            continue
        owner = node.func.value  # 调用者
        # 形态 1：audit_logger.xxx(...)
        if isinstance(owner, ast.Name) and owner.id == _AUDIT_LOGGER_NAME:
            hits.append(node.lineno)
        # 形态 2：logging.getLogger("audit").xxx(...)
        elif (
            isinstance(owner, ast.Call)
            and isinstance(owner.func, ast.Attribute)
            and owner.func.attr == "getLogger"
            and owner.args
            and isinstance(owner.args[0], ast.Constant)
            and owner.args[0].value == "audit"
        ):
            hits.append(node.lineno)
    return hits


class TestNoBypass:
    """全仓不得绕过 `emit()`。"""

    def test_only_emit_writes_audit(self) -> None:
        """除 `core/audit.py` 外，任何文件直调 audit logger → 红。"""
        offenders: list[str] = []
        for path in _iter_py_files():
            if path in WHITELIST:
                continue
            for lineno in _direct_audit_writes(path):
                offenders.append(f"  {path.relative_to(SRC)}:{lineno}")

        assert not offenders, (
            "发现绕过 emit() 的审计写入：\n"
            + "\n".join(offenders)
            + "\n正解：改为调用 `from src.core.audit import emit`——"
            "绕过会让审计方言重新长出来（字段不统一、下游解析会炸）。"
        )


class TestScannerSanity:
    """扫描面自检——防"路径写错 → 永远绿"（同 test_layering 手法）。"""

    def test_scanner_detects_the_whitelisted_writer(self) -> None:
        """白名单文件**本身**必须能被扫出直调 → 证明扫描器有效。

        若这条挂了，说明检测逻辑坏了（而不是"大家都很干净"）——
        那 `TestNoBypass` 就是一条永远绿的假锁。
        """
        found = [
            lineno for path in WHITELIST for lineno in _direct_audit_writes(path)
        ]
        assert found, (
            "扫描器没能在 core/audit.py 里找到 audit_logger 直调——"
            "检测逻辑或路径已失效，反绕过锁成了摆设"
        )

    def test_scan_covers_expected_scale(self) -> None:
        """扫描规模自检：src/ 下的文件数不该是个位数（防根路径写错）。"""
        files = list(_iter_py_files())
        assert len(files) > 50, f"只扫到 {len(files)} 个文件，疑似路径失效"
        assert SRC.is_dir(), f"源码根不存在：{SRC}"

    def test_detector_flags_both_evasion_forms(self, tmp_path: Path) -> None:
        """检测器自测：两种绕过形态都要能被抓到（含现场取 logger 那种）。"""
        sample = tmp_path / "sample.py"
        sample.write_text(
            "import logging\n"
            "audit_logger = logging.getLogger('audit')\n"
            "audit_logger.info('形态 1')\n"          # 第 3 行
            "logging.getLogger('audit').info('形态 2')\n",  # 第 4 行
            encoding="utf-8",
        )
        assert _direct_audit_writes(sample) == [3, 4]

    def test_detector_ignores_emit_and_other_loggers(self, tmp_path: Path) -> None:
        """不误伤：`emit(...)`、普通 logger、以及**注释里的** audit_logger 都不算。"""
        sample = tmp_path / "sample.py"
        sample.write_text(
            "from src.core.audit import emit\n"
            "import logging\n"
            "# audit_logger.info('这是注释，不该被抓')\n"
            "logger = logging.getLogger(__name__)\n"
            "logger.info('普通日志')\n"
            "emit('tool_call', 'tool_call.start')\n",
            encoding="utf-8",
        )
        assert _direct_audit_writes(sample) == []
