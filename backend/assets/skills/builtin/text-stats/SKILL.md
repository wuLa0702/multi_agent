---
name: text-stats
description: Use this skill when the user wants to count characters, words, or lines in a piece of text or a text file — for example "这段文字多少字" / "统计一下这篇稿子的字数" / "how many words in report.md". Triggers on 字数 / 词数 / 行数 / 字符数 / word count / character count / line count.
---

# Text Stats（文本统计）

统计一段文本或一个文本文件的**字符数 / 词数 / 行数**，输出 JSON。

> 📁 **本技能的位置**：`backend/assets/skills/builtin/text-stats/`，
> 运行时挂载为只读虚拟路径 `/skills/static/text-stats/`（随代码发布，Agent 只读）。
> 对比：市场安装的技能落在 `data/skills/skill_md/`（挂 `/skills/market/`，可增删）。

## 什么时候用

- 用户问"这段多少字""这篇稿子多少词""有多少行"
- 需要为报告 / 文案做字数校验（如"控制在 800 字以内"）
- **不要**用它做翻译、改写、摘要——本技能只数数，不改内容

## 怎么用

1. 统计**工作区文件**：确认文件存在（`ls`）后直接传文件名
2. 统计**用户直接给的一段文字**：先把文本写入临时文件，再传路径（脚本只接受文件路径或 stdin）

```
run_skill_script(skill_name="text-stats", script_name="run.py", script_args="report.md")
```

## 输出

```json
{"chars": 1234, "chars_no_space": 1100, "words": 210, "lines": 42, "source": "report.md"}
```

- `chars`：含空白的总字符数
- `chars_no_space`：去掉所有空白后的字符数（中文"字数"通常用这个）
- `words`：按空白切分的词数（中文按字计更贴近直觉，可用 `chars_no_space`）
- `lines`：行数

## 注意

- 脚本**只读不写**，可安全重复执行
- 文件不存在 / 非 UTF-8 → 脚本返回非零退出码，错误信息在 stderr
