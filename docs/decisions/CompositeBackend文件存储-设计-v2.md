# CompositeBackend 文件存储 — 设计文档 v2（评审吸收版）

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-04
> 📝 **版本变更记录**（永久保存，只追加不删除）：

> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v2.0 | 2026-08-04 | 吸收评审 10 项：§2.1 废弃全局单例改**会话级 Backend + Agent 缓存**（硬缺陷 1）；§2.2 新增 **ReadOnlyBackend 只读强制**（硬缺陷 2）；§2.3 核心代码 v2（create_backend(thread_id) 工厂 + settings 开关 + 路径环境变量化 + 自动初始化）；§2.4 生命周期 + **临时文件清理**（隐患 1）+ **USE_MEMORY_WORKSPACE 双模式**（隐患 3）；§2.5 测试含**并发隔离**用例；§2.6 **子 Agent 隔离限制**标注与演进（隐患 2）；§2.7 细节优化 5 项（StoreBackend 对比/路径环境变量/日志埋点/并发/初始化） |
> | v1.2 | 2026-08-04 | §2.1 补「与现有目录映射核对表」（5 路由逐一核对无冲突）+「tools（代码）vs skills（文件）边界」澄清 +「skill_md 共写语义」标注（SkillMarket 写入 / Agent 只读约定） |
> | v1.1 | 2026-08-04 | §2.1 多路由组合（4 类：记忆/内置技能/市场技能/导出）+ 沙盒澄清表 + 参考配置对照表；§2.2 完整核心代码；§2.3 多路由测试 |
> | v1 | 2026-08-04 | 初版：CompositeBackend 组合存储设计（B.0 前置落地）——Agent 文件落盘 + 记忆文件路由 |

> **目录**：
> - §1 总：背景与目标
> - §2 分：设计（会话级 Backend / 只读强制 / 核心代码 / 生命周期与清理 / 测试 / 子 Agent / 细节优化）
> - §3 总：自检清单与后续
>
> **关联文档**：
> - 持久化计划：`docs/decisions/持久化能力开发计划-Checkpointer与Store-v1.md`（§B.0 / §B.1 / §B.2）
> - 架构：`docs/架构/多agent项目-架构目录-v1.md`（§2 目录树 / §2.1 能力落地位置对照）
> - 路径：`docs/方案/后端基础架构-v1.md`（路径自适应）

---

## 1. 总：背景与目标

### 1.1 背景

持久化计划 §B.0 前置约束：`MemoryMiddleware` 强依赖 backend；当前默认 StateBackend（内存）
导致记忆文件无法落盘、Agent 文件操作重启即失。

**v2.0 修订背景**：评审指出 v1 三处架构级问题——
① 全局 Backend 单例无会话隔离（多会话文件混存）；
② 只读路由仅文档约定无代码强制（安全漏洞）；
③ 磁盘持久化引入临时文件堆积、子 Agent 污染、demo 兼容问题。

### 1.2 目标

1. **会话级文件隔离**：每会话独立工作区（`data/workspace/{thread_id}/`）
2. **只读代码强制**：技能目录 Agent 不可写（ReadOnlyBackend 拦截）
3. **生命周期可控**：临时文件清理 + 内存模式开关（dev 兼容）
4. 为 MemoryMiddleware 启用铺路（B.1）

### 1.3 范围

| 在本设计内 | 不在本设计内 |
|-----------|-------------|
| 会话级 Backend 工厂 + Agent 缓存 | MemoryMiddleware 启用（B.1，后续） |
| ReadOnlyBackend 只读强制 | 沙箱后端（OpenSandbox 独立执行层） |
| 临时文件清理 + 内存模式开关 | 云上多机部署 |
| 子 Agent 隔离方案标注 | 子 Agent 真隔离（LangGraph 手写主图演进） |

---

## 2. 分：设计

### 2.1 会话级 Backend（v2.0，硬缺陷 1 修复）

**废弃全局 `get_backend()` 单例**——多会话文件全局混存是致命短板（会话 A 草稿污染会话 B）。
改为**工厂函数按会话构建**：

```
create_backend(thread_id)                  # 每次会话构建专属 backend
  └─ default: FilesystemBackend(data/workspace/{thread_id}/)   ← 会话文件隔离
  └─ routes:
       /memories/       → data/memory                  （全局共享记忆）
       /skills/static/  → ReadOnlyBackend(skill-resources/)   ← 只读强制
       /skills/market/  → ReadOnlyBackend(data/skills/skill_md)← 只读强制
       /exports/        → data/exports                 （全局导出）
```

**配套：会话级 Agent 缓存**（deepagents 无运行时 backend 覆盖机制——已探索确认，
务实等价方案）：

