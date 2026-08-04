# CompositeBackend 文件存储 — 设计文档（评审稿）

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-04
> 📝 **版本变更记录**（永久保存，只追加不删除）：

> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1.2 | 2026-08-04 | §2.1 补「与现有目录映射核对表」（5 路由逐一核对无冲突）+「tools（代码）vs skills（文件）边界」澄清 +「skill_md 共写语义」标注（SkillMarket 写入 / Agent 只读约定） |
> | v1.1 | 2026-08-04 | §2.1 多路由组合（4 类：记忆/内置技能/市场技能/导出）+ 沙盒澄清表 + 参考配置对照表；§2.2 完整核心代码；§2.3 多路由测试 |
> | v1 | 2026-08-04 | 初版：CompositeBackend 组合存储设计（B.0 前置落地）——Agent 文件落盘 + 记忆文件路由 |

> **目录**：
> - §1 总：背景与目标
> - §2 分：设计（架构 / 核心代码 / 生命周期 / 测试）
> - §3 总：自检清单与后续
>
> **关联文档**：
> - 持久化计划：`docs/decisions/持久化能力开发计划-Checkpointer与Store-v1.md`（§B.0 前置约束 / §B.1 文件记忆）
> - 架构：`docs/架构/多agent项目-架构目录-v1.md`（§2 目录树 / 依赖单向）
> - 路径：`docs/方案/后端基础架构-v1.md`（路径自适应）

---

## 1. 总：背景与目标

### 1.1 背景

持久化计划 §B.0 已确认前置约束：

> `MemoryMiddleware` 构造签名**强依赖 `backend: BackendProtocol`**——记忆文件读写
> 走 backend 文件 API。项目当前用 deepagents 默认 StateBackend（进程内存），
> **直接启用 MemoryMiddleware 会出现文件读写路径异常**。

同时，Agent 的文件操作能力（deepagents `FilesystemMiddleware` 提供的
ls/read_file/write_file/edit_file/glob/grep）也挂在 StateBackend（内存）上——
**Agent 写的文件不落盘**，重启即失。

### 1.2 目标

1. **组合存储**：用 `CompositeBackend` 按路径前缀路由——
   - Agent 常规文件操作 → 真实磁盘（`data/workspace/`）
   - 记忆文件（`/memories/` 前缀）→ 独立目录（`data/memory/`）
2. **为 MemoryMiddleware 启用铺路**（B.1 前置完成）
3. 保持依赖单向：`api → agent → core`（backend 工厂归 `core/`）

### 1.3 范围

| 在本设计内 | 不在本设计内 |
|-----------|-------------|
| `core/backend.py` 工厂 + `create_deep_agent(backend=...)` 挂载 | MemoryMiddleware 启用（B.1，后续） |
| 路径映射与目录隔离 | 沙箱后端（OpenSandbox 独立层） |
| 测试（落盘/路由/越权） | 云端部署细节 |

---

## 2. 分：设计

### 2.1 架构：CompositeBackend 多路由组合（v1.1）

```
Agent（FilesystemMiddleware / 未来 MemoryMiddleware）
        │ backend=CompositeBackend
        ▼
┌──────────────────────────────────────────────────────┐
│ CompositeBackend                                     │
│  default : FilesystemBackend(data/workspace)         │  ← Agent 文件工作区
│  routes  : {                                         │
│    "/memories/":       FilesystemBackend(data/memory)│  ← 记忆文件
│    "/skills/static/":  FilesystemBackend(skill-resources/)│  ← 内置静态技能（只读）
│    "/skills/market/":  FilesystemBackend(data/skills/skill_md)│  ← 市场下载技能
│    "/exports/":        FilesystemBackend(data/exports)│  ← 导出报告
│  }                                                   │
└──────────────────────────────────────────────────────┘
```

**路径映射表**：

| 路径前缀 | 落盘位置 | 用途 |
|---------|---------|------|
| `/`（默认） | `data/workspace/` | Agent 常规文件操作（ls/read/write/edit） |
| `/memories/` | `data/memory/` | 记忆文件（MemoryMiddleware 启用后读写 AGENTS.md 类记忆） |
| `/skills/static/` | `skill-resources/`（项目根，蓝图占位） | 内置静态技能（Agent 只读参考） |
| `/skills/market/` | `data/skills/skill_md/` | 市场下载技能（SkillMarket 已写此目录） |
| `/exports/` | `data/exports/` | 导出报告/文档（Agent 写报告落盘） |

**多 backend 隔离的理由**：每个路由 root_dir 物理分离（虚拟根各自独立）——
Agent 的 workspace 操作碰不到记忆/技能/导出目录；各用途目录互不污染。

#### 与现有目录映射核对（v1.2 新增，确认无冲突）

