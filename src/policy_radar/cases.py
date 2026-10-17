"""真值基准的**参照实现**与**对账语义**（单一实现源）。

本模块有两个互相关联、但性质不同的部分：

1. **独立参照实现（oracle）**：`naive_diff()` / `naive_parse_pcode()` /
   `naive_match()`。它们**故意写得笨**（双重循环、位置切片、`str.find`），
   并且与生产实现走不同代码路径——生产模块（`snapshot.py` / `parse.py` /
   `subscribe.py`）**不得 import 本模块**（由 `tests/test_cases_independence.py`
   的源码扫描守门）。

   判别口诀：**"把生产实现的判定逻辑注释掉，真值还能算出来吗？"** 能——真值只依赖
   本模块与输入数据。这条是"基准不跟着实现一起错"的前提。

2. **对账语义（`compare_*`）**：把"实测结论"与"真值期望"逐条点名比对，返回**差异清单**
   而非模糊的"通过/不通过"。测试与基准（M4 的 `bench`）**共用这一份**——否则会出现
   "基准说达标、测试说不过"的双真相。

## 为什么参照实现放在包内而不是 `tools/`

真值台账要有**真调用方**（不是"文件存在"）：用户敲的 `policy-radar verify-data`
必须真读它。审计命令装在包里，故参照实现也须在包里（`src/` 不能反向依赖 `tools/`，
`tools/` 不进安装包）。

## 真值库卫生（K11）

`assert_no_observed_fields()`：真值库出现 `observed_*` 一类字段即红。冻结"观测"会让
基准退化成"比对两份预先算好的答案"——引擎整个坏掉也照样全绿。
"""

import re

#: 未解析字段的哨兵值（与 `data/truth/pcode-truth.json` 的契约同值）。
UNPARSED = "未解析"

#: 文号解析三态（K6）。
STATUS_PARSED = "parsed"
STATUS_PARTIAL = "partial"
STATUS_UNPARSED = "unparsed"

#: 六角括号与全角变体（M1 实测：`〔〕`=U+3014/U+3015，`﹝﹞`=U+FE5D/U+FE5E）。
BRACKET_PAIRS = (("\u3014", "\u3015"), ("\ufe5d", "\ufe5e"))

#: 命中字段优先序（真值与生产实现共用，单一来源）。
FIELD_PRIORITY = ("title", "summary")


# ===========================================================================
# 一、独立参照实现（oracle）
# ===========================================================================

def naive_diff(snapshot_a, snapshot_b):
    """参照实现：按 `id` / `pcode` 双键判定 B 中每条相对 A 是"新增"还是"重复"。

    **故意用最笨的写法**：双重循环 + 字符串相等，不用 set/dict 做键索引（生产实现
    大概率用哈希索引——不同代码路径更容易在两边都写错时暴露分歧）。

    判定规则（K4）：`id` 相同 → 重复；否则 `pcode` 相同**且非空** → 重复；否则新增。

    参数与返回都是纯数据（dict 列表 / id 列表），不依赖 `PolicyItem`。
    返回 `(new_ids, dup_ids, matched_by)`，`new_ids`/`dup_ids` 均为 **id 升序**。
    """
    a_ids = [it.get("id", "") for it in snapshot_a]
    a_pcodes = [it.get("pcode", "") for it in snapshot_a if it.get("pcode")]

    new_ids = []
    dup_ids = []
    matched_by = {}
    for item in snapshot_b:
        bid = item.get("id", "")
        hit_id = False
        for aid in a_ids:
            if aid == bid:
                hit_id = True
                break
        if hit_id:
            dup_ids.append(bid)
            matched_by[bid] = "id"
            continue

        bpcode = item.get("pcode", "") or ""
        hit_pcode = False
        if bpcode:
            for apcode in a_pcodes:
                if apcode == bpcode:
                    hit_pcode = True
                    break
        if hit_pcode:
            dup_ids.append(bid)
            matched_by[bid] = "pcode"
        else:
            new_ids.append(bid)

    new_ids.sort()
    dup_ids.sort()
    return new_ids, dup_ids, matched_by


