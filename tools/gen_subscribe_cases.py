#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""订阅命中真值 + 订阅配置 + 归一表生成器（M1）。

产出三份：`data/config/subscribe.json`、`data/config/normalize.json`、
`data/truth/subscribe-truth.json`。

用法::

    py -3.8 -X utf8 tools/gen_subscribe_cases.py
    py -3.8 -X utf8 tools/gen_subscribe_cases.py --check

## 真值独立性（skill 核心纪律）

命中真值由本文件内**独立朴素 oracle**（`naive_match()`）算出，不 import 生产
订阅实现（M4 才落地）。oracle 只用"归一化 + `str.find`"，与生产实现（大概率用
`re` 或切片）走不同代码路径。

## 覆盖形态（plan/05 §3.3 三类边界 + 归一化）

| 形态 | 样本 | 说明 |
|---|---|---|
| 多词命中 | 一条目命中多个 include 词 | 每词一条命中记录 |
| **命中 0 次** | 既无 include 也无 exclude 命中 | 不得凭空产生命中 |
| **只命中 exclude** | 只命中 exclude、无 include 命中 | 整条剔除，且可回溯"确实只中了 exclude" |
| **命中 include 但也中 exclude** | 两样都中 | exclude 优先：整条剔除（不是"不标注"） |
| **同词重复配置** | include 里同词出现两次 | 去重后只产生**一条**命中记录 |
| **全半角归一** | 关键词用 ASCII 引号，正文是全角引号 | 不归一则该条**漏命中** |

## 归一化表设计决策：**长度保持（length-preserving）**

归一表的每条映射都是"单字符 → 单字符"。这不是凑巧，是**刻意的设计约束**：
长度保持使"命中位置 `offset`"在归一前后同值，因而 `offset` 语义唯一、可审计——
否则归一化会移位，真值里的 offset 就成了"哪一份文本的下标"的糊涂账。
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

from policy_radar.cases import (  # noqa: E402
    FIELD_PRIORITY, dedup_keywords, naive_match, normalize_text,
)
from policy_radar.serialize import read_json, write_json  # noqa: E402

#: 订阅配置（含多词 / 排除词 / **重复词**）。
#: 关键词全部取自观测池真实文本（`data/samples/*-n30.json`），不凭空造业务词。
INCLUDE_KEYWORDS = (
    "规划",
    "十五五",
    "\"\u5341\u4e94\u4e94\"",   # ASCII 引号关键词 -> 测全半角归一（正文是全角引号）
    "电商",
    "保险",
    "碳排放",                     # 观测池命中 0 次 -> 供"命中 0 次"边界
    "规划",                       # **同词重复配置** -> 去重后只应产生一条记录
)

EXCLUDE_KEYWORDS = (
    "复函",   # 命中 26475541（该条也命中 include「十五五」）-> "两样都中"边界
    "条例",   # 命中 26598004 / 26437655（两条例都不含任何 include 词）-> "只命中 exclude"
)

#: 归一表（K8 单一来源）：**单字符 → 单字符**（长度保持，见模块 docstring）。
#: 每条都有实测依据，不是凭空补的通用表。
NORMALIZE_MAP = {
    # 全角括号 -> 半角（用户可能按半角输入）
    "\uff08": "(",
    "\uff09": ")",
    # 全角弯引号 -> ASCII 直引号（**实测正文用 `“十五五”`**，用户常按 ASCII 引号搜）
    "\u201c": "\"",
    "\u201d": "\"",
    # 全角单引号 -> ASCII 单引号
    "\u2018": "'",
    "\u2019": "'",
    # 全角六角括号变体 -> 标准六角括号（**M1 实测 E6**：`﹝﹞`=U+FE5D/FE5E）
    "\ufe5d": "\u3014",
    "\ufe5e": "\u3015",
    # 非常规空白 -> 半角空格（**M1 实测 E5**：实测出现 U+2002 EN SPACE）
    "\u3000": " ",
    "\u2002": " ",
    "\u00a0": " ",
}

#: 未命中/边界角色标签。
ROLE_MULTI = "multi_keyword"
ROLE_ZERO = "zero_hit"
ROLE_EXCLUDE_ONLY = "exclude_only"
ROLE_EXCLUDE_AND_INCLUDE = "exclude_and_include"
ROLE_DUP_KEYWORD = "duplicate_keyword_dedup"
ROLE_NORMALIZED = "normalized_fullwidth"


# --- 独立朴素 oracle ---------------------------------------------------------

#: 参照实现从 `policy_radar.cases` 引入（**单一实现源**：生成器、守门测试、
#: `verify-data` 命令共用同一份，避免三处各写一份而互相漂移）。
#: 该模块由 `tests/test_cases_independence.py` 守门：生产模块不得 import 它。
#:
#: **独立性说明**：oracle 只用"归一化 + `str.find`"，与生产实现（M4 `subscribe.py`，
#: 大概率用正则）走不同代码路径——"把生产实现注释掉，真值仍可算出"。
normalize_text = normalize_text
dedup_keywords = dedup_keywords
naive_match = naive_match


