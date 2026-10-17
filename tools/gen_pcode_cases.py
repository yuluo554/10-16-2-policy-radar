#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""文号解析真值 + 部门别名表生成器（M1）：`data/truth/pcode-truth.json` +
`data/config/org-aliases.json`。

用法::

    py -3.8 -X utf8 tools/gen_pcode_cases.py            # 生成
    py -3.8 -X utf8 tools/gen_pcode_cases.py --check    # 位级守门（重跑逐字节比对）

## 真值独立性（skill 核心纪律）

`pcode-truth.json` 的期望**不来自生产解析器**（M3 才落地），有两个来源：

1. **人工标注表**（`CANONICAL_CASES`）：本文件里**逐条手写**的期望结构——覆盖
   实测八形态 + 三类反向样例。这是**人类写的答案**，不是解析器算的。
2. **观测池语料**（57 条真实文号）：期望由本文件内**独立朴素 oracle**（
   `naive_parse_pcode()`，纯位置切片、不用正则）算出。

**生成守卫**：人工标注表与 oracle 必须逐条一致，不一致即拒绝写盘——这样"表里写错"
与"oracle 写错"都会在生成期暴露，而不是在 M3 才变成"真值跟着实现一起错"。

## 反向样例（适用域纪律：只测"该命中"的样例，适用域写错永远不红）

