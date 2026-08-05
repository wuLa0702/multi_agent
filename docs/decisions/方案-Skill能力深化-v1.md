# Skill 能力深化方案 v1（多文件技能 + 模板体系 · 评审稿）

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-05
> 📝 **版本变更记录**（永久保存，只追加不删除）：
> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1 | 2026-08-05 | 初版：官方 skills 规范（frontmatter/多文件目录/渐进式披露）vs 项目现状差距盘点——§3 设计（多文件技能规范 / 模板体系 / 渐进式披露 / allowed_tools 联动 / 生命周期）；§4 **完整技能示例**（研究报告技能：目录树 + 全文件内容）；§7 完整核心代码 |

> **目录**：
> - §1 总：背景、目标与范围
> - §2 分·现状盘点（官方规范 vs 项目现状差距）
> - §3 分·设计（多文件技能规范 / 模板体系 / 渐进式披露 / allowed_tools 联动 / 生命周期）
> - §4 分·完整技能示例（研究报告技能——模板 + 实例数据）
> - §5 分·兼容方案
> - §6 总·优先级与风险自检
> - §7 分·完整核心代码（模板生成器 / installer 多文件增量）

> **关联文档**：
> - 官方 skills：https://docs.langchain.com/oss/python/deepagents/skills（Agent Skills 规范，agentskills.io）
> - 目录重构：`docs/decisions/方案-Skills目录体系重构-v1.md`（本方案的前置基础篇）
> - 沙箱能力：`docs/decisions/方案-沙箱能力开发计划-v1.md`（技能的 scripts/ 执行闭环）

---

## 1. 总：背景、目标与范围

### 1.1 背景

项目技能能力现状：SkillMarket 安装**单文件** SKILL.md（installer.py 下载
`SKILL.md` 写入 `data/skills/skill_md/{name}/`）；`pdf` 技能实测暴露差距——
其正文引用 `REFERENCE.md`/`FORMS.md` 配套文件，但**安装器只装了 SKILL.md 单文件**，
配套文件缺失，技能能力打折。

官方规范（deepagents skills / Agent Skills 规范）：**技能 = 目录**——
`SKILL.md`（frontmatter + 指令）+ 可选 `scripts/`（脚本）+ `references/`（参考）
+ `assets/`（模板/数据）；**渐进式披露**（启动只加载 name+description，
激活时才读全文，防上下文膨胀）。

### 1.2 目标

1. **多文件技能落地**：技能 = 目录（SKILL.md + scripts + references + assets）——
   补齐 installer 多文件下载能力
2. **技能模板体系**：项目自己的技能模板（目录骨架 + SKILL.md 模板 + 配套约定），
   新建技能用模板生成
3. **完整技能示例**：一个真实的多文件技能（模板 + 实例数据全量展示，§4）
4. **能力联动**：allowed_tools（技能声明所需工具）与权限体系结合；
   技能 scripts/ 与沙箱执行闭环

### 1.3 范围

| 在本方案内 | 不在本方案内 |
|-----------|-------------|
| 多文件技能规范 + 模板体系 + 完整示例 | 技能市场端改造（Smithery 协议，外部依赖） |
| installer 多文件下载增量（§7） | 技能版本管理/依赖解析 |
| allowed_tools 声明与权限联动设计 | 技能自动评测体系 |
| 渐进式披露配置确认 | 跨项目技能共享平台 |

---

## 2. 分·现状盘点

### 2.1 官方规范要点（deepagents skills / Agent Skills）

| 维度 | 官方规范 |
|------|---------|
| 技能形态 | **目录**：`skills/<name>/SKILL.md` + 可选 `scripts/`、`references/`、`assets/` |
| frontmatter | `name`（必填）/ `description`（必填 ≤1024 字符）/ `license`（可选）/ `compatibility`（可选 ≤500）/ `metadata`（可选）/ `allowed_tools`（可选，本项目源码 skills.py:352 支持解析） |
| 加载机制 | **渐进式披露**：启动只注入 name+description 摘要；技能激活（agent 判断相关）才读全文与配套文件——防上下文膨胀 |
| 使用方式 | agent 读到摘要 → 判断任务相关 → 按指令激活 → 按需读 scripts/references/assets |
| 可组合性 | 单 agent 可挂多个技能（各自独立能力域） |

