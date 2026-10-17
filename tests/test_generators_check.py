"""生成器位级守门（M1 DoD #1：`--check` **两层**真跑）。

**这是"两层"的第二层必须真跑一遍生成器**的落点：本文件用**子进程**真跑每个
生成器的 `--check`，而不是在测试里复述一遍比对逻辑——否则"守门测的是产物还是
生成器"这一问就答不上来（skill 头号假门来源）。

覆盖：
1. 四个生成器 `--check` 真跑，退出码 0（两层：形态正确 + 重跑逐字节一致）；
2. `--check` **可证伪**：改动冻结产物后必须变红（证明它真在读盘比对）；
3. 重跑生成器到临时目录 → 与冻结产物逐字节一致（第二层的直接证据）。
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TOOLS = os.path.join(ROOT, "tools")

GENERATORS = (
    "gen_snapshot_pairs.py",
    "gen_pcode_cases.py",
    "gen_subscribe_cases.py",
    "gen_truth_manifest.py",
)


def _run_tool(name, *args, **kwargs):
    """真跑 tools/ 下的生成器（子进程，与用户/CI 一致的通路）。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-X", "utf8", os.path.join(TOOLS, name)] + list(args),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        cwd=kwargs.pop("cwd", ROOT), timeout=180)


@pytest.mark.parametrize("name", GENERATORS)
def test_generator_check_passes(name):
    """**两层位级守门**：`--check` 必须 exit 0。"""
    proc = _run_tool(name, "--check")
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 0, "%s --check 退出码 %d\n%s%s" % (
        name, proc.returncode, out, err)
    assert "第一层" in out, out
    assert "第二层" in out, out


@pytest.mark.parametrize("name", GENERATORS)
def test_generator_check_scan_surface_not_empty(name):
    """扫描面非空自证：`--check` 输出必须提到它实际校验的产物（防空转）。"""
    proc = _run_tool(name, "--check")
    out = proc.stdout.decode("utf-8", "replace")
    assert ("份产物" in out) or ("sha256" in out) or ("形态" in out), out


def test_check_is_falsifiable_for_snapshot_pairs(tmp_path):
    """**可证伪**：把冻结的快照对改动一个字节 → `--check` 必须变红。

    证明它真在读盘比对（不是"恒 True 空壳"）。测试在**临时目录**里做：
    复制 data/ 到 tmp，改副本，`--root` 指向副本——不碰仓库里的冻结产物。
    """
    fake_root = str(tmp_path)
    shutil.copytree(DATA, os.path.join(fake_root, "data"))
    snap_path = os.path.join(fake_root, "data", "snapshots", "pair-A.json")

    # 篡改：把快照的 item_count 改掉（形态校验应拦住）。
    with io.open(snap_path, "r", encoding="utf-8") as fh:
        snap = json.load(fh)
    snap["item_count"] = snap["item_count"] + 1
    with io.open(snap_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(snap, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    proc = _run_tool("gen_snapshot_pairs.py", "--check", "--root", fake_root)
    assert proc.returncode != 0, "篡改冻结产物后 --check 仍通过 = 恒 True 空壳"
    err = proc.stderr.decode("utf-8", "replace")
    assert "FAIL" in err, err


def test_check_is_falsifiable_for_truth_manifest(tmp_path):
    """`gen_truth_manifest.py --check` 也必须可证伪（改真值即红）。"""
    fake_root = str(tmp_path)
    shutil.copytree(DATA, os.path.join(fake_root, "data"))
    truth_path = os.path.join(fake_root, "data", "truth", "diff-truth.json")
    with io.open(truth_path, "r", encoding="utf-8") as fh:
        truth = json.load(fh)
    truth["expect"]["new_ids"] = truth["expect"]["new_ids"][:-1]
    with io.open(truth_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(truth, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    proc = _run_tool("gen_truth_manifest.py", "--check", "--root", fake_root)
    assert proc.returncode != 0, "改坏真值后 --check 仍通过 = 恒 True 空壳"


def test_regenerate_into_temp_dir_matches_frozen_bytes():
    """**第二层的直接证据**：重跑生成器到临时目录 → 与冻结产物逐字节一致。

    这是"位级一致"的**独立复算**（不是读生成器自己的 `--check` 输出）：
    测试自己跑生成器、自己比字节。
    """
    tmp = tempfile.mkdtemp(prefix="policy-radar-bytecheck-")
    try:
        tmp_data = os.path.join(tmp, "data")
        os.makedirs(os.path.join(tmp_data, "snapshots"))
        os.makedirs(os.path.join(tmp_data, "truth"))
        os.makedirs(os.path.join(tmp_data, "config"))
        # 样本目录用**真实冻结样本**（生成器的输入），故软链/复制过来。
        shutil.copytree(os.path.join(DATA, "samples"),
                        os.path.join(tmp_data, "samples"))
        # 生成器需要真实仓库的 samples 作为输入池，但产物落到 tmp_data。
        # 做法：`--root` 指向 tmp（产物落 tmp/data），samples 已复制过去。
        fake_root = tmp
        for name in ("gen_snapshot_pairs.py", "gen_pcode_cases.py",
                     "gen_subscribe_cases.py", "gen_truth_manifest.py"):
            proc = _run_tool(name, "--root", fake_root)
            assert proc.returncode == 0, (name, proc.stderr.decode("utf-8", "replace"))

        pairs = [
            (os.path.join(tmp_data, "snapshots", "pair-A.json"),
             os.path.join(DATA, "snapshots", "pair-A.json")),
            (os.path.join(tmp_data, "snapshots", "pair-B.json"),
             os.path.join(DATA, "snapshots", "pair-B.json")),
            (os.path.join(tmp_data, "snapshots", "manifest.json"),
             os.path.join(DATA, "snapshots", "manifest.json")),
            (os.path.join(tmp_data, "truth", "diff-truth.json"),
             os.path.join(DATA, "truth", "diff-truth.json")),
            (os.path.join(tmp_data, "truth", "pcode-truth.json"),
             os.path.join(DATA, "truth", "pcode-truth.json")),
            (os.path.join(tmp_data, "truth", "subscribe-truth.json"),
             os.path.join(DATA, "truth", "subscribe-truth.json")),
            (os.path.join(tmp_data, "truth", "manifest.json"),
             os.path.join(DATA, "truth", "manifest.json")),
            (os.path.join(tmp_data, "config", "org-aliases.json"),
             os.path.join(DATA, "config", "org-aliases.json")),
            (os.path.join(tmp_data, "config", "subscribe.json"),
             os.path.join(DATA, "config", "subscribe.json")),
            (os.path.join(tmp_data, "config", "normalize.json"),
             os.path.join(DATA, "config", "normalize.json")),
        ]
        for fresh, frozen in pairs:
            assert os.path.isfile(fresh), "重跑未产出：%s" % fresh
            with io.open(fresh, "rb") as f1, io.open(frozen, "rb") as f2:
                assert f1.read() == f2.read(), "字节不一致：%s" % os.path.basename(frozen)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sample_capture_check_passes():
    """样本 sha256 登记守门（不打真站点）。"""
    proc = _run_tool("capture_samples.py", "--out-dir", os.path.join(DATA, "samples"),
                     "--check")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
