# Skills 目录体系重构方案 v1（评审稿）

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-05
> 📝 **版本变更记录**（永久保存，只追加不删除）：
> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1 | 2026-08-05 | 初版：对话讨论总结（技能目录四层混淆 + skill-resources 三问题）——§2 现状盘点与已清理项；§3 方案对比与推荐 B（backend/assets/skills/builtin/）；§4 影响面；§5 兼容；§6 优先级风险；§7 完整核心代码（paths 增量 / gitignore / 测试影响） |

> **目录**：
> - §1 总：背景、目标与范围
> - §2 分·现状盘点（四层目录全景 / 问题清单 / 已执行清理项）
> - §3 分·方案设计（A/B/C 对比 / 推荐 B / 命名原则）
> - §4 分·影响面清单
> - §5 分·兼容方案
> - §6 总·优先级与风险自检
> - §7 分·完整核心代码（paths.py 增量 / .gitignore / 测试影响）

> **关联文档**：
> - 设计 v3：`docs/decisions/CompositeBackend文件存储-设计-v3.md`（/skills/static/ 路由）
> - 深化改造：`docs/decisions/方案-CompositeBackend深化改造-v1.md`（技能只读权限）
> - 路径：`docs/方案/后端基础架构-v1.md`（路径自适应）
> - 文档规范：`docs/文档规范.md`（v4：设计方案必含核心代码）

---

## 1. 总：背景、目标与范围

### 1.1 背景

对话讨论（2026-08-05）沉淀：项目存在**四个同名"skills"目录**，职责混淆；
用户指出 `skill-resources/` 存在**位置、命名、gitignore 三处问题**，并确认
`.claude/skills/`（Clowder AI 平台注入）不参与本项目治理。

### 1.2 目标

1. **三层各居其位**：src=代码 / data=数据 / assets=资产——语义自明
2. **命名表达内容**：`builtin`（内置）替代误导的 `resources`
3. **修正 gitignore 矛盾**：固定资产必须入库（当前被忽略 = 未来漏提交真实技能文件）
4. 清理历史遗留（空目录）

### 1.3 范围

| 在本方案内 | 不在本方案内 |
|-----------|-------------|
| skill-resources 迁移 + 改名（方案 B） | `.claude/skills/`（平台注入，用户确认不管） |
| .gitignore 修正（解除 skill-resources 忽略） | `data/skills/skill_md` 结构变更（防御性设计保留） |
| 空目录 backend/src/agent/skills/ 清理 | SkillMarket 代码层（src/skills）重构 |
| 本方案**只写方案不改代码**（用户指示） | 虚拟路由 /skills/static/ 变更（不变） |

---

## 2. 分·现状盘点

### 2.1 四层目录全景（代码级核实，2026-08-05）

| 目录 | 层 | 职责 | 数据性质 | Agent 权限 |
|------|----|------|---------|-----------|
| `backend/src/skills/` | 代码层 | SkillMarket 逻辑：installer.py（下载 SKILL.md → data/skills/skill_md/{name}/）+ marketplace.py（Smithery 适配） | 代码（入库） | — |
| `data/skills/skill_md/` | 数据层 | 市场安装的 SKILL.md 技能（SkillsMiddleware 扫描源，`/skills/market/` 路由） | 运行时数据（不入库） | 🔒 只读 |
| `skill-resources/`（项目根） | 资产层 | 内置静态技能（`/skills/static/` 路由）——随项目走的固定资产 | **资产（应入库）** | 🔒 只读 |
| `.claude/skills/` | 平台层 | Clowder AI 注入 cat-cafe 技能（symlink）——**不参与本项目治理** | 环境注入 | — |

### 2.2 问题清单

