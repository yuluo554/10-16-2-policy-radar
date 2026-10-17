"""中文日报生成（M5 模块 5）：新增条目 + 订阅命中 → Markdown + HTML 双格式日报。

设计纪律（`plan/04-模块详设.md` 模块 5，逐条对应）：

1. **渲染层零判定（K9）**：本模块只消费既有结论（diff 的新增清单、parse 产物、
   `subscribe.match_items` 的命中记录），**不重算** diff/解析/命中——渲染前
   各输入已由对应模块判定完毕，本模块若再判一次就会出现两套结论。
   AST 守门（`tests/test_report_pipeline.py`）锁死：本模块源码不得出现
   `detect_new` / `parse_pcode` / `parse_orgs` / `match_items` 调用。
2. **零外链（本地可开）**：HTML 的**渲染资源**（脚本/样式/字体/图片引用）零外部
   引用——CSS 全内联、无 `<script>`/`<link>`/`@import`/外链图片；条目自带的
   `url` 字段是**原文链接**（正文内容），不属于"渲染资源"，断言只扫资源类标签。
   `assert_no_external_resources()` **常驻在渲染出口**（不是只在测试里验一次）。
3. **确定性（无时钟）**：标题不含日期时间戳，无随机序 → 同输入双跑逐字节一致。
4. **单一渲染源**：`report_entries()` 产出结构化条目记录，Markdown 与 HTML
   两个渲染器各自读同一份 → "两格式内容对等"是结构性质，测试抽文本比对。
5. **缺字段显式渲染「未提供」**：不静默略过（哨兵与 parse 的「未解析」同纪律）。
6. **未挂原文核对不落库/不进日报（FR-11）**：进日报前逐条 `PolicyItem.validate()`，
   未过的**该条不进日报**（计 `dropped_count`），不补编字段。
7. **无新增**：显式写"本次无新增"段（不落空文件）。

退出码：0 = 完成；1 = 有条目未过校验被丢弃（降级完成，日报照常产出）；
2 = 用法/输入错误（输入不可读 / format 不认识）。
"""

import html
import os
import re
import sys

from .errors import UsageError
from .model import PolicyItem
from .serialize import read_json, write_text

DIGEST_FORMAT = "policy-radar-digest"
DIGEST_FORMAT_VERSION = 1

#: 缺失字段的显式哨兵（不静默略过、不编造）。
MISSING = "未提供"

#: 允许的日报格式（CLI `--format` choices 同源）。
DIGEST_FORMATS = ("md", "html", "both")

DEFAULT_DIGEST_OUT = "out/report.md"

#: 「零外链」断言：渲染资源类标签的口径（K9）。
#: **条目自带的 `url` 字段是原文链接（内容），不在扫描面里**；
#: 扫的是资源引用：`<script>`/`<link>`/`<img>`/`@import`/外部字体。
_EXTERNAL_RESOURCE_RE = re.compile(
    r"<\s*(script|link|img|iframe|object|embed|source|video|audio)\b"
    r"|@import\b"
    r"|url\s*\(\s*['\"]?https?://",
    re.I)

#: `http://` / `https://`（只用于"资源标签内不得出现外链"的逐标签检查辅助）。
_EXTERNAL_SCHEME_RE = re.compile(r"https?://", re.I)

#: 渲染层零判定（K9）的 AST 守门依据：本模块不得调用的判定函数名。
#: （测试 `tests/test_report_pipeline.py` 按本常量扫描源码——口径单点。）
FORBIDDEN_CALLS_IN_REPORT = (
    "detect_new", "parse_pcode", "parse_orgs", "match_items",
    "build_diff_product", "build_parse_product",
)


class DigestInputError(UsageError):
    """日报输入不可用（文件缺失 / 坏格式 / format 不认识）→ exit 2。"""


# --- 输入装载（只消费既有结论，零判定） --------------------------------------

def _load_obj(path, what):
    if not path:
        raise DigestInputError("缺少 %s 路径（--%s）" % (what, "new-items" if what == "新增清单" else "hits"))
    if not os.path.isfile(path):
        raise DigestInputError("%s 文件不存在：%s" % (what, path))
    try:
        return read_json(path)
    except ValueError as exc:
        raise DigestInputError("%s 不可读：%s" % (what, exc))


