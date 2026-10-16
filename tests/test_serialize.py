"""序列化单点确定性测试（K3）。

核心判据：**同输入双跑逐字节一致**；且契约参数（`sort_keys` / `ensure_ascii=False` /
LF / 尾换行）真的生效——不是"文档说一套、代码做一套"。
"""

import io
import os

import pytest

from policy_radar import serialize
from policy_radar.serialize import (
    JSON_DUMPS_KWARGS, NEWLINE, dumps_json, read_json, read_text, write_json, write_text,
)

CHINESE_SAMPLE = {
    "z": "政策文件雷达",
    "a": {"文号": "国办发〔2026〕28号", "n": 28},
    "m": ["标题", "摘要"],
}


def test_frozen_kwargs_values():
    """契约参数就是这三个值，改它属"动了会打挂测试"的口径变更。"""
    assert JSON_DUMPS_KWARGS == {"sort_keys": True, "ensure_ascii": False, "indent": 2}
    assert NEWLINE == "\n"


def test_ensure_ascii_false_no_escapes():
    """中文项目必选项：默认 True 会把中文转 \\uXXXX，diff 不可读。"""
    out = dumps_json(CHINESE_SAMPLE)
    assert "\\u" not in out
    assert "政策文件雷达" in out


def test_sort_keys_actually_sorts():
    out = dumps_json(CHINESE_SAMPLE)
    lines = [ln.strip() for ln in out.splitlines()]
    assert lines[1].startswith('"a"')
    assert lines[-2].startswith('"z"') or lines[-1].startswith("}")


def test_trailing_newline():
    out = dumps_json({"x": 1})
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_write_read_roundtrip_json(tmp_path):
    path = os.path.join(str(tmp_path), "out.json")
    write_json(path, CHINESE_SAMPLE)
    assert read_json(path) == CHINESE_SAMPLE


def test_write_json_is_byte_identical_across_runs(tmp_path):
    """同输入双跑逐字节一致（确定性写盘的核心断言）。"""
    p1 = os.path.join(str(tmp_path), "a.json")
    p2 = os.path.join(str(tmp_path), "b.json")
    write_json(p1, CHINESE_SAMPLE)
    write_json(p2, CHINESE_SAMPLE)
    with io.open(p1, "rb") as f1, io.open(p2, "rb") as f2:
        assert f1.read() == f2.read()


def test_write_json_uses_lf_only(tmp_path):
    """Windows 上不得写 CRLF（否则跨平台"再生成位级一致"不成立）。"""
    path = os.path.join(str(tmp_path), "lf.json")
    write_json(path, CHINESE_SAMPLE)
    with io.open(path, "rb") as fh:
        raw = fh.read()
    assert b"\r\n" not in raw
    assert b"\r" not in raw


def test_write_text_normalizes_crlf_and_trailing_newline(tmp_path):
    path = os.path.join(str(tmp_path), "t.md")
    write_text(path, "# 标题\r\n正文\r\n\r\n")
    with io.open(path, "rb") as fh:
        raw = fh.read()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    # 结尾恰好一个换行：输入的多余尾换行被收口（跨工具链逐字节稳定的前提）。
    assert read_text(path) == "# 标题\n正文\n"


def test_write_text_adds_missing_trailing_newline(tmp_path):
    path = os.path.join(str(tmp_path), "t2.md")
    write_text(path, "无尾换行")
    with io.open(path, "rb") as fh:
        assert fh.read().endswith(b"\n")


def test_write_json_creates_parent_dir(tmp_path):
    path = os.path.join(str(tmp_path), "nested", "deep", "x.json")
    write_json(path, {"ok": True})
    assert read_json(path) == {"ok": True}


def test_atomic_write_leaves_no_temp_files(tmp_path):
    """原子写不得残留临时文件。"""
    path = os.path.join(str(tmp_path), "x.json")
    write_json(path, {"a": 1})
    leftovers = [n for n in os.listdir(str(tmp_path)) if n.startswith(".tmp-")]
    assert leftovers == []


def test_read_json_bad_format_raises_value_error(tmp_path):
    """坏格式抛 ValueError（CLI 转 exit 2），不逃逸成 traceback。"""
    path = os.path.join(str(tmp_path), "bad.json")
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    with pytest.raises(ValueError):
        read_json(path)


def test_read_json_missing_file_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        read_json(os.path.join(str(tmp_path), "nope.json"))


def test_read_text_missing_file_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        read_text(os.path.join(str(tmp_path), "nope.md"))


def test_module_has_single_write_surface():
    """写盘单点自证：本模块之外不得出现 json.dump 直写（源码扫描）。

    扫描面 = `src/policy_radar/*.py`；`serialize.py` 自身豁免。
    """
    import glob
    pkg_dir = os.path.dirname(serialize.__file__)
    offenders = []
    for path in glob.glob(os.path.join(pkg_dir, "*.py")):
        if os.path.basename(path) == "serialize.py":
            continue
        with io.open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        if "json.dump(" in src:
            offenders.append(os.path.basename(path))
    assert offenders == [], "写盘未收口到 serialize.py：%r" % offenders
