"""统一 schema 与 PolicyItem 测试（K1 / K10 / FR-11）。

覆盖：字段集合与顺序 / 必填校验（未通过不得落库）/ 日期形态 / API 条目转换
（**取数路径 `searchVO.listVO`，顶层 `data` 为 null**）/ 快照禁全文边界。
"""

import pytest

from policy_radar.model import (
    CHANNELS, FORBIDDEN_SNAPSHOT_FIELDS, REQUIRED_FIELDS, SCHEMA_FIELDS,
    PolicyItem, item_from_api, items_from_listvo, total_count,
)


# --- schema 常量 ------------------------------------------------------------

def test_schema_fields_exact_and_ordered():
    assert SCHEMA_FIELDS == (
        "source", "id", "index", "pcode", "title", "pubtimeStr",
        "puborg", "url", "summary", "channel",
    )


def test_required_fields_subset_of_schema():
    assert set(REQUIRED_FIELDS) <= set(SCHEMA_FIELDS)


def test_required_fields_excludes_optional_pcode_index_channel():
    """`pcode`/`index`/`channel` 不是必填（实测 pcode 可空、部委 index 为空）。"""
    for optional in ("pcode", "index", "channel"):
        assert optional not in REQUIRED_FIELDS


def test_channels_single_source():
    assert CHANNELS == {"gwy": "国务院", "bm": "部委"}


def test_forbidden_snapshot_fields_cover_fulltext_names():
    """边界 2：快照不得落全文——禁字段表必须覆盖常见全文命名。"""
    for name in ("content", "body", "fulltext"):
        assert name in FORBIDDEN_SNAPSHOT_FIELDS


# --- PolicyItem 基本行为 ----------------------------------------------------

def _item(**kw):
    base = dict(
        source="gwy", id="26772701", title="国务院关于《X》的批复",
        pubtimeStr="2026.10.08", puborg="国务院",
        url="https://www.gov.cn/zhengce/zhengceku/202610/content_7082738.htm",
        summary="摘要正文", pcode="国函〔2026〕105号", index="000014349/2026-00075",
    )
    base.update(kw)
    return PolicyItem(**base)


def test_to_dict_ordered_by_schema():
    d = _item().to_dict()
    assert tuple(d.keys()) == SCHEMA_FIELDS


def test_channel_defaults_from_source():
    assert _item().channel == "国务院"
    assert _item(source="bm").channel == "部委"


def test_roundtrip_from_dict():
    original = _item()
    assert PolicyItem.from_dict(original.to_dict()) == original


def test_from_dict_ignores_unknown_fields():
    d = _item().to_dict()
    d["extra_field"] = "不该进模型"
    assert "extra_field" not in PolicyItem.from_dict(d).to_dict()


def test_validate_passes_on_complete_item():
    assert _item().validate() == []


def test_validate_reports_missing_required():
    item = _item(puborg="")
    assert item.validate() == ["puborg"]


def test_validate_empty_pcode_is_allowed():
    """实测部委 3/30 pcode 为空——空 pcode 不得导致校验失败。"""
    assert _item(pcode="").validate() == []


def test_validate_empty_index_is_allowed():
    """实测部委 index 30/30 为空——空 index 不得导致校验失败。"""
    assert _item(index="", source="bm").validate() == []


def test_validate_all_missing():
    item = PolicyItem(source="", id="", title="", pubtimeStr="",
                      puborg="", url="", summary="")
    assert set(item.validate()) == set(REQUIRED_FIELDS)


@pytest.mark.parametrize("date,ok", [
    ("2026.10.08", True), ("2026.09.30", True),
    ("2026-10-08", False), ("20261008", False), ("", False), ("2026.13.45", False),
])
def test_date_valid(date, ok):
    assert _item(pubtimeStr=date).date_valid() is ok


def test_equality_and_hash():
    assert _item() == _item()
    assert _item(id="other") != _item()
    assert len({_item(), _item(), _item(id="x")}) == 2


# --- API 转换（取数路径） ---------------------------------------------------

def _payload(items, total=6222):
    return {"code": 200, "data": None,
            "searchVO": {"totalCount": total, "listVO": items}}


def test_items_from_listvo_uses_searchvo_listvo_path():
    payload = _payload([{"id": "1", "title": "T", "pubtimeStr": "2026.10.08",
                         "puborg": "国务院", "url": "https://x", "summary": "s",
                         "pcode": "国办发〔2026〕28号", "index": "000014349/2026-00001"}])
    items = items_from_listvo(payload, "gwy")
    assert len(items) == 1
    assert items[0].source == "gwy"
    assert items[0].pcode == "国办发〔2026〕28号"


def test_items_from_listvo_rejects_missing_searchvo():
    """结构异常显式报错（不静默按最宽松规则解析）。"""
    with pytest.raises(ValueError):
        items_from_listvo({"code": 200, "data": None}, "gwy")


def test_items_from_listvo_rejects_missing_listvo():
    with pytest.raises(ValueError):
        items_from_listvo({"searchVO": {"totalCount": 1}}, "gwy")


def test_items_from_listvo_rejects_non_dict():
    with pytest.raises(ValueError):
        items_from_listvo([], "gwy")


def test_items_from_listvo_skips_non_dict_entries():
    payload = _payload([{"id": "1", "title": "T", "pubtimeStr": "2026.10.08",
                         "puborg": "国务院", "url": "https://x", "summary": "s"},
                        "not-a-dict", None])
    assert len(items_from_listvo(payload, "gwy")) == 1


def test_item_from_api_handles_none_values():
    """API 字段可能是 JSON null（实测 `code`/`piclinksurl` 等为 ""，但须防 None）。"""
    item = item_from_api({"id": None, "title": None, "pcode": None}, "bm")
    assert item.id == ""
    assert item.title == ""
    assert item.pcode == ""


def test_total_count_reads_searchvo():
    assert total_count(_payload([], total=12803)) == 12803


def test_total_count_missing_returns_none():
    assert total_count({}) is None


def test_top_level_data_is_null_in_real_api_shape():
    """自证：真实 API 形态里顶层 `data` 是 null——不得按 data 取条目。"""
    payload = _payload([{"id": "1"}])
    assert payload["data"] is None
    assert payload["searchVO"]["listVO"]


# --- 快照禁全文边界（K10） -------------------------------------------------

def test_snapshot_payload_has_no_forbidden_fields():
    """构造一份合法快照，断言不含任何禁字段（守门测试在 M3 对真实快照复跑）。"""
    snapshot = {"items": [_item().to_dict()], "meta": {"count": 1}}
    flat_keys = set()
    for it in snapshot["items"]:
        flat_keys |= set(it.keys())
    assert flat_keys & set(FORBIDDEN_SNAPSHOT_FIELDS) == set()