```python
# agent/main_agent.py
_agents: dict[str, CompiledStateGraph] = {}
_agents_lock = threading.Lock()

def get_agent(thread_id: str = "default"):
    """按会话懒构建 agent（backend 绑 thread_id 目录，会话文件隔离）。

    每会话一个编译图 + 独立文件根；compile 是内存操作，单机会话数少可接受。
    demo/无会话场景用默认 "default" thread_id。
    """
    if thread_id not in _agents:
        with _agents_lock:                      # 双重检查锁（会话维度）
            if thread_id not in _agents:
                _agents[thread_id] = create_deep_agent(
                    ..., backend=create_backend(thread_id),
                )
    return _agents[thread_id]
```

- `stream_agent_tokens`：`agent = get_agent(session_id)`（会话维度复用）
- `rebuild_agent()` → 清空 `_agents`（Skill 变更热刷新）
- 挂载耦合说明：`create_deep_agent(backend=...)` 是编译时绑定——会话级缓存是
  「每会话编译」的等价实现，比运行时覆盖更明确、无黑魔法

### 2.2 ReadOnlyBackend 只读强制（v2.0，硬缺陷 2 修复）

`FilesystemBackend` 无只读参数（已探索确认）——`virtual_mode` 仅防路径逃逸，
不区分读写权限。新增只读包装类：

```python
# core/backend.py
class ReadOnlyBackend(BackendProtocol):
    """只读包装：拦截技能目录的写操作（代码强制，非文档约定）。

    - /skills/static/、/skills/market/ 用此包装——Agent 无法篡改/删除技能文件
    - 拦截操作抛 PermissionError + 日志（越权写入可追踪，§2.7-3）
    - 读操作（read/ls/glob/grep）透传
    """

    def __init__(self, root_dir: Path) -> None:
        self._inner = FilesystemBackend(root_dir=root_dir, virtual_mode=True)

    def write(self, *args, **kwargs):   raise PermissionError("技能目录只读")
    def edit(self, *args, **kwargs):    raise PermissionError("技能目录只读")
    def delete(self, *args, **kwargs):  raise PermissionError("技能目录只读")
    def upload_files(self, *args, **kwargs): raise PermissionError("技能目录只读")
    # read / ls / glob / grep → 委托 self._inner
```

- 拦截时 `logging.warning("只读拦截：%s 尝试 %s（path=%s, thread=%s）")`
- SkillMarket 安装写技能走**后端代码**（installer.py），不经 backend——不受只读限制

### 2.3 核心代码（v2 完整版）

**`core/backend.py`**：

```python
"""Agent Backend 工厂：会话级组合存储（2026-08-04 设计 v2）。

- create_backend(thread_id)：按会话构建——default 绑 data/workspace/{thread_id}/
  （会话文件隔离，硬缺陷 1 修复）；技能路由 ReadOnlyBackend 只读强制（硬缺陷 2）
- USE_MEMORY_WORKSPACE 环境开关：default 切 StateBackend（dev 测试兼容，§2.4）
- FilesystemBackend 无连接 → 无 lifespan 需求（区别于 checkpointer/store）
"""

def create_backend(thread_id: str, *, memory_workspace: bool | None = None) -> CompositeBackend:
    memory_workspace = settings.memory_workspace if memory_workspace is None else memory_workspace
    default = (
        StateBackend()
        if memory_workspace
        else FilesystemBackend(root_dir=get_workspace_dir() / thread_id, virtual_mode=True)
    )
    return CompositeBackend(
        default=default,
        routes={
            "/memories/": FilesystemBackend(root_dir=get_memory_dir(), virtual_mode=True),
            "/skills/static/": ReadOnlyBackend(get_static_skills_dir()),
            "/skills/market/": ReadOnlyBackend(get_skill_md_dir()),
            "/exports/": FilesystemBackend(root_dir=get_exports_dir(), virtual_mode=True),
        },
    )
```

**`core/config.py`**（settings 补，隐患 3）：

```python
# 工作区模式：True = 内存临时（dev 测试兼容重启清空）；False = 磁盘持久（prod 默认）
memory_workspace: bool = False
```

**`core/paths.py`**（细节优化 2/5：不硬编码 parents[3] + 自动初始化）：

```python
def get_static_skills_dir() -> Path:
    """内置静态技能目录（/skills/static/ 路由）：SKILL_RESOURCES_DIR 优先，
    缺省项目根 skill-resources/（环境变量配置，不硬编码目录层级）。"""
    env = os.getenv("SKILL_RESOURCES_DIR")
    base = Path(env) if env else Path(__file__).resolve().parents[3] / "skill-resources"
    base.mkdir(parents=True, exist_ok=True)
    if not (base / "README.md").exists():      # 细节优化 5：自动初始化
        (base / "README.md").write_text("# skill-resources\n\n内置静态技能目录（Agent 只读）。", encoding="utf-8")
    return base
```

### 2.4 生命周期与清理（v2.0，隐患 1/3）

**临时文件清理**（隐患 1——磁盘持久化后草稿/临时代码无限堆积）：