| 设计路由 | 物理目录 | 现有功能 | 一致性 |
|---------|---------|---------|--------|
| `/`（default） | `data/workspace/` | Agent 文件操作（路径函数已建） | ✅ 无冲突 |
| `/memories/` | `data/memory/` | 规划（B.1 记忆） | ✅ 无冲突 |
| `/skills/static/` | `skill-resources/` | 蓝图占位（**当前不存在，实施时创建**） | ⚠️ 需创建 |
| `/skills/market/` | `data/skills/skill_md/` | SkillMarket 安装写入（installer.py:75） | ✅ 一致 |
| `/exports/` | `data/exports/` | 规划（导出落盘可选） | ✅ 无冲突 |

#### tools（代码）vs skills（文件）边界（v1.2 澄清）

用户疑问"我的 skill 和 tools 好像跟这里不一致？"——**是设计使然，非冲突**：

- **内置代码工具**：`backend/src/mcp/tools/`（Python 函数）+ `mcp/registry.py` 注册表——
  **代码不是文件**，不进 backend 文件路由体系（工具挂载进 Agent 是函数调用）
- **backend 文件路由只管文件类能力**：SKILL.md 技能（/skills/*）、记忆（/memories/）、
  Agent 工作文件（/）、导出（/exports/）
- 与架构文档 §2.1「能力落地位置对照」一致：**tool=代码（注册表）、skill=文件（路由）**

#### skill_md 共写语义（v1.2 标注）

`data/skills/skill_md/` 有两个潜在写入者：
- **SkillMarket**（安装时写，installer.py:75）——统一管理写入
- **Agent**（FilesystemMiddleware）——**只读约定**：技能是加载的，Agent 不应写 /skills/
  （SkillMarket 代码约束 + 文档约定；virtual_mode 限制路径范围）

#### 沙盒澄清（v1.1 新增，回答"我们项目有沙盒呀？"）

**OpenSandbox（执行沙箱）与 Backend（文件存储）是两个独立层**：

| 维度 | OpenSandbox（执行沙箱） | Backend（文件存储） |
|------|------------------------|--------------------|
| 职责 | **隔离代码执行**（不可信代码跑在隔离容器） | **Agent 文件操作**（read/write/ls）落哪里 |
| 归属 | `sandbox/adapter.py`（独立层） | `core/backend.py`（Agent 挂载） |
| 生命周期 | 容器创建/销毁（远程实例） | 无连接（本地目录） |
| 调用方 | `run_code_in_sandbox` 工具 | FilesystemMiddleware / MemoryMiddleware |

参考配置的 `/sandbox_temp/` 实为**文件工作区**（对应我们 default=workspace），
不是执行沙箱——我们的执行隔离已由 OpenSandbox 承担，本设计不改动它。

#### 参考配置对照（v1.1 新增）

| 参考项目配置 | 我们 | 差异说明 |
|------------|------|---------|
| `default=StateBackend()`（内存临时） | `default=FilesystemBackend(workspace)` | 我们更持久：Agent 文件直接落盘，重启不丢 |
| `/sandbox_temp/{thread_id}`（会话隔离工作区） | `/`（workspace 全局） | 会话隔离后置：CompositeBackend 静态路由不支持动态 thread_id，需每会话 backend 或路径约定 |
| `/skills/static/`（内置技能只读） | `/skills/static/` → `skill-resources/` | 新增（蓝图占位目录，实施时创建） |
| `/skills/market/{user_id}` | `/skills/market/` → `data/skills/skill_md/` | 单用户项目无 user_id |
| `/user_export/{user_id}` | `/exports/` → `data/exports/` | 新增（对应前端导出改后端落盘，可选） |

### 2.2 核心代码（完整可运行，v1.1）

**`core/paths.py`**（补 3 个路径函数）：

```python
def get_memory_dir() -> Path:
    """记忆文件目录（MemoryMiddleware 用）：data/memory/，父目录自动创建。"""
    base = get_app_dir() / "memory"
    base.mkdir(parents=True, exist_ok=True)
    return base

def get_exports_dir() -> Path:
    """导出报告目录（/exports/ 路由）：data/exports/，父目录自动创建。"""
    base = get_app_dir() / "exports"
    base.mkdir(parents=True, exist_ok=True)
    return base

def get_static_skills_dir() -> Path:
    """内置静态技能目录（/skills/static/ 路由，蓝图占位）：项目根 skill-resources/。"""
    base = Path(__file__).resolve().parents[3] / "skill-resources"
    base.mkdir(parents=True, exist_ok=True)
    return base
```

**`core/backend.py`**（新建，模块级惰性单例——完整版）：

```python
"""Agent Backend 工厂：CompositeBackend 多路由组合存储（2026-08-04 设计 v1.1）。

- default=workspace：Agent 常规文件操作落盘（非 StateBackend 内存，重启不丢）
- 路由：/memories/ 记忆、/skills/static/ 内置技能（只读）、/skills/market/ 市场技能、
  /exports/ 导出——多用途组合存储（参考项目 4 类路由映射，见设计文档 §2.1）
- FilesystemBackend 无连接资源 → 模块级惰性单例（无需 lifespan，
  区别于 checkpointer/store 的 async 连接）
"""

from __future__ import annotations

from deepagents.backends import CompositeBackend, FilesystemBackend

from src.core.paths import (
    get_exports_dir,
    get_memory_dir,
    get_skill_md_dir,
    get_static_skills_dir,
    get_workspace_dir,
)

_backend: CompositeBackend | None = None


def get_backend() -> CompositeBackend:
    """组合 backend 单例（惰性创建，路径自适应）。"""
    global _backend
    if _backend is None:
        _backend = CompositeBackend(
            default=FilesystemBackend(root_dir=get_workspace_dir(), virtual_mode=True),
            routes={
                "/memories/": FilesystemBackend(root_dir=get_memory_dir(), virtual_mode=True),
                "/skills/static/": FilesystemBackend(root_dir=get_static_skills_dir(), virtual_mode=True),
                "/skills/market/": FilesystemBackend(root_dir=get_skill_md_dir(), virtual_mode=True),
                "/exports/": FilesystemBackend(root_dir=get_exports_dir(), virtual_mode=True),
            },
        )
    return _backend
```

**挂载**（`agent/main_agent.py`）：

```python
from src.core.backend import get_backend

_agent = create_deep_agent(
    ...,
    backend=get_backend(),   # ← Agent 文件操作落盘 + 多路由存储
)
```

### 2.3 生命周期

- `FilesystemBackend` 无连接/无 async 资源 → **模块级惰性单例**（首次 get_backend 创建）
- 区别于 Checkpointer/Store（async 连接需 lifespan init/close）——backend 无需生命周期钩子
- 路径自适应：dev 落 `data/workspace|memory`，prod 落 `/data/workspace|memory`（paths.py 已有机制）

### 2.4 行为变化（StateBackend → FilesystemBackend）

| 能力 | 之前（内存） | 之后（磁盘） |
|------|------------|------------|
| Agent 写文件 | 进程内存，重启即失 | `data/workspace/` 落盘，重启仍在 |
| 文件操作范围 | 虚拟路径 `/` | `data/workspace/` 虚拟根（virtual_mode=True 防越权） |
| 记忆文件 | 无（MemoryMiddleware 未启用） | `/memories/` 路由就绪（B.1 启用时直接用） |

⚠️ 风险：demo 脚本（scripts/agent_demo.py）若依赖内存文件操作需兼容验证（落盘后路径
仍为虚拟 `/`，对 Agent 透明——只需确认工具调用不受影响）。

### 2.5 测试设计（v1.1 多路由）

| 用例 | 断言 |
|------|------|
| 默认路由落盘 | `backend.write("/note.txt")` → `data/workspace/note.txt` 存在 → read 返回内容 |
| 记忆路由 | `backend.write("/memories/facts.md")` → 落 `data/memory/facts.md`（非 workspace） |
| 市场技能路由 | `backend.write("/skills/market/pdf.md")` → 落 `data/skills/skill_md/pdf.md` |
| 导出路由 | `backend.write("/exports/report.md")` → 落 `data/exports/report.md` |
| 内置技能只读语义 | `/skills/static/` 目录由 SkillMarket 代码约束写入；Agent 约定不写（virtual_mode 限制路径） |
| virtual_mode 越权拒绝 | `../` 路径 → 拒绝/规范化（不逃出 root_dir） |
| 单例 | `get_backend() is get_backend()` |

测试隔离：tmp_path 构造 FilesystemBackend（不依赖真实 data/）；各路由断言
用独立 tmp 子目录。

---

## 3. 总：自检清单与后续

### 3.1 自检清单

- [ ] **需求覆盖**：B.0 前置约束落地（backend 文件系统就绪）✅；B.1 记忆路由 `/memories/` 就绪 ✅
- [ ] **依赖单向**：`core/backend.py` 归 core 层；`agent/main_agent.py` → core（合法单向）✅
- [ ] **API 一致性**：FilesystemBackend/CompositeBackend 签名与 deepagents 3.x 实测一致
  （root_dir/virtual_mode / default/routes）✅
- [ ] **可测性**：测试用 tmp_path 构造，无真实 data/ 依赖 ✅
- [ ] **不破坏现有**：Agent 文件操作从内存→磁盘是增强（数据不丢）；demo 兼容性标注验证项
- [ ] **Windows 兼容**：virtual_mode 虚拟根路径规范化（`../` 防逃逸），与平台无关
- [ ] **文档归位**：设计稿归 `docs/decisions/`（05-docs-placement 规则）✅

### 3.2 后续（不在本设计内）

1. **MemoryMiddleware 启用**（B.1）：`memory=[...]` + backend 已就绪——直接配置即可
2. 记忆文件管理 UI（设置页展示/删除）
3. workspace 清理策略（Agent 产生的临时文件生命周期）

> 📌 **评审结论预期**：设计为持久化计划 B.0 前置的落地——组合存储将 Agent 文件
> 操作与记忆文件路由到真实磁盘，零架构级风险（仅 backend 挂载 + 路径映射），
> 为 MemoryMiddleware 铺平道路。