- `国令第847号` → **不得**解析出年份（无 `〔〕`）；
- 空 `pcode` → **不得**解析出代字/年份/序号（全 `未解析`）；
- `工信部联规﹝2026﹞210号` → 全角括号变体，**必须**解析出年份（不得因括号码位不同而漏）。
"""

import argparse
import io
import os
import re
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _genlib as G  # noqa: E402

from policy_radar.cases import (  # noqa: E402
    STATUS_PARSED, STATUS_PARTIAL, STATUS_UNPARSED, UNPARSED,
    naive_parse_pcode,
)
from policy_radar.serialize import read_json, write_json  # noqa: E402

#: 人工标注表：`(pcode, 期望结构)`。**逐条手写**，覆盖实测形态 + 反向样例。
CANONICAL_CASES = (
    # --- 形态 1：标准六角括号（实采） ---
    ("国办发〔2026〕28号",
     {"agency_code": "国办发", "year": "2026", "serial": "28", "status": STATUS_PARSED}),
    # --- 形态 2：多字代字（实采 `国知发服字`，代字含"字"） ---
    ("国知发服字〔2026〕29号",
     {"agency_code": "国知发服字", "year": "2026", "serial": "29",
      "status": STATUS_PARSED}),
    # --- 形态 3：多部门联发代字（实采 `工信部联规函`） ---
    ("工信部联规函〔2026〕305号",
     {"agency_code": "工信部联规函", "year": "2026", "serial": "305",
      "status": STATUS_PARSED}),
    # --- 形态 4：序号含汉字前缀、无年份（实采）——**反向样例：不得编造年份** ---
    ("国令第847号",
     {"agency_code": "国令", "year": UNPARSED, "serial": "847",
      "status": STATUS_PARTIAL}),
    # --- 形态 5：空 pcode（实测部委 3/30）——**反向样例：不得解析出任何字段** ---
    ("",
     {"agency_code": UNPARSED, "year": UNPARSED, "serial": UNPARSED,
      "status": STATUS_UNPARSED}),
    # --- 形态 6：全角括号变体（**M1 实采新发现**，码位与〔〕不同） ---
    ("工信部联规﹝2026﹞210号",
     {"agency_code": "工信部联规", "year": "2026", "serial": "210",
      "status": STATUS_PARSED}),
    # --- 形态 7：序号与"号"之间有空格（**M1 实采新发现**） ---
    ("农农发〔2026〕9 号",
     {"agency_code": "农农发", "year": "2026", "serial": "9", "status": STATUS_PARSED}),
    # --- 形态 8：国务院令类无括号（同形态 4 的另一实例，交叉验证序号抽取） ---
    ("国令第846号",
     {"agency_code": "国令", "year": UNPARSED, "serial": "846",
      "status": STATUS_PARTIAL}),
    # --- 附加实采形态（多部门联发、含"字"代字的其他实例） ---
    ("发改价格〔2026〕1476号",
     {"agency_code": "发改价格", "year": "2026", "serial": "1476",
      "status": STATUS_PARSED}),
    ("建办城函〔2026〕239号",
     {"agency_code": "建办城函", "year": "2026", "serial": "239",
      "status": STATUS_PARSED}),
    ("交水发〔2026〕127号",
     {"agency_code": "交水发", "year": "2026", "serial": "127",
      "status": STATUS_PARSED}),
)


# --- 独立朴素 oracle ---------------------------------------------------------

#: 参照实现从 `policy_radar.cases` 引入（**单一实现源**：生成器、守门测试、
#: `verify-data` 命令共用同一份 oracle，避免三处各写一份而互相漂移）。
#: 该模块由 `tests/test_cases_independence.py` 守门：生产模块不得 import 它。
#:
#: **独立性说明**：oracle 与生产解析器（M3 `parse.py`）走不同代码路径
#: （oracle 纯位置切片、不用正则），故"把生产实现注释掉，真值仍可算出"。
naive_parse_pcode = naive_parse_pcode


# --- 生成守卫 ---------------------------------------------------------------

def assert_canonical_matches_oracle():
    """人工标注表必须与 oracle 逐条一致（不一致即说明两边至少一边写错）。"""
    mismatches = []
    for pcode, expected in CANONICAL_CASES:
        actual = naive_parse_pcode(pcode)
        if actual != expected:
            mismatches.append((pcode, expected, actual))
    if mismatches:
        lines = []
        for pcode, exp, act in mismatches:
            lines.append("pcode=%r\n    标注=%r\n    oracle=%r" % (pcode, exp, act))
        raise AssertionError("人工标注与 oracle 不一致：\n  " + "\n  ".join(lines))


def assert_reverse_cases_present():
    """反向样例必须真存在（防"只测该命中"）。"""
    by_pcode = dict(CANONICAL_CASES)
    # 反向样例 1：无括号 → 年份不得解析出来。
    case = by_pcode.get("国令第847号")
    if not case or case["year"] != UNPARSED:
        raise AssertionError("反向样例缺失：`国令第847号` 的年份必须标 未解析")
    if case["serial"] == UNPARSED:
        raise AssertionError("反向样例自相矛盾：`国令第847号` 的序号应能解析出")
    # 反向样例 2：空 pcode → 三字段全未解析。
    empty = by_pcode.get("")
    if not empty or empty["status"] != STATUS_UNPARSED:
        raise AssertionError("反向样例缺失：空 pcode 必须整条 unparsed")
    for field in ("agency_code", "year", "serial"):
        if empty[field] != UNPARSED:
            raise AssertionError("反向样例失败：空 pcode 的 %s 应为 未解析" % field)
    # 正向对照：全角括号变体必须解析出年份（防"适用域写太窄"）。
    full = by_pcode.get("工信部联规﹝2026﹞210号")
    if not full or full["year"] != "2026":
        raise AssertionError("正向对照失败：全角括号变体应解析出年份 2026")
    # 正向对照：序号含空格必须解析出纯数字序号。
    spaced = by_pcode.get("农农发〔2026〕9 号")
    if not spaced or spaced["serial"] != "9":
        raise AssertionError("正向对照失败：`农农发〔2026〕9 号` 序号应为 '9'（不带空格）")


# --- 产物 ------------------------------------------------------------------

def build_pcode_truth(samples_dir):
    """构造 `pcode-truth.json`：人工标注用例 + 观测池全量真实文号语料。"""
    assert_canonical_matches_oracle()
    assert_reverse_cases_present()

    cases = []
    for pcode, expected in CANONICAL_CASES:
        cases.append({
            "pcode": pcode,
            "expect": expected,
            "origin": "hand_annotated",
            "form": _form_label(pcode),
        })

    # 观测池语料：57 条真实文号（逐条 oracle 复算）。
    pool_pcodes = sorted(set(it.pcode for it in G.load_pool(samples_dir) if it.pcode))
    annotated = set(pc for pc, _ in CANONICAL_CASES)
    pool_cases = []
    for pc in pool_pcodes:
        pool_cases.append({
            "pcode": pc,
            "expect": naive_parse_pcode(pc),
            "origin": "pool_corpus",
            "form": _form_label(pc),
        })

    truth = {
        "case": "pcode-parse",
        "case_kind": "pcode-structure",
        "unparsed_sentinel": UNPARSED,
        "status_values": [STATUS_PARSED, STATUS_PARTIAL, STATUS_UNPARSED],
        "note": "期望只存输入与期望；观测由基准运行时实算（K11）。",
        "input": {
            "source": "data/samples/*-n30.json 的 pcode 字段 + 人工标注用例",
        },
        "expect_semantics": {
            "parsed": "agency_code / year / serial 三字段全部解析成功",
            "partial": "部分字段解析成功，未成功者为哨兵 %r" % UNPARSED,
            "unparsed": "整条无法解析，三字段全为哨兵 %r" % UNPARSED,
        },
        "cases": cases,
        "pool_corpus_cases": pool_cases,
        "also_expect": {
            "hand_annotated_not_in_pool": sorted(
                pc for pc in annotated if pc not in set(pool_pcodes)),
            "reverse_no_fabricated_year": True,
            "reverse_empty_pcode_unparsed": True,
            "fullwidth_bracket_parses_year": True,
        },
        "coverage": {
            "hand_annotated_cases": len(cases),
            "pool_corpus_cases": len(pool_cases),
            "form_counts": _form_counts(cases + pool_cases),
            "sampling_note": "观测池两频道各 30 条（共 57 条非空 pcode）；"
                             "**抽样覆盖、非穷举**",
        },
    }
    G.assert_no_observed_fields(truth, "pcode-truth")
    return truth


def _form_label(pcode):
    """给文号打形态标签（供覆盖声明统计；纯描述，不参与判定）。"""
    text = (pcode or "").strip()
    if not text:
        return "empty"
    has_std = "\u3014" in text
    has_full = "\ufe5d" in text
    if has_std or has_full:
        bracket = "std_bracket" if has_std else "fullwidth_bracket"
        tail = text.split("\u3015" if has_std else "\ufe5e", 1)
        if len(tail) == 2 and " " in tail[1]:
            return bracket + "_spaced_serial"
        return bracket
    if "第" in text and "号" in text:
        return "decree_no_bracket"
    return "other"


def _form_counts(all_cases):
    counts = {}
    for case in all_cases:
        form = case["form"]
        counts[form] = counts.get(form, 0) + 1
    return dict((k, counts[k]) for k in sorted(counts))


# --- 部门别名表 -------------------------------------------------------------

def build_org_aliases(samples_dir):
    """从观测池的 `puborg` 归纳部门别名表（K7 单一来源）。

    **只登记实测出现过的部门名**（含"办公厅/办公室/综合司"后缀变体），
    未出现的不编造。`puborg` 为**空白分隔多部门**（实测分隔符含 U+0020 与 U+2002）——
    归一化前须按 `\\s` 类空白拆分（见 `_genlib` 与 `data/README.md` E5）。

    别名表为 `{原始名: 规范名}`；`住房城乡建设部` → `住房和城乡建设部` 是实测
    **唯一真变体对**（同一部门两种写法）。匹配**最长优先**（`住房城乡建设部`
    是 `住房城乡建设部办公厅` 的前缀，短串优先会把长串读成短串）。
    """
    tokens = []
    for item in G.load_pool(samples_dir):
        for tok in re.split(r"\s+", (item.puborg or "").strip()):
            if tok and tok not in tokens:
                tokens.append(tok)
    tokens.sort()

    aliases = {}
    for tok in tokens:
        aliases[tok] = _canonical_org(tok)

    return {
        "note": "部门别名表（K7 单一来源）：只登记实测出现过的部门名；"
                "匹配最长优先；未登记的部门原样保留并标 alias_missing（不猜）。",
        "source": "data/samples/*-n30.json 的 puborg 字段（2026-10-17 实采）",
        "match_rule": "longest_first",
        "unmatched_policy": "keep_raw_and_flag_alias_missing",
        "aliases": aliases,
        "canonical_orgs": sorted(set(aliases.values())),
        "sampled_token_count": len(tokens),
    }


#: 实测真变体对：原始名 → 规范名（只有**实测出现过**的才登记）。
_ORG_VARIANTS = {
    "住房城乡建设部": "住房和城乡建设部",
    "住房城乡建设部办公厅": "住房和城乡建设部办公厅",
}


def _canonical_org(token):
    return _ORG_VARIANTS.get(token, token)


# --- 主流程 ----------------------------------------------------------------

def generate(root, truth_dir, config_dir, samples_dir):
    paths = []
    truth = build_pcode_truth(samples_dir)
    path_t = os.path.join(truth_dir, "pcode-truth.json")
    write_json(path_t, truth)
    paths.append(path_t)

    aliases = build_org_aliases(samples_dir)
    path_a = os.path.join(config_dir, "org-aliases.json")
    write_json(path_a, aliases)
    paths.append(path_a)
    return paths, truth, aliases


def check(root, truth_dir, config_dir, samples_dir):
    """位级守门：重跑生成器到临时目录，与冻结产物逐字节比对。"""
    failures = []
    path_t = os.path.join(truth_dir, "pcode-truth.json")
    path_a = os.path.join(config_dir, "org-aliases.json")
    for path in (path_t, path_a):
        if not os.path.isfile(path):
            failures.append("冻结产物缺失：%s" % G.relative_posix(path, root))

    if not failures:
        # 形态覆盖自证（第一层）。
        truth = read_json(path_t)
        forms = truth["coverage"]["form_counts"]
        for needed in ("std_bracket", "fullwidth_bracket", "decree_no_bracket", "empty"):
            if not forms.get(needed):
                failures.append("形态 %s 无样本（覆盖不全）" % needed)
        if not truth["coverage"]["hand_annotated_cases"]:
            failures.append("人工标注用例为空")
        if not truth["coverage"]["pool_corpus_cases"]:
            failures.append("观测池语料为空")

        # 第二层：重跑逐字节比对。
        tmp = tempfile.mkdtemp(prefix="policy-radar-pcodecheck-")
        try:
            tmp_truth = os.path.join(tmp, "truth")
            tmp_config = os.path.join(tmp, "config")
            os.makedirs(tmp_truth)
            os.makedirs(tmp_config)
            generate(root, tmp_truth, tmp_config, samples_dir)
            pairs = (
                (os.path.join(tmp_truth, "pcode-truth.json"),
                 os.path.join(truth_dir, "pcode-truth.json")),
                (os.path.join(tmp_config, "org-aliases.json"),
                 os.path.join(config_dir, "org-aliases.json")),
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
    sys.stdout.write("  [OK] 第一层：形态覆盖齐备（%r）\n"
                     % read_json(path_t)["coverage"]["form_counts"])
    sys.stdout.write("  [OK] 第二层：重跑生成器与冻结产物逐字节一致（2 份产物）\n")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="文号解析真值 + 部门别名表生成器（M1）")
    parser.add_argument("--root", default=G._ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    truth_dir = os.path.join(args.root, "data", "truth")
    config_dir = os.path.join(args.root, "data", "config")
    samples_dir = os.path.join(args.root, "data", "samples")
    for d in (truth_dir, config_dir, samples_dir):
        if not os.path.isdir(d):
            sys.stderr.write("目录不存在：%s\n" % d)
            return 2

    if args.check:
        return check(args.root, truth_dir, config_dir, samples_dir)

    try:
        paths, truth, aliases = generate(args.root, truth_dir, config_dir, samples_dir)
    except AssertionError as exc:
        sys.stderr.write("生成守卫拦截（未写盘）：%s\n" % exc)
        return 1

    for path in paths:
        sys.stdout.write("  写入 %s\n" % G.relative_posix(path, args.root))
    sys.stdout.write("  人工标注 %d 条 / 观测池语料 %d 条；形态 %r\n"
                     % (truth["coverage"]["hand_annotated_cases"],
                        truth["coverage"]["pool_corpus_cases"],
                        truth["coverage"]["form_counts"]))
    sys.stdout.write("  部门别名表：%d 条原始名 → %d 个规范名\n"
                     % (aliases["sampled_token_count"],
                        len(aliases["canonical_orgs"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
