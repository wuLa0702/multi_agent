"""学习 Demo：Interpreters PTC（程序化工具调用，引入方案学习点 P2）。

思维方式：编排进代码——模型只决策"做什么"，解释器代码执行"怎么做"
（循环/分支/并行批次由 JS 驱动，中间结果不进模型上下文，省 token）。

⚠️ 环境阻塞（2026-08-05 实测）：Python 3.14 无 bsdiff4 wheel 且源码构建
失败（langchain-quickjs 硬依赖）——本脚本需 Python 3.11/3.12 venv 运行：
    pip install deepagents[quickjs]
    python examples/interpreter_ptc_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    try:
        from langchain_quickjs import CodeInterpreterMiddleware  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "环境阻塞：langchain-quickjs 不可用（Python 3.14 无 bsdiff4 wheel）。"
            "请换 Python 3.11/3.12 venv 后 `pip install deepagents[quickjs]`。"
        ) from exc

    print("== PTC 并行搜索聚合演示（官方示例形态）==")
    print(
        """
const topics = ["retrieval", "memory", "evaluation"];
const results = await Promise.all(
  topics.map((topic) => tools.webSearch({ query: `${topic} best practices` })),
);
results.join("\\n\\n");
"""
    )
    print(
        "挂载方式（main_agent._build_agent，interpreter_enabled=True）：\n"
        "CodeInterpreterMiddleware(ptc=['internet_search'], mode='turn')"
    )
