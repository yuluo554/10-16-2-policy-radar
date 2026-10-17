"""文号三态解析（K6）+ 部门归一（K7）（M3 模块 3）；`parse` 子命令落点。

设计纪律（`plan/04-模块详设.md` 模块 3，逐条对应）：

1. **规则化解析，不做语义猜测**：
   - 有括号（`〔〕` = U+3014/U+3015 或全角 `﹝﹞` = U+FE5D/FE5E，E6）：
     代字 = 左括号前全部非空字符（**不做白名单硬编码**——实测代字可含
     `字`/`联规` 等）；年份 = 括号内**四位数字**；序号 = `〕` 之后到 `号`
     之前的数字串（容忍序号与"号"之间的空白，E7；无 `号` 时取 `〕` 后全体）。
   - 无括号但有 `第…号`（如 `国令第847号`）：代字 = `第` 前字符；
     年份 = `未解析`（**不编造**）；序号 = `第` 与 `号` 之间的数字串。
   - 其它：整条 `unparsed`。
2. **失败显式"未解析"**：哨兵串 = `未解析`（与 `data/truth/pcode-truth.json`
   的 `unparsed_sentinel` 同值）；部分字段失败不得当全字段成功。
3. **解析结果三态（K6）**：`parsed`（三字段全出）/ `partial`（部分字段）/
   `unparsed`（整条）——**不把 partial 当 parsed**。
4. **部门归一（K7）**：`puborg` 按 `\\s` 类空白拆分（E5：分隔符含 U+2002
   EN SPACE 且同串混用，**不能只按 `' '`**）；逐 token 查别名表；别名表
   **单一来源** `data/config/org-aliases.json`，本模块不另建第二份；
   匹配 = **前缀匹配 + 最长优先**（部门名是串首；防短串吃掉长串前缀，如
   `国务院` 不能把 `国务院办公厅` 读成 `国务院`）；认不出的**原样保留** +
   `alias_missing`（**不猜**）。
5. **别名表口径校验**：表里 `match_rule` 不是 `longest_first` 即拒绝工作
   （本模块只实现这一种口径，宁可显式报错也不静默套错语义）。

对账与测试：生产实现与真值的比对走 `cases.compare_pcode`（K15 共用对账语义），
在**测试**里做；本模块**不得** import `cases`（K14，源码扫描守门）。
"""

import os
import re
import sys

from .errors import EXIT_OK, UsageError
from .paths import find_data_root
from .serialize import read_json, write_json
from .snapshot import load_items_file

#: 未解析字段的哨兵值（三态契约之一，与真值 `unparsed_sentinel` 同值）。
UNPARSED = "未解析"

#: 文号解析三态（K6）。
STATUS_PARSED = "parsed"
STATUS_PARTIAL = "partial"
STATUS_UNPARSED = "unparsed"
STATUS_VALUES = (STATUS_PARSED, STATUS_PARTIAL, STATUS_UNPARSED)

#: 六角括号与其全角变体（E6 实测：`﹝﹞` 是不同码位；成对使用）。
BRACKET_PAIRS = (("\u3014", "\u3015"), ("\ufe5d", "\ufe5e"))

#: parse 产物格式标识。
PARSE_FORMAT = "policy-radar-parse"
PARSE_FORMAT_VERSION = 1

#: 默认产出路径（`/out/` 已在 `.gitignore` 覆盖：运行时产物不入库）。
DEFAULT_PARSE_OUT = "out/parsed.json"

#: 部门别名表相对数据根的路径（K7 单一来源）。
ORG_ALIASES_REL = os.path.join("config", "org-aliases.json")

#: 无括号形态：`第…号`（`第` 前至少一个字符，镜像参照实现 `di > 0` 的约束）。
_DECREE_RE = re.compile(r"^(?P<agency>[^\u7b2c]+)\u7b2c(?P<body>[^\u53f7]*)\u53f7")

#: 拆分 `puborg` 的空白（E5：`\s` 类含 U+2002 / U+00A0 等；只按 `' '` 会拆不开）。
_WHITESPACE_RE = re.compile(r"\s+")


