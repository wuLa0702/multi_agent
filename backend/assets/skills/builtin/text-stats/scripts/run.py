"""text_stats 技能脚本 —— **skill 模板的脚本形态**。

用法（由 `run_skill_script` 在沙箱内调用）：

    python run.py <文件路径>      # 统计工作区里的文件
    echo "hello" | python run.py  # 无参数时从 stdin 读

输出：单行 JSON 到 stdout；出错时写 stderr 并以非零码退出。

## 作为模板怎么读

技能脚本与 `tools/impl/*.py` **不是一回事**：

| | 工具（impl/*.py） | 技能脚本（本文件） |
|---|---|---|
| 运行位置 | 后端进程内 | **沙箱内** |
| 返回值 | `ToolResult` 信封 | **stdout 文本 / JSON** |
| 错误 | 返回 error 信封 | **非零退出码 + stderr** |
| 谁写 | 我们（进 registry） | 技能作者（市场安装） |

因为跑在沙箱里，脚本**不 import 项目代码**——只依赖标准库，才能在任何沙箱镜像里跑。
"""

from __future__ import annotations

import json
import sys


def _read_text(argv: list[str]) -> tuple[str, str]:
    """读入文本（文件名或 stdin），返回 (文本, 来源标签)。"""
    if len(argv) > 1:
        path = argv[1]
        with open(path, encoding="utf-8") as handle:
            return handle.read(), path
    return sys.stdin.read(), "<stdin>"


def main() -> int:
    """入口：统计并输出 JSON。

    Returns:
        进程退出码（0 = 成功）
    """
    try:
        text, source = _read_text(sys.argv)
    except OSError as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 1

    stats = {
        "chars": len(text),
        "chars_no_space": len("".join(text.split())),
        "words": len(text.split()),
        "lines": len(text.splitlines()),
        "source": source,
    }
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
