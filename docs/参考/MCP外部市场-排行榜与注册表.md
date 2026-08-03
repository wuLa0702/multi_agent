# 参考：MCP 外部市场、排行榜与注册表

> 📋 **规范**：遵循 `docs/文档规范.md`
> 📌 **更新时间**：2026-08-03
> 📝 **版本变更记录**（永久保存，只追加不删除）：

> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1 | 2026-08-03 | 初版：收录主要 MCP 市场/注册表链接与定位，为后续"浏览→安装外置 skill"对接准备 |

> **目录**：
> - § 用途
> - § 市场总览表
> - § 对接建议
> - § 生态背景与安全提醒

---

## 用途

本页收录 MCP 生态的主要外部市场/排行榜，作为「浏览 → 下载安装外部 skill」
功能（规划中，尚未实现）的选型参考。当前项目接入外部 MCP 的能力已有
（`mcp/client.py` 连接 `mcp_servers` 表配置的 server），缺的是**发现**环节
——即"去哪里找、怎么选、排行榜在哪"。

## 市场总览表

| 平台 | 规模（2026 中） | 亮点 | 适合场景 |
|------|------|------|----------|
| [Smithery](https://smithery.ai) | 132K+ skills，5K+ servers | CLI 安装（`smithery install`），最接近"npm for MCP"，深度绑定 Anthropic | **首选对接**：有 CLI + API，托管免部署 |
| [MCP.so](https://mcp.so) | 20K+ servers | 调用量排行榜（Call Ranking），免费开源 | **首选对接**：公开排行数据好拿 |
| [PulseMCP](https://pulsemcp.com) | 12K+ servers | 编辑精选 + 访客指标，official/community 分类 | 人工浏览、质量过滤 |
| [Awesome MCP Servers](https://github.com/punkpeye/awesome-mcp-servers) | 80.6K ⭐ | 社区最全面的精选列表 | 人工浏览、按类别找 |
| [MCP Market](https://mcpmarket.com) | 38K servers，250K skills | 按 GitHub stars 排行 | 看热度排行 |
| [SkillsMP](https://skillsmp.com) | 34K+ skills | AI 语义搜索 + CLI 一键安装 | 找 skill 而非 server |
| [Glama](https://glama.ai/mcp) | 21K+ servers | 安全扫描 + 企业级网关 | 注重安全性 |
| [官方 Registry](https://registry.modelcontextprotocol.io) | — | Anthropic/MCP 工作组维护，JSON 机器可读 | 权威元数据，**无排行** |

## 对接建议

- **首选 Smithery**：有 `smithery install` CLI 和公开 API，安装元数据可直接
  落地为 `mcp_servers` 表的行（transport/url/command/args 都有了）
- **次选 MCP.so**：有公开的调用量排行榜数据，可做"热门 skill"推荐列表
- 注意：各市场没有统一协议，对接方式各不相同——按需逐个适配，不做大一统

## 生态背景与安全提醒

- 2026 年生态已破万：10,000+ 活跃 server，9,700 万+ 月下载；协议已捐赠给
  Linux 基金会下的 Agentic AI Foundation（AAIF）
- **质量参差**：2026 年审计 2,181 个远程 MCP 端点，仅 9% 完全健康，
  52% 实际已死/弃养。选 server 优先**第一方官方**（GitHub、Stripe、Notion 等）
- **安全风险**：生态出现过 CVSS 9.6 的 `mcp-remote` RCE、Git MCP server CVE 等。
  安装外部 server = 引入可执行代码，生产环境必须 pin 版本、审查源码
