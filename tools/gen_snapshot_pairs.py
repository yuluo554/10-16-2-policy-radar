#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""预置快照对生成器（M1）：合成快照对 + 独立朴素 oracle + 生成守卫 + `--check`。

用法::

    py -3.8 -X utf8 tools/gen_snapshot_pairs.py                  # 生成到 data/
    py -3.8 -X utf8 tools/gen_snapshot_pairs.py --check          # 两层位级守门

**产出**：`data/snapshots/pair-A.json`、`pair-B.json`、`manifest.json` +
`data/truth/diff-truth.json`。

## 两条 skill 核心纪律的落点

1. **期望值独立可复算**：真值里的"应判新增/重复"**不由生产实现算出**——本文件里
   **独立重写一遍朴素 oracle**（`naive_oracle_diff()`，按 `id`/`pcode` 双键做集合差，
   用最笨的双重循环写，不 import 任何生产 diff 代码）。落库前跑**生成守卫**：
   声明的期望值与 oracle 重算逐条一致才许写盘。
   判别口诀：**"把主实现的 diff 逻辑注释掉，真值还能算出来吗？"**——能，因为真值只依赖
   本文件的 oracle 与输入快照，不依赖 `snapshot.py`（M3 才落地）。

2. **两层位级守门**（skill 头号假门来源）：
   ① **冻结产物自身形态正确**：B 相对 A 的新增数 == manifest 声明数、逐条角色标注齐备；
   ② **重跑生成器到临时目录 → 与冻结产物逐字节比对**（`--check` 通路）。
   判别口诀：**"这个守门测的是产物还是生成器？"**——②必须真跑一遍生成器。

## 覆盖形态（题面评分"真值基准覆盖应判新增/重复两类样本"）

| 角色 | 含义 | 判据 |
|---|---|---|
| `carried` | B 保留 A 的条目 | 应判**重复**（`id` 键） |
| `fresh` | B 中的全新条目 | 应判**新增** |
| `pcode_dup` | B 中 id 新、但 `pcode` 与 A 某条相同 | 应判**重复**（**`pcode` 副键**）——只按 id 判会漏 |
| `empty_pcode_new` | `pcode` 空 + id 新 | 应判**新增**（空 pcode 不得致误判） |
| `empty_pcode_same` | `pcode` 空 + id 同 | 应判**重复**（只能按 id 判） |
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

from policy_radar.cases import naive_diff as naive_oracle_diff  # noqa: E402
from policy_radar.model import PolicyItem  # noqa: E402
from policy_radar.serialize import read_json, write_json  # noqa: E402

#: 合成规模（固定，不随环境变化）。
A_SIZE = 20
CARRY_SIZE = 14
FRESH_SIZE = 5

#: 角色常量（真值与 manifest 共用）。
ROLE_CARRIED = "carried"
ROLE_FRESH = "fresh"
ROLE_PCODE_DUP = "pcode_dup"
ROLE_EMPTY_NEW = "empty_pcode_new"
ROLE_EMPTY_SAME = "empty_pcode_same"

#: 应判"重复"的角色集合 / 应判"新增"的角色集合。
DUP_ROLES = (ROLE_CARRIED, ROLE_PCODE_DUP, ROLE_EMPTY_SAME)
NEW_ROLES = (ROLE_FRESH, ROLE_EMPTY_NEW)


# --- 独立朴素 oracle（**故意用最笨的写法**，不与任何生产实现共享代码） --------

#: 参照实现从 `policy_radar.cases` 引入（**单一实现源**：生成器、守门测试、
#: `verify-data` 命令共用同一份 oracle，避免三处各写一份而互相漂移）。
#: 该模块由 `tests/test_cases_independence.py` 守门：生产模块不得 import 它。
naive_oracle_diff = naive_oracle_diff


# --- 合成 ------------------------------------------------------------------

def _pick(rng, candidates, n, what):
    """从 candidates 里确定性挑 n 个（洗牌后取前 n），不足即报错。"""
    if len(candidates) < n:
        raise AssertionError("%s 候选不足：需要 %d，只有 %d" % (what, n, len(candidates)))
    return rng.shuffle(candidates)[:n]


