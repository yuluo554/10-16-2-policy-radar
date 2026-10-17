"""快照存储 + 新增/重复判定测试（M3）：生产实现 `snapshot.py` 对真值逐条对账。

**真喂生产实现（K14 的意义）**：`verify-data` 走的是 oracle（`cases.naive_*`），
它核的是"真值库自身自洽"；本文件把真值的**输入**喂给**生产** `snapshot.py`，
用**共用对账语义** `cases.compare_diff`（K15）与期望逐条比对——生产实现写错，
这里红，oracle 全绿也救不了它。

**判别口诀（K14）**："把生产实现的判定逻辑注释掉，真值还能算出来吗？"
能（真值只依赖 oracle 与输入）——但本文件的断言会红（生产实现被考住了）。

判据分布（`plan/04-模块详设.md` 模块 2 的纪律逐条对应）：

| 纪律 | 本文件测试 |
|---|---|
| K5 规范排序 + 双跑逐字节 | `test_rebuilt_snapshot_is_byte_identical_to_frozen_*` |
| K4 双键判定 + matched_by | `test_detect_new_matches_diff_truth` / `test_matched_by_*` |
| K10 快照白名单门禁 | `test_forbidden_fields_*` |
| K22 输入按 format 分派 | `test_load_items_file_*` |
| K23 首跑语义 | `test_first_run_*` |
| 无时钟参与判定 | `test_module_has_no_wall_clock_in_judgment` |
"""

import io
import os
import re

import pytest

from policy_radar import cases, snapshot
from policy_radar.errors import EXIT_OK, UsageError
from policy_radar.model import FORBIDDEN_SNAPSHOT_FIELDS, SCHEMA_FIELDS, PolicyItem
from policy_radar.serialize import dumps_json, read_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SNAPSHOTS = os.path.join(DATA, "snapshots")

PATH_A = os.path.join(SNAPSHOTS, "pair-A.json")
PATH_B = os.path.join(SNAPSHOTS, "pair-B.json")


def _load_items(path):
    return snapshot.load_snapshot(path)


@pytest.fixture(scope="module")
def items_a():
    return _load_items(PATH_A)


@pytest.fixture(scope="module")
def items_b():
    return _load_items(PATH_B)


# --- 一、生产 diff 判定对真值（核心：真喂生产实现） --------------------------

def test_detect_new_matches_diff_truth(items_a, items_b):
    """**M3 核心判据**：生产 `detect_new` 对预置快照对的结果与真值逐条一致。

    对账走共用语义 `cases.compare_diff`（K15）——新增 6 / 重复 15 /
    `matched_by` 含 1 条 `pcode` 键命中，全部逐条点名。
    """
    result = snapshot.detect_new(items_a, items_b)
    observed = {"new_ids": result["new_ids"], "dup_ids": result["dup_ids"],
                "matched_by": result["matched_by"]}
    truth = read_json(os.path.join(DATA, "truth", "diff-truth.json"))
    compare = cases.compare_diff(observed, truth["expect"])
    assert compare["ok"], compare
    assert result["new_ids"] == truth["expect"]["new_ids"]
    assert result["dup_ids"] == truth["expect"]["dup_ids"]
    assert result["matched_by"] == truth["expect"]["matched_by"]


def test_pcode_key_hit_is_named(items_a, items_b):
    """真值里那条专门考 `pcode` 副键的样本，必须以 `pcode` 键命中（不是 id 蒙对）。"""
    result = snapshot.detect_new(items_a, items_b)
    pcode_hits = sorted(k for k, v in result["matched_by"].items() if v == "pcode")
    assert len(pcode_hits) == 1, pcode_hits
    truth = read_json(os.path.join(DATA, "truth", "diff-truth.json"))
    expected = sorted(k for k, v in truth["expect"]["matched_by"].items()
                      if v == "pcode")
    assert pcode_hits == expected


def test_empty_pcode_only_matches_by_id(items_a, items_b):
    """边界：空 `pcode` 不得参与 pcode 键判定（`empty_pcode_same` 只按 id 判重）。"""
    result = snapshot.detect_new(items_a, items_b)
    for item_id, key in result["matched_by"].items():
        if key == "pcode":
            dup = next(it for it in items_b if it.id == item_id)
            assert dup.pcode, "空 pcode 条目被记成 pcode 键命中：%s" % item_id


