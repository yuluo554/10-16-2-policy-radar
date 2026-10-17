"""真值基准（M4）：`bench` 子命令——三套件一键跑通 + 门槛判定 + 可证伪探活。

与 `verify-data`（M1）的分工（别混）：

- **`verify-data`**：真值库**自身自洽**——把真值的输入喂**参照实现**（oracle）
  实算，与期望逐条比对。它证明"期望可由输入独立复算"，**不跑生产实现**。
- **`bench`（本命令）**：把真值的输入喂**生产实现**（`snapshot.detect_new` /
  `parse.parse_pcode` / `subscribe.match_items`）实算，用**共用对账语义**
  （`cases.compare_*`，K15）与期望逐条比对，再按**随数据下发的门槛**
  （K17）判达标。它证明"生产实现对真值逐条一致"。

对账语义（K15）与门槛装载（K17）**同源复用**，不写第二份：
- 对账 = `cases.compare_diff` / `compare_pcode` / `compare_subscribe`；
- 门槛 = `verify._load_thresholds`（`data/truth/manifest.json` 的 `thresholds`，
  缺失即 exit 2，**代码零默认值**）。

## 退出码三语义（锁进 tests/test_cli_contract.py）

- **0** 达标：三套件全 ok 且全部门槛满足；
- **1** 未达标：任一套件不 ok 或任一门槛不满足（**逐条点名**：缺的、多的、
  判错的键，以及"该有而没有"的检出缺口）；
- **2** 用法错误：数据根缺失、真值文件缺失/坏格式、门槛缺失、`--only` 不认识。

## 双边门（K 门槛的两边）

对账 ok 只保证"不该有的结论一条没多"（**误报率 0**），但生产实现若**整条
通路空转**（如命中恒为空、解析恒 unparsed），对账也会 ok——只要真值也是空。
故每套件在"ok 门"之外再配**检出门**（该有的逐样本点名，阈值随 manifest 下发）：

- diff：`diff_new_accuracy` / `diff_dup_accuracy`（真值 new/dup 逐 id 命中率）；
- pcode：`pcode_field_accuracy` / `pcode_status_accuracy`（逐键逐字段命中率）；
- subscribe：`subscribe_hit_recall`（真值命中逐条命中）/ `subscribe_hit_precision`
  （观测命中没有多余的）/ `subscribe_exclude_recall`（真值剔除逐条剔除）。

门槛值与阈值键名**只从 manifest 读**，缺哪个键即 exit 2（不猜、不默认）。

## 可证伪探活

"探活"由测试执行：向生产实现**注入缺陷**（如把 pcode 键判定注释掉、把命中
判定短路成空），基准必须**报未达标（exit 1）**——打到**端到端入口**（CLI 层，
经 `main()` / `cmd_bench`），不是只调函数。探活方法见 `tests/test_subscribe_bench.py`
（monkeypatch 生产函数后跑 `main(["bench"])` 断言退出码与点名行）。
"""

import os
import sys

from . import cases  # noqa: F401  基准是 cases 的**正当调用方**（K14 不适用本模块）
from .cases import compare_diff, compare_pcode, compare_subscribe
from .errors import EXIT_OK, EXIT_DEGRADED, EXIT_USAGE, UsageError
from .parse import parse_orgs, parse_pcode
from .paths import find_data_root
from .serialize import read_json
from .snapshot import detect_new, load_items_file
from .subscribe import load_subscribe_inputs, match_items, sort_hits_like_truth
from .verify import (
    TRUTH_DIFF, TRUTH_MANIFEST, TRUTH_PCODE, TRUTH_SUBSCRIBE,
    _load_thresholds,
)

#: 各套件需要的门槛键（K17：随数据下发；缺任一键即 exit 2，代码零默认值）。
REQUIRED_THRESHOLDS = (
    "diff_new_accuracy",
    "diff_dup_accuracy",
    "pcode_field_accuracy",
    "pcode_status_accuracy",
    "subscribe_hit_recall",
    "subscribe_hit_precision",
    "subscribe_exclude_recall",
)


