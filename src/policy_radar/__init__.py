"""政策文件雷达（policy-radar）。

本地定时抓取中国政府网政策文件库（国务院 + 部委两个频道），通过"上次快照 diff"
检测今日新发政策，把"新发政策 + 发文字号 + 发布部门 + 摘要"变成一份可订阅关键词的中文日报。

设计纪律（详见 plan/04-模块详设.md 的 K 清单）：
- 运行时零第三方依赖（仅 stdlib），Python 底线 3.12（D30；原 3.8，由 PEP 639 的
  setuptools>=77 倒推，见 plan/00 决策表）；
- 全链路确定性：无 LLM、不读时钟参与判定、写盘经单一序列化单点；
- 未挂原文核对（与 API 返回字段一致）不得落库、不得在日报中生效。
"""

__version__ = "0.2.0"

# 与 pyproject.toml 的 [project] version 必须一致（tests/test_cli_contract.py 守门）。
__all__ = ["__version__"]
