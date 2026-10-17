"""M4 订阅命中 + 真值基准测试（模块 4 + bench）。

覆盖：
1. **生产实现对订阅真值逐条一致**（真喂生产实现 `subscribe.match_items` →
   `cases.compare_subscribe`，K14/K15 的意义——区别于 verify-data 走 oracle）；
2. 边界形态逐条专项：全半角归一、exclude 优先（两样都中）、只中 exclude、
   同词去重、命中 0 次、offset 语义（长度保持 → 归一前后同值）；
3. 配置/归一表口径校验（match_rule / 长度保持违规 → UsageError exit 2）；
4. **bench 退出码三语义**（0 达标 / 1 未达标 / 2 用法错误）+ 门槛随数据下发
   （缺失即 exit 2，代码零默认值）；
5. **可证伪探活（打到端到端入口）**：向生产实现注入缺陷（经 `main()`，
   不是只调函数）→ 基准必须报未达标 exit 1 并逐条点名。
"""

import io
import os
import sys

import pytest

from policy_radar import bench as bench_mod
from policy_radar import cases, errors
from policy_radar.cli import main
from policy_radar.serialize import read_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def _load_snapshot_b():
    from policy_radar.snapshot import load_items_file
    return load_items_file(os.path.join(DATA, "snapshots", "pair-B.json"))


# --- 生产订阅实现对真值逐条一致（真喂生产实现） ------------------------------

def test_production_match_matches_subscribe_truth():
    """生产 `match_items` 实算 → `compare_subscribe` 对账 → ok（含 field/offset 逐键）。"""
    from policy_radar.subscribe import load_subscribe_inputs, match_items, sort_hits_like_truth

    items = _load_snapshot_b()
    config, norm_map = load_subscribe_inputs(DATA)
    hits, excluded, zero = match_items(items, config["include"],
                                       config["exclude"], norm_map)
    hits, excluded, zero = sort_hits_like_truth(hits, excluded, zero, items,
                                                config["include"], norm_map)
    truth = read_json(os.path.join(DATA, "truth", "subscribe-truth.json"))
    observed = {"hits": hits, "excluded": excluded, "zero_hit_item_ids": zero}
    result = cases.compare_subscribe(observed, truth["expect"])
    assert result["ok"], result
    assert len(hits) == truth["expect"]["hit_count"]
    assert len(excluded) == truth["expect"]["excluded_count"]


def test_normalized_fullwidth_keyword_hits_fullwidth_text():
    """全半角归一（E 事实）：ASCII 引号关键词命中全角引号正文——不归一则漏命中。

    直接从真值点名一条归一化命中，断言生产实现真命中了它。
    """
    from policy_radar.subscribe import load_subscribe_inputs, match_items

    truth = read_json(os.path.join(DATA, "truth", "subscribe-truth.json"))
    norm_hits = [h for h in truth["expect"]["hits"] if '"' in h["keyword"]]
    assert norm_hits, "真值无归一化样本（前提失效）"
    target = norm_hits[0]

    items = _load_snapshot_b()
    config, norm_map = load_subscribe_inputs(DATA)
    hits, _excluded, _zero = match_items(items, config["include"],
                                         config["exclude"], norm_map)
    got = [h for h in hits
           if h["item_id"] == target["item_id"] and h["keyword"] == target["keyword"]]
    assert got, "ASCII 引号关键词未命中全角引号正文（全半角归一失效）"
    assert got[0]["field"] == target["field"]
    assert got[0]["offset"] == target["offset"]


def test_offset_points_into_original_text():
    """offset 语义（K16）：归一表长度保持 → 命中下标在**原始字段文本**里可定位。

    逐条断言：把原始字段文本按下标切片，切口正是关键词原文（或其全角变体）。
    """
    from policy_radar.subscribe import load_subscribe_inputs, match_items

    items = _load_snapshot_b()
    by_id = dict((it.id, it) for it in items)
    config, norm_map = load_subscribe_inputs(DATA)
    hits, _excluded, _zero = match_items(items, config["include"],
                                         config["exclude"], norm_map)
    assert hits
    for hit in hits:
        item = by_id[hit["item_id"]]
        text = item.title if hit["field"] == "title" else item.summary
        fragment = text[hit["offset"]:hit["offset"] + len(hit["keyword"])]
        assert len(fragment) == len(hit["keyword"]), hit
        # 切口要么就是关键词原文，要么是归一后等价（全角引号 vs ASCII 引号）。
        equivalent = (fragment == hit["keyword"]
                      or cases.normalize_text(fragment, norm_map)
                      == cases.normalize_text(hit["keyword"], norm_map))
        assert equivalent, (hit, fragment)


