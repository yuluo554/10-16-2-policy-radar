"""快照存储 + 新增/重复判定（M3 模块 2）；`diff` 子命令落点。

设计纪律（`plan/04-模块详设.md` 模块 2，逐条对应）：

1. **快照只存元数据**（边界 2）：形态 = `{"format": "policy-radar-snapshot",
   "format_version": 1, "note": …, "item_count": N, "items": [...]}`；`items`
   字段白名单 = `PolicyItem` 十项；出现 `content`/`body`/`fulltext` 一类字段
   即拒（K10 代码级门禁；**读、写两条路径都拦**）。
2. **规范排序（K5）**：`items` 按 `(pubtimeStr 倒序, id 升序)`；产物**无时间戳**
   （"同输入双跑逐字节一致"的前提）。排序只在 `canonical_order()` 一处实现；
   与 M1 冻结快照的逐字节一致性由测试守门（包内不得 import `tools/`，故本模块
   自带生产侧实现）。
3. **重复判定双键（K4）**：`id` 相同 → 重复；否则 `pcode` 相同**且非空** → 重复；
   两键任一命中即判重复，命中键写进 `matched_by` 供回溯。`pcode` 为空只按 `id` 判。
4. **输入按 `format` 分派（K22/K23）**：`--current` / `--input` 认本仓三类承载
   条目的产物——`fetch` 产物（`policy-radar-fetch`，API 返回序）、快照
   （`policy-radar-snapshot`，规范序）、diff 产物（`policy-radar-diff`，新增清单）；
   未知格式**显式拒绝**（exit 2），不静默按最宽松规则解析。**规范排序由本模块
   负责**——"抓来什么顺序就什么顺序"不进快照。
5. **首跑语义（K24）**：省略 `--snapshot` = 首次运行（全部计入新增，stdout 明示）；
   给了路径但读不到 = exit 2——**不得**静默回落成首跑（把"路径打错"读成
   "全是新发的"是最坏的一类静默错误）。
6. **diff 产出两件**：diff 产物（新增条目 + 判定元信息）与**更新后的快照**
   （全量覆盖式更新；决策 P5：只留当前快照，历史轮次由版本控制留档）。

对账与测试：生产实现与真值的比对走 `cases.compare_diff`（K15 共用对账语义），
在**测试**里做；本模块**不得** import `cases`（K14，`tests/test_cases_independence.py`
源码扫描守门）。
"""

import os
import sys

from .errors import EXIT_OK, UsageError
from .fetch import FETCH_FORMAT, FETCH_FORMAT_VERSION
from .model import FORBIDDEN_SNAPSHOT_FIELDS, SCHEMA_FIELDS, PolicyItem
from .serialize import read_json, write_json

#: 快照格式标识（M1 冻结；`tools/_genlib.py` 是同一形态的生成侧实现——
#: 包内不得 import `tools/`，故本模块是**生产侧单点**）。
SNAPSHOT_FORMAT = "policy-radar-snapshot"
SNAPSHOT_FORMAT_VERSION = 1

#: diff 产物格式标识。
DIFF_FORMAT = "policy-radar-diff"
DIFF_FORMAT_VERSION = 1

#: 默认产出路径（`/out/` 已在 `.gitignore` 覆盖：运行时产物不入库）。
DEFAULT_DIFF_OUT = "out/diff.json"
DEFAULT_SNAPSHOT_OUT = "out/snapshot.json"

#: 更新后快照的固定 note（**不得含时间戳**：双跑逐字节一致的前提）。
UPDATE_NOTE = ("当前快照（diff 全量覆盖更新）：规范序 pubtimeStr 倒序 / id 升序；"
               "禁手改；只存元数据不落正文。")


class SnapshotError(ValueError):
    """快照/条目产物形态违规（格式错、item_count 不符、K10 禁字段）→ exit 2。

    继承 `ValueError`：`cli.main_guarded` 的兜底把它转成退出码 2，
    不逃逸成用户眼里的"程序崩了"。
    """


# --- 规范排序（K5） ---------------------------------------------------------

def canonical_order(items):
    """按 `(pubtimeStr 倒序, id 升序)` 排序（**全程不读时钟**）。

    两步稳定排序（先按 id 升序、再**稳定**按 pubtimeStr 倒序）——与 M1 生成侧
    `_genlib.canonical_order` 行为等价，与冻结快照的**逐字节一致性**由测试守门。
    不用 `sorted(key=lambda x: (-date_num, id))`：`pubtimeStr` 是定宽
    `YYYY.MM.DD` 字符串，"倒序即字典序反转"，两步法不引入日期数值转换。
    """
    by_id = sorted(items, key=lambda it: it.id)
    by_id.sort(key=lambda it: it.pubtimeStr, reverse=True)
    return by_id


# --- 字段白名单门禁（K10） --------------------------------------------------

