"""数据根定位（单一来源）。

优先级：**显式参数 > 环境变量 `POLICY_RADAR_DATA` > 源码树相对定位**。

注意（skill 纪律）：凡"缺省值有副作用"的参数（读真实用户数据/写盘），**测试与演示一律
显式传**——所以 `selftest` 的 `--data-root` 在测试里必须显式指向临时目录，不能靠自动发现
（否则阴性对照会去扫真实仓库数据）。

首期发布物是**源码包 + editable 安装**，数据文件以"包外相对路径"定位；wheel 安装后解析
不到（已在 README「已知环境问题」节声明，不写成"已验证 wheel"）。
"""

import os

#: 数据根下必须存在的子目录（selftest 据此判定"数据根完整"）。
EXPECTED_DATA_SUBDIRS = ("config", "snapshots", "truth", "samples")

#: 环境变量名（README 与测试共用，单一来源）。
ENV_DATA_ROOT = "POLICY_RADAR_DATA"


def find_data_root(explicit=None):
    """定位数据根目录；找不到返回 None（调用方转 exit 2 或 selftest 非 0）。"""
    if explicit:
        return explicit if os.path.isdir(explicit) else None

    from_env = os.environ.get(ENV_DATA_ROOT)
    if from_env:
        return from_env if os.path.isdir(from_env) else None

    # 源码树：从本包所在位置向上找含 data/README.md 的目录。
    here = os.path.dirname(os.path.abspath(__file__))
    probe = here
    for _ in range(6):
        candidate = os.path.join(probe, "data")
        if os.path.isfile(os.path.join(candidate, "README.md")):
            return candidate
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return None


def missing_subdirs(data_root):
    """返回数据根下缺失的预期子目录名列表（空列表 = 完整）。"""
    if not data_root or not os.path.isdir(data_root):
        return list(EXPECTED_DATA_SUBDIRS)
    return [d for d in EXPECTED_DATA_SUBDIRS
            if not os.path.isdir(os.path.join(data_root, d))]
