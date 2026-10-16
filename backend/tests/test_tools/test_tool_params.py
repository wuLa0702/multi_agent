"""工具入参 schema 守卫：**每个对外参数必须有 description**（#7，2026-10-16）。

## 为什么需要这条守卫

LLM 理解工具入参的**唯一渠道**是 `args_schema`（由函数签名推断，见
`tools/contract/adapter.py::as_lc_tool`）。此前实测：

```
11 个工具 · 27 个参数 · description 缺失 27/27
LLM 看到的是: {"query": {"type": "string"}}   ← 零语义
```

LLM 只能猜"query 该写什么格式""max_results 上限多少"。补完之后，本测试
把这条约定**锁死**——新增工具时漏写 description 会当场变红。

依据：`.claude/rules/07-tool-center.md` §2「输入规范」第 4 条
「命名所见即所得：人看得懂、LLM 也看得懂」。
"""

from __future__ import annotations

import pytest

from src.tools.registry import TOOL_REGISTRY

#: 框架注入参数（非 LLM 契约，不参与描述覆盖统计）。
#:
#: `config` 由 langchain 在调用时注入（工具实现取 thread_id 定位会话沙箱）。
#: ⚠️ 已知问题：它当前**仍出现在 `args_schema` 里**——实测 `tool()` 只自动过滤
#: `FILTERED_ARGS = ("run_manager", "callbacks")`，`InjectedToolArg` 对
#: `RunnableConfig | None` 这种 Optional 写法不生效（疑因 `_is_injected_arg_type`
#: 只认 class 类型）。**未修，留档**：对 LLM 影响低（可选、无描述 → 不会被填），
#: 但属于 schema 卫生问题。修好后本白名单可删。
INTERNAL_PARAMS = frozenset({"config"})

#: 对外参数总数下限——防"schema 意外变空导致守卫空过"
MIN_EXTERNAL_PARAMS = 20


def _external_params() -> dict[str, dict]:
    """全部工具的对外参数 → `{"工具名.参数名": schema}` 扁平表。"""
    flat: dict[str, dict] = {}
    for tool_name, spec in TOOL_REGISTRY.items():
        properties = spec.fn.args_schema.model_json_schema().get("properties", {})
        for param, sub_schema in properties.items():
            if param not in INTERNAL_PARAMS:
                flat[f"{tool_name}.{param}"] = sub_schema
    return flat


def test_every_external_param_has_description() -> None:
    """正常路径：所有对外参数都有 description（LLM 能读懂每个入参的含义）。"""
    missing = [
        name for name, schema in _external_params().items() if not schema.get("description")
    ]
    assert not missing, f"以下参数缺 description（LLM 看不到语义）：{missing}"


def test_external_param_count_is_sane() -> None:
    """边界：对外参数总数不得异常缩水（防 schema 意外为空 → 上一条守卫空过）。"""
    total = len(_external_params())
    assert total >= MIN_EXTERNAL_PARAMS, (
        f"对外参数仅 {total} 个（< {MIN_EXTERNAL_PARAMS}）——"
        "args_schema 可能没正常推断，请检查 as_lc_tool 的 functools.wraps"
    )


def test_registry_tools_all_have_description() -> None:
    """正常路径：每个工具的 description 非空（框架要求，缺则 import 期已失败）。"""
    empty = [name for name, spec in TOOL_REGISTRY.items() if not (spec.fn.description or "").strip()]
    assert not empty, f"以下工具缺 description：{empty}"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