| # | 问题 | 位置 | 严重度 |
|---|------|------|--------|
| 1 | 资产层放根目录裸放，不规范 | `skill-resources/` | 中 |
| 2 | 命名 `skill-resources` 无法表达"内置静态" | 同上 | 中 |
| 3 | **被 .gitignore 忽略**——"固定资产"与"忽略"自相矛盾，未来放真实技能文件会漏提交 | `.gitignore` 的 `skill-resources/` 行 | **高** |
| 4 | 空目录 `backend/src/agent/skills/`（零文件，2026-08-02 建） | 同上 | 低 |
| 5 | `data/skills/skill_md` 命名 `md` 含义不清 | 数据层 | 低（已在文档澄清：SKILL.md 格式） |

### 2.3 已执行清理项（对话中完成，2026-08-05）

| 项 | 状态 |
|----|------|
| 删除遗留 `backend/data/`（agent_demo_ws 无引用；agent_demo.py 实际用项目根 data/） | ✅ 已执行（f9fac2e） |
| agent_demo.py 过时注释修正（旧路径 backend/data/...） | ✅ 已执行（f9fac2e） |
| `.gitignore` 改 `.venv*/`（.venv312 解释器环境） | ✅ 已执行（d5f0a1c） |

---

## 3. 分·方案设计

### 3.1 命名原则

```
src    = 代码（怎么装技能）——保持
data   = 运行时数据（装好的技能）——保持
assets = 随项目走的固定资产（内置技能）——新引入
```

三层前缀语义自明；`builtin` 表达"内置"，消除 `resources` 的误导。

### 3.2 方案对比

| 方案 | 资产层位置 | 命名 | 优点 | 缺点 |
|------|-----------|------|------|------|
| **B（推荐）** | `backend/assets/skills/builtin/` | builtin | 三层语义统一；命名直白；预留扩展位（未来内置技能变体可平级） | 改动稍大（路径函数+注释+ignore） |
| A（最小） | `backend/assets/skills/` | 同上 | 简单，无 builtin 层 | 无扩展位 |
| C（只移位不改名） | `backend/assets/skills/` | 保留 skill-resources 名 | 改动最小 | 名字仍误导 |

**推荐 B**：迁移成本与 A 相同（同名层级仅多一层目录），语义收益最大。

### 3.3 目标结构（方案 B）

```
backend/
  src/skills/           代码层（SkillMarket 逻辑）——不动
  assets/
    skills/
      builtin/          资产层（内置静态技能）← skill-resources 迁入
data/
  skills/
    skill_md/           数据层（市场技能）——不动
```

---

## 4. 分·影响面清单

| 项 | 改动 | 风险 |
|----|------|------|
| `paths.py get_static_skills_dir` | 默认路径 → `backend/assets/skills/builtin/`；`SKILL_RESOURCES_DIR` 环境变量**保留兼容**（§5） | 低 |
| `backend.py` 路由 | 仅注释更新——虚拟路由 `/skills/static/` 不变，磁盘映射变 | 无代码改动 |
| `.gitignore` | **移除 `skill-resources/` 忽略行**；确认 `assets/` 不被任何忽略规则误伤 | 低 |
| 迁移方式 | 直接移动（`skill-resources/` 从未入库（?? 状态），git 历史零负担，无需 git mv） | 无 |
| 测试 | `test_static_skills_dir_auto_init` 用 SKILL_RESOURCES_DIR 指向 tmp——不受影响；自动初始化 README 逻辑照旧 | 低 |
| 空目录 | 删除 `backend/src/agent/skills/` | 无 |

---

## 5. 分·兼容方案

| 场景 | 行为 |
|------|------|
| 已配置 `SKILL_RESOURCES_DIR`（部署/本地） | 环境变量优先——**零破坏**，指向旧位置也照常工作 |
| 未配置（默认） | 新默认路径 `backend/assets/skills/builtin/`（自动初始化 README） |
| 虚拟路由 | `/skills/static/` 映射不变（agent 视角零感知） |
| 权限 | 只读策略（PolicyBackend）不变——只换磁盘根，不换权限语义 |

---

