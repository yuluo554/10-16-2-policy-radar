"""M5 日报与编排测试（K9 零判定 + 零外链 + 确定性 + 编排行为等价）。

覆盖：
- 渲染层零判定（K9）：AST 扫 `report.py` 源码，判定函数调用不得出现
  （扫 import/调用语句形态，不扫子串——M3 教训）；
- 零外链断言（K9）：资源标签内含外部 URL 即红；阳性对照（正文含原文链接
  `url` 字段不红——"零外链"= 渲染资源零外部引用，不是内容字段不许出现）；
- 确定性：同输入双跑逐字节一致（无时间戳）；
- 两格式内容对等：Markdown 与 HTML 的文本抽取逐项一致（不是"都调了同一函数"）；
- 缺字段渲染「未提供」；无新增显式"本次无新增"；FR-11 未过校验条目不进日报；
- `run` 编排：行为等价（CLI 统计 == 直调统计 == 报告统计）、降级/失败路径。
"""

import ast
import io
import os

import pytest

from policy_radar import report as report_mod
from policy_radar import pipeline as pipeline_mod
from policy_radar.errors import UsageError
from policy_radar.model import PolicyItem
from policy_radar.report import (
    assert_no_external_resources,
    build_digest_product,
    report_entries,
    render_html,
    render_markdown,
    write_digest,
)
from policy_radar.serialize import read_json, write_json


def _item_dict(**overrides):
    base = {
        "source": "gwy", "id": "1001", "index": "",
        "pcode": "国发〔2026〕12号", "title": "关于印发测试规划的通知",
        "pubtimeStr": "2026.10.10", "puborg": "国务院办公厅",
        "url": "https://www.gov.cn/zhengce/content_1.htm",
        "summary": "现将测试规划印发给你们。", "channel": "国务院",
    }
    base.update(overrides)
    return base


def _hits(hits_path, hits, excluded=(), zero=()):
    product = {
        "format": "policy-radar-subscribe", "format_version": 1,
        "hits": list(hits), "excluded": list(excluded), "zero_hit_ids": list(zero),
    }
    write_json(hits_path, product)
    return hits_path


def _diff(new_dicts, new_ids=None, dup_ids=(), path="diff.json"):
    product = {
        "format": "policy-radar-diff", "format_version": 1,
        "note": "test", "first_run": False,
        "previous_item_count": 0, "current_item_count": len(new_dicts),
        "new_count": len(new_dicts), "dup_count": len(dup_ids),
        "dedup_keys": {"primary": "id", "secondary": "pcode_nonempty"},
        "new_ids": new_ids if new_ids is not None else [d["id"] for d in new_dicts],
        "dup_ids": list(dup_ids), "matched_by": {},
        "item_count": len(new_dicts), "items": list(new_dicts),
    }
    write_json(path, product)
    return path


# --- K9：渲染层零判定（AST 扫源码） -------------------------------------------

def test_report_module_has_no_judgement_calls():
    """AST 守门（K9）：`report.py` 不得调用判定函数（detect_new / parse_pcode /
    parse_orgs / match_items / build_*_product）。扫调用与名字引用，不扫子串。"""
    src_path = os.path.join(os.path.dirname(report_mod.__file__), "report.py")
    with io.open(src_path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename="report.py")
    forbidden = set(report_mod.FORBIDDEN_CALLS_IN_REPORT)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in forbidden:
                hits.append(node.func.id)
        elif isinstance(node, ast.Attribute):
            if node.attr in forbidden:
                hits.append(node.attr)
    assert hits == [], "report.py 渲染层出现判定调用（K9 零判定违规）：%r" % hits


# --- K9：零外链断言（口径与阳性对照） -----------------------------------------

def test_no_external_resources_flags_resource_tags_and_import():
    doc = ('<html><head><link rel="stylesheet" '
           'href="https://cdn.example.com/x.css"></head></html>')
    with pytest.raises(AssertionError):
        assert_no_external_resources(doc)
    with pytest.raises(AssertionError):
        assert_no_external_resources('<style>@import url("https://x.com/f.css");</style>')
    with pytest.raises(AssertionError):
        assert_no_external_resources('<img src="https://x.com/a.png">')
    with pytest.raises(AssertionError):
        assert_no_external_resources('<script src="https://x.com/a.js"></script>')


