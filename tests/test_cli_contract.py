"""退出码与 CLI 契约测试（K2 锁死）。

覆盖：退出码常量齐备 / 未就绪子命令 exit 3 / 未知子命令 exit 2 / version exit 0 /
`python -m policy_radar` 可执行 / 失败路径（坏输入不逃逸成 traceback）。
"""

import io
import os
import subprocess
import sys

import pytest

from policy_radar import __version__
from policy_radar import errors
from policy_radar.cli import NOT_READY_COMMANDS, build_parser, main, main_guarded

PY = sys.executable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(args, **kw):
    """在子进程里真跑 CLI（走 `python -m policy_radar`，README 指令面的那条通路）。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    env["PYTHONUTF8"] = "1"
    return subprocess.run([PY, "-m", "policy_radar"] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=env, timeout=60, **kw)


# --- 退出码常量 -------------------------------------------------------------

def test_exit_codes_complete_and_distinct():
    codes = errors.ALL_EXIT_CODES
    assert codes == (0, 1, 2, 3, 4), codes
    assert len(set(codes)) == len(codes)


def test_radar_error_is_value_error_subclass():
    """领域异常必须能被 CLI 的 `except (RadarError, ValueError)` 捕获。"""
    for exc_type in (errors.UsageError, errors.NotReadyError,
                     errors.ExternalError, errors.DegradedError):
        assert issubclass(exc_type, ValueError), exc_type
        assert issubclass(exc_type, errors.RadarError), exc_type


def test_domain_exception_carries_exit_code():
    assert errors.UsageError("x").code == errors.EXIT_USAGE
    assert errors.NotReadyError("x").code == errors.EXIT_NOT_READY
    assert errors.ExternalError("x").code == errors.EXIT_EXTERNAL
    assert errors.DegradedError("x").code == errors.EXIT_DEGRADED


# --- 未就绪子命令 exit 3 ----------------------------------------------------

@pytest.mark.parametrize("command", sorted(NOT_READY_COMMANDS))
def test_not_ready_commands_exit_3(command):
    """骨架期未就绪子命令必须 exit 3，且**不产出空结果**（stderr 写明计划里程碑）。"""
    proc = run_cli([command] + _min_args(command))
    assert proc.returncode == errors.EXIT_NOT_READY, proc.stderr.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    assert "尚未就绪" in err
    assert proc.stdout == b"" or proc.stdout.decode("utf-8").strip() == ""


def _min_args(command):
    """未就绪命令所需的最小参数（argparse required 参数必须给全，否则 exit 2 掩盖 exit 3）。

    `fetch` 已在 M2 落地、`diff`/`parse` 已在 M3 落地、`bench` 已在 M4 落地
    -> 均从本表移除（K2 退役：凡断言某命令 exit 3 的地方，退役时逐处处置）。
    """
    required = {
        "digest": ["--new-items", "n.json"],
        "run": [],
    }
    return required[command]


def test_not_ready_stderr_mentions_milestone():
    """未就绪命令的 stderr 必须写明计划里程碑。

    M4 后 `bench` 已落地（真值基准，0/1/2），**不能再断言它 exit 3** -> 改用仍在
    未就绪状态的 `digest`（M5）。这条测试守的是"退出码 3 的提示语含里程碑"
    这一契约，不是某一条具体命令。
    """
    proc = run_cli(["digest", "--new-items", "n.json"])
    err = proc.stderr.decode("utf-8")
    assert "M5" in err


def test_fetch_diff_parse_bench_are_retired_from_not_ready():
    """`fetch`（M2）/ `diff`、`parse`（M3）/ `bench`（M4）必须已从
    `NOT_READY_COMMANDS` 移除（否则落地了还报"未就绪"）。子命令本身必须
    仍然注册（只是不再 exit 3）。"""
    for command in ("fetch", "diff", "parse", "bench"):
        assert command not in NOT_READY_COMMANDS
        assert command in _registered_commands(), \
            "%s 子命令必须仍然注册（只是不再 exit 3）" % command


def test_other_commands_still_not_ready():
    """反向断言：退役只退 `fetch`/`diff`/`parse`/`bench`，其余命令的 exit 3
    语义**不得**被顺手删掉。"""
    assert set(NOT_READY_COMMANDS) == {"digest", "run"}
    assert errors.EXIT_NOT_READY == 3
    assert hasattr(errors, "NotReadyError"), "NOT_READY 通路（M5 还要用）不得整体删除"


def test_retired_commands_do_real_work_offline(tmp_path):
    """M3/M4 退役的命令**真干活**（离线）：diff 判定真值一致、parse 解析真值一致、
    bench 三套件达标退出 0。

    这是"退役 ≠ 顺手删语义"的行为级证明：diff/parse 走 0/2、bench 走 0/1/2 退出码通路。
    """
    from policy_radar.serialize import read_json

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data = os.path.join(root, "data")
    path_a = os.path.join(data, "snapshots", "pair-A.json")
    path_b = os.path.join(data, "snapshots", "pair-B.json")
    out_diff = os.path.join(str(tmp_path), "diff.json")
    out_snap = os.path.join(str(tmp_path), "snap.json")
    out_parse = os.path.join(str(tmp_path), "parsed.json")

    code_diff = main(["diff", "--snapshot", path_a, "--current", path_b,
                      "--out", out_diff, "--snapshot-out", out_snap])
    assert code_diff == errors.EXIT_OK
    product = read_json(out_diff)
    truth = read_json(os.path.join(data, "truth", "diff-truth.json"))
    assert product["new_ids"] == truth["expect"]["new_ids"]
    assert product["dup_ids"] == truth["expect"]["dup_ids"]

    code_parse = main(["parse", "--input", path_b, "--data-root", data,
                       "--out", out_parse])
    assert code_parse == errors.EXIT_OK
    parsed = read_json(out_parse)
    assert parsed["item_count"] == 21
    assert set(parsed["pcode_status_counts"]) == {"parsed", "partial", "unparsed"}

    code_bench = main(["bench", "--data-root", data])
    assert code_bench == errors.EXIT_OK


# --- bench（M4）：退出码三语义 0 达标 / 1 未达标 / 2 用法错误 -----------------

def test_bench_passes_exit_0_subprocess():
    """全量三套件对真值实算：生产实现逐条一致 → exit 0（子进程端到端）。"""
    data = os.path.join(ROOT, "data")
    proc = run_cli(["bench", "--data-root", data])
    out = proc.stdout.decode("utf-8")
    assert proc.returncode == errors.EXIT_OK, out + proc.stderr.decode("utf-8")
    assert "全部达标" in out


def test_bench_only_accepts_known_suites():
    """`--only` 不认识的名字 = 用法错误 exit 2（不静默跑全量）。"""
    data = os.path.join(ROOT, "data")
    proc = run_cli(["bench", "--only", "nope", "--data-root", data])
    assert proc.returncode == errors.EXIT_USAGE
    assert "only" in proc.stderr.decode("utf-8")


def test_bench_usage_error_exit_2_without_data_root(tmp_path):
    """数据根指向空目录 → 真值/门槛缺失 → exit 2（不是 1；"没数据"不是"未达标"）。"""
    proc = run_cli(["bench", "--data-root", str(tmp_path)])
    assert proc.returncode == errors.EXIT_USAGE


def test_fetch_usage_error_exit_2_without_network():
    """`fetch --pages 0` 必须在**发任何请求之前**就被参数校验挡下 -> exit 2。

    本用例刻意不加 `--out` 也不打真站点：参数非法时进程不该碰网络。
    """
    proc = run_cli(["fetch", "--pages", "0", "--delay", "0"])
    assert proc.returncode == errors.EXIT_USAGE, proc.stderr.decode("utf-8", "replace")
    assert b"pages" in proc.stderr


# --- 未知子命令 exit 2 ------------------------------------------------------

def test_unknown_subcommand_exit_2():
    proc = run_cli(["definitely-not-a-command"])
    assert proc.returncode == errors.EXIT_USAGE


def test_no_subcommand_prints_help_exit_2():
    proc = run_cli([])
    assert proc.returncode == errors.EXIT_USAGE
    out = proc.stdout.decode("utf-8")
    assert "policy-radar" in out


def test_unknown_channel_choice_exit_2():
    """`fetch --channel` 的 choices 校验由 argparse 负责 -> exit 2。"""
    proc = run_cli(["fetch", "--channel", "nope"])
    assert proc.returncode == errors.EXIT_USAGE


# --- version ----------------------------------------------------------------

def test_version_subcommand_exit_0():
    proc = run_cli(["version"])
    assert proc.returncode == errors.EXIT_OK
    assert __version__ in proc.stdout.decode("utf-8")


def test_version_flag_exit_0():
    proc = run_cli(["--version"])
    assert proc.returncode == errors.EXIT_OK
    assert __version__ in proc.stdout.decode("utf-8")


# --- 模块可执行（README 指令面"模块可执行"断言） ---------------------------

def test_module_entry_point_executable():
    """`python -m policy_radar` 必须真能跑（缺 __main__.py 会报 No module named ...）。"""
    proc = run_cli(["version"])
    err = proc.stderr.decode("utf-8")
    assert "__main__" not in err, err
    assert proc.returncode == errors.EXIT_OK


def test_main_guarded_converts_usage_error_to_exit_2(monkeypatch):
    """领域异常经 main_guarded 转成既定退出码，而非逃逸 traceback。"""
    def boom(_argv):
        raise errors.UsageError("坏输入")
    monkeypatch.setattr("policy_radar.cli.main", boom)
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    assert main_guarded(["version"]) == errors.EXIT_USAGE
    assert "坏输入" in err.getvalue()


def test_main_guarded_converts_bad_json_value_error(monkeypatch):
    """`ValueError`（含 json 解码错误）也必须转 exit 2。"""
    def boom(_argv):
        raise ValueError("JSON 格式错误")
    monkeypatch.setattr("policy_radar.cli.main", boom)
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    assert main_guarded(["version"]) == errors.EXIT_USAGE
    assert "输入不可用" in err.getvalue()


# --- parser 结构（README 指令面守门按它反射） --------------------------------

def test_parser_registers_all_commands():
    names = _registered_commands()
    expected = ({"version", "selftest", "verify-data", "fetch"}
                | set(NOT_READY_COMMANDS))
    assert expected <= names, expected - names


def _registered_commands():
    """parser 里注册的全部子命令名（README 指令面守门同款反射）。"""
    parser = build_parser()
    names = set()
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices:
            names |= set(action.choices)
    return names
