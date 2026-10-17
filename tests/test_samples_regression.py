"""真实 API 样本离线回归（M1 DoD #7 的验证面）。

**绝不打真站点**（真站点不可复现、且会触发对方风控）：用 `data/samples/` 里**冻结的
真实响应**喂 `model.items_from_listvo()`，断言 M0 实测的取数路径与字段形态成立。

这组测试的价值：它是"生产取数路径"与"真实服务器返回形态"之间的**离线锚点**——
一旦 API 结构漂移（例如条目从 `searchVO.listVO` 挪走、或顶层 `data` 不再是 null），
本文件会红，而不是等到 M2 抓取时才发现。

覆盖：
1. 取数路径 = `searchVO.listVO`，顶层 `data` 为 null（决策 D13）；
2. 两频道条目都能转成 `PolicyItem` 且必填字段齐备；
3. 实测形态锚点：部委 `index` 全空、`pcode` 可空、`fwzh/wenhao/wjlx` 全空；
4. 真实文号覆盖 M0/M1 记录的形态（含全角括号、序号含空格）；
5. `puborg` 多部门分隔符含 U+2002 EN SPACE（M1 实测 E5）；
6. 样本 sha256 与登记值一致（字节冻结）；
7. **M2 抓取器离线回归**：`fetch` 真跑（假传输层只回放下面这些冻结字节）产出的
   条目与留档样本**逐字段一致**，产物 schema 锁定为 `SCHEMA_FIELDS`。
"""

import io
import json
import os
import re

import pytest

from policy_radar.fetch import build_url, fetch_all
from policy_radar.model import (
    FORBIDDEN_SNAPSHOT_FIELDS, SCHEMA_FIELDS, PolicyItem, items_from_listvo, total_count,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "data", "samples")

#: (文件名, 频道标识)。n=5 是台账登记的最小样本；n=30 是观测池。
SAMPLE_FILES = (
    ("gwy-p1-n5.json", "gwy"),
    ("bm-p1-n5.json", "bm"),
    ("gwy-p1-n30.json", "gwy"),
    ("bm-p1-n30.json", "bm"),
)


def _read_json(name):
    path = os.path.join(SAMPLES, name)
    assert os.path.isfile(path), "样本缺失（M1 产出）：%s" % name
    with io.open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def payloads():
    return dict((name, _read_json(name)) for name, _src in SAMPLE_FILES)


# --- 1. 取数路径（决策 D13） ------------------------------------------------

@pytest.mark.parametrize("name,source", SAMPLE_FILES)
def test_entries_live_in_searchvo_listvo(name, source, payloads):
    """**取数路径锚点**：条目在 `searchVO.listVO`。"""
    payload = payloads[name]
    assert isinstance(payload.get("searchVO"), dict), name
    assert isinstance(payload["searchVO"].get("listVO"), list), name
    assert payload["searchVO"]["listVO"], name


@pytest.mark.parametrize("name,source", SAMPLE_FILES)
def test_top_level_data_is_null(name, source, payloads):
    """**顶层 `data` 实测为 null**（不得按 `data` 取条目）。"""
    assert payloads[name].get("data", "MISSING") is None, name


@pytest.mark.parametrize("name,source", SAMPLE_FILES)
def test_items_from_listvo_works_on_real_payload(name, source, payloads):
    """真实响应喂 `items_from_listvo()` 必须成立（生产取数路径离线回归）。"""
    items = items_from_listvo(payloads[name], source)
    assert items, name
    for item in items:
        assert isinstance(item, PolicyItem)
        assert item.source == source
        assert item.channel in ("国务院", "部委")
        assert item.validate() == [], (name, item.id, item.validate())


@pytest.mark.parametrize("name,source", SAMPLE_FILES)
def test_total_count_is_real_total(name, source, payloads):
    """`totalCount` 是真实总数（`pageSize` 是请求回显，两者不得混淆）。"""
    payload = payloads[name]
    total = total_count(payload)
    assert isinstance(total, int) and total > 0, (name, total)
    assert total >= len(payload["searchVO"]["listVO"]), name
    assert payload["searchVO"]["pageSize"] == payload["searchVO"]["listVO"].__len__() \
        or payload["searchVO"]["pageSize"] >= 1


# --- 2. 实测形态锚点（M0 勘误 E3/E4 的离线复现） ----------------------------