# --- 生成守卫 ---------------------------------------------------------------

def assert_norm_map_is_length_preserving(norm_map):
    """归一表必须长度保持（`offset` 语义唯一的前提，见模块 docstring）。"""
    for src, dst in sorted(norm_map.items()):
        if len(src) != 1 or len(dst) != 1:
            raise AssertionError("归一表非单字符映射：%r -> %r" % (src, dst))


def assert_cases_present(hits, excluded, zero, include, norm_map):
    """三类边界样本 + 归一化 + 重复词去重必须真存在（防"声称覆盖但没样本"）。"""
    # ① 同词重复配置：配置里确有重复，且去重后条数变少。
    if len(include) == len(dedup_keywords(include, norm_map)):
        raise AssertionError("订阅配置未含重复词（无法验证去重）")
    # ② 命中 0 次样本。
    if not zero:
        raise AssertionError("无「命中 0 次」样本")
    # ③ 只命中 exclude 样本（有 exclude 命中、无 include 命中）。
    exclude_only = [e for e in excluded if not e["include_matched_before_exclusion"]]
    if not exclude_only:
        raise AssertionError("无「只命中 exclude」样本")
    # ④ 命中 include 但也中 exclude（exclude 优先）样本。
    both = [e for e in excluded if e["include_matched_before_exclusion"]]
    if not both:
        raise AssertionError("无「命中 include 但也中 exclude」样本")
    # ⑤ 多词命中：某条目命中 ≥2 个 include 词。
    by_item = {}
    for h in hits:
        by_item.setdefault(h["item_id"], []).append(h["keyword"])
    multi = [i for i, ks in by_item.items() if len(ks) >= 2]
    if not multi:
        raise AssertionError("无「一条目命中多词」样本")
    # ⑥ 阳性对照：include 必须真命中 >0 条（防"永远不命中"的假门）。
    if not hits:
        raise AssertionError("include 命中 0 条：关键词集或匹配规则写错了")
    # ⑦ 归一化样本：ASCII 引号关键词必须命中全角引号正文。
    norm_kw = [k for k in include if '"' in k]
    if not norm_kw:
        raise AssertionError("配置里无 ASCII 引号关键词，无法验证全半角归一")
    norm_hits = [h for h in hits if h["keyword"] in norm_kw]
    if not norm_hits:
        raise AssertionError("ASCII 引号关键词未命中任何条目：全半角归一未生效")
    # ⑧ 重复词去重：去重后的关键词不得在命中记录里出现两次同条目同词。
    pairs = [(h["item_id"], h["keyword"]) for h in hits]
    if len(pairs) != len(set(pairs)):
        raise AssertionError("命中记录出现重复 (item, keyword)：去重失效")
    # ⑨ 归一化表非空自证。
    if not norm_map:
        raise AssertionError("归一表为空")


def assert_no_overlap(hits, excluded, zero):
    """三类结论不得互相重叠（同一条目既被剔除又产生命中 = 逻辑矛盾）。"""
    hit_ids = set(h["item_id"] for h in hits)
    exc_ids = set(e["item_id"] for e in excluded)
    zero_ids = set(zero)
    if hit_ids & exc_ids:
        raise AssertionError("有条目既产生命中又被剔除：%r" % sorted(hit_ids & exc_ids))
    if hit_ids & zero_ids:
        raise AssertionError("有条目既产生命中又算 0 命中：%r" % sorted(hit_ids & zero_ids))
    if exc_ids & zero_ids:
        raise AssertionError("有条目既被剔除又算 0 命中：%r" % sorted(exc_ids & zero_ids))


# --- 产物 ------------------------------------------------------------------

def build_configs():
    """订阅配置 + 归一表（两者都是"规则数据"，入 `data/config/`）。"""
    subscribe = {
        "note": "订阅配置样例（M1）：含多关键词、排除词、重复词三类边界样本；"
                "关键词取自观测池真实文本，不预置业务热词（决策 P4 按推荐默认执行）。",
        "include": list(INCLUDE_KEYWORDS),
        "exclude": list(EXCLUDE_KEYWORDS),
        "match_rule": "substring_containment_after_normalization",
        "dedup_rule": "dedup_by_normalized_keyword_preserve_config_order",
        "field_priority": list(FIELD_PRIORITY),
        "exclude_policy": "drop_item_entirely",
    }
    normalize = {
        "note": "全半角/异体字归一表（K8 单一来源）：**每条映射都是单字符 → 单字符**"
                "（长度保持），使命中位置 offset 在归一前后同值。",
        "source": "M1 实测：正文用全角引号“”，全角括号（），六角括号存在全角变体﹝﹞，"
                  "空白出现 U+2002 EN SPACE",
        "apply_to": "both_keyword_and_text",
        "map": dict((k, NORMALIZE_MAP[k]) for k in sorted(NORMALIZE_MAP)),
    }
    return subscribe, normalize


