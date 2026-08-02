"""Redis 连接池：进程级单例 + FastAPI lifespan 管理。

短期记忆语义（业务数据结构 v3 再细化，现在先立地基）：
- 连接池进程级共享（redis.asyncio 内部管理连接复用）
- 惰性创建：本地没 Redis 也能启动，health 检查降级为 disconnected 不崩溃

用法：
    from src.core.redis import get_redis, close_redis
    redis = get_redis()
    await redis.ping()
    await redis.set("sessions:{id}", ...)   # v3 业务键
"""

from __future__ import annotations

from redis.asyncio import Redis

from src.core.config import settings

# 进程级单例（lifespan 启动时创建，关闭时释放；懒加载兜底）
_redis: Redis | None = None


def get_redis() -> Redis:
    """返回进程级 Redis 客户端（未初始化时惰性创建）。

    Returns:
        redis.asyncio.Redis：decode_responses=True（字符串语义，避免 bytes 坑）
    """
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """关闭连接池（FastAPI lifespan 关闭时调用，幂等）。"""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
