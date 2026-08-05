"""OpenSandbox 沙箱适配器（同步 SDK 封装）。

分层（依赖单向 api → agent → sandbox）：sandbox 是独立层，
业务代码不直接依赖 opensandbox SDK，统一走本适配器；
连接配置统一来自 src.core.config.settings（.env.dev / .env.prod）。

本地开发连本地 Docker（docker compose 起 opensandbox，8080），
生产连云端 OpenSandbox；两者只换 SANDBOX_URL / SANDBOX_API_KEY。
"""

from datetime import timedelta

from opensandbox.config.connection_sync import ConnectionConfigSync
from opensandbox.models.execd import RunCommandOpts
from opensandbox.sync.sandbox import SandboxSync

from src.core.config import settings

# 沙箱默认镜像：python 官方镜像，够跑 demo（建包 + pytest）
DEFAULT_IMAGE = "python:3.11"
# 沙箱最长存活时间（到期自动回收）：agent 真实工作流（写代码 → pip install → 跑测试）
# 单次工具调用可能持续数分钟，5 分钟存活期实测不够（容器到期被杀 → 执行流断连）
DEFAULT_TIMEOUT = timedelta(minutes=30)
# SDK 管理面请求超时（create/destroy 等；首次拉镜像可能 50s+，需留余量）
DEFAULT_REQUEST_TIMEOUT = timedelta(seconds=120)


