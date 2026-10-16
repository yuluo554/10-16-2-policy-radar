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
    """未就绪命令所需的最小参数（argparse required 参数必须给全，否则 exit 2 掩盖 exit 3）。"""
    required = {
        "fetch": [],
        "diff": ["--snapshot", "s.json", "--current", "c.json"],
        "parse": ["--input", "i.json"],
        "digest": ["--new-items", "n.json"],
        "run": [],
        "bench": [],
    }
    return required[command]


def test_not_ready_stderr_mentions_milestone():
    proc = run_cli(["fetch"])
    err = proc.stderr.decode("utf-8")
    assert "M2" in err


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
    parser = build_parser()
    actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
    names = set()
    for a in actions:
        names |= set(a.choices)
    expected = {"version", "selftest"} | set(NOT_READY_COMMANDS)
    assert expected <= names, expected - names
