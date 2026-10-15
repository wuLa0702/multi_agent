"""HITL 审批的**第二个来源**：MCP 治理元数据（D2 批次 2）。

为什么独立成文件：`test_hitl.py` 锁的是"本地工具登记表派生 == 改造前硬编码表"的
**等价锁**；本文件锁的是**新增的 MCP 来源**——外部工具经 `mcp_tool_meta` 走
同一条审批流水线（此前它们永不弹窗，是安全缺口 G2）。

设计依据：`docs/决策/2026-10-15-设计-工具动态注册两方案对比-v1.md` §8.1/§8.2。
"""

from __future__ import annotations

import pytest

from src.agent.hitl.hitl import build_hitl_interrupt_on
from src.tools.channels import mcp_meta


@pytest.fixture(autouse=True)
def _clean_cache():
    """每用例前后清 MCP 元数据缓存（模块级全局状态）。"""
    mcp_meta.reset()
    yield
    mcp_meta.reset()


def _row(**over) -> dict:
    """造一条 mcp_tool_meta 行。"""
    row = {
        "server_name": "exa",
        "tool_name": "web_search",
        "risk_level": "low",
        "requires_approval": 0,
        "allowed_decisions": "[]",
        "is_idempotent": 0,
        "retry": "",
        "note": "",
    }
    row.update(over)
    return row


async def _load(mocker, *rows: dict) -> None:
    """把给定元数据灌进缓存（走真实解析路径）。"""
    mocker.patch(
        "src.db.mcp_meta_repository.list_meta_rows",
        new=mocker.AsyncMock(return_value=list(rows)),
    )
    await mcp_meta.load_policies(object())


class TestMcpSourceInApproval:
    """MCP 工具进审批配置（G2 三缺口之一：外部工具此前永不弹窗）。"""

    async def test_requires_approval_enters_config(self, mocker) -> None:
        """登记了 requires_approval 的 MCP 工具 → 出现在 interrupt_on，**以挂载名为键**。"""
        await _load(
            mocker,
            _row(
                tool_name="run_sql",
                risk_level="high",
                requires_approval=1,
                allowed_decisions='["approve", "reject"]',
            ),
        )

        config = build_hitl_interrupt_on(True)

        assert config is not None
        assert config["exa_run_sql"]["allowed_decisions"] == ["approve", "reject"]

    async def test_non_approval_mcp_tool_absent(self, mocker) -> None:
        """未声明需审批的 MCP 工具不出现在 config（不当"全都要审批"）。"""
        await _load(mocker, _row(tool_name="web_search", requires_approval=0))

        config = build_hitl_interrupt_on(True)

        assert config is not None
        assert "exa_web_search" not in config

    async def test_local_tools_still_present(self, mocker) -> None:
        """两个来源**共存**：加 MCP 不挤掉本地工具（回归风险点）。"""
        await _load(mocker, _row(tool_name="run_sql", requires_approval=1,
                                 allowed_decisions='["approve" ]'))

        config = build_hitl_interrupt_on(True)

        assert config is not None
        assert "run_code_in_sandbox" in config, "本地高危工具仍在"
        assert "exa_run_sql" in config, "MCP 工具也进来了"

    async def test_no_mcp_rows_is_fine(self, mocker) -> None:
        """MCP 表空 → 行为等同改造前（本地工具照常）。"""
        await _load(mocker)

        config = build_hitl_interrupt_on(True)

        assert config is not None
        assert config["run_code_in_sandbox"]["allowed_decisions"] == [
            "approve",
            "edit",
            "reject",
        ]


class TestMcpFailFast:
    """fail-fast 不变量**同样约束 MCP 来源**——否则又是一种"静默不审批"。"""

    async def test_mcp_approval_without_decisions_raises(self, mocker) -> None:
        """MCP 声明需审批却没配 allowed_decisions → ValueError（不静默跳过）。"""
        await _load(mocker, _row(tool_name="run_sql", requires_approval=1))

        with pytest.raises(ValueError, match="exa_run_sql"):
            build_hitl_interrupt_on(True)

    async def test_disabled_skips_everything(self, mocker) -> None:
        """hitl_enabled=False → None（连校验都不做：不挂审批就不查配置）。"""
        await _load(mocker, _row(tool_name="run_sql", requires_approval=1))

        assert build_hitl_interrupt_on(False) is None
