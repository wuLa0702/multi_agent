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