def ensure_item_fields(item_dicts, where):
    """条目字段必须恰在 schema 白名单内，且不得含禁字段（K10：不做全文归档）。

    读、写两条路径都调用：写（构造快照/清单时）拦"把全文塞进条目"；
    读（加载既有产物时）拦"文件里混进禁字段"。含 `content`/`body`/`fulltext`
    即拒；白名单之外的字段（哪怕不是禁字段）同样拒——"字段白名单"是允许清单，
    不是黑名单。
    """
    forbidden = set(FORBIDDEN_SNAPSHOT_FIELDS)
    allowed = set(SCHEMA_FIELDS)
    for idx, item in enumerate(item_dicts):
        if not isinstance(item, dict):
            raise SnapshotError("%s 第 %d 条不是 JSON 对象：%r"
                                % (where, idx, type(item).__name__))
        hit = sorted(set(item) & forbidden)
        if hit:
            raise SnapshotError("%s 第 %d 条出现禁字段（不做全文归档，K10）：%r"
                                % (where, idx, hit))
        extra = sorted(set(item) - allowed)
        if extra:
            raise SnapshotError("%s 第 %d 条出现字段白名单之外的字段：%r"
                                % (where, idx, extra))


# --- 构造 / 读取 ------------------------------------------------------------

def build_snapshot(items, note):
    """构造快照对象（规范序 + 白名单守门）。

    **无时间戳**（决策 P5：历史轮次由版本控制留档，不落时钟）——这是
    "同输入双跑逐字节一致"的前提。
    """
    ordered = canonical_order(items)
    dicts = [it.to_dict() for it in ordered]
    ensure_item_fields(dicts, "快照")
    return {
        "format": SNAPSHOT_FORMAT,
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "note": note,
        "item_count": len(dicts),
        "items": dicts,
    }


def _validate_snapshot_obj(obj, path):
    """校验快照对象形态，返回原始条目 dict 列表（不静默按最宽松规则解析）。"""
    if not isinstance(obj, dict) or obj.get("format") != SNAPSHOT_FORMAT:
        raise SnapshotError("快照格式不是 %s：%s" % (SNAPSHOT_FORMAT, path))
    if obj.get("format_version") != SNAPSHOT_FORMAT_VERSION:
        raise SnapshotError("快照 format_version 不支持（%r != %d）：%s"
                            % (obj.get("format_version"),
                               SNAPSHOT_FORMAT_VERSION, path))
    items = obj.get("items")
    if not isinstance(items, list):
        raise SnapshotError("快照缺少 items 列表：%s" % path)
    if obj.get("item_count") != len(items):
        raise SnapshotError("快照 item_count 与实际条数不符：%s（%r != %d）"
                            % (path, obj.get("item_count"), len(items)))
    ensure_item_fields(items, "快照 %s" % path)
    return items


def load_snapshot(path):
    """读快照文件 → `PolicyItem` 列表（形态校验失败抛 `SnapshotError` → exit 2）。"""
    obj = read_json(path)
    items = _validate_snapshot_obj(obj, path)
    return [PolicyItem.from_dict(d) for d in items]


def load_items_file(path):
    """读"承载条目的产物"并按 `format` 分派（K22/K23）。

    支持三类：`policy-radar-fetch`（抓取产物，API 返回序）、
    `policy-radar-snapshot`（快照，规范序）、`policy-radar-diff`（新增清单）。
    未知格式**显式拒绝**——"按 format 分派"的意义就在于不猜；把不认识的文件
    当条目读，会把"喂错文件"变成"静默产出错结论"。
    """
    obj = read_json(path)
    if not isinstance(obj, dict):
        raise SnapshotError("条目文件不是 JSON 对象：%s" % path)
    fmt = obj.get("format")
    if fmt == SNAPSHOT_FORMAT:
        items = _validate_snapshot_obj(obj, path)
    elif fmt in (FETCH_FORMAT, DIFF_FORMAT):
        version = (FETCH_FORMAT_VERSION if fmt == FETCH_FORMAT
                   else DIFF_FORMAT_VERSION)
        if obj.get("format_version") != version:
            raise SnapshotError("产物 format_version 不支持（%r != %d）：%s"
                                % (obj.get("format_version"), version, path))
        items = obj.get("items")
        if not isinstance(items, list):
            raise SnapshotError("产物缺少 items 列表：%s" % path)
        if obj.get("item_count") != len(items):
            raise SnapshotError("产物 item_count 与实际条数不符：%s（%r != %d）"
                                % (path, obj.get("item_count"), len(items)))
        ensure_item_fields(items, "产物 %s" % path)
    else:
        raise SnapshotError(
            "无法识别的产物格式（支持 %s / %s / %s）：%r（%s）"
            % (SNAPSHOT_FORMAT, FETCH_FORMAT, DIFF_FORMAT, fmt, path))
    return [PolicyItem.from_dict(d) for d in items]


# --- 新增/重复判定（K4） ----------------------------------------------------

