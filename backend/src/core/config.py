"""配置中心：Pydantic BaseSettings，.env.dev / .env.prod 双配置驱动。

环境策略（v2.2 拍板）：同一套代码 + 同一份 docker-compose.yml，
只换 --env-file 指向不同 .env；OpenSandbox 与 Redis 连云端，不本地部署。

用法：
    from src.core.config import settings
    settings.deepseek_api_key   # str
    settings.sandbox_url        # str
"""

from __future__ import annotations

import os
import warnings
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── 环境文件选择（v2.2 配置驱动切换）──
# 由进程环境变量 APP_ENV 决定加载哪个 .env（docker compose --env-file 注入，
# 或本地 export APP_ENV=dev）。绝不叠加读取多个 .env（会互相覆盖，难排查）。
_APP_ENV = os.getenv("APP_ENV", "dev").lower()

# 项目根（backend/src/core → 项目根，与 paths.py 同一约定）。
# 必须用绝对路径：pydantic-settings 从进程 cwd 找相对 env_file，而后端从
# backend/ 启动（uvicorn -m），cwd 不含 .env.dev，会静默读到全空配置。
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / (".env.prod" if _APP_ENV == "prod" else ".env.dev")

# ── 安全护栏：Clowder AI 生产 Redis 端口 ──
# 家规硬约束：6399 是 Clowder AI 生产 Redis，外部项目严禁连接；dev/test 用 6398。
# 风险点：本机运行环境可能注入 REDIS_URL=redis://localhost:6399（pydantic-settings
# 优先级：环境变量 > .env 文件 > 默认值），直接读取会连到 Clowder 生产存储。
# 护栏在 Settings 层统一拦截——无论 REDIS_URL 来自环境变量还是 .env，端口 6399
# 一律替换为本地 dev 端口，保证本项目任何代码路径都触碰不到生产 Redis。
_CLOWDER_PROD_REDIS_PORT = 6399
_SAFE_DEV_REDIS_URL = "redis://localhost:6398/0"


