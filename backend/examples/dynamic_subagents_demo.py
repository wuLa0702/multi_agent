"""学习 Demo：动态子代理 task() 批量扇出（引入方案学习点 P2）。

思维方式：从"模型逐个委派"到"代码批量扇出"——解释器代码里用 task()
对 N 个 item 并行派 reviewer 子代理并聚合结果。

⚠️ 环境阻塞（2026-08-05 实测）：同 interpreter_ptc_demo（需 quickjs 包 +
Python 3.11/3.12 venv）。

⚠️ 前置：需配置子代理（subagents/*.yaml，如 reviewer 角色），
且主 agent 挂载解释器中间件 + subagents 参数。
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

    print("== task() 动态子代理扇出演示（官方示例形态）==")
    print(
        """
const paths = ["src/auth.ts", "src/routes/api.ts"];
const reviews = await Promise.all(
  paths.map((path) =>
    task({ description: `Review ${path} for auth issues`, subagentType: "reviewer" }),
  ),
);
reviews.join("\\n\\n");
"""
    )