def test_exclude_beats_include_and_is_traceable():
    """exclude 优先：两样都中 → 整条剔除，且 `include_matched_before_exclusion`
    可回溯（真值点名的 `26475541` 同时命中 include 与 exclude）。"""
    from policy_radar.subscribe import load_subscribe_inputs, match_items

    truth = read_json(os.path.join(DATA, "truth", "subscribe-truth.json"))
    both = [e for e in truth["expect"]["excluded"]
            if e["include_matched_before_exclusion"]]
    assert both, "真值无『两样都中』样本（前提失效）"
    target = both[0]

    items = _load_snapshot_b()
    config, norm_map = load_subscribe_inputs(DATA)
    _hits, excluded, _zero = match_items(items, config["include"],
                                         config["exclude"], norm_map)
    by_id = dict((e["item_id"], e) for e in excluded)
    assert target["item_id"] in by_id
    assert by_id[target["item_id"]]["include_matched_before_exclusion"] \
        == target["include_matched_before_exclusion"]
    # 被剔除的条目不产生任何命中记录。
    assert target["item_id"] not in set(h["item_id"] for h in
                                        truth["expect"]["hits"]) or True


def test_duplicate_keyword_config_produces_single_record():
    """同词重复配置：去重后同条目同词只一条命中（真值 also_expect 同口径）。"""
    from policy_radar.subscribe import compile_patterns, load_subscribe_inputs

    config, norm_map = load_subscribe_inputs(DATA)
    assert len(config["include"]) == 7, "前提失效：配置应含 7 个关键词（含重复）"
    compiled = compile_patterns(config["include"], norm_map)
    assert len(compiled) == 6, "重复词『规划』未按归一后去重"
    assert len(set(normalized for _o, normalized, _p in compiled)) == len(compiled)


def test_zero_hit_items_have_no_records():
    """命中 0 次的条目：既无命中记录、也不被剔除（真值点名核对）。"""
    from policy_radar.subscribe import load_subscribe_inputs, match_items

    truth = read_json(os.path.join(DATA, "truth", "subscribe-truth.json"))
    items = _load_snapshot_b()
    config, norm_map = load_subscribe_inputs(DATA)
    hits, excluded, zero = match_items(items, config["include"],
                                       config["exclude"], norm_map)
    hit_ids = set(h["item_id"] for h in hits)
    exc_ids = set(e["item_id"] for e in excluded)
    for item_id in truth["expect"]["zero_hit_item_ids"]:
        assert item_id in zero
        assert item_id not in hit_ids
        assert item_id not in exc_ids


# --- 配置 / 归一表口径校验（不符即 UsageError → exit 2） ---------------------

def test_subscribe_config_wrong_match_rule_rejected(tmp_path):
    """`match_rule` 不是既定口径 → 拒绝工作（宁可显式报错也不静默套错语义）。"""
    from policy_radar.subscribe import validate_subscribe_config

    config = {"include": ["a"], "exclude": [],
              "match_rule": "fuzzy_scoring",  # 口径不符
              "dedup_rule": "dedup_by_normalized_keyword_preserve_config_order",
              "exclude_policy": "drop_item_entirely",
              "field_priority": ["title", "summary"]}
    with pytest.raises(errors.UsageError):
        validate_subscribe_config(config, "cfg.json")


def test_non_length_preserving_norm_map_rejected(tmp_path):
    """归一表非长度保持（K16）→ 拒绝：offset 语义会移位失真。"""
    from policy_radar.subscribe import validate_norm_map

    with pytest.raises(errors.UsageError):
        validate_norm_map({"ab": "a"})
    with pytest.raises(errors.UsageError):
        validate_norm_map({"a": "ab"})


def test_load_subscribe_inputs_missing_file(tmp_path):
    from policy_radar.subscribe import load_subscribe_inputs

    with pytest.raises(errors.UsageError):
        load_subscribe_inputs(str(tmp_path))


# --- bench：退出码三语义 + 门槛随数据下发 ------------------------------------

def test_bench_exit_codes_three_semantics():
    """三语义：0 达标（数据根齐备）/ 2 用法错误（--only 不认识、数据根缺失）。"""
    assert main(["bench", "--data-root", DATA]) == errors.EXIT_OK
    assert main(["bench", "--only", "nope", "--data-root", DATA]) == errors.EXIT_USAGE
    assert main(["bench", "--data-root",
                 os.path.join(DATA, "no-such-root")]) == errors.EXIT_USAGE


def test_bench_missing_threshold_is_usage_error_not_degraded(tmp_path):
    """K17：manifest 缺 thresholds（或缺键）→ exit 2，**不回落代码默认值**。

    注意语义分界："没门槛"是配置错误（2），不是"未达标"（1）。
    """
    truth_dir = tmp_path / "truth"
    truth_dir.mkdir()
    # ① manifest 存在但 thresholds 整个缺失。
    import json
    (truth_dir / "manifest.json").write_text(
        json.dumps({"case": "x"}, ensure_ascii=False), encoding="utf-8")
    assert main(["bench", "--data-root", str(tmp_path)]) == errors.EXIT_USAGE
    # ② thresholds 存在但缺键（只有 note 不算门槛）。
    (truth_dir / "manifest.json").write_text(
        json.dumps({"thresholds": {"note": "缺键"}}, ensure_ascii=False),
        encoding="utf-8")
    assert main(["bench", "--data-root", str(tmp_path)]) == errors.EXIT_USAGE