def _load(data_root, *parts):
    """读数据文件；缺失或坏格式抛 `UsageError`（→ exit 2）。"""
    path = os.path.join(data_root, *parts)
    if not os.path.isfile(path):
        raise UsageError("数据文件缺失：%s" % path)
    try:
        return read_json(path)
    except ValueError as exc:
        raise UsageError(str(exc))


TRUTH_FILE_BY_SUITE = {
    "diff": TRUTH_DIFF,
    "pcode": TRUTH_PCODE,
    "subscribe": TRUTH_SUBSCRIBE,
}


def _load_truth(data_root, suite):
    """按套件名读真值台账。"""
    return _load(data_root, "truth", TRUTH_FILE_BY_SUITE[suite])


# ===========================================================================
# 各套件：生产实现实算 → compare_* 对账 → 双边门（ok 门 + 检出门）
# ===========================================================================

def bench_diff(data_root, truth):
    """diff 套件：`snapshot.detect_new`（生产）实算 → `compare_diff` 对账。"""
    items_a = load_items_file(
        os.path.join(data_root, truth["input"]["snapshot_a"].replace("/", os.sep)))
    items_b = load_items_file(
        os.path.join(data_root, truth["input"]["snapshot_b"].replace("/", os.sep)))
    result = detect_new(items_a, items_b)
    observed = {"new_ids": result["new_ids"], "dup_ids": result["dup_ids"],
                "matched_by": result["matched_by"]}
    compare = compare_diff(observed, truth["expect"])
    meta = {"suite": "diff", "corpus": len(items_a) + len(items_b),
            "compared": len(result["new_ids"]) + len(result["dup_ids"])}
    return compare, meta, {"observed": observed}


def bench_pcode(data_root, truth):
    """pcode 套件：`parse.parse_pcode`（生产）实算 → `compare_pcode` 对账。"""
    expected = {}
    for case in truth["cases"]:
        expected[case["pcode"]] = case["expect"]
    for case in truth.get("pool_corpus_cases", []):
        expected.setdefault(case["pcode"], case["expect"])
    observed = dict((pcode, parse_pcode(pcode)) for pcode in expected)
    compare = compare_pcode(observed, expected)
    meta = {"suite": "pcode", "corpus": len(expected), "compared": len(expected)}
    return compare, meta, {"observed": observed, "expected": expected}


def bench_subscribe(data_root, truth):
    """subscribe 套件：`subscribe.match_items`（生产）实算 → `compare_subscribe` 对账。"""
    items = load_items_file(
        os.path.join(data_root, truth["input"]["corpus"].replace("/", os.sep)))
    config, norm_map = load_subscribe_inputs(data_root)
    hits, excluded, zero = match_items(items, config["include"],
                                       config["exclude"], norm_map)
    hits, excluded, zero = sort_hits_like_truth(hits, excluded, zero, items,
                                                config["include"], norm_map)
    observed = {"hits": hits, "excluded": excluded, "zero_hit_item_ids": zero}
    compare = compare_subscribe(observed, truth["expect"])
    meta = {"suite": "subscribe", "corpus": len(items),
            "compared": len(hits) + len(excluded) + len(zero)}
    return compare, meta, {"observed": observed}


#: 套件注册表：(名称, 实算函数)。
SUITES = (
    ("diff", bench_diff),
    ("pcode", bench_pcode),
    ("subscribe", bench_subscribe),
)


# ===========================================================================
# 双边门：检出门（该有的逐样本点名；阈值随 manifest 下发，K17）
# ===========================================================================

def _accuracy_hit(expected_keys, observed_keys):
    """命中率 = 观测命中数 / 期望数（期望空集 → 恒 1.0，"该有没有"为空集）。"""
    if not expected_keys:
        return 1.0
    hit = sum(1 for key in expected_keys if key in observed_keys)
    return hit / float(len(expected_keys))