def build_truth(items, subscribe, normalize, data_root):
    """构造 `subscribe-truth.json`（只存输入与期望，K11：无 `observed_*`）。"""
    include = subscribe["include"]
    exclude = subscribe["exclude"]
    norm_map = normalize["map"]

    hits, excluded, zero = naive_match(items, include, exclude, norm_map)
    assert_norm_map_is_length_preserving(norm_map)
    assert_cases_present(hits, excluded, zero, include, norm_map)
    assert_no_overlap(hits, excluded, zero)

    # 条目在输入里的规范序（K5）+ 关键词的**去重后**配置序（同词重复只占一个位次）。
    # 用 `dedup_keywords` 的结果（而非原始 include 列表）排关键词：原始列表里
    # 重复词占两个位次，会让"同一词在不同条目上的相对次序"随列表内容漂移。
    ordered_ids = [it.id for it in items]
    keyword_order = dedup_keywords(include, norm_map)
    hits_sorted = sorted(hits, key=lambda h: (ordered_ids.index(h["item_id"]),
                                              keyword_order.index(h["keyword"])))
    excluded_sorted = sorted(excluded, key=lambda e: ordered_ids.index(e["item_id"]))
    zero_sorted = sorted(zero, key=lambda i: ordered_ids.index(i))

    truth = {
        "case": "subscribe-hits",
        "case_kind": "keyword-subscription",
        "input": {
            "config": G.relative_posix(
                os.path.join(data_root, "config", "subscribe.json"), data_root),
            "normalize": G.relative_posix(
                os.path.join(data_root, "config", "normalize.json"), data_root),
            "corpus": G.relative_posix(
                os.path.join(data_root, "snapshots", "pair-B.json"), data_root),
            "corpus_size": len(items),
        },
        "semantics": {
            "match": "归一化后子串包含（title 优先，其次 summary）",
            "field_priority": list(FIELD_PRIORITY),
            "offset": "命中词在**原始字段文本**中的起始下标（归一表长度保持，故与归一后同值）",
            "dedup": "同词重复配置按归一后关键词去重，保持配置顺序",
            "exclude": "任一 exclude 命中即整条剔除（不产命中记录）",
        },
        "expect": {
            "hits": hits_sorted,
            "hit_count": len(hits_sorted),
            "excluded": excluded_sorted,
            "excluded_count": len(excluded_sorted),
            "zero_hit_item_ids": zero_sorted,
            "zero_hit_count": len(zero_sorted),
            "matched_item_count": len(set(h["item_id"] for h in hits_sorted)),
        },
        "also_expect": {
            "hit_items_never_excluded": not (
                set(h["item_id"] for h in hits_sorted)
                & set(e["item_id"] for e in excluded_sorted)),
            "zero_hit_items_have_no_include_match": all(
                i not in set(h["item_id"] for h in hits_sorted) for i in zero_sorted),
            "exclude_only_sample_present": any(
                not e["include_matched_before_exclusion"] for e in excluded_sorted),
            "exclude_and_include_sample_present": any(
                e["include_matched_before_exclusion"] for e in excluded_sorted),
            "duplicate_config_deduped": len(include) > len(
                dedup_keywords(include, norm_map)),
            "normalized_fullwidth_sample_present": any(
                '"' in h["keyword"] for h in hits_sorted),
        },
        "coverage": {
            "include_configured": len(include),
            "include_after_dedup": len(dedup_keywords(include, norm_map)),
            "exclude_configured": len(exclude),
            "exclude_after_dedup": len(dedup_keywords(exclude, norm_map)),
            "corpus_items": len(items),
            "boundary_shapes": {
                ROLE_MULTI: len([i for i, ks in _by_item(hits_sorted).items()
                                 if len(ks) >= 2]),
                ROLE_ZERO: len(zero_sorted),
                ROLE_EXCLUDE_ONLY: len([e for e in excluded_sorted
                                        if not e["include_matched_before_exclusion"]]),
                ROLE_EXCLUDE_AND_INCLUDE: len([e for e in excluded_sorted
                                               if e["include_matched_before_exclusion"]]),
                ROLE_DUP_KEYWORD: len(include) - len(dedup_keywords(include, norm_map)),
                ROLE_NORMALIZED: len([h for h in hits_sorted if '"' in h["keyword"]]),
            },
            "sampling_note": "语料 = 预置快照对 B 侧（21 条，取自真实观测池）；"
                             "**抽样覆盖、非穷举**",
        },
    }
    G.assert_no_observed_fields(truth, "subscribe-truth")
    return truth