def _require_format(obj, fmt, what, path):
    if not isinstance(obj, dict) or obj.get("format") != fmt:
        raise DigestInputError("%s 不是 %s 产物（format=%r）：%s"
                               % (what, fmt, (obj or {}).get("format") if isinstance(obj, dict) else None, path))
    if obj.get("format_version") != 1:
        raise DigestInputError("%s format_version 不支持（%r）：%s"
                               % (what, obj.get("format_version"), path))


def load_digest_inputs(new_items_path, hits_path):
    """装载日报输入：新增清单（`policy-radar-diff`）+ 订阅命中（`policy-radar-subscribe`）。

    两个输入都是**判定完毕的结论**（diff 已判新增、subscribe 已判命中），
    本函数只做形态校验，不重算任何判定（K9）。缺失/坏格式 → `UsageError`（exit 2）。
    """
    new_obj = _load_obj(new_items_path, "新增清单")
    _require_format(new_obj, "policy-radar-diff", "新增清单", new_items_path)
    new_items = new_obj.get("items")
    if not isinstance(new_items, list):
        raise DigestInputError("新增清单缺少 items 列表：%s" % new_items_path)

    hits_obj = _load_obj(hits_path, "订阅命中")
    _require_format(hits_obj, "policy-radar-subscribe", "订阅命中", hits_path)
    hits = hits_obj.get("hits")
    excluded = hits_obj.get("excluded")
    zero_hit_ids = hits_obj.get("zero_hit_ids")
    if not isinstance(hits, list) or not isinstance(excluded, list) \
            or not isinstance(zero_hit_ids, list):
        raise DigestInputError("订阅命中产物缺少 hits/excluded/zero_hit_ids：%s"
                               % hits_path)
    return new_obj, new_items, hits, excluded, zero_hit_ids


# --- 结构化条目（单一渲染源） ------------------------------------------------

def report_entries(new_items, hits, parse_map):
    """新增条目 + 命中记录 → 结构化条目记录（Markdown/HTML 两渲染器的**唯一输入**）。

    - `new_items`：diff 产物的条目 dict 列表（已规范序，本函数**不再排序**——
      排序口径（K5）单点在 diff 层，渲染层重排就是第二个实现点）；
    - `hits`：订阅命中记录列表 `{item_id, keyword, field, offset}`；
    - `parse_map`：`{item_id: parse 产物记录}`（可部分缺失——缺了显式渲染「未提供」）；
    - 未过 `PolicyItem.validate()` 的条目**不进日报**（FR-11），返回值里给
      `dropped`（id + 原因），调用方计数 `dropped_count`，**不补编字段**。
    """
    hits_by_item = {}
    for hit in hits:
        hits_by_item.setdefault(hit.get("item_id"), []).append(hit)

    entries = []
    dropped = []
    for d in new_items:
        item = PolicyItem.from_dict(d)
        missing = item.validate()
        if missing:
            dropped.append({"id": item.id, "reason": "required_fields_missing",
                            "missing": missing})
            continue

        record = parse_map.get(item.id) or {}
        pcode_parse = record.get("pcode_parse") or {}
        entries.append({
            "item_id": item.id,
            "title": item.title,
            "pubtime": item.pubtimeStr,
            "channel": item.channel,
            "url": item.url,
            "summary": item.summary,
            "pcode_raw": item.pcode,
            "pcode_status": pcode_parse.get("status", ""),
            "pcode_agency_code": pcode_parse.get("agency_code", ""),
            "pcode_year": pcode_parse.get("year", ""),
            "pcode_serial": pcode_parse.get("serial", ""),
            "puborg_raw": item.puborg,
            "orgs": record.get("orgs", []),
            "hit_fields": hits_by_item.get(item.id, []),
        })
    return entries, dropped


# --- Markdown 渲染 -----------------------------------------------------------

def _pcode_line_md(entry):
    raw = entry["pcode_raw"].strip()
    if raw:
        text = "`%s`" % raw
    else:
        text = MISSING
    if entry["pcode_status"]:
        parts = []
        for key, label in (("pcode_agency_code", "代字"), ("pcode_year", "年份"),
                           ("pcode_serial", "序号")):
            value = entry[key]
            parts.append("%s `%s`" % (label, value)) if value else parts.append("%s %s" % (label, MISSING))
        text += "（解析状态 %s：%s）" % (entry["pcode_status"], "；".join(parts))
    return text


