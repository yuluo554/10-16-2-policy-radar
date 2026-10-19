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


# --- 安装态契约：非 editable 安装读不到数据根 -----------------------------
#
# 本仓的数据文件以**包外相对路径**定位（`paths.find_data_root` 从包所在目录向上找
# `data/README.md`）。非 editable 安装（wheel/sdist）时包落在 site-packages，
# 向上找不到数据根 —— 这是**已知且已在 README 披露的契约**，不是缺陷。
#
# 这里把它钉成门禁，防它"悄悄变成 0"（真出现包内 data 时，下面那条必须红并提醒改契约）。
# 判据不靠字符串：把包**复制到源树外**再跑 CLI，完全等价于安装态的 sys.path 布局。

import shutil  # noqa: E402  （与上方同组，仅按主题就近放置）

SRC_PKG = os.path.join(ROOT, "src", "policy_radar")


def _run_outside_source_tree(pkg_parent, args):
    """在"包位于源树外"的 sys.path 布局下跑 CLI（安装态等价物）。"""
    env = dict(os.environ)
    env.pop("POLICY_RADAR_DATA", None)  # 契约场景不设环境变量
    env["PYTHONPATH"] = pkg_parent
    env["PYTHONUTF8"] = "1"
    return subprocess.run([sys.executable, "-m", "policy_radar"] + args,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=env, timeout=60)


def test_installed_layout_cannot_find_data_root(tmp_path):
    """**契约门禁**：包在源树外且未显式给数据根 → selftest 必须 exit 1 并点名缺失项。

    同时断言前置条件（自动发现确实返回 None），否则这条测试会在"意外找到数据根"时
    假绿——那正是"守门空转"的形态。
    """
    from policy_radar.paths import find_data_root

    pkg_parent = str(tmp_path / "site-packages")
    os.makedirs(pkg_parent)
    shutil.copytree(SRC_PKG, os.path.join(pkg_parent, "policy_radar"))

    # 前置条件：这个布局下自动发现必须找不到数据根（否则下面的断言无意义）。
    env = dict(os.environ)
    env.pop("POLICY_RADAR_DATA", None)
    probe = subprocess.run(
        [sys.executable, "-c",
         "from policy_radar.paths import find_data_root; print(find_data_root())"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=dict(env, PYTHONPATH=pkg_parent),
        timeout=60)
    assert probe.stdout.decode("utf-8", "replace").strip() == "None", (
        "安装态布局下仍能发现数据根，契约门禁失去意义：%r"
        % probe.stdout.decode("utf-8", "replace"))
    assert find_data_root() is not None, "源码态自动发现应当成立（反向自证）"

    proc = _run_outside_source_tree(pkg_parent, ["selftest"])
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == EXIT_DEGRADED, (
        "安装态 selftest 必须 exit 1（数据根不可定位的契约），实测 exit %d：\n%s"
        % (proc.returncode, out[-2000:]))
    assert "data_root_complete" in out and "missing=" in out, (
        "安装态 selftest 必须点出 data_root_complete missing=[...]，实测：\n%s" % out[-2000:])


def test_installed_layout_data_commands_exit_2(tmp_path):
    """同一契约的另一半：数据相关命令（bench/verify-data）必须 exit 2「找不到数据根」。"""
    pkg_parent = str(tmp_path / "site-packages")
    os.makedirs(pkg_parent)
    shutil.copytree(SRC_PKG, os.path.join(pkg_parent, "policy_radar"))

    for command in ("bench", "verify-data"):
        proc = _run_outside_source_tree(pkg_parent, [command])
        assert proc.returncode == 2, (
            "%s 在安装态无数据根时应 exit 2，实测 exit %d：\n%s"
            % (command, proc.returncode, proc.stdout.decode("utf-8", "replace")[-1500:]))


def test_no_data_dir_inside_package():
    """反向：包内**不得**出现 data/ 目录。

    一旦有人把 data 打进包，`find_data_root` 的自动发现会在安装态意外成立，
    上面两条契约测试就会假绿 —— 所以这里独立钉住"数据在包外"这一前提。
    真要改成"打包数据"，必须同时改 README 契约与上面两条测试（有意为之，不是顺手）。
    """
    assert not os.path.isdir(os.path.join(SRC_PKG, "data")), (
        "包内出现 data/ → 「数据在包外」契约被破坏，请同步改 README 契约与本文件三条测试")