def test_diff_product_counts_and_order(items_a, items_b):
    """diff 产物的元信息与新增条目序：new/dup 计数一致，`items` 按 K5 规范序。"""
    product = snapshot.build_diff_product(items_a, items_b)
    truth = read_json(os.path.join(DATA, "truth", "diff-truth.json"))
    assert product["new_count"] == truth["expect"]["new_count"] == 6
    assert product["dup_count"] == truth["expect"]["dup_count"] == 15
    assert product["previous_item_count"] == 20
    assert product["current_item_count"] == 21
    assert product["dedup_keys"] == {"primary": "id", "secondary": "pcode_nonempty"}
    # 新增条目按 (pubtimeStr 倒序, id 升序)。
    dates = [it["pubtimeStr"] for it in product["items"]]
    assert dates == sorted(dates, reverse=True)
    ids_in_date = {}
    for it in product["items"]:
        ids_in_date.setdefault(it["pubtimeStr"], []).append(it["id"])
    for date, ids in ids_in_date.items():
        assert ids == sorted(ids), (date, ids)
    # 新增清单的条目字段恰为 schema 十项（K10 白名单）。
    for it in product["items"]:
        assert set(it) == set(SCHEMA_FIELDS)


def test_diff_product_is_byte_identical_across_runs(items_a, items_b, tmp_path):
    """**DoD"同输入同输出"**：同一对快照双跑，diff 产物逐字节一致。"""
    p1 = os.path.join(str(tmp_path), "d1.json")
    p2 = os.path.join(str(tmp_path), "d2.json")
    from policy_radar.serialize import write_json
    write_json(p1, snapshot.build_diff_product(items_a, items_b))
    write_json(p2, snapshot.build_diff_product(list(items_a), list(items_b)))
    with io.open(p1, "rb") as f1, io.open(p2, "rb") as f2:
        assert f1.read() == f2.read()


def test_diff_product_is_byte_identical_regardless_of_input_order(items_a, items_b):
    """输入序打乱（模拟 API 返回序 K22）不改变产物：判定与排序都在生产层收口。"""
    shuffled = list(reversed(items_b))
    p1 = dumps_json(snapshot.build_diff_product(items_a, items_b))
    p2 = dumps_json(snapshot.build_diff_product(items_a, shuffled))
    assert p1 == p2


# --- 二、K5：重建快照与冻结产物逐字节一致 ------------------------------------

@pytest.mark.parametrize("name", ["pair-A.json", "pair-B.json"])
def test_rebuilt_snapshot_is_byte_identical_to_frozen(name):
    """生产 `build_snapshot` 重建冻结快照必须**逐字节一致**（K5 单点 + 无时间戳）。

    包内不得 import `tools/`（`_genlib.canonical_order` 是生成侧实现）——
    这条测试就是"生产侧实现与冻结产物一致"的守门。
    """
    path = os.path.join(SNAPSHOTS, name)
    frozen = read_json(path)
    items = [PolicyItem.from_dict(d) for d in frozen["items"]]
    rebuilt = snapshot.build_snapshot(items, frozen["note"])
    with io.open(path, "rb") as fh:
        raw = fh.read()
    assert dumps_json(rebuilt).encode("utf-8") == raw


@pytest.mark.parametrize("name", ["pair-A.json", "pair-B.json"])
def test_rebuilt_snapshot_is_order_independent(name):
    """输入序打乱（API 返回序）不改变快照字节：规范排序在生产层收口（K22）。"""
    path = os.path.join(SNAPSHOTS, name)
    frozen = read_json(path)
    items = [PolicyItem.from_dict(d) for d in frozen["items"]]
    rebuilt = snapshot.build_snapshot(list(reversed(items)), frozen["note"])
    with io.open(path, "rb") as fh:
        assert dumps_json(rebuilt).encode("utf-8") == fh.read()


def test_updated_snapshot_from_diff_is_canonical(items_a, items_b):
    """diff 附带的更新后快照：以 B 为当前输入重建，与冻结 pair-B 逐字节同构。"""
    frozen_b = read_json(PATH_B)
    updated = snapshot.build_snapshot(items_b, frozen_b["note"])
    assert dumps_json(updated) == dumps_json(frozen_b)
    assert "20" not in updated["note"]  # note 不得含时间戳类内容（宽检：非空且固定）
    assert updated["item_count"] == 21


# --- 三、K10：字段白名单门禁（读、写两条路径都拦） ---------------------------

def _dict_item(**overrides):
    base = dict((f, "") for f in SCHEMA_FIELDS)
    base.update({"source": "gwy", "id": "1", "title": "t", "pubtimeStr": "2026.10.01",
                 "puborg": "o", "url": "u", "summary": "s"})
    base.update(overrides)
    return base