# --- 文号解析（K6） ---------------------------------------------------------

def _find_bracket_pair(text):
    """找第一个**完整**的括号对（先 `〔〕` 后全角变体，镜像实测形态的检查顺序）。

    左括号出现但配不到右括号时换下一对（如 `〔` 单独出现不构成形态），
    与参照实现的行为一致。
    """
    for left, right in BRACKET_PAIRS:
        pos = text.find(left)
        if pos >= 0:
            end = text.find(right, pos + 1)
            if end > pos:
                return pos, end
    return None, None


def _is_year(text):
    """年份 = 四位数字（`str.isdigit()` 判定，与哨兵语义对齐）。"""
    return len(text) == 4 and text.isdigit()


def _digits(text):
    """抽取数字串（保持出现顺序拼接）；无数字则 `未解析`。"""
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits if digits else UNPARSED


def _serial_from_tail(tail):
    """序号 = `〕` 之后到 `号` 之前的数字串（无 `号` 则取 `〕` 后全体）。

    E7：序号与"号"之间可有空格（`农农发〔2026〕9 号` → `9` 不带尾空格）——
    空白不进数字串，天然容忍。
    """
    before_hao = tail.split("\u53f7", 1)[0]
    return _digits(before_hao)


def _with_status(fields):
    """按已解析字段数定三态：3 → parsed；1–2 → partial；0 → unparsed。"""
    known = [v for v in fields.values() if v != UNPARSED]
    if len(known) == 3:
        status = STATUS_PARSED
    elif known:
        status = STATUS_PARTIAL
    else:
        status = STATUS_UNPARSED
    out = dict(fields)
    out["status"] = status
    return out


def _unparsed_all():
    return {"agency_code": UNPARSED, "year": UNPARSED, "serial": UNPARSED,
            "status": STATUS_UNPARSED}


def parse_pcode(pcode):
    """把文号原文拆成 `{agency_code, year, serial, status}`（K6 三态）。

    形态规则见模块 docstring；**失败显式标 `未解析`，不编造**。
    """
    text = (pcode or "").strip()
    if not text:
        return _unparsed_all()

    open_b, close_b = _find_bracket_pair(text)
    if open_b is not None:
        agency = text[:open_b].strip()
        inner = text[open_b + 1:close_b].strip()
        return _with_status({
            "agency_code": agency if agency else UNPARSED,
            "year": inner if _is_year(inner) else UNPARSED,
            "serial": _serial_from_tail(text[close_b + 1:]),
        })

    match = _DECREE_RE.match(text)
    if match:
        agency = match.group("agency").strip()
        return _with_status({
            "agency_code": agency if agency else UNPARSED,
            "year": UNPARSED,  # 无〔〕即可靠年份来源缺失：不编造
            "serial": _digits(match.group("body")),
        })

    return _unparsed_all()


# --- 部门归一（K7） ---------------------------------------------------------

def load_org_aliases(data_root):
    """读部门别名表（K7 单一来源）→ `{原始名: 规范名}`。

    缺失/为空/口径不符（`match_rule != longest_first`）一律 `UsageError`（exit 2）：
    宁可显式报错，也不静默套错匹配语义。
    """
    path = os.path.join(data_root, ORG_ALIASES_REL)
    if not os.path.isfile(path):
        raise UsageError("部门别名表缺失（K7 单一来源）：%s" % path)
    obj = read_json(path)
    aliases = obj.get("aliases")
    if not isinstance(aliases, dict) or not aliases:
        raise UsageError("部门别名表为空或格式错：%s" % path)
    if obj.get("match_rule") != "longest_first":
        raise UsageError("部门别名表 match_rule 不是 longest_first（本模块只实现该口径）：%s"
                         % path)
    return aliases