def naive_parse_pcode(pcode):
    """参照实现：把文号拆成 `agency_code / year / serial` + 三态 `status`。

    **刻意不用正则**（生产解析器大概率用 `re`）——只用 `str.find` / 切片 / `isdigit()`。

    规则（K6）：
    - 有括号（`〔〕` 或全角 `﹝﹞`）：代字 = 左括号前全部非空字符；年份 = 括号内 4 位数字；
      序号 = 右括号后至 `号` 前的数字串（**去空白**）。
    - 无括号但有 `第…号`：代字 = `第` 前字符；年份 = `未解析`（**不编造**）；序号 = 中间数字。
    - 其它：整条 `unparsed`。
    """
    text = (pcode or "").strip()
    if not text:
        return {"agency_code": UNPARSED, "year": UNPARSED, "serial": UNPARSED,
                "status": STATUS_UNPARSED}

    open_b = None
    close_b = None
    for left, right in BRACKET_PAIRS:
        pos = text.find(left)
        if pos >= 0:
            end = text.find(right, pos + 1)
            if end > pos:
                open_b, close_b = pos, end
                break

    if open_b is not None:
        agency = text[:open_b].strip()
        inner = text[open_b + 1:close_b].strip()
        tail = text[close_b + 1:]
        fields = {
            "agency_code": agency if agency else UNPARSED,
            "year": inner if _is_year(inner) else UNPARSED,
            "serial": _digits_after(tail),
        }
        return _with_status(fields)

    di = text.find("第")
    if di > 0:
        hao = text.find("号", di + 1)
        if hao > di:
            agency = text[:di].strip()
            fields = {
                "agency_code": agency if agency else UNPARSED,
                "year": UNPARSED,
                "serial": _digits_in(text[di + 1:hao]),
            }
            return _with_status(fields)

    return {"agency_code": UNPARSED, "year": UNPARSED, "serial": UNPARSED,
            "status": STATUS_UNPARSED}


def _is_year(text):
    return len(text) == 4 and text.isdigit()


def _digits_after(tail):
    """从 `〕` 之后取数字串（容忍序号与"号"之间的空白，实测 `农农发〔2026〕9 号`）。"""
    return _digits_in(re.sub(r"\s+", "", tail))


def _digits_in(text):
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits if digits else UNPARSED


def _with_status(fields):
    known = [v for v in (fields["agency_code"], fields["year"], fields["serial"])
             if v != UNPARSED]
    if len(known) == 3:
        status = STATUS_PARSED
    elif known:
        status = STATUS_PARTIAL
    else:
        status = STATUS_UNPARSED
    out = dict(fields)
    out["status"] = status
    return out


def normalize_text(text, norm_map):
    """按归一表逐字符替换。

    归一表的每条映射都是**单字符 → 单字符**（长度保持），因此命中位置 `offset`
    在归一前后同值——`offset` 语义唯一、可审计（见 `data/config/normalize.json`）。
    """
    return "".join(norm_map.get(ch, ch) for ch in (text or ""))


def dedup_keywords(keywords, norm_map):
    """按**归一后**的关键词去重，保持配置顺序（同词重复配置 → 只留一条）。"""
    seen = []
    out = []
    for kw in keywords:
        key = normalize_text(kw, norm_map)
        if key and key not in seen:
            seen.append(key)
            out.append(kw)
    return out


def naive_match(items, include, exclude, norm_map):
    """参照实现：订阅命中。返回 `(hits, excluded, zero_hit_ids)`。

    `items` 为对象序列（需有 `.id` / `.title` / `.summary`）。判定（K8）：
    exclude 优先（命中即整条剔除）→ 否则 include 按配置顺序取**首次出现**
    （title 优先）→ 都不中记 `zero_hit_ids`。
    """
    inc = dedup_keywords(include, norm_map)
    exc = dedup_keywords(exclude, norm_map)

    hits = []
    excluded = []
    zero = []
    for item in items:
        title_n = normalize_text(item.title, norm_map)
        summary_n = normalize_text(item.summary, norm_map)

        matched_exc = [kw for kw in exc
                       if normalize_text(kw, norm_map) in title_n
                       or normalize_text(kw, norm_map) in summary_n]
        matched_inc = []
        for kw in inc:
            pos = _first_position(normalize_text(kw, norm_map), title_n, summary_n)
            if pos is not None:
                matched_inc.append((kw, pos[0], pos[1]))

        if matched_exc:
            excluded.append({
                "item_id": item.id,
                "matched_exclude": matched_exc,
                "include_matched_before_exclusion": [k for k, _f, _o in matched_inc],
            })
            continue
        if not matched_inc:
            zero.append(item.id)
            continue
        for kw, field, offset in matched_inc:
            hits.append({"item_id": item.id, "keyword": kw,
                         "field": field, "offset": offset})
    return hits, excluded, zero


def _first_position(key, title_n, summary_n):
    """按 `FIELD_PRIORITY`（title 先）找首次出现，返回 `(field, offset)` 或 None。"""
    for field in FIELD_PRIORITY:
        text = title_n if field == "title" else summary_n
        idx = text.find(key)
        if idx >= 0:
            return field, idx
    return None


# ===========================================================================
# 二、对账语义（compare_*，测试与基准共用）
# ===========================================================================

def compare_sets(expected, observed):
    """集合类对账：返回 `{"missing": [...], "extra": [...], "ok": bool}`。

    **逐条点名**而非只给布尔值——"未达标"必须能说出**哪几条**不一致。
    """
    exp = sorted(set(expected))
    obs = sorted(set(observed))
    missing = [x for x in exp if x not in set(obs)]
    extra = [x for x in obs if x not in set(exp)]
    return {"missing": missing, "extra": extra, "ok": not missing and not extra}


