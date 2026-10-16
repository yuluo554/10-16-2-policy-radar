"""README 指令面守门（skill "测试面 = 安装面 = README 指令面"）。

**判别口诀：我的"README 一致性"守门，是查字符串还是查可执行性？**
子串断言证明不了"用户照抄能跑"——所以本文件断言的是**结构位置**：

1. README 里每条 `policy-radar <command>` / `python -m policy_radar <command>` 的子命令
   必须真在 argparse 的 `build_parser()` 里注册（防"README 写了个不存在的命令"）；
2. README 里出现的 `--flag` 必须真属于它所在的那条命令行（**逐行关联，防张冠李戴**）；
3. README 里引用的仓库内路径参数必须**真实存在**；
4. README 安装行用到的 extras 必须与 pyproject 双向一致；
5. README 必须明示退出码语义；
6. **测试面**：tests/ 真 import 的每个第三方库都能在 README 那条安装命令的 extras 里找到
   （stdlib 用**冻结名单**判定，不用 `sys.stdlib_module_names`——那是 3.10+ 才有，
   3.8 上取到空集会把每个标准库判成第三方 → 全量假红）。
"""

import ast
import io
import os
import re
import sys

import pytest

from policy_radar.cli import NOT_READY_COMMANDS, build_parser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
TESTS_DIR = os.path.join(ROOT, "tests")

#: 冻结的 stdlib 名单（3.8 时代标准库；新增测试 import 名单外的 stdlib 要同步进来）。
#: **不得用 `sys.stdlib_module_names`**（3.10+，3.8 上空集 → 假红）。
STDLIB_FROZEN = frozenset([
    "argparse", "ast", "io", "json", "os", "re", "sys", "tempfile", "subprocess",
    "shutil", "glob", "collections", "datetime", "hashlib", "itertools", "math",
    "pathlib", "textwrap", "types", "typing", "unittest", "urllib", "warnings",
    "contextlib", "csv", "functools", "logging", "random", "string", "time",
    "traceback", "uuid", "errno", "socket", "ssl", "base64", "codecs", "platform",
    "struct", "threading", "unicodedata", "difflib", "enum", "copy", "abc",
    "importlib", "binascii", "gzip", "zipfile", "stat", "operator", "pickle",
])

#: 分发名 -> import 名 别名表（直接比较会造假红，skill 明示）。
DIST_TO_IMPORT = {
    "pytest": "pytest",
    "pyyaml": "yaml",
    "pillow": "PIL",
    "python-dateutil": "dateutil",
    "setuptools": "setuptools",
}