```python
def cleanup_workspace(thread_id: str, older_than_days: int = 30) -> int:
    """清理会话工作区过期临时文件（mtime 超期删除，返回删除数）。

    调用时机：会话删除时（DELETE /v1/sessions）+ 定期巡检（可选 cron）。
    """
```

- 测试：会话销毁目录清理断言

**内存模式开关**（隐患 3——demo/测试依赖"重启清空"内存语义）：

| 模式 | USE_MEMORY_WORKSPACE | default backend | 适用 |
|------|---------------------|----------------|------|
| 持久（prod 默认） | False | FilesystemBackend(workspace/{thread_id}) | 生产/本地真实 |
| 内存（dev 测试） | True | StateBackend() | demo 脚本/单测（重启清空兼容） |

### 2.5 测试设计（v2.0 含并发隔离）

| 用例 | 断言 |
|------|------|
| 会话隔离 | thread A write → `workspace/A/`；thread B write → `workspace/B/`（互不污染） |
| **并发隔离** | 多协程同时写不同 thread_id → 各落各自目录（无交叉/无锁冲突） |
| 只读强制 | `/skills/market/xxx` write/edit/delete → PermissionError |
| 默认路由 | write("/note.txt") → `workspace/{thread_id}/note.txt` |
| 记忆/导出路由 | `/memories/`、`/exports/` 各落对应目录 |
| virtual_mode 越权 | `../` → 拒绝/规范化 |
| 内存模式 | memory_workspace=True → default 为 StateBackend（写后读回，无磁盘文件） |
| 清理 | cleanup_workspace 删除过期文件、保留新鲜文件 |

测试隔离：tmp_path 构造各 backend；并发用 asyncio.gather。

### 2.6 子 Agent 文件隔离（v2.0，隐患 2——限制标注 + 演进）

**已确认（探索）**：`SubAgentMiddleware(backend=backend)` 继承主 Agent backend
（graph.py:830 传同一实例）——子 Agent 与主 Agent 共用文件目录，deepagents 内部
**不支持 per-subagent backend**。

- **务实结论**：单机场景可接受（子 Agent 文件与主会话同目录，靠文件名空间分离）；
  不为此改造 deepagents 内部
- **演进路径**：LangGraph 手写主图时，子 Agent 节点显式绑定独立 StateBackend
  （内存临时）实现真隔离——标注为学习点（`02-hands-on-training.md` 演进路线）

### 2.7 细节优化（v2.0 新增）

| # | 项 | 方案 |
|---|----|------|
| 1 | **StoreBackend 备选对比** | `/memories/` 现用 FilesystemBackend（MD 文本）；备选 StoreBackend（SqliteStore 结构化，见持久化计划 B.2）——对比：文件记忆（人类可读/简单）vs 结构化（可检索/查表） |
| 2 | **路径函数环境变量化** | `get_static_skills_dir`：SKILL_RESOURCES_DIR 优先，缺省项目根探测（不硬编码 parents[3]） |
| 3 | **日志埋点** | ReadOnlyBackend 拦截日志（path/op/thread_id）+ FilesystemBackend 读写路径日志 |
| 4 | **并发测试** | 见 §2.5（多协程多 thread_id 隔离断言） |
| 5 | **skill-resources 自动初始化** | 不存在时生成 README 模板（启动自检） |

---

## 3. 总：自检清单与后续

### 3.1 自检清单（评审 10 项逐条）

- [ ] **硬缺陷 1**：全局单例 → 会话级 create_backend(thread_id) + _agents 缓存 ✅（§2.1）
- [ ] **硬缺陷 2**：只读路由 ReadOnlyBackend 代码强制（非文档约定）✅（§2.2）
- [ ] **隐患 1**：cleanup_workspace 清理接口 + 过期策略 + 测试 ✅（§2.4）
- [ ] **隐患 2**：子 Agent 隔离——deepagents 限制标注 + LangGraph 演进 ✅（§2.6）
- [ ] **隐患 3**：USE_MEMORY_WORKSPACE 双模式 + 双场景测试 ✅（§2.4）
- [ ] 细节 1-5：StoreBackend 对比 / 路径环境变量 / 日志埋点 / 并发测试 / 初始化 ✅（§2.7）
- [ ] 文档规范：大改升级文件名 -v2 + 版本记录逐条 ✅
- [ ] API 一致性：SubAgentMiddleware backend 继承已探索确认 ✅

### 3.2 后续

1. **MemoryMiddleware 启用**（B.1）——backend 会话级就绪后直接配置
2. 会话删除联动 `cleanup_workspace(thread_id)`
3. 定期巡检清理任务（可选 cron）
4. LangGraph 手写主图：子 Agent 真隔离 + 运行时 backend 覆盖

> 📌 **评审结论预期**：v2.0 修复会话隔离与只读安全两个硬缺陷，补齐临时文件清理、
> 内存模式兼容、子 Agent 隔离标注；细节优化 5 项全部落点——可进入实施。