def build_pair(samples_dir, seed=G.DEFAULT_SEED):
    """确定性合成快照对 A/B，返回 `(items_a, items_b, roles)`。

    `roles` 为 `{b_id: role}`（角色标注供真值与 manifest 审计用）。
    """
    rng = G.SplitMix64(seed)
    pool = G.canonical_order(G.load_pool(samples_dir))

    # 预留三个空 pcode 条目（实测部委 3/30 为空）给两条边界形态。
    empty_pcode = [it for it in pool if not it.pcode]
    if len(empty_pcode) < 3:
        raise AssertionError("观测池空 pcode 条目不足（实测应有 3 条）")

    empty_same = empty_pcode[0]   # 进 A、且 B 保留 → 空 pcode + id 同
    empty_new = empty_pcode[1]    # 只进 B → 空 pcode + id 新
    nonempty = [it for it in pool if it.pcode]

    # --- A：从非空 pcode 条目里挑 (A_SIZE - 1) 条，加上 empty_same ---
    a_nonempty = _pick(rng, [it for it in nonempty], A_SIZE - 1, "A 的非空 pcode 条目")
    a_items = a_nonempty + [empty_same]
    a_items = G.canonical_order(a_items)
    a_ids = set(it.id for it in a_items)

    # --- B 的 carried：从 A 里挑 CARRY_SIZE 条，**强制含 empty_same** ---
    carry_pool = [it for it in a_items if it.id != empty_same.id]
    carried_rest = _pick(rng, carry_pool, CARRY_SIZE - 1, "B 的 carried 条目")
    carried = carried_rest + [empty_same]

    # --- B 的 fresh：池里既不在 A、也不是预留的 empty_new ---
    fresh_cand = [it for it in pool
                  if it.id not in a_ids and it.id != empty_new.id]
    fresh = _pick(rng, fresh_cand, FRESH_SIZE, "B 的 fresh 条目")
    fresh_ids = set(it.id for it in fresh)

    # --- B 的 pcode_dup：取一条**池中真实但未用**的条目，只改 pcode ---
    # 纪律：id 用真实值（不编造数字串），只合成 (id, pcode) 的**配对关系**；
    # 挑一条 pcode 非空、不在 A、不是 fresh 的条目。
    dup_cand = [it for it in pool
                if it.pcode and it.id not in a_ids and it.id not in fresh_ids
                and it.id != empty_new.id]
    dup_base = _pick(rng, dup_cand, 1, "B 的 pcode_dup 基条")[0]
    # 取一条 carried 里 pcode 非空的条目，把它的 pcode 赋给 dup_base。
    carry_with_pcode = [it for it in carried if it.pcode]
    pcode_source = _pick(rng, carry_with_pcode, 1, "pcode_dup 的 pcode 来源")[0]
    pcode_dup_item = G.clone_item(dup_base, pcode=pcode_source.pcode)
    if pcode_dup_item.id in a_ids:
        raise AssertionError("pcode_dup 的 id 撞进了 A（合成失败）")

    # --- 组装 B（规范序） ---
    b_items = G.canonical_order(carried + fresh + [pcode_dup_item, empty_new])

    roles = {}
    for it in carried:
        roles[it.id] = ROLE_CARRIED
    for it in fresh:
        roles[it.id] = ROLE_FRESH
    roles[pcode_dup_item.id] = ROLE_PCODE_DUP
    roles[empty_new.id] = ROLE_EMPTY_NEW
    # empty_same 已在 carried 里 → 覆盖为专属边界角色（同一条同时属两角色，取更具体者）。
    roles[empty_same.id] = ROLE_EMPTY_SAME

    return a_items, b_items, roles


# --- 生成守卫 ---------------------------------------------------------------

def assert_required_fields(items, where):
    """落库前校验必填字段齐备（FR-11：缺字段不得落库）。"""
    for it in items:
        missing = it.validate()
        if missing:
            raise AssertionError("%s 有条目缺必填字段 %r：id=%s" % (where, missing, it.id))