def test_bm_channel_index_is_empty(payloads):
    """**M0 实测 E3**：部委频道 `index` 全空 → 不能作唯一主键（决策 D12）。"""
    items = items_from_listvo(payloads["bm-p1-n30.json"], "bm")
    assert all(item.index == "" for item in items), "部委 index 应全空"
    assert all(item.id for item in items), "id 必须非空（主键）"


def test_gwy_channel_index_is_populated(payloads):
    """国务院频道 `index` 实测非空（两频道差异，故 index 只能作副键）。"""
    items = items_from_listvo(payloads["gwy-p1-n30.json"], "gwy")
    assert all(item.index for item in items), "国务院 index 应非空"


def test_pcode_can_be_empty_in_bm_channel(payloads):
    """**M0 实测 E4**：部委 `pcode` 可空（实测 3/30）→ 空 pcode 不得致校验失败。"""
    items = items_from_listvo(payloads["bm-p1-n30.json"], "bm")
    empty = [item for item in items if not item.pcode]
    assert empty, "样本里应有空 pcode 条目"
    for item in empty:
        assert item.validate() == [], item.id


def test_fwzh_wenhao_wjlx_are_all_empty(payloads):
    """**M0 实测 E4**：`fwzh`/`wenhao`/`wjlx` 三字段 60/60 全空 → 不入模型。"""
    for name in ("gwy-p1-n30.json", "bm-p1-n30.json"):
        for entry in payloads[name]["searchVO"]["listVO"]:
            for field in ("fwzh", "wenhao", "wjlx"):
                assert (entry.get(field) or "") == "", (name, entry.get("id"), field)


def test_dates_are_valid_yyyymmdd_dotted(payloads):
    """实测 `pubtimeStr` 形态 = `YYYY.MM.DD` 且组合真实。"""
    for name, source in SAMPLE_FILES:
        for item in items_from_listvo(payloads[name], source):
            assert item.date_valid(), (name, item.id, item.pubtimeStr)


# --- 3. 真实文号形态（M0 六形态 + M1 新增形态） ----------------------------

def _all_pcodes(payloads):
    pcodes = []
    for name in ("gwy-p1-n30.json", "bm-p1-n30.json"):
        for entry in payloads[name]["searchVO"]["listVO"]:
            if entry.get("pcode"):
                pcodes.append(entry["pcode"])
    return pcodes


def test_real_pcodes_cover_standard_and_decree_forms(payloads):
    """真实文号必须同时含标准六角括号形态与"第…号"无年份形态。"""
    pcodes = _all_pcodes(payloads)
    assert any("\u3014" in p for p in pcodes), "缺标准六角括号形态"
    assert any(re.match(r"^国令第\d+号$", p) for p in pcodes), "缺国令第N号形态"


def test_real_pcodes_cover_fullwidth_bracket_variant(payloads):
    """**M1 实测 E6**：真实文号含全角 `﹝﹞`（U+FE5D/U+FE5E，码位与 `〔〕` 不同）。"""
    pcodes = _all_pcodes(payloads)
    fullwidth = [p for p in pcodes if "\ufe5d" in p]
    assert fullwidth, "样本里应有全角括号文号"
    for pcode in fullwidth:
        assert "\u3014" not in pcode, "全角变体不应混用标准括号：%s" % pcode


def test_real_pcodes_cover_spaced_serial(payloads):
    """**M1 实测 E7**：序号与"号"之间可出现空格（`农农发〔2026〕9 号`）。"""
    pcodes = _all_pcodes(payloads)
    spaced = [p for p in pcodes if re.search(r"\d\s+号$", p)]
    assert spaced, "样本里应有『序号 + 空格 + 号』形态的文号"


# --- 4. puborg 分隔符（M1 实测 E5） -----------------------------------------

def test_puborg_uses_non_ascii_space_separators(payloads):
    """**M1 实测 E5**：`puborg` 分隔符含 **U+2002 EN SPACE**（不止 U+0020）。

    只按 `' '` 拆分 → 多部门串会变成单个不可识别 token。
    """
    found_en_space = False
    for name in ("gwy-p1-n30.json", "bm-p1-n30.json"):
        for entry in payloads[name]["searchVO"]["listVO"]:
            puborg = entry.get("puborg") or ""
            if "\u2002" in puborg:
                found_en_space = True
    assert found_en_space, "样本里应有含 U+2002 分隔符的 puborg"


