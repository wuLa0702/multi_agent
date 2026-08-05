---
name: research-report
description: 生成结构化研究报告——当用户需要调研报告、分析总结、资料综述时使用。
  本技能提供报告骨架生成脚本、写作规范与模板；涉及多来源资料汇总时先委派
  搜索子代理收集资料再按本技能组织。
license: MIT
compatibility: Python 3.11+（scripts 需沙箱执行）
allowed_tools:
  - run_code_in_sandbox
metadata:
  version: "1.0.0"
---

# 研究报告生成

## 概览

将多来源调研资料组织为结构化研究报告。三步流程：
1. **收集**：委派 search_agent 收集资料（多轮可并行）
2. **骨架**：运行 `scripts/build_report.py` 生成报告骨架（先创建沙箱工作目录）
3. **撰写**：按 `assets/report_template.md` 填充章节，风格遵循
   `references/writing_guide.md`

## 关键指令

1. 报告结构固定五段：结论先行 → 背景 → 发现（分点+证据）→ 讨论 → 建议
2. 每个发现必须附来源（标题+链接）；无来源信息标注"待核实"
3. 生成骨架后先确认章节覆盖用户问题，再逐节撰写
4. 输出前用 `references/writing_guide.md` 的自检清单过一遍

## 配套文件

- 骨架脚本：`scripts/build_report.py`（用法见文件头注释）
- 写作规范：`references/writing_guide.md`
- 报告模板：`assets/report_template.md`
