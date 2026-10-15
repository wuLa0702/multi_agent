"""MCP 客户端管理：连接外部 MCP server，收集工具注入 agent。

模式（与 core/model_registry.py 同款）：
- lifespan 启动时 connect_all（读 mcp_servers 表 → MultiServerMCPClient → get_tools）
- 进程内缓存；配置变更后 reload（管理 API 接入时用）
- MultiServerMCPClient 每次工具调用自动建/销 session，无需手动管理连接

tool_name_prefix=True：多 server 同名工具加 server 名前缀，避免冲突
（如 "bocha_search" vs "tavily_search"）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from psycopg import AsyncConnection
from pydantic import PrivateAttr

from src.core.errors import is_retryable_tool_error
from src.core.retry import retry_tool
from src.tools.contract.adapter import artifact_of
from src.tools.contract.error_map import classify_exception
from src.tools.contract.result import ToolResult, render
from src.tools.registry import RetryPolicy

logger = logging.getLogger(__name__)


class _SafeTool(BaseTool):
    """MCP 工具安全包装：协议层异常（429/连接失败）降级为错误字符串返回。

    langchain_mcp_adapters 的 handle_tool_errors 只处理「工具结果 error」，
    协议层异常（Smithery 限流 429、连接失败）会在调用处抛异常中断 agent run——
    本包装捕获一切异常转字符串（与项目「工具失败降级不中断」设计一致）。

    **重试必须包在本类【内层】**（`_retry`）：本类是"兜底网"，把异常吞成字符串；
    若把重试包在外层，外层永远看不到异常 → 重试永不触发（与 P4 那次"外层空转"
    同一个坑）。故顺序固定为 `原始工具 → 重试 → 本包装`。

    Attributes:
        _tool: 被包装的原始 MCP 工具（PrivateAttr——BaseTool 是 Pydantic 模型，
            下划线字段必须用 PrivateAttr 声明，否则不实例化）
        _retry: 治理声明里的重试参数（None = 不重试；由幂等门控决定，见 mcp_meta）
    """

    _tool: BaseTool = PrivateAttr()
    _retry: RetryPolicy | None = PrivateAttr(default=None)

    def __init__(
        self, tool: BaseTool, *, retry: RetryPolicy | None = None, **kwargs
    ) -> None:
        super().__init__(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            # 与本地工具**同一输出契约**（阶段 2 双通道）：不声明的话本类返回的
            # 二元组会被 `_stringify` 成一整段 repr 塞给 LLM（适配器早已声明
            # content_and_artifact，是本层包装把 artifact 弄丢的——批次 3 修）
            response_format="content_and_artifact",
            # ⚠️ 必须透传 metadata：适配器把 **MCP 工具注解**（readOnlyHint /
            # destructiveHint / idempotentHint）放在这里，自动登记时据此推导
            # 治理默认值——不透传的话注解信息在这一层就丢了（tools.py:511 起）
            metadata=tool.metadata,
            **kwargs,
        )
        self._tool = tool
        self._retry = retry

    @property
    def raw_tool(self) -> BaseTool:
        """内层原始 MCP 工具。

        治理侧需要**按重试声明重包**时取它——直接包在本类外层会让重试空转
        （本类把异常吞成字符串，外层看不到异常）。见 `mcp_meta.governed_tools`。
        """
        return self._tool

    def _run(self, *args, **kwargs):  # pragma: no cover - MCP 工具走 async
        raise NotImplementedError("MCP 工具为 async，使用 _arun")

    async def _invoke_raw(self, payload: dict, config) -> object:
        """调用远端工具（走 ainvoke 顶层入口：内部处理 RunnableConfig/args_schema，
        直接调 _arun 会丢 config 参数——实测 StructuredTool 必传 config）。"""
        return await self._tool.ainvoke(payload, config=config)

    async def _arun(self, *args, **kwargs) -> tuple[str, dict[str, Any]]:
        """执行 MCP 工具 → `(content, artifact)` 双通道（与本地工具同一输出契约）。

        成功 → `ok` 信封；失败 → `error` 信封（归一错误码 + `retryable`）。
        **不产生 `degraded`**：MCP 没有"拿到一半/被截断"的语义。
        """
        config = kwargs.pop("config", None)
        payload = args[0] if args and isinstance(args[0], dict) else kwargs

        async def _call():
            """**必须是具名 async 函数**：`retry_tool` 用
            `asyncio.iscoroutinefunction` 分流 sync/async——传 `lambda: coro()`
            会被判成同步函数，走 sync 分支后根本不 await（重试静默失效）。
            本类首版就这么写错，被 `test_retry_actually_retries` 当场抓出。"""
            return await self._invoke_raw(payload, config)

        try:
            if self._retry is None:
                raw = await _call()
            else:
                # 按治理声明重试（瞬时故障）；耗尽后由 retry_tool 返回降级字符串，
                # 仍走下方统一格式 —— 故 on_exhausted 不另配（保持文案一处）
                wrapped = retry_tool(
                    retries=self._retry.retries,
                    delays=self._retry.delays,
                    extra_exceptions=self._retry.extra_exceptions,
                )(_call)
                raw = await wrapped()
        except Exception as exc:  # noqa: BLE001 —— 工具失败降级为错误信封，不中断 run
            logger.warning("MCP 工具 %s 执行失败（降级）：%s", self.name, exc)
            return _error_envelope(self.name, exc)

        result = ToolResult(
            status="ok",
            message=mcp_output_to_text(raw),
            data={"mcp": _mcp_artifact_of(raw)},
            tool=self.name,
        )
        return render(result), artifact_of(result)


def mcp_output_to_text(raw: Any) -> str:
    """MCP 工具原始返回 → 给 LLM 的文本（content 通道）。

    适配器返回 `(content, artifact)` 二元组（`response_format="content_and_artifact"`，
    见 `langchain_mcp_adapters/tools.py::_convert_call_tool_result`），其中 `content`
    可能是**字符串**（单段文本）或 **langchain content block 列表**（文本/图片/文件）。

    Args:
        raw: `_invoke_raw` 的返回值

    Returns:
        纯文本；非文本块降级为占位说明（如 `[图片]`）——不静默丢内容
    """
    content = raw[0] if isinstance(raw, tuple) and len(raw) == 2 else raw
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            kind = block.get("type")
            if kind == "text":
                parts.append(str(block.get("text", "")))
            else:
                # 图片/文件等非文本块：给它一个可读占位，而不是丢掉
                parts.append(f"[{kind or '未知内容'}]")
    return "\n".join(p for p in parts if p)


def _mcp_artifact_of(raw: Any) -> Any:
    """MCP 工具返回的 artifact 通道 → 可进信封的 data（结构化内容）。

    适配器把 MCP 的 `structuredContent` 包成 `MCPToolArtifact`：
    `{"structured_content": {...}}`；没有结构化内容时为 None。

    Returns:
        结构化内容 dict；无则 None
    """
    if not (isinstance(raw, tuple) and len(raw) == 2):
        return None
    artifact = raw[1]
    if isinstance(artifact, dict):
        return artifact.get("structured_content")
    return None


def _error_envelope(tool_name: str, exc: BaseException) -> tuple[str, dict[str, Any]]:
    """失败 → `(content, artifact)` 错误信封（与本地工具口径一致）。

    文案沿用改造前逐字（`工具执行失败（{类型}）：{摘要}，请勿重试，改用其他方式。`），
    只是从"裸字符串"升级为**带 artifact 的错误信封**——这才是 SSE/审计能读懂的部分。
    """
    error_code = classify_exception(exc)
    result = ToolResult(
        status="error",
        message=(
            f"工具执行失败（{type(exc).__name__}）：{str(exc)[:300]}，"
            "请勿重试，改用其他方式。"
        ),
        error_code=error_code,
        retryable=is_retryable_tool_error(error_code),
        tool=tool_name,
    )
    return render(result), artifact_of(result)


def wrap_safe(tool: BaseTool, *, retry: RetryPolicy | None = None) -> BaseTool:
    """包装单个 MCP 工具为安全版本（保留 name/description/args_schema）。

    Args:
        tool: 原始 MCP 工具
        retry: 重试参数（幂等工具才给；None = 不重试）

    Returns:
        `_SafeTool`（异常兜底为字符串）
    """
    return _SafeTool(tool=tool, retry=retry)

_manager: "McpClientManager | None" = None
_manager_lock = threading.Lock()


class McpClientManager:
    """外部 MCP server 连接管理（DB 配置 → 工具列表缓存）。

    Attributes:
        _client: MultiServerMCPClient 实例（懒创建，connect_all 时初始化）
        _tools: 收集到的 langchain BaseTool 列表（agent 构建时注入）
    """

    def __init__(self) -> None:
        self._client: MultiServerMCPClient | None = None
        self._tools: list[BaseTool] = []

    async def connect_all(self, conn: AsyncConnection) -> None:
        """读取 mcp_servers 表 active server → 构建 client → 收集工具。

        Args:
            conn: 已初始化 schema 的 PG 连接（连接层借出）

        Raises:
            Exception: 连接/取工具失败（由 lifespan 捕获降级为仅内部工具）
        """
        connections = await self._load_connections(conn)
        if not connections:
            logger.info("mcp_servers 表无启用 server，agent 仅使用内部工具")
            self._client = None
            self._tools = []
            return

        # handle_tool_errors=False（2026-10-15 批次 3，与项目错误模型对齐）：
        # 默认 True 时适配器把 MCP 的 `isError=True` **吞成正常返回的文本**，
        # 下游无从判断成败（三态退化成"永远 ok"，比 unknown 更糟——假阳性）。
        # 关闭后 `_MCPToolExecutionError` 以异常形式逃逸到 `_SafeTool` 的兜底层，
        # 由它转成**错误信封**（status=error + 归一错误码）——错误文本照样进
        # content 给模型看，模型的自我纠正能力不受影响。
        client = MultiServerMCPClient(
            connections, tool_name_prefix=True, handle_tool_errors=False
        )
        # 逐个 server 取工具（gather return_exceptions）：单个 server 连不上
        # （缺 key / 服务下线）只跳过它，不影响其他 server 与整体启动
        tasks = [
            client.get_tools(server_name=name)
            for name in connections
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        tools: list[BaseTool] = []
        failed: list[str] = []
        for name, result in zip(connections, results, strict=True):
            if isinstance(result, BaseException):
                failed.append(name)
                logger.warning("MCP server %s 连接/取工具失败（跳过）：%s", name, result)
            else:
                # 安全包装：协议层异常（Smithery 限流 429 等）降级为错误字符串，
                # 不中断 agent run（实测：搜索任务调 Exa → 429 → TaskGroup 崩溃）
                # ⚠️ 此处**不**挂重试——治理声明（含 is_idempotent）在本步之后才
                #    加载；重试由 `mcp_meta.governed_tools()` 在装配时补（见其 docstring）
                tools.extend(wrap_safe(t) for t in result)
        if failed:
            logger.warning("MCP 客户端共 %d 个 server，%d 个失败跳过", len(connections), len(failed))

        self._client = client
        self._tools = tools
        logger.info("MCP 客户端已连接 %d 个 server，收集 %d 个工具", len(connections) - len(failed), len(tools))

    async def reload(self, conn: AsyncConnection) -> None:
        """配置变更后重建连接与工具缓存（管理 API 接入后调用）。"""
        await self.connect_all(conn)

    def reset(self) -> None:
        """清空缓存（测试隔离）。"""
        self._client = None
        self._tools = []

    def get_tools(self) -> list[BaseTool]:
        """当前 MCP 工具列表（agent 构建时注入；未连接时为空列表）。"""
        return self._tools

    def get_client(self) -> MultiServerMCPClient | None:
        """底层 client（测试 / 高级用例）。"""
        return self._client

    @staticmethod
    async def _load_connections(
        conn: AsyncConnection,
    ) -> dict[str, dict]:
        """mcp_servers 表 → MultiServerMCPClient connections 格式。

        Args:
            conn: PG 连接

        Returns:
            {server_name: {transport, url | command/args, ...}}；无启用 server 时为空 dict
        """
        cur = await conn.execute(
            """SELECT name, transport, url, command, args, headers
               FROM mcp_servers WHERE is_active = 1 ORDER BY sort_order"""
        )
        rows = await cur.fetchall()

        connections: dict[str, dict] = {}
        for row in rows:
            name = row["name"]
            transport = row["transport"]
            if transport in ("sse", "streamable_http"):
                connections[name] = {
                    "transport": transport,
                    "url": row["url"],
                    "headers": json.loads(row["headers"] or "{}"),
                }
            elif transport == "stdio":
                connections[name] = {
                    "transport": "stdio",
                    "command": row["command"],
                    "args": json.loads(row["args"] or "[]"),
                    # Windows 子进程默认 GBK 输出（04-logging.md：项目强制 UTF-8），
                    # 不注入会把 GBK 字节写进父进程 stderr 流（测试捕获/日志乱码）
                    "env": {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                }
            else:
                logger.warning("mcp_servers %s: 未知 transport=%s，跳过", name, transport)
        return connections


def get_mcp_client_manager() -> McpClientManager:
    """进程内单例（线程安全懒创建）。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = McpClientManager()
    return _manager
