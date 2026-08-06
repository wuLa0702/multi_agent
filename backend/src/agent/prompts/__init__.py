"""提示词包：集中维护（2026-08-05 结构重构——唯一提示词定义处）。

当前单文件 prompts.py 维护全部提示词；后续提示词增多可拆分文件，
本 __init__ re-export 保持导入路径稳定。
"""

from src.agent.prompts.prompts import (  # noqa: F401
    DEFAULT_SYSTEM_PROMPT,
    MEMORY_AGENT_PROMPT,
    MEMORY_EXTRACT_PROMPT,
    MEMORY_GUIDANCE_V3,
    MODE_INSTRUCTIONS,
    TITLE_GENERATE_PROMPT,
)