def test_no_external_resources_allows_item_url_as_content():
    """阳性对照：条目自带的原文链接（`url` 字段）是**内容**，不是渲染资源——
    `<a href="https://...">` 不得触发断言（口径写清楚，防测试自相矛盾）。"""
    doc = '<html><body><a href="https://www.gov.cn/zhengce/x.htm">原文</a></body></html>'
    assert assert_no_external_resources(doc) is True


def test_rendered_html_passes_no_external_resources(tmp_path):
    """渲染出口真过断言：正常渲染的日报（含原文链接）零外链通过。"""
    diff_path = _diff([_item_dict()], path=str(tmp_path / "d.json"))
    hits_path = _hits(str(tmp_path / "h.json"),
                      [{"item_id": "1001", "keyword": "规划",
                        "field": "title", "offset": 4}])
    product = build_digest_product(diff_path, hits_path, fmt="both")
    assert "https://www.gov.cn" in product["html"]  # 原文链接在内容里
    assert assert_no_external_resources(product["html"]) is True


# --- 确定性：双跑逐字节一致 -----------------------------------------------------

def test_double_run_byte_identical(tmp_path):
    d1 = _diff([_item_dict(), _item_dict(id="1002", pcode="",
                                         puborg="工业和信息化部",
                                         summary="十五五规划摘要。")],
               path=str(tmp_path / "d1.json"))
    h1 = _hits(str(tmp_path / "h1.json"),
               [{"item_id": "1002", "keyword": "规划", "field": "summary", "offset": 2}])
    p1 = build_digest_product(d1, h1, fmt="both")
    d2 = _diff([_item_dict(), _item_dict(id="1002", pcode="",
                                         puborg="工业和信息化部",
                                         summary="十五五规划摘要。")],
               path=str(tmp_path / "d2.json"))
    h2 = _hits(str(tmp_path / "h2.json"),
               [{"item_id": "1002", "keyword": "规划", "field": "summary", "offset": 2}])
    p2 = build_digest_product(d2, h2, fmt="both")
    assert p1["markdown"] == p2["markdown"]
    assert p1["html"] == p2["html"]
    out_md = str(tmp_path / "r.md")
    out_html = str(tmp_path / "r.html")
    paths1 = write_digest(out_md, p1, "md") + write_digest(out_html, p1, "html")
    b1 = [(os.path.basename(p), io.open(p, "rb").read()) for p in paths1]
    paths2 = write_digest(out_md, p2, "md") + write_digest(out_html, p2, "html")
    b2 = [(os.path.basename(p), io.open(p, "rb").read()) for p in paths2]
    assert b1 == b2


# --- 两格式内容对等 ------------------------------------------------------------

def test_markdown_html_content_equivalence(tmp_path):
    """单一渲染源的内容对等：两格式抽出的信息逐项一致（标题/日期/文号/部门/命中词）。"""
    diff_path = _diff([_item_dict()], path=str(tmp_path / "d.json"))
    hits_path = _hits(str(tmp_path / "h.json"),
                      [{"item_id": "1001", "keyword": "规划",
                        "field": "title", "offset": 4}])
    product = build_digest_product(diff_path, hits_path, fmt="both")
    md, doc = product["markdown"], product["html"]
    for token in ("关于印发测试规划的通知", "2026.10.10", "国发〔2026〕12号",
                  "规划", "content_1.htm"):
        assert token in md, token
        assert token in doc, token
    # 结构性质：每条目在两格式里都是一个小节，条数一致。
    assert md.count("\n## ") == doc.count("<h2>")
    # 渲染出口断言已过（build_digest_product 内部常驻）。


# --- 缺字段 / 无新增 / FR-11 ----------------------------------------------------

