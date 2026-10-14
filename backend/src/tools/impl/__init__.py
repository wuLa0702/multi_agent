"""工具实现（按域分包，工具中心的实现层）。

各域文件：
- search.py  网络搜索（博查 Bocha）
- fetch.py   受控抓取网页正文
- sandbox.py OpenSandbox 执行 + 会话工作区文件同步
- skill.py   技能脚本执行
- wiki.py    wiki 知识库写入
- report.py  研报结构化生成
- ask_human.py / publish_report.py  HITL 出口

注册进 `src/tools/registry.py`（工具真相源）；Agent 只经注册表挂载。
"""
