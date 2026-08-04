# CompositeBackend 文件存储 — 设计文档（评审稿）

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-04
> 📝 **版本变更记录**（永久保存，只追加不删除）：

> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
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

### 2.1 架构：CompositeBackend 路径路由

```
Agent（FilesystemMiddleware / 未来 MemoryMiddleware）
        │ backend=CompositeBackend
        ▼
┌────────────────────────────────────────────┐
│ CompositeBackend                           │
│  default : FilesystemBackend(data/workspace)│  ← 未匹配前缀的路径（Agent 常规文件）
│  routes  : {                               │
│    "/memories/": FilesystemBackend(data/memory)│  ← 记忆文件（前缀路由）
│  }                                          │
└────────────────────────────────────────────┘
```

**路径映射表**：

| 路径前缀 | 落盘位置 | 用途 |
|---------|---------|------|
| `/`（默认） | `data/workspace/` | Agent 常规文件操作（ls/read/write/edit） |
| `/memories/` | `data/memory/` | 记忆文件（MemoryMiddleware 启用后读写 AGENTS.md 类记忆） |

**双 FilesystemBackend 隔离的理由**：root_dir 物理分离——Agent 的 workspace 操作
永远碰不到记忆目录（虚拟根各自独立），记忆文件不被 Agent 误改/误删。
若用单一 backend + 路由无隔离，Agent 写 `/memories/` 会绕过隔离意图。

### 2.2 核心代码

**`core/paths.py`**（补路径）：

```python
def get_memory_dir() -> Path:
    """记忆文件目录（MemoryMiddleware 用）：data/memory/，父目录自动创建。"""
    base = get_app_dir() / "memory"
    base.mkdir(parents=True, exist_ok=True)
    return base
```

**`core/backend.py`**（新建，模块级惰性单例）：

```python
"""Agent Backend 工厂：CompositeBackend 组合存储（2026-08-04 设计）。

- Agent 常规文件操作 → data/workspace（真实磁盘，非 StateBackend 内存）
- /memories/ 前缀 → data/memory（记忆文件独立目录，物理隔离）
- FilesystemBackend 无连接资源 → 模块级惰性单例即可（无需 lifespan，
  区别于 checkpointer/store 的 async 连接）
"""

from __future__ import annotations

from deepagents.backends import CompositeBackend, FilesystemBackend

from src.core.paths import get_memory_dir, get_workspace_dir

_backend: CompositeBackend | None = None


def get_backend() -> CompositeBackend:
    """组合 backend 单例（惰性创建，路径自适应）。"""
    global _backend
    if _backend is None:
        _backend = CompositeBackend(
            default=FilesystemBackend(root_dir=get_workspace_dir(), virtual_mode=True),
            routes={
                "/memories/": FilesystemBackend(root_dir=get_memory_dir(), virtual_mode=True),
            },
        )
    return _backend
```

**挂载**（`agent/main_agent.py`）：

```python
from src.core.backend import get_backend

_agent = create_deep_agent(
    ...,
    backend=get_backend(),   # ← Agent 文件操作落盘 + 记忆路由
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

### 2.5 测试设计

| 用例 | 断言 |
|------|------|
| 落盘持久化 | `backend.write("/note.txt")` → `data/workspace/note.txt` 存在 → read 返回内容 |
| 前缀路由 | `backend.write("/memories/facts.md")` → 落 `data/memory/facts.md`（非 workspace） |
| virtual_mode 越权拒绝 | `../` 路径 → 拒绝/规范化（不逃出 root_dir） |
| 单例 | `get_backend() is get_backend()` |

测试隔离：tmp_path 构造 FilesystemBackend（不依赖真实 data/）。

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