def _by_item(hits):
    out = {}
    for h in hits:
        out.setdefault(h["item_id"], []).append(h["keyword"])
    return out


# --- 主流程 ----------------------------------------------------------------

def generate(data_root, truth_dir, config_dir):
    items = G.load_snapshot(os.path.join(data_root, "snapshots", "pair-B.json"))
    subscribe, normalize = build_configs()
    truth = build_truth(items, subscribe, normalize, data_root)

    paths = []
    path_s = os.path.join(config_dir, "subscribe.json")
    path_n = os.path.join(config_dir, "normalize.json")
    path_t = os.path.join(truth_dir, "subscribe-truth.json")
    write_json(path_s, subscribe)
    write_json(path_n, normalize)
    write_json(path_t, truth)
    paths += [path_s, path_n, path_t]
    return paths, truth


def check(data_root, truth_dir, config_dir):
    """两层守门：形态正确（边界样本齐备）+ 重跑逐字节一致。"""
    failures = []
    path_s = os.path.join(config_dir, "subscribe.json")
    path_n = os.path.join(config_dir, "normalize.json")
    path_t = os.path.join(truth_dir, "subscribe-truth.json")
    for path in (path_s, path_n, path_t):
        if not os.path.isfile(path):
            failures.append("冻结产物缺失：%s" % G.relative_posix(path, data_root))

    if not failures:
        # 第一层：边界形态齐备 + 结论互不重叠 + 阳性对照。
        truth = read_json(path_t)
        shapes = truth["coverage"]["boundary_shapes"]
        for needed in (ROLE_MULTI, ROLE_ZERO, ROLE_EXCLUDE_ONLY,
                       ROLE_EXCLUDE_AND_INCLUDE, ROLE_DUP_KEYWORD, ROLE_NORMALIZED):
            if not shapes.get(needed):
                failures.append("边界形态 %s 无样本" % needed)
        if not truth["expect"]["hit_count"]:
            failures.append("命中数为 0（阳性对照失败）")
        for key in ("hit_items_never_excluded", "zero_hit_items_have_no_include_match"):
            if not truth["also_expect"].get(key):
                failures.append("also_expect.%s 不成立" % key)

        # 第二层：重跑逐字节比对。
        tmp = tempfile.mkdtemp(prefix="policy-radar-subcheck-")
        try:
            tmp_truth = os.path.join(tmp, "truth")
            tmp_config = os.path.join(tmp, "config")
            os.makedirs(tmp_truth)
            os.makedirs(tmp_config)
            generate(data_root, tmp_truth, tmp_config)
            pairs = (
                (os.path.join(tmp_config, "subscribe.json"), path_s),
                (os.path.join(tmp_config, "normalize.json"), path_n),
                (os.path.join(tmp_truth, "subscribe-truth.json"), path_t),
            )
            for fresh_path, frozen_path in pairs:
                with io.open(fresh_path, "rb") as f1, \
                        io.open(frozen_path, "rb") as f2:
                    if f1.read() != f2.read():
                        failures.append("重跑与冻结产物字节不一致：%s"
                                        % os.path.basename(frozen_path))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            sys.stderr.write("  [FAIL] %s\n" % f)
        return 1
    truth = read_json(path_t)
    sys.stdout.write("  [OK] 第一层：边界形态齐备（%r）\n"
                     % truth["coverage"]["boundary_shapes"])
    sys.stdout.write("  [OK] 第二层：重跑生成器与冻结产物逐字节一致（3 份产物）\n")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="订阅命中真值生成器（M1）")
    parser.add_argument("--root", default=G._ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    data_root = os.path.join(args.root, "data")
    truth_dir = os.path.join(data_root, "truth")
    config_dir = os.path.join(data_root, "config")
    for d in (truth_dir, config_dir, os.path.join(data_root, "snapshots")):
        if not os.path.isdir(d):
            sys.stderr.write("目录不存在：%s\n" % d)
            return 2

    if args.check:
        return check(data_root, truth_dir, config_dir)

    try:
        paths, truth = generate(data_root, truth_dir, config_dir)
    except AssertionError as exc:
        sys.stderr.write("生成守卫拦截（未写盘）：%s\n" % exc)
        return 1

    for path in paths:
        sys.stdout.write("  写入 %s\n" % G.relative_posix(path, args.root))
    sys.stdout.write("  命中 %d 条（覆盖 %d 个条目）/ 剔除 %d 条 / 0 命中 %d 条；边界 %r\n"
                     % (truth["expect"]["hit_count"],
                        truth["expect"]["matched_item_count"],
                        truth["expect"]["excluded_count"],
                        truth["expect"]["zero_hit_count"],
                        truth["coverage"]["boundary_shapes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