### 2.2 项目现状 vs 差距

| 项 | 项目现状 | 差距 |
|----|---------|------|
| 技能形态 | 单文件 SKILL.md（installer.py:77 `target_dir / "SKILL.md"`） | ❌ 无配套文件——pdf 技能实测缺 REFERENCE.md/FORMS.md |
| frontmatter | 解析支持 name/description/license/metadata/allowed_tools（SkillsMiddleware 原生） | ✅ 已具备（deepagents 自带），未利用 allowed_tools |
| 渐进式披露 | SkillsMiddleware 原生支持（`skills=["/skills/market/"]` 挂载） | ✅ 已启用，未利用摘要分层（技能全文过大时） |
| 模板体系 | 无 | ❌ 新建技能无骨架 |
| 技能示例 | pdf 技能（单文件） | ❌ 无多文件完整示例 |
| 与权限联动 | 技能目录只读（PolicyBackend） | ✅ 已具备 |
| 与沙箱联动 | 无 | ❌ 技能的 scripts/ 无执行闭环 |

---

## 3. 分·设计

### 3.1 多文件技能规范（项目标准）

```
data/skills/skill_md/<skill-name>/        ← 技能 = 目录（安装落点）
├── SKILL.md          # 必填：frontmatter + 指令正文（激活入口）
├── scripts/          # 可选：可执行脚本（Python/bash，沙箱执行闭环）
├── references/       # 可选：参考文档（深水区知识，SKILL.md 引用）
└── assets/           # 可选：模板/实例数据（JSON/CSV/MD 模板等）
```

**SKILL.md frontmatter 规范**（项目标准模板字段）：

```yaml
---
name: <技能名>            # 必填，snake_case
description: <一句话说明 + 何时使用>   # 必填 ≤1024 字符（摘要层，渐进披露）
license: <许可证>          # 可选
compatibility: <环境要求>  # 可选（系统包/网络访问，≤500）
allowed_tools:            # 可选：技能激活时需要的工具白名单
  - run_code_in_sandbox
metadata:
  version: "1.0.0"        # 可选：技能版本（SkillMarket 升级判断）
  author: <作者>
---
```

**目录约定**：
- `SKILL.md` 正文 = 激活入口：概览 + 关键指令 + 指向配套文件的引用
  （"详细脚本见 scripts/xxx.py"）——保持入口文件聚焦，深水区下沉
- `scripts/` 脚本 = 可直接执行的成品（沙箱可跑），不是代码片段
- `references/` = 深水区知识（完整 API 手册/排障指南），SKILL.md 按需引用
- `assets/` = 模板与实例数据（新建任务时的起点）

### 3.2 技能模板体系

**模板库**（随项目走，`backend/assets/skills/builtin/`——目录重构方案 B 落点）：
`template/` 子目录 = 标准技能骨架（§4 示例即模板实例化），新建技能流程：

```
技能开发者 → 复制 template/ → 填 frontmatter → 写 SKILL.md 正文
  → scripts/references/assets 按需填充 → 走 SkillMarket 安装/或入 builtin
```

### 3.3 渐进式披露深化

- 现状：SkillsMiddleware 启动注入 name+description 摘要（已启用）——确认配置即可
- 深化点：**技能全文过大时**（>阈值），SKILL.md 正文拆"概览 + 分文件"，
  利用渐进披露的自然分层（激活后才读 references/）——规范写入 §3.1 目录约定

### 3.4 allowed_tools 与权限联动（设计）

- 技能 frontmatter 声明 `allowed_tools`：技能激活时建议授予的工具
- 联动：**声明 ≠ 授权**——工具最终授权仍由权限体系裁决（Permissions/PolicyBackend）；
  allowed_tools 仅作 agent 使用指引 + 审计参考（技能期望的工具集可追踪）
- 落地：SkillsMiddleware 已解析 allowed_tools（skills.py:352）——后续可在
  技能审计日志中记录"技能 X 声明工具集 vs 实际调用"

