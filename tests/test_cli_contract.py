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


# --- 退出码 3：NOT_READY_COMMANDS 已随 M5 清空（语义保留，无调用方） ----------

def test_not_ready_commands_table_is_empty_after_m5():
    """M5 落地 `digest`/`run` 后，全部子命令已实现 → `NOT_READY_COMMANDS` 必须为**空集**。

    退出码 3 的**语义与常量保留**（对外契约的一部分：README 退出码表已写、
    `errors.EXIT_NOT_READY`/`NotReadyError` 不删），只是不再有调用方——
    防的是"幽灵语义复活"：将来若有人往表里加回命令，这条测试所在的
    `parametrize` 会自动恢复对该命令的 exit 3 断言（空表 = 无参数化用例，
    但本条空集断言仍在）。
    """
    assert NOT_READY_COMMANDS == {}
    assert errors.EXIT_NOT_READY == 3
    assert hasattr(errors, "NotReadyError"), "退出码 3 的语义常量不得整体删除（对外契约）"


def test_retired_commands_do_real_work_offline(tmp_path, monkeypatch):
    """M2–M5 退役的命令**真干活**（离线）：diff 判定真值一致、parse 解析真值一致、
    bench 三套件达标退出 0、digest 真渲染日报、run 真编排（离线注入产物）。

    这是"退役 ≠ 顺手删语义"的行为级证明：diff/parse 走 0/2、bench 走 0/1/2、
    digest/run 走 0/1/2 退出码通路。
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

    # --- digest（M5 退役）：真渲染日报（离线） --------------------------------
    from policy_radar.pipeline import load_subscribe_hits
    from policy_radar.snapshot import load_items_file

    new_items = load_items_file(out_diff)
    subscribe_product = load_subscribe_hits(new_items, data)
    out_subscribe = os.path.join(str(tmp_path), "subscribe.json")
    from policy_radar.serialize import write_json as _write_json
    _write_json(out_subscribe, subscribe_product)
    out_md = os.path.join(str(tmp_path), "report.md")
    out_html = os.path.join(str(tmp_path), "report.html")
    code_digest = main(["digest", "--new-items", out_diff,
                        "--hits", out_subscribe, "--parse", out_parse,
                        "--out", out_md, "--format", "both"])
    assert code_digest == errors.EXIT_OK
    assert os.path.isfile(out_md)
    assert os.path.isfile(os.path.join(str(tmp_path), "report.html"))
    md_text = io.open(out_md, "r", encoding="utf-8").read()
    assert "政策文件雷达" in md_text
    truth_diff = read_json(os.path.join(data, "truth", "diff-truth.json"))
    expected_new = truth_diff["expect"]["new_count"]
    if expected_new:
        assert "本次无新增" not in md_text

    # --- run（M5 退役）：真编排（离线：monkeypatch 传输层为冻结样本，联网无关） --
    # 与 fetch 测试同纪律：patch 打在调用方模块（pipeline）的绑定名上。
    from policy_radar import pipeline as pipeline_mod
    from policy_radar.fetch import build_output

    meta_ok = {
        "channel": "gwy", "channel_param": "zhengcelibrary_gwy", "status": "ok",
        "pages": 1, "n": 6, "requested": 6, "returned": 6, "kept": 6,
        "dropped": 0, "dropped_details": [], "declared_total": 6,
        "captured_at": "2026-10-17T00:00:00", "page_details": [], "error": "",
    }
    fetched_path = os.path.join(str(tmp_path), "fetched-in.json")
    _write_json(fetched_path, build_output(new_items, [meta_ok],
                                           "2026-10-17T00:00:00"))
    offline_items = load_items_file(fetched_path)
    monkeypatch.setattr(pipeline_mod, "fetch_all",
                        lambda *a, **kw: (offline_items, [meta_ok]))

    run_out = os.path.join(str(tmp_path), "run")
    code_run = main(["run", "--channels", "gwy", "--out-dir", run_out,
                     "--data-root", data])
    assert code_run == errors.EXIT_OK
    run_report_md = os.path.join(run_out, "report.md")
    assert os.path.isfile(run_report_md)
    assert os.path.isfile(os.path.join(run_out, "report.html"))
    for name in ("fetched.json", "diff.json", "snapshot.json", "parsed.json",
                 "subscribe.json"):
        assert os.path.isfile(os.path.join(run_out, name)), name

    # 行为等价（编排层纪律）：直调编排（离线注入）的统计 == 报告内容与 CLI 通路逐字节一致。
    stats = pipeline_mod.run_pipeline(
        channels=["gwy"], out_dir=os.path.join(str(tmp_path), "run-direct"),
        data_root=data, fetch_items=offline_items,
        fetch_channel_meta=[meta_ok], captured_at="2026-10-17T00:00:00")
    assert stats["new_count"] == len(offline_items)
    # hit_count 是**命中记录数**（每词一条），不是条目数——条目级口径按 id 集合对账。
    hit_entry_ids = {h["item_id"] for h in
                     read_json(os.path.join(str(tmp_path), "run-direct",
                                            "subscribe.json"))["hits"]}
    zero_ids = set(read_json(os.path.join(str(tmp_path), "run-direct",
                                          "subscribe.json"))["zero_hit_ids"])
    excluded_ids = {e["item_id"] for e in
                    read_json(os.path.join(str(tmp_path), "run-direct",
                                           "subscribe.json"))["excluded"]}
    new_ids = set(read_json(os.path.join(str(tmp_path), "run-direct",
                                         "diff.json"))["new_ids"])
    assert hit_entry_ids | zero_ids | excluded_ids == new_ids
    assert not (hit_entry_ids & zero_ids) and not (hit_entry_ids & excluded_ids)
    direct_md = io.open(os.path.join(str(tmp_path), "run-direct", "report.md"),
                        "r", encoding="utf-8").read()
    cli_md = io.open(run_report_md, "r", encoding="utf-8").read()
    assert direct_md == cli_md


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