def _orgs_line_md(entry):
    orgs = entry["orgs"]
    if not orgs:
        return MISSING
    parts = []
    for org in orgs:
        if org.get("alias_missing"):
            parts.append("%s（未识别）" % org["raw"])
        elif org["canonical"] != org["raw"]:
            parts.append("%s → %s" % (org["raw"], org["canonical"]))
        else:
            parts.append(org["raw"])
    return "、".join(parts)


def _keywords_line_md(entry):
    keywords = []
    for hit in entry["hit_fields"]:
        if hit["keyword"] not in keywords:
            keywords.append(hit["keyword"])
    return "、".join("`%s`" % k for k in keywords) if keywords else "（无命中关键词）"


def render_markdown(entries, meta):
    """结构化条目 → 中文 Markdown 日报（无时钟、确定性）。

    `meta`：`{"new_count","hit_count","excluded_count","zero_hit_count","dropped_count"}`。
    """
    lines = []
    lines.append("# 政策文件雷达 · 中文日报")
    lines.append("")
    if not entries:
        lines.append("本次无新增。")
        lines.append("")
        lines.append("（新增 %d 条 / 命中 %d 条 / 剔除 %d 条 / 零命中 %d 条 / 未过校验丢弃 %d 条）"
                     % (meta["new_count"], meta["hit_count"], meta["excluded_count"],
                        meta["zero_hit_count"], meta["dropped_count"]))
        return "\n".join(lines)

    lines.append("本次新增 %d 条，命中 %d 条（剔除 %d 条 / 零命中 %d 条 / 未过校验丢弃 %d 条）。"
                 % (meta["new_count"], meta["hit_count"], meta["excluded_count"],
                    meta["zero_hit_count"], meta["dropped_count"]))
    lines.append("")
    for idx, entry in enumerate(entries, 1):
        lines.append("## %d. %s" % (idx, entry["title"]))
        lines.append("")
        lines.append("- 发布日期：%s" % (entry["pubtime"] or MISSING))
        lines.append("- 频道：%s" % (entry["channel"] or MISSING))
        lines.append("- 文号：%s" % _pcode_line_md(entry))
        lines.append("- 发布部门：%s" % _orgs_line_md(entry))
        lines.append("- 原文链接：<%s>" % (entry["url"] or MISSING))
        lines.append("- 命中关键词：%s" % _keywords_line_md(entry))
        summary = entry["summary"] or MISSING
        lines.append("- 摘要：%s" % summary)
        lines.append("")
    return "\n".join(lines).rstrip("\n")


# --- HTML 渲染 ---------------------------------------------------------------

def _e(text):
    """HTML 转义（所有动态值过这一关；`None`/空串按空串处理）。"""
    return html.escape(str(text if text is not None else ""), quote=True)


def _pcode_line_html(entry):
    raw = entry["pcode_raw"].strip()
    text = "<code>%s</code>" % _e(raw) if raw else _e(MISSING)
    if entry["pcode_status"]:
        parts = []
        for key, label in (("pcode_agency_code", "代字"), ("pcode_year", "年份"),
                           ("pcode_serial", "序号")):
            value = entry[key]
            shown = _e(value) if value else _e(MISSING)
            parts.append("%s <code>%s</code>" % (label, shown))
        text += "（解析状态 %s：%s）" % (_e(entry["pcode_status"]), "；".join(parts))
    return text


def _orgs_line_html(entry):
    orgs = entry["orgs"]
    if not orgs:
        return _e(MISSING)
    parts = []
    for org in orgs:
        if org.get("alias_missing"):
            parts.append("%s（未识别）" % _e(org["raw"]))
        elif org["canonical"] != org["raw"]:
            parts.append("%s → %s" % (_e(org["raw"]), _e(org["canonical"])))
        else:
            parts.append(_e(org["raw"]))
    return "、".join(parts)


def _keywords_line_html(entry):
    keywords = []
    for hit in entry["hit_fields"]:
        if hit["keyword"] not in keywords:
            keywords.append(hit["keyword"])
    return "、".join("<code>%s</code>" % _e(k) for k in keywords) \
        if keywords else "（无命中关键词）"


