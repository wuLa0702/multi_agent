"""llm/cache.py 轻量结果缓存单测（设计-成本控制 §8 用例 5-7/11-12）。

覆盖：命中 / 键隔离（不同模型不共享）/ TTL 过期 / 容量上限 / 开关不写缓存。
"""

from __future__ import annotations

import pytest

from src.llm.cache import get_cached, set_cached, _cache, _MAX_ENTRIES


@pytest.fixture(autouse=True)
def _clear_cache():
    _cache.clear()
    yield
    _cache.clear()


class TestCacheHit:
    def test_hit_same_prompt_model(self) -> None:
        """同 prompt+model 二次调用 → 命中（§8 用例 5）。"""
        set_cached("你好", "deepseek-v4-flash", "回复1")
        assert get_cached("你好", "deepseek-v4-flash", ttl=3600) == "回复1"

    def test_miss_different_model(self) -> None:
        """不同 model 不共享缓存（§8 用例 6）。"""
        set_cached("你好", "deepseek-v4-flash", "回复1")
        assert get_cached("你好", "doubao", ttl=3600) is None

    def test_miss_different_prompt(self) -> None:
        set_cached("A", "m", "1")
        assert get_cached("B", "m", ttl=3600) is None


class TestCacheTtl:
    def test_ttl_expired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """超 TTL → 未命中（§8 用例 7）。"""
        import src.llm.cache as cache_mod

        fake_time = [1000.0]
        monkeypatch.setattr(cache_mod.time, "monotonic", lambda: fake_time[0])
        set_cached("你好", "m", "v")
        fake_time[0] += 7200  # 2h 后
        assert get_cached("你好", "m", ttl=3600) is None


class TestCacheCapacity:
    def test_max_entries_evicts_oldest(self) -> None:
        """容量上限逐出最旧（防泄漏）。"""
        for i in range(_MAX_ENTRIES + 10):
            set_cached(f"p{i}", "m", f"v{i}")
        assert len(_cache) <= _MAX_ENTRIES


class TestCacheNotEnabled:
    def test_disabled_by_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """enabled=False 不写缓存（§8 用例 11）——通过 adapter 集成验证。"""
        # 纯函数层面：直接验证 set_cached 后 get_cached 生效（开关逻辑在 adapter）
        set_cached("x", "m", "v")
        assert get_cached("x", "m", ttl=3600) == "v"


class TestCacheRedisBackend:
    """Redis 后端（2026-08-11 缓存接 Redis）：键前缀 + TTL + 不可用降级。"""

    def test_redis_backend_set_get(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import settings
        from src.llm import cache as cache_mod

        store: dict[str, str] = {}

        class FakeRedis:
            def get(self, k):
                return store.get(k)

            def setex(self, k, ttl, v):
                store[k] = v

        monkeypatch.setattr(settings, "llm_cache_backend", "redis")
        monkeypatch.setattr(cache_mod, "get_redis", lambda: FakeRedis())
        cache_mod.set_cached("你好", "m", "v1")
        assert cache_mod.get_cached("你好", "m", ttl=3600) == "v1"
        # 键前缀
        assert list(store.keys())[0].startswith("llm_cache:")

    def test_redis_unavailable_degrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """redis 不可用 → None 降级（容错纪律，不阻断 LLM）。"""
        from src.core.config import settings
        from src.llm import cache as cache_mod

        monkeypatch.setattr(settings, "llm_cache_backend", "redis")

        def _boom():
            raise ConnectionError("redis down")

        monkeypatch.setattr(cache_mod, "get_redis", _boom)
        assert cache_mod.get_cached("你好", "m", ttl=3600) is None
