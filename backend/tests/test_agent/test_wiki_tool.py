"""write_wiki 工具单测（阶段 2.2.8）。

此前无直接行为测试（只有工具清单里的名字断言），本次补齐。
全 mock：不连 wiki 服务。
"""

from __future__ import annotations

import pytest

from src.core.errors import ToolErrorCode
from src.wiki.export_service import WikiExportError
from src.tools.impl import wiki as wiki_mod
from src.tools.impl.wiki import write_wiki


def test_empty_content_is_invalid_arg() -> None:
    """内容为空 → invalid_arg（不可重试：空内容重试还是空）。"""
    result = write_wiki("调研结论-x", "   ")
    assert result.status == "error"
    assert result.error_code == ToolErrorCode.INVALID_ARG
    assert result.retryable is False
    assert "内容为空" in result.message


def test_success_returns_written_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """成功 → ok 信封，data.path 取 wiki 侧回传的 path。"""
    monkeypatch.setattr(
        wiki_mod, "export_to_wiki", lambda path, content, title: {"path": "调研结论-新"}
    )
    result = write_wiki("调研结论-x", "正文", title="标题")

    assert result.status == "ok"
    assert result.error_code == ""
    assert result.data == {"path": "调研结论-新"}
    assert "已写入 wiki: 调研结论-新" in result.message


def test_falls_back_to_input_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """wiki 侧未回传 path → 回落入参 path（不产生 None）。"""
    monkeypatch.setattr(wiki_mod, "export_to_wiki", lambda path, content, title: {})
    result = write_wiki("知识-x", "正文")
    assert result.data == {"path": "知识-x"}


def test_blank_title_uses_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """title 缺省 → 用 path 兜底（不把空标题发给 wiki）。"""
    seen: dict[str, str] = {}

    def _capture(path, content, title):
        seen["title"] = title
        return {"path": path}

    monkeypatch.setattr(wiki_mod, "export_to_wiki", _capture)
    write_wiki("知识-y", "正文")
    assert seen["title"] == "知识-y"


def test_wiki_failure_is_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """wiki 侧故障 → upstream_error（上游系统问题，非我方参数错）。"""

    def _raise(path, content, title):
        raise WikiExportError("连接 wiki 超时")

    monkeypatch.setattr(wiki_mod, "export_to_wiki", _raise)
    result = write_wiki("知识-z", "正文")

    assert result.status == "error"
    assert result.error_code == ToolErrorCode.UPSTREAM_ERROR
    assert "写入 wiki 失败" in result.message
