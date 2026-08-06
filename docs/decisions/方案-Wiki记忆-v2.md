# 方案-Wiki 记忆 v2（基础设计：收藏流程 + 对接接口 + 降级方案）

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-06
> 📝 **版本变更记录**（永久保存，只追加不删除）：
> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v2 | 2026-08-06 | **基础设计深化**（本地先行，接口供对面项目讨论）：§5 新增「对接接口设计」（REST 契约 5 端点 + 鉴权 + 错误码 + 待确认问题）；§6 新增「前端收藏流程设计」（收藏入口/类型归类/状态机 + 本端收藏 API）；§7 新增「降级方案设计」（统一记忆后端抽象 Wiki/Local 双实现 + 熔断触发与恢复 + 前端降级表现）；§8 新增「配置化设计」（wiki_* 配置项清单 + .env 示例）；§9 实施路径重排（P0 纳入收藏 MVP + 降级 + 接口联调）；§10 新增「核心代码形态」（config 增量 / wiki_client / 记忆后端抽象 / 收藏 API / 前端组件要点 / 测试设计） |
> | v1 | 2026-08-06 | 初版：全文录入 Wiki 记忆方向分析（2026-08-06 讨论产出）——§2 差异化对比 / §3 可行性分析 / §4 技术方案（映射与检索）/ §5 风险与挑战 / §6 实施路径 |

> **目录**：
> - §1 总：定位与 v2 深化目标
> - §2 分·差异化对比（官方 RAG vs Wiki 记忆）
> - §3 分·可行性分析
> - §4 分·技术方案：记忆→Wiki 映射与检索
> - §5 分·对接接口设计（对 Wiki 项目，供讨论）
> - §6 分·前端收藏流程设计
> - §7 分·降级方案设计
> - §8 分·配置化设计
> - §9 分·实施路径（P0/P1/P2）
> - §10 附·核心代码形态（规范 v4）
> - 附录：待确认问题清单

> **关联文档**：
> - 本地方案家族：`docs/decisions/方案-记忆能力开发-v3.md`（本地文件 + Store 记忆——降级方案的兜底实现）
> - 架构真相源：`docs/架构/多agent项目-架构目录-v1.md`（依赖单向：api → agent → memory）
> - 配置中心：`backend/src/core/config.py`（BaseSettings + .env 切换）
> - 文档规范：`docs/文档规范.md`

---

## 1. 总：定位与 v2 深化目标 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v2</span>

> **官方 RAG = 向量数据库里找相似片段（技术驱动）；本方案 = Wiki 文档里找结构化知识（文档驱动）**

v2 深化四大块（本地先行设计，接口留待与对面 Wiki 项目讨论确认）：

| # | 块 | 现状 | v2 设计 |
|---|----|------|---------|
| 1 | **前端收藏流程** | 前端无"收藏 → 加入 Wiki 文档"整套流程 | §6：收藏入口 → 类型归类 → 写入 → 状态反馈 + 本端收藏 API |
| 2 | **降级方案** | 本地无兜底（Wiki 挂了记忆就挂） | §7：统一记忆后端抽象，Wiki 失败熔断 → 本地文件记忆兜底 |
| 3 | **对接接口** | 对面 Wiki 项目暂无对外接口 | §5：简单 REST 契约（5 端点），供双方讨论 |
| 4 | **配置化** | 地址/URL 写死风险 | §8：全部走 `.env.dev/.env.prod`（settings 配置项） |

**原则**：保持简单（对面项目接口尽量少、尽量直白）；一切外部地址/密钥配置化（遵守"密钥只进 .env"硬约束）。

---

## 2. 分·差异化对比（官方 RAG vs Wiki 记忆）