def test_forbidden_fields_rejected_on_write():
    """写入路径：条目含 `content/body/fulltext` 一类字段即拒（K10）。"""
    for field in FORBIDDEN_SNAPSHOT_FIELDS:
        bad = [_dict_item(**{field: "全文内容"})]
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.ensure_item_fields(bad, "快照")
        assert field in str(exc.value)


def test_forbidden_fields_rejected_on_read(tmp_path):
    """读取路径：快照文件里混进禁字段即拒（不静默忽略后照用）。"""
    from policy_radar.serialize import write_json
    obj = read_json(PATH_B)
    obj["items"][0]["fulltext"] = "不应该存在的正文"
    path = os.path.join(str(tmp_path), "bad.json")
    write_json(path, obj)
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.load_snapshot(path)
    assert "fulltext" in str(exc.value)


def test_extra_fields_outside_whitelist_rejected():
    """白名单是**允许清单**不是黑名单：schema 外字段（哪怕不是禁字段）同样拒。"""
    bad = [_dict_item(unknown_field="x")]
    with pytest.raises(snapshot.SnapshotError):
        snapshot.ensure_item_fields(bad, "快照")


# --- 四、快照形态校验（不静默按最宽松规则解析） ------------------------------

def test_load_snapshot_rejects_wrong_format(tmp_path):
    from policy_radar.serialize import write_json
    path = os.path.join(str(tmp_path), "wrong.json")
    write_json(path, {"format": "something-else", "items": []})
    with pytest.raises(snapshot.SnapshotError):
        snapshot.load_snapshot(path)


def test_load_snapshot_rejects_bad_version(tmp_path):
    from policy_radar.serialize import write_json
    obj = read_json(PATH_A)
    obj["format_version"] = 99
    path = os.path.join(str(tmp_path), "v99.json")
    write_json(path, obj)
    with pytest.raises(snapshot.SnapshotError):
        snapshot.load_snapshot(path)


def test_load_snapshot_rejects_item_count_mismatch(tmp_path):
    from policy_radar.serialize import write_json
    obj = read_json(PATH_A)
    obj["item_count"] = 999
    path = os.path.join(str(tmp_path), "count.json")
    write_json(path, obj)
    with pytest.raises(snapshot.SnapshotError):
        snapshot.load_snapshot(path)


# --- 五、K22：输入按 format 分派 ---------------------------------------------

def test_load_items_file_accepts_all_three_formats(tmp_path):
    """三类承载条目的产物都能喂：fetch / snapshot / diff。"""
    from policy_radar.fetch import FETCH_FORMAT, build_output
    from policy_radar.serialize import write_json

    items = _load_items(PATH_B)
    # fetch 产物（借 build_output 组装，channel_meta 合法即可）。
    fetch_obj = build_output(items, [], "2026-10-17T00:00:00")
    fetch_path = os.path.join(str(tmp_path), "fetch.json")
    write_json(fetch_path, fetch_obj)
    assert len(snapshot.load_items_file(fetch_path)) == 21

    # 快照。
    assert len(snapshot.load_items_file(PATH_B)) == 21

    # diff 产物。
    diff_obj = snapshot.build_diff_product(items, items)  # 全重复 → items 空
    diff_path = os.path.join(str(tmp_path), "diff.json")
    write_json(diff_path, diff_obj)
    assert snapshot.load_items_file(diff_path) == []


def test_load_items_file_rejects_unknown_format(tmp_path):
    """未知格式**显式拒绝**（不猜）：parse 产物不能再当输入喂。"""
    from policy_radar.serialize import write_json
    path = os.path.join(str(tmp_path), "unknown.json")
    write_json(path, {"format": "policy-radar-parse", "format_version": 1,
                      "item_count": 0, "items": []})
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.load_items_file(path)
    assert "无法识别" in str(exc.value)


def test_load_items_file_rejects_plain_list(tmp_path):
    """裸 JSON 数组（没有 format 键）不是本仓产物 → 拒绝，不静默当条目读。"""
    from policy_radar.serialize import write_json
    path = os.path.join(str(tmp_path), "list.json")
    write_json(path, [_dict_item()])
    with pytest.raises(snapshot.SnapshotError):
        snapshot.load_items_file(path)


# --- 六、K23：首跑语义 -------------------------------------------------------

