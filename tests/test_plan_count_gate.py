"""plan/ 测试数漂移守门（`plan/00` D33）。

**为什么需要这一条**：`tests/test_readme_gate.py` 已把 README 的测试数钉在实测收集数上，
但实测失效模式就在这里重演了一次——README 改了 330，`plan/00`/`06`/`07`/`HANDOFF-M6`
里的 321 却烂在原地。**只守一个文件的守门会让"另一个文件漂了"完全无声**。

**判据怎么定（关键，别写成空转）**：
`plan/` 里出现 `N 项` 的地方有两类，混在一起就会误判：

1. **当前口径**（必须等于实测收集数）——例如 `plan/00` 的「当前全量测试 = 330 项」；
2. **历史快照**（该里程碑当时的数字，**必须保持原样**，改了反而篡改历史）——
   M1 171 / M2 230 / M4 287 / M5–M6 307→321，散落在各棒 DoD 与诚实口径尾注里。

所以判据不是"全扫 N 项必须等于 330"（那会把 40 多处历史记录全判红，逼人篡改历史），
而是：**聚合口径（全量 pytest / 全量测试 / 双解释器全量）里的数字，要么等于实测收集数，
要么它所在的段落带有历史限定语**。限定语是**显式词表**（当时 / 本对话实测 / 已退役 / 尾注（M<n> 等），
不是"猜"——没有限定语的当前陈述写错了就会红。

**扫描面自证**（防守门空转）：本文件必须先证明"真的扫到了聚合口径的句子"，
否则有人把措辞改掉（例如把"全量测试"改成"全部测试"）时，正则匹配不到 → 零命中 → 假绿。
"""

import io
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 判定"当前状态"的文档（历史留档 `plan/HANDOFF-M*.md`、`plan/RELEASE-M6.md`、
#: `plan/WRAPUP-M6.md` 整篇都是历史快照，**不在此列**——对它们做"当前值"断言等于逼人篡改历史）。
LIVING_DOCS = (
    "plan/00-README总览.md",
    "plan/06-里程碑.md",
    "plan/07-交付对标.md",
)

#: 聚合口径的措辞（**收窄到"全量"语义**：`tests/test_fetch.py`（38 项）这类单文件计数
#: 不属于聚合口径，混进来会造假红）。
_AGGREGATE_RE = re.compile(r"(?:全量\s*pytest|全量测试|双解释器全量)[^\n]{0,40}?(\d{2,4})\s*项")

#: 历史限定语（**显式词表**，可审计）。命中任一条即视为"历史快照，保留不改"。
#:
#: **词表宽度是这条守门的成败所在**（本文件写成时用 4 条负控实测校准过）：
#: 初版收了「已退役 / 不再 / 旧」——结果 `plan/07` 的当前行
#: 「**M7 现状：99 项绿**（py3.12；3.8 通道已退役）」因为"已退役"被判成历史，
#: **负控 2 静默逃逸**。这三个词说的是"解释器通道退役"，不是"这个数字是历史"。
#: 现在只保留真正声明历史语义的词：
_HISTORICAL_RE = re.compile(r"当时|本对话实测|本棒实测|历史快照|尾注（M\d|M\d 当时")


def _read(rel):
    with io.open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def _aggregate_hits(text):
    """返回 [(数字, 是否带历史限定, 所在行)]，**按行判断**。

    为什么是行而不是段：限定语要贴着数字。段级判断会让"同段里别处写了『当时』"
    去豁免本行的当前值——正是负控 2 的逃逸路径。
    """
    hits = []
    for line in text.splitlines():
        matches = list(_AGGREGATE_RE.finditer(line))
        if not matches:
            continue
        historical = bool(_HISTORICAL_RE.search(line))
        for m in matches:
            hits.append((int(m.group(1)), historical, line.strip()[:100]))
    return hits


def _collected_count():
    """真跑一次 `pytest --collect-only` 取实测收集数（不跑测试体，无递归风险）。"""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "--collect-only"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, "collect-only 失败：\n%s" % out[-2000:]
    m = re.search(r"(\d+) tests? collected", out)
    assert m, "collect-only 输出里没抽到收集数：\n%s" % out[-2000:]
    return int(m.group(1))


def test_scan_face_is_not_empty():
    """**扫描面自证**：三份现行文档里必须真抽到聚合口径的句子。

    没有这一条，下面两条在"措辞被改掉 / 正则失配"时会零命中 → 全部通过 → 假绿。
    实测基线：`plan/00` 5 处、`plan/06` 9 处、`plan/07` 2 处（含带历史限定语的）。
    """
    total_hits = 0
    per_doc = {}
    for rel in LIVING_DOCS:
        assert os.path.isfile(os.path.join(ROOT, rel)), "现行文档缺 %s" % rel
        n = len(_aggregate_hits(_read(rel)))
        per_doc[rel] = n
        total_hits += n
    assert total_hits >= 10, (
        "聚合口径句子只抽到 %d 处（%r）——扫描面可能已失配，守门等于空转" % (total_hits, per_doc))
    assert all(n > 0 for n in per_doc.values()), "有文档零命中：%r" % (per_doc,)


def test_current_counts_match_collected():
    """**主判据**：不带历史限定语的聚合口径数字必须等于实测收集数。

    负控（本文件写成时实测过）：把「当前全量测试 = 330 项」改成 331 → 红；
    README 那句「全量测试 99 项绿」原样搬进 `plan/` → 红（99 ≠ 330 且无限定语）。
    阳性对照：带「（M5）」尾注的 321 → 绿（历史快照，保留不改）。
    """
    actual = _collected_count()
    offenders = []
    for rel in LIVING_DOCS:
        for number, historical, head in _aggregate_hits(_read(rel)):
            if not historical and number != actual:
                offenders.append("%s: %d 项（实测 %d）← %s" % (rel, number, actual, head))
    assert offenders == [], (
        "当前口径的测试数与实测收集数不一致（若确属历史快照，请在段落里写明"
        "「当时 / 本对话实测」等限定语）：\n  " + "\n  ".join(offenders))


def test_authoritative_count_is_stated_once():
    """`plan/00` 必须有一处**无历史限定**的权威口径，且写明等于实测收集数。

    这是"读者该信哪个数字"的单一答案；有它下面那条才知道该对齐什么。
    """
    text = _read("plan/00-README总览.md")
    actual = _collected_count()
    current = [(n, head) for n, historical, head in _aggregate_hits(text) if not historical]
    assert current, "plan/00 没有『当前全量测试 = N 项』这一处权威声明"
    declared = sorted({n for n, _ in current})
    assert declared == [actual], (
        "plan/00 的当前口径声明为 %r，实测收集数 %d" % (declared, actual))


@pytest.mark.parametrize("rel", LIVING_DOCS)
def test_living_docs_mention_the_count_rule(rel):
    """三份现行文档都要指向同一个权威口径，避免读者按各自版本核对。

    只查"有没有指向"，不查措辞细节——措辞部分由上两条的数值判据兜住。
    """
    text = _read(rel)
    assert "plan/00" in text, "%s 未指向 plan/00 的测试数口径" % rel
    has_marker = ("测试数口径" in text) or ("数字口径" in text)
    assert has_marker, "%s 缺『测试数口径 / 数字口径』说明段" % rel
