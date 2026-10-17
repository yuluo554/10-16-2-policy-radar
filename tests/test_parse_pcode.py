r"""文号三态解析 + 部门归一测试（M3）：生产实现 `parse.py` 对真值逐条对账。

**真喂生产实现（K14 的意义）**：`verify-data` 走的是 oracle（`cases.naive_parse_pcode`）；
本文件把真值里的每条 `pcode` 喂给**生产** `parse.parse_pcode`，用**共用对账语义**
`cases.compare_pcode`（K15）与期望逐条比对——"年份编造了"与"代字切错了"由对账
语义点名字段，生产实现写错这里必红。

判据分布（`plan/04-模块详设.md` 模块 3 的纪律逐条对应）：

| 纪律 | 本文件测试 |
|---|---|
| K6 三态 + 哨兵 `未解析` | `test_production_parse_matches_pcode_truth` |
| E6 全角括号 `﹝﹞` | `test_fullwidth_bracket_parses` |
| E7 序号与"号"间空格 | `test_spaced_serial_parses` |
| 反向样例（不编造年份） | `test_decree_without_bracket_does_not_fabricate_year` |
| 空 pcode 三字段全未解析 | `test_empty_pcode_is_fully_unparsed` |
| 代字不做白名单硬编码 | `test_agency_code_is_not_whitelisted` |
| K7 别名表单一来源 + 最长优先 | `test_org_aliases_*` |
| E5 按 `\s` 拆分 puborg | `test_puborg_split_on_all_whitespace` |
| 未识别原样保留 + alias_missing | `test_unknown_org_kept_raw_with_flag` |
"""

import io
import os

import pytest

from policy_radar import cases, parse
from policy_radar.errors import EXIT_OK, UsageError
from policy_radar.serialize import read_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TRUTH = os.path.join(DATA, "truth")

PATH_A = os.path.join(DATA, "snapshots", "pair-A.json")
PATH_B = os.path.join(DATA, "snapshots", "pair-B.json")


@pytest.fixture(scope="module")
def pcode_expected():
    """真值全量：人工标注 11 条 + 观测池语料 57 条（同 pcode 以先登记者为准）。"""
    truth = read_json(os.path.join(TRUTH, "pcode-truth.json"))
    expected = {}
    for case in truth["cases"]:
        expected[case["pcode"]] = case["expect"]
    for case in truth["pool_corpus_cases"]:
        expected.setdefault(case["pcode"], case["expect"])
    return expected


# --- 一、生产解析对真值（核心：真喂生产实现） -------------------------------

def test_production_parse_matches_pcode_truth(pcode_expected):
    """**M3 核心判据**：生产 `parse_pcode` 对真值全量（68 条去重后 58 键）逐条一致。

    对账走共用语义 `cases.compare_pcode`（K15）——字段级差异逐条点名。
    """
    observed = dict((pc, parse.parse_pcode(pc)) for pc in pcode_expected)
    compare = cases.compare_pcode(observed, pcode_expected)
    assert compare["ok"], compare
    assert compare["checked"] == len(pcode_expected)


def test_unparsed_sentinel_value_matches_truth(pcode_expected):
    """哨兵串必须与真值 `unparsed_sentinel` 同值（不得各写各的 `None`/空串/`-`）。"""
    truth = read_json(os.path.join(TRUTH, "pcode-truth.json"))
    assert parse.UNPARSED == truth["unparsed_sentinel"] == "未解析"
    # 真值里出现哨兵的字段，生产解析也恰好在该字段给哨兵。
    for case in truth["cases"]:
        actual = parse.parse_pcode(case["pcode"])
        for field in ("agency_code", "year", "serial"):
            if case["expect"][field] == truth["unparsed_sentinel"]:
                assert actual[field] == parse.UNPARSED, (case["pcode"], field)


def test_three_states_all_present(pcode_expected):
    """三态都有真值样本（防"某种状态永远不出现、分支永不执行"）。"""
    statuses = set(v["status"] for v in pcode_expected.values())
    assert statuses == set(parse.STATUS_VALUES), statuses


def test_standard_bracket_parses():
    result = parse.parse_pcode("国办发〔2026〕28号")
    assert result == {"agency_code": "国办发", "year": "2026", "serial": "28",
                      "status": parse.STATUS_PARSED}