def assert_pair_shape(items_a, items_b, roles, expected_new, expected_dup):
    """**第一层守门**：冻结产物自身形态正确。

    ① A/B 必填字段齐备；② 角色表覆盖 B 的每一条；③ 声明的期望值与 oracle 重算一致；
    ④ 五类角色**各自至少一条**（防"某形态没样本却声称覆盖"）。
    """
    assert_required_fields(items_a, "快照 A")
    assert_required_fields(items_b, "快照 B")

    b_ids = set(it.id for it in items_b)
    missing_roles = sorted(b_ids - set(roles))
    if missing_roles:
        raise AssertionError("B 有条目未标角色：%r" % missing_roles)

    # ③ 期望值与 oracle 重算逐条一致（生成守卫）。
    oracle_new, oracle_dup, oracle_by = naive_oracle_diff(
        [it.to_dict() for it in items_a], [it.to_dict() for it in items_b])
    if sorted(expected_new) != sorted(oracle_new):
        raise AssertionError("新增期望与 oracle 不一致：声明 %r vs oracle %r"
                             % (sorted(expected_new), sorted(oracle_new)))
    if sorted(expected_dup) != sorted(oracle_dup):
        raise AssertionError("重复期望与 oracle 不一致：声明 %r vs oracle %r"
                             % (sorted(expected_dup), sorted(oracle_dup)))

    # ④ 五类角色各自至少一条。
    role_counts = {}
    for role in sorted(set(roles.values())):
        role_counts[role] = sum(1 for r in roles.values() if r == role)
    for role in (ROLE_CARRIED, ROLE_FRESH, ROLE_PCODE_DUP, ROLE_EMPTY_NEW,
                 ROLE_EMPTY_SAME):
        if role_counts.get(role, 0) < 1:
            raise AssertionError("角色 %s 无样本（形态覆盖不全）" % role)

    # 角色与判定结论必须自洽：DUP_ROLES 全在 dup 里，NEW_ROLES 全在 new 里。
    for bid, role in sorted(roles.items()):
        if role in DUP_ROLES and bid not in expected_dup:
            raise AssertionError("角色 %s 的条目 %s 未进重复集" % (role, bid))
        if role in NEW_ROLES and bid not in expected_new:
            raise AssertionError("角色 %s 的条目 %s 未进新增集" % (role, bid))

    # pcode_dup 必须真的靠 pcode 命中（不是靠 id 蒙对）。
    pcode_dup_ids = [bid for bid, role in roles.items() if role == ROLE_PCODE_DUP]
    for bid in pcode_dup_ids:
        if oracle_by.get(bid) != "pcode":
            raise AssertionError("pcode_dup 条目 %s 的命中键应为 pcode，实为 %r"
                                 % (bid, oracle_by.get(bid)))

    return role_counts