def parse_orgs(puborg, aliases):
    """`puborg` → 逐 token 的 `{raw, canonical, alias_missing}` 记录列表。

    拆分按 `\\s` 类空白（E5）；匹配 = **前缀 + 最长优先**（K7 细化口径）；
    未命中：`canonical` 原样保留（= `raw`）、`alias_missing=True`（**不猜**）。
    """
    text = (puborg or "").strip()
    if not text:
        return []
    keys = sorted(aliases, key=lambda k: (-len(k), k))
    out = []
    for token in _WHITESPACE_RE.split(text):
        if not token:
            continue
        matched = None
        for key in keys:
            if token.startswith(key):
                matched = key
                break
        if matched is None:
            out.append({"raw": token, "canonical": token, "alias_missing": True})
        else:
            out.append({"raw": token, "canonical": aliases[matched],
                        "alias_missing": False})
    return out


# --- 产物 ------------------------------------------------------------------

def build_parse_product(items, aliases):
    """构造 parse 产物：逐条目文号解析 + 部门归一 + 计数汇总。

    `parsed_items` 为逐条目记录（**输入序**，确定性来自调用方传入的清单序）；
    未解析字段显式标哨兵 `未解析`；统计三态计数与 `alias_missing` 点名。
    """
    records = []
    status_counts = {STATUS_PARSED: 0, STATUS_PARTIAL: 0, STATUS_UNPARSED: 0}
    missing_tokens = []
    missing_count = 0
    for item in items:
        parsed = parse_pcode(item.pcode)
        status_counts[parsed["status"]] += 1
        orgs = parse_orgs(item.puborg, aliases)
        for org in orgs:
            if org["alias_missing"]:
                missing_count += 1
                if org["raw"] not in missing_tokens:
                    missing_tokens.append(org["raw"])
        records.append({
            "item_id": item.id,
            "pcode": item.pcode,
            "pcode_parse": parsed,
            "puborg": item.puborg,
            "orgs": orgs,
        })
    return {
        "format": PARSE_FORMAT,
        "format_version": PARSE_FORMAT_VERSION,
        "note": "文号解析 + 部门归一产出（M3）：未解析字段显式标哨兵「未解析」；条目按输入序；不含正文。",
        "item_count": len(records),
        "pcode_status_counts": status_counts,
        "alias_missing_count": missing_count,
        "alias_missing_tokens": sorted(missing_tokens),
        "parsed_items": records,
    }


# --- CLI --------------------------------------------------------------------

def cmd_parse(args):
    """`parse` 子命令：读条目文件 → 文号三态解析 + 部门归一 → 写 parse 产物。

    退出码：0 = 完成；2 = 用法/输入错误（别名表缺失、输入不可读/不可识别等）。
    """
    input_path = getattr(args, "input", None)
    if not input_path:
        raise UsageError("--input 必填（条目文件）")
    out_path = getattr(args, "out", None) or DEFAULT_PARSE_OUT
    data_root = find_data_root(getattr(args, "data_root", None))
    if not data_root:
        raise UsageError("找不到数据根（部门别名表在 data/config/ 下；"
                         "显式传 --data-root 或设 POLICY_RADAR_DATA）")

    aliases = load_org_aliases(data_root)
    items = load_items_file(input_path)
    product = build_parse_product(items, aliases)

    try:
        write_json(out_path, product)
    except (IOError, OSError) as exc:
        raise UsageError("无法写出 parse 产物：%s" % exc)

    counts = product["pcode_status_counts"]
    token_total = sum(len(r["orgs"]) for r in product["parsed_items"])
    missing = product["alias_missing_count"]
    detail = ("：%s" % "、".join(product["alias_missing_tokens"])
              if product["alias_missing_tokens"] else "")
    sys.stdout.write(
        "  parse: 条目 %d 条；文号 parsed %d / partial %d / unparsed %d；"
        "部门 token %d 个（未识别 %d 个%s）\n"
        % (product["item_count"], counts[STATUS_PARSED], counts[STATUS_PARTIAL],
           counts[STATUS_UNPARSED], token_total, missing, detail))
    sys.stdout.write("  已写出 %s\n" % out_path)
    return EXIT_OK
