"""搜索域工具：Searchpin（默认，免费）→ 博查 Bocha（降级，付费）。

2026-08-12 策略调整：co-creator 拍板——Searchpin 作为默认搜索引擎（免费无限、
国内原生、语义重排），博查作为降级兜底（付费 API，Searchpin 失败时用）。

Searchpin 为懒加载：未安装 `pip install searchpin` 或首次模型下载未完成时
自动降级博查——不影响既有搜索。

**输出（阶段 2.2.1）**：返回 `ToolResult` 信封（`ok` / `error` 两态，无
`degraded`——搜索要么有结果要么没有，不存在"拿到一半"）。
`data` 带 `engine` 与 `fallback_used`：**降级对上层透明**（编排层据此才知道
"这个工具最近一直在走付费后端"）。引擎优先级本身属部署配置，**不进 status**
（否则同一段代码在测试期/生产期会打出相反的标签）。
"""

from __future__ import annotations

import logging
import os
from typing import Annotated

import httpx
from pydantic import Field

from src.core.config import settings
from src.core.errors import ToolErrorCode
from src.tools.contract.error_map import classify_exception
from src.tools.contract.result import ToolResult

logger = logging.getLogger(__name__)

_TOOL_NAME = "internet_search"

# Searchpin 语义重排模型默认走 hf-mirror（国内 HF 直连超时；已实测镜像可下，~26s 首次）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


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


def _normalize_results(pages: list[dict], max_results: int = 5) -> list[dict]:
    """结果列表 → 结构化载荷（`data.results`，字段名对齐设计 §5 迁移清单）。

    Args:
        pages: 引擎原始结果页（name / url / summary）
        max_results: 截取上限

    Returns:
        [{title, url, snippet}, ...]
    """
    return [
        {
            "title": p.get("name", ""),
            "url": p.get("url", ""),
            "snippet": p.get("summary") or p.get("snippet", ""),
        }
        for p in pages[:max_results]
    ]


def _ok_result(
    query: str,
    pages: list[dict],
    max_results: int,
    *,
    engine: str,
    fallback_used: bool,
) -> ToolResult:
    """命中结果 → `ok` 信封。

    Args:
        query: 原始查询词（回填 `data`，便于审计对账）
        pages: 结果页（非空）
        max_results: 截取上限
        engine: 实际出结果的引擎名（searchpin / bocha）
        fallback_used: 是否走了降级引擎——**降级透明**的唯一出口

    Returns:
        `ok` 信封；`message` 为可读文本，`data` 含 results + 引擎溯源
    """
    return ToolResult(
        status="ok",
        message=_format_results(pages, max_results),
        data={
            "query": query,
            "results": _normalize_results(pages, max_results),
            "engine": engine,
            "fallback_used": fallback_used,
        },
        tool=_TOOL_NAME,
    )


def _bocha_search(query: str, max_results: int = 5) -> ToolResult:
    """博查搜索（降级引擎，付费）。失败降级为错误信封，不中断 run。"""
    if not settings.bocha_api_key:
        return ToolResult(
            status="error",
            message="搜索不可用：BOCHA_API_KEY 未配置（.env.dev），请直接基于已有知识回答。",
            error_code=ToolErrorCode.NOT_CONFIGURED,
            tool=_TOOL_NAME,
        )
    try:
        pages = bocha_client.search(query, max_results)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            # 授权/配额耗尽（403：key 无效或账号无额度/欠费）——重试无意义，
            # 立即降级并明确指示 agent 直接回答
            return ToolResult(
                status="error",
                message=(
                    "搜索不可用：博查授权失败（HTTP 403，多为账号配额耗尽或 key 无效）。"
                    "请勿重试搜索，直接基于已有知识回答。"
                ),
                error_code=ToolErrorCode.UNPAID,
                tool=_TOOL_NAME,
            )
        raise  # 429/5xx → 可重试，交给注册表的重试包装
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
        raise  # 网络瞬时故障 → 交给注册表的重试包装
    except Exception as e:  # noqa: BLE001 —— 其余异常就地降级，不冒泡中断 run
        return ToolResult(
            status="error",
            message=(
                f"搜索失败（{type(e).__name__}）：{e}。"
                "请勿重试搜索，直接基于已有知识回答。"
            ),
            error_code=classify_exception(e),
            tool=_TOOL_NAME,
        )
    if not pages:
        # 搜了但没命中 = 正常结果，不是失败（co-creator 2026-10-15 拍板）
        return ToolResult(
            status="ok",
            message="搜索无结果，请直接基于已有知识回答。",
            data={
                "query": query,
                "results": [],
                "engine": "bocha",
                "fallback_used": True,
            },
            tool=_TOOL_NAME,
        )
    return _ok_result(
        query, pages, max_results, engine="bocha", fallback_used=True
    )


def internet_search(
    query: Annotated[
        str,
        Field(description="搜索关键词（自然语言即可，越具体越准；例：LangGraph 1.x 中断恢复机制）"),
    ],
    max_results: Annotated[
        int,
        Field(description="返回结果条数上限；不传默认 5，建议 3–10（过多会挤占上下文）"),
    ] = 5,
) -> ToolResult:
    """针对给定查询执行一次网络搜索（Searchpin 默认 → 博查降级）。

    Searchpin（免费默认）失败/无结果 → 自动降级博查（付费）；
    两者都不可用 → 返回明确降级信息，agent 基于已有知识回答。

    失败时返回错误信息给 agent（不抛异常）——工具调用失败不应中断整个 run。
    网络瞬时故障**上抛**，由注册表派生的重试包装接管（`registry.RetryPolicy`，
    阶段 4 批次 3 起重试不再写在本文件）；配额/授权类就地降级。
    """
    # 1. Searchpin（默认，免费）——失败/无结果自动降级博查
    pages = searchpin_client.search(query, max_results)
    if pages:
        return _ok_result(
            query, pages, max_results, engine="searchpin", fallback_used=False
        )
    # 2. 博查（降级，付费）
    return _bocha_search(query, max_results)