def build_truth(items_a, items_b, roles, snapshots_dir, data_root):
    """构造 `diff-truth.json`（**只存输入与期望**，K11：无 `observed_*`）。

    `input` 里的路径记**相对数据根**（`snapshots/pair-A.json`）而非相对仓库根——
    这样产物与"生成时落在哪个目录"无关：`--check` 把生成器重跑到临时目录时，
    记录的路径逐字不变，逐字节比对才有意义（相对仓库根会在跨盘/临时目录时失配）。
    """
    a_dicts = [it.to_dict() for it in items_a]
    b_dicts = [it.to_dict() for it in items_b]
    new_ids, dup_ids, matched_by = naive_oracle_diff(a_dicts, b_dicts)

    new_cases = []
    dup_cases = []
    for bid in sorted(roles):
        role = roles[bid]
        item = next(it for it in items_b if it.id == bid)
        record = {
            "item_id": bid,
            "source": item.source,
            "pcode": item.pcode,
            "role": role,
        }
        if role in DUP_ROLES:
            record["matched_by"] = matched_by.get(bid)
            dup_cases.append(record)
        else:
            new_cases.append(record)

    # also_expect：隐含结论（**可机器核验的布尔式**，不是散文）。
    # 只由输入（A/B 的 dict 列表）与 oracle 结论算出，不依赖生产实现。
    a_id_set = set(d["id"] for d in a_dicts)
    a_pcode_set = set(d["pcode"] for d in a_dicts if d.get("pcode"))
    b_by_id = dict((d["id"], d) for d in b_dicts)
    dup_absent_from_a = [
        bid for bid in dup_ids
        if bid not in a_id_set
        and not (b_by_id[bid].get("pcode") and b_by_id[bid]["pcode"] in a_pcode_set)
    ]
    also_expect = {
        "new_ids_absent_from_a": sorted(set(new_ids) & a_id_set) == [],
        "dup_ids_all_traceable_to_a": dup_absent_from_a == [],
        "pcode_dup_matched_by_pcode": sorted(
            bid for bid, role in roles.items() if role == ROLE_PCODE_DUP
        ) == sorted(bid for bid in dup_ids if matched_by.get(bid) == "pcode"),
    }

    return {
        "case": "snapshot-pair-A-B",
        "case_kind": "diff-new-vs-duplicate",
        "input": {
            "snapshot_a": G.relative_posix(
                os.path.join(snapshots_dir, "pair-A.json"), data_root),
            "snapshot_b": G.relative_posix(
                os.path.join(snapshots_dir, "pair-B.json"), data_root),
        },
        "dedup_keys": {"primary": "id", "secondary": "pcode_nonempty"},
        "expect": {
            "new_ids": new_ids,
            "dup_ids": dup_ids,
            "new_count": len(new_ids),
            "dup_count": len(dup_ids),
            "matched_by": dict((k, matched_by[k]) for k in sorted(matched_by)),
        },
        "also_expect": also_expect,
        "cases": {
            "new": new_cases,
            "dup": dup_cases,
        },
        "role_counts": _role_counts(roles),
    }


def _role_counts(roles):
    counts = {}
    for role in sorted(set(roles.values())):
        counts[role] = sum(1 for r in roles.values() if r == role)
    return counts


# --- 写盘 ------------------------------------------------------------------

def generate(data_root, snapshots_dir, truth_dir, samples_dir, seed=G.DEFAULT_SEED):
    """生成全部产物（快照对 + manifest + 真值），返回写盘路径列表。

    `data_root` 是**数据根**（`data/`），不是仓库根：真值里记的路径相对它，
    故产物与"落在哪个目录"无关（见 `build_truth` 的说明）。
    """
    items_a, items_b, roles = build_pair(samples_dir, seed=seed)
    a_dicts = [it.to_dict() for it in items_a]
    b_dicts = [it.to_dict() for it in items_b]
    new_ids, dup_ids, matched_by = naive_oracle_diff(a_dicts, b_dicts)

    # 生成守卫（写盘前）：形态正确 + 期望值与 oracle 一致 + 五形态齐备。
    role_counts = assert_pair_shape(items_a, items_b, roles, new_ids, dup_ids)

    snap_a = G.make_snapshot(items_a, "预置快照 A（旧）：合成样本，取自真实观测池，禁手改")
    snap_b = G.make_snapshot(items_b, "预置快照 B（新）：合成样本，取自真实观测池，禁手改")
    G.assert_no_forbidden_snapshot_fields(snap_a)
    G.assert_no_forbidden_snapshot_fields(snap_b)

    truth = build_truth(items_a, items_b, roles, snapshots_dir, data_root)
    G.assert_no_observed_fields(truth, "diff-truth")

    paths = []
    path_a = os.path.join(snapshots_dir, "pair-A.json")
    path_b = os.path.join(snapshots_dir, "pair-B.json")
    path_t = os.path.join(truth_dir, "diff-truth.json")
    write_json(path_a, snap_a)
    write_json(path_b, snap_b)
    write_json(path_t, truth)
    paths += [path_a, path_b, path_t]

    manifest = build_manifest(snapshots_dir, items_a, items_b, roles, role_counts)
    path_m = os.path.join(snapshots_dir, "manifest.json")
    write_json(path_m, manifest)
    paths.append(path_m)

    return paths, manifest


