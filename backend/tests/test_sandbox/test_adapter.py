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


class TestResourceLimit:
    """单沙箱资源限额（能力计划 §3.5：settings 兜底注入，配置化非写死）。"""

    def test_create_sandbox_injects_resource_from_settings(self, mocker, monkeypatch) -> None:
        """settings.sandbox_cpu/sandbox_memory → SDK create 的 resource 参数。"""
        from src.core.config import settings

        fake = SimpleNamespace(
            files=SimpleNamespace(write_file=mocker.Mock()),
            commands=mocker.Mock(),
            destroy=mocker.Mock(),
        )
        create_mock = mocker.patch("src.sandbox.adapter.SandboxSync.create", return_value=fake)
        monkeypatch.setattr(settings, "sandbox_cpu", "0.5")
        monkeypatch.setattr(settings, "sandbox_memory", "512Mi")

        adapter = OpenSandboxAdapter(url="http://test:8080")
        adapter.create_sandbox()

        _, kwargs = create_mock.call_args
        assert kwargs["resource"] == {"cpu": "0.5", "memory": "512Mi"}, "限额应来自 settings 配置"

    def test_create_sandbox_explicit_resource_wins(self, mocker, monkeypatch) -> None:
        """显式传 resource 优先于 settings 兜底。"""
        from src.core.config import settings

        fake = SimpleNamespace(files=mocker.Mock(), commands=mocker.Mock(), destroy=mocker.Mock())
        create_mock = mocker.patch("src.sandbox.adapter.SandboxSync.create", return_value=fake)
        monkeypatch.setattr(settings, "sandbox_cpu", "1")
        monkeypatch.setattr(settings, "sandbox_memory", "1Gi")

        adapter = OpenSandboxAdapter(url="http://test:8080")
        adapter.create_sandbox(resource={"cpu": "2", "memory": "2Gi"})

        _, kwargs = create_mock.call_args
        assert kwargs["resource"] == {"cpu": "2", "memory": "2Gi"}

    def test_run_script_writes_files_then_runs_entry(self, mocker) -> None:
        """run_script：多文件逐写 → 运行入口文件。"""
        fake = SimpleNamespace(
            files=SimpleNamespace(write_file=mocker.Mock()),
            commands=SimpleNamespace(
                run=mocker.Mock(return_value=_execution(["done"]))
            ),
            destroy=mocker.Mock(),
        )
        adapter = OpenSandboxAdapter(url="http://test:8080")

        out = adapter.run_script(fake, {"main.py": "code", "utils.py": "util"}, "main.py")

        assert out == "done"
        assert fake.files.write_file.call_args_list[0][0] == ("main.py", "code")
        assert fake.files.write_file.call_args_list[1][0] == ("utils.py", "util")
        fake.commands.run.assert_called_once_with("python main.py")


class TestCommandEnhanceAndSync:
    """命令增强（timeout/envs 透传）+ 文件同步 + 快照（能力计划 §3.2/§3.3/P2）。"""

    def test_run_command_passes_opts(self, mocker) -> None:
        """run_command 增强：timeout/envs 经 RunCommandOpts 透传。"""
        from datetime import timedelta

        from opensandbox.models.execd import RunCommandOpts

        fake = SimpleNamespace(
            commands=SimpleNamespace(run=mocker.Mock(return_value=_execution(["ok"])))
        )
        adapter = OpenSandboxAdapter(url="http://test:8080")

        adapter.run_command(fake, "pip install x", timeout=timedelta(seconds=60), envs={"A": "1"})

        args, kwargs = fake.commands.run.call_args
        assert args[0] == "pip install x"
        assert isinstance(kwargs["opts"], RunCommandOpts)
        assert kwargs["opts"].timeout == timedelta(seconds=60)
        assert kwargs["opts"].envs == {"A": "1"}

    def test_run_command_no_opts_when_plain(self, mocker) -> None:
        """run_command 无增强参数：不传 opts（兼容旧调用，服务端不强制超时）。"""
        fake = SimpleNamespace(
            commands=SimpleNamespace(run=mocker.Mock(return_value=_execution(["ok"])))
        )
        adapter = OpenSandboxAdapter(url="http://test:8080")

        adapter.run_command(fake, "echo hi")

        _, kwargs = fake.commands.run.call_args
        assert kwargs.get("opts") is None

    def test_upload_download_files(self, mocker) -> None:
        """文件同步：upload 写沙箱 / download 读沙箱。"""
        fake = SimpleNamespace(
            files=SimpleNamespace(
                write_file=mocker.Mock(),
                read_file=mocker.Mock(return_value="content"),
            ),
            commands=mocker.Mock(),
            destroy=mocker.Mock(),
        )
        adapter = OpenSandboxAdapter(url="http://test:8080")

        adapter.upload_file(fake, "workspace/x.py", "code")
        out = adapter.download_file(fake, "workspace/x.py")

        fake.files.write_file.assert_called_once_with("workspace/x.py", "code")
        fake.files.read_file.assert_called_once_with("workspace/x.py")
        assert out == "content"

    def test_create_sandbox_snapshot_id(self, mocker, monkeypatch) -> None:
        """P2 快照：配置 sandbox_snapshot_id → image 置 None + snapshot_id 透传（SDK 二选一）。"""
        from src.core.config import settings

        fake = SimpleNamespace(files=mocker.Mock(), commands=mocker.Mock(), destroy=mocker.Mock())
        create_mock = mocker.patch("src.sandbox.adapter.SandboxSync.create", return_value=fake)
        monkeypatch.setattr(settings, "sandbox_snapshot_id", "snap-1")

        adapter = OpenSandboxAdapter(url="http://test:8080")
        adapter.create_sandbox()

        args, kwargs = create_mock.call_args
        assert args[0] is None, "快照模式 image 必须为 None（SDK image/snapshot_id 二选一）"
        assert kwargs["snapshot_id"] == "snap-1"
