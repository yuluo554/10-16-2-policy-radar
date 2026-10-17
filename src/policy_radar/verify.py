"""数据自审：真值台账一致性核对（`policy-radar verify-data`）。

**这是真值台账的"真调用方"**（skill 三问之③）：用户敲的这条命令**真读**真值库，
并在运行时**实算**观测——不是"文件存在"、也不是只在测试里被读。

它做的事：把 `data/truth/` 的**输入**喂给参照实现（`cases.py` 的 oracle）**实算**一遍，
再用**共用对账语义**（`cases.compare_*`）与真值库里的**期望**逐条比对。因此它能抓住：

- 真值库被手改坏（期望与输入不再自洽）→ 报差异并点名哪几条；
- 输入数据被改动而真值未同步 → 同上；
- 真值库出现 `observed_*` 字段（K11 违规）→ 直接报错；
- 门槛缺失（`manifest.json` 无 thresholds）→ 报配置错误 exit 2，**不回落代码默认值**。

**它不做的事**：不跑生产实现（那是 M4 `bench` 的事）。本命令只核"真值库自身是否自洽"，
即"期望可由输入独立复算"这一条的**运行时证据**。

退出码：0 = 真值库自洽且门槛齐备；1 = 有差异/有 K11 违规；2 = 用法错误（缺文件/坏格式/门槛缺失）。
"""

import json
import os
import sys

from .cases import (
    assert_no_observed_fields,
    compare_diff,
    compare_pcode,
    compare_subscribe,
    naive_diff,
    naive_match,
    naive_parse_pcode,
)
from .errors import EXIT_OK, EXIT_DEGRADED, EXIT_USAGE, UsageError
from .model import PolicyItem
from .paths import find_data_root
from .serialize import read_json

#: 真值台账文件名。
TRUTH_DIFF = "diff-truth.json"
TRUTH_PCODE = "pcode-truth.json"
TRUTH_SUBSCRIBE = "subscribe-truth.json"
TRUTH_MANIFEST = "manifest.json"

#: 本命令覆盖的真值语义（供自证"非空转"）。
EXPECTED_TRUTH_FILES = (TRUTH_DIFF, TRUTH_PCODE, TRUTH_SUBSCRIBE, TRUTH_MANIFEST)


def _load(data_root, *parts):
    """读数据文件；缺失或坏格式抛 `UsageError`（→ exit 2）。"""
    path = os.path.join(data_root, *parts)
    if not os.path.isfile(path):
        raise UsageError("数据文件缺失：%s" % path)
    try:
        return read_json(path)
    except ValueError as exc:
        raise UsageError(str(exc))


def _items_from_snapshot(data_root, rel_path):
    """按真值里登记的**相对数据根路径**读快照，返回 PolicyItem 列表。"""
    path = os.path.join(data_root, rel_path.replace("/", os.sep))
    if not os.path.isfile(path):
        raise UsageError("快照文件缺失（真值登记为 %s）" % rel_path)
    obj = read_json(path)
    items = obj.get("items")
    if not isinstance(items, list):
        raise UsageError("快照缺少 items 列表：%s" % rel_path)
    return [PolicyItem.from_dict(d) for d in items]


def _load_thresholds(data_root):
    """读验收门槛（**随数据下发**）。缺失即报配置错误，**不回落代码默认值**。"""
    manifest = _load(data_root, "truth", TRUTH_MANIFEST)
    thresholds = manifest.get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds:
        raise UsageError(
            "真值 manifest 缺少 thresholds（门槛须随数据下发，代码零默认值）：%s"
            % os.path.join(data_root, "truth", TRUTH_MANIFEST))
    return thresholds


def check_diff(data_root, truth):
    """实算 diff 观测并与真值对账。返回 `(compare_result, 元信息)`。"""
    items_a = _items_from_snapshot(data_root, truth["input"]["snapshot_a"])
    items_b = _items_from_snapshot(data_root, truth["input"]["snapshot_b"])
    new_ids, dup_ids, matched_by = naive_diff(
        [it.to_dict() for it in items_a], [it.to_dict() for it in items_b])
    observed = {"new_ids": new_ids, "dup_ids": dup_ids, "matched_by": matched_by}
    result = compare_diff(observed, truth["expect"])
    meta = {
        "case": "diff",
        "corpus": len(items_a) + len(items_b),
        "observed_new": len(new_ids),
        "observed_dup": len(dup_ids),
        "expected_new": truth["expect"]["new_count"],
        "expected_dup": truth["expect"]["dup_count"],
        "compared": len(new_ids) + len(dup_ids),
    }
    return result, meta


def check_pcode(data_root, truth):
    """实算文号解析观测并与真值对账（人工标注用例 + 观测池语料）。"""
    expected = {}
    for case in truth["cases"]:
        expected[case["pcode"]] = case["expect"]
    for case in truth.get("pool_corpus_cases", []):
        expected.setdefault(case["pcode"], case["expect"])

    observed = dict((pcode, naive_parse_pcode(pcode)) for pcode in expected)
    result = compare_pcode(observed, expected)
    meta = {
        "case": "pcode",
        "corpus": len(expected),
        "hand_annotated": truth["coverage"]["hand_annotated_cases"],
        "pool_corpus": truth["coverage"]["pool_corpus_cases"],
        "observed_new": 0,
        "observed_dup": 0,
        "expected_new": 0,
        "expected_dup": 0,
        "compared": len(expected),
    }
    return result, meta