def build_manifest(snapshots_dir, items_a, items_b, roles, role_counts):
    """快照清单：逐份 sha256 + 形态覆盖声明 + 验收门槛（**随数据下发，代码零默认值**）。"""
    files = []
    for name in ("pair-A.json", "pair-B.json"):
        path = os.path.join(snapshots_dir, name)
        files.append({
            "file": name,
            "sha256": G.sha256_file(path),
            "bytes": os.path.getsize(path),
        })

    return {
        "format": G.SNAPSHOT_FORMAT,
        "format_version": G.SNAPSHOT_FORMAT_VERSION,
        "generator": "tools/gen_snapshot_pairs.py",
        "seed": G.DEFAULT_SEED,
        "note": "预置快照对清单：字节冻结（禁手改），重生成须整目录重跑并更新 sha256。",
        "counts": {
            "a_items": len(items_a),
            "b_items": len(items_b),
            "expected_new": sum(1 for r in roles.values() if r in NEW_ROLES),
            "expected_dup": sum(1 for r in roles.values() if r in DUP_ROLES),
        },
        # 覆盖声明：**形态总数 / 真值采样数 / 采样清单** 三登记（防假覆盖）。
        "coverage": {
            "declared_shapes": sorted(role_counts),
            "sampled_shapes": sorted(role_counts),
            "role_counts": role_counts,
            "sampling_note": "五类形态各至少 1 条；**抽样覆盖、非穷举**（观测池 60 条）",
        },
        # 验收门槛随数据下发：基准层只读，缺失即报配置错误，**不得回落代码默认值**。
        "thresholds": {
            "diff_new_accuracy": 1.0,
            "diff_dup_accuracy": 1.0,
            "note": "首期基准门槛：新增/重复判定准确率必须 100%（真值逐条对账）",
        },
        "files": files,
    }


# --- 两层位级守门 -----------------------------------------------------------