def test_first_run_counts_everything_as_new(items_b):
    """省略 --snapshot = 首跑：全部计入新增、重复 0、`first_run` 标记为真。"""
    product = snapshot.build_diff_product([], items_b, first_run=True)
    assert product["first_run"] is True
    assert product["new_count"] == 21
    assert product["dup_count"] == 0
    assert product["previous_item_count"] == 0
    assert product["item_count"] == 21


def test_first_run_flag_defaults_false(items_a, items_b):
    product = snapshot.build_diff_product(items_a, items_b)
    assert product["first_run"] is False


def test_detect_new_is_pure_function_of_inputs(items_a, items_b):
    """判定只依赖输入：重复调用（含乱序输入）结论一致。"""
    r1 = snapshot.detect_new(items_a, items_b)
    r2 = snapshot.detect_new(list(reversed(items_a)), list(reversed(items_b)))
    assert r1 == r2


# --- 七、无时钟参与判定（源码扫描，M2 同款守门） -----------------------------

def test_module_has_no_wall_clock_in_judgment():
    """`snapshot.py` 不得 import 时钟模块（K5"全程不读时钟"的代码级守门）。"""
    path = snapshot.__file__
    with io.open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    for token in ("import time", "from time", "datetime", "time.time",
                  "time.localtime", "strftime"):
        assert token not in src, "snapshot.py 出现时钟引用：%s" % token


def test_module_does_not_import_cases_or_tools():
    """K14/K-tool：生产模块不得 import `cases`（oracle）或 `tools/`（判定 import 语句）。"""
    with io.open(snapshot.__file__, "r", encoding="utf-8") as fh:
        src = fh.read()
    assert not re.search(r"from\s+\.?cases\s+import|import\s+cases\b"
                         r"|policy_radar\.cases", src)
    assert not re.search(r"import\s+_genlib|from\s+.*\btools\b", src)


# --- 八、CLI 层（cmd_diff） --------------------------------------------------

def _run_main(argv):
    from policy_radar.cli import main
    return main(argv)


def test_cmd_diff_end_to_end(tmp_path, capsys):
    """真跑 `diff`：读冻结对 → 写两件产物 → 退出码 0 → 产物与真值一致。"""
    out_diff = os.path.join(str(tmp_path), "diff.json")
    out_snap = os.path.join(str(tmp_path), "snap.json")
    code = _run_main(["diff", "--snapshot", PATH_A, "--current", PATH_B,
                      "--out", out_diff, "--snapshot-out", out_snap])
    assert code == EXIT_OK
    product = read_json(out_diff)
    truth = read_json(os.path.join(DATA, "truth", "diff-truth.json"))
    compare = cases.compare_diff(
        {"new_ids": product["new_ids"], "dup_ids": product["dup_ids"],
         "matched_by": product["matched_by"]}, truth["expect"])
    assert compare["ok"], compare
    updated = read_json(out_snap)
    assert updated["format"] == snapshot.SNAPSHOT_FORMAT
    assert updated["item_count"] == 21
    out = capsys.readouterr().out
    assert "新增 6 条" in out and "重复 15 条" in out


def test_cmd_diff_first_run_via_cli(tmp_path, capsys):
    """CLI 首跑：省略 --snapshot → 全部计入新增，stdout 明示"首次运行"。"""
    out_diff = os.path.join(str(tmp_path), "diff.json")
    out_snap = os.path.join(str(tmp_path), "snap.json")
    code = _run_main(["diff", "--current", PATH_B,
                      "--out", out_diff, "--snapshot-out", out_snap])
    assert code == EXIT_OK
    product = read_json(out_diff)
    assert product["first_run"] is True and product["new_count"] == 21
    assert "首次运行" in capsys.readouterr().out


def test_cmd_diff_missing_snapshot_is_usage_error_not_first_run(tmp_path):
    """K24 反向：给了 --snapshot 但读不到 → exit 2，**不得**静默回落成首跑。"""
    out_diff = os.path.join(str(tmp_path), "diff.json")
    out_snap = os.path.join(str(tmp_path), "snap.json")
    with pytest.raises(UsageError):
        _run_main(["diff", "--snapshot", os.path.join(str(tmp_path), "nope.json"),
                   "--current", PATH_B, "--out", out_diff, "--snapshot-out",
                   out_snap])
    assert not os.path.exists(out_diff)


def test_cmd_diff_rejects_snapshot_without_required_args():
    """--current 缺失 → argparse 拦下（SystemExit 2），不进入判定通路。"""
    with pytest.raises(SystemExit) as exc:
        _run_main(["diff", "--snapshot", PATH_A])
    assert exc.value.code == 2