| 维度 | 官方 RAG | Wiki 记忆方案 |
|---|---|---|
| **本质** | 向量相似度匹配（黑盒） | 结构化文档组织（白盒） |
| **人类可读性** | ❌ 向量不可读 | ✅ Wiki 天然可读可编辑 |
| **知识组织** | 扁平的片段集合 | 分层、分类、标签、目录 |
| **编辑能力** | ❌ 只能重新嵌入 | ✅ 直接在 Wiki 里改 |
| **可解释性** | ❌ 为什么搜到这条？说不清 | ✅ 因为在 XX 分类/标签下 |
| **复用性** | ❌ 只能给 AI 用 | ✅ 人和 AI 共用一套知识库 |
| **技术栈** | 向量数据库 + 嵌入模型 | Wiki API + 文档结构 |
| **亮点** | 技术先进 | 产品创新 + 人机协同 |

---

## 3. 分·可行性分析

**核心链路**：

```
前端收藏 → 后端收藏 API → 记忆后端（Wiki 优先）→ 调用 Wiki API → 写入指定文档
                                    └─ 失败 → 本地文件记忆（降级）
```

**能力依赖**（三项）：
1. **Wiki 项目提供 API**：创建/更新文档、搜索文档（v2 §5 给出建议契约，待对方确认）
2. **Agent/后端封装 `wiki_memory_tool`**：写入、检索、更新（v2 §7 统一后端抽象）
3. **记忆分类映射**：映射到 Wiki 的命名空间/目录结构（v2 §4.1）

---

## 4. 分·技术方案：记忆→Wiki 映射与检索

### 4.1 记忆 → Wiki 映射关系

| 记忆类型 | Wiki 位置 | 写入方式 |
|---|---|---|
| 用户画像 | `User:用户名/Profile` | 结构化 infobox |
| 决策记录 | `Decisions/YYYY-MM-DD-主题` | 独立页面 |
| 任务记忆 | `Tasks/当前任务` | 列表更新 |
| 事实/常识 | `Knowledge/分类/主题` | 分类页面 |
| 对话摘要 | `Logs/YYYY-MM-DD` | 日志页面 |

> 映射表 v2 定位为**代码常量**（`MEMORY_TYPE_MAP`），后续可配置化（P2）。

### 4.2 检索方式（不用向量，用 Wiki 自带能力）

| 方式 | 特点 |
|------|------|
| 1. 标题搜索 | Wiki 自带标题匹配（快、准） |
| 2. 全文搜索 | Wiki 自带关键词搜索（够用） |
| 3. 标签检索 | 按标签过滤（结构化） |
| 4. 分类树遍历 | 按目录层级找（人类思维方式） |

**为什么不用向量也够**：记忆是**结构化写入**的，不是随机片段；有分类、有标签、有标题，检索精度比向量高；量小时关键词搜索比向量还准。

---

## 5. 分·对接接口设计（对 Wiki 项目，供讨论） <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v2</span>

> 目的：对方项目暂无对外接口——本端先给一版**简单 REST 契约**（5 端点），拿到对面讨论。**一切地址/密钥配置化**（§8），不写死。

### 5.1 接口清单

| # | 方法 | 路径 | 用途 | 备注 |
|---|------|------|------|------|
| 1 | `GET` | `/api/v1/health` | 健康检查 | 降级探测 + 前端状态展示 |
| 2 | `POST` | `/api/v1/pages` | 创建页面 | 核心写入 |
| 3 | `PUT` | `/api/v1/pages/{page_id}` | 更新页面 | 追加/编辑 |
| 4 | `GET` | `/api/v1/pages/{page_id}` | 获取页面 | 详情读取 |
| 5 | `GET` | `/api/v1/search` | 搜索页面 | 标题/全文/标签 |

### 5.2 契约细节

**鉴权**：`Authorization: Bearer <token>`（token 配置化，§8 `WIKI_API_KEY`）；401 未授权 / 403 无权限。

**请求/响应示例**：

