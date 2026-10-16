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
