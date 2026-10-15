"""工具定义唯一真相源（蓝图 §4：tools/registry.py）。

本模块是"工具是什么"的**唯一登记处**：一条 `ToolSpec` = 一个工具的实现 + 元数据。
三个消费方全部从 `TOOL_REGISTRY` 派生，杜绝"两处清单漂移"（阶段 0.1）：

- 主 Agent 挂载 → `tools_for_main()` / `hitl_tools()`
- 子代理 YAML 查表 → `get_tool()`
- 未来 MCP 协议化暴露清单 → 同一张表

元数据口径见 `docs/决策/2026-10-14-设计-工具中心职责边界-v1.md`：
domain 支撑分层归纳；is_idempotent / fallback_to 支撑重试与降级；
risk_level / requires_approval 支撑审批；size 支撑大/小工具划分。

**两层结构**（阶段 2.2.0）：`_IMPL_SPECS` 声明「实现 + 重试」，`TOOL_REGISTRY`
在其上再包一层**输出适配**（`as_lc_tool` → `content_and_artifact`，见
`docs/决策/2026-10-14-设计-工具中心阶段2输出侧-v1.md`）后作为对外唯一真相源。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from langchain_core.tools import BaseTool

from src.tools.adapter import as_lc_tool
from src.tools.impl.ask_human import ask_human
from src.tools.impl.fetch import fetch_url
from src.tools.impl.publish_report import publish_report
from src.tools.impl.report import generate_report
from src.tools.impl.sandbox import (
    download_sandbox_file,
    run_code_in_sandbox,
    run_command_in_sandbox,
    upload_workspace_file,
)
from src.tools.impl.search import internet_search
from src.tools.impl.skill import run_skill_script
from src.tools.impl.wiki import write_wiki

HITL_DOMAIN = "hitl"


@dataclass(frozen=True)
class ToolSpec:
    """单条工具定义：实现 + 元数据（唯一真相源的一行）。

    Attributes:
        name: 工具名（LLM 看到的函数名，全局唯一）
        fn: 挂载形态 `BaseTool`——由 `_IMPL_SPECS` 经「按需包 retry → 包输出适配
            （`as_lc_tool`，`content_and_artifact`）」派生，**不是**裸实现函数
        domain: 能力域（search / sandbox / file / skill / wiki / report / hitl）
        description: 一句话描述（给 LLM，压缩后）
        is_idempotent: 幂等性——决定能否自动重试（写操作 False）
        risk_level: 风险级（low / medium / high）——审批依据
        size: 粒度（small=可自由编排 / big=强事务整体动作）
        fallback_to: 降级备选工具名（显式声明，不靠猜）
        requires_approval: 是否需 HITL 审批
        allowed_decisions: 审批时**允许人类做哪些决策**（`requires_approval=True`
            时必填，见下方不变量）。取值：`approve`（通过执行）/ `edit`（人类改参数
            后重执行）/ `reject`（驳回）/ `respond`（仅澄清类工具——人类回答即结果）。
            **为什么不是从 `risk_level` 推导**：同为 `high` 的工具按钮集可以不同——
            `run_code_in_sandbox` 允许 `edit`（代码可改了重跑），
            `run_command_in_sandbox` 不允许（命令改了还是得重执行）。故显式声明。
        mount_main: 是否挂到主 Agent（False = 仅子代理按 YAML 取用）
    """

    name: str
    fn: BaseTool
    domain: str
    description: str
    is_idempotent: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
    size: Literal["small", "big"] = "small"
    fallback_to: str | None = None
    requires_approval: bool = False
    allowed_decisions: tuple[str, ...] | None = None
    mount_main: bool = True


# ── 实现层声明（fn = 实现函数；重试包装按需在此显式挂）──
# 重试（计划-容错处理 v1.2）：只包读操作幂等工具——internet_search / fetch_url
# 是读操作（幂等）→ 瞬时故障重试；run_skill_script 脚本含写操作
# （build_report.py 写文件）→ 重试幂等风险，排除（v1.2 评审）。
# 沙箱纯计算工具不包（本地执行无网络瞬时故障）。
#
# ⚠️ 条目顺序即挂载顺序：`tools_for_main()` 按此顺序返回，须与重构前手写清单一致。
_IMPL_SPECS: dict[str, ToolSpec] = {
    # ── 搜索域（mount_main=False：仅搜索子代理按 YAML 取用）──
    # P4 闭环（2026-10-15）：此处原为 `retry_tool()(internet_search)`，与外层
    # 模块内的 `@retry_tool(retries=2, extra_exceptions=HTTPStatusError)` 构成
    # 双重包装。实测证明**外层是空转**（内层已把异常吞成降级返回值，外层永不
    # 触发：探测到博查仅被调用 3 次 = 1 首发 + 2 重试，恰为内层参数）。
    # 且内层带 HTTP 细节（extra_exceptions），保留内层删外层 = 零行为变更。
    "internet_search": ToolSpec(
        name="internet_search",
        fn=internet_search,
        domain="search",
        description="博查网络搜索：关键词 → 结构化结果（标题/链接/摘要）",
        is_idempotent=True,
        fallback_to="fetch_url",
        mount_main=False,
    ),
    # P4 闭环（2026-10-15，同 internet_search）：删掉外层 `retry_tool()`——
    # 实测其空转（内层已把异常吞成降级返回值），内层自带 HTTP 细节，零行为变更。
    "fetch_url": ToolSpec(
        name="fetch_url",
        fn=fetch_url,
        domain="search",
        description="受控抓取网页正文（搜索发现 + 抓取获取 双工具分工）",
        is_idempotent=True,
        mount_main=False,
    ),
    # ── 沙箱域（副作用操作，不可重试，需审批）──
    "run_code_in_sandbox": ToolSpec(
        name="run_code_in_sandbox",
        fn=run_code_in_sandbox,
        domain="sandbox",
        description="在隔离 OpenSandbox 沙箱执行 Python 代码并返回输出",
        risk_level="high",
        requires_approval=True,
        # 允许 edit：代码可以人类改完再跑，改比重写省事
        allowed_decisions=("approve", "edit", "reject"),
    ),
    "run_command_in_sandbox": ToolSpec(
        name="run_command_in_sandbox",
        fn=run_command_in_sandbox,
        domain="sandbox",
        description="在沙箱执行 shell 命令并返回输出",
        risk_level="high",
        requires_approval=True,
        # 不允许 edit：命令改了还是得重新执行，"改了照旧跑"没有意义
        allowed_decisions=("approve", "reject"),
    ),
    # ── 文件域（会话级工作区同步）──
    # ⚠️ 2026-10-15 修正：这两个此前【漏了】 requires_approval——而审批实现在
    # hitl.py 里手写了它们（approve+reject），即"登记表说不用审批、实际却在审批"。
    # 收敛时由等价锁抓出，此处补正（行为不变：审批照旧）。
    "upload_workspace_file": ToolSpec(
        name="upload_workspace_file",
        fn=upload_workspace_file,
        domain="file",
        description="把会话工作区文件上传到沙箱",
        risk_level="medium",
        requires_approval=True,
        allowed_decisions=("approve", "reject"),
    ),
    "download_sandbox_file": ToolSpec(
        name="download_sandbox_file",
        fn=download_sandbox_file,
        domain="file",
        description="从沙箱取回文件到会话工作区",
        risk_level="medium",
        requires_approval=True,
        allowed_decisions=("approve", "reject"),
    ),
    # ── 技能域（读文件→沙箱→执行 一步封装）──
    "run_skill_script": ToolSpec(
        name="run_skill_script",
        fn=run_skill_script,
        domain="skill",
        description="执行技能脚本（读文件→沙箱→执行一步封装）",
        size="big",  # 强事务：一个整体动作，非可自由编排的原子操作
        risk_level="high",
        requires_approval=True,
        allowed_decisions=("approve", "reject"),
    ),
    # ── Wiki 知识库 ──
    "write_wiki": ToolSpec(
        name="write_wiki",
        fn=write_wiki,
        domain="wiki",
        description="把内容写入 wiki 知识库（不可达时工具降级）",
        risk_level="medium",
    ),
    # ── 研报域 ──
    "generate_report": ToolSpec(
        name="generate_report",
        fn=generate_report,
        domain="report",
        description="研报结构化生成（主 Agent 撰写 → 结构化 → 交付）",
        size="big",
    ),
    # ── HITL 域（hitl_enabled 门控，见 hitl_tools）──
    "ask_human": ToolSpec(
        name="ask_human",
        fn=ask_human,
        domain=HITL_DOMAIN,
        description="向人类澄清需求 / 中途确认（HITL 决策出口）",
        requires_approval=True,
        # 只用 respond：人类回答即工具结果。**绝不配 approve/edit**
        # （官方警告：respond 仅限 ask-user 类工具）
        allowed_decisions=("respond",),
    ),
    "publish_report": ToolSpec(
        name="publish_report",
        fn=publish_report,
        domain=HITL_DOMAIN,
        description="输出审核交付闸门（HITL 审批出口）",
        requires_approval=True,
        # 允许 edit：人类可直接改报告正文后交付
        allowed_decisions=("approve", "edit", "reject"),
    ),
}


def _with_output_adapter(spec: ToolSpec) -> ToolSpec:
    """实现函数 → 挂载形态 `BaseTool`（输出适配包在最外层，见 `tools/adapter.py`）。

    只做一件事：把 `spec.fn`（实现）换成「执行后拆分 content / artifact」的
    langchain 工具。**幂等/重试等策略不在此处**——`_IMPL_SPECS` 里已显式挂好，
    保持「重试在最内、输出适配在最外」的既有层次，本步不引入行为变更。

    Args:
        spec: 实现层声明（`fn` 为普通函数）

    Returns:
        `fn` 替换为 `BaseTool` 的同名 `ToolSpec`（`name` 单一来源，不重复书写）
    """
    return replace(spec, fn=as_lc_tool(spec.fn, name=spec.name))


# 对外唯一真相源：键 → 挂载形态（实现 + 重试 + 输出适配）。
TOOL_REGISTRY: dict[str, ToolSpec] = {
    name: _with_output_adapter(spec) for name, spec in _IMPL_SPECS.items()
}


def get_tool(name: str) -> BaseTool:
    """按名称取工具（挂载形态 `BaseTool`）。

    Args:
        name: 注册表内的工具名（YAML tools 字段 / agent 挂载清单）

    Returns:
        可直接交给 langchain 挂载的 `BaseTool`

    Raises:
        KeyError: 未知工具名（配置错误，fail fast——不让 agent 带病启动）
    """
    if name not in TOOL_REGISTRY:
        raise KeyError(f"未注册工具：{name}，可选：{sorted(TOOL_REGISTRY)}")
    return TOOL_REGISTRY[name].fn


def tools_for_main() -> list[BaseTool]:
    """主 Agent 挂载清单（_build_agent 的唯一来源，不含 HITL 域）。

    HITL 门控留给编排层（main_agent 按 settings.hitl_enabled 决定是否追加
    `hitl_tools()`）——注册表只做"表"，不做策略。

    Returns:
        mount_main=True 且非 HITL 域的挂载形态工具，顺序同 TOOL_REGISTRY
    """
    return [
        spec.fn
        for spec in TOOL_REGISTRY.values()
        if spec.mount_main and spec.domain != HITL_DOMAIN
    ]


def hitl_tools() -> list[BaseTool]:
    """HITL 域工具（编排层按 hitl_enabled 门控挂载）。

    Returns:
        domain == HITL_DOMAIN 的挂载形态工具
    """
    return [spec.fn for spec in TOOL_REGISTRY.values() if spec.domain == HITL_DOMAIN]
