"""搜索域工具：博查 Bocha（国内 Tavily 平替，官方无 SDK，REST 直调）。

定义工具（internet_search）供 agent 挂载；注册进 mcp.registry 供
deepagents 与子代理 YAML 加载器查表。失败降级为错误信息，不中断 run。
"""

from __future__ import annotations

import httpx

from src.core.config import settings
from src.core.retry import retry_tool


class BochaClient:
    """博查搜索客户端（轻量封装，对应 TavilyClient 的定位）。

    博查官方无 Python SDK pip 包（官方接入 = REST API 直调 + MCP Server），
    此处用 httpx 直调并统一超时；搜索失败由调用方降级（返回信息，不中断 run）。
    """

    _TIMEOUT_SECONDS = 30

    def __init__(self, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """执行网络搜索，返回结果页列表（name/url/summary/snippet）。

        Args:
            query: 搜索关键词
            max_results: 返回结果数量上限

        Returns:
            结果页字典列表；无结果时返回空列表

        Raises:
            httpx.HTTPError / KeyError: API 调用失败或响应异常，由调用方降级
        """
        resp = httpx.post(
            f"{self._base_url}/web-search",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"query": query, "count": max_results, "summary": True},
            timeout=self._TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return (resp.json().get("data") or {}).get("webPages", {}).get("value", [])


# 全局搜索客户端：key 未配置时为空对象语义（工具降级），配置后自动启用
bocha_client = BochaClient(settings.bocha_api_key, settings.bocha_base_url)


@retry_tool(retries=2, extra_exceptions=(httpx.HTTPStatusError,))
def internet_search(query: str, max_results: int = 5) -> str:
    """针对给定查询执行一次网络搜索（博查 Bocha，国内直连）。

    失败时返回错误信息给 agent（不抛异常）——工具调用失败不应中断整个 run，
    agent 收到错误后可自行决定放弃搜索、基于已有知识回答。

    P1 容错（2026-08-12 批次2.5 R-1）：网络异常（httpx 超时/连接/HTTPStatusError）
    **上抛给 @retry_tool 重试**（读操作幂等，重试安全）——重试耗尽才降级返回错误串；
    仅配置缺失等不可重试场景就地返回。
    """
    if not settings.bocha_api_key:
        return "搜索不可用：BOCHA_API_KEY 未配置（.env.dev），请直接基于已有知识回答。"
    try:
        pages = bocha_client.search(query, max_results)
        if not pages:
            return "搜索无结果，请直接基于已有知识回答。"
        return "\n".join(
            f"- {p.get('name', '')}: {p.get('url', '')}\n"
            f"  {p.get('summary') or p.get('snippet', '')}"
            for p in pages[:max_results]
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            # 授权/配额耗尽（403：key 无效或账号无额度/欠费）——重试无意义，
            # 立即降级并明确指示 agent 直接回答（2026-08-12 实测：配额 403 曾重试 6 次拖慢）
            return (
                "搜索不可用：博查授权失败（HTTP 403，多为账号配额耗尽或 key 无效）。"
                "请勿重试搜索，直接基于已有知识回答。"
            )
        raise  # 429/5xx → 可重试，交给 retry_tool
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
        raise  # 网络瞬时故障 → 交给 retry_tool 重试
    except Exception as e:  # noqa: BLE001 —— 其余异常就地降级，不冒泡中断 run
        return (
            f"搜索失败（{type(e).__name__}）：{e}。"
            "请勿重试搜索，直接基于已有知识回答。"
        )