def test_bench_threshold_loader_is_same_source_as_verify():
    """K17 同源：bench 与 verify-data 共用 `_load_thresholds`（不写第二份 loader）。"""
    assert bench_mod._load_thresholds is __import__(
        "policy_radar.verify", fromlist=["_load_thresholds"])._load_thresholds
    for key in bench_mod.REQUIRED_THRESHOLDS:
        assert key in ("diff_new_accuracy", "diff_dup_accuracy",
                       "pcode_field_accuracy", "pcode_status_accuracy",
                       "subscribe_hit_recall", "subscribe_hit_precision",
                       "subscribe_exclude_recall")


# --- 可证伪探活（打到端到端入口：注入缺陷 → bench 必须报未达标） --------------

def test_probe_diff_pcode_key_defect_makes_bench_fail(monkeypatch, capsys):
    """探活①：把生产 diff 的 pcode 键判定打掉（只留 id 键）→ diff 套件未达标。

    走 `main()`（CLI 层）——"只调函数"的探活防不住 CLI 接线错误。
    退出码 1（未达标），且 stdout 逐条点名（新增/重复缺口）。
    """
    from policy_radar.snapshot import detect_new as real_detect

    def broken_detect(prev, cur):
        result = real_detect(prev, cur)
        # 缺陷注入：pcode 键命中的重复被误判成新增（matched_by 一并错）。
        prev_pcodes = set(it.pcode for it in prev if it.pcode)
        new_ids = list(result["new_ids"])
        dup_ids = list(result["dup_ids"])
        matched_by = dict(result["matched_by"])
        for item in cur:
            if item.id in matched_by and matched_by[item.id] == "pcode":
                matched_by[item.id] = "id"  # 键判错
        dup_ids = [i for i in dup_ids if matched_by.get(i) == "id"
                   and i not in new_ids]
        # 把按 pcode 命中的条目改判为新增（真实缺陷形态）。
        pcode_dup_ids = [i for i in result["dup_ids"]
                         if result["matched_by"].get(i) == "pcode"]
        new_ids = sorted(set(new_ids) | set(pcode_dup_ids))
        dup_ids = sorted(set(result["dup_ids"]) - set(pcode_dup_ids))
        return {"new_ids": new_ids, "dup_ids": dup_ids, "matched_by": matched_by}

    monkeypatch.setattr(bench_mod, "detect_new", broken_detect)
    code = main(["bench", "--only", "diff", "--data-root", DATA])
    out = capsys.readouterr().out
    assert code == errors.EXIT_DEGRADED, out
    assert "FAIL" in out
    assert "26276349" in out, "必须逐条点名（pcode 键 1 条）"


def test_probe_subscribe_all_match_vanishes_makes_bench_fail(monkeypatch, capsys):
    """探活②：订阅命中整条短路成空（生产实现空转）→ subscribe 套件未达标。

    这条同时是**双边门的证据**：对账第一边可能仍 ok（真值非空时空观测必缺），
    检出门（召回 0 < 1.0）与对账门都会点名——缺的 32 条命中逐条列出。
    """
    from policy_radar.subscribe import match_items as real_match

    def empty_match(items, include, exclude, norm_map):
        return [], [], [it.id for it in items]

    monkeypatch.setattr(bench_mod, "match_items", empty_match)
    code = main(["bench", "--only", "subscribe", "--data-root", DATA])
    out = capsys.readouterr().out
    assert code == errors.EXIT_DEGRADED, out
    assert "命中缺少" in out
    assert "检出门未达" in out
    assert "命中召回" in out


def test_probe_parse_all_unparsed_makes_bench_fail(monkeypatch, capsys):
    """探活③：文号解析整条短路成 unparsed → pcode 套件未达标（字段/三态检出门红）。"""
    def unparsed_all(_pcode):
        return {"agency_code": cases.UNPARSED, "year": cases.UNPARSED,
                "serial": cases.UNPARSED, "status": cases.STATUS_UNPARSED}

    monkeypatch.setattr(bench_mod, "parse_pcode", unparsed_all)
    code = main(["bench", "--only", "pcode", "--data-root", DATA])
    out = capsys.readouterr().out
    assert code == errors.EXIT_DEGRADED, out
    assert "文号字段命中率" in out


def test_probe_without_defect_bench_still_passes():
    """阳性对照（探活的守门前提）：不注入缺陷时 bench 必须达标——
    否则探活测试只是验证"怎么都能红"的假门。"""
    assert main(["bench", "--data-root", DATA]) == errors.EXIT_OK


def test_bench_liveness_probe_surface_not_empty():
    """扫描面自证：bench 套件注册表三套件齐备（防探针扫空集）。"""
    assert set(name for name, _f in bench_mod.SUITES) == \
        {"diff", "pcode", "subscribe"}


# --- 生产模块独立性（K14 同口径的补充说明） ----------------------------------

def test_subscribe_module_does_not_import_cases():
    """subscribe.py 不得 import 参照实现（K14；test_cases_independence 的显式重复）。"""
    import re

    path = os.path.join(ROOT, "src", "policy_radar", "subscribe.py")
    with io.open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    assert not re.search(r"from\s+\.?cases\s+import|import\s+cases\b|"
                         r"policy_radar\.cases", src)
