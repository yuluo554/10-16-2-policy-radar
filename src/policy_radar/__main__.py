"""使 `python -m policy_radar` 可执行（README 指令面守门的"模块可执行"断言需要它）。

薄入口：只做 argv 转发，判定逻辑全在 cli.py，不复制。
"""

import sys

from .cli import main_guarded

if __name__ == "__main__":
    sys.exit(main_guarded())
