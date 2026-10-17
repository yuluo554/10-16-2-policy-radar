#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真实 API 样本抓取与登记（M1 产出；离线回归的输入源）。

用法（逐页加延时，遵守平台限频礼仪）::

    py -3.8 -X utf8 tools/capture_samples.py --out-dir data/samples
    py -3.8 -X utf8 tools/capture_samples.py --out-dir data/samples --check

设计纪律：
- **只用 stdlib**（`urllib.request`），与本项目"运行时零第三方依赖"一致；
- 逐请求固定延时（默认 3s），不做并发；
- 单请求超时 20s；
- 落盘**原始响应字节**（不重新序列化）——样本的价值在于"那一刻服务器真返回了什么"，
  重新 `json.dumps` 会把字节冻结纪律变成"我们的序列化器输出了什么"；
- 写盘经 `serialize.py` 的原子写路径的字节通道（`_atomic_write_bytes`），保持"写盘单点"；
- `--check` 只重算 sha256 与登记值比对（**不打真站点**，用于克隆/检出后验证字节未变）。
"""

import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from policy_radar.serialize import read_json, write_bytes, write_json  # noqa: E402

#: 抓取目标：两个公开频道（决策 D1）。URL 与 README 的示例逐字一致。
API_BASE = "https://sousuo.www.gov.cn/search-gov/data"

#: 样本清单：(文件名, 频道参数, 页, 每页条数)。
#: n=5 是台账/README 逐字登记的最小样本；n=30 是**观测池**——供 `gen_snapshot_pairs.py`
#: 取真实条目合成快照对（合成纪律：不编造不存在的机关代字与数值，故必须取自实采）。
SAMPLE_SPECS = (
    ("gwy-p1-n5.json", "zhengcelibrary_gwy", 1, 5),
    ("bm-p1-n5.json", "zhengcelibrary_bm", 1, 5),
    ("gwy-p1-n30.json", "zhengcelibrary_gwy", 1, 30),
    ("bm-p1-n30.json", "zhengcelibrary_bm", 1, 30),
)

#: 抓取登记表文件名（与样本同目录）。
REGISTRY_NAME = "manifest.json"

#: 默认逐页延时（秒）；平台礼仪，见 README「平台礼仪」。
DEFAULT_DELAY = 3.0
DEFAULT_TIMEOUT = 20


def build_url(channel_param, page, n):
    """按实测通过的形态拼 URL（与 README/台账示例逐字一致）。"""
    return "%s?t=%s&q=&p=%d&n=%d&sort=pubtime&sortType=1" % (
        API_BASE, channel_param, page, n)


def fetch_bytes(url, timeout=DEFAULT_TIMEOUT, retries=2):
    """抓取原始响应字节；返回 (bytes, http_status)。

    失败重试（指数退避 1s/2s）；最终失败抛 `ExternalError`（调用方转 exit 4）。
    """
    from policy_radar.errors import ExternalError

    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            # 明确 UA 便于对方识别；只发只读 GET（边界 4）。
            "User-Agent": "policy-radar/0.1 (+local CLI; metadata only)",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                body = resp.read()
                if status != 200:
                    raise ExternalError("API 返回 HTTP %s（%s）" % (status, url))
                return body, status
        except ExternalError:
            raise
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise ExternalError("抓取失败（%d 次尝试）：%s（%s）" % (retries + 1, last, url))


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def validate_payload(raw, expect_channel):
    """结构性校验：只认 `searchVO.listVO`（实测取数路径，决策 D13）。

    返回 (totalCount, entry_count)。结构异常即抛 ValueError（由调用方转 exit 4）。
    """
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("响应不是合法 UTF-8 JSON：%s" % exc)
    if not isinstance(payload, dict):
        raise ValueError("响应顶层不是 JSON 对象")
    sv = payload.get("searchVO")
    if not isinstance(sv, dict):
        raise ValueError("响应缺少 searchVO 对象（取数路径应为 searchVO.listVO）")
    lst = sv.get("listVO")
    if not isinstance(lst, list):
        raise ValueError("响应缺少 searchVO.listVO 列表")
    # 顶层 `data` 实测为 null —— 断言它，防未来结构漂移被静默接受。
    if payload.get("data", None) is not None:
        raise ValueError("响应顶层 data 非 null（实测为 null，取数路径可能已变）")
    if not lst:
        raise ValueError("listVO 为空列表")
    return sv.get("totalCount"), len(lst)


def capture(out_dir, delay=DEFAULT_DELAY, timeout=DEFAULT_TIMEOUT):
    """真跑一次抓取，落样本 + 登记表。返回登记表 dict。"""
    entries = []
    for idx, (fname, param, page, n) in enumerate(SAMPLE_SPECS):
        if idx and delay > 0:
            time.sleep(delay)  # 逐页/逐频道延时（平台礼仪）
        url = build_url(param, page, n)
        raw, status = fetch_bytes(url, timeout=timeout)
        total, count = validate_payload(raw, param)
        path = os.path.join(out_dir, fname)
        # 原始字节落盘（不重新序列化）：样本 = 服务器真返回的字节。
        write_bytes(path, raw)
        entries.append({
            "file": fname,
            "channel_param": param,
            "page": page,
            "n": n,
            "url": url,
            "http_status": status,
            "captured_date": time.strftime("%Y-%m-%d", time.localtime()),
            "bytes": len(raw),
            "sha256": sha256_of(raw),
            "totalCount": total,
            "entries_in_sample": count,
        })
        sys.stdout.write("  [OK] %s  HTTP=%s bytes=%d totalCount=%s entries=%d\n"
                         % (fname, status, len(raw), total, count))

    registry = {
        "note": "真实 API 响应样本登记（M1）。样本为原始响应字节，逐份 sha256 供克隆后比对。",
        "source": API_BASE,
        "samples": entries,
    }
    write_json(os.path.join(out_dir, REGISTRY_NAME), registry)
    return registry


def check(out_dir):
    """只比对冻结样本的 sha256 与登记值（不打真站点）。返回 0/1。"""
    registry_path = os.path.join(out_dir, REGISTRY_NAME)
    if not os.path.isfile(registry_path):
        sys.stderr.write("登记表缺失：%s\n" % registry_path)
        return 1
    registry = read_json(registry_path)
    bad = []
    for entry in registry.get("samples", []):
        path = os.path.join(out_dir, entry["file"])
        if not os.path.isfile(path):
            bad.append((entry["file"], "缺失"))
            continue
        with io.open(path, "rb") as fh:
            actual = sha256_of(fh.read())
        if actual != entry["sha256"]:
            bad.append((entry["file"], "sha256 失配：登记 %s 实际 %s"
                        % (entry["sha256"][:12], actual[:12])))
    if bad:
        for name, why in bad:
            sys.stderr.write("  [FAIL] %s  %s\n" % (name, why))
        return 1
    sys.stdout.write("  [OK] %d 份样本 sha256 与登记值一致\n"
                     % len(registry.get("samples", [])))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="真实 API 样本抓取与登记（M1）")
    parser.add_argument("--out-dir", default="data/samples", help="样本目录")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help="逐请求延时（秒），默认 3.0")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--check", action="store_true",
                        help="只校验冻结样本 sha256（不打真站点）")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.out_dir):
        sys.stderr.write("输出目录不存在：%s\n" % args.out_dir)
        return 2

    try:
        if args.check:
            return check(args.out_dir)
        registry = capture(args.out_dir, delay=args.delay, timeout=args.timeout)
    except ValueError as exc:
        sys.stderr.write("样本抓取失败（结构异常）：%s\n" % exc)
        return 4
    except Exception as exc:  # noqa: BLE001 - 领域异常已在 fetch_bytes 内归一
        from policy_radar.errors import ExternalError
        if isinstance(exc, ExternalError):
            sys.stderr.write("样本抓取失败（外部依赖）：%s\n" % exc)
            return 4
        raise

    sys.stdout.write("已落 %d 份样本 + 登记表 %s\n"
                     % (len(registry["samples"]), os.path.join(args.out_dir, REGISTRY_NAME)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