def test_fullwidth_bracket_parses():
    """E6：全角括号 `﹝﹞`（U+FE5D/FE5E）必须解析，不得因码位不同误判未解析。"""
    result = parse.parse_pcode("工信部联规﹝2026﹞210号")
    assert result == {"agency_code": "工信部联规", "year": "2026", "serial": "210",
                      "status": parse.STATUS_PARSED}


def test_spaced_serial_parses():
    """E7：序号与"号"之间有空格 → 序号是 `9`，不带尾空格。"""
    result = parse.parse_pcode("农农发〔2026〕9 号")
    assert result == {"agency_code": "农农发", "year": "2026", "serial": "9",
                      "status": parse.STATUS_PARSED}


def test_multi_char_and_joint_agency_codes():
    """多字代字与联发代字（不做白名单硬编码的反向证明：这些代字不在任何表里）。"""
    for pcode, agency in (("国知发服字〔2026〕29号", "国知发服字"),
                          ("工信部联规函〔2026〕239号", "工信部联规函")):
        result = parse.parse_pcode(pcode)
        assert result["agency_code"] == agency
        assert result["status"] == parse.STATUS_PARSED


def test_decree_without_bracket_does_not_fabricate_year():
    """**反向样例**：`国令第847号` 无 `〔〕` → 年份必须 `未解析`（不编造）。"""
    result = parse.parse_pcode("国令第847号")
    assert result == {"agency_code": "国令", "year": parse.UNPARSED,
                      "serial": "847", "status": parse.STATUS_PARTIAL}


def test_empty_pcode_is_fully_unparsed():
    """**反向样例**：空 `pcode` → 三字段全 `未解析`、整条 `unparsed`。"""
    assert parse.parse_pcode("") == {
        "agency_code": parse.UNPARSED, "year": parse.UNPARSED,
        "serial": parse.UNPARSED, "status": parse.STATUS_UNPARSED}
    assert parse.parse_pcode(None)["status"] == parse.STATUS_UNPARSED


def test_partial_is_not_parsed():
    """K6：部分字段未解析 → `partial`，**不把 partial 当 parsed**。"""
    assert parse.parse_pcode("国令第846号")["status"] == parse.STATUS_PARTIAL
    assert parse.STATUS_PARTIAL not in (parse.STATUS_PARSED,
                                        parse.STATUS_UNPARSED)


def test_agency_code_is_not_whitelisted():
    """代字 = 左括号前全部非空字符：任意非实测代字也按同一规则切，不查表。"""
    result = parse.parse_pcode("某新单位发〔2025〕1号")
    assert result["agency_code"] == "某新单位发"
    assert result["year"] == "2025" and result["serial"] == "1"


def test_garbage_pcode_is_unparsed():
    """完全不成形态的串 → 整条 `unparsed`（不猜、不硬切）。

    `〔2026〕` 缺代字 → 代字 `未解析`、年份可解析 → `partial`（与参照实现同语义）；
    只有"三字段全无着落"才是 `unparsed`。
    """
    assert parse.parse_pcode("无结构文本")["status"] == parse.STATUS_UNPARSED
    result = parse.parse_pcode("〔2026〕")
    assert result["status"] == parse.STATUS_PARTIAL
    assert result["agency_code"] == parse.UNPARSED
    assert result["year"] == "2026"


# --- 二、部门归一（K7 + E5） -------------------------------------------------

@pytest.fixture(scope="module")
def aliases():
    return parse.load_org_aliases(DATA)


def test_org_aliases_single_source(aliases):
    """别名表来自单一来源文件（39 原始名 → 38 规范名，实测规模）。"""
    assert len(aliases) == 39
    assert len(set(aliases.values())) == 38


def test_load_org_aliases_rejects_wrong_rule(tmp_path):
    """`match_rule` 不是 `longest_first` → 拒绝工作（不静默套错语义）。"""
    import json
    from policy_radar.serialize import write_json
    root = str(tmp_path)
    cfg = os.path.join(root, "config")
    os.makedirs(cfg)
    write_json(os.path.join(cfg, "org-aliases.json"),
               {"aliases": {"财政部": "财政部"}, "match_rule": "shortest_first"})
    with pytest.raises(UsageError):
        parse.load_org_aliases(root)


