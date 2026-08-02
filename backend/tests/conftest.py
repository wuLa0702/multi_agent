"""共享 Fixture：mock LLM / tmp_path / :memory: 数据库。

约定（.claude/rules/20-testing.md）：
- LLM 全部 mock，不实际调 API
- 文件系统用 tmp_path，数据库用 :memory:
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 backend 可导入（src/ 是包，import src.core.config 需要 backend 在 path 上）
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def app_env_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制 APP_ENV=dev，避免测试误读 .env.prod。"""
    monkeypatch.setenv("APP_ENV", "dev")


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """临时数据目录（替代真实 data/，测试隔离）。"""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def mock_llm_chat(mocker) -> None:
    """Mock LLMAdapter.chat 返回值（按需 override return_value）。"""
    mocker.patch("src.llm.adapter.LLMAdapter.chat", return_value="mock response")