def evaluate_gates(suite, compare, extra, truth, thresholds):
    """双边门判定：返回 `(ok, 缺口点名行列表)`。

    第一边（误报 0）：`compare["ok"]`——不该有的结论一条不能多（含 matched_by
    命中键判错、命中位置错、剔除判错）。
    第二边（检出率）：真值期望逐样本点名，命中率 ≥ manifest 门槛——
    生产实现整条空转（命中恒空、解析恒未解析）时第一边可能仍 ok，本边必红。
    """
    lines = []
    ok = bool(compare.get("ok"))

    if suite == "diff":
        exp_new = truth["expect"]["new_ids"]
        exp_dup = truth["expect"]["dup_ids"]
        obs_new = set(extra["observed"]["new_ids"])
        obs_dup = set(extra["observed"]["dup_ids"])
        for label, expected, observed, key in (
                ("新增", exp_new, obs_new, "diff_new_accuracy"),
                ("重复", exp_dup, obs_dup, "diff_dup_accuracy")):
            rate = _accuracy_hit(expected, observed)
            if rate < thresholds[key]:
                ok = False
                missing = [i for i in expected if i not in observed]
                lines.append("检出门未达：%s命中率 %.4f < 门槛 %s（%s 缺 %d 条：%r）"
                             % (label, rate, thresholds[key], key,
                                len(missing), missing))

    elif suite == "pcode":
        expected = extra["expected"]
        observed = extra["observed"]
        field_hit = 0
        field_total = 0
        status_hit = 0
        missing_fields = []
        missing_status = []
        for pcode in sorted(expected):
            exp = expected[pcode]
            obs = observed.get(pcode)
            for field in ("agency_code", "year", "serial"):
                field_total += 1
                if obs is not None and exp.get(field) == obs.get(field):
                    field_hit += 1
                else:
                    missing_fields.append("%s.%s" % (pcode, field))
            if obs is not None and exp.get("status") == obs.get("status"):
                status_hit += 1
            else:
                missing_status.append(pcode)
        field_rate = (field_hit / float(field_total)) if field_total else 1.0
        status_rate = (status_hit / float(len(expected))) if expected else 1.0
        if field_rate < thresholds["pcode_field_accuracy"]:
            ok = False
            lines.append("检出门未达：文号字段命中率 %.4f < 门槛 %s（缺 %d 处：%r）"
                         % (field_rate, thresholds["pcode_field_accuracy"],
                            len(missing_fields), missing_fields))
        if status_rate < thresholds["pcode_status_accuracy"]:
            ok = False
            lines.append("检出门未达：文号三态命中率 %.4f < 门槛 %s（缺 %d 条：%r）"
                         % (status_rate, thresholds["pcode_status_accuracy"],
                            len(missing_status), missing_status))

    elif suite == "subscribe":
        exp_hits = truth["expect"]["hits"]
        obs_hits = extra["observed"]["hits"]
        exp_excluded = [e["item_id"] for e in truth["expect"]["excluded"]]
        obs_excluded = set(e["item_id"] for e in extra["observed"]["excluded"])
        hit_keys = set((h["item_id"], h["keyword"]) for h in obs_hits)
        recall = _accuracy_hit([(h["item_id"], h["keyword"]) for h in exp_hits],
                               hit_keys)
        if recall < thresholds["subscribe_hit_recall"]:
            ok = False
            missing = ["%s|%s" % k for k in
                       [(h["item_id"], h["keyword"]) for h in exp_hits]
                       if k not in hit_keys]
            lines.append("检出门未达：命中召回 %.4f < 门槛 %s（缺 %d 条：%r）"
                         % (recall, thresholds["subscribe_hit_recall"],
                            len(missing), missing))
        # 精确率：观测命中数（逐键）相对真值命中数的膨胀率必须为 0 多余。
        exp_keys = set((h["item_id"], h["keyword"]) for h in exp_hits)
        extra_hits = ["%s|%s" % k for k in sorted(hit_keys - exp_keys)]
        precision = 1.0 if not hit_keys else \
            (len(exp_keys & hit_keys) / float(len(hit_keys)))
        if precision < thresholds["subscribe_hit_precision"]:
            ok = False
            lines.append("检出门未达：命中精确率 %.4f < 门槛 %s（多余 %d 条：%r）"
                         % (precision, thresholds["subscribe_hit_precision"],
                            len(extra_hits), extra_hits))
        exclude_recall = _accuracy_hit(exp_excluded, obs_excluded)
        if exclude_recall < thresholds["subscribe_exclude_recall"]:
            ok = False
            missing = [i for i in exp_excluded if i not in obs_excluded]
            lines.append("检出门未达：剔除召回 %.4f < 门槛 %s（缺 %d 条：%r）"
                         % (exclude_recall, thresholds["subscribe_exclude_recall"],
                            len(missing), missing))

    return ok, lines