### 3.5 技能生命周期

```
模板（builtin/template/）
  → 开发（SKILL.md + scripts/references/assets）
  → 安装（SkillMarket installer——v2 支持多文件目录下载，§7）
  → 使用（SkillsMiddleware 渐进披露 → agent 激活 → 按需读配套文件）
  → 执行闭环：scripts/ 经 run_code_in_sandbox 在沙箱跑（隔离）
  → 升级（metadata.version 判断，SkillMarket 后续）
```

---

## 4. 分·完整技能示例（研究报告技能——模板 + 实例数据）

> 用户核心诉求：**完整技能**（模板 + 实例数据），非单文件。以下为完整可落地的
> 示例技能（同时作为 §3.2 模板体系的实例化范本）。

```
data/skills/skill_md/research-report/          ← 技能目录（完整形态）
├── SKILL.md                    # frontmatter + 指令入口
├── scripts/
│   ├── build_report.py         # 报告骨架生成脚本（沙箱可执行）
│   └── sample_data.json        # 脚本实例数据（演示输入）
├── references/
│   └── writing_guide.md        # 报告写作规范（深水区知识）
└── assets/
    └── report_template.md      # 报告模板（新建报告起点）
```

### 4.1 `SKILL.md`（激活入口）

```markdown
---
name: research-report
description: 生成结构化研究报告——当用户需要调研报告、分析总结、资料综述时使用。
  本技能提供报告骨架生成脚本、写作规范与模板；涉及多来源资料汇总时先委派
  搜索子代理收集资料再按本技能组织。
license: MIT
compatibility: Python 3.11+（scripts 需沙箱执行）
allowed_tools:
  - run_code_in_sandbox
metadata:
  version: "1.0.0"
---

# 研究报告生成

## 概览

将多来源调研资料组织为结构化研究报告。三步流程：
1. **收集**：委派 search_agent 收集资料（多轮可并行）
2. **骨架**：运行 `scripts/build_report.py` 生成报告骨架（先创建沙箱工作目录）
3. **撰写**：按 `assets/report_template.md` 填充章节，风格遵循
   `references/writing_guide.md`

## 关键指令

1. 报告结构固定五段：结论先行 → 背景 → 发现（分点+证据）→ 讨论 → 建议
2. 每个发现必须附来源（标题+链接）；无来源信息标注"待核实"
3. 生成骨架后先确认章节覆盖用户问题，再逐节撰写
4. 输出前用 `references/writing_guide.md` 的自检清单过一遍

## 配套文件

- 骨架脚本：`scripts/build_report.py`（用法见文件头注释）
- 写作规范：`references/writing_guide.md`
- 报告模板：`assets/report_template.md`
```

### 4.2 `scripts/build_report.py`（可执行脚本 + 实例数据）

```python
"""报告骨架生成脚本（沙箱可执行）。

用法（沙箱）：python build_report.py sample_data.json
输入：JSON——{"title": 报告标题, "sections": [{"heading": 章节名, "points": [要点...]}]}
输出：Markdown 骨架文件（report_draft.md），含占位与来源标注。

示例数据见同目录 sample_data.json（§4.3）。
"""
import json
import sys
from pathlib import Path


def build_draft(data: dict) -> str:
    """按五段结构生成报告骨架 Markdown。"""
    title = data.get("title", "未命名报告")
    sections = data.get("sections", [])
    lines = [f"# {title}", ""]
    for section in sections:
        lines += [f"## {section['heading']}", ""]
        for point in section.get("points", []):
            lines += [f"- [ ] {point}（来源：待核实）", ""]
    lines += ["## 自检清单", "",
              "- [ ] 每个发现附来源", "- [ ] 结论先行", "- [ ] 无来源信息标注待核实", ""]
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print("用法：python build_report.py <data.json>")
        sys.exit(1)
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path("report_draft.md").write_text(build_draft(data), encoding="utf-8")
    print("骨架已生成：report_draft.md")


if __name__ == "__main__":
    main()
```

### 4.3 `scripts/sample_data.json`（实例数据）