def test_puborg_mixes_separator_kinds_within_one_string(payloads):
    """**M1 实测 E5 的强化**：同一条 `puborg` 内可**混用** U+2002 与 U+0020。"""
    mixed = []
    for name in ("gwy-p1-n30.json", "bm-p1-n30.json"):
        for entry in payloads[name]["searchVO"]["listVO"]:
            puborg = entry.get("puborg") or ""
            if " " in puborg and "\u2002" in puborg:
                mixed.append(puborg)
    assert mixed, "样本里应有『同一串混用两种空格』的 puborg"


def test_puborg_splits_into_known_departments(payloads):
    """按 `\\s` 类空白拆分后，各部门名应能逐个识别（对照别名表）。"""
    aliases = _read_json(os.path.join("..", "config", "org-aliases.json"))
    known = set(aliases["aliases"])
    tokens = set()
    for name in ("gwy-p1-n30.json", "bm-p1-n30.json"):
        for entry in payloads[name]["searchVO"]["listVO"]:
            for tok in re.split(r"\s+", (entry.get("puborg") or "").strip()):
                if tok:
                    tokens.add(tok)
    unknown = sorted(tokens - known)
    assert unknown == [], "别名表未覆盖实测部门名：%r" % unknown


# --- 5. 字节冻结（sha256 与登记值一致） -------------------------------------

def test_sample_sha256_matches_registry():
    """样本字节冻结：逐份 sha256 与 `manifest.json` 登记值一致。

    注意：这**只**证明"仓库里的字节没被改动"，不证明"服务器仍返回同样内容"
    （重抓会改变 sha256，那是正常更新，须连同登记表一起提交）。
    """
    import hashlib
    registry = _read_json("manifest.json")
    assert registry.get("samples"), "登记表为空"
    for entry in registry["samples"]:
        path = os.path.join(SAMPLES, entry["file"])
        assert os.path.isfile(path), entry["file"]
        with io.open(path, "rb") as fh:
            actual = hashlib.sha256(fh.read()).hexdigest()
        assert actual == entry["sha256"], "%s sha256 失配" % entry["file"]


def test_registry_records_required_metadata():
    """登记表必须记 URL / 抓取日期 / HTTP 状态（DoD #7 硬要求）。"""
    registry = _read_json("manifest.json")
    for entry in registry["samples"]:
        for field in ("url", "captured_date", "http_status", "sha256", "bytes"):
            assert entry.get(field) not in (None, ""), (entry["file"], field)
        assert entry["url"].startswith("https://sousuo.www.gov.cn/"), entry["url"]
        assert entry["http_status"] == 200, entry["file"]


# --- 6. M2 抓取器离线回归（真跑 fetch，输入是冻结字节） ---------------------

#: (样本文件, 频道标识, 每页条数)。
FETCH_REGRESSION_CASES = (
    ("gwy-p1-n5.json", "gwy", 5),
    ("bm-p1-n5.json", "bm", 5),
    ("gwy-p1-n30.json", "gwy", 30),
    ("bm-p1-n30.json", "bm", 30),
)

#: 频道标识 -> API 的 `t` 参数。
CHANNEL_PARAM = {"gwy": "zhengcelibrary_gwy", "bm": "zhengcelibrary_bm"}

FROZEN_CLOCK = "2026-10-17T00:00:00"


class _FrozenTransport(object):
    """假传输层：**只回放冻结的真实响应字节**（按 URL 的 `t`/`p`/`n` 取样本）。

    这是"不打真站点"的关键：抓取器走完整真实代码路径，唯一被替换的是"字节从哪来"。
    """

    def __init__(self, files_by_key):
        self.files_by_key = dict(files_by_key)
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append(url)
        query = dict(part.split("=", 1)
                     for part in url.split("?", 1)[1].split("&") if "=" in part)
        key = (query["t"], int(query["p"]), int(query["n"]))
        assert key in self.files_by_key, "计划外请求：%s" % url
        path = os.path.join(SAMPLES, self.files_by_key[key])
        with io.open(path, "rb") as fh:
            return 200, fh.read()


def _fetch_frozen(sample_name, source, n):
    """用冻结样本跑一次真 `fetch_all`（限频/重试/自证/字段校验全在路径上）。"""
    transport = _FrozenTransport({(CHANNEL_PARAM[source], 1, n): sample_name})
    items, meta = fetch_all([source], pages=1, n=n, delay=0, get=transport,
                            sleep=lambda _seconds: None, now=lambda: FROZEN_CLOCK)
    return items, meta, transport


