# 学习：MCP 工具层薄壳与实现层解耦（Facade + Adapter）

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-03
> 📝 **版本变更记录**（永久保存，只追加不删除）：

> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1 | 2026-08-03 | 初版：记录工具层/实现层分层与 Facade+Adapter 双模式 |

> **目录**：
> - § 现象
> - § 根因与模式
> - § 沉淀规则

---

## 现象

`mcp/tools/sandbox_tool.py` 只有 35 行，是个"薄壳"：

```python
def run_code_in_sandbox(code: str, filename: str = "script.py") -> str:
    if not settings.sandbox_url:
        return "沙箱不可用：SANDBOX_URL 未配置（.env.dev）..."
    try:
        return sandbox_adapter.run_code(code, filename)
    except Exception as e:
        return f"沙箱执行失败（{type(e).__name__}）：{e}..."
```

真正的实现（创建容器 → 写文件 → 执行 → 销毁、连接配置、镜像超时）全在
`sandbox/adapter.py`（140 行）。当时疑问：功能这么多，为什么拆到两个文件？

## 根因与模式

### 依赖链

```
agent/main_agent.py
  → mcp/tools/sandbox_tool.py  （工具定义，薄壳）
    → sandbox/adapter.py       （OpenSandbox SDK 封装，实现层）
      → opensandbox SDK        （第三方库）
```

依赖单向，符合项目架构约束。

### 两个经典模式叠加

**Facade（外观模式）**：`sandbox_tool.py` 是 Agent 面对的门面——Agent 只看到
`run_code_in_sandbox(code, filename)` 一个函数，不需要知道底下有 Docker 容器、
SDK 连接配置、镜像拉取超时。成了返回结果，败了返回中文错误。

**Adapter（适配器模式）**：`adapter.py` 把 OpenSandbox SDK 适配成项目内部接口；
`sandbox_tool.py` 再把适配器适配成 Agent 工具（LLM 可消费的签名 + 错误降级）。

### 分层的本质：What vs How

| 层 | 关心的问题 |
|---|---|
| 工具层 `mcp/tools/` | **What**——给 Agent 什么能力？调用契约？失败时给什么提示？ |
| 实现层 `sandbox/adapter.py` | **How**——容器怎么起？文件怎么传？命令怎么执行？ |

工具层是 Agent 对底层能力的**消费边界**。两层通过 `adapter.run_code()` 窄接口
解耦：以后换沙箱实现（如 OpenSandbox → 别的），只改 adapter，工具层一行不动。

### 同构验证：search.py 也是同一模式

`mcp/tools/search.py` 结构完全一样：`BochaClient`（实现，REST 直调+超时）+
`internet_search()`（薄壳，设置检查+异常降级）。每个工具域一个薄壳文件，
实现下沉到自己的服务层——这是项目的标准工具组织方式。

## 沉淀规则

工具层的三件事，实现层**不该知道**：

1. **设置前置检查**（`if not settings.xxx_url: return "不可用..."`）——消费者感知
2. **异常 → 字符串降级**（`except Exception: return "失败...请勿重试"`）——工具
   失败不冒泡中断 agent run；但实现层应该正常抛异常
3. **LLM 友好中文提示**——实现层不知道自己在服务 Agent

如果把这三点搬进 adapter，sandbox 层就需要知道"我在给 agent 服务"——这才是
真正的耦合。工具层只依赖实现层的**窄接口**，实现层不依赖工具层的任何东西。
