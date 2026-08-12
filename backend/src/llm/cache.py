"""LLM 结果缓存（设计 §4.3/§5.3）：轻量内存 dict + TTL。

- key = sha1(prompt + model_name)——不同模型不共享缓存
- settings.llm_cache_enabled 开关；llm_cache_ttl 过期
- 缓存不可用/异常 → 直接调 LLM（降级不阻断，容错纪律）
- P2 升级：LRU 上限 + 语义相似检索（记忆 Store 对接）
"""

from __future__ import annotations

import hashlib
import threading
import time

from src.core.redis import get_redis  # 模块级（llm → core 依赖合规；测试可 patch）

_cache: dict[str, tuple[float, str]] = {}
_REDIS_PREFIX = "llm_cache"  # Redis 键前缀（生产后端）
_lock = threading.Lock()
_MAX_ENTRIES = 1024  # 容量上限（防泄漏，超限逐出最旧）


def _key(prompt: str, model_name: str) -> str:
    """缓存键：prompt + model 哈希（不同模型不共享）。

    Args:
        prompt: 输入 prompt
        model_name: 模型名

    Returns:
        sha1 十六进制键
    """
    return hashlib.sha1(f"{model_name}:{prompt}".encode()).hexdigest()


def get_cached(prompt: str, model_name: str, ttl: int) -> str | None:
    """查缓存（未命中/过期返回 None；按 settings.llm_cache_backend 分发）。

    - memory：进程内存 dict（单用户够用）
    - redis：Redis GET（生产跨进程持久化；redis 不可用 → None 降级直接调 LLM）

    Args:
        prompt: 输入 prompt
        model_name: 模型名（缓存键维度）
        ttl: 有效期（秒）

    Returns:
        缓存结果；None=未命中/过期/redis 不可用
    """
    from src.core.config import settings

    if settings.llm_cache_backend == "redis":
        return _get_redis(prompt, model_name)
    return _get_memory(prompt, model_name, ttl)


def set_cached(prompt: str, model_name: str, value: str) -> None:
    """写入缓存（按 settings.llm_cache_backend 分发）。

    Args:
        prompt: 输入 prompt
        model_name: 模型名
        value: 模型回复
    """
    from src.core.config import settings

    if settings.llm_cache_backend == "redis":
        _set_redis(prompt, model_name, value)
    else:
        _set_memory(prompt, model_name, value)


def _get_memory(prompt: str, model_name: str, ttl: int) -> str | None:
    """内存后端：dict + TTL（未命中/过期返回 None）。"""
    key = _key(prompt, model_name)
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > ttl:
            _cache.pop(key, None)
            return None
        return value


def _set_memory(prompt: str, model_name: str, value: str) -> None:
    """内存后端：写入（容量上限逐出最旧）。"""
    key = _key(prompt, model_name)
    with _lock:
        if len(_cache) >= _MAX_ENTRIES:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest, None)
        _cache[key] = (time.monotonic(), value)


def _get_redis(prompt: str, model_name: str) -> str | None:
    """Redis 后端：GET llm_cache:{sha1}（redis 不可用 → None 降级，容错纪律）。"""
    try:
        return get_redis().get(f"{_REDIS_PREFIX}:{_key(prompt, model_name)}")
    except Exception:  # noqa: BLE001 - redis 不可用降级，不阻断 LLM 调用
        return None


def _set_redis(prompt: str, model_name: str, value: str) -> None:
    """Redis 后端：SETEX（TTL 取 settings.llm_cache_ttl；redis 不可用静默跳过）。"""
    from src.core.config import settings

    try:
        get_redis().setex(
            f"{_REDIS_PREFIX}:{_key(prompt, model_name)}", settings.llm_cache_ttl, value
        )
    except Exception:  # noqa: BLE001 - redis 不可用跳过，不阻断
        return