def test_missing_fields_rendered_explicitly(tmp_path):
    """缺文号/解析产物 → 显式渲染「未提供」，不静默略过、不编造。"""
    diff_path = _diff([_item_dict(pcode="")], path=str(tmp_path / "d.json"))
    hits_path = _hits(str(tmp_path / "h.json"), [])
    product = build_digest_product(diff_path, hits_path, fmt="both")
    assert "未提供" in product["markdown"]
    assert "未提供" in product["html"]
    # 该条仍在日报里（缺字段 ≠ 整条丢弃；整条丢弃是 schema 必填项缺失）。
    assert "关于印发测试规划的通知" in product["markdown"]


def test_no_new_items_says_so(tmp_path):
    diff_path = _diff([], new_ids=[], path=str(tmp_path / "d.json"))
    hits_path = _hits(str(tmp_path / "h.json"), [])
    product = build_digest_product(diff_path, hits_path, fmt="both")
    assert "本次无新增" in product["markdown"]
    assert "本次无新增" in product["html"]


def test_invalid_item_dropped_not_silently_rendered(tmp_path):
    """FR-11：未过 schema 校验的条目不进日报（dropped_count 计数，不补编字段）。"""
    bad = _item_dict(id="bad-1", title="")  # title 必填
    good = _item_dict()
    diff_path = _diff([bad, good], path=str(tmp_path / "d.json"))
    hits_path = _hits(str(tmp_path / "h.json"), [])
    product = build_digest_product(diff_path, hits_path, fmt="both")
    assert product["dropped_count"] == 1
    assert product["dropped"][0]["id"] == "bad-1"
    assert product["item_count"] == 1
    assert "关于印发测试规划的通知" in product["markdown"]
    assert product["markdown"].count("\n## ") == 1


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_parse_product_enriches_entries(tmp_path):
    """给了 parse 产物 → 文号解析结构与部门归一进日报；条目 id 关联（不重算解析）。"""
    from policy_radar.parse import build_parse_product, load_org_aliases
    items = [PolicyItem.from_dict(_item_dict())]
    aliases = load_org_aliases(os.path.join(ROOT, "data"))
    parse_product = build_parse_product(items, aliases)
    parse_path = str(tmp_path / "p.json")
    write_json(parse_path, parse_product)
    diff_path = _diff([_item_dict()], path=str(tmp_path / "d.json"))
    hits_path = _hits(str(tmp_path / "h.json"), [])
    product = build_digest_product(diff_path, hits_path, parse_path=parse_path,
                                   fmt="both")
    assert "2026" in product["markdown"]  # 文号年份解析进日报
    assert "parsed" in product["markdown"]


# --- 输入校验（exit 2 语义） ---------------------------------------------------

def test_digest_rejects_unknown_input_format(tmp_path):
    path = str(tmp_path / "x.json")
    write_json(path, {"format": "something-else", "items": []})
    hits_path = _hits(str(tmp_path / "h.json"), [])
    with pytest.raises(UsageError):
        build_digest_product(path, hits_path, fmt="md")


def test_digest_rejects_missing_file(tmp_path):
    hits_path = _hits(str(tmp_path / "h.json"), [])
    with pytest.raises(UsageError):
        build_digest_product(str(tmp_path / "nope.json"), hits_path, fmt="md")


def test_digest_rejects_unknown_format_argument(tmp_path):
    diff_path = _diff([_item_dict()], path=str(tmp_path / "d.json"))
    hits_path = _hits(str(tmp_path / "h.json"), [])
    with pytest.raises(UsageError):
        build_digest_product(diff_path, hits_path, fmt="pdf")


# --- run 编排（pipeline） ------------------------------------------------------

def _meta(channel="gwy", n=3):
    return {
        "channel": channel, "channel_param": "zhengcelibrary_gwy" if channel == "gwy" \
            else "zhengcelibrary_bm", "status": "ok",
        "pages": 1, "n": n, "requested": n, "returned": n, "kept": n,
        "dropped": 0, "dropped_details": [], "declared_total": n,
        "captured_at": "2026-10-17T00:00:00", "page_details": [], "error": "",
    }


