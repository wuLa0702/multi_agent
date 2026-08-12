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

_cache: dict[str, tuple[float, str]] = {}
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
    """查缓存（未命中/过期返回 None）。

    Args:
        prompt: 输入 prompt
        model_name: 模型名（缓存键维度）
        ttl: 有效期（秒）

    Returns:
        缓存结果；None=未命中/过期
    """
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


def set_cached(prompt: str, model_name: str, value: str) -> None:
    """写入缓存（容量上限逐出最旧）。

    Args:
        prompt: 输入 prompt
        model_name: 模型名
        value: 模型回复
    """
    key = _key(prompt, model_name)
    with _lock:
        if len(_cache) >= _MAX_ENTRIES:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest, None)
        _cache[key] = (time.monotonic(), value)