```json
{
  "title": "多 Agent 系统技术调研",
  "sections": [
    {"heading": "背景", "points": ["deepagents 与 LangGraph 的演进关系", "多 Agent 协作模式现状"]},
    {"heading": "发现", "points": ["事件流式 v3 投影机制", "子代理隔离策略对比"]},
    {"heading": "建议", "points": ["执行层走沙箱隔离", "审批链路接入 interrupt"]}
  ]
}
```

### 4.4 `references/writing_guide.md`（深水区知识，节选）

```markdown
# 报告写作规范（深水区：SKILL.md 按需引用，不进主指令上下文）

## 五段结构细则
- 结论先行：首段给出核心结论（1-2 句），供快速决策
- 发现分点：每点 = 主张 + 证据（来源引用）+ 置信度（高/中/低）

## 来源引用格式
- 网页：[标题](URL)
- 无来源：标注（待核实）——绝不编造链接

## 自检清单
1. 结论是否在首段？  2. 每个发现是否有来源？
3. 是否区分事实与推测？  4. 报告是否回答用户原始问题？
```

### 4.5 `assets/report_template.md`（报告模板/实例起点）

```markdown
# <报告标题>

> 结论：<核心结论 1-2 句>

## 背景
<为什么做这份调研>

## 发现
### <发现 1>
- 主张：<内容>
- 证据：<来源>
- 置信度：<高/中/低>

## 讨论
<权衡与局限>

## 建议
<可执行建议>
```

---

## 5. 分·兼容方案

| 项 | 行为 |
|----|------|
| 现有单文件技能（pdf 等） | 兼容——SKILL.md 单文件仍是合法技能（目录形态的超集）；不强制补配套文件 |
| installer 旧版本下载记录 | install_path 记录不变（SKILL.md 路径）；v2 多文件下载新增目录字段 |
| SkillsMiddleware 挂载 | `skills=["/skills/market/"]` 不变——目录扫描自动发现新技能目录 |
| 权限 | 技能目录只读不变；新增 scripts/ 只读（agent 只能读，执行走沙箱） |
| 虚拟路由 | `/skills/market/` 路由不变 |

---

## 6. 总·优先级与风险自检

### 6.1 优先级

| 优先级 | 项 | 内容 | 依赖 |
|--------|----|------|------|
| **P0** | 多文件技能规范落文档 | §3.1 目录约定 + frontmatter 规范（并入目录重构方案实施） | 目录重构方案 B |
| **P0** | 技能模板入库 | `backend/assets/skills/builtin/template/`（§4 示例去实例化） | 目录重构方案 B |
| **P1** | installer 多文件下载 | §7.2 增量（下载目录而非单文件） | P0 |
| **P1** | 完整示例技能入库 | research-report 技能（§4）入 builtin 或市场 | P0 |
| **P2** | allowed_tools 审计联动 | 技能声明工具集 vs 实际调用记录 | 权限体系（已就绪） |
| **P2** | 技能版本升级 | metadata.version 驱动 SkillMarket 升级判断 | — |

### 6.2 风险自检清单

- [ ] **多文件下载的市场协议**：Smithery skills API 是否提供目录下载（含配套文件）？
      若只提供单文件，P1 需扩展安装源（本地打包上传/自定义仓库）——⚠️ 实施第一步核实
- [ ] **scripts 只读 + 沙箱执行闭环**：技能 scripts/ 可读不可写（PolicyBackend）；
      执行必须经 run_code_in_sandbox（内容拷贝进沙箱，不直接执行磁盘文件）
- [ ] **渐进披露收益量化**：技能全文过大的拆分配置（阈值）需实测决定，不拍脑袋
- [ ] **模板质量**：模板是技能体系地基——§4 示例经真实使用验证后再固化
- [ ] **先红后绿**：实施时测试先行（installer 多文件下载用例）；提交前 pytest 全绿

---

## 7. 分·完整核心代码（文档规范 v4）

### 7.1 技能模板生成器（`src/skills/templates.py`，新建）

