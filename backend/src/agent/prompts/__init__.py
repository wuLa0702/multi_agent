"""提示词包：集中维护（2026-08-05 结构重构——唯一提示词定义处）。

当前单文件 prompts.py 维护全部提示词；后续提示词增多可拆分文件，
本 __init__ re-export 保持导入路径稳定。
"""

from src.agent.prompts.prompts import (  # noqa: F401
    DEFAULT_SYSTEM_PROMPT,
    HITL_GUIDANCE_TEMPLATE,
    MEMORY_AGENT_PROMPT,
    MEMORY_EXTRACT_PROMPT,
    MEMORY_GUIDANCE_V3,
    MODE_INSTRUCTIONS,
    PROMPT_LAYERS,
    REVIEW_GUIDANCE,
    TITLE_GENERATE_PROMPT,
    build_system_prompt,
)
