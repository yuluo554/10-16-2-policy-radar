"""确定性写盘单点（K3）。

**所有产物**（快照、新增清单、日报、真值台账、基准产物）一律经本模块写盘，
不在各模块各写各的 `open()+json.dump()`。

判别口诀：**"换一个子命令，写盘形态会变吗？"** 会变 = 迟早出现"两个产物一个带 BOM
一个不带""一个 sort_keys 一个不排"的漂移。

冻结的序列化契约（K3，改它属"动了会打挂测试"的口径变更）：
- JSON：`json.dumps(sort_keys=True, ensure_ascii=False, indent=2)`；
- `ensure_ascii=False` 是中文项目的必选项（默认 True 会把中文转 `\\uXXXX`，diff 不可读）；
- 文本行尾一律 LF（`newline="\\n"`，注意 3.8 没有 `Path.write_text(newline=)` 参数）；
- 文件结尾固定一个换行；
- 原子写：先写临时文件再 rename，防中断留下半个产物。
"""

import io
import json
import os
import tempfile

#: 冻结契约（供测试与文档引用，单一来源）。
JSON_DUMPS_KWARGS = {"sort_keys": True, "ensure_ascii": False, "indent": 2}
NEWLINE = "\n"


def dumps_json(obj):
    """按冻结参数序列化为 str（带结尾换行）。"""
    return json.dumps(obj, **JSON_DUMPS_KWARGS) + NEWLINE


def _atomic_write_bytes(path, data):
    """原子写字节：临时文件（同目录）-> fsync -> rename。"""
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory or None)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, obj):
    """原子写 JSON 产物（冻结参数）。"""
    _atomic_write_bytes(path, dumps_json(obj).encode("utf-8"))


def write_text(path, text):
    """原子写文本产物；行尾归一为 LF，且**结尾恰好一个换行**。

    `rstrip("\\n")` 而非"只在缺失时补"——否则 `"...\\n\\n"` 会留两个尾换行，
    破坏"同输入双跑逐字节一致"在跨工具链时的稳定性。
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + NEWLINE
    _atomic_write_bytes(path, normalized.encode("utf-8"))


def read_json(path):
    """读 JSON 产物；坏格式抛 ValueError（由 CLI 转 exit 2，不逃逸成 traceback）。"""
    try:
        with io.open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as exc:  # json.JSONDecodeError 是 ValueError 子类
        raise ValueError("JSON 格式错误：%s（%s）" % (path, exc))
    except (IOError, OSError) as exc:
        raise ValueError("无法读取文件：%s（%s）" % (path, exc))


def read_text(path):
    """读文本产物（行尾归一为 LF）。"""
    try:
        with io.open(path, "r", encoding="utf-8") as fh:
            return fh.read().replace("\r\n", "\n").replace("\r", "\n")
    except (IOError, OSError) as exc:
        raise ValueError("无法读取文件：%s（%s）" % (path, exc))