def detect_new(previous_items, current_items):
    """双键判定：`id` 相同 → 重复；否则 `pcode` 相同**且非空** → 重复；否则新增。

    哈希索引实现（参照实现 `cases.naive_diff` 故意走双重循环——不同代码路径，
    见 K14）。返回 `{"new_ids": [...升序], "dup_ids": [...升序],
    "matched_by": {id: "id"|"pcode"}}`；`matched_by` 覆盖每一条重复
    （**命中键供回溯**：该按 pcode 命中的却按 id 算，是缺陷，必须能点名）。
    """
    prev_ids = set(it.id for it in previous_items)
    prev_pcodes = set(it.pcode for it in previous_items if it.pcode)

    new_ids = []
    dup_ids = []
    matched_by = {}
    for item in current_items:
        if item.id in prev_ids:
            dup_ids.append(item.id)
            matched_by[item.id] = "id"
            continue
        if item.pcode and item.pcode in prev_pcodes:
            dup_ids.append(item.id)
            matched_by[item.id] = "pcode"
            continue
        new_ids.append(item.id)
    new_ids.sort()
    dup_ids.sort()
    return {"new_ids": new_ids, "dup_ids": dup_ids, "matched_by": matched_by}


def build_diff_product(previous_items, current_items, first_run=False):
    """构造 diff 产物：新增条目（**规范序**）+ 判定元信息。

    元信息含"本次总数 / 上次总数 / 新增数 / 重复数 / 主键口径"（模块 2 输出契约），
    另有 `new_ids` / `dup_ids` / `matched_by`（供对账与回溯）。
    `items` = 新增条目（规范序），与 `fetch`/快照产物同键位——下游（M4 订阅 /
    M5 日报）按同一约定消费。
    """
    result = detect_new(previous_items, current_items)
    new_ids = set(result["new_ids"])
    new_items = [it for it in current_items if it.id in new_ids]
    dicts = [it.to_dict() for it in canonical_order(new_items)]
    ensure_item_fields(dicts, "新增清单")
    return {
        "format": DIFF_FORMAT,
        "format_version": DIFF_FORMAT_VERSION,
        "note": "快照 diff 产出（M3）：相对上次快照的新增条目（规范序）+ 判定元信息；不含正文。",
        "first_run": bool(first_run),
        "previous_item_count": len(previous_items),
        "current_item_count": len(current_items),
        "new_count": len(result["new_ids"]),
        "dup_count": len(result["dup_ids"]),
        "dedup_keys": {"primary": "id", "secondary": "pcode_nonempty"},
        "new_ids": result["new_ids"],
        "dup_ids": result["dup_ids"],
        "matched_by": result["matched_by"],
        "item_count": len(dicts),
        "items": dicts,
    }


# --- CLI --------------------------------------------------------------------

def cmd_diff(args):
    """`diff` 子命令：读上次快照（可省 = 首跑）与本次条目 → 双键判定 → 写两件产物。

    产出：① diff 产物（`--out`，默认 `out/diff.json`）；② 更新后的快照
    （`--snapshot-out`，默认 `out/snapshot.json`，规范序、全量覆盖）。

    退出码：0 = 完成；2 = 用法/输入错误（本层无降级语义——判定本身没有
    "完成但有降级"态；输入文件的问题一律是"输入不可用"）。
    """
    current_path = getattr(args, "current", None)
    if not current_path:
        raise UsageError("--current 必填（本次条目文件）")
    snapshot_path = getattr(args, "snapshot", None)
    out_path = getattr(args, "out", None) or DEFAULT_DIFF_OUT
    snapshot_out = getattr(args, "snapshot_out", None) or DEFAULT_SNAPSHOT_OUT

    # 首跑语义（K24）：省略 --snapshot 才是首跑；给了路径就必须读得到。
    first_run = not snapshot_path
    try:
        if first_run:
            previous_items = []
        else:
            previous_items = load_snapshot(snapshot_path)
        current_items = load_items_file(current_path)
    except ValueError as exc:
        # 读不进来 = 输入不可用（缺文件 / 坏格式 / 形态违规）→ 统一 exit 2 语义。
        raise UsageError(str(exc))

    product = build_diff_product(previous_items, current_items, first_run=first_run)
    updated = build_snapshot(current_items, UPDATE_NOTE)

    try:
        write_json(out_path, product)
        write_json(snapshot_out, updated)
    except (IOError, OSError) as exc:
        raise UsageError("无法写出 diff 产物：%s" % exc)

    if first_run:
        sys.stdout.write("  diff: 首次运行（无上次快照）→ 本次 %d 条全部计入新增（重复 0 条）\n"
                         % product["current_item_count"])
    else:
        pcode_hits = sum(1 for v in product["matched_by"].values() if v == "pcode")
        sys.stdout.write(
            "  diff: 上次快照 %d 条 → 本次 %d 条；新增 %d 条 / 重复 %d 条"
            "（命中键 id %d / pcode %d）\n"
            % (product["previous_item_count"], product["current_item_count"],
               product["new_count"], product["dup_count"],
               product["dup_count"] - pcode_hits, pcode_hits))
    sys.stdout.write("  已写出 %s（新增清单 %d 条）+ %s（更新后快照 %d 条）\n"
                     % (out_path, product["item_count"], snapshot_out,
                        updated["item_count"]))
    return EXIT_OK