```http
# 创建页面
POST /api/v1/pages
Authorization: Bearer <token>
Content-Type: application/json

{
  "namespace": "Decisions",          // 命名空间（映射到目录/分类）
  "title": "2026-08-06 沙箱选型",
  "content": "# 2026-08-06 沙箱选型\n- 决策：选 OpenSandbox 自建\n- 原因：可控性强、成本低",
  "tags": ["决策", "沙箱"]
}
→ 201
{
  "page_id": "12345",
  "url": "https://wiki.example.com/wiki/Decisions/2026-08-06-沙箱选型"
}

# 更新页面（追加/编辑）
PUT /api/v1/pages/12345
{ "content": "<全文或增量>", "tags": ["决策", "沙箱"] }
→ 200 { "page_id": "12345" }

# 获取页面
GET /api/v1/pages/12345
→ 200 { "page_id": "12345", "namespace": "Decisions", "title": "...", "content": "...", "tags": [...] }

# 搜索页面
GET /api/v1/search?q=沙箱&by=fulltext&namespace=Decisions&limit=10
→ 200 { "results": [ { "page_id": "...", "title": "...", "snippet": "..." } ] }

# 健康检查
GET /api/v1/health
→ 200 { "status": "ok" }
```

**错误码统一**：

| 状态码 | 含义 | 本端处理 |
|--------|------|---------|
| 200/201 | 成功 | 正常流程 |
| 400 | 参数错误 | 返回错误给前端 |
| 401/403 | 鉴权失败 | 记审计日志 + 前端提示配置问题 |
| 404 | 页面不存在 | 按"未找到"处理 |
| 429 | 频率限制 | 退避重试（≤1 次） |
| 5xx | 服务端错误 | 计入失败 → 触发降级熔断（§7） |

### 5.3 待与对方确认问题（见附录 A-1）

1. namespace 语义：对方是否已有目录/命名空间概念？还是用"标签"平铺？
2. 更新语义：`PUT` 传全文替换 vs 传增量追加？——本端倾向**全文替换**（幂等、实现简单）
3. 搜索能力：对方能否支持 `by=tag` / `namespace` 过滤？不能则退化为 `q` 全文搜索
4. 鉴权方案：Bearer token 是否可接受？对方是否有更合适的方案
5. 频率限制：写入口径（本端会做写入审核 §5 v1 风险 1，频率不高，但确认对方限流值）

---

## 6. 分·前端收藏流程设计 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v2</span>

### 6.1 交互流程（收藏一条内容 → 写入 Wiki）

```
用户在聊天消息卡片点「收藏」
  → 弹收藏确认框（预填内容 + 选择记忆类型 + 可编辑标题）
  → 提交 POST /v1/favorites
  → 后端：写记忆后端（Wiki 优先，失败降级本地）
  → 返回 { status, storage: "wiki"|"local", page_id? }
  → 前端 toast 反馈：✅ 已收藏到 Wiki / ⚠️ 已本地暂存（Wiki 不可用）/ ❌ 失败
```

### 6.2 页面与组件

| 组件/页面 | 说明 |
|-----------|------|
| 消息卡片「收藏」按钮 | ChatPage 消息尾部操作（星标图标 + tooltip） |
| `FavoriteDialog` | 收藏确认框：内容预览（可编辑）+ 类型选择（决策/任务/事实/用户画像/对话摘要）+ 标题 |
| `FavoritesPage` | 收藏列表页：展示 storage 徽章（wiki/本地暂存）、筛选、删除、跳转 Wiki 页面链接（url 可配置） |
| 收藏状态徽章 | `wiki`（绿）/ `local`（橙）/ `failed`（红） |

### 6.3 本端收藏 API（`/v1/` 前缀，Pydantic schema）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| `POST` | `/v1/favorites` | `{content, memory_type, title?}` | `{id, storage, wiki_page_id?, wiki_url?}` |
| `GET` | `/v1/favorites` | query: `memory_type?`、`storage?`、`page/limit` | 分页列表 |
| `GET` | `/v1/favorites/{id}` | — | 单条详情 |
| `DELETE` | `/v1/favorites/{id}` | — | `{status: "ok"}` |
| `GET` | `/v1/favorites/health` | — | `{wiki_ok, storage: "wiki"\|"local"}`（前端顶部状态条） |