```python
"""技能模板体系：从内置模板生成新技能目录骨架（方案 §3.2）。

模板源：backend/assets/skills/builtin/template/（目录重构方案 B 落点）；
生成目标：data/skills/skill_md/<name>/（市场技能）或 builtin/（内置技能）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from src.core.paths import get_skill_md_dir

# 标准技能目录骨架（多文件规范 §3.1）
_SUBDIRS = ("scripts", "references", "assets")


def create_skill_from_template(
    name: str, template_dir: Path, *, target: Path | None = None
) -> Path:
    """从模板复制生成技能目录。

    Args:
        name: 技能名（snake_case，目录名）
        template_dir: 模板目录（含 SKILL.md + 子目录骨架）
        target: 生成目标（缺省 data/skills/skill_md/<name>）

    Returns:
        生成的技能目录路径

    Raises:
        FileExistsError: 目标已存在（防覆盖已安装技能）
    """
    target = target or get_skill_md_dir() / name
    if target.exists():
        raise FileExistsError(f"技能目录已存在：{target}——不覆盖（SkillMarket 升级请走安装器）")
    target.mkdir(parents=True)
    for sub in _SUBDIRS:
        (target / sub).mkdir(exist_ok=True)
    shutil.copy2(template_dir / "SKILL.md", target / "SKILL.md")
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
        for field in ("name:", "description:"):
            if field not in text.split("---", 2)[1]:
                problems.append(f"frontmatter 缺少必填字段 {field}")
    return problems
```

### 7.2 installer 多文件下载增量（`src/skills/installer.py`）

```python
"""（installer.py 增量：单文件 → 目录下载，方案 §3.1/P1）

⚠️ 前置核实（§6.2 风险项）：Smithery skills API 是否提供目录下载
（含 scripts/references/assets）。若仅单文件，先扩展安装源。
"""

# 下载技能为目录（单文件版本保持兼容，调用方二选一）：
def install_skill_directory(
    conn, name: str, files: dict[str, str], *, source: str = "market"
) -> str:
    """安装完整技能目录（多文件）。

    Args:
        conn: SQLite 连接（install 记录落库）
        name: 技能名
        files: {相对路径: 内容}——{"SKILL.md": ..., "scripts/build_report.py": ...}
        source: 来源标记（market / builtin）

    Returns:
        安装记录 install_path（技能目录路径）

    Raises:
        FileExistsError: 技能已存在（先卸载）
    """
    from src.skills.templates import validate_skill_dir

    target = get_skill_md_dir() / name
    if target.exists():
        raise FileExistsError(f"技能已存在：{name}——先卸载再安装")
    for rel_path, content in files.items():
        # 路径校验：禁 ../ 与绝对路径（00-security 硬约束）
        parts = rel_path.replace("\\", "/").split("/")
        if rel_path.startswith("/") or any(p == ".." for p in parts):
            raise ValueError(f"技能文件路径不合法：{rel_path}")
        file_path = target / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    problems = validate_skill_dir(target)
    if problems:
        raise ValueError(f"技能目录校验失败：{problems}")
    return str(target)
```

### 7.3 测试设计（增量）

| 用例 | 断言 |
|------|------|
| 模板生成：create_skill_from_template 生成目录骨架 | 目录 + scripts/references/assets 子目录 + SKILL.md 复制 |
| 重复生成 → FileExistsError | 防覆盖已安装技能 |
| validate_skill_dir：缺 SKILL.md / 缺 frontmatter / 缺必填字段 | 问题列表逐项 |
| installer 多文件：安装目录 → 校验通过 + install_path 为目录 | 落盘结构 |
| 路径逃逸：`../x` / 绝对路径 → ValueError | 00-security |
| 现有单文件安装回归 | 兼容 |

---

## 附录：官方 frontmatter 字段表（deepagents skills 文档核实）

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | 技能名 |
| `description` | ✅ | 做什么 + 何时用，≤1024 字符（渐进披露摘要层） |
| `license` | ❌ | 许可证名或引用捆绑 license 文件 |
| `compatibility` | ❌ | 环境要求（系统包/网络访问），≤500 字符 |
| `metadata` | ❌ | 任意键值对 |
| `allowed_tools` | ❌ | 技能激活时的工具白名单（项目 SkillsMiddleware 已支持解析，skills.py:352） |
