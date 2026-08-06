"""示例脚本（模板占位，可执行）。

用法（沙箱）：python example.py example_data.json
输入：JSON 文件路径；输出：处理结果到 stdout。
"""
import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        print("用法：python example.py <data.json>")
        sys.exit(1)
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(f"已处理 {len(data)} 条数据：{list(data)[:3]}")


if __name__ == "__main__":
    main()
