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
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── 环境文件选择（v2.2 配置驱动切换）──
# 由进程环境变量 APP_ENV 决定加载哪个 .env（docker compose --env-file 注入，
# 或本地 export APP_ENV=dev）。绝不叠加读取多个 .env（会互相覆盖，难排查）。
_APP_ENV = os.getenv("APP_ENV", "dev").lower()
_ENV_FILE = ".env.prod" if _APP_ENV == "prod" else ".env.dev"


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
    deepseek_model: str = "deepseek-chat"

    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_model: str = ""

    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_model: str = "glm-4-plus"

    llm_provider: str = Field(default="deepseek", description="deepseek / ark / zhipu")

    # ── 沙箱（云端 OpenSandbox，本地不部署）──
    sandbox_url: str = ""
    sandbox_api_key: str = ""

    # ── 记忆/存储 ──
    redis_url: str = "redis://localhost:6379/0"
    db_path: str = "./data/wiki.db"

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

    @property
    def is_prod(self) -> bool:
        """是否生产环境。"""
        return self.app_env.lower() == "prod"

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS 白名单（逗号分隔 → 列表）。"""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def provider_config(self) -> dict[str, str]:
        """当前默认 provider 的调用参数（base_url + api_key + model）。"""
        provider = self.llm_provider.lower()
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
        return {
            "base_url": self.deepseek_base_url,
            "api_key": self.deepseek_api_key,
            "model": self.deepseek_model,
        }


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置（LLM 调用高频，缓存避免重复解析 .env）。"""
    return Settings()


settings = get_settings()