**字段**（schema 草案）：`id` / `content` / `memory_type`（五类枚举）/ `title` / `storage`（wiki|local）/ `wiki_page_id` / `wiki_url` / `created_at`。

### 6.4 写入状态机

```
提交收藏
  ├─ Wiki 正常 → 写 Wiki → storage=wiki（记 page_id/url）
  ├─ Wiki 熔断/失败 → 写本地文件（复用 v3 decisions/tasks 格式）→ storage=local（标注"待同步"）
  └─ 双重失败 → failed（返回错误，前端提示重试）
```

---

## 7. 分·降级方案设计 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v2</span>

> 风险 4（Wiki 项目依赖）的对策落地：**统一记忆后端抽象 + 熔断降级**。

### 7.1 统一记忆后端抽象

```
MemoryBackend（协议：create/update/get/search/health）
├── WikiBackend    # 调对面 Wiki API（§5），配置化 base_url/token
└── LocalBackend   # 复用 v3 本地记忆（decisions.md/tasks.md + Store），零外部依赖
```

**路由逻辑**（`MemoryRouter`，无第三方依赖、可单测）：

```
写入：Wiki 健康（未熔断）→ WikiBackend.create；异常 → 失败计数+1 → LocalBackend 兜底
读取：Agent/前端读收藏 → 双源合并（Wiki 为主，local 标注"待同步"）
```

### 7.2 触发与恢复（熔断器，简单计数版）

| 状态 | 触发条件 | 行为 |
|------|---------|------|
| 正常 | `wiki_fail_threshold`（默认 3）内未连续失败 | Wiki 优先 |
| **熔断** | 连续失败 ≥ 阈值（5xx/超时/连接失败） | 全部写本地，`/v1/favorites/health` 返回 `wiki_ok=false` |
| 恢复探测 | 熔断后每 `wiki_recovery_interval`（默认 5min）后台探活一次 | 恢复 → 回切 Wiki；未恢复 → 维持本地 |
| 手动恢复 | 配置/接口触发重置 | 排障后即时回切 |

**降级时本地落盘格式**：沿用 v3 方案格式（`decisions.md` 决策模板 / `tasks.md` 任务列表），保证本地人工可读。

### 7.3 降级时的前端表现

- 顶部状态条（Wiki 离线黄条）：`⚠️ Wiki 暂不可用，收藏将本地暂存`——数据源 `GET /v1/favorites/health`
- 收藏列表 `local` 徽章橙色，显示"待同步"；Wiki 恢复后标记可手动重试同步（P1）

---

## 8. 分·配置化设计 <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v2</span>

> 全部地址/密钥/阈值进 `.env.dev` / `.env.prod`（`core/config.py` 增量，绝不硬编码）。

### 8.1 配置项清单

| 配置键 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `WIKI_ENABLED` | bool | `false` | 总开关（未对接前默认关，不影响存量功能） |
| `WIKI_BASE_URL` | str | `""` | 对面 Wiki 项目地址（dev 本地 / prod 云端分别配） |
| `WIKI_API_KEY` | str | `""` | 鉴权 token（🔴 密钥只进 .env，不入库） |
| `WIKI_TIMEOUT` | float | `10.0` | 单请求超时秒（LLM 调用同样式：timeout + retry） |
| `WIKI_RETRIES` | int | `2` | 失败重试次数 |
| `WIKI_FAIL_THRESHOLD` | int | `3` | 连续失败熔断阈值 |
| `WIKI_RECOVERY_INTERVAL` | int | `300` | 熔断后探活间隔秒 |
| `WIKI_FALLBACK_LOCAL` | bool | `true` | 熔断时是否降级本地（false = 直接失败） |
| `WIKI_NAMESPACE_MAP` | str | 空（用代码常量） | 五类记忆 → namespace 映射覆写（逗号分隔，P2） |