def render_html(entries, meta):
    """结构化条目 → HTML 日报（CSS 全内联、零外部渲染资源、无时钟）。

    出口常驻 `assert_no_external_resources()` 断言（K9：不是只在测试里验一次）。
    """
    head = (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>政策文件雷达 · 中文日报</title>\n"
        "<style>\n"
        "body { font-family: 'SimSun', 'Songti SC', serif; margin: 2rem auto;"
        " max-width: 56rem; line-height: 1.7; color: #222; background: #fff; }\n"
        "h1 { font-size: 1.5rem; border-bottom: 2px solid #b33; padding-bottom: .4rem; }\n"
        "h2 { font-size: 1.15rem; margin-top: 1.6rem; }\n"
        "ul { padding-left: 1.2rem; }\n"
        "code { background: #f4f4f4; padding: 0 .25rem; border-radius: 3px; }\n"
        ".muted { color: #777; }\n"
        "a { color: #06c; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
    )
    parts = [head]
    parts.append("<h1>政策文件雷达 · 中文日报</h1>\n")
    if not entries:
        parts.append("<p>本次无新增。</p>\n")
        parts.append('<p class="muted">新增 %d 条 / 命中 %d 条 / 剔除 %d 条 / 零命中 %d 条 / 未过校验丢弃 %d 条</p>\n'
                     % (meta["new_count"], meta["hit_count"], meta["excluded_count"],
                        meta["zero_hit_count"], meta["dropped_count"]))
    else:
        parts.append("<p>本次新增 %d 条，命中 %d 条（剔除 %d 条 / 零命中 %d 条 / 未过校验丢弃 %d 条）。</p>\n"
                     % (meta["new_count"], meta["hit_count"], meta["excluded_count"],
                        meta["zero_hit_count"], meta["dropped_count"]))
        for idx, entry in enumerate(entries, 1):
            parts.append("<h2>%d. %s</h2>\n" % (idx, _e(entry["title"])))
            parts.append("<ul>\n")
            parts.append("<li>发布日期：%s</li>\n" % (_e(entry["pubtime"]) if entry["pubtime"] else _e(MISSING)))
            parts.append("<li>频道：%s</li>\n" % (_e(entry["channel"]) if entry["channel"] else _e(MISSING)))
            parts.append("<li>文号：%s</li>\n" % _pcode_line_html(entry))
            parts.append("<li>发布部门：%s</li>\n" % _orgs_line_html(entry))
            if entry["url"]:
                parts.append('<li>原文链接：<a href="%s">%s</a></li>\n'
                             % (_e(entry["url"]), _e(entry["url"])))
            else:
                parts.append("<li>原文链接：%s</li>\n" % _e(MISSING))
            parts.append("<li>命中关键词：%s</li>\n" % _keywords_line_html(entry))
            summary = entry["summary"] or MISSING
            parts.append("<li>摘要：%s</li>\n" % _e(summary))
            parts.append("</ul>\n")
    parts.append("</body>\n</html>\n")
    document = "".join(parts)
    assert_no_external_resources(document)
    return document


# --- 零外链断言（渲染出口常驻，K9） -------------------------------------------

def assert_no_external_resources(html_text):
    """渲染出口常驻断言：HTML 的**渲染资源**零外部引用（K9）。

    口径（测试同源）："零外链"指**渲染资源**（脚本/样式/字体/图片/内嵌框引用）
    零外部引用——保证断网本地可开；条目自带的 `url` 字段是**原文链接**（内容），
    属正常字段，不在本断言的扫描面里。
    违规直接 `AssertionError`（渲染层自证，不静默产出带外链资源的日报）。
    """
    match = _EXTERNAL_RESOURCE_RE.search(html_text)
    if match:
        raise AssertionError(
            "日报 HTML 出现外部渲染资源引用（K9 零外链违规）：%r"
            % html_text[max(match.start() - 40, 0):match.end() + 40])
    # 资源类标签**内部**不得出现 http(s) 外链（href/src 指向外部）。
    for m in re.finditer(r"<\s*(script|link|img|iframe)\b[^>]*>", html_text, re.I):
        if _EXTERNAL_SCHEME_RE.search(m.group(0)):
            raise AssertionError(
                "日报 HTML 资源标签含外部 URL（K9 零外链违规）：%r" % m.group(0))
    return True


# --- 产物构造与 CLI ----------------------------------------------------------

