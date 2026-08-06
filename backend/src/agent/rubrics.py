"""Rubric 评分模板库与中间件构建（Rubric 设计 §5.4/§5.5）。

- 模板 = 换行 checklist（官方 rubric 字符串形态），业务接入时选模板/覆盖/扩展
- grader model 必须传实例（国产模型自定义 base_url——同 P1-1 教训）
- ⚠️ P0-V1 验证（设计 §6.1）：RubricMiddleware grader 走 response_format
  结构化输出，国产模型三态全挂风险——验证通过前保持 settings.rubric_enabled=False
  （.env.dev 不开）；验证是开发动作，通过后直接开开关（v1.2 无验证中间态）

设计文档：docs/decisions/方案-人在回路与Rubric评分-详细设计-v1.md §5.4/§5.5/§7.2
"""

from __future__ import annotations

import logging

from src.core.config import settings

logger = logging.getLogger(__name__)

RUBRIC_TEMPLATES: dict[str, str] = {
    "code_review": (
        "- 覆盖功能正确性与边界条件\n"
        "- 指出安全问题（注入/越权/密钥泄露）与证据行号\n"
        "- 风格与可维护性建议（有具体依据）\n"
        "- 结论给出严重度分级（P0/P1/P2）"
    ),
    "report_completeness": (
        "- 覆盖用户要求的全部章节\n"
        "- 关键数据有来源引用\n"
        "- 结论可追溯（从数据到结论路径清晰）\n"
        "- 无未经验证的主张"
    ),
    "source_veracity": (
        "- 每条断言都有可核验的来源（URL/文档/代码位置）\n"
        "- 区分事实与推测（推测必须明确标注）\n"
        "- 无编造的数据、引用或统计数字\n"
        "- 无「可能/大概」式的无依据断言"
    ),
}


def build_rubric_middleware() -> list:
    """构建 RubricMiddleware（rubric_enabled 门控，v1.2 起无验证开关）。

    ⚠️ TODO（P0-V1 验证，设计 §6.1）：RubricMiddleware grader 走
    response_format 结构化输出，国产模型三态全挂风险——验证通过前保持
    settings.rubric_enabled=False；验证是开发动作，通过后直接开开关即可，
    无运行时"验证过"状态（v1.2 评审修正）。

    Returns:
        rubric_enabled=True → [RubricMiddleware]；否则 []（不挂载）
    """
    if not settings.rubric_enabled:
        return []
    from deepagents import RubricMiddleware
    from src.llm.adapter import get_chat_model

    return [
        RubricMiddleware(
            model=get_chat_model(),  # grader 传实例（国产 base_url）
            max_iterations=3,
            on_evaluation=_log_evaluation,
        )
    ]


def _log_evaluation(ev: dict) -> None:
    """on_evaluation 回调：日志记录（P1 观测；P2 升级为 SSE 事件）。

    Args:
        ev: RubricEvaluation dict（grading_run_id/iteration/result/explanation/criteria）
    """
    logger.info(
        "rubric iteration=%s result=%s explanation=%s",
        ev.get("iteration"),
        ev.get("result"),
        ev.get("explanation"),
    )
