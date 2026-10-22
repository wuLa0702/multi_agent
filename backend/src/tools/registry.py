"""工具定义唯一真相源（蓝图 §4：tools/registry.py）。

本模块是"工具是什么"的**唯一登记处**：一条 `ToolSpec` = 一个工具的实现 + 元数据。
三个消费方全部从 `TOOL_REGISTRY` 派生，杜绝"两处清单漂移"（阶段 0.1）：

- 主 Agent 挂载 → `tools_for_main()` / `hitl_tools()`
- 子代理 YAML 查表 → `get_tool()`
- 未来 MCP 协议化暴露清单 → 同一张表

元数据口径见 `docs/决策/2026-10-14-设计-工具中心职责边界-v1.md`。
**当前消费方（2026-10-15 批次 2/3 后实测）**：

| 字段 | 谁在读 |
|---|---|
| `domain` / `mount_main` | `tools_for_main()` / `hitl_tools()`（挂载清单） |
| `requires_approval` / `allowed_decisions` | `build_hitl_interrupt_on()`（审批配置，批次 2） |
| `is_idempotent` | `_apply_retry()`（重试门控，批次 3） |
| `fallback_to` | `fallback_for()` → 审计事后行（批次 3） |
| `risk_level` / `size` | **无消费方**——人读的分类标签，如实标注不假装接线 |

**三层结构**（阶段 4 批次 3 定稿）：

```
_IMPL_SPECS（人手写）          fn = 裸实现函数
     │  _apply_retry          ← 幂等门控：is_idempotent 才允许配 retry（否则 fail fast）
     ▼
（派生态）                     fn = retry(fn)
     │  _with_output_adapter  ← as_lc_tool → content_and_artifact
     ▼
TOOL_REGISTRY（对外真相源）     fn = 挂载形态 BaseTool
```

**重试参数也声明在本表**（`RetryPolicy`），不再写在实现文件里——此前
`impl/search.py` / `impl/fetch.py` 各自挂 `@retry_tool` 装饰器，与这里的
`is_idempotent` 构成**第三处「同一件事写两遍」**（批次 3 收敛，同批次 2 的审批）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial
from typing import Callable, Literal

import httpx
from langchain_core.tools import BaseTool

from src.core.retry import DEFAULT_DELAYS, DEFAULT_RETRIES, retry_tool
from src.tools.contract.adapter import as_lc_tool
from src.tools.impl.ask_human import ask_human
from src.tools.impl.calc import calculate
from src.tools.impl.clock import current_time
from src.tools.impl.fetch import fetch_url
from src.tools.impl.json_extract import json_extract
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
from src.tools.contract.result import exhausted_result

HITL_DOMAIN = "hitl"


@dataclass(frozen=True)
class RetryPolicy:
    """幂等读操作的自动重试参数（`ToolSpec.retry` 的值类型）。

    **只在 `is_idempotent=True` 时可配**——由 `_apply_retry` 强制（fail fast）；
    写操作重试有幂等风险（`run_skill_script` v1.2 评审即因此排除）。

    **为什么本类放 registry 而不是 `core/retry.py`**：`wrap()` 要注入
    `exhausted_result`（`tools/contract/result.py`），而 `core/` 是底座层、禁依赖业务目录
    （06-structure-optimization §2）——故「策略声明」留在登记表，底座只提供
    `retry_tool` 机制本身。

    Attributes:
        retries: 最大重试次数（首发之外）
        delays: 每次重试的退避秒数
        extra_exceptions: 该工具额外视为可重试的异常（如 HTTPStatusError——
            对本工具是瞬时故障，对底座不是通用网络异常）
    """

    retries: int = DEFAULT_RETRIES
    delays: tuple[float, ...] = DEFAULT_DELAYS
    extra_exceptions: tuple[type[Exception], ...] = ()

    def wrap(self, fn: Callable, *, tool: str) -> Callable:
        """把裸实现函数包成重试版本。

        `on_exhausted` **必须**注入 `exhausted_result`：重试耗尽要返回**错误信封**
        而非裸字符串——裸字符串会让输出适配层取 `.status` 时 AttributeError
        打崩 run（阶段 2 自检发现的崩溃路径）。

        Args:
            fn: 裸实现函数（返回 `ToolResult`）
            tool: 工具名（耗尽信封的 `tool` 字段，供审计/事件定位）

        Returns:
            重试包装后的函数（签名与 docstring 经 `functools.wraps` 保留）
        """
        return retry_tool(
            retries=self.retries,
            delays=self.delays,
            extra_exceptions=self.extra_exceptions,
            on_exhausted=partial(exhausted_result, tool=tool),
        )(fn)


@dataclass(frozen=True)
class ToolSpec:
    """单条工具定义：实现 + 元数据（唯一真相源的一行）。

    Attributes:
        name: 工具名（LLM 看到的函数名，全局唯一）
        fn: 两种形态——`_IMPL_SPECS` 里是**裸实现函数**；`TOOL_REGISTRY` 里是
            **挂载形态 `BaseTool`**（经「幂等门控包 retry → 包输出适配」两级派生）
        domain: 能力域（search / sandbox / file / skill / wiki / report / hitl）
        description: 一句话描述（给 LLM，压缩后）
        is_idempotent: 幂等性——重复执行是否安全（写操作 False）。
            **同时是重试的门控**：`retry` 只允许配在幂等工具上
        retry: 自动重试参数（None = 不重试）。幂等读操作才配——见 `RetryPolicy`
        risk_level: 风险级（low / medium / high）——**人读的分类标签，当前无消费方**。
            ⚠️ 审批**不**由它推导（批次 2 方案 A 拍板）：同为 high 的工具按钮集可以不同
            （`run_code_in_sandbox` 允许 edit、`run_command_in_sandbox` 不允许），
            故按钮集由 `allowed_decisions` 显式声明，见该字段说明
        size: 粒度（small=可自由编排 / big=强事务整体动作）——**人读的分类标签，当前无消费方**
        fallback_to: 降级备选工具名（显式声明，不靠猜）。
            消费方：`fallback_for()` → 审计事后行（只读声明，**不执行降级**）
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
    retry: RetryPolicy | None = None
    risk_level: Literal["low", "medium", "high"] = "low"
    size: Literal["small", "big"] = "small"
    fallback_to: str | None = None
    requires_approval: bool = False
    allowed_decisions: tuple[str, ...] | None = None
    mount_main: bool = True


