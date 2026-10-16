"""selftest 可证伪测试（防"恒 True 空壳"，skill 编排层空壳条）。

核心判据：**把数据根指向空目录，selftest 必须返回非 0**——恒 True 的空壳一测就露。
测试**显式传 `--data-root`**（skill：凡缺省值有副作用的参数，测试与演示一律显式传，
否则回落自动发现会去扫真实仓库数据）。
"""

import os
import subprocess
import sys

from policy_radar.cli import cmd_selftest, main
from policy_radar.errors import EXIT_OK, EXIT_DEGRADED, EXIT_USAGE
from policy_radar.paths import EXPECTED_DATA_SUBDIRS, missing_subdirs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.path.join(ROOT, "data")


class _Args(object):
    def __init__(self, data_root):
        self.data_root = data_root


# --- 阳性：真数据根 ---------------------------------------------------------

def test_selftest_passes_on_real_data_root():
    assert cmd_selftest(_Args(DATA_ROOT)) == EXIT_OK


def test_real_data_root_has_all_subdirs():
    assert missing_subdirs(DATA_ROOT) == []


# --- 阴性对照（本文件的核心）：空目录必须非 0 ------------------------------

def test_selftest_fails_on_empty_data_root(tmp_path):
    """**阴性对照**：空数据根 -> 必须 EXIT_DEGRADED，绝不允许恒 True。"""
    code = cmd_selftest(_Args(str(tmp_path)))
    assert code != EXIT_OK, "空数据根下 selftest 返回 0 = 恒 True 空壳"
    assert code == EXIT_DEGRADED


def test_selftest_fails_on_nonexistent_data_root(tmp_path):
    missing = os.path.join(str(tmp_path), "does-not-exist")
    assert cmd_selftest(_Args(missing)) == EXIT_DEGRADED


def test_selftest_fails_when_one_subdir_missing(tmp_path):
    """只缺一个子目录也必须红（防"只看根目录存在"的弱判据）。"""
    for d in EXPECTED_DATA_SUBDIRS[:-1]:
        os.makedirs(os.path.join(str(tmp_path), d))
    assert cmd_selftest(_Args(str(tmp_path))) == EXIT_DEGRADED


def test_missing_subdirs_reports_names(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), "config"))
    missing = missing_subdirs(str(tmp_path))
    assert "config" not in missing
    assert set(EXPECTED_DATA_SUBDIRS) - {"config"} == set(missing)


# --- 变异验证：把被测行为弄坏，门必须变红 ----------------------------------

def test_selftest_detects_broken_exit_code_table(monkeypatch):
    """变异项：把退出码表改坏 -> selftest 必须红（证明该项不是装饰）。"""
    from policy_radar import errors
    monkeypatch.setattr(errors, "ALL_EXIT_CODES", (0, 1, 2))
    assert cmd_selftest(_Args(DATA_ROOT)) == EXIT_DEGRADED


def test_selftest_detects_broken_schema(monkeypatch):
    """变异项：把 schema 字段表改坏 -> selftest 必须红。"""
    from policy_radar import model
    monkeypatch.setattr(model, "SCHEMA_FIELDS", ("id",))
    assert cmd_selftest(_Args(DATA_ROOT)) == EXIT_DEGRADED


# --- CLI 通路（exit code 从进程里出来，不只看函数返回） --------------------

def _run(args):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    env["PYTHONUTF8"] = "1"
    return subprocess.run([sys.executable, "-m", "policy_radar"] + args,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=env, timeout=60)


def test_cli_selftest_exit_0_on_real_root():
    proc = _run(["selftest", "--data-root", DATA_ROOT])
    assert proc.returncode == EXIT_OK, proc.stdout.decode("utf-8", "replace")


def test_cli_selftest_exit_1_on_empty_root(tmp_path):
    proc = _run(["selftest", "--data-root", str(tmp_path)])
    assert proc.returncode == EXIT_DEGRADED
    out = proc.stdout.decode("utf-8", "replace")
    assert "FAIL" in out


def test_cli_selftest_bad_root_exit_1(tmp_path):
    proc = _run(["selftest", "--data-root", os.path.join(str(tmp_path), "nope")])
    assert proc.returncode == EXIT_DEGRADED


def test_main_no_command_is_usage_error():
    assert main([]) == EXIT_USAGE
