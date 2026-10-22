"""current_time 工具：当前时间 —— **模板工具（最简骨架）**。

## 为什么需要它

LLM 不知道"现在几点"：训练截止之后的时间、跨时区的"今天"，它只能瞎猜。
给一个确定性时钟，比让它在日期题上编造强。

## 作为模板怎么读

本文件是**最小可抄的骨架**——一个参数、一条失败分支、一个成功分支。看完这个
再看 `impl/calc.py`（纯函数）与 `impl/json_extract.py`（完整处理链），
三种粒度就齐了：

| 文件 | 形态 | 适合抄什么 |
|------|------|-----------|
| `clock.py` | 最简 | 只要一个参数、一个外部调用 |
| `calc.py` | 纯函数 | 无 IO、纯计算、需严格校验 |
| `json_extract.py` | 完整链 | 解析 + 归一 + 多级错误 |

**时区依赖**：Windows 无 IANA 时区库，需 `tzdata`（已在 requirements）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from src.core.constants import TIMESTAMP_FORMAT
from src.core.errors import ToolErrorCode
from src.tools.contract.result import ToolResult

_TOOL_NAME = "current_time"


def current_time(
    timezone: Annotated[
        str,
        Field(
            description=(
                "IANA 时区名（如 Asia/Shanghai、UTC、America/New_York）；"
                "**留空则用本机本地时区**"
            )
        ),
    ] = "",
) -> ToolResult:
    """获取当前时间（可指定时区）。

    Args:
        timezone: IANA 时区名；空串 = 本机本地时区

    Returns:
        `ok` 信封（`data` 带 iso / date / timezone）；
        时区名非法 → `error: invalid_arg`
    """
    tz_name = timezone.strip()
    if tz_name:
        try:
            now = datetime.now(ZoneInfo(tz_name))
        except (ZoneInfoNotFoundError, ValueError):
            return ToolResult(
                status="error",
                message=(
                    f"时区不存在：{tz_name}（请用 IANA 名，如 Asia/Shanghai、UTC；"
                    "留空则用本机时区）"
                ),
                error_code=ToolErrorCode.INVALID_ARG,
                tool=_TOOL_NAME,
            )
    else:
        now = datetime.now().astimezone()

    stamp = now.strftime(TIMESTAMP_FORMAT)
    tz_display = str(now.tzinfo) if now.tzinfo else "local"
    return ToolResult(
        status="ok",
        message=f"当前时间：{stamp}（{tz_display}）",
        data={
            "iso": stamp,
            "date": now.date().isoformat(),
            "timezone": tz_display,
            "weekday": now.strftime("%A"),
        },
        tool=_TOOL_NAME,
    )