def check_subscribe(data_root, truth):
    """实算订阅命中观测并与真值对账。"""
    items = _items_from_snapshot(data_root, truth["input"]["corpus"])
    subscribe = _load(data_root, "config", "subscribe.json")
    normalize = _load(data_root, "config", "normalize.json")
    norm_map = normalize.get("map") or {}
    if not norm_map:
        raise UsageError("归一表为空：%s" % os.path.join(data_root, "config",
                                                        "normalize.json"))

    hits, excluded, zero = naive_match(items, subscribe["include"],
                                       subscribe["exclude"], norm_map)
    # 按真值口径排序（与生成器一致：语料序 + include 配置序）。
    order = dict((it.id, idx) for idx, it in enumerate(items))
    inc_order = dict((kw, idx) for idx, kw in enumerate(subscribe["include"]))
    hits.sort(key=lambda h: (order.get(h["item_id"], 0),
                             inc_order.get(h["keyword"], 0)))
    excluded.sort(key=lambda e: order.get(e["item_id"], 0))
    zero.sort(key=lambda i: order.get(i, 0))

    observed = {"hits": hits, "excluded": excluded, "zero_hit_item_ids": zero}
    result = compare_subscribe(observed, truth["expect"])
    meta = {
        "case": "subscribe",
        "corpus": len(items),
        "observed_new": len(hits),
        "observed_dup": len(excluded),
        "expected_new": truth["expect"]["hit_count"],
        "expected_dup": truth["expect"]["excluded_count"],
        "compared": len(hits) + len(excluded) + len(zero),
    }
    return result, meta


#: 三个套件：(名称, 真值文件名, 核对函数)。
SUITES = (
    ("diff", TRUTH_DIFF, check_diff),
    ("pcode", TRUTH_PCODE, check_pcode),
    ("subscribe", TRUTH_SUBSCRIBE, check_subscribe),
)


def cmd_verify_data(args):
    """`verify-data`：真值台账一致性核对。"""
    data_root = find_data_root(getattr(args, "data_root", None))
    if not data_root:
        sys.stderr.write("verify-data: 找不到数据根（显式传 --data-root 或设 "
                         "POLICY_RADAR_DATA）\n")
        return EXIT_USAGE

    # 门槛必须齐备（缺失即配置错误，不回落代码默认值）。
    try:
        thresholds = _load_thresholds(data_root)
    except UsageError as exc:
        sys.stderr.write("verify-data: %s\n" % exc)
        return EXIT_USAGE

    # 真值库卫生（K11）：出现 observed 类字段即红。
    observed_violations = []
    for name in EXPECTED_TRUTH_FILES:
        try:
            obj = _load(data_root, "truth", name)
        except UsageError as exc:
            sys.stderr.write("verify-data: %s\n" % exc)
            return EXIT_USAGE
        try:
            assert_no_observed_fields(obj, "truth/%s" % name)
        except AssertionError as exc:
            observed_violations.append(str(exc))

    if observed_violations:
        for violation in observed_violations:
            sys.stdout.write("  [FAIL] K11 违规：%s\n" % violation)
        sys.stdout.write("verify-data: 真值库出现 observed 类字段，判定不通过\n")
        return EXIT_DEGRADED

    total_compared = 0
    failures = []
    for name, filename, func in SUITES:
        try:
            truth = _load(data_root, "truth", filename)
            result, meta = func(data_root, truth)
        except UsageError as exc:
            sys.stderr.write("verify-data: %s\n" % exc)
            return EXIT_USAGE

        total_compared += meta["compared"]
        status = "OK" if result["ok"] else "FAIL"
        sys.stdout.write("  [%s] %-10s 语料 %-4d 比对 %-4d 条\n"
                         % (status, name, meta["corpus"], meta["compared"]))
        if not result["ok"]:
            failures.append((name, result))

    if failures:
        for name, result in failures:
            for line in _describe_failures(name, result):
                sys.stdout.write("        %s\n" % line)
        sys.stdout.write("verify-data: %d/%d 套件不通过（比对 %d 条）\n"
                         % (len(failures), len(SUITES), total_compared))
        return EXIT_DEGRADED

    # 门槛齐备性自证（读到了、非空）。
    sys.stdout.write("  门槛（随数据下发）：%s\n"
                     % ", ".join(sorted(k for k in thresholds
                                        if k != "note")))
    sys.stdout.write("verify-data: %d 套件全部自洽（比对 %d 条），真值库可复算\n"
                     % (len(SUITES), total_compared))
    return EXIT_OK


def _describe_failures(name, result):
    """把对账差异翻译成人读行（**逐条点名**，不只说"不通过"）。"""
    lines = []
    if name == "diff":
        for key in ("new_ids", "dup_ids"):
            diff = result[key]
            if diff["missing"]:
                lines.append("%s 缺少（真值有、实算无）：%r" % (key, diff["missing"]))
            if diff["extra"]:
                lines.append("%s 多出（实算有、真值无）：%r" % (key, diff["extra"]))
        for mismatch in result["matched_by_mismatch"]:
            lines.append("matched_by 判错：%r" % (mismatch,))
    elif name == "pcode":
        for mismatch in result["mismatches"]:
            lines.append("文号 %r 差异：%s" % (mismatch.get("pcode"),
                                            json.dumps(mismatch, ensure_ascii=False)))
    elif name == "subscribe":
        diff = result["hits"]
        if diff["missing"]:
            lines.append("命中缺少：%r" % (diff["missing"],))
        if diff["extra"]:
            lines.append("命中多出：%r" % (diff["extra"],))
        for field_diff in result["hit_field_diffs"]:
            lines.append("命中位置/字段错：%r" % (field_diff,))
        for key in ("excluded_item_ids", "zero_hit_item_ids"):
            d = result[key]
            if d["missing"]:
                lines.append("%s 缺少：%r" % (key, d["missing"]))
            if d["extra"]:
                lines.append("%s 多出：%r" % (key, d["extra"]))
    return lines
