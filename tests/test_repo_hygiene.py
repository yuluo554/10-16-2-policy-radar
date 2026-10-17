"""仓库卫生守门：`.gitignore` 不得误伤冻结数据（skill 三问之①"入库件在不在"）。

**实测抓出的真缺陷**：`.gitignore` 里未锚定的 `snapshots/` 模式会连 `data/snapshots/`
（真值基准的**冻结 fixtures**）一起忽略 → 那正是"冻结真值库实际不在仓里"的失效形态
（文件在本地存在、`git ls-files` 查不到 → 三问第一问就不过）。

本文件用**文本级判据**（不依赖 git 可执行），因此源码 zip 解压树里也能跑
（skill：入仓工具/守门不硬依赖 git）。
"""

import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GITIGNORE = os.path.join(ROOT, ".gitignore")

#: 必须能被提交的冻结数据目录（相对仓库根）。
FROZEN_DATA_DIRS = ("data/snapshots", "data/truth", "data/config", "data/samples")


def _read(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def test_gitignore_exists():
    assert os.path.isfile(GITIGNORE)


def test_no_unanchored_directory_patterns_shadowing_data():
    """**核心断言**：不得存在未锚定的目录模式（如裸 `snapshots/`）会遮蔽 `data/<同名>`。

    判据：把每条模式与 `data/` 下四个目录名比对——模式的 basename 若等于某个数据目录名
    且模式**未锚定到仓库根**（不以 `/` 开头、不含 `data/` 前缀），即视为遮蔽风险。
    """
    lines = [ln.strip() for ln in _read(GITIGNORE).splitlines()]
    patterns = [ln for ln in lines if ln and not ln.startswith("#")]
    names = {os.path.basename(d) for d in FROZEN_DATA_DIRS}

    offenders = []
    for pat in patterns:
        if pat.startswith("!"):
            continue
        stripped = pat.rstrip("/")
        base = os.path.basename(stripped)
        if base not in names:
            continue
        anchored = stripped.startswith("/") or "/" in stripped
        if not anchored:
            offenders.append(pat)
    assert offenders == [], (
        "存在未锚定的目录模式会遮蔽 data/ 下的冻结目录：%r（应写成 `/xxx/`）" % offenders)


def test_frozen_data_dirs_are_not_ignored_by_explicit_negation():
    """若确有同名模式，必须有 `!data/<name>/` 形式的显式反忽略（双保险）。"""
    text = _read(GITIGNORE)
    unanchored = [ln.strip() for ln in text.splitlines()
                  if ln.strip() and not ln.strip().startswith(("#", "!"))]
    names = {os.path.basename(d) for d in FROZEN_DATA_DIRS}
    shadowed = [p for p in unanchored
                if os.path.basename(p.rstrip("/")) in names
                and not (p.startswith("/") or "/" in p)]
    for pat in shadowed:
        name = os.path.basename(pat.rstrip("/"))
        assert ("!data/%s" % name) in text or ("!data/%s/" % name) in text, pat


def test_runtime_snapshot_dir_still_ignored():
    """反向：运行时快照目录（仓库根 `snapshots/`）必须仍被忽略，别把忽略面一起删掉。"""
    text = _read(GITIGNORE)
    assert re.search(r"^/snapshots/?$", text, re.M), text
    assert re.search(r"^/out/?$", text, re.M), text


def test_data_subdirs_have_readme():
    """四个数据子目录各带 README（说明它是哪个里程碑的产出，防"空目录被忽略"）。"""
    for d in FROZEN_DATA_DIRS:
        assert os.path.isfile(os.path.join(ROOT, d, "README.md")), d


# --- 字节冻结保护（M1：所有走逐字节比对的产物目录都要 -text） ----------------

#: 参与逐字节比对 / sha256 校验的数据目录（相对仓库根）。
#: `data/config/` 也在此列：它的三份规则数据由生成器产出，`--check` 做逐字节比对。
BYTE_FROZEN_DIRS = ("data/samples", "data/snapshots", "data/truth", "data/config")


def test_gitattributes_marks_all_byte_frozen_dirs_as_binary():
    """**实测抓出的缺口**：`data/config/*.json` 由生成器产出且 `--check` 逐字节比对，
    但最初漏了 `-text` → 克隆时 EOL 归一化会改写字节、使位级守门跨平台假红。

    判据：`data/{samples,snapshots,truth,config}/*.json` 每一条都必须在
    `.gitattributes` 里显式标 `-text`（只靠 `* text=auto eol=lf` 不够——
    那是"归一化"而非"冻结"）。
    """
    text = _read(os.path.join(ROOT, ".gitattributes"))
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    missing = []
    for d in BYTE_FROZEN_DIRS:
        pattern = "%s/*.json -text" % d
        if pattern not in lines:
            missing.append(pattern)
    assert missing == [], "以下目录未标 `-text`（克隆后字节可能被改写）：%r" % missing


def test_gitattributes_scan_surface_not_empty():
    """扫描面非空自证（防"探针读到空文件 → 永不红"）。"""
    text = _read(os.path.join(ROOT, ".gitattributes"))
    patterns = [ln.strip() for ln in text.splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    assert len(patterns) >= 4, patterns


# --- 品牌隔离（题面第六节第 6 条：不含任何姊妹项目字样） --------------------

#: 姊妹项目词族（**词面不入库**：本守门是"判定词表"，扩词表是正常维护动作）。
SIBLING_BRAND_TOKENS = (
    "petfood", "labelcheck", "decision-atlas", "bill-reconciler",
    "agent-rework", "crash-loop-rescue", "safety-expense", "e-bike",
    "hws-math", "hws_math", "ghg-workbench", "rcc",
)

#: 扫描面：入库的源码与文档（排除本文件自身——它就是判定词表的载体）。
SCAN_EXTS = (".py", ".md", ".toml", ".yml", ".yaml", ".cfg", ".txt")
SCAN_SKIP_DIRS = (".git", "__pycache__", ".venv", "node_modules")


def _iter_scanned_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SCAN_SKIP_DIRS]
        for name in filenames:
            if not name.endswith(SCAN_EXTS):
                continue
            path = os.path.join(dirpath, name)
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue  # 判定词表自身豁免
            yield path


def test_brand_isolation_no_sibling_tokens():
    """**题面硬要求**：文档与代码中不得出现任何其他姊妹项目名称。

    实测抓出过一处泄漏（plan 文档里点名了一个姊妹项目的代号）→ 改为"方向级描述"。
    """
    offenders = []
    for path in _iter_scanned_files():
        try:
            text = _read(path)
        except (IOError, OSError, UnicodeDecodeError):
            continue
        low = text.lower()
        for token in SIBLING_BRAND_TOKENS:
            if token.lower() in low:
                offenders.append((os.path.relpath(path, ROOT), token))
    assert offenders == [], "品牌隔离违规（出现姊妹项目词面）：%r" % offenders


def test_brand_scan_surface_not_empty():
    """扫描面非空自证（防"探针抽到空集 → 永不红"）。"""
    files = list(_iter_scanned_files())
    assert len(files) >= 10, "扫描面只有 %d 个文件，守门等于空转" % len(files)
    names = {os.path.basename(p) for p in files}
    assert "cli.py" in names and "README.md" in names