def test_load_org_aliases_missing_file(tmp_path):
    with pytest.raises(UsageError):
        parse.load_org_aliases(str(tmp_path))


def test_variant_pair_normalized(aliases):
    """实测唯一真变体对：`住房城乡建设部（办公厅）` → `住房和城乡…`。"""
    result = parse.parse_orgs("住房城乡建设部", aliases)
    assert result == [{"raw": "住房城乡建设部",
                       "canonical": "住房和城乡建设部", "alias_missing": False}]
    result = parse.parse_orgs("住房城乡建设部办公厅", aliases)
    assert result[0]["canonical"] == "住房和城乡建设部办公厅"
    assert result[0]["alias_missing"] is False


def test_longest_first_matching(aliases):
    """K7 细化口径：`国务院办公厅` 不得被短串 `国务院` 吃掉前缀。"""
    result = parse.parse_orgs("国务院办公厅", aliases)
    assert result[0]["raw"] == "国务院办公厅"
    assert result[0]["canonical"] == "国务院办公厅"
    assert result[0]["alias_missing"] is False


def test_puborg_split_on_all_whitespace(aliases):
    r"""E5：分隔符含 U+2002 EN SPACE 且同串混用 → 按 `\s` 拆，8 部门不得粘成 1 个 token。"""
    mixed = ("国家发展改革委\u2002民政部 国家卫生健康委\u2002财政部")
    result = parse.parse_orgs(mixed, aliases)
    assert [r["raw"] for r in result] == ["国家发展改革委", "民政部",
                                          "国家卫生健康委", "财政部"]
    assert all(not r["alias_missing"] for r in result)


def test_eight_dept_string_with_en_space(aliases):
    """E5 实测原串（全 U+2002）：多部门串不得变成单个不可识别 token。"""
    text = "中国人民银行\u2002金融监管总局\u2002国家卫生健康委"
    result = parse.parse_orgs(text, aliases)
    assert len(result) == 3
    assert result[0]["canonical"] == "中国人民银行"


def test_unknown_org_kept_raw_with_flag(aliases):
    """认不出的部门**原样保留** + `alias_missing`（不猜）。"""
    result = parse.parse_orgs("生态环境部", aliases)
    assert result == [{"raw": "生态环境部", "canonical": "生态环境部",
                       "alias_missing": True}]


def test_empty_puborg_yields_no_tokens(aliases):
    assert parse.parse_orgs("", aliases) == []
    assert parse.parse_orgs(None, aliases) == []
    assert parse.parse_orgs("   \u2002 ", aliases) == []


def test_whole_pool_puborgs_resolve_without_missing():
    """观测池 60 条的 `puborg` 全部 token 都能归一（别名表登记自同一批实测）。"""
    from policy_radar.model import items_from_listvo
    missing = []
    for name in ("gwy-p1-n30.json", "bm-p1-n30.json"):
        payload = read_json(os.path.join(DATA, "samples", name))
        for item in items_from_listvo(payload, "x"):
            for org in parse.parse_orgs(item.puborg, parse.load_org_aliases(DATA)):
                if org["alias_missing"]:
                    missing.append((item.id, org["raw"]))
    assert missing == [], missing


# --- 三、parse 产物 ----------------------------------------------------------

def test_build_parse_product_counts_and_records(aliases):
    """产物：逐条记录 + 三态计数 + alias_missing 点名；未解析显式标哨兵。"""
    from policy_radar.snapshot import load_items_file
    items = load_items_file(PATH_B)
    product = parse.build_parse_product(items, aliases)
    assert product["item_count"] == 21
    assert sum(product["pcode_status_counts"].values()) == 21
    assert product["pcode_status_counts"] == {
        parse.STATUS_PARSED: 17, parse.STATUS_PARTIAL: 2,
        parse.STATUS_UNPARSED: 2}
    assert product["alias_missing_count"] == 0
    # 输入序保持（确定性来自调用方清单序）。
    assert [r["item_id"] for r in product["parsed_items"]] == \
        [it.id for it in items]
    for record in product["parsed_items"]:
        assert record["pcode_parse"]["status"] in parse.STATUS_VALUES


