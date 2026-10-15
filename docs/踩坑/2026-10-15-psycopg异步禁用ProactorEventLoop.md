# 教训：psycopg 3 async 在 Windows 禁用 ProactorEventLoop

> 📋 **规范**：遵循 `docs/规则/文档规范.md`
> 📌 **更新时间**：2026-10-15
> 📝 **版本变更记录**（永久保存，只追加不删除）：

> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1 | 2026-10-15 | 初版：PG 迁移中实测发现——psycopg 3 async 硬禁 ProactorEventLoop，记录现象 / 根因 / 三处入口影响面 / 修复与沉淀 |

> **目录**：
> - § 现象
> - § 根因
> - § 影响面（dev / pytest / prod 三态）
> - § 修复与沉淀
> - § 副作用与边界
> - § 关联

---

## 现象

PG 迁移后，容器健康、端口通、`psql` 能连，但任何走 psycopg 异步的连接**直接抛错**：

```
psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async
mode. Please use a compatible event loop, for instance by running
'asyncio.run(..., loop_factory=asyncio.SelectorEventLoop(selectors.SelectSelector()))'
```

触发点极早——`AsyncConnection.connect()` 第一步就检查并拒。

## 根因

**psycopg 3 在 win32 上硬性拒绝 `ProactorEventLoop`**，无开关、无降级、无环境变量可绕。
源码位置（`psycopg/connection_async.py::AsyncConnection.connect`）：

```python
if sys.platform == "win32":
    loop = asyncio.get_running_loop()
    if isinstance(loop, asyncio.ProactorEventLoop):
        raise e.InterfaceError("Psycopg cannot use the 'ProactorEventLoop' ...")
```

而 **Python 3.8+ 在 Windows 的默认事件循环策略就是 Proactor**
（`_WindowsProactorEventLoopPolicy` → `ProactorEventLoop`），本机实测确认：

```
默认事件循环策略: _WindowsProactorEventLoopPolicy
默认策略新建的 loop 类型: ProactorEventLoop
```

即：**「Windows 本机 + psycopg 异步」这个组合在默认配置下必然崩**。
迁移前的 SQLite 栈（aiosqlite 走线程）不受此约束，所以这是个**迁移才暴露**的坑。

## 影响面（dev / pytest / prod 三态）

| 入口 | 默认拿到的 loop | 结果 |
|---|---|---|
| `uvicorn ...`（无 `--reload`） | `ProactorEventLoop` | 🔴 崩 |
| `uvicorn ... --reload` | **`SelectorEventLoop`** | ✅ 正常（见下） |
| `pytest`（pytest-asyncio） | `ProactorEventLoop` | 🔴 崩（每个用例建连接即死） |
| 云端 Linux（prod） | Selector / Epoll | ✅ 正常 |

**为什么 `--reload` 反而是对的**——这是本次最反直觉的一点。
uvicorn 的 loop 工厂：

```python
def asyncio_loop_factory(use_subprocess: bool = False):
    if sys.platform == "win32" and not use_subprocess:
        return asyncio.ProactorEventLoop
    return asyncio.SelectorEventLoop
```

`use_subprocess = reload or workers > 1`。所以：
- **不带 `--reload`** → Proactor → 撞 psycopg 限制；
- **带 `--reload`** → 走子进程 → Selector → 恰好可用。

项目 dev 命令（`scripts/dev.sh` / `dev-restart.sh`）一直是 `uvicorn ... --reload`，
**属侥幸命中**，不是设计使然——故必须把结论固定下来（见下）。

## 修复与沉淀

### 1. 测试入口（已落地）

`backend/tests/conftest.py` 覆盖 pytest-asyncio 的 session 级 loop 工厂 fixture：

```python
@pytest.fixture(scope="session")
def _asyncio_loop_factory():
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop
    return None          # Linux 用平台默认（即 Selector/Epoll）
```

选 `_asyncio_loop_factory`（而非 `event_loop_policy`）的理由：Python 3.14 起
`asyncio.set_event_loop_policy` / `get_event_loop_policy` 已 **DeprecationWarning**
（3.16 移除），而 `loop_factory` 是 pytest-asyncio ≥1.0 的新钩子、走 `Runner(loop_factory=...)`，
不踩弃用。

### 2. 顺手把「唯一可用的那种启动方式」写进结论

- 本项目 **Windows 本地跑后端必须带 `--reload`**（现有脚本已满足）；
- 若将来要加不带 `--reload` 的本地启动方式（如打包/常驻），**必须显式设
  `WindowsSelectorEventLoopPolicy`**，否则首请求即崩。

### 3. 反面记录：为什么没改 `src/api/main.py`

在 application 模块里设策略**来不及**——uvicorn 的执行顺序是
`Server.run()` → `asyncio.run(...)` **先建 loop** → `serve()` 内 `Config.load()` 才 import app。
应用模块被导入时 loop 早已创建，改策略无效。故修复只能落在**测试入口**与**启动器**，
不能落在 app 模块。

## 副作用与边界

切到 `SelectorEventLoop` 的代价：**Windows 本机 `asyncio` 子进程不可用**
（Selector 不支持 `create_subprocess_exec`）。影响面收敛如下：

| 能力 | 是否走 asyncio 子进程 | 影响 |
|---|---|---|
| MCP **stdio** transport | ✅ 是 | 🔴 Windows 本地不可用（项目当前**未配置任何 stdio server**；标准 MCP 走 sse / streamable_http） |
| OpenSandbox 沙箱 | ❌ 否（HTTP 连 server） | 无影响 |
| QuickJS 解释器 | ❌ 否（进程内） | 无影响 |
| Redis / PG / 网络工具 | ❌ 否 | 无影响 |

**生产为 Linux，不受任何影响。** 若将来确需在 Windows 本地跑 stdio MCP，
可行路径：改用 HTTP transport，或把后端放进 Docker/WSL 跑。

## 关联

- `docs/索引.md`（唯一入口）
- `docs/决策/2026-10-15-计划-PG迁移-v1.md`（本坑所属工作单，§7 测试策略）
- `backend/tests/conftest.py`（修复落点 + 同款说明注释）
- `.claude/rules/20-testing.md`（数据库条目同步修订）
