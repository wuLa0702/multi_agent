# 安全规则

## 核心原则

| 目录/资源 | 权限 | 说明 |
|-----------|------|------|
| `backend/src/` | Agent 可读写 | 本项目自身代码由 AI 搭建（学习项目） |
| `.env.dev` / `.env.prod` | **只读 + 不入库** | 密钥文件，已 gitignore；Agent 读取不修改不打印 |
| `.claude/` | **AI 可起草，人类确认授权** | 规则可由 AI 起草修订，**须经 co-creator 确认后才算生效** |
| `docs/` | 读写 | 学习文档与架构蓝图 |

## 规则文件变更流程（2026-10-14 确立）

AI **可以起草** `.claude/rules/` 下的规则文件（新建 / 修订），但必须：

1. **说明改了什么、为什么**——给出依据（代码事实 / 决策记录 / 用户指示），不含糊
2. **等 co-creator 确认**后才算生效；**未确认的草稿不得当作约束引用**
3. 修订既有规则时**保留原意**，只改过时 / 冲突的部分，不顺手重写无关段落

> 变更前身：「`.claude/` 只读，配置规则由人类维护」。2026-10-14 由 co-creator 授权改为上述流程（理由：规则数量增长，AI 起草可提速，但授权环节保留在人类）。

## 密钥安全（硬约束）

1. **密钥只存在于 `.env.dev` / `.env.prod`**，永不硬编码进代码 / compose / 文档
2. 聊天中收到密钥 → 只写入 .env，不回显完整值
3. 提交前检查 `git status`，确认无 .env* 文件进入暂存区
4. `docker-compose.yml` 用 `${VAR}` 引用，不写死

## 路径前缀校验

Agent 工具读写文件必须校验路径前缀：

```python
ALLOWED_PREFIXES = {"backend", "docs"}
actual = os.path.normpath(path).lstrip("./")
if not any(actual.startswith(p + "/") for p in ALLOWED_PREFIXES):
    raise PermissionError(f"Access denied: {path}")
```

## LLM 输出验证

- Agent 生成文件前校验：文件名无 `../`、内容无可执行脚本注入
- LLM 调用必须 timeout + max_retries（统一在 llm/adapter.py 封装）
