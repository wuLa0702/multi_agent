# 工具与技能模板（照抄入口）

> 📌 **2026-10-16 新增**：项目工具量偏少、部分写法不统一。这里按**三种实现粒度**
> 各给一个**能跑的真工具**，抄的时候挑最接近的那个改。

## 一、三个工具模板（都在 `backend/src/tools/impl/`）

| 模板 | 形态 | 什么时候抄它 | 文件 |
|------|------|-------------|------|
| `current_time` | **最简骨架** | 一个参数、一次外部调用、一条失败分支 | `impl/clock.py` |
| `calculate` | **纯函数 + 严格校验** | 无 IO、纯计算、输入必须白名单校验（防注入） | `impl/calc.py` |
| `json_extract` | **完整处理链** | 要解析、要归一、要多级错误提示 | `impl/json_extract.py` |

三者都已注册进 `tools/registry.py` 并**挂在主 Agent 上**——是能直接用的工具，不只是样例。

## 二、技能模板（本目录 `skill_template/`）

```
skill_template/
├── SKILL.md          # 给 LLM 看的说明书（frontmatter: name + description）
└── scripts/run.py    # 沙箱里跑的脚本（只用标准库）
```

**安装到项目**（`data/*` 被 gitignore，故模板放这儿、用时复制）：

```bash
cp -r backend/examples/skill_template data/skills/skill_md/text_stats
```

装完后：
- 前端「技能」页能看到（SkillsMiddleware 扫描 `data/skills/skill_md/`）
- Agent 可调 `run_skill_script(skill_name="text_stats", script_name="run.py", script_args="...")`

> ⚠️ **技能脚本 vs 工具**：脚本跑在**沙箱**里、用 stdout/退出码通信、**只能依赖标准库**；
> 工具跑在后端进程内、返回 `ToolResult`。别把两者混着写。

## 三、新增一个工具的 Checklist

照 `impl/clock.py` 抄完，确认这 6 条：

1. [ ] **参数注解**：`Annotated[..., Field(description=...)]` —— LLM 靠它理解入参
   （`tests/test_tools/test_tool_params.py` 会检查，漏写 description 当场红）
2. [ ] **不抛异常**：业务失败返回 `ToolResult(status="error", error_code=...)`
3. [ ] **三态选对**：`ok` / `degraded`（部分结果）/ `error`
4. [ ] **结构化出参**：`data` 放程序可用的字段，`message` 放给 LLM 的中文文本
5. [ ] **登记**：`tools/registry.py::_IMPL_SPECS` 加一行（**唯一真相源**）
   - 有副作用的：加 `requires_approval` + `allowed_decisions`
   - 幂等读操作才配 `retry`
6. [ ] **测试**：`backend/tests/test_tools/test_<模块>.py`（正常 / 边界 / 错误）

## 四、已有的能力（别重复造）

`deepagents` 的 `FilesystemMiddleware` **已内置**：`ls` / `read_file` / `write_file` /
`edit_file` / `delete` / `glob` / `grep`。所以**不需要**再写文件读写工具。

现有注册工具（14 个）：`internet_search` · `fetch_url` · `run_code_in_sandbox` ·
`run_command_in_sandbox` · `upload_workspace_file` · `download_sandbox_file` ·
`run_skill_script` · `write_wiki` · `generate_report` · `ask_human` · `publish_report` ·
`calculate` · `current_time` · `json_extract`
