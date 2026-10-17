"""关键词订阅 + 命中判定（M4 模块 4）；订阅命中能力落点（供 `bench` 与 M5 日报）。

设计纪律（`plan/04-模块详设.md` 模块 4，逐条对应）：

1. **确定性匹配（K8）**：归一化后**子串包含**——不做相关性打分、不做分词、
   不做模糊匹配。命中判定 = `keyword in title or keyword in summary`（归一后）。
2. **全半角归一**（单一来源 `data/config/normalize.json`）：关键词与文本
   **两侧都归一**（`apply_to: both_keyword_and_text`）。归一表**长度保持**
   （K16：单字符 → 单字符），故命中位置 `offset` 在归一前后同值——
   真值里登记的 offset 就是**原始字段文本**里的起始下标，可审计。
3. **exclude 命中整条剔除**（`exclude_policy: drop_item_entirely`）：被剔除的
   条目记 `include_matched_before_exclusion`（可回溯"确实只中了 exclude"，
   还是"两样都中被 exclude 优先"）。剔除条目**不产生命中记录**。
4. **同词去重**：同一关键词重复配置（如 `规划` 在 include 里出现两次）按
   **归一后**关键词去重、保持配置顺序（`dedup_rule`）——重复词只产生一条命中。
5. **命中字段与位置可回溯**：按 `FIELD_PRIORITY`（title 优先、其次 summary）
   取**首次出现**的字段与下标；每词一条记录，同一条目命中多词 → 多条记录。
6. **配置口径校验**：`match_rule` / `field_priority` / `exclude_policy` /
   `dedup_rule` 不是本模块实现的口径即拒绝工作（宁可显式报错也不静默套错语义，
   同 `parse.load_org_aliases` 的纪律）。

对账与测试：生产实现与真值的比对走 `cases.compare_subscribe`（K15 共用对账语义），
在**测试与基准**里做；本模块**不得** import `cases`（K14——参照实现与字段序常量
在本模块各自单点声明，两处一致性由真值对账测试守门）。

实现路径说明：参照实现 `cases.naive_match` 用逐字符映射 + `str.find`（故意笨）；
生产实现走**正则预编译（`re`）+ 命中位置取 `match.start()`** 的不同代码路径——
两路径的分歧由真值对账暴露（K14）。
"""

import re

from .errors import UsageError

#: 命中字段优先序（单一来源；与真值 `semantics.field_priority` 同口径，
#: 值 = 真值里登记的 field 名）。
FIELD_PRIORITY = ("title", "summary")

#: 订阅配置的既定口径（与 `data/config/subscribe.json` 的声明同值；不符即拒绝）。
MATCH_RULE = "substring_containment_after_normalization"
DEDUP_RULE = "dedup_by_normalized_keyword_preserve_config_order"
EXCLUDE_POLICY = "drop_item_entirely"

#: 归一表的既定口径：作用域 = 关键词与文本两侧；映射必须长度保持（K16）。
NORMALIZE_APPLY_TO = "both_keyword_and_text"


def validate_norm_map(norm_map):
    """归一表必须**长度保持**（K16：单字符 → 单字符），否则 offset 语义失效。

    违规即 `UsageError`（exit 2）——不静默按非长度保持表匹配（位置会移位，
    真值里的 offset 就成了"哪一份文本的下标"的糊涂账）。
    """
    for src, dst in sorted(norm_map.items()):
        if len(src) != 1 or len(dst) != 1:
            raise UsageError(
                "归一表非单字符映射（K16 长度保持违规，offset 语义失效）：%r -> %r"
                % (src, dst))


def validate_subscribe_config(config, path="subscribe.json"):
    """订阅配置口径校验：本模块只实现既定的四种口径，不符即显式拒绝（exit 2）。"""
    if config.get("match_rule") != MATCH_RULE:
        raise UsageError("订阅配置 match_rule 不是 %s（本模块只实现该口径）：%s"
                         % (MATCH_RULE, path))
    if config.get("dedup_rule") != DEDUP_RULE:
        raise UsageError("订阅配置 dedup_rule 不是 %s：%s" % (DEDUP_RULE, path))
    if config.get("exclude_policy") != EXCLUDE_POLICY:
        raise UsageError("订阅配置 exclude_policy 不是 %s：%s" % (EXCLUDE_POLICY, path))
    priority = tuple(config.get("field_priority") or ())
    if priority != FIELD_PRIORITY:
        raise UsageError("订阅配置 field_priority 不是 %r：%s"
                         % (FIELD_PRIORITY, path))
    for key in ("include", "exclude"):
        if not isinstance(config.get(key), list):
            raise UsageError("订阅配置缺少 %s 列表：%s" % (key, path))


def compile_patterns(keywords, norm_map):
    """关键词 → `[(原文, 归一后, 预编译正则)]`（按**归一后**去重、保持配置顺序）。

    生产实现与参照实现的路径差异点：这里把每个关键词预编译成
    `re.compile(re.escape(归一后关键词))`，匹配用 `pattern.search`、
    位置取 `match.start()`——而参照实现 `cases.naive_match` 用
    `str.find`。`re.escape` 保证关键词里的正则元字符（如引号）按字面匹配。
    """
    out = []
    seen = set()
    for kw in keywords:
        normalized = _normalize(kw, norm_map)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append((kw, normalized, re.compile(re.escape(normalized))))
    return out


