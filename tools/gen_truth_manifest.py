#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真值台账总清单生成器（M1）：`data/truth/manifest.json`。

用法::

    py -3.8 -X utf8 tools/gen_truth_manifest.py
    py -3.8 -X utf8 tools/gen_truth_manifest.py --check

## 本文件解决两个"假覆盖"失效形态（skill 纪律）

1. **只写分子 = 假覆盖**：只声明"各有覆盖件"而不登记
   **"规则包总数 / 真值库采样数 / 采样清单"**，读者无法判断覆盖到什么程度。
   本清单逐形态三登记，并**显式声明"抽样覆盖、非穷举"**。

2. **门槛内联进代码 = 抄进代码的第二份真相**：验收门槛（准确率/覆盖率阈值）
   **随数据下发**——落在本清单里，基准层**只读**，缺失即报配置错误（exit 2），
   **不得回落代码里的默认值**。这样"改门槛"只需改数据文件，不会出现
   "代码里一套、文档里一套"。
"""

import argparse
import io
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _genlib as G  # noqa: E402

from policy_radar.serialize import read_json, write_json  # noqa: E402

#: 三份真值台账 + 快照清单的文件名（相对 data/）。
TRUTH_FILES = ("diff-truth.json", "pcode-truth.json", "subscribe-truth.json")
SNAPSHOT_MANIFEST = os.path.join("snapshots", "manifest.json")

#: 验收门槛（**随数据下发，代码零默认值**）。首期口径：确定性规则 + 逐条对账，
#: 故判定类门槛一律 1.0（准确率 100%），解析类门槛按实测覆盖率定。
THRESHOLDS = {
    "diff_new_accuracy": 1.0,
    "diff_dup_accuracy": 1.0,
    "pcode_status_accuracy": 1.0,
    "pcode_field_accuracy": 1.0,
    "subscribe_hit_precision": 1.0,
    "subscribe_hit_recall": 1.0,
    "subscribe_exclude_recall": 1.0,
    "note": "首期基准门槛：确定性规则 + 真值逐条对账 → 判定类准确率必须 100%。"
            "**基准层只读本清单；缺失即报配置错误 exit 2；不得回落代码默认值。**",
}


def _rel(data_root, *parts):
    return G.relative_posix(os.path.join(data_root, *parts), data_root)


def build_manifest(data_root):
    """读三份真值台账 + 快照清单，汇总覆盖声明与门槛。"""
    truth = {}
    for name in TRUTH_FILES:
        truth[name] = read_json(os.path.join(data_root, "truth", name))
    snap_manifest = read_json(os.path.join(data_root, SNAPSHOT_MANIFEST))

    diff = truth["diff-truth.json"]
    pcode = truth["pcode-truth.json"]
    sub = truth["subscribe-truth.json"]

    # --- 覆盖声明：逐形态"总数 / 采样数 / 采样清单"三登记 -------------------
    diff_roles = diff["role_counts"]
    coverage_diff = {
        "case": "diff-truth.json",
        "rule_package": "K4 双键判定（id 主键 / pcode 非空并入）",
        "declared_shapes": ["carried", "fresh", "pcode_dup",
                            "empty_pcode_new", "empty_pcode_same"],
        "sampled_shapes": sorted(diff_roles),
        "shape_sample_counts": dict((k, diff_roles[k]) for k in sorted(diff_roles)),
        "sampled_total": diff["expect"]["new_count"] + diff["expect"]["dup_count"],
        "sampling_list": {
            "new_ids": diff["expect"]["new_ids"],
            "dup_ids": diff["expect"]["dup_ids"],
            "matched_by": diff["expect"]["matched_by"],
        },
        "sampling_note": "预置快照对 A(20)/B(21)，取自真实观测池 60 条；**抽样覆盖、非穷举**",
    }

    pcode_forms = pcode["coverage"]["form_counts"]
    coverage_pcode = {
        "case": "pcode-truth.json",
        "rule_package": "K6 文号三态解析（代字/年份/序号，代字不做白名单硬编码）",
        "declared_shapes": ["std_bracket", "fullwidth_bracket",
                            "std_bracket_spaced_serial", "decree_no_bracket", "empty"],
        "sampled_shapes": sorted(pcode_forms),
        "shape_sample_counts": dict((k, pcode_forms[k]) for k in sorted(pcode_forms)),
        "sampled_total": (pcode["coverage"]["hand_annotated_cases"]
                          + pcode["coverage"]["pool_corpus_cases"]),
        "hand_annotated_cases": [c["pcode"] for c in pcode["cases"]],
        "reverse_samples": ["国令第847号（不得解析出年份）", "空 pcode（不得解析出代字）"],
        "sampling_note": "人工标注 11 条 + 观测池语料 57 条真实文号；**抽样覆盖、非穷举**",
    }

    sub_shapes = sub["coverage"]["boundary_shapes"]
    coverage_sub = {
        "case": "subscribe-truth.json",
        "rule_package": "K8 订阅匹配（子串包含 + 全半角归一 + exclude 整条剔除）",
        "declared_shapes": ["multi_keyword", "zero_hit", "exclude_only",
                            "exclude_and_include", "duplicate_keyword_dedup",
                            "normalized_fullwidth"],
        "sampled_shapes": sorted(sub_shapes),
        "shape_sample_counts": dict((k, sub_shapes[k]) for k in sorted(sub_shapes)),
        "sampled_total": sub["coverage"]["corpus_items"],
        "configured_include": sub["coverage"]["include_configured"],
        "configured_exclude": sub["coverage"]["exclude_configured"],
        "sampling_note": "语料 = 预置快照对 B 侧 21 条；**抽样覆盖、非穷举**",
    }

    return {
        "case": "truth-manifest",
        "note": "真值台账总清单（M1）：覆盖声明（总数/采样数/采样清单三登记）"
                "+ 验收门槛（随数据下发，代码零默认值）。",
        "truth_files": dict((name, _rel(data_root, "truth", name))
                            for name in TRUTH_FILES),
        "snapshot_manifest": _rel(data_root, "snapshots", "manifest.json"),
        "coverage": [coverage_diff, coverage_pcode, coverage_sub],
        "coverage_disclaimer": "以上均为**抽样覆盖**（观测池 60 条 / 语料 21 条 / 文号 57 条），"
                               "**非穷举**；未覆盖形态在后续里程碑增量补录。",
        "thresholds": dict(THRESHOLDS),
        "thresholds_policy": "基准层只读；缺失即报配置错误（exit 2）；**不得回落代码默认值**。",
        "snapshot_counts": snap_manifest["counts"],
    }


def generate(data_root, truth_dir):
    manifest = build_manifest(data_root)
    path = os.path.join(truth_dir, "manifest.json")
    write_json(path, manifest)
    return path, manifest


def check(data_root, truth_dir):
    """两层守门：形态正确（三份真值齐备 + 无 observed 字段）+ 重跑逐字节一致。"""
    failures = []
    path = os.path.join(truth_dir, "manifest.json")
    if not os.path.isfile(path):
        failures.append("冻结产物缺失：%s" % G.relative_posix(path, data_root))
    for name in TRUTH_FILES:
        if not os.path.isfile(os.path.join(data_root, "truth", name)):
            failures.append("真值台账缺失：%s" % name)

    if not failures:
        manifest = read_json(path)
        # 第一层：每形态都有采样数，且**采样清单非空**（防"声明了形态但没样本"）。
        for cov in manifest["coverage"]:
            for shape in cov["declared_shapes"]:
                if cov["shape_sample_counts"].get(shape, 0) < 1:
                    failures.append("%s 的形态 %s 采样数为 0"
                                    % (cov["case"], shape))
            if not cov["sampled_shapes"]:
                failures.append("%s 无采样清单" % cov["case"])
        if not manifest["thresholds"]:
            failures.append("门槛缺失")
        G.assert_no_observed_fields(manifest, "truth-manifest")

        # 第二层：重跑逐字节比对。
        tmp = tempfile.mkdtemp(prefix="policy-radar-tmcheck-")
        try:
            tmp_truth = os.path.join(tmp, "truth")
            os.makedirs(tmp_truth)
            fresh_path, _ = generate(data_root, tmp_truth)
            with io.open(fresh_path, "rb") as f1, io.open(path, "rb") as f2:
                if f1.read() != f2.read():
                    failures.append("重跑与冻结产物字节不一致：manifest.json")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            sys.stderr.write("  [FAIL] %s\n" % f)
        return 1
    manifest = read_json(path)
    sys.stdout.write("  [OK] 第一层：三份真值齐备，逐形态采样数非零，门槛就位\n")
    sys.stdout.write("  [OK] 第二层：重跑生成器与冻结产物逐字节一致（1 份产物）\n")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="真值台账总清单生成器（M1）")
    parser.add_argument("--root", default=G._ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    data_root = os.path.join(args.root, "data")
    truth_dir = os.path.join(data_root, "truth")
    if not os.path.isdir(truth_dir):
        sys.stderr.write("目录不存在：%s\n" % truth_dir)
        return 2

    if args.check:
        return check(data_root, truth_dir)

    try:
        path, manifest = generate(data_root, truth_dir)
    except (AssertionError, KeyError, ValueError) as exc:
        sys.stderr.write("生成失败（未写盘）：%s\n" % exc)
        return 1

    sys.stdout.write("  写入 %s\n" % G.relative_posix(path, args.root))
    for cov in manifest["coverage"]:
        sys.stdout.write("  %-22s 形态 %d 个 / 采样 %d 条\n"
                         % (cov["case"], len(cov["declared_shapes"]),
                            cov["sampled_total"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