def build_digest_product(new_items_path, hits_path, parse_path=None, fmt="both"):
    """构造日报产物：`{markdown, html, entries, meta, ...}`（双跑逐字节一致）。

    `fmt` ∈ `md/html/both`（CLI `--format` 同源）；`html` 只在 fmt ∈ (html, both)
    时渲染。判定结论一律来自输入产物（K9 零判定）。
    """
    if fmt not in DIGEST_FORMATS:
        raise DigestInputError("--format 只支持 %s：%r" % ("/".join(DIGEST_FORMATS), fmt))
    new_obj, new_items, hits, excluded, zero_hit_ids = load_digest_inputs(
        new_items_path, hits_path)

    parse_map = {}
    if parse_path:
        parse_obj = _load_obj(parse_path, "解析产物")
        _require_format(parse_obj, "policy-radar-parse", "解析产物", parse_path)
        records = parse_obj.get("parsed_items")
        if isinstance(records, list):
            for record in records:
                parse_map[record.get("item_id")] = record

    entries, dropped = report_entries(new_items, hits, parse_map)
    meta = {
        "new_count": new_obj.get("new_count", len(new_items)),
        "hit_count": len(hits),
        "excluded_count": len(excluded),
        "zero_hit_count": len(zero_hit_ids),
        "dropped_count": len(dropped),
    }
    product = {
        "format": DIGEST_FORMAT,
        "format_version": DIGEST_FORMAT_VERSION,
        "note": "中文日报产出（M5）：Markdown/HTML 同一渲染源；无时间戳（双跑逐字节一致）；"
                "渲染层零判定（K9）；HTML 渲染资源零外链（原文链接是内容字段，不属资源）。",
        "format_requested": fmt,
        "new_count": meta["new_count"],
        "hit_count": meta["hit_count"],
        "excluded_count": meta["excluded_count"],
        "zero_hit_count": meta["zero_hit_count"],
        "dropped_count": meta["dropped_count"],
        "dropped": dropped,
        "item_count": len(entries),
        "entries": entries,
    }
    product["markdown"] = render_markdown(entries, meta)
    product["html"] = render_html(entries, meta) if fmt in ("html", "both") else ""
    return product


def write_digest(out_path, product, fmt):
    """按 `fmt` 写日报文件，返回写出的路径列表。

    - `--out` 给出且 fmt = md/html → 按给定扩展名写单文件；
    - fmt = both 且 `--out` 未给 → 默认 `out/report.md` + `out/report.html`；
      `--out` 给了 → 以其为主干替换扩展名派生另一格式（`report.md` ↔ `report.html`）；
    - fmt = md/html 且 `--out` 未给 → 默认 `out/report.md` / `out/report.html`。
    """
    base, ext = os.path.splitext(out_path)
    paths = []
    if fmt == "md":
        write_text(out_path, product["markdown"])
        paths.append(out_path)
    elif fmt == "html":
        write_text(out_path, product["html"])
        paths.append(out_path)
    else:  # both
        md_path = base + ".md" if ext != ".md" else out_path
        html_path = base + ".html" if ext != ".html" else out_path
        if md_path == html_path:  # `--out report`（无扩展名）的退化输入
            md_path, html_path = base + ".md", base + ".html"
        write_text(md_path, product["markdown"])
        write_text(html_path, product["html"])
        paths.extend([md_path, html_path])
    return paths


def cmd_digest(args):
    """`digest` 子命令：读新增清单 + 订阅命中 → 渲染中文日报（Markdown/HTML）。

    退出码：0 = 完成；1 = 有条目未过校验被丢弃（降级完成，日报照常产出）；
    2 = 用法/输入错误。
    """
    new_items_path = getattr(args, "new_items", None)
    hits_path = getattr(args, "hits", None)
    parse_path = getattr(args, "parse", None)
    if not new_items_path:
        raise UsageError("--new-items 必填（diff 产物）")
    if not hits_path:
        raise UsageError("--hits 必填（subscribe 产物）")
    fmt = getattr(args, "format", None) or "both"
    out_path = getattr(args, "out", None) or DEFAULT_DIGEST_OUT

    product = build_digest_product(new_items_path, hits_path,
                                   parse_path=parse_path, fmt=fmt)
    paths = write_digest(out_path, product, fmt)

    for path in paths:
        sys.stdout.write("  已写出 %s\n" % path)
    sys.stdout.write(
        "  digest: 新增 %d 条 / 命中 %d 条（剔除 %d 条 / 零命中 %d 条）/ 进日报 %d 条"
        "%s\n"
        % (product["new_count"], product["hit_count"], product["excluded_count"],
           product["zero_hit_count"], product["item_count"],
           ("；丢弃 %d 条（未过 schema 校验，不进日报）" % product["dropped_count"])
           if product["dropped_count"] else ""))
    if product["dropped_count"]:
        return 1  # EXIT_DEGRADED（避免顶部循环 import，按 K2 语义字面量 + 测试锁定）
    return 0
