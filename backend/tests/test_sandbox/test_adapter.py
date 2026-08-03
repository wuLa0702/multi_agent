"""OpenSandboxAdapter 单测：mock SDK，不连 docker。

约定（20-testing.md）：外部依赖全部 mock；本文件验证 adapter 的生命周期
编排与输出拼装逻辑，真实 docker 链路由 demo 的"模拟调用一次"集成验证覆盖。
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.core.config import settings
from src.sandbox.adapter import DEFAULT_IMAGE, DEFAULT_TIMEOUT, OpenSandboxAdapter


def _execution(
    stdout_lines: list[str],
    stderr_lines: list[str] | None = None,
    exit_code: int | None = 0,
) -> SimpleNamespace:
    """构造 SDK Execution 替身（只含 adapter 用到的字段）。"""
    return SimpleNamespace(
        logs=SimpleNamespace(
            stdout=[SimpleNamespace(text=t) for t in stdout_lines],
            stderr=[SimpleNamespace(text=t) for t in (stderr_lines or [])],
        ),
        exit_code=exit_code,
    )


@pytest.fixture
def sandbox_url_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    """清空 sandbox 配置，验证 adapter 的默认回退（不依赖 .env.dev）。"""
    monkeypatch.setattr(settings, "sandbox_url", "")
    monkeypatch.setattr(settings, "sandbox_api_key", "")


class TestRunCodeLifecycle:
    """run_code 一键执行：生命周期编排正确、失败必清理。"""

    def test_run_code_full_chain(self, mocker) -> None:
        """正常链路：create → write_file → run(python 脚本) → destroy，返回 stdout。"""
        fake = SimpleNamespace(
            files=SimpleNamespace(write_file=mocker.Mock()),
            commands=SimpleNamespace(run=mocker.Mock(return_value=_execution(["Hello", "2"]))),
            destroy=mocker.Mock(),
        )
        create_mock = mocker.patch(
            "src.sandbox.adapter.SandboxSync.create", return_value=fake
        )

        adapter = OpenSandboxAdapter(url="http://test:8080", api_key="k")
        out = adapter.run_code('print("Hello")', filename="hello.py")

        assert out == "Hello\n2"
        fake.files.write_file.assert_called_once_with("hello.py", 'print("Hello")')
        fake.commands.run.assert_called_once_with("python hello.py")
        fake.destroy.assert_called_once()
        # 创建参数：镜像（位置参数）、超时、server-proxy 连接配置
        args, kwargs = create_mock.call_args
        assert args[0] == DEFAULT_IMAGE
        assert kwargs["timeout"] == DEFAULT_TIMEOUT
        assert kwargs["connection_config"].use_server_proxy is True

    def test_run_code_destroys_on_error(self, mocker) -> None:
        """write_file 抛异常时 destroy 仍执行（finally 清理语义，不留僵尸沙箱）。"""
        fake = SimpleNamespace(
            files=SimpleNamespace(write_file=mocker.Mock(side_effect=RuntimeError("boom"))),
            commands=mocker.Mock(),
            destroy=mocker.Mock(),
        )
        mocker.patch("src.sandbox.adapter.SandboxSync.create", return_value=fake)

        adapter = OpenSandboxAdapter(url="http://test:8080", api_key="k")
        with pytest.raises(RuntimeError, match="boom"):
            adapter.run_code("x")

        fake.destroy.assert_called_once()

    def test_run_command_nonzero_exit_includes_stderr(self, mocker) -> None:
        """非零退出码：输出附 stderr 与退出码（调试信息不丢）。"""
        fake = SimpleNamespace(
            files=SimpleNamespace(write_file=mocker.Mock()),
            commands=SimpleNamespace(
                run=mocker.Mock(
                    return_value=_execution(["oops"], stderr_lines=["Traceback..."], exit_code=1)
                )
            ),
            destroy=mocker.Mock(),
        )
        mocker.patch("src.sandbox.adapter.SandboxSync.create", return_value=fake)

        adapter = OpenSandboxAdapter(url="http://test:8080", api_key="k")
        out = adapter.run_code("raise ValueError()")

        assert "[exit=1]" in out
        assert "Traceback..." in out


class TestConnectionConfig:
    """连接配置：默认回退 + server-proxy 恒开（docker bridge 部署通用解）。"""

    def test_defaults_when_no_config(self, sandbox_url_cleared) -> None:
        """无 url/key：domain 回退 localhost:8080（本地 docker 默认地址）。"""
        adapter = OpenSandboxAdapter()
        config = adapter._connection_config()

        assert config.get_domain() == "localhost:8080"
        assert config.get_api_key() == ""
        assert config.use_server_proxy is True
        assert config.request_timeout == timedelta(seconds=120)

    def test_injected_url_wins(self) -> None:
        """显式传入 url/key：优先于 settings。"""
        adapter = OpenSandboxAdapter(url="http://sandbox.example:9999", api_key="secret")
        config = adapter._connection_config()

        # domain 保留原始值（SDK 负责拼协议），base_url 正确拼接 /v1
        assert config.domain == "http://sandbox.example:9999"
        assert config.get_base_url() == "http://sandbox.example:9999/v1"
        assert config.get_api_key() == "secret"
