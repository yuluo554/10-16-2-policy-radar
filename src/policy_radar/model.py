"""统一中间表示（PolicyItem）与统一 schema 常量。

两个频道（`zhengcelibrary_gwy` / `zhengcelibrary_bm`）的返回字段一致，统一为下表；
字段与 API 实测字段一一对应（勘误与取数路径见 data/README.md 与 plan/03-架构与技术选型.md）。

| 字段 | 来源 | 说明 |
|---|---|---|
| source | 我方注入 | 频道标识 `gwy` / `bm`（API 未返回） |
| id | API `id` | **去重主键**（实测两频道均非空） |
| index | API `index` | 去重副键（**部委频道实测为空**） |
| pcode | API `pcode` | 文号原文，可空（部委实测 3/30 空） |
| title | API `title` | 标题 |
| pubtimeStr | API `pubtimeStr` | 发布日期 `YYYY.MM.DD` |
| puborg | API `puborg` | 发布机关原文（可为空格分隔多部门） |
| url | API `url` | 原文链接（抓取目标只认此字段） |
| summary | API `summary` | 摘要 |
| channel | 我方注入 | 中文频道名，渲染用 |

**显式排除**：`fwzh` / `wenhao` / `wjlx` 实测 60/60 全空，不作任何判定依据；
`piclinksurl` / `imgurl` / `theme` / `personal` 等 UI 字段不入模型。
"""

import datetime
import re

#: 频道标识 -> 中文名（抓取与渲染共用，单一来源）。
CHANNELS = {
    "gwy": "国务院",
    "bm": "部委",
}

#: 统一 schema 的字段集合与顺序（K1；改此常量属"动了会打挂测试"的口径变更）。
SCHEMA_FIELDS = (
    "source",
    "id",
    "index",
    "pcode",
    "title",
    "pubtimeStr",
    "puborg",
    "url",
    "summary",
    "channel",
)

#: 必填字段（缺失即该条不得落库/不得进日报，FR-11）。
REQUIRED_FIELDS = ("source", "id", "title", "pubtimeStr", "puborg", "url", "summary")

#: 快照字段白名单（K10）：快照里出现以下任一字段即违反"不做全文归档"边界。
FORBIDDEN_SNAPSHOT_FIELDS = (
    "content",
    "body",
    "fulltext",
    "full_text",
    "html",
    "text",
    "article",
)

_DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")


class PolicyItem(object):
    """一条政策文件元数据（统一中间表示）。

    只承载元数据与链接，**不含正文**（边界 2：不做全文下载归档）。
    """

    __slots__ = SCHEMA_FIELDS

    def __init__(self, source, id, title, pubtimeStr, puborg, url, summary,
                 pcode="", index="", channel=""):
        self.source = source
        self.id = id
        self.index = index
        self.pcode = pcode
        self.title = title
        self.pubtimeStr = pubtimeStr
        self.puborg = puborg
        self.url = url
        self.summary = summary
        self.channel = channel or CHANNELS.get(source, source)

    def to_dict(self):
        """按 SCHEMA_FIELDS 固定顺序导出 dict（写盘顺序因此与字段定义一致）。"""
        return dict((f, getattr(self, f)) for f in SCHEMA_FIELDS)

    @classmethod
    def from_dict(cls, d):
        """从 API 条目或快照记录构造；只认白名单字段，多余字段忽略。"""
        return cls(
            source=d.get("source", ""),
            id=d.get("id", ""),
            title=d.get("title", ""),
            pubtimeStr=d.get("pubtimeStr", ""),
            puborg=d.get("puborg", ""),
            url=d.get("url", ""),
            summary=d.get("summary", ""),
            pcode=d.get("pcode", ""),
            index=d.get("index", ""),
            channel=d.get("channel", ""),
        )

    # --- 校验 ---------------------------------------------------------------
    def validate(self):
        """返回缺失的必填字段名列表（空列表 = 通过）。

        未通过校验的条目**不得落库、不得进日报**（FR-11）——调用方负责把它计进
        `dropped_count` 并降级，绝不补编字段。
        """
        missing = []
        for f in REQUIRED_FIELDS:
            if not str(getattr(self, f, "") or "").strip():
                missing.append(f)
        return missing

    def date_valid(self):
        """`pubtimeStr` 形态与真实性校验（`YYYY.MM.DD`）。

        两步：① 分隔符形态由正则把关（`2026-10-08` 这类不得放过）；② **用
        `datetime.date()` 校验组合真实性**——"2026.13.45" 这种"月日各自合法但组合不存在"
        的日期必须被挡下（否则会被当作"已提供"，把真实缺陷读成合规）。
        """
        text = self.pubtimeStr or ""
        if not _DATE_RE.match(text):
            return False
        try:
            datetime.date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
        except (ValueError, TypeError):
            return False
        return True

    def __eq__(self, other):
        if not isinstance(other, PolicyItem):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __hash__(self):
        return hash(tuple(getattr(self, f) for f in SCHEMA_FIELDS))

    def __repr__(self):
        return "PolicyItem(source=%r, id=%r, pcode=%r, pubtimeStr=%r)" % (
            self.source, self.id, self.pcode, self.pubtimeStr,
        )


def item_from_api(entry, source):
    """把 API 的 `searchVO.listVO` 条目转成 PolicyItem。

    **取数路径**：条目在 `searchVO.listVO`，响应顶层 `data` 实测为 `null`——
    调用方须先取到 listVO 再逐条喂进来（见 fetch.py）。
    """
    return PolicyItem(
        source=source,
        id=str(entry.get("id", "") or ""),
        title=entry.get("title", "") or "",
        pubtimeStr=entry.get("pubtimeStr", "") or "",
        puborg=entry.get("puborg", "") or "",
        url=entry.get("url", "") or "",
        summary=entry.get("summary", "") or "",
        pcode=entry.get("pcode", "") or "",
        index=entry.get("index", "") or "",
    )


def items_from_listvo(payload, source):
    """从完整 API 响应里抽出条目列表。

    显式拒绝结构异常（不静默按最宽松规则解析）：缺 `searchVO` 或缺 `listVO` 即抛
    ValueError，由调用方转成 exit 4。
    """
    if not isinstance(payload, dict):
        raise ValueError("API 响应不是 JSON 对象")
    sv = payload.get("searchVO")
    if not isinstance(sv, dict):
        raise ValueError("API 响应缺少 searchVO 对象")
    lst = sv.get("listVO")
    if not isinstance(lst, list):
        raise ValueError("API 响应缺少 searchVO.listVO 列表")
    return [item_from_api(e, source) for e in lst if isinstance(e, dict)]


def total_count(payload):
    """响应声明的总数（供抓取器与"实际取到条数"对账，不得当作"我拿到了这么多"）。"""
    sv = payload.get("searchVO") or {}
    return sv.get("totalCount")
