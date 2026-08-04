"""辅助任务提示词集中管理（2026-08-04：防散落，一处维护可评审）。

轻量辅助任务（记忆抽取/标题生成等）不需要子 agent——无工具、单次调用、
失败可降级，用 prompt + 单次 ainvoke 即可（探讨结论见 docs/decisions/过程中优化记录）。
本文件是**唯一 prompt 定义处**：新增辅助任务（摘要/分类等）先在此加 prompt。
"""

from __future__ import annotations

# 记忆抽取（memory_store.extract_memory_fact 使用）
MEMORY_EXTRACT_PROMPT = """你是记忆抽取器。判断这段对话是否有【值得长期记忆】的内容：
用户的事实/身份信息、明确偏好、关键决策、项目约束。若有，用一句话抽取为精简事实
（中文，≤50 字，第三人称描述）；若没有（普通问答、一次性任务、闲聊），只输出：无

对话：
用户：{user}
助手：{assistant}

抽取结果："""

# 会话标题生成（assistant_tasks.generate_title 使用）
TITLE_GENERATE_PROMPT = """你是会话标题生成器。根据用户第一条消息生成一个简洁的会话标题：
中文，≤15 字，概括对话主题，不要标点结尾。只输出标题本身，不要解释。

用户消息：{message}"""