class Settings(BaseSettings):
    """全局配置。字段名与 .env 键一一对应（忽略大小写）。"""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 运行环境 ──
    app_env: str = Field(default="dev", description="dev / prod，控制路径探测与日志级别")

    # ── LLM 多 provider（OpenAI 兼容协议）──
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"

    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_model: str = ""

    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_model: str = "glm-4-plus"

    llm_provider: str = Field(default="deepseek", description="deepseek / ark / zhipu")

    # ── 沙箱（OpenSandbox：本地 dev 连 docker 8080，prod 连云端）──
    sandbox_url: str = ""
    sandbox_api_key: str = ""

    # ── 沙箱池（2026-08-05 能力计划 §3.1/§3.5：配置化，代码零写死）──
    # 会话级池化总开关：False = 一次性语义（工具自管生命周期 try/finally destroy）
    sandbox_pool_enabled: bool = True
    # 池化默认镜像（现有 adapter.DEFAULT_IMAGE 迁移）
    sandbox_image: str = "python:3.11"
    # 沙箱 TTL 秒（现 DEFAULT_TIMEOUT=30min 迁移；取用即 renew 续期）
    sandbox_timeout: int = 1800
    # 空闲回收阈值（15min 无取用即销毁）
    sandbox_idle_ttl: int = 900
    # 并发沙箱上限（本地 6；云端 .env.prod 改 4——4G 云 4 个并发对话封顶）
    sandbox_pool_max: int = 6
    # 单沙箱 CPU 限额（云端 .env.prod 改 0.5）
    sandbox_cpu: str = "1"
    # 单沙箱内存限额（云端 .env.prod 改 512Mi；SDK 默认 2Gi 云端吃满）
    sandbox_memory: str = "1Gi"
    # 单次命令输出截断字节（防上下文爆炸）
    sandbox_output_limit: int = 8192
    # 快照模板 ID（P2）：依赖预装后 create_snapshot 生成，配置后起沙箱跳过拉镜像/装依赖
    sandbox_snapshot_id: str = ""

    # ── 事件流增强（2026-08-05 引入方案；默认开——多事件分发）──
    # True = token 走 v2 chunk 流（打字机不退化）+ 多事件分发
    #   （tool_call/subagent 事件，契约 v3 落地）
    # False = 仅 token 流（回退旧行为，排查用）
    # 实测结论（2026-08-05）：v3 messages 投影为 message 粒度且本模型栈
    # 无 content-block 协议——token 通道必须保留 v2 chunk；v3 声明式投影
    # 仅作学习脚本（examples/event_streaming_v3_demo.py）
    event_stream_v3: bool = True
    # True = 挂载 CodeInterpreterMiddleware（QuickJS eval + PTC）。
    # ⚠️ 环境阻塞（2026-08-05 实测）：Python 3.14 无 bsdiff4 wheel 且源码构建
    # 失败（langchain-quickjs 硬依赖）——当前环境开启会得到明确错误提示；
    # 换 3.11/3.12 venv 或 bsdiff4 出 wheel 后即可用
    interpreter_enabled: bool = False
    # PTC 白名单（逗号分隔；🔴 只允许只读工具——PTC 调用绕 interrupt_on 审批）
    interpreter_ptc: str = "internet_search"
    # Agent 图单次运行递归上限（2026-08-10 评估体系实证：研究任务多轮搜索
    # 频繁撞默认 25 → 调 50；成本权衡：上限翻倍 = 循环失控时 LLM 调用上限翻倍，
    # 需结合成本/用量告警使用；调小可降低单次成本上限）
    agent_recursion_limit: int = 50
    # 工具调用统一超时（秒，2026-08-11 容错 P1-d）：fetch_url 等网络工具
    # 单次请求超时——超时抛 TimeoutException → 被重试装饰器捕获 → 重试 → 降级
    tool_timeout_seconds: float = 10.0
    # 对话流并发上限（2026-08-10 拍板：环境保存，替代 main_agent 硬编码 4）：
    # SQLite checkpointer 写锁是硬约束——Semaphore 限制同时执行的流数量，超出排队。
    # 本地 .env.dev=10（开发机强）；云端 .env.prod=2（2核4g 保守）——开大先验
    # 限流/写锁，出问题再调小（co-creator 拍板：本地允许 10，云端 2）
    stream_concurrency: int = 4
    # ── 成本控制（2026-08-11 设计 §4.3/§4.4/§5.3/§5.4）──
    # LLM 结果缓存开关（面试演示开；生产按需）
    llm_cache_enabled: bool = False
    llm_cache_ttl: int = 3600            # 缓存有效期（秒）
    # 缓存后端：memory（进程内存，单用户够用）/ redis（生产，跨进程持久化，2026-08-11）
    llm_cache_backend: str = "memory"
    # 会话成本软告警阈值（元，>0 启用；只记录+告警，不做硬限制——用户拍板）
    session_cost_warn_threshold: float = 5.0

    # ── 人在回路 / Rubric（2026-08-06 设计：docs/decisions/方案-人在回路与Rubric评分-详细设计-v1.md）──
    # HITL 审批：True = 沙箱/文件/技能等副作用工具执行前人类审批（按风险分级，见 agent/hitl/hitl.py）。
    # 需 checkpointer（已接）；默认关，业务接入时开。
    hitl_enabled: bool = False
    # Rubric 自评：True = 挂载 RubricMiddleware（LLM-as-judge 按 rubric 迭代）。
    # ⚠️ P0-V1 验证（设计 §6.1：grader response_format 国产模型风险）通过前保持 False——
    # 验证是开发动作，通过后直接开本开关，无"验证过"中间态（v1.2 评审修正）。
    rubric_enabled: bool = False
    # 输出审核修订上限（2026-08-11 P0 HITL 设计 §5.4，v1.2 评审修正：配置化不硬编码）：
    # publish_report 被拒后模型修订重出次数上限；resume 时计数 > 上限 → 注入
    # SystemMessage 提示模型输出当前版本并停止修订（防无限修订循环）。0 = 不注入。
    publish_review_max_revisions: int = 2

    # ── 记忆/存储 ──
    redis_url: str = "redis://localhost:6379/0"
    db_path: str = "./data/wiki.db"

    # ── 搜索（博查 Bocha：国内 Tavily 平替，2026-08-03 拍板）──
    bocha_api_key: str = ""
    bocha_base_url: str = "https://api.bocha.cn/v1"

    @model_validator(mode="after")
    def _guard_clowder_prod_redis(self) -> "Settings":
        """护栏：任何来源的 redis_url 若指向 6399（Clowder 生产 Redis），
        替换为本地 dev 端口 6398 并告警——外部项目永不触碰 Clowder 生产存储。

        触发场景：Clowder 运行环境注入 REDIS_URL=redis://localhost:6399，
        pydantic-settings 会让环境变量覆盖 .env.dev 的值。
        """
        port = urlparse(self.redis_url).port
        if port == _CLOWDER_PROD_REDIS_PORT:
            warnings.warn(
                f"REDIS_URL={self.redis_url!r} 指向 Clowder 生产端口 {_CLOWDER_PROD_REDIS_PORT}，"
                f"已拦截并替换为 {_SAFE_DEV_REDIS_URL}（家规硬约束：外部项目禁连 6399）",
                stacklevel=2,
            )
            self.redis_url = _SAFE_DEV_REDIS_URL
        return self

    # ── 监控 ──
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "multi-agent"

    # ── Web ──
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # ── MCP ──
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 9000

    # ── Skill Market（Smithery 托管 server 连接鉴权；浏览无需 key）──
    smithery_api_key: str = ""

    # ── 工作区模式（v2.0 设计：CompositeBackend 内存/磁盘双模式）──
    # True = 内存临时（StateBackend，dev 测试兼容"重启清空"）；False = 磁盘持久（prod 默认）
    memory_workspace: bool = False

    # ── 安全分层（2026-08-04 深化 v3）──
    # 策略层总开关：False = PolicyBackend 透明直通（测试隔离/性能对比/排查）
    backend_policy_enabled: bool = True
    # 子代理隔离：False(默认) = P1 权限覆盖（原生）；True = P2 编译子代理独立内存 backend
    subagent_isolation: bool = False

    # ── 记忆抽取子代理（2026-08-05 记忆抽取子代理方案）──
    # True=子代理后台抽取（队列+多步+工具）；False=回退单次 LLM 抽取
    memory_agent_enabled: bool = True
    # 抽取专用模型（小模型省钱；空=主模型兜底——用户拍板 2026-08-05）
    memory_agent_model: str = ""

    # ── 上下文工程（2026-08-05 开发计划 v2）──
    # 工具结果驱逐阈值（默认对齐官方 20000；⚠️ P1 只观察不盲调——
    # create_deep_agent 无直接参数，P2 自定义中间件时才真正生效）
    context_tool_evict_limit: int = 20000

    @property
    def is_prod(self) -> bool:
        """是否生产环境。"""
        return self.app_env.lower() == "prod"

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS 白名单（逗号分隔 → 列表）。"""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def provider_config(self, name: str | None = None) -> dict[str, str]:
        """查询指定 provider 的调用参数（base_url + api_key + model）。

        Args:
            name: provider 名（deepseek / ark / zhipu）；None → llm_provider 默认值

        Returns:
            {"base_url": ..., "api_key": ..., "model": ...}

        Raises:
            ValueError: 未知 provider 名（含 .env 里 llm_provider 配错的情况）
        """
        provider = (name or self.llm_provider).lower()
        if provider == "ark":
            return {
                "base_url": self.ark_base_url,
                "api_key": self.ark_api_key,
                "model": self.ark_model,
            }
        if provider == "zhipu":
            return {
                "base_url": self.zhipu_base_url,
                "api_key": self.zhipu_api_key,
                "model": self.zhipu_model,
            }
        if provider == "deepseek":
            return {
                "base_url": self.deepseek_base_url,
                "api_key": self.deepseek_api_key,
                "model": self.deepseek_model,
            }
        raise ValueError(f"未知 LLM provider={provider}，可选：deepseek / ark / zhipu")


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置（LLM 调用高频，缓存避免重复解析 .env）。"""
    return Settings()


settings = get_settings()