### 8.2 `.env.dev` / `.env.prod` 示例

```bash
# 记忆 Wiki（v2 新增；dev 先关，对接后开）
WIKI_ENABLED=false
WIKI_BASE_URL=http://localhost:8080        # prod: https://wiki.example.com
WIKI_API_KEY=
WIKI_TIMEOUT=10
WIKI_RETRIES=2
WIKI_FAIL_THRESHOLD=3
WIKI_RECOVERY_INTERVAL=300
WIKI_FALLBACK_LOCAL=true
```

---

## 9. 分·实施路径（P0/P1/P2） <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v2</span>

| 阶段 | 内容 | 依赖 |
|------|------|------|
| **P0 收藏 MVP** | 后端：config 增量 + `MemoryBackend` 抽象 + `LocalBackend`（降级天然就绪）+ 收藏 API（CRUD + health）+ 测试；前端：消息卡片收藏按钮 + FavoriteDialog + FavoritesPage + 状态徽章 | 无对面接口——**先用 LocalBackend 跑通全流程**（Wiki 未对接也能开发/验收） |
| **P1 Wiki 对接** | `WikiBackend` 实现 + 与对面确认 §5 契约 + 联调；熔断器 + 恢复探测 + `wiki_ok` 前端状态条；收藏列表"待同步重试" | 对方接口就绪（§5.3 确认项） |
| **P2 产品化** | 双向同步（人改 Wiki → Agent 感知）+ 版本历史（Wiki 自带）+ 记忆图谱（链接关系）+ 人机协同编辑界面 + 映射表配置化 | P1 |

> **P0 不依赖对面项目**是本次深化最关键的落地决策：本地兜底先行，收藏全链路（前端 → 后端 → 本地记忆）可先验收，Wiki 接口到位后只换后端实现。

---

## 10. 附·核心代码形态（规范 v4 强制） <span style="color:#fff;background-color:#e11d48;border-radius:4px;padding:1px 6px;font-size:0.8em">v2</span>

> 可运行形态（增量代码，落地时按实施计划调整）。依赖单向：`api → agent → memory`，新模块放 `src/agent/`（与 `memory_store.py` 平级）。

### 10.1 config.py 增量（§8 配置项）

```python
# ── 记忆 Wiki（v2：Wiki 记忆方案基础设计 §8）──
wiki_enabled: bool = False                       # 总开关（未对接前默认关）
wiki_base_url: str = ""                          # 对面 Wiki 项目地址（双环境分别配）
wiki_api_key: str = ""                           # 鉴权 token（🔴 只进 .env）
wiki_timeout: float = 10.0                       # 单请求超时秒
wiki_retries: int = 2                            # 失败重试次数
wiki_fail_threshold: int = 3                     # 连续失败熔断阈值
wiki_recovery_interval: int = 300                # 熔断后探活间隔秒
wiki_fallback_local: bool = True                 # 熔断时降级本地
```

### 10.2 Wiki 客户端适配层（`src/agent/wiki_client.py`）

```python
"""对面 Wiki 项目 API 客户端（§5 契约，httpx 异步）。"""

import httpx

from src.core.config import settings


class WikiClient:
    """REST 客户端。全部地址/密钥来自 settings（配置化，§8）。"""

    def __init__(self) -> None:
        self._base_url = settings.wiki_base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {settings.wiki_api_key}"}
        self._timeout = httpx.Timeout(settings.wiki_timeout)

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def create_page(self, namespace: str, title: str,
                          content: str, tags: list[str] | None = None) -> dict:
        """POST /api/v1/pages → {"page_id", "url"}。失败抛 WikiError（可重试）。"""
        ...

    async def update_page(self, page_id: str, content: str,
                          tags: list[str] | None = None) -> None:
        """PUT /api/v1/pages/{page_id}（全文替换，幂等）。"""
        ...

    async def search(self, q: str, *, by: str = "fulltext",
                     namespace: str | None = None, limit: int = 10) -> list[dict]:
        """GET /api/v1/search → [{"page_id","title","snippet"}]。"""
        ...

    async def health(self) -> bool:
        """GET /api/v1/health；异常一律 False（熔断探测用）。"""
        ...
```

