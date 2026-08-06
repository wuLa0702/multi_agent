"""报告骨架生成脚本（沙箱可执行，research-report 技能配套）。

用法（沙箱）：python build_report.py sample_data.json
输入：JSON——{"title": 报告标题, "sections": [{"heading": 章节名, "points": [要点...]}]}
输出：Markdown 骨架文件（report_draft.md），含占位与来源标注。

示例数据见同目录 sample_data.json。
"""
import json
import sys
from pathlib import Path


def build_draft(data: dict) -> str:
    """按五段结构生成报告骨架 Markdown。"""
    title = data.get("title", "未命名报告")
    sections = data.get("sections", [])
    lines = [f"# {title}", ""]
    for section in sections:
        lines += [f"## {section['heading']}", ""]
        for point in section.get("points", []):
            lines += [f"- [ ] {point}（来源：待核实）", ""]
    lines += ["## 自检清单", "",
              "- [ ] 每个发现附来源", "- [ ] 结论先行", "- [ ] 无来源信息标注待核实", ""]
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print("用法：python build_report.py <data.json>")
        sys.exit(1)
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path("report_draft.md").write_text(build_draft(data), encoding="utf-8")
    print("骨架已生成：report_draft.md")


if __name__ == "__main__":
    main()