def _read(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def readme():
    assert os.path.isfile(README), "README.md 缺失"
    return _read(README)


@pytest.fixture(scope="module")
def pyproject():
    return _read(PYPROJECT)


# --- 1. README 的子命令必须真存在 -------------------------------------------

def _registered_commands():
    parser = build_parser()
    names = set()
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices:
            names |= set(action.choices)
    return names


def _readme_command_mentions(readme):
    """抽取 README 里的命令行调用（两种形态：裸命令 与 python -m 形态）。"""
    pat = re.compile(r"(?:^|[\s`$])(?:policy-radar|python\s+-m\s+policy_radar)\s+([a-z][a-z0-9-]*)")
    return pat.findall(readme)


def test_readme_mentions_at_least_one_command(readme):
    """扫描面非空自证（防"探针把目标文本切坏"→ 抽到空集 → 永不红）。"""
    mentions = _readme_command_mentions(readme)
    assert mentions, "README 里没抽到任何命令调用，守门等于空转"


def test_readme_commands_all_registered(readme):
    registered = _registered_commands()
    mentioned = set(_readme_command_mentions(readme))
    # `--version` 这类旗标形态会被上面的正则误抽成命令名，按"注册表 + 已知旗标"过滤。
    unknown = {m for m in mentioned if m not in registered and m != "version"}
    assert unknown == set(), "README 提到了未注册的子命令：%r" % sorted(unknown)


def test_readme_covers_every_user_facing_command(readme):
    """反向覆盖：CLI 的每个子命令都应在 README 的命令表里出现。"""
    registered = _registered_commands()
    missing = sorted(c for c in registered if c not in readme)
    assert missing == [], "README 未提及这些子命令：%r" % missing


# --- 2. 旗标必须属于它所在的那条命令行（逐行关联） --------------------------

def _flags_for_command(command):
    parser = build_parser()
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices and command in action.choices:
            sub = action.choices[command]
            flags = set()
            for a in sub._actions:
                flags |= set(a.option_strings)
            return flags
    return set()


def test_readme_flags_belong_to_their_command(readme):
    """**逐行关联**：防"旗标写在错的命令行上"的张冠李戴。"""
    violations = []
    for line in readme.splitlines():
        m = re.search(r"policy-radar\s+([a-z][a-z0-9-]*)", line)
        if not m:
            continue
        command = m.group(1)
        if command not in _registered_commands():
            continue
        allowed = _flags_for_command(command)
        for flag in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", line):
            if flag in ("--help",):
                continue
            if flag not in allowed:
                violations.append((command, flag, line.strip()))
    assert violations == [], "README 旗标与命令不匹配：%r" % violations


# --- 3. README 引用的仓库内路径必须存在 -------------------------------------

def test_readme_internal_paths_exist(readme):
    """抽取 README 里的仓库内相对路径（`plan/...`、`data/...`、`src/...`、`tests/...`），
    逐个断言存在——子串断言证明不了"用户照抄能跑"（skill 头号实录：README 多了一层
    不存在的 `samples/`）。"""
    candidates = set(re.findall(
        r"`((?:plan|data|src|tests|tools|docs)/[A-Za-z0-9_\u4e00-\u9fff./-]+)`", readme))
    missing = sorted(p for p in candidates if not os.path.exists(os.path.join(ROOT, p)))
    assert missing == [], "README 引用了不存在的路径：%r" % missing


def test_readme_paths_scan_surface_not_empty(readme):
    candidates = set(re.findall(
        r"`((?:plan|data|src|tests|tools|docs)/[A-Za-z0-9_\u4e00-\u9fff./-]+)`", readme))
    assert candidates, "README 未抽到任何仓库内路径，路径守门等于空转"


# --- 4. extras 双向一致 -----------------------------------------------------

def _pyproject_extras(pyproject):
    block = re.search(r"\[project\.optional-dependencies\](.*?)(?=\n\[|\Z)",
                      pyproject, re.S)
    assert block, "pyproject 缺 [project.optional-dependencies]"
    extras = {}
    for line in block.group(1).splitlines():
        m = re.match(r"\s*([A-Za-z0-9_-]+)\s*=\s*\[(.*)\]", line)
        if m:
            extras[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))
    return extras


def test_pyproject_has_dev_extra(pyproject):
    extras = _pyproject_extras(pyproject)
    assert "dev" in extras
    assert any("pytest" in d for d in extras["dev"]), extras["dev"]


def test_readme_install_line_uses_declared_extras(readme, pyproject):
    """README 的 `pip install -e ".[...]"` 行里的 extras 必须都在 pyproject 里声明。"""
    declared = set(_pyproject_extras(pyproject))
    used = set()
    for m in re.finditer(r'pip install -e\s+"?\.\[([^\]]+)\]"?', readme):
        used |= {x.strip() for x in m.group(1).split(",") if x.strip()}
    assert used, "README 未给出带 extras 的安装命令"
    unknown = used - declared
    assert unknown == set(), "README 用了未声明的 extras：%r" % sorted(unknown)


def test_readme_install_line_is_the_dev_extra(readme):
    """README 那条安装命令必须含 dev（否则测试期依赖装不上）。"""
    assert re.search(r'pip install -e\s+"?\.\[dev', readme)


# --- 5. 退出码语义明示 ------------------------------------------------------

