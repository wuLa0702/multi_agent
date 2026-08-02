"""冒烟测试：基建可用性（配置/路径/环境切换）。

覆盖：正常路径（dev 环境加载）、边界（无 .env 时默认值）、错误路径（密钥不暴露）。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.config import get_settings, settings  # noqa: E402
from src.core.paths import get_app_dir, get_db_path, get_log_dir, is_cloud  # noqa: E402


def test_dev_env_loaded(app_env_dev) -> None:
    """正常路径：dev 环境读取 .env.dev（APP_ENV=dev → 非 prod）。"""
    assert settings.app_env == "dev"
    assert settings.is_prod is False


def test_provider_default_deepseek() -> None:
    """正常路径：默认 provider 为 deepseek，配置键齐全。"""
    cfg = settings.provider_config()
    assert cfg["base_url"] == "https://api.deepseek.com/v1"
    assert cfg["model"] == "deepseek-chat"
    assert "api_key" in cfg


def test_paths_local_on_windows() -> None:
    """边界条件：Windows 上不误判云端，路径指向项目 data/logs。"""
    if sys.platform == "win32":
        assert is_cloud() is False
        assert str(get_app_dir()).endswith("data")
        assert str(get_log_dir()).endswith("logs")


def test_db_path_under_data() -> None:
    """正常路径：SQLite 数据库落在数据目录下。"""
    db = get_db_path()
    assert db.name == "wiki.db"
    assert db.parent.name == "data"


def test_config_never_exposes_raw_secrets_in_defaults() -> None:
    """错误路径：默认配置不含任何密钥字面量（密钥只从 .env 注入）。"""
    for v in [settings.deepseek_api_key, settings.ark_api_key, settings.zhipu_api_key]:
        # 未配置时为空串，绝不等于示例 key 或占位符
        assert "lsv2_pt" not in v
        assert "95af8b85" not in v


def test_redis_url_never_points_to_clowder_prod_port(monkeypatch) -> None:
    """安全护栏：环境注入 6399（Clowder 生产端口）也会被拦截替换为 6398。"""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6399/0")
    get_settings.cache_clear()
    guarded = get_settings()
    assert guarded.redis_url == "redis://localhost:6398/0"  # 护栏替换后的 dev 端口
    get_settings.cache_clear()  # 还原缓存，避免污染其他测试