# ===========================================================================
# CLI：`bench` 子命令（退出码三语义：0 达标 / 1 未达标 / 2 用法错误）
# ===========================================================================

def cmd_bench(args):
    """`bench`：三套件一键跑通（生产实现实算 → 共用对账语义 → 门槛判定）。

    - `--only <suite>`：只跑指定套件（不认识的名字 = exit 2）；
    - 门槛随数据下发（K17）：`data/truth/manifest.json` 的 `thresholds`，
      与 `verify-data` 同源装载；缺失任一需要的键即 exit 2（代码零默认值）；
    - 退出码：0 达标 / 1 未达标（逐条点名）/ 2 用法错误。
    """
    data_root = find_data_root(getattr(args, "data_root", None))
    if not data_root:
        sys.stderr.write("bench: 找不到数据根（显式传 --data-root 或设 "
                         "POLICY_RADAR_DATA）\n")
        return EXIT_USAGE

    only = getattr(args, "only", None)
    if only is not None and only not in TRUTH_FILE_BY_SUITE:
        sys.stderr.write("bench: --only 只认 %s（收到 %r）\n"
                         % ("/".join(sorted(TRUTH_FILE_BY_SUITE)), only))
        return EXIT_USAGE

    # 门槛随数据下发（K17，同源 verify._load_thresholds；缺失即 exit 2）。
    try:
        thresholds = _load_thresholds(data_root)
        missing_keys = [key for key in REQUIRED_THRESHOLDS
                        if key not in thresholds]
        if missing_keys:
            raise UsageError("真值 manifest 的 thresholds 缺少门槛键（代码零默认值）：%r"
                             % missing_keys)
    except UsageError as exc:
        sys.stderr.write("bench: %s\n" % exc)
        return EXIT_USAGE

    suites = [s for s in SUITES if only is None or s[0] == only]
    failures = []
    total_compared = 0
    for suite, func in suites:
        try:
            truth = _load_truth(data_root, suite)
            compare, meta, extra = func(data_root, truth)
        except UsageError as exc:
            sys.stderr.write("bench: %s\n" % exc)
            return EXIT_USAGE
        total_compared += meta["compared"]
        gates_ok, gate_lines = evaluate_gates(suite, compare, extra, truth,
                                              thresholds)
        status = "OK" if (compare["ok"] and gates_ok) else "FAIL"
        sys.stdout.write("  [%s] %-9s 语料 %-4d 比对 %-4d 条\n"
                         % (status, suite, meta["corpus"], meta["compared"]))
        if not compare["ok"] or not gates_ok:
            failures.append((suite, compare, gate_lines))

    if failures:
        for suite, compare, gate_lines in failures:
            for line in describe_failures(suite, compare):
                sys.stdout.write("        %s\n" % line)
            for line in gate_lines:
                sys.stdout.write("        %s\n" % line)
        sys.stdout.write("bench: %d/%d 套件未达标（比对 %d 条）\n"
                         % (len(failures), len(suites), total_compared))
        return EXIT_DEGRADED

    sys.stdout.write("  门槛（随数据下发）：%s\n"
                     % ", ".join(sorted(k for k in thresholds if k != "note")))
    sys.stdout.write("bench: %d 套件全部达标（比对 %d 条），生产实现对真值逐条一致\n"
                     % (len(suites), total_compared))
    return EXIT_OK


def describe_failures(suite, compare):
    """把对账差异翻译成人读行（**逐条点名**）——复用 verify 的同一套翻译。"""
    from .verify import _describe_failures
    return _describe_failures(suite, compare)
