#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成器共享底座（M1）：确定性 RNG、观测池加载、规范排序、字节工具。

**这是 tools/ 下的私有支撑模块，不挂到用户 CLI 上**（plan/03 第五节：`tools/`
仅发布/审计/数据生成期新增）。

设计纪律（plan/05 第三节）：
- **确定性生成**：自研 splitmix64 RNG（**禁 stdlib `random`**——它不承诺跨版本序列一致）；
  固定 seed；**全程不读时钟**；落盘产物无时间戳。
- **禁 set 迭代序**：凡参与产物顺序的集合一律先转 `sorted()` 再消费（set 序在
  CPython 里对 str 虽是确定的，但依赖它等于把产物绑死在实现细节上）。
- **合成素材取自实采**：快照对的条目来自 `data/samples/*-n30.json` 观测池
  （真实 id / pcode / title / puborg / url），**不编造不存在的机关代字与数值**。
- 写盘一律经 `serialize.py`（写盘单点），不在生成器里各写各的 `open()+json.dump()`。
"""

import hashlib
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from policy_radar.model import PolicyItem, items_from_listvo  # noqa: E402
from policy_radar.serialize import read_json  # noqa: E402

#: 生成器固定 seed（改它 = 换一整套冻结产物，属"动了会打挂测试"的口径变更）。
DEFAULT_SEED = 20261017

#: 观测池样本（真实抓取，两频道各 30 条）。
POOL_SAMPLES = (("gwy-p1-n30.json", "gwy"), ("bm-p1-n30.json", "bm"))

#: 快照文件格式标识（M3 的 snapshot.py 必须认这一形态）。
SNAPSHOT_FORMAT = "policy-radar-snapshot"
SNAPSHOT_FORMAT_VERSION = 1

_MASK = (1 << 64) - 1


class SplitMix64(object):
    """splitmix64 确定性伪随机数发生器（自研，**不用 stdlib `random`**）。

    stdlib `random` 的序列不承诺跨 Python 版本一致（Mersenne Twister 的播种与
    取样路径都变过）——一旦生成器产物依赖它，"再生成位级一致"守门会跨版本假红。
    splitmix64 是纯整数运算，跨版本、跨平台（含 32/64 位）逐位一致。
    """

    def __init__(self, seed=DEFAULT_SEED):
        self.state = seed & _MASK

    def next_u64(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & _MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        return (z ^ (z >> 31)) & _MASK

    def below(self, n):
        """返回 [0, n) 的整数（拒绝采样，避免取模偏置）。"""
        if n <= 0:
            raise ValueError("below(n) 需要 n > 0，收到 %r" % (n,))
        limit = (1 << 64) - ((1 << 64) % n)
        while True:
            v = self.next_u64()
            if v < limit:
                return v % n

    def shuffle(self, seq):
        """Fisher-Yates 洗牌（用本 RNG，不用 stdlib `random.shuffle`）。"""
        out = list(seq)
        for i in range(len(out) - 1, 0, -1):
            j = self.below(i + 1)
            out[i], out[j] = out[j], out[i]
        return out


# --- 规范排序（K5 口径：pubtimeStr 倒序, id 升序；全程不读时钟） ----------------

def canonical_order(items):
    """按 `(pubtimeStr 倒序, id 升序)` 排序。

    两步实现（先按 id 升序、再**稳定**按 pubtimeStr 倒序）——比手写复合键更不易写错：
    `sorted(key=lambda x: (-date, id))` 需要把日期转成可比较的数值，而
    `pubtimeStr` 是定宽 `YYYY.MM.DD` 字符串，倒序即字典序反转，故两步法正确且直观。
    """
    by_id = sorted(items, key=lambda it: it.id)
    by_id.sort(key=lambda it: it.pubtimeStr, reverse=True)
    return by_id


# --- 观测池 -----------------------------------------------------------------

def load_pool(samples_dir):
    """加载观测池（真实条目），按 `(source, id)` 稳定去重后返回。

    **取数路径**：`searchVO.listVO`（决策 D13，`model.items_from_listvo` 已按此实现）。
    """
    seen = {}
    for fname, source in POOL_SAMPLES:
        path = os.path.join(samples_dir, fname)
        payload = read_json(path)
        for item in items_from_listvo(payload, source):
            seen[(item.source, item.id)] = item
    keys = sorted(seen)  # 禁 set 迭代序：显式排序后再消费
    return [seen[k] for k in keys]


# --- 快照形态 ---------------------------------------------------------------

def make_snapshot(items, note):
    """构造快照对象（字段白名单 = PolicyItem 全部字段，**无全文**，无时间戳）。"""
    ordered = canonical_order(items)
    return {
        "format": SNAPSHOT_FORMAT,
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "note": note,
        "item_count": len(ordered),
        "items": [it.to_dict() for it in ordered],
    }


def load_snapshot(path):
    """读快照文件，返回 PolicyItem 列表（校验形态，不静默按最宽松规则解析）。"""
    obj = read_json(path)
    if not isinstance(obj, dict) or obj.get("format") != SNAPSHOT_FORMAT:
        raise ValueError("快照格式不是 %s：%s" % (SNAPSHOT_FORMAT, path))
    items = obj.get("items")
    if not isinstance(items, list):
        raise ValueError("快照缺少 items 列表：%s" % path)
    if obj.get("item_count") != len(items):
        raise ValueError("快照 item_count 与实际条数不符：%s" % path)
    return [PolicyItem.from_dict(d) for d in items]


def clone_item(item, **overrides):
    """复制条目并按需覆盖字段（供合成变体；其余字段原样保留）。"""
    d = item.to_dict()
    d.update(overrides)
    return PolicyItem.from_dict(d)


# --- 字节工具 ---------------------------------------------------------------

def sha256_file(path):
    with io.open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def relative_posix(path, root):
    """返回相对 root 的 POSIX 风格路径（产物里记路径不记绝对路径，跨机可比）。"""
    rel = os.path.relpath(path, root)
    return rel.replace(os.sep, "/")


# --- 生成守卫公共件 ---------------------------------------------------------

def assert_no_forbidden_snapshot_fields(snapshot):
    """K10：快照出现 `content/body/fulltext` 一类字段即红。"""
    from policy_radar.model import FORBIDDEN_SNAPSHOT_FIELDS
    forbidden = set(FORBIDDEN_SNAPSHOT_FIELDS)
    for it in snapshot["items"]:
        hit = set(it.keys()) & forbidden
        if hit:
            raise AssertionError("快照出现禁字段（不做全文归档）：%r" % sorted(hit))


def assert_no_observed_fields(obj, where="产物"):
    """K11：真值台账不得出现 `observed_*` 一类字段（出现即红）。

    冻结"观测"会让基准退化成"比对两份预先算好的答案"，引擎整个坏掉也照样全绿。
    """
    offenders = []

    def walk(node, trail):
        if isinstance(node, dict):
            for k in sorted(node):
                if isinstance(k, str) and (k.startswith("observed")
                                           or k.startswith("_observed")):
                    offenders.append("%s.%s" % (trail, k))
                walk(node[k], "%s.%s" % (trail, k))
        elif isinstance(node, list):
            for idx, v in enumerate(node):
                walk(v, "%s[%d]" % (trail, idx))

    walk(obj, where)
    if offenders:
        raise AssertionError("真值库出现 observed 类字段（K11 违规）：%r" % offenders)


def dump_pool(samples_dir):
    """打印观测池（规范序），供人工挑选与复核。"""
    for idx, it in enumerate(canonical_order(load_pool(samples_dir))):
        sys.stdout.write("%3d  %-4s %-10s %-26s %-12s %s\n" % (
            idx, it.source, it.id, it.pcode or "(空)", it.pubtimeStr,
            (it.puborg or "")[:34]))