@pytest.mark.parametrize("name,source,n", FETCH_REGRESSION_CASES)
def test_fetch_output_matches_frozen_sample_field_by_field(name, source, n, payloads):
    """**DoD 硬判据**：抓取产出与留档样本**逐字段一致**（不是"都有这些字段"）。"""
    items, meta, transport = _fetch_frozen(name, source, n)
    expected = items_from_listvo(payloads[name], source)

    assert len(items) == len(expected) == len(payloads[name]["searchVO"]["listVO"])
    assert [it.to_dict() for it in items] == [it.to_dict() for it in expected]
    # 条目顺序 = API 返回序（抓取层不重排；规范排序是 M3 快照层的事）。
    assert [it.id for it in items] == [it.id for it in expected]
    assert meta[0]["status"] == "ok"
    assert transport.calls == [build_url(source, 1, n)]


@pytest.mark.parametrize("name,source,n", FETCH_REGRESSION_CASES)
def test_fetch_items_are_schema_locked(name, source, n, payloads):
    """产出条目必须**恰好**是 `SCHEMA_FIELDS` 十项：不多（UI 字段）不少（必填字段）。"""
    items, _meta, _transport = _fetch_frozen(name, source, n)
    for item in items:
        assert list(item.to_dict().keys()) == list(SCHEMA_FIELDS), item.id
        assert not (set(item.to_dict()) & set(FORBIDDEN_SNAPSHOT_FIELDS)), item.id
        assert item.validate() == [], (item.id, item.validate())


@pytest.mark.parametrize("name,source,n", FETCH_REGRESSION_CASES)
def test_fetch_reconciliation_uses_sample_total_count(name, source, n, payloads):
    """对账里的"声明 totalCount"必须等于样本登记的真实总数（不是请求条数）。"""
    items, meta, _transport = _fetch_frozen(name, source, n)
    from policy_radar.fetch import reconciliation_lines
    sample_total = payloads[name]["searchVO"]["totalCount"]
    assert meta[0]["declared_total"] == sample_total
    line = reconciliation_lines(meta)[0]
    assert re.search(r"请求 %d 条 / 声明 totalCount %d / 实际 %d 条"
                     % (n, sample_total, len(items)), line), line


@pytest.mark.parametrize("name,source,n", FETCH_REGRESSION_CASES)
def test_fetch_requested_url_equals_registry_url(name, source, n):
    """抓取请求 URL 必须与 `manifest.json` 登记的**真实抓取 URL**逐字一致。

    不硬编码 URL（"不写漂移硬数字"纪律）：拿登记表比对。
    """
    _items, _meta, transport = _fetch_frozen(name, source, n)
    registry = _read_json("manifest.json")
    by_file = dict((e["file"], e["url"]) for e in registry["samples"])
    assert transport.calls == [by_file[name]]


def test_fetch_artifact_written_by_cli_is_field_equal_to_sample(tmp_path, monkeypatch):
    """端到端产物面：CLI `fetch` 写出的文件里，条目与样本**逐字段一致**、无禁字段。"""
    from policy_radar import fetch as fetch_mod
    from policy_radar.cli import main_guarded

    name, source, n = "gwy-p1-n5.json", "gwy", 5
    payload = _read_json(name)
    transport = _FrozenTransport({(CHANNEL_PARAM[source], 1, n): name})
    monkeypatch.setattr(fetch_mod, "_default_get", transport)
    monkeypatch.setattr(fetch_mod, "_default_now", lambda: FROZEN_CLOCK)
    monkeypatch.setattr(fetch_mod, "_default_sleep", lambda _seconds: None)

    out = os.path.join(str(tmp_path), "fetched.json")
    code = main_guarded(["fetch", "--channel", source, "--pages", "1", "--n", str(n),
                         "--delay", "0", "--out", out])
    assert code == 0

    artifact = json.loads(io.open(out, "r", encoding="utf-8").read())
    expected = [it.to_dict() for it in items_from_listvo(payload, source)]
    assert artifact["items"] == expected, "产物条目必须与留档样本逐字段一致"
    assert artifact["item_count"] == len(expected)
    assert artifact["reconciliation"]["returned_total"] == len(expected)
    assert artifact["reconciliation"]["kept_total"] == len(expected)
    assert artifact["reconciliation"]["dropped_total"] == 0
    assert artifact["reconciliation"]["declared_total"] == \
        payload["searchVO"]["totalCount"]
    for item in artifact["items"]:
        assert set(item) == set(SCHEMA_FIELDS)
        assert not (set(item) & set(FORBIDDEN_SNAPSHOT_FIELDS))
