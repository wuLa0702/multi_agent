"""安全机制单测（设计-安全机制 v1 §7.1 用例 1-10）。

覆盖：路径校验（合法/绝对/穿越/协议）/ FileRef 对象校验 / URL 注入校验 / 拦截事件。
"""

from __future__ import annotations

import pytest

from src.agent.tools.fetch_tool import _validate_url, fetch_url
from src.core.permissions import validate_workspace_path


class TestValidateWorkspacePath:
    """D1 文件路径白名单校验（用例 1-4）。"""

    def test_valid_relative(self) -> None:
        assert validate_workspace_path("reports/x.md") is True

    def test_absolute_path_rejected(self) -> None:
        assert validate_workspace_path("/etc/passwd") is False

    def test_parent_traversal_rejected(self) -> None:
        assert validate_workspace_path("../../secret.txt") is False

    def test_external_protocol_rejected(self) -> None:
        assert validate_workspace_path("file:///etc/passwd") is False
        assert validate_workspace_path("https://evil.com/x") is False

    def test_empty_rejected(self) -> None:
        assert validate_workspace_path("") is False


class TestFileRef:
    """D2 文件引用对象校验（用例 5-6）。"""

    def test_valid_path_ok(self) -> None:
        from src.schemas.file import FileRef

        ref = FileRef(name="报告.md", path="reports/x.md")
        assert ref.path == "reports/x.md"

    def test_invalid_path_raises(self) -> None:
        from pydantic import ValidationError
        from src.schemas.file import FileRef

        with pytest.raises(ValidationError):
            FileRef(name="x", path="../../secret.txt")


class TestFetchUrlInjection:
    """D3 URL 注入校验（用例 7-8）。"""

    def test_valid_url(self) -> None:
        assert _validate_url("https://api.deepseek.com/pricing") is True

    def test_javascript_protocol_rejected(self) -> None:
        assert _validate_url("javascript:alert(1)") is False

    def test_file_protocol_rejected(self) -> None:
        assert _validate_url("file:///etc/passwd") is False

    def test_injection_chars_rejected(self) -> None:
        assert _validate_url("https://x.com/a;rm -rf") is False
        assert _validate_url("https://x.com/\"onerror=alert") is False

    def test_fetch_url_invalid_degrades(self) -> None:
        """注入 URL → 降级提示（不中断）。"""
        out = fetch_url("javascript:alert(1)")
        assert "链接格式非法" in out


class TestAuditBlocked:
    """D5 安全拦截事件（用例 9-10）。"""

    def test_blocked_event_logged(self, audit_records) -> None:
        from src.agent.middlewares.tool_audit import ToolAuditMiddleware

        mw = ToolAuditMiddleware()
        mw._audit_blocked("fetch_url", "注入 URL")
        rec = audit_records[-1]
        assert rec.getMessage()  # 审计 logger 记录 JSON 行
