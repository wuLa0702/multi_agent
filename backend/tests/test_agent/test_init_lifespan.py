"""无参初始化回归测试：防 NameError 再犯（2026-08-04 浏览器实测事故）。

事故：init_store() 无参路径调用未导入的 get_store_path() → NameError，
main.py lifespan 启动即崩。conftest 的 autouse fixture 总是传 db_path=tmp_path，
生产无参路径永不被测——本文件补齐这条链路（20-testing.md：正常/边界三态）。

实现要点：每个用例先 close 复位全局（conftest autouse 已以 tmp_path 初始化），
再把 src.core.paths.get_app_dir 指到 tmp 隔离区（不碰真实 data/），
无参调用即等价于 main.py lifespan 的调用路径。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.paths import CHECKPOINTER_DB_FILE, STORE_DB_FILE



async def _reset() -> None:
    """复位全局 store/checkpointer（与 conftest autouse 清理兼容，幂等）。"""
    from src.agent import main_agent

    await main_agent.close_store()
    await main_agent.close_checkpointer()


async def _teardown() -> None:
    """用例结束关闭连接并复位。"""
    from src.agent import main_agent

    await main_agent.close_store()
    await main_agent.close_checkpointer()


@pytest.mark.asyncio
async def test_init_store_no_arg_uses_prod_paths(tmp_path: Path, monkeypatch) -> None:
    """正常：无参 init_store 走 get_store_path()（曾 NameError），文件落数据目录。"""
    from src.agent import main_agent

    await _reset()
    fake_dir = tmp_path / "data"
    fake_dir.mkdir()
    monkeypatch.setattr("src.core.paths.get_app_dir", lambda: fake_dir)

    await main_agent.init_store()  # 无参 = main.py lifespan 同款调用

    assert main_agent._store is not None
    assert (fake_dir / STORE_DB_FILE).exists()
    await _teardown()


@pytest.mark.asyncio
async def test_init_checkpointer_no_arg_uses_prod_paths(tmp_path: Path, monkeypatch) -> None:
    """正常：无参 init_checkpointer 走 get_checkpointer_path()，文件落数据目录。"""
    from src.agent import main_agent

    await _reset()
    fake_dir = tmp_path / "data"
    fake_dir.mkdir()
    monkeypatch.setattr("src.core.paths.get_app_dir", lambda: fake_dir)

    await main_agent.init_checkpointer()  # 无参 = main.py lifespan 同款调用

    assert main_agent._checkpointer is not None
    assert (fake_dir / CHECKPOINTER_DB_FILE).exists()
    await _teardown()


@pytest.mark.asyncio
async def test_init_store_dir_arg_appends_filename(tmp_path: Path) -> None:
    """正常：传目录 → 目录下拼 store.db（conftest 隐式路径的显式断言）。"""
    from src.agent import main_agent

    await _reset()
    await main_agent.init_store(db_path=tmp_path)

    assert main_agent._store is not None
    assert (tmp_path / STORE_DB_FILE).exists()
    await _teardown()


@pytest.mark.asyncio
async def test_init_checkpointer_dir_arg_appends_filename(tmp_path: Path) -> None:
    """正常：传目录 → 目录下拼 checkpoints.db。"""
    from src.agent import main_agent

    await _reset()
    await main_agent.init_checkpointer(db_path=tmp_path)

    assert main_agent._checkpointer is not None
    assert (tmp_path / CHECKPOINTER_DB_FILE).exists()
    await _teardown()


@pytest.mark.asyncio
async def test_init_store_file_arg_used_directly(tmp_path: Path) -> None:
    """边界：传文件路径 → 直接建该文件，不在其父目录另拼。

    用独立子目录做父目录（conftest autouse 已用 tmp_path 初始化过 store，
    父目录残留 store.db 属正常，断言子目录干净才可靠）。
    """
    from src.agent import main_agent

    await _reset()
    sub = tmp_path / "sub"
    sub.mkdir()
    target = sub / "custom_store.db"

    await main_agent.init_store(db_path=target)

    assert main_agent._store is not None
    assert target.exists()
    assert not (sub / STORE_DB_FILE).exists()  # 不得在父目录另拼文件名
    await _teardown()


@pytest.mark.asyncio
async def test_init_idempotent_second_call_noop(tmp_path: Path, monkeypatch) -> None:
    """边界：重复无参调用幂等（已初始化 → 直接返回，不重复建连接）。"""
    from src.agent import main_agent

    await _reset()
    fake_dir = tmp_path / "data"
    fake_dir.mkdir()
    monkeypatch.setattr("src.core.paths.get_app_dir", lambda: fake_dir)

    await main_agent.init_store()
    first = main_agent._store
    await main_agent.init_store()  # 二次调用 → no-op

    assert main_agent._store is first
    await _teardown()