def test_readme_documents_exit_codes(readme):
    for code in ("0", "1", "2", "3", "4"):
        assert re.search(r"\b%s\b" % code, readme), "README 未写明退出码 %s" % code
    assert "退出码" in readme
    # 骨架期专用语义必须写明"模块落地后退役"
    assert "未就绪" in readme


def test_readme_documents_limits(readme):
    """题面硬要求：⚠️ 局限必须原样披露。"""
    assert "局限" in readme
    assert "mintime" in readme or "日期" in readme
    assert "404" in readme


def test_readme_has_brand_and_quickstart(readme):
    assert "定位宣言" in readme or "定位" in readme
    assert "快速" in readme


# --- 6. 测试面：tests/ 真 import 的第三方库必须在 dev extra 里 ---------------

def _test_imports():
    """AST 从严收集 tests/ 的全部 import（**含函数体内 import**）。"""
    top = set()
    for name in sorted(os.listdir(TESTS_DIR)):
        if not name.endswith(".py"):
            continue
        with io.open(os.path.join(TESTS_DIR, name), "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    top.add(node.module.split(".")[0])
    return top


def test_test_imports_scan_surface_not_empty():
    imports = _test_imports()
    assert imports, "tests/ import 扫描面为空，守门等于空转"


def test_third_party_test_imports_are_declared_in_dev_extra(pyproject):
    """**测试面 = 安装面**：干净 venv 照 README 装完，全量测试必须绿。

    判定落点四分法：冻结名单 stdlib / dev extra / 本包（policy_radar）/ 本地模块（conftest）。
    """
    extras = _pyproject_extras(pyproject)
    dev_import_names = set()
    for dist in extras.get("dev", []):
        pkg = re.split(r"[<>=!~\[]", dist)[0].strip().lower()
        dev_import_names.add(DIST_TO_IMPORT.get(pkg, pkg))

    offenders = []
    for name in sorted(_test_imports()):
        if name in STDLIB_FROZEN:
            continue
        if name in ("policy_radar", "conftest"):
            continue
        if name not in dev_import_names:
            offenders.append(name)
    assert offenders == [], (
        "tests/ import 了未在 dev extra 声明的第三方库（干净环境会 ModuleNotFoundError）：%r"
        % offenders)


def test_policy_radar_package_is_importable_by_tests(pyproject):
    """安装面第四面：我们自己的包必须在 packages.find 的 include 里（否则装完 import 不到）。"""
    block = re.search(r"\[tool\.setuptools\.packages\.find\](.*?)(?=\n\[|\Z)",
                      pyproject, re.S)
    assert block, "pyproject 缺 [tool.setuptools.packages.find]"
    assert "policy_radar" in block.group(1), block.group(1)
    # 判据落在 package-dir 的映射上，不是"文件里出现过这个词"。
    assert re.search(r'package-dir\s*=\s*\{\s*""\s*=\s*"src"\s*\}', pyproject)


# --- 7. 哨兵串排查（skill：桩会静默混过里程碑） -----------------------------

def test_no_sentinel_stubs_in_src():
    """收尾期固定扫一遍：空桩/占位串不得存在于 src/（骨架期靠 exit 3 表达未就绪，
    不落 NotImplementedError 桩）。"""
    pkg_dir = os.path.join(ROOT, "src", "policy_radar")
    offenders = []
    for name in sorted(os.listdir(pkg_dir)):
        if not name.endswith(".py"):
            continue
        src = _read(os.path.join(pkg_dir, name))
        for token in ("NotImplementedError", "TODO: 实现", "placeholder"):
            if token in src:
                offenders.append((name, token))
    assert offenders == [], "src/ 出现哨兵桩：%r" % offenders


def test_ci_workflow_exists_and_sets_utf8():
    """CI 预置（未接远端，待首推验证）：env 必须含 PYTHONUTF8=1（skill 编码三加固之一）。"""
    path = os.path.join(ROOT, ".github", "workflows", "ci.yml")
    assert os.path.isfile(path), "CI workflow 缺失"
    text = _read(path)
    assert "PYTHONUTF8" in text
    assert "pytest" in text