def _normalize(text, norm_map):
    """按归一表逐字符替换（关键词与文本两侧都归一）。"""
    return "".join(norm_map.get(ch, ch) for ch in (text or ""))


def _first_hit(pattern, title_n, summary_n):
    """按 `FIELD_PRIORITY`（title 先）找首次出现，返回 `(field, offset)` 或 None。

    `offset` 是**归一后**文本里的下标；归一表长度保持（K16），
    故与原始字段文本里的下标同值。
    """
    for field in FIELD_PRIORITY:
        text_n = title_n if field == "title" else summary_n
        match = pattern.search(text_n)
        if match:
            return field, match.start()
    return None


def match_items(items, include, exclude, norm_map):
    """订阅命中判定（K8 生产实现）。返回 `(hits, excluded, zero_hit_ids)`。

    参数：`items` 为对象序列（需有 `.id` / `.title` / `.summary`），
    `include` / `exclude` 为关键词列表，`norm_map` 为归一表（已过
    `validate_norm_map` 校验）。

    判定顺序（排除优先）：任一 exclude 命中 → 整条剔除（记
    `include_matched_before_exclusion`，**不产生命中记录**）；否则按 include
    逐词（配置序、去重后）取首次命中 → 每词一条 `{item_id, keyword, field,
    offset}`；全不中 → 记 `zero_hit_ids`。

    **确定性**：不打分、不分词、不读时钟；同输入同输出。
    """
    validate_norm_map(norm_map)
    inc = compile_patterns(include, norm_map)
    exc = compile_patterns(exclude, norm_map)

    hits = []
    excluded = []
    zero = []
    for item in items:
        title_n = _normalize(item.title, norm_map)
        summary_n = _normalize(item.summary, norm_map)

        # exclude 优先（排除策略 = 整条剔除）：先扫排除词，再扫 include。
        matched_exc = [original for original, _n, pattern in exc
                       if pattern.search(title_n) or pattern.search(summary_n)]
        matched_inc = []
        for original, _n, pattern in inc:
            hit = _first_hit(pattern, title_n, summary_n)
            if hit is not None:
                matched_inc.append((original, hit[0], hit[1]))

        if matched_exc:
            excluded.append({
                "item_id": item.id,
                "matched_exclude": matched_exc,
                "include_matched_before_exclusion":
                    [k for k, _f, _o in matched_inc],
            })
            continue
        if not matched_inc:
            zero.append(item.id)
            continue
        for keyword, field, offset in matched_inc:
            hits.append({"item_id": item.id, "keyword": keyword,
                         "field": field, "offset": offset})
    return hits, excluded, zero


def sort_hits_like_truth(hits, excluded, zero, items, include, norm_map):
    """把观测结果排成**真值口径**的顺序（对账是逐键点名，序不影响 ok 判定，
    但输出对齐真值便于人读与逐条 diff）。

    顺序（与生成器一致）：条目按语料输入序；关键词按**去重后**配置序
    （重复词只占一个位次，防相对次序漂移）。
    """
    item_order = dict((it.id, idx) for idx, it in enumerate(items))
    keyword_order = dict((kw, idx)
                         for idx, kw in enumerate(_keyword_order(include, norm_map)))
    hits_sorted = sorted(hits, key=lambda h: (item_order.get(h["item_id"], 0),
                                              keyword_order.get(h["keyword"], 0)))
    excluded_sorted = sorted(excluded,
                             key=lambda e: item_order.get(e["item_id"], 0))
    zero_sorted = sorted(zero, key=lambda i: item_order.get(i, 0))
    return hits_sorted, excluded_sorted, zero_sorted


def _keyword_order(include, norm_map):
    """去重后的关键词配置序（编译去重与排序共用同一份去重语义）。"""
    return [normalized for _orig, normalized, _p in compile_patterns(include, norm_map)]


# --- 配置/归一表装载（CLI 通路；真值对账的输入入口） ------------------------

def load_subscribe_inputs(data_root, config_dir="config"):
    """读订阅配置与归一表（单一来源 `data/config/`），校验口径 → `(config, norm_map)`。

    缺失/坏格式/口径不符 → `UsageError`（exit 2）；归一表空或非长度保持同拒。
    """
    import os

    from .serialize import read_json

    config_path = os.path.join(data_root, config_dir, "subscribe.json")
    normalize_path = os.path.join(data_root, config_dir, "normalize.json")
    for path in (config_path, normalize_path):
        if not os.path.isfile(path):
            raise UsageError("订阅规则数据缺失：%s" % path)
    try:
        config = read_json(config_path)
        normalize = read_json(normalize_path)
    except ValueError as exc:
        raise UsageError(str(exc))

    validate_subscribe_config(config, config_path)
    norm_map = normalize.get("map")
    if not isinstance(norm_map, dict) or not norm_map:
        raise UsageError("归一表为空或格式错：%s" % normalize_path)
    if normalize.get("apply_to") != NORMALIZE_APPLY_TO:
        raise UsageError(
            "归一表 apply_to 不是 %r（关键词与文本须两侧归一）：%s"
            % (NORMALIZE_APPLY_TO, normalize_path))
    validate_norm_map(norm_map)
    return config, norm_map
