"""搜索域工具：Searchpin（默认，免费）→ 博查 Bocha（降级，付费）。

2026-08-12 策略调整：co-creator 拍板——Searchpin 作为默认搜索引擎（免费无限、
国内原生、语义重排），博查作为降级兜底（付费 API，Searchpin 失败时用）。

Searchpin 为懒加载：未安装 `pip install searchpin` 或首次模型下载未完成时
自动降级博查——不影响既有搜索。
"""

from __future__ import annotations

import logging

import httpx

from src.core.config import settings
from src.core.retry import retry_tool

logger = logging.getLogger(__name__)


class SearchpinClient:
    """Searchpin 搜索引擎（免费默认，懒加载——未安装/模型未下自动降级博查）。

    底层用 Searchpin 的 SearchEngine（fastembed 语义重排 + 多引擎聚合）。
    """

    _engine = None  # 懒加载单例（模型 ~118MB 首次下载）

    @classmethod
    def _get_engine(cls):
        if cls._engine is None:
            from searchpin import SearchEngine  # 懒加载：未安装则 ImportError → 降级

            cls._engine = SearchEngine()
        return cls._engine

    def search(self, query: str, max_results: int = 5) -> list[dict] | None:
        """执行搜索，返回归一化结果列表；不可用/失败返回 None（调用方降级博查）。

        Returns:
            [{name, url, summary}, ...]；Searchpin 不可用或无结果 → None
        """
        try:
            engine = self._get_engine()
            raw = engine.search(query, max_results)
            if not raw:
                return None
            pages = []
            for r in raw:
                if isinstance(r, dict):
                    pages.append(
                        {
                            "name": r.get("title") or r.get("name") or "",
                            "url": r.get("url") or "",
                            "summary": r.get("snippet")
                            or r.get("content")
                            or r.get("summary", ""),
                        }
                    )
            return pages or None
        except Exception as exc:  # noqa: BLE001 —— 任何失败降级博查
            logger.warning("Searchpin 搜索失败，降级博查：%s", exc)
            return None


class BochaClient:
    """博查搜索客户端（降级引擎，付费，官方无 SDK，REST 直调）。"""

    _TIMEOUT_SECONDS = 30

    def __init__(self, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """执行网络搜索，返回结果页列表（name/url/summary/snippet）。

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


searchpin_client = SearchpinClient()
bocha_client = BochaClient(settings.bocha_api_key, settings.bocha_base_url)


def _format_results(pages: list[dict], max_results: int = 5) -> str:
    """结果列表 → agent 可读文本（name: url + summary）。"""
    return "\n".join(
        f"- {p.get('name', '')}: {p.get('url', '')}\n"
        f"  {p.get('summary') or p.get('snippet', '')}"
        for p in pages[:max_results]
    )


def _bocha_search(query: str, max_results: int = 5) -> str:
    """博查搜索（降级引擎，付费）。失败降级为错误信息，不中断 run。"""
    if not settings.bocha_api_key:
        return "搜索不可用：BOCHA_API_KEY 未配置（.env.dev），请直接基于已有知识回答。"
    try:
        pages = bocha_client.search(query, max_results)
        if not pages:
            return "搜索无结果，请直接基于已有知识回答。"
        return _format_results(pages, max_results)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            # 授权/配额耗尽（403：key 无效或账号无额度/欠费）——重试无意义，
            # 立即降级并明确指示 agent 直接回答
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


@retry_tool(retries=2, extra_exceptions=(httpx.HTTPStatusError,))
def internet_search(query: str, max_results: int = 5) -> str:
    """针对给定查询执行一次网络搜索（Searchpin 默认 → 博查降级）。

    Searchpin（免费默认）失败/无结果 → 自动降级博查（付费）；
    两者都不可用 → 返回明确降级信息，agent 基于已有知识回答。

    失败时返回错误信息给 agent（不抛异常）——工具调用失败不应中断整个 run。
    网络瞬时故障上抛给 @retry_tool 重试（读操作幂等）；配额/授权类就地降级。
    """
    # 1. Searchpin（默认，免费）——失败/无结果自动降级博查
    pages = searchpin_client.search(query, max_results)
    if pages:
        return _format_results(pages, max_results)
    # 2. 博查（降级，付费）
    return _bocha_search(query, max_results)