> 错误处理：统一 `WikiError`（可重试=超时/5xx/429；不可重试=401/403/400），重试次数 `settings.wiki_retries`——与 `llm/adapter.py` 同款纪律。

### 10.3 统一记忆后端 + 熔断路由（`src/agent/memory_backends.py`）

```python
"""统一记忆后端：Wiki 优先 + 本地兜底（§7 降级方案）。"""

from dataclasses import dataclass
import time

from src.agent.wiki_client import WikiClient

# 五类记忆 → Wiki namespace（v2 §4.1 映射表，代码常量；P2 可配置化）
MEMORY_TYPE_MAP = {
    "user_profile": "User",
    "decision": "Decisions",
    "task": "Tasks",
    "fact": "Knowledge",
    "log": "Logs",
}


class MemoryBackend(Protocol):
    """统一记忆后端协议（Wiki / Local 双实现）。"""
    async def create(self, memory_type: str, title: str, content: str) -> dict: ...
    async def health(self) -> bool: ...


class WikiBackend:
    """Wiki 实现：走 §5 契约。"""
    def __init__(self) -> None:
        self._client = WikiClient()

    async def create(self, memory_type: str, title: str, content: str) -> dict:
        namespace = MEMORY_TYPE_MAP[memory_type]
        return await self._client.create_page(namespace, title, content, tags=[memory_type])


class LocalBackend:
    """本地兜底：复用 v3 方案本地记忆格式（decisions.md / tasks.md）。"""
    async def create(self, memory_type: str, title: str, content: str) -> dict:
        ...  # 追加写入 data/memory/decisions.md（决策）或 tasks.md（任务），零外部依赖
        return {"storage": "local"}

    async def health(self) -> bool:
        return True


@dataclass
class MemoryRouter:
    """熔断路由：连续失败 ≥ 阈值 → 全走本地；后台定期探活恢复（§7.2）。"""
    wiki: WikiBackend
    local: LocalBackend
    fail_threshold: int = settings.wiki_fail_threshold
    recovery_interval: int = settings.wiki_recovery_interval

    def __post_init__(self) -> None:
        self._fail_count = 0
        self._open = False
        self._last_probe = 0.0

    async def create(self, memory_type: str, title: str, content: str) -> dict:
        """Wiki 优先；熔断或失败 → 本地兜底。返回 {"storage": "wiki"|"local", ...}。"""
        if not settings.wiki_enabled or self._open:
            return await self.local.create(memory_type, title, content)
        try:
            result = await self.wiki.create(memory_type, title, content)
            self._fail_count = 0
            return {"storage": "wiki", **result}
        except Exception:
            self._fail_count += 1
            if self._fail_count >= self.fail_threshold:
                self._open = True   # 熔断：后续写入直通本地
            if settings.wiki_fallback_local:
                return await self.local.create(memory_type, title, content)
            raise

    async def health(self) -> dict:
        """降级状态（前端 /v1/favorites/health 数据源）。"""
        if self._open and time.time() - self._last_probe > self.recovery_interval:
            self._last_probe = time.time()   # 后台探活：恢复则回切
            if await self.wiki.health():
                self._open, self._fail_count = False, 0
        return {"wiki_ok": settings.wiki_enabled and not self._open,
                "storage": "wiki" if not self._open else "local"}
```

### 10.4 收藏 API（`src/schemas/favorite.py` + `src/api/favorites.py`）