## 6. 总·优先级与风险自检

### 6.1 优先级

| 优先级 | 项 | 内容 |
|--------|----|------|
| **P0** | gitignore 矛盾修正 | 移除 skill-resources 忽略（**防未来漏提交**，最高优先） |
| **P0** | 资产层迁移 + 改名 | skill-resources → backend/assets/skills/builtin/（paths.py + 注释） |
| **P1** | 空目录清理 | 删除 backend/src/agent/skills/ |

### 6.2 风险自检清单

- [ ] **assets 不被误忽略**：`assets/` 目录名需确认不在任何 gitignore 规则内（如前端 assets 规则是否误伤）
- [ ] **环境变量兼容**：SKILL_RESOURCES_DIR 读取逻辑保留，测试覆盖两种路径来源
- [ ] **虚拟路由零感知**：/skills/static/ 路由不改——agent/权限/审计不受影响
- [ ] **文档同步**：v3 设计文档 §2.2 中 skill-resources 引用同步更新（实施时）
- [ ] **先红后绿**：实施时测试先行（paths 单测适配）；提交前 pytest 全绿

### 6.3 后续（用户预留）

本方案是"技能目录讨论与改进"的第一篇——后续用户会追加其他技能相关方案，
本文件作为该主题系列的基础篇（命名/分层原则沉淀，后续方案复用引用）。

---

## 7. 分·完整核心代码（文档规范 v4：设计方案必含核心代码）

### 7.1 `core/paths.py` 增量（默认路径迁移）

```python
def get_static_skills_dir() -> Path:
    """内置静态技能目录（/skills/static/ 路由，Agent 只读）。

    SKILL_RESOURCES_DIR 环境变量优先（兼容旧配置，零破坏）；缺省
    backend/assets/skills/builtin/（2026-08-05 方案 B：资产层入 backend，
    命名 builtin 表达内置；原 skill-resources 迁入）；不存在时自动初始化
    README 模板（启动自检容错）。
    """
    env = os.getenv("SKILL_RESOURCES_DIR")
    base = (
        Path(env)
        if env
        else Path(__file__).resolve().parents[1] / "assets" / "skills" / "builtin"
        # parents[1] = backend（src/core → backend/src → backend）
    )
    base.mkdir(parents=True, exist_ok=True)
    if not (base / "README.md").exists():
        (base / "README.md").write_text(
            "# builtin skills\n\n内置静态技能目录（Agent 只读）。", encoding="utf-8"
        )
    return base
```

> ⚠️ 路径计算核对：现实现为 `parents[3]`（backend/src/core → 项目根）。
> 方案 B 目标为 `backend/assets/skills/builtin/` → 应为 `parents[1] / "assets" / "skills" / "builtin"`。
> 实施时以实际目录树为准（paths.py 单测断言路径）。

### 7.2 `.gitignore` 增量（解除固定资产忽略）

```gitignore
# 移除（原 skill-resources/ 忽略行——固定资产必须入库）：
- skill-resources/

# 确认 assets/ 不被忽略（若前端 assets 规则存在需精确化，勿用裸 assets/ 忽略）
```

### 7.3 测试影响（test_backend.py）

```python
def test_static_skills_dir_auto_init(tmp_path, monkeypatch) -> None:
    """路径：get_static_skills_dir 不存在时自动创建 + README 模板（现状用例，不受影响）。"""
    target = tmp_path / "skill-resources"
    monkeypatch.setenv("SKILL_RESOURCES_DIR", str(target))   # 环境变量优先路径
    d = get_static_skills_dir()
    assert d == target
    assert (target / "README.md").exists()
```

- 上述用例走环境变量路径——**零改动**；新增 1 用例断言**默认路径**为新目录树
  （monkeypatch 不设环境变量 + 临时 cwd 校验 parents[1] 解析）
- `test_skills_routes_readonly_in_composite` 用 monkeypatch get_static_skills_dir ——零改动
