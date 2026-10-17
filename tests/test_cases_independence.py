"""参照实现（oracle）独立性守门（M1 DoD #3）。

**核心纪律**：真值的期望必须**独立于生产实现**可复算。

判别口诀：**"把生产实现的判定逻辑注释掉，真值还能算出来吗？"**

本文件用**源码扫描**断言：生产模块（`snapshot.py` / `parse.py` / `subscribe.py`，
M3/M4 落地）**不得 import `cases`**——否则"参照实现"与"生产实现"会变成同一份代码，
真值就成了"自己验自己"（两边一起错时全绿）。

同时反向断言：**生成器与守门测试必须 import `cases`**（否则参照实现没有真调用方，
等于写了一份没人用的代码）。
"""

import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "policy_radar")
TOOLS = os.path.join(ROOT, "tools")
TESTS = os.path.join(ROOT, "tests")

#: 生产模块（判定逻辑的落点）。这些模块**不得** import `cases`。
#: 注意：`verify.py` **可以** import（它就是真值的审计调用方），故不在本表。
PRODUCTION_MODULES = ("snapshot.py", "parse.py", "subscribe.py")

#: 必须 import `cases` 的文件（参照实现要有真调用方）。
MUST_IMPORT_CASES = (
    os.path.join(TOOLS, "gen_snapshot_pairs.py"),
    os.path.join(TOOLS, "gen_pcode_cases.py"),
    os.path.join(TOOLS, "gen_subscribe_cases.py"),
    os.path.join(SRC, "verify.py"),
    os.path.join(TESTS, "test_truth_gate.py"),
)


def _read(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def test_cases_module_exists():
    assert os.path.isfile(os.path.join(SRC, "cases.py")), "参照实现模块缺失"


def test_cases_module_exposes_all_three_oracles():
    """三个参照实现 + 三个对账语义必须齐备（单一实现源）。"""
    src = _read(os.path.join(SRC, "cases.py"))
    for func in ("def naive_diff", "def naive_parse_pcode", "def naive_match",
                 "def compare_diff", "def compare_pcode", "def compare_subscribe",
                 "def find_observed_fields", "def assert_no_observed_fields"):
        assert func in src, "cases.py 缺 %s" % func


def test_production_modules_do_not_import_cases():
    """**核心断言**：生产模块不得 import 参照实现。

    判据：源码里出现 `from .cases import` / `import cases` / `from policy_radar.cases`
    即视为同源（真值会跟着实现一起错）。
    """
    offenders = []
    for name in PRODUCTION_MODULES:
        path = os.path.join(SRC, name)
        if not os.path.isfile(path):
            continue  # 模块未落地（M3/M4 才建），跳过
        src = _read(path)
        if re.search(r"from\s+\.?cases\s+import|import\s+cases\b|policy_radar\.cases", src):
            offenders.append(name)
    assert offenders == [], "生产模块 import 了参照实现（同源，真值不再独立）：%r" % offenders


def test_must_import_files_actually_import_cases():
    """反向：参照实现必须有真调用方（不是"写了一份没人用的代码"）。"""
    offenders = []
    for path in MUST_IMPORT_CASES:
        assert os.path.isfile(path), "文件缺失：%s" % path
        src = _read(path)
        if not re.search(r"from\s+\.?cases\s+import|from\s+policy_radar\.cases\s+import"
                         r"|import\s+cases\b", src):
            offenders.append(os.path.relpath(path, ROOT))
    assert offenders == [], "以下文件未 import 参照实现：%r" % offenders


def test_cases_oracle_uses_different_approach_than_regex_heavy_production():
    """oracle 的文号解析**不得用正则**（与生产实现走不同代码路径的前提）。

    判据：`naive_parse_pcode` 函数体内不得出现 `re.` 调用（除 `_digits_after`
    里用于去空白的 `re.sub` —— 那一步是"去空白"而非"识别形态"，故允许，
    但函数体本身必须靠 `str.find` + 切片定位括号）。
    """
    src = _read(os.path.join(SRC, "cases.py"))
    body = src[src.index("def naive_parse_pcode"):src.index("def _is_year")]
    assert "str.find" in body or ".find(" in body, "oracle 未用 str.find 定位括号"
    # 不得用正则匹配括号形态（`re.findall` / `re.match` / `re.search` 一律不允许）。
    for pattern in ("re.findall", "re.match", "re.search", "re.compile"):
        assert pattern not in body, "oracle 用了 %s 识别形态（与生产实现同路径）" % pattern


def test_cases_module_is_importable_and_oracles_work():
    """参照实现必须真能跑（不是空壳）。"""
    from policy_radar import cases

    # diff oracle。
    a = [{"id": "1", "pcode": "国办发〔2026〕28号"}, {"id": "2", "pcode": ""}]
    b = [{"id": "1", "pcode": "国办发〔2026〕28号"},   # id 命中 -> 重复
         {"id": "3", "pcode": "国办发〔2026〕28号"},   # pcode 命中 -> 重复
         {"id": "4", "pcode": ""}]                    # 都不中 -> 新增
    new_ids, dup_ids, matched_by = cases.naive_diff(a, b)
    assert new_ids == ["4"]
    assert dup_ids == ["1", "3"]
    assert matched_by == {"1": "id", "3": "pcode"}

    # pcode oracle：反向样例必须真"未解析"。
    assert cases.naive_parse_pcode("国令第847号")["year"] == cases.UNPARSED
    assert cases.naive_parse_pcode("")["status"] == cases.STATUS_UNPARSED
    assert cases.naive_parse_pcode("工信部联规﹝2026﹞210号")["year"] == "2026"
    assert cases.naive_parse_pcode("农农发〔2026〕9 号")["serial"] == "9"


def test_compare_functions_are_falsifiable():
    """对账函数必须真能报差异（防"恒 True 对账"）。"""
    from policy_radar import cases

    # compare_sets：多/少都要报。
    result = cases.compare_sets(["a", "b"], ["a"])
    assert not result["ok"] and result["missing"] == ["b"]
    result = cases.compare_sets(["a"], ["a", "c"])
    assert not result["ok"] and result["extra"] == ["c"]
    assert cases.compare_sets(["a"], ["a"])["ok"]

    # compare_diff：matched_by 判错也算差异。
    result = cases.compare_diff(
        {"new_ids": [], "dup_ids": ["x"], "matched_by": {"x": "id"}},
        {"new_ids": [], "dup_ids": ["x"], "matched_by": {"x": "pcode"}})
    assert not result["ok"]
    assert result["matched_by_mismatch"] == [
        {"item_id": "x", "expected": "pcode", "observed": "id"}]

    # compare_pcode：字段级差异必须点名。
    result = cases.compare_pcode(
        {"国令第847号": {"agency_code": "国令", "year": "2026", "serial": "847",
                       "status": "parsed"}},
        {"国令第847号": {"agency_code": "国令", "year": cases.UNPARSED,
                       "serial": "847", "status": "partial"}})
    assert not result["ok"]
    assert result["mismatches"][0]["fields"]["year"]["expected"] == cases.UNPARSED


def test_scan_surface_not_empty():
    """扫描面非空自证（防"探针扫到空集 → 永不红"）。"""
    py_files = [n for n in os.listdir(SRC) if n.endswith(".py")]
    assert len(py_files) >= 6, py_files
    assert os.path.isfile(os.path.join(SRC, "cases.py"))