def compare_diff(observed, expected):
    """对账 diff 真值。

    `observed` / `expected` 形如 `{"new_ids": [...], "dup_ids": [...],
    "matched_by": {...}}`。返回逐项差异（含 `matched_by` 的键级差异——
    命中键判错（该按 pcode 却按 id）也须点名）。
    """
    result = {}
    result["new_ids"] = compare_sets(expected.get("new_ids", []),
                                     observed.get("new_ids", []))
    result["dup_ids"] = compare_sets(expected.get("dup_ids", []),
                                     observed.get("dup_ids", []))
    exp_mb = expected.get("matched_by", {}) or {}
    obs_mb = observed.get("matched_by", {}) or {}
    mb_mismatch = []
    for key in sorted(set(exp_mb) | set(obs_mb)):
        if exp_mb.get(key) != obs_mb.get(key):
            mb_mismatch.append({"item_id": key,
                                "expected": exp_mb.get(key),
                                "observed": obs_mb.get(key)})
    result["matched_by_mismatch"] = mb_mismatch
    result["ok"] = (result["new_ids"]["ok"] and result["dup_ids"]["ok"]
                    and not mb_mismatch)
    return result


def compare_pcode(observed, expected):
    """对账文号解析：逐条比对四个字段（三字段 + `status`）。

    `observed` / `expected` 为 `{pcode: {...}}` 映射。返回 `{"mismatches": [...],
    "checked": n, "ok": bool}`；每条差异**点名字段**（"年份编造了"与"代字切错了"
    是不同性质的缺陷，必须能区分）。
    """
    mismatches = []
    keys = sorted(set(observed) | set(expected))
    for key in keys:
        exp = expected.get(key)
        obs = observed.get(key)
        if exp is None:
            mismatches.append({"pcode": key, "kind": "unexpected_observed",
                               "observed": obs})
            continue
        if obs is None:
            mismatches.append({"pcode": key, "kind": "missing_observed",
                               "expected": exp})
            continue
        field_diffs = {}
        for field in ("agency_code", "year", "serial", "status"):
            if exp.get(field) != obs.get(field):
                field_diffs[field] = {"expected": exp.get(field),
                                      "observed": obs.get(field)}
        if field_diffs:
            mismatches.append({"pcode": key, "kind": "field_mismatch",
                               "fields": field_diffs})
    return {"mismatches": mismatches, "checked": len(keys),
            "ok": not mismatches}


def compare_subscribe(observed, expected):
    """对账订阅命中。

    `observed` / `expected` 形如 `{"hits": [{item_id, keyword, field, offset}],
    "excluded": [{item_id, matched_exclude, include_matched_before_exclusion}],
    "zero_hit_item_ids": [...]}`。命中记录按 `(item_id, keyword)` 建键逐条比对
    （`field` / `offset` 判错也须点名——"命中了但位置错"是缺陷，不是达标）。
    """
    result = {}
    exp_hits = dict(((h["item_id"], h["keyword"]), h) for h in expected.get("hits", []))
    obs_hits = dict(((h["item_id"], h["keyword"]), h) for h in observed.get("hits", []))
    hit_keys = compare_sets(["%s|%s" % k for k in exp_hits],
                            ["%s|%s" % k for k in obs_hits])
    hit_field_diffs = []
    for key in sorted(set(exp_hits) & set(obs_hits)):
        for field in ("field", "offset"):
            if exp_hits[key].get(field) != obs_hits[key].get(field):
                hit_field_diffs.append({
                    "item_id": key[0], "keyword": key[1], "field": field,
                    "expected": exp_hits[key].get(field),
                    "observed": obs_hits[key].get(field)})
    result["hits"] = hit_keys
    result["hit_field_diffs"] = hit_field_diffs
    result["excluded_item_ids"] = compare_sets(
        [e["item_id"] for e in expected.get("excluded", [])],
        [e["item_id"] for e in observed.get("excluded", [])])
    result["zero_hit_item_ids"] = compare_sets(
        expected.get("zero_hit_item_ids", []),
        observed.get("zero_hit_item_ids", []))
    result["ok"] = (result["hits"]["ok"] and not hit_field_diffs
                    and result["excluded_item_ids"]["ok"]
                    and result["zero_hit_item_ids"]["ok"])
    return result


# ===========================================================================
# 三、真值库卫生（K11）
# ===========================================================================

def find_observed_fields(obj, where="产物"):
    """返回真值库里的 `observed*` 字段路径列表（空列表 = 干净）。"""
    offenders = []

    def walk(node, trail):
        if isinstance(node, dict):
            for key in sorted(node):
                if isinstance(key, str) and key.startswith("observed"):
                    offenders.append("%s.%s" % (trail, key))
                walk(node[key], "%s.%s" % (trail, key))
        elif isinstance(node, list):
            for idx, value in enumerate(node):
                walk(value, "%s[%d]" % (trail, idx))

    walk(obj, where)
    return offenders


def assert_no_observed_fields(obj, where="产物"):
    """真值库不得出现 `observed_*` 一类字段（出现即抛 AssertionError）。"""
    offenders = find_observed_fields(obj, where)
    if offenders:
        raise AssertionError("真值库出现 observed 类字段（K11 违规）：%r" % offenders)