# ── 实现层声明（fn = 裸实现函数；重试由 `retry` 字段声明，包装在派生时生成）──
# 重试（计划-容错处理 v1.2 + 阶段 4 批次 3）：只包读操作幂等工具——
# internet_search / fetch_url 是读操作（幂等）→ 瞬时故障重试；
# run_skill_script 脚本含写操作（build_report.py 写文件）→ 重试幂等风险，排除。
# 沙箱纯计算工具不配（本地执行无网络瞬时故障）。
# ⚠️ 批次 3 前，重试参数写在 `impl/search.py` / `impl/fetch.py` 的 `@retry_tool`
# 装饰器里，与下面的 `is_idempotent` 脱节——现全部收敛到本表。
#
# ⚠️ 条目顺序即挂载顺序：`tools_for_main()` 按此顺序返回，须与重构前手写清单一致。
_IMPL_SPECS: dict[str, ToolSpec] = {
    # ── 搜索域（mount_main=False：仅搜索子代理按 YAML 取用）──
    # 重试参数原写在 `impl/search.py` 的 `@retry_tool(retries=2,
    # extra_exceptions=HTTPStatusError, on_exhausted=exhausted_result)` 上
    # （P4 闭环：曾与登记表的外层包装构成双重包装，实测外层空转已删）。
    # 批次 3 把参数搬到此处——`_apply_retry` 按 `is_idempotent` 门控后生成包装，
    # 行为逐项等价（retries / delays / extra_exceptions / on_exhausted 全保留）。
    "internet_search": ToolSpec(
        name="internet_search",
        fn=internet_search,
        domain="search",
        description="博查网络搜索：关键词 → 结构化结果（标题/链接/摘要）",
        is_idempotent=True,
        retry=RetryPolicy(extra_exceptions=(httpx.HTTPStatusError,)),
        fallback_to="fetch_url",
        mount_main=False,
    ),
    # 重试参数同 internet_search（原挂在 impl/fetch.py 的装饰器上）。
    "fetch_url": ToolSpec(
        name="fetch_url",
        fn=fetch_url,
        domain="search",
        description="受控抓取网页正文（搜索发现 + 抓取获取 双工具分工）",
        is_idempotent=True,
        retry=RetryPolicy(extra_exceptions=(httpx.HTTPStatusError,)),
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
    # ── 通用工具域（2026-10-16 新增：门面 + 模板）──
    # 三个都**无副作用且幂等**：不配 retry（纯本地计算/解析，重试无意义）、
    # 不需要审批；挂主 Agent（`mount_main` 默认 True）——正是为了让主链路能直接用。
    # 三者刻意覆盖三种实现粒度，供后续新工具对照抄写：
    #   clock（最简）→ calc（纯函数 + 严格校验）→ json_extract（完整处理链）
    "calculate": ToolSpec(
        name="calculate",
        fn=calculate,
        domain="util",
        description="安全算术计算（+ - * / // % ** 与括号）；算数/百分比/单位换算时用它，别心算",
        is_idempotent=True,
    ),
    "current_time": ToolSpec(
        name="current_time",
        fn=current_time,
        domain="util",
        description="获取当前时间（可指定 IANA 时区）；回答「今天/现在/几天后」类问题前先查",
        is_idempotent=True,
    ),
    "json_extract": ToolSpec(
        name="json_extract",
        fn=json_extract,
        domain="util",
        description="按路径（a.b[0].c）从 JSON 文本取单个字段；避免把整段 JSON 塞进上下文",
        is_idempotent=True,
    ),
}


def _apply_retry(spec: ToolSpec) -> ToolSpec:
    """幂等门控：`is_idempotent` 是重试的唯一开关（声明在表，不写在实现里）。

    包装在最内层（先于输出适配）——保持「retry 最内、输出适配最外」的既有层次。

    Args:
        spec: 实现层声明（`fn` 为裸实现函数）

    Returns:
        `retry` 为 None → 原样返回；否则 `fn` 换成重试包装后的函数

    Raises:
        ValueError: 配了 `retry` 却没声明 `is_idempotent`——写操作重试有幂等风险，
            必须显式声明幂等才允许。**fail fast**：静默忽略等于"配了却不生效"
    """
    if spec.retry is None:
        return spec
    if not spec.is_idempotent:
        raise ValueError(
            f"{spec.name}：配了 retry 但未声明 is_idempotent"
            "（写操作重试有幂等风险，须显式声明幂等才允许）"
        )
    return replace(spec, fn=spec.retry.wrap(spec.fn, tool=spec.name))


def _with_output_adapter(spec: ToolSpec) -> ToolSpec:
    """实现函数 → 挂载形态 `BaseTool`（输出适配包在最外层，见 `tools/contract/adapter.py`）。

    只做一件事：把 `spec.fn`（实现）换成「执行后拆分 content / artifact」的
    langchain 工具。**幂等/重试等策略不在此处**——`_IMPL_SPECS` 里已显式挂好，
    保持「重试在最内、输出适配在最外」的既有层次，本步不引入行为变更。

    Args:
        spec: 实现层声明（`fn` 为普通函数）

    Returns:
        `fn` 替换为 `BaseTool` 的同名 `ToolSpec`（`name` 单一来源，不重复书写）
    """
    return replace(spec, fn=as_lc_tool(spec.fn, name=spec.name))


# 对外唯一真相源：键 → 挂载形态（裸实现 → 幂等门控包重试 → 包输出适配）。
# 派生顺序不可颠倒：retry 必须在最内（耗尽信封是 ToolResult，输出适配才拆得动）。
TOOL_REGISTRY: dict[str, ToolSpec] = {
    name: _with_output_adapter(_apply_retry(spec))
    for name, spec in _IMPL_SPECS.items()
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


def fallback_for(name: str) -> str:
    """查工具的降级备选（登记表 `fallback_to` 声明）；无声明 / 未注册 → 空串。

    **消费方**：审计事后行（工具失败时记下"该换谁"）——`fallback_to` 此前是
    死数据（声明了无人读）。**本函数只读声明，不执行降级**：真要换工具是编排层
    的决定（07-tool-center §4），归后续（P11）。

    Args:
        name: 工具名

    Returns:
        备选工具名；无则空串（不抛异常——审计是旁路，查不到不应打断）
    """
    spec = TOOL_REGISTRY.get(name)
    return spec.fallback_to if spec is not None and spec.fallback_to else ""


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