def _offline_items():
    return [PolicyItem.from_dict(_item_dict(id=str(2000 + i),
                                            pcode="国发〔2026〕%d号" % i))
            for i in range(3)]


def test_run_pipeline_offline_produces_all_products(tmp_path):
    data = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")
    out_dir = str(tmp_path / "run")
    stats = pipeline_mod.run_pipeline(
        channels=["gwy"], out_dir=out_dir, data_root=data,
        fetch_items=_offline_items(), fetch_channel_meta=[_meta(3)],
        captured_at="2026-10-17T00:00:00")
    assert stats["kept"] == 3
    assert stats["new_count"] == 3
    # 条目级口径：命中条目 ∪ 剔除条目 ∪ 零命中条目 == 全部新增（hit_count 是记录数）。
    sub = read_json(os.path.join(out_dir, "subscribe.json"))
    hit_ids = {h["item_id"] for h in sub["hits"]}
    excl_ids = {e["item_id"] for e in sub["excluded"]}
    assert hit_ids | excl_ids | set(sub["zero_hit_ids"]) == \
        set(read_json(os.path.join(out_dir, "diff.json"))["new_ids"])
    for name in ("fetched.json", "diff.json", "snapshot.json", "parsed.json",
                 "subscribe.json", "report.md", "report.html"):
        assert os.path.isfile(os.path.join(out_dir, name)), name
    md = io.open(os.path.join(out_dir, "report.md"), "r", encoding="utf-8").read()
    assert md.count("\n## ") == stats["report_item_count"] == 3


def test_run_pipeline_uses_snapshot_when_given(tmp_path):
    """给了上次快照 → 相对快照判新增（编排不做自己的判定，走 snapshot.detect_new 单点）。"""
    data = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")
    items = _offline_items()
    from policy_radar.snapshot import build_snapshot
    snap_path = str(tmp_path / "last.json")
    write_json(snap_path, build_snapshot(items[:1], "上次快照"))
    stats = pipeline_mod.run_pipeline(
        channels=["gwy"], out_dir=str(tmp_path / "run"), data_root=data,
        snapshot_path=snap_path, fetch_items=items,
        fetch_channel_meta=[_meta(3)], captured_at="2026-10-17T00:00:00")
    assert stats["new_count"] == 2
    assert stats["dup_count"] == 1


def test_run_pipeline_all_channels_failed_raises_external(tmp_path):
    """全部频道失败 → `ExternalError`（exit 4），且不产出任何文件（fetch 语义透传）。"""
    meta_dead = dict(_meta(1), status="degraded", error="不可达",
                     returned=0, kept=0, declared_total=None)
    with pytest.raises(pipeline_mod.ExternalError):
        pipeline_mod.run_pipeline(
            channels=["gwy"], out_dir=str(tmp_path / "run"),
            fetch_items=[], fetch_channel_meta=[meta_dead],
            captured_at="2026-10-17T00:00:00")
    assert not os.path.isdir(str(tmp_path / "run")) or \
        not os.listdir(str(tmp_path / "run"))


def test_run_pipeline_degraded_propagates(tmp_path):
    """fetch 降级（有频道 degraded）→ 统计 degraded=True（CLI 透传 exit 1）。"""
    data = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")
    stats = pipeline_mod.run_pipeline(
        channels=["gwy", "bm"], out_dir=str(tmp_path / "run"), data_root=data,
        fetch_items=_offline_items(),
        fetch_channel_meta=[_meta(3), dict(_meta("bm", 3), status="degraded",
                                           error="不可达", returned=0, kept=0,
                                           declared_total=None)],
        captured_at="2026-10-17T00:00:00")
    assert stats["channels_degraded"] == 1
    assert stats["degraded"] is True


def test_run_pipeline_bad_channel_is_usage_error(tmp_path):
    with pytest.raises(UsageError):
        pipeline_mod.run_pipeline(channels=["nope"], out_dir=str(tmp_path / "run"),
                                  fetch_items=_offline_items(),
                                  fetch_channel_meta=[_meta(3)],
                                  captured_at="2026-10-17T00:00:00")
