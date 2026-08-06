"""Skill 体系测试（方案 Skill 体系 §8.6）：模板 copytree / 校验 / installer 多文件 /
run_skill_script 执行闭环。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 模板生成：copytree 整体复制（含子目录示例文件——评审问题 1 回归）
- 校验：缺 SKILL.md / 缺 frontmatter / 缺必填字段
- installer 多文件：落盘结构 / 路径逃逸拒绝 / 校验门禁
- run_skill_script：读文件→沙箱→执行一步封装（评审问题 2 回归）
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.config import settings
from src.mcp.tools import skill_tool
from src.skills.templates import create_skill_from_template, validate_skill_dir


# ── 模板生成（copytree，评审问题 1）──

def _make_template(tmp_path: Path) -> Path:
    """构造带示例文件的模板目录（SKILL.md + 三子目录各含文件）。"""
    tpl = tmp_path / "template"
    (tpl / "scripts").mkdir(parents=True)
    (tpl / "references").mkdir()
    (tpl / "assets").mkdir()
    (tpl / "scripts" / "__pycache__").mkdir()
    (tpl / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 演示技能\n---\n正文", encoding="utf-8"
    )
    (tpl / "scripts" / "run.py").write_text("print('ok')", encoding="utf-8")
    (tpl / "references" / "guide.md").write_text("深水区", encoding="utf-8")
    (tpl / "assets" / "data.json").write_text("{}", encoding="utf-8")
    (tpl / "scripts" / "__pycache__" / "x.pyc").write_text("", encoding="utf-8")
    return tpl


def test_create_skill_copies_full_tree(tmp_path) -> None:
    """评审问题 1 回归：copytree 整体复制——子目录示例文件一并生成，非空壳。"""
    target = create_skill_from_template("demo", _make_template(tmp_path), target=tmp_path / "demo")

    assert (target / "SKILL.md").exists()
    assert (target / "scripts" / "run.py").read_text(encoding="utf-8") == "print('ok')"
    assert (target / "references" / "guide.md").exists()
    assert (target / "assets" / "data.json").exists()
    assert not (target / "scripts" / "__pycache__").exists(), "排除 __pycache__"


def test_create_skill_duplicate_raises(tmp_path) -> None:
    """重复生成 → FileExistsError（防覆盖已安装技能）。"""
    tpl = _make_template(tmp_path)
    create_skill_from_template("demo", tpl, target=tmp_path / "demo")
    with pytest.raises(FileExistsError):
        create_skill_from_template("demo", tpl, target=tmp_path / "demo")


# ── 技能目录校验 ──

def test_validate_skill_dir_ok(tmp_path) -> None:
    """合法技能目录 → 无问题。"""
    d = tmp_path / "ok"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 演示\n---\n正文", encoding="utf-8"
    )
    assert validate_skill_dir(d) == []


def test_validate_skill_dir_problems(tmp_path) -> None:
    """缺 SKILL.md / 缺 frontmatter / 缺必填字段 → 问题列表逐项。"""
    d = tmp_path / "bad"
    d.mkdir()
    assert any("缺少 SKILL.md" in p for p in validate_skill_dir(d))

    (d / "SKILL.md").write_text("没有 frontmatter", encoding="utf-8")
    problems = validate_skill_dir(d)
    assert "frontmatter" in problems[0]

    (d / "SKILL.md").write_text(
        "---\nname: demo\n---\n正文", encoding="utf-8"
    )
    assert any("description" in p for p in validate_skill_dir(d))


# ── installer 多文件下载 ──

def test_install_skill_directory_writes_tree(monkeypatch, tmp_path) -> None:
    """多文件安装：落盘目录结构 + install_path 为目录。"""
    monkeypatch.setattr("src.skills.installer.get_skill_md_dir", lambda: tmp_path / "skill_md")

    from src.skills.installer import install_skill_directory

    path = install_skill_directory(
        None,
        "demo-skill",
        {
            "SKILL.md": "---\nname: demo-skill\ndescription: 演示\n---\n正文",
            "scripts/run.py": "print('ok')",
        },
    )
    assert Path(path) == tmp_path / "skill_md" / "demo-skill"
    assert (tmp_path / "skill_md" / "demo-skill" / "SKILL.md").exists()
    assert (tmp_path / "skill_md" / "demo-skill" / "scripts" / "run.py").exists()


def test_install_skill_directory_rejects_escape(monkeypatch, tmp_path) -> None:
    """路径逃逸（../ 与绝对路径）→ ValueError（00-security）。"""
    monkeypatch.setattr("src.skills.installer.get_skill_md_dir", lambda: tmp_path / "skill_md")

    from src.skills.installer import install_skill_directory

    with pytest.raises(ValueError, match="路径不合法"):
        install_skill_directory(
            None, "evil", {"SKILL.md": "x", "../escape.txt": "y"}
        )


def test_install_skill_directory_validates(monkeypatch, tmp_path) -> None:
    """校验门禁：缺 frontmatter 必填字段 → ValueError。"""
    monkeypatch.setattr("src.skills.installer.get_skill_md_dir", lambda: tmp_path / "skill_md")

    from src.skills.installer import install_skill_directory

    with pytest.raises(ValueError, match="校验失败"):
        install_skill_directory(None, "bad", {"SKILL.md": "无 frontmatter"})


# ── run_skill_script 执行闭环（评审问题 2）──

@pytest.fixture
def script_env(monkeypatch, tmp_path):
    """技能脚本环境：tmp 技能目录 + mock 沙箱。"""
    skill_dir = tmp_path / "skill_md" / "research-report" / "scripts"
    skill_dir.mkdir(parents=True)
    (skill_dir / "build_report.py").write_text("print('骨架')", encoding="utf-8")
    monkeypatch.setattr(skill_tool, "get_skill_md_dir", lambda: tmp_path / "skill_md")
    monkeypatch.setattr(settings, "sandbox_url", "http://localhost:8080")
    calls = {"run_script": 0}
    monkeypatch.setattr(
        skill_tool.sandbox_adapter, "run_script",
        lambda sandbox, files, entry: calls.update(run_script=calls["run_script"] + 1)
        or f"out:{entry}",
    )
    monkeypatch.setattr(
        skill_tool.sandbox_pool, "get_sandbox", lambda tid: SimpleNamespace(id="sb")
    )
    return calls


def test_run_skill_script_success(script_env) -> None:
    """评审问题 2 回归：读脚本 → 沙箱执行一步封装（entry 不重复拼 python）。"""
    out = skill_tool.run_skill_script("research-report", "build_report.py", args="sample_data.json")
    assert out == "out:build_report.py sample_data.json"
    assert script_env["run_script"] == 1


def test_run_skill_script_not_found(script_env) -> None:
    """脚本不存在 → 友好提示（不中断 run）。"""
    out = skill_tool.run_skill_script("research-report", "missing.py")
    assert "技能脚本不存在" in out


def test_run_skill_script_rejects_path_escape(script_env) -> None:
    """路径逃逸 → 拒绝提示（00-security）。"""
    for bad in ("../x.py", "/etc/passwd"):
        out = skill_tool.run_skill_script("research-report", bad)
        assert "路径不合法" in out


def test_run_skill_script_no_url(script_env, monkeypatch) -> None:
    """sandbox_url 空 → 降级提示。"""
    monkeypatch.setattr(settings, "sandbox_url", "")
    assert "沙箱不可用" in skill_tool.run_skill_script("research-report", "build_report.py")