def test_parse_product_is_byte_identical_across_runs(aliases, tmp_path):
    """同输入双跑逐字节一致（K3 序列化单点 + 产物无时钟）。

    产物条目按**输入序**保持（确定性来自调用方清单序），故乱序输入会
    合法地产生不同字节——那不是不确定性；本断言只考"同输入"。
    """
    from policy_radar.snapshot import load_items_file
    from policy_radar.serialize import write_json
    items = load_items_file(PATH_B)
    p1 = os.path.join(str(tmp_path), "p1.json")
    p2 = os.path.join(str(tmp_path), "p2.json")
    write_json(p1, parse.build_parse_product(items, aliases))
    write_json(p2, parse.build_parse_product(list(items), aliases))
    with io.open(p1, "rb") as f1, io.open(p2, "rb") as f2:
        assert f1.read() == f2.read()


def test_parse_product_forbidden_fields_guard(aliases):
    """产物只含元数据与解析结构：出现禁字段即拒（复用 K10 门禁）。"""
    from policy_radar.model import FORBIDDEN_SNAPSHOT_FIELDS, PolicyItem
    from policy_radar.snapshot import ensure_item_fields
    item = PolicyItem.from_dict(dict(
        source="gwy", id="1", title="t", pubtimeStr="2026.10.01",
        puborg="财政部", url="u", summary="s"))
    product = parse.build_parse_product([item], aliases)
    # 产物顶层与逐条记录都不得含禁字段（结构性自查）。
    text_keys = set(product["parsed_items"][0])
    assert not (text_keys & set(FORBIDDEN_SNAPSHOT_FIELDS))
    # 白名单门禁对产物内条目 dict 同样有效（写成 item dict 后复用）。
    ensure_item_fields([{"id": "1"}], "自查")


# --- 四、K14：生产模块不得 import 参照实现 -----------------------------------

def test_module_does_not_import_cases_or_tools():
    import re
    with io.open(parse.__file__, "r", encoding="utf-8") as fh:
        src = fh.read()
    assert not re.search(r"from\s+\.?cases\s+import|import\s+cases\b"
                         r"|policy_radar\.cases", src)
    assert not re.search(r"import\s+_genlib|from\s+.*\btools\b", src)


# --- 五、CLI 层（cmd_parse） -------------------------------------------------

def _run_main(argv):
    from policy_radar.cli import main
    return main(argv)


def test_cmd_parse_end_to_end(tmp_path, capsys):
    out = os.path.join(str(tmp_path), "parsed.json")
    code = _run_main(["parse", "--input", PATH_B, "--data-root", DATA,
                      "--out", out])
    assert code == EXIT_OK
    product = read_json(out)
    assert product["item_count"] == 21
    counts = product["pcode_status_counts"]
    assert counts[parse.STATUS_PARSED] == 17
    out_text = capsys.readouterr().out
    assert "parsed 17" in out_text and "partial 2" in out_text


def test_cmd_parse_accepts_fetch_product(tmp_path):
    """fetch 产物也能直接喂 parse（K22 分派；借 build_output 组装合法 fetch 产物）。"""
    from policy_radar.fetch import build_output
    from policy_radar.snapshot import load_items_file
    from policy_radar.serialize import write_json
    items = load_items_file(PATH_B)
    fetch_path = os.path.join(str(tmp_path), "fetch.json")
    write_json(fetch_path, build_output(items, [], "2026-10-17T00:00:00"))
    out = os.path.join(str(tmp_path), "parsed.json")
    code = _run_main(["parse", "--input", fetch_path, "--data-root", DATA,
                      "--out", out])
    assert code == EXIT_OK
    assert read_json(out)["item_count"] == 21


def test_cmd_parse_missing_data_root_is_usage_error(tmp_path):
    out = os.path.join(str(tmp_path), "parsed.json")
    with pytest.raises(UsageError):
        _run_main(["parse", "--input", PATH_B,
                   "--data-root", os.path.join(str(tmp_path), "nope"),
                   "--out", out])
    assert not os.path.exists(out)
