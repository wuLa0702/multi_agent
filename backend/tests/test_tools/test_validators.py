"""校验器单测（阶段 1.2）：契约（None=通过 / str=拦截）+ 统一审计。"""

from __future__ import annotations

import json
import logging

from src.tools.runtime import validators


# ── validate_url ──

def test_validate_url_allows_http() -> None:
    """http/https 放行。"""
    assert validators.validate_url("https://example.com/a?b=1") is None
    assert validators.validate_url("http://example.com") is None


def test_validate_url_blocks_other_scheme() -> None:
    """非 http/https 协议拦截。"""
    assert validators.validate_url("file:///etc/passwd") == "URL 注入/协议非法"


def test_validate_url_blocks_injection_chars() -> None:
    """含引号/分号/尖括号等注入字符拦截。"""
    assert validators.validate_url("https://x.com/a'b") is not None
    assert validators.validate_url("https://x.com/a;rm") is not None


# ── validate_command ──

def test_validate_command_blocks_dangerous_prefix() -> None:
    """危险命令前缀拦截。"""
    assert validators.validate_command("rm -rf /") is not None
    assert validators.validate_command("mkfs.ext4 /dev/sda") is not None


def test_validate_command_pierces_sudo_prefix() -> None:
    """`sudo ` 前缀穿透后仍应拦截（防绕过）。"""
    assert validators.validate_command("sudo rm -rf /") is not None


def test_validate_command_allows_normal() -> None:
    """普通命令放行。"""
    assert validators.validate_command("pip install pandas") is None


# ── validate_sandbox_path ──

def test_validate_sandbox_path_allows_relative() -> None:
    """workspace 相对路径放行。"""
    assert validators.validate_sandbox_path("main.py") is None
    assert validators.validate_sandbox_path("sub/x.py") is None


def test_validate_sandbox_path_blocks_traversal() -> None:
    """`../` 逃逸拦截（含反斜杠变体）。"""
    assert validators.validate_sandbox_path("../etc/passwd") is not None
    assert validators.validate_sandbox_path("a\\..\\b") is not None


def test_validate_sandbox_path_blocks_absolute() -> None:
    """绝对路径拦截。"""
    assert validators.validate_sandbox_path("/etc/passwd") is not None


# ── 统一审计 ──

def test_block_is_audited(caplog) -> None:
    """拦截必须落 `security.blocked` 审计（@security_audit 统一记）。

    审计落地批次 1：断言从**原始 JSON 文本**改为**解析后按字段判**
    （文本断言会随字段顺序/格式微调而脆断；按字段判才是语义断言）。
    """
    with caplog.at_level(logging.INFO, logger="audit"):
        validators.validate_url("file:///etc/passwd")

    records = [json.loads(r.getMessage()) for r in caplog.records if r.name == "audit"]
    assert any(
        r["layer"] == "security" and r["event"] == "security.blocked" and r["tool"] == "fetch_url"
        for r in records
    ), f"应落 security.blocked 审计：{records}"


def test_pass_is_not_audited(caplog) -> None:
    """通过不记审计（避免日志噪音）。"""
    with caplog.at_level(logging.INFO, logger="audit"):
        validators.validate_url("https://example.com")
    assert not caplog.records


def test_every_validator_is_audited() -> None:
    """不变量：三个校验器都必须挂 @security_audit（防新增校验器时漏挂）。"""
    for fn in (
        validators.validate_url,
        validators.validate_command,
        validators.validate_sandbox_path,
    ):
        assert hasattr(fn, "__wrapped__"), f"{fn.__name__} 未挂 @security_audit"