def check(root, snapshots_dir, truth_dir, samples_dir, seed=G.DEFAULT_SEED):
    """**两层位级守门**。返回 0（全过）/ 1（有失败）。"""
    failures = []

    # 第一层：冻结产物自身形态正确。
    path_a = os.path.join(snapshots_dir, "pair-A.json")
    path_b = os.path.join(snapshots_dir, "pair-B.json")
    path_m = os.path.join(snapshots_dir, "manifest.json")
    path_t = os.path.join(truth_dir, "diff-truth.json")
    for path in (path_a, path_b, path_m, path_t):
        if not os.path.isfile(path):
            failures.append("冻结产物缺失：%s" % G.relative_posix(path, root))
    if failures:
        for f in failures:
            sys.stderr.write("  [FAIL] %s\n" % f)
        return 1

    manifest = read_json(path_m)
    truth = read_json(path_t)
    snap_b = read_json(path_b)
    snap_a = read_json(path_a)

    # ①a sha256 与 manifest 登记值一致。
    for entry in manifest.get("files", []):
        actual = G.sha256_file(os.path.join(snapshots_dir, entry["file"]))
        if actual != entry["sha256"]:
            failures.append("%s sha256 失配（登记 %s 实际 %s）"
                            % (entry["file"], entry["sha256"][:12], actual[:12]))

    # ①b 形态正确：B 的新增数 == manifest 声明数；oracle 重算与真值一致。
    items_a = [PolicyItem.from_dict(d) for d in snap_a["items"]]
    items_b = [PolicyItem.from_dict(d) for d in snap_b["items"]]
    oracle_new, oracle_dup, _ = naive_oracle_diff(
        [it.to_dict() for it in items_a], [it.to_dict() for it in items_b])
    if sorted(oracle_new) != sorted(truth["expect"]["new_ids"]):
        failures.append("真值 new_ids 与 oracle 重算不一致")
    if sorted(oracle_dup) != sorted(truth["expect"]["dup_ids"]):
        failures.append("真值 dup_ids 与 oracle 重算不一致")
    declared_new = manifest["counts"]["expected_new"]
    if declared_new != len(oracle_new):
        failures.append("manifest 声明新增数 %d != oracle 实算 %d"
                        % (declared_new, len(oracle_new)))
    declared_dup = manifest["counts"]["expected_dup"]
    if declared_dup != len(oracle_dup):
        failures.append("manifest 声明重复数 %d != oracle 实算 %d"
                        % (declared_dup, len(oracle_dup)))
    if snap_b["item_count"] != len(snap_b["items"]):
        failures.append("快照 B item_count 与实际条数不符")

    # ② 重跑生成器到临时目录 → 与冻结产物逐字节比对。
    #    `data_root` 传临时目录本身：真值里记的路径相对数据根（`snapshots/pair-A.json`），
    #    故重跑产物的路径字段与冻结产物逐字相同（否则跨目录比对必然假红）。
    tmp = tempfile.mkdtemp(prefix="policy-radar-gencheck-")
    try:
        tmp_snap = os.path.join(tmp, "snapshots")
        tmp_truth = os.path.join(tmp, "truth")
        os.makedirs(tmp_snap)
        os.makedirs(tmp_truth)
        generate(tmp, tmp_snap, tmp_truth, samples_dir, seed=seed)
        for name, frozen_dir in (("pair-A.json", snapshots_dir),
                                 ("pair-B.json", snapshots_dir),
                                 ("manifest.json", snapshots_dir),
                                 ("diff-truth.json", truth_dir)):
            fresh = os.path.join(tmp_snap if name != "diff-truth.json" else tmp_truth,
                                 name)
            frozen = os.path.join(frozen_dir, name)
            with io.open(fresh, "rb") as f1, io.open(frozen, "rb") as f2:
                b1, b2 = f1.read(), f2.read()
            if b1 != b2:
                failures.append("重跑与冻结产物字节不一致：%s（%d vs %d 字节）"
                                % (name, len(b1), len(b2)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            sys.stderr.write("  [FAIL] %s\n" % f)
        return 1

    sys.stdout.write("  [OK] 第一层：形态正确（新增 %d / 重复 %d，五形态齐备，sha256 一致）\n"
                     % (len(oracle_new), len(oracle_dup)))
    sys.stdout.write("  [OK] 第二层：重跑生成器与冻结产物逐字节一致（4 份产物）\n")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="预置快照对生成器（M1）")
    parser.add_argument("--root", default=G._ROOT)
    parser.add_argument("--seed", type=int, default=G.DEFAULT_SEED)
    parser.add_argument("--check", action="store_true",
                        help="两层位级守门（不写盘）")
    args = parser.parse_args(argv)

    snapshots_dir = os.path.join(args.root, "data", "snapshots")
    truth_dir = os.path.join(args.root, "data", "truth")
    samples_dir = os.path.join(args.root, "data", "samples")
    data_root = os.path.join(args.root, "data")
    for d in (snapshots_dir, truth_dir, samples_dir):
        if not os.path.isdir(d):
            sys.stderr.write("目录不存在：%s\n" % d)
            return 2

    if args.check:
        return check(args.root, snapshots_dir, truth_dir, samples_dir, seed=args.seed)

    try:
        paths, manifest = generate(data_root, snapshots_dir, truth_dir,
                                   samples_dir, seed=args.seed)
    except AssertionError as exc:
        sys.stderr.write("生成守卫拦截（未写盘）：%s\n" % exc)
        return 1

    for path in paths:
        sys.stdout.write("  写入 %s\n" % G.relative_posix(path, args.root))
    sys.stdout.write("  A=%d 条 / B=%d 条；应判新增 %d 条 / 应判重复 %d 条；形态 %r\n"
                     % (manifest["counts"]["a_items"], manifest["counts"]["b_items"],
                        manifest["counts"]["expected_new"],
                        manifest["counts"]["expected_dup"],
                        manifest["coverage"]["role_counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
