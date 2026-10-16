"""pytest 公共配置。

未安装（源码态）时把 `src/` 加入 sys.path，使 `import policy_radar` 成立。
干净环境（README 快速开始 `pip install -e ".[dev]"`）下已装包，本行为无副作用。
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

REPO_ROOT = _ROOT
