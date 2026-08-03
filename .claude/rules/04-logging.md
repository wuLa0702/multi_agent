# 日志规范

> 2026-08-02 确立（co-creator 拍板）：项目日志 UTF-8 输出 + 滚动分割策略。
> 适用范围：multi_agent 项目全部日志（后端日志、脚本输出重定向）。

## 1. 编码（硬性要求）

- **所有日志文件一律 UTF-8 输出**：文件 handler 必须显式 `encoding="utf-8"`，禁止依赖系统默认编码（Windows 默认 GBK 会乱码）
- 入口处对 `sys.stdout` / `sys.stderr` `reconfigure(encoding="utf-8")`，控制台与重定向输出统一 UTF-8
- 日志内容为 UTF-8 文本：禁止混入 GBK/ANSI 字节；发现乱码日志先查编码配置再查内容

## 2. 分割与保留（滚动策略）

| 项 | 约定 |
|----|------|
| 时间分割 | 每天 00:00 滚动一次（后缀 `.YYYY-MM-DD`） |
| 大小分割 | 单文件超过 **50MB** 立即滚动 |
| 保留 | 滚动文件保留 **14 个**（约 2 周） |
| 文件名 | `logs/multi-agent.log`（本地）/ `/logs/multi-agent.log`（云端，路径自适应） |

## 3. 唯一配置点

- 日志配置**只允许**在 `backend/src/core/logging.py`（`setup_logging()`），业务模块禁止自建 handler
- 模块顶部调用一次：`setup_logging()`（幂等，重复调用无副作用）
- 接管 uvicorn 系 logger（uvicorn / uvicorn.error / uvicorn.access），统一格式与编码

## 4. 其他

- 日志目录 `logs/` 已在 .gitignore（不提交日志文件）
- 业务日志用 `logging.getLogger(__name__)`，禁止 print 代替日志
