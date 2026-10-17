"""真值台账守门（M1 DoD #2 / #3 / #5；K11）。

覆盖：
1. **真值库无 `observed_*` 字段**（出现即红，K11）；
2. **真值库有真调用方**（不是"文件存在"）：`cases.py` 被 `verify.py` 真 import，
   且 CLI 真的挂了 `verify-data` 子命令；
3. **期望值可由输入独立复算**（生成器的 oracle 与真值一致）；
4. **覆盖声明非空**（防"只写分子"的假覆盖）；
5. **门槛随数据下发且非空**（代码零默认值）。
"""

import io
import json
import os
import subprocess
import sys

import pytest

from policy_radar import cases
from policy_radar.cli import build_parser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TRUTH = os.path.join(DATA, "truth")

TRUTH_FILES = ("diff-truth.json", "pcode-truth.json",
               "subscribe-truth.json", "manifest.json")


def _read_json(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def truth_docs():
    docs = {}
    for name in TRUTH_FILES:
        path = os.path.join(TRUTH, name)
        assert os.path.isfile(path), "真值台账缺失：%s" % name
        docs[name] = _read_json(path)
    return docs


# --- 1. K11：真值库无 observed 字段 -----------------------------------------

@pytest.mark.parametrize("name", TRUTH_FILES)
def test_truth_has_no_observed_fields(name, truth_docs):
    """**K11 核心断言**：真值库出现 `observed_*` 一类字段即红。

    冻结"观测"会让基准退化成"比对两份预先算好的答案"——引擎全坏也全绿。
    """
    offenders = cases.find_observed_fields(truth_docs[name], "truth/%s" % name)
    assert offenders == [], "真值库出现 observed 类字段：%r" % offenders


def test_observed_field_detector_is_falsifiable():
    """变异验证：注入 `observed_x` → 探针必须红（防"探针永不红"）。"""
    assert cases.find_observed_fields({"a": {"observed_x": 1}}) != []
    assert cases.find_observed_fields({"observed_hits": []}) != []
    # 反向：正常字段不得误报。
    assert cases.find_observed_fields({"expect": {"hits": []}}) == []
    with pytest.raises(AssertionError):
        cases.assert_no_observed_fields({"observed_y": 2})


def test_no_truth_file_contains_observed_key_textually():
    """文本级双保险：三份真值 + 清单的**原文**不得含 `"observed` 子串。"""
    for name in TRUTH_FILES:
        path = os.path.join(TRUTH, name)
        with io.open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        assert '"observed' not in text, "%s 含 observed 字段" % name


# --- 2. 真值库有真调用方（三问之③） -----------------------------------------

def test_cases_module_is_imported_by_verify():
    """**真调用方**：`verify.py` 必须真 import `cases`（不是"文件存在"）。"""
    verify_path = os.path.join(ROOT, "src", "policy_radar", "verify.py")
    assert os.path.isfile(verify_path)
    with io.open(verify_path, "r", encoding="utf-8") as fh:
        src = fh.read()
    assert "from .cases import" in src, "verify.py 未 import cases（真值库无调用方）"
    for func in ("naive_diff", "naive_parse_pcode", "naive_match", "compare_diff"):
        assert func in src, "verify.py 未使用 %s" % func


def test_verify_data_command_is_registered():
    """用户敲的那条命令必须真注册（`verify-data`）。"""
    parser = build_parser()
    names = set()
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices:
            names |= set(action.choices)
    assert "verify-data" in names, names


def test_verify_data_reads_truth_files():
    """`verify.py` 必须真按文件名读真值库（防"读了但读的是别的东西"）。"""
    verify_path = os.path.join(ROOT, "src", "policy_radar", "verify.py")
    with io.open(verify_path, "r", encoding="utf-8") as fh:
        src = fh.read()
    for name in ("diff-truth.json", "pcode-truth.json", "subscribe-truth.json",
                 "manifest.json"):
        assert name in src, "verify.py 未引用 %s" % name


def test_verify_data_cli_actually_runs_and_exits_0():
    """**端到端**：真跑用户那条命令，必须 exit 0 且真比对过条目。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "policy_radar", "verify-data", "--data-root", DATA],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=120)
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, out + proc.stderr.decode("utf-8", "replace")
    assert "全部自洽" in out, out
    assert "比对" in out, out


# --- 3. 期望值可由输入独立复算 ----------------------------------------------

def test_diff_expect_matches_oracle_recompute(truth_docs):
    """**核心纪律**：把真值的输入喂给 oracle 重算，必须与期望逐条一致。

    这证明"真值不依赖生产实现"——oracle 是 `cases.py` 里独立写的参照实现。
    """
    truth = truth_docs["diff-truth.json"]
    items_a = _read_json(os.path.join(DATA, truth["input"]["snapshot_a"]))["items"]
    items_b = _read_json(os.path.join(DATA, truth["input"]["snapshot_b"]))["items"]
    new_ids, dup_ids, matched_by = cases.naive_diff(items_a, items_b)
    assert new_ids == truth["expect"]["new_ids"]
    assert dup_ids == truth["expect"]["dup_ids"]
    assert matched_by == truth["expect"]["matched_by"]


def test_pcode_expect_matches_oracle_recompute(truth_docs):
    truth = truth_docs["pcode-truth.json"]
    for case in truth["cases"] + truth["pool_corpus_cases"]:
        assert cases.naive_parse_pcode(case["pcode"]) == case["expect"], case["pcode"]


def test_subscribe_expect_matches_oracle_recompute(truth_docs):
    truth = truth_docs["subscribe-truth.json"]
    from policy_radar.model import PolicyItem
    snap = _read_json(os.path.join(DATA, truth["input"]["corpus"]))
    items = [PolicyItem.from_dict(d) for d in snap["items"]]
    subscribe = _read_json(os.path.join(DATA, truth["input"]["config"]))
    normalize = _read_json(os.path.join(DATA, truth["input"]["normalize"]))
    hits, excluded, zero = cases.naive_match(
        items, subscribe["include"], subscribe["exclude"], normalize["map"])
    # 排序口径与生成器一致：语料序 + **去重后**关键词配置序（同词重复只占一个位次）。
    order = dict((it.id, i) for i, it in enumerate(items))
    keyword_order = cases.dedup_keywords(subscribe["include"], normalize["map"])
    inc_order = dict((kw, i) for i, kw in enumerate(keyword_order))
    hits.sort(key=lambda h: (order.get(h["item_id"], 0),
                             inc_order.get(h["keyword"], 0)))
    excluded.sort(key=lambda e: order.get(e["item_id"], 0))
    zero.sort(key=lambda o: order.get(o, 0))
    assert hits == truth["expect"]["hits"]
    assert excluded == truth["expect"]["excluded"]
    assert zero == truth["expect"]["zero_hit_item_ids"]


# --- 4. 覆盖声明非空（防"只写分子"的假覆盖） --------------------------------

def test_manifest_coverage_declares_shapes_and_samples(truth_docs):
    """覆盖声明必须**逐形态**登记采样数，且每形态 > 0；并显式声明抽样、非穷举。"""
    manifest = truth_docs["manifest.json"]
    assert manifest["coverage"], "覆盖声明为空"
    for cov in manifest["coverage"]:
        assert cov["declared_shapes"], cov["case"]
        assert cov["sampled_shapes"], cov["case"]
        for shape in cov["declared_shapes"]:
            assert cov["shape_sample_counts"].get(shape, 0) > 0, (cov["case"], shape)
        assert cov["sampling_note"], cov["case"]
    assert "抽样覆盖" in manifest["coverage_disclaimer"]
    assert "非穷举" in manifest["coverage_disclaimer"]


def test_manifest_declared_shapes_cover_all_declared_forms(truth_docs):
    """diff 的五类形态必须全部出现在覆盖声明里（题面硬要求两类 + 三类边界）。"""
    diff_cov = [c for c in truth_docs["manifest.json"]["coverage"]
                if c["case"] == "diff-truth.json"][0]
    for shape in ("carried", "fresh", "pcode_dup",
                  "empty_pcode_new", "empty_pcode_same"):
        assert shape in diff_cov["declared_shapes"], shape


# --- 5. 门槛随数据下发且非空 ------------------------------------------------

def test_thresholds_are_downloaded_with_data(truth_docs):
    """**代码零默认值**：门槛必须在真值 manifest 里，且非空。"""
    thresholds = truth_docs["manifest.json"]["thresholds"]
    assert thresholds, "门槛缺失（应随数据下发）"
    for key in ("diff_new_accuracy", "diff_dup_accuracy",
                "pcode_status_accuracy", "subscribe_hit_recall"):
        assert key in thresholds, key
        assert isinstance(thresholds[key], float)
        assert 0.0 < thresholds[key] <= 1.0, (key, thresholds[key])


def test_verify_data_rejects_missing_thresholds(tmp_path):
    """门槛缺失 -> 配置错误 exit 2（**不回落代码默认值**）。"""
    data_root = str(tmp_path)
    for sub in ("truth", "config", "snapshots", "samples"):
        os.makedirs(os.path.join(data_root, sub))
    # 造一个"三子目录齐但 manifest 无 thresholds"的数据根。
    with io.open(os.path.join(data_root, "truth", "manifest.json"),
                 "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"coverage": []}))
    for name in ("diff-truth.json", "pcode-truth.json", "subscribe-truth.json"):
        with io.open(os.path.join(data_root, "truth", name), "w",
                     encoding="utf-8") as fh:
            fh.write("{}")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "policy_radar", "verify-data",
         "--data-root", data_root],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
    assert proc.returncode == 2, proc.stdout.decode("utf-8", "replace")
    assert "thresholds" in proc.stderr.decode("utf-8", "replace")


# --- 6. 快照形态（K10：禁全文） ---------------------------------------------

def test_snapshots_have_no_forbidden_fulltext_fields():
    """K10：快照出现 `content/body/fulltext` 一类字段即红。"""
    from policy_radar.model import FORBIDDEN_SNAPSHOT_FIELDS
    forbidden = set(FORBIDDEN_SNAPSHOT_FIELDS)
    for name in ("pair-A.json", "pair-B.json"):
        snap = _read_json(os.path.join(DATA, "snapshots", name))
        for item in snap["items"]:
            assert set(item.keys()) & forbidden == set(), (name, item.get("id"))


def test_snapshots_are_canonically_ordered():
    """K5：快照 items 必须按 `(pubtimeStr 倒序, id 升序)`（全程不读时钟）。

    判据是**两步排序的复合结果**：先按 id 升序、再**稳定**按 pubtimeStr 倒序。
    因此断言不能是"全局 id 升序"（跨日期时 id 会回退），而应是：
    ① 日期序列非递增；② **同一日期内** id 严格递增。
    """
    for name in ("pair-A.json", "pair-B.json"):
        snap = _read_json(os.path.join(DATA, "snapshots", name))
        dates = [it["pubtimeStr"] for it in snap["items"]]
        assert dates == sorted(dates, reverse=True), "%s 日期未按倒序" % name

        groups = {}
        for it in snap["items"]:
            groups.setdefault(it["pubtimeStr"], []).append(it["id"])
        for date in sorted(groups, reverse=True):
            ids = groups[date]
            assert ids == sorted(ids), "%s 的 %s 组内 id 未升序：%r" % (name, date, ids)