```python
# schemas/favorite.py
from pydantic import BaseModel, Field

MEMORY_TYPES = ("user_profile", "decision", "task", "fact", "log")

class FavoriteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    memory_type: str = Field(pattern="|".join(MEMORY_TYPES))
    title: str | None = None

class FavoriteOut(BaseModel):
    id: str
    content: str
    memory_type: str
    storage: str                 # wiki | local
    wiki_page_id: str | None = None
    wiki_url: str | None = None
    created_at: float
```

```python
# api/favorites.py（路由 v1 前缀，只做编排——函数长度铁律 ≤80 行）
@router.post("/favorites")
async def create_favorite(req: FavoriteCreate) -> FavoriteOut:
    """收藏 → 记忆后端（Wiki 优先，失败降级本地）。"""
    result = await router_backend.create(req.memory_type, req.title or req.content[:30], req.content)
    return await _save_favorite(req, result)   # 落本地收藏索引（SQLite）+ 审计

@router.get("/favorites/health")
async def favorites_health() -> dict:
    """Wiki 降级状态（前端状态条数据源）。"""
    return await router_backend.health()
```

### 10.5 前端组件要点（React 19 + shadcn/ui）

| 组件 | 要点 |
|------|------|
| 收藏按钮 | ChatPage 消息卡片尾部：星标 IconButton → 打开 `FavoriteDialog`（内容预填当前消息） |
| `FavoriteDialog` | Dialog + Textarea（可编辑）+ Select（五类记忆类型）+ 提交按钮；提交调 `POST /v1/favorites` |
| `FavoritesPage` | 列表 + storage 徽章（wiki 绿 / local 橙"待同步"）+ 删除 + "在 Wiki 打开"（`wiki_url`，url 来自后端，前端零配置） |
| 降级状态条 | 顶部 Banner：`GET /v1/favorites/health` 轮询（30s），`wiki_ok=false` 显示"Wiki 暂不可用，收藏将本地暂存" |

### 10.6 测试设计

| 组 | 用例 | 断言 |
|----|------|------|
| **WikiClient** | mock httpx：create/search 正常返回 | URL/headers/解析正确 |
| | 超时/5xx → WikiError 可重试；401 → 不可重试 | 错误分级正确 |
| | base_url 来自 settings（配置化） | 无硬编码断言 |
| **Router 降级** | wiki 连续失败 3 次 → 熔断，后续写本地 | storage=local + fail_count |
| | 熔断后探活恢复 → 回切 wiki | storage=wiki |
| | `wiki_enabled=false` → 直通本地 | 不发起 wiki 调用 |
| **收藏 API** | POST 正常（mock backend）→ 201 + storage | 响应 schema |
| | 非法 memory_type → 422 | 枚举校验 |
| | GET /favorites/health 返回 wiki_ok | 前端状态源 |
| **前端** | FavoriteDialog 提交 → 调用 API + toast（组件测试） | 调用参数正确 |
| **兼容** | `WIKI_ENABLED=false` 存量功能零影响 | 全量回归 |

---

## 附录：待确认问题清单

**A-1 对 Wiki 项目（对面）**（§5.3）：
- [ ] namespace/目录概念是否存在；更新语义全文替换 vs 增量；搜索是否支持 tag/namespace 过滤；鉴权方案；限流值

**A-2 本端待拍板**：
- [ ] 收藏入口除"消息卡片"外，是否需要页面级收藏（整篇对话摘要 → Logs）
- [ ] `WIKI_NAMESPACE_MAP` 配置化是否 P0 就要（当前代码常量，改动小，可后移）
- [ ] 本地收藏索引落 SQLite 还是文件（v3 记忆布局并行确认）

**A-3 与 v3 本地方案的关系**：
- [ ] LocalBackend 复用 v3 `decisions.md`/`tasks.md` 格式（降级时人工可读）——写入权限/格式与 v3 方案对齐，落地时核对 `方案-记忆能力开发-v3.md`
