"""技能模板体系：从内置模板生成新技能目录（方案 Skill 体系 §4.2/§8.2）。

模板源：backend/assets/skills/builtin/template/（含 SKILL.md + 三配套目录示例）；
生成目标：data/skills/skill_md/<name>/（市场技能）或 builtin/（内置技能）。

⚠️ 评审问题 1 修复（v1.1）：copytree 整体复制模板目录（含子目录示例文件），
非"只建空子目录 + 只复制 SKILL.md"的空壳。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from src.core.paths import get_skill_md_dir

# 模板目录中排除的文件（运行时产物/缓存）
_EXCLUDE_DIRS = {"__pycache__"}


def create_skill_from_template(
    name: str, template_dir: Path, *, target: Path | None = None
) -> Path:
    """从模板整体复制生成技能目录（copytree，含子目录示例文件）。

    Args:
        name: 技能名（snake_case，目录名）
        template_dir: 模板目录（SKILL.md + scripts/references/assets 含示例）
        target: 生成目标（缺省 data/skills/skill_md/<name>）

    Returns:
        生成的技能目录路径

    Raises:
        FileExistsError: 目标已存在（防覆盖已安装技能）
    """
    target = target or get_skill_md_dir() / name
    if target.exists():
        raise FileExistsError(f"技能目录已存在：{target}——不覆盖（SkillMarket 升级请走安装器）")
    shutil.copytree(
        template_dir,
        target,
        ignore=shutil.ignore_patterns(*_EXCLUDE_DIRS),
    )
    return target


def validate_skill_dir(skill_dir: Path) -> list[str]:
    """技能目录合法性校验（安装前/模板生成后调用）。

    Args:
        skill_dir: 技能目录

    Returns:
        问题列表（空 = 合法）
    """
    problems: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        problems.append("缺少 SKILL.md（技能必填入口）")
    else:
        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            problems.append("SKILL.md 缺少 YAML frontmatter（--- 开头）")
        try:
            frontmatter = text.split("---", 2)[1]
        except IndexError:
            frontmatter = ""
        for field in ("name:", "description:"):
            if field not in frontmatter:
                problems.append(f"frontmatter 缺少必填字段 {field}")
    return problems
