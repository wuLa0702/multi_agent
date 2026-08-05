"""SandboxPool 会话级沙箱池测试（能力计划 §5 池化组 + 评审 2 修复用例）。

覆盖（全 mock，不连 docker）：
- 同 thread 复用 + renew 续期；不同 thread 独立实例
- 空闲 sweep 销毁；pool_max 超限 SandboxFullError
- 续期失败 → 销毁重建（评审问题 2）
- 非池化模式直通（不托管）；生命周期审计行
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.core.config import settings
from src.sandbox.pool import SandboxFullError, SandboxPool


def _fake_sandbox(sid: str, *, fail_renew: bool = False):
    """假沙箱：id + renew（fail_renew=True 时 renew 抛异常）。"""
    sb = SimpleNamespace(id=sid)
    if fail_renew:
        sb.renew = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("renew boom"))
    else:
        sb.renew = lambda *a, **k: None
    return sb


def _make_pool(monkeypatch, *, pool_max: int = 3, idle_ttl: int = 900, enabled: bool = True):
    """构造假适配器池：create 计数可断言；destroy 记录被调。"""
    created: list = []
    destroyed: list = []

    class _FakeAdapter:
        def create_sandbox(self, *a, **k):
            sb = _fake_sandbox(f"sb-{len(created)}")
            created.append(sb)
            return sb

        def destroy(self, sandbox) -> None:
            destroyed.append(sandbox)

    monkeypatch.setattr(settings, "sandbox_pool_enabled", enabled)
    monkeypatch.setattr(settings, "sandbox_pool_max", pool_max)
    monkeypatch.setattr(settings, "sandbox_idle_ttl", idle_ttl)
    monkeypatch.setattr(settings, "sandbox_timeout", 1800)
    pool = SandboxPool(_FakeAdapter())
    return pool, created, destroyed


def test_pool_reuses_sandbox_per_thread(monkeypatch) -> None:
    """池化：同 thread 两次取用 → 同一实例（create 只 1 次）+ renew 续期。"""
    pool, created, _ = _make_pool(monkeypatch)

    sb1 = pool.get_sandbox("t1")
    sb2 = pool.get_sandbox("t1")

    assert sb1 is sb2, "同会话应复用同一沙箱（文件/环境保留）"
    assert len(created) == 1, "同会话只 create 一次"


def test_pool_isolates_threads(monkeypatch) -> None:
    """池化：不同 thread → 独立沙箱实例。"""
    pool, created, _ = _make_pool(monkeypatch)

    sb1 = pool.get_sandbox("t1")
    sb2 = pool.get_sandbox("t2")

    assert sb1 is not sb2, "不同会话必须独立沙箱（会话级隔离）"
    assert len(created) == 2


def test_pool_sweep_destroys_idle(monkeypatch) -> None:
    """空闲回收：超过 idle_ttl 未取用的沙箱被销毁；活跃的保留。"""
    pool, _, destroyed = _make_pool(monkeypatch, idle_ttl=900)
    pool.get_sandbox("idle")
    pool.get_sandbox("active")
    # 模拟 idle 早、active 新：直接改 last_used 时间戳
    import time

    pool._entries["idle"].last_used = time.time() - 3600

    removed = pool.sweep()

    assert removed == 1
    assert [d.id for d in destroyed] == ["sb-0"], "idle 沙箱应销毁"
    assert "active" in pool._entries, "活跃沙箱保留"


def test_pool_max_raises_full(monkeypatch) -> None:
    """池上限：pool_max=2 时第 3 个 thread 取用 → SandboxFullError（不排队不无限创建）。"""
    pool, created, _ = _make_pool(monkeypatch, pool_max=2)
    pool.get_sandbox("a")
    pool.get_sandbox("b")

    with pytest.raises(SandboxFullError, match="沙箱资源已满"):
        pool.get_sandbox("c")
    assert len(created) == 2, "超限不得创建新沙箱"


def test_pool_renew_failure_rebuilds(monkeypatch) -> None:
    """评审 2：续期失败 → 旧沙箱销毁、get_sandbox 重建返回新实例（不返回死沙箱）。"""
    pool, created, destroyed = _make_pool(monkeypatch)
    first = pool.get_sandbox("t1")
    # 让沙箱 renew 抛异常（续期失败场景）
    first.renew = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("renew boom"))

    rebuilt = pool.get_sandbox("t1")

    assert rebuilt is not first, "续期失败必须返回新沙箱（评审问题 2）"
    assert [d.id for d in destroyed] == ["sb-0"], "旧沙箱应被销毁"
    assert len(created) == 2, "重建触发新 create"


def test_pool_disabled_returns_fresh(monkeypatch) -> None:
    """兼容：sandbox_pool_enabled=False → 每次新建（池不托管生命周期）。"""
    pool, created, _ = _make_pool(monkeypatch, enabled=False)

    sb1 = pool.get_sandbox("t1")
    sb2 = pool.get_sandbox("t1")

    assert sb1 is not sb2, "非池化模式每次新建（旧一次性语义）"
    assert len(created) == 2


def test_pool_audits_lifecycle(monkeypatch, audit_records) -> None:
    """生命周期审计：create/destroy 事件写 layer=sandbox 扁平 JSON。"""
    pool, _, _ = _make_pool(monkeypatch)
    sb = pool.get_sandbox("t1")
    pool.destroy("t1")

    events = [json.loads(r.getMessage()) for r in audit_records]
    creates = [e for e in events if e["event"] == "create"]
    destroys = [e for e in events if e["event"] == "destroy"]
    assert len(creates) == 1 and creates[0]["layer"] == "sandbox"
    assert creates[0]["thread_id"] == "t1"
    assert destroys[0]["sandbox_id"] == sb.id