class OpenSandboxAdapter:
    """OpenSandbox 同步适配器：封装沙箱生命周期（创建/写文件/执行/销毁）。

    Args:
        url: OpenSandbox 服务地址（默认读 settings.sandbox_url，
            dev 为 http://localhost:8080，prod 为云端地址）
        api_key: API key（默认读 settings.sandbox_api_key，本地 dev 可空）
    """

    def __init__(self, url: str | None = None, api_key: str | None = None) -> None:
        self._url = url or settings.sandbox_url
        self._api_key = api_key or settings.sandbox_api_key

    def _connection_config(self) -> ConnectionConfigSync:
        """构建 SDK 连接配置：domain 支持带协议前缀（http://localhost:8080）。

        use_server_proxy=True：execd 请求走服务端代理——docker bridge 部署下
        沙箱容器 IP 从宿主机不可达（Windows Docker Desktop 常见），
        走服务端中转是通用解（本地 dev 与云端均适用）。
        """
        return ConnectionConfigSync(
            domain=self._url or "localhost:8080",
            api_key=self._api_key,
            request_timeout=DEFAULT_REQUEST_TIMEOUT,
            use_server_proxy=True,
        )

    def create_sandbox(
        self,
        image: str = DEFAULT_IMAGE,
        *,
        timeout: timedelta = DEFAULT_TIMEOUT,
        resource: dict[str, str] | None = None,
        snapshot_id: str | None = None,
    ) -> SandboxSync:
        """创建沙箱并等待就绪（增强：资源限额 + 快照模板，配置化）。

        原签名 create_sandbox(image, timeout) 完全兼容——resource/snapshot_id
        为新增可选参数。限额来自 settings（sandbox_cpu / sandbox_memory，
        能力计划 §3.5），显式传参优先、settings 兜底注入——⚠️ 不注入时 SDK
        默认 1cpu/2Gi（sync/sandbox.py:554），云端 4G 下 2 沙箱即吃满。
        快照（P2）：settings.sandbox_snapshot_id 配置后优先使用，
        SDK 要求 image 与 snapshot_id 二选一（sync/sandbox.py:543）——用快照时 image 置 None。

        Args:
            image: 沙箱容器镜像（快照模式自动置 None）
            timeout: 沙箱最长存活时间（到期自动回收）
            resource: 容器资源限额 {"cpu": "1", "memory": "1Gi"}；None → settings 兜底
            snapshot_id: 快照模板 ID（依赖预装加速起沙箱）；None → settings 兜底

        Returns:
            就绪的 SandboxSync 实例

        Raises:
            SandboxException: 创建失败或超时未就绪
        """
        if resource is None and settings.sandbox_cpu and settings.sandbox_memory:
            resource = {"cpu": settings.sandbox_cpu, "memory": settings.sandbox_memory}
        if snapshot_id is None:
            snapshot_id = settings.sandbox_snapshot_id or None
        if snapshot_id:
            image = None  # SDK：image 与 snapshot_id 必须二选一
        return SandboxSync.create(
            image,
            timeout=timeout,
            snapshot_id=snapshot_id,
            resource=resource,
            connection_config=self._connection_config(),
        )

    def write_file(self, sandbox: SandboxSync, path: str, content: str) -> None:
        """向沙箱写入文件。

        Args:
            sandbox: 已创建的沙箱实例
            path: 沙箱内目标路径
            content: 文件内容（UTF-8）
        """
        sandbox.files.write_file(path, content)

    def run_script(self, sandbox: SandboxSync, files: dict[str, str], entry: str) -> str:
        """多文件执行（能力计划 §3.2）：逐文件写入 → 运行入口文件。

        Args:
            sandbox: 沙箱实例（池化复用或一次性均可）
            files: {沙箱内路径: 内容}（如 {"main.py": "...", "utils.py": "..."}）
            entry: 入口文件（如 "main.py"）

        Returns:
            run_command 的 stdout 文本

        Raises:
            SandboxException: 写入/执行失败（调用方降级）
        """
        for path, content in files.items():
            self.write_file(sandbox, path, content)
        return self.run_command(sandbox, f"python {entry}")

    def run_command(
        self,
        sandbox: SandboxSync,
        command: str,
        *,
        timeout: timedelta | None = None,
        envs: dict[str, str] | None = None,
    ) -> str:
        """在沙箱内执行 shell 命令（增强：命令级超时/环境变量，能力计划 §3.2）。

        原签名 run_command(sandbox, command) 完全兼容——timeout/envs 为新增
        可选参数（None = 服务端不强制超时，同现状）。

        Args:
            sandbox: 已创建的沙箱实例
            command: 要执行的命令
            timeout: 命令级超时（超时服务端终止，防长命令挂起）
            envs: 命令级环境变量（白名单注入，禁密钥——00-security）

        Returns:
            stdout 文本；退出码非零时附加 stderr 与退出码

        Raises:
            SandboxException: 执行失败
        """
        if timeout is not None or envs is not None:
            execution = sandbox.commands.run(
                command, opts=RunCommandOpts(timeout=timeout, envs=envs)
            )
        else:
            execution = sandbox.commands.run(command)  # 无增强参数：不传 opts（兼容旧调用形态）
        stdout = "\n".join(m.text for m in execution.logs.stdout if m.text)
        if execution.exit_code not in (None, 0):
            stderr = "\n".join(m.text for m in execution.logs.stderr if m.text)
            return f"{stdout}\n[exit={execution.exit_code}]\n{stderr}".strip()
        return stdout

    def upload_file(self, sandbox: SandboxSync, sandbox_path: str, content: str) -> None:
        """上传（能力计划 §3.3）：内容写入沙箱内路径（/workspace/ 约定）。

        Args:
            sandbox: 沙箱实例
            sandbox_path: 沙箱内目标路径（如 "workspace/x.py"）
            content: 文件内容（UTF-8）
        """
        sandbox.files.write_file(sandbox_path, content)

    def download_file(self, sandbox: SandboxSync, sandbox_path: str) -> str:
        """取回（能力计划 §3.3）：读取沙箱内文件内容。

        Args:
            sandbox: 沙箱实例
            sandbox_path: 沙箱内文件路径

        Returns:
            文件文本内容
        """
        return sandbox.files.read_file(sandbox_path)

    def destroy(self, sandbox: SandboxSync) -> None:
        """销毁沙箱：终止远程实例 + 关闭本地 HTTP 资源。

        Args:
            sandbox: 要销毁的沙箱实例
        """
        sandbox.destroy()

    def run_code(
        self,
        code: str,
        filename: str = "script.py",
        image: str = DEFAULT_IMAGE,
    ) -> str:
        """一键执行代码：创建沙箱 → 写入代码文件 → 运行 → 销毁（生命周期自管理）。

        Args:
            code: 要执行的 Python 代码
            filename: 沙箱内文件名（python 直接运行）
            image: 沙箱镜像

        Returns:
            执行 stdout 文本

        Raises:
            SandboxException / SandboxInternalException: 任一步失败（沙箱已清理）
        """
        sandbox = self.create_sandbox(image=image)
        try:
            self.write_file(sandbox, filename, code)
            return self.run_command(sandbox, f"python {filename}")
        finally:
            self.destroy(sandbox)
