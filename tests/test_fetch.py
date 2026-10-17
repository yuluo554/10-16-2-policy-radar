"""双源抓取机制测试（M2）：限频 / 超时重试 / 抓取自证 / 失败隔离 / 原子写 / 退出码。

**全部离线**：网络经 `get(url, timeout)` 参数注入（`ApiStub` 按 URL 的 `(t, p, n)`
回放**冻结的真实响应字节**），时钟与 sleep 同样注入——真站点不可复现，也不该被测试打。

判据分布（`plan/04-模块详设.md` 模块 1 的确定性纪律逐条对应）：

| 纪律 | 本文件测试 |
|---|---|
| 取数路径 `searchVO.listVO` | `test_structure_anomaly_is_a_hard_failure` |
| 限频（逐请求延时、串行） | `test_pacer_*` / `test_two_channels_are_serial_and_delayed` |
| 超时重试（指数退避） | `test_retry_*` |
| 抓取自证（对账） | `test_reconciliation_mismatch_*` / `test_total_count_*` |
| 失败隔离 vs 硬失败 | `test_transport_failure_is_isolated_*` / `test_structure_*` |
| 不拼 URL、不发正文请求 | `test_only_api_endpoint_is_requested` |
| 时间戳只进元信息 | `test_timestamp_is_meta_only` |

「真实抓取产出与留档样本 schema 逐字段一致」的**离线回归**放在
`tests/test_samples_regression.py`（第六节），那里已有样本加载通路。
"""

import io
import json
import os
import re
import sys
import urllib.error

import pytest

from policy_radar import errors
from policy_radar import fetch as fetch_mod
from policy_radar.cli import main_guarded
from policy_radar.fetch import (
    API_BASE, ChannelUnavailable, DEFAULT_CHANNELS, ExternalError, Pacer,
    UsageError, build_output, build_url, fetch_all, fetch_channel,
    reconciliation_lines, resolve_channels,
)
from policy_radar.model import FORBIDDEN_SNAPSHOT_FIELDS, SCHEMA_FIELDS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "data", "samples")

#: 冻结样本（真实响应字节）与它对应的频道参数。
FROZEN = {
    ("zhengcelibrary_gwy", 1, 5): "gwy-p1-n5.json",
    ("zhengcelibrary_bm", 1, 5): "bm-p1-n5.json",
    ("zhengcelibrary_gwy", 1, 30): "gwy-p1-n30.json",
    ("zhengcelibrary_bm", 1, 30): "bm-p1-n30.json",
}
PARAM = {"gwy": "zhengcelibrary_gwy", "bm": "zhengcelibrary_bm"}

FIXED_CLOCK = "2026-10-17T00:00:00"


# --- 测试替身 ---------------------------------------------------------------

def sample_bytes(name):
    with io.open(os.path.join(SAMPLES, name), "rb") as fh:
        return fh.read()


def sample_payload(name):
    return json.loads(sample_bytes(name).decode("utf-8"))


def _query(url):
    query = url.split("?", 1)[1]
    return dict(part.split("=", 1) for part in query.split("&") if "=" in part)


class ApiStub(object):
    """假传输层：按 URL 的 `(t, p, n)` 分发。

    路由值可以是 ①`(status, bytes)`（直接回原始字节）②`(status, payload_dict)`
    ③异常实例（抛出，用于模拟网络失败）。**未注册的请求直接 AssertionError**，
    免得"发了个计划外请求"被静默放过。
    """

    def __init__(self, routes, default=None):
        self.routes = dict(routes)
        self.default = default
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append(url)
        query = _query(url)
        key = (query["t"], int(query["p"]), int(query["n"]))
        if key in self.routes:
            response = self.routes[key]
        elif self.default is not None:
            response = self.default
        else:
            raise AssertionError("传输层收到计划外请求：%s" % url)
        if isinstance(response, BaseException):
            raise response
        status, payload = response
        if isinstance(payload, bytes):
            return status, payload
        return status, json.dumps(payload, ensure_ascii=False).encode("utf-8")

    @property
    def requested_urls(self):
        return list(self.calls)


class SleepRecorder(object):
    """记录延时而不真睡（测试不该等 1.5s × N）。"""

    def __init__(self):
        self.slept = []

    def __call__(self, seconds):
        self.slept.append(seconds)


def frozen_route(source, n=5):
    """冻结样本路由：`(status=200, 原始字节)`。"""
    return (200, sample_bytes(FROZEN[(PARAM[source], 1, n)]))


def derived_payload(source, entries, total, page_size):
    """用冻结样本改出多页响应（改的只有 `listVO` / `totalCount` / `pageSize`）。

    这是**测试替身**（模拟一个分页服务器），不是数据产物：条目本身仍是样本里的
    真实条目，字节与字段都没编造。
    """
    payload = sample_payload(FROZEN[(PARAM[source], 1, 30)])
    sv = payload["searchVO"]
    sv["listVO"] = entries
    sv["totalCount"] = total
    sv["pageSize"] = page_size
    return payload


def entries_of(source, n=30):
    return sample_payload(FROZEN[(PARAM[source], 1, n)])["searchVO"]["listVO"]


def unreachable():
    return urllib.error.URLError("模拟：网络不可达")


# --- 1. 请求形态（不拼正文 URL、限频结构） ---------------------------------

def test_build_url_matches_the_frozen_registry():
    """请求 URL 形态必须与 `data/samples/manifest.json` 登记的那条**逐字一致**。

    不硬编码 URL 字符串（"不写漂移硬数字"纪律）：拿登记表里的真实抓取 URL 比对。
    """
    registry = json.loads(io.open(os.path.join(SAMPLES, "manifest.json"),
                                  "r", encoding="utf-8").read())
    by_file = dict((e["file"], e["url"]) for e in registry["samples"])
    assert build_url("gwy", 1, 5) == by_file["gwy-p1-n5.json"]
    assert build_url("bm", 1, 30) == by_file["bm-p1-n30.json"]


def test_only_api_endpoint_is_requested():
    """决策 D2：抓取目标只认 API 端点，**不拼正文链接**、不发正文请求。"""
    stub = ApiStub({(PARAM["gwy"], 1, 5): frozen_route("gwy")})
    items, _meta = fetch_all(["gwy"], pages=1, n=5, delay=0,
                             get=stub, sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    assert stub.requested_urls == [build_url("gwy", 1, 5)]
    assert all(url.startswith(API_BASE + "?") for url in stub.requested_urls)
    item_urls = set(it.url for it in items)
    assert item_urls, "样本里应有原文链接（用于反向断言）"
    assert not (item_urls & set(stub.requested_urls)), "不得请求条目里的 url 字段"


def test_two_channels_are_serial_and_delayed():
    """两频道同进程**串行**，且请求之间恒为 `delay` 间隔（含跨频道边界）。"""
    stub = ApiStub({(PARAM["gwy"], 1, 5): frozen_route("gwy"),
                    (PARAM["bm"], 1, 5): frozen_route("bm")})
    recorder = SleepRecorder()
    items, meta = fetch_all(["gwy", "bm"], pages=1, n=5, delay=1.5,
                            get=stub, sleep=recorder, now=lambda: FIXED_CLOCK)
    assert stub.requested_urls == [build_url("gwy", 1, 5), build_url("bm", 1, 5)]
    assert recorder.slept == [1.5], "两次请求之间恰好延时一次 delay"
    assert [m["channel"] for m in meta] == ["gwy", "bm"]
    assert len(items) == 10


def test_pacer_first_request_has_no_delay():
    recorder = SleepRecorder()
    pacer = Pacer(1.5, recorder)
    pacer.wait()
    assert recorder.slept == []
    pacer.wait()
    pacer.wait()
    assert recorder.slept == [1.5, 1.5]


def test_pacer_zero_delay_never_sleeps():
    recorder = SleepRecorder()
    pacer = Pacer(0, recorder)
    for _ in range(3):
        pacer.wait()
    assert recorder.slept == []


def test_multi_page_stops_when_declared_total_is_reached():
    """已取满声明总数 -> 不再发多余请求（第 3 页不该被请求）。"""
    entries = entries_of("gwy")
    stub = ApiStub({
        (PARAM["gwy"], 1, 5): (200, derived_payload("gwy", entries[0:5], 10, 5)),
        (PARAM["gwy"], 2, 5): (200, derived_payload("gwy", entries[5:10], 10, 5)),
    })
    items, meta = fetch_all(["gwy"], pages=3, n=5, delay=0, get=stub,
                            sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    assert len(stub.requested_urls) == 2, stub.requested_urls
    assert len(items) == 10
    assert meta[0]["returned"] == 10 and meta[0]["kept"] == 10
    assert meta[0]["declared_total"] == 10
    assert [d["page"] for d in meta[0]["page_details"]] == [1, 2]


def test_channel_meta_records_url_status_and_declared_total():
    """元信息必须逐页记 `url` / `http_status` / `declared_total`（DoD 抓取留档要求）。"""
    payload = sample_payload(FROZEN[(PARAM["gwy"], 1, 5)])
    declared = payload["searchVO"]["totalCount"]
    stub = ApiStub({(PARAM["gwy"], 1, 5): frozen_route("gwy")})
    _items, meta = fetch_all(["gwy"], pages=1, n=5, delay=0, get=stub,
                             sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    detail = meta[0]["page_details"][0]
    assert detail["url"] == build_url("gwy", 1, 5)
    assert detail["http_status"] == 200
    assert detail["declared_total"] == declared
    assert meta[0]["captured_at"] == FIXED_CLOCK


def test_unknown_channel_is_usage_error():
    with pytest.raises(UsageError):
        fetch_all(["nope"], get=ApiStub({}), sleep=SleepRecorder())


def test_resolve_channels_defaults_to_both_and_dedupes():
    assert resolve_channels(None) == list(DEFAULT_CHANNELS)
    assert resolve_channels([]) == list(DEFAULT_CHANNELS)
    assert resolve_channels(["gwy", "gwy"]) == ["gwy"], "重复频道不得抓两遍"


def test_cli_dedupes_repeated_channel(tmp_path):
    stub = ApiStub({(PARAM["gwy"], 1, 5): frozen_route("gwy")})
    out = os.path.join(str(tmp_path), "dup.json")
    code = _run_cli(stub, ["--channel", "gwy", "--channel", "gwy",
                           "--pages", "1", "--n", "5", "--delay", "0", "--out", out])
    assert code == errors.EXIT_OK
    payload = json.loads(io.open(out, "r", encoding="utf-8").read())
    assert len(payload["channels"]) == 1


# --- 2. 超时重试 ------------------------------------------------------------

def test_retry_then_success_uses_exponential_backoff():
    """第 1 次连接失败、第 2 次成功：退避 2**0 = 1s，只重试不放弃。"""
    attempts = {"n": 0}

    def flaky(url, timeout):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise unreachable()
        return 200, sample_bytes(FROZEN[(PARAM["gwy"], 1, 5)])

    recorder = SleepRecorder()
    items, meta = fetch_all(["gwy"], pages=1, n=5, delay=0, get=flaky,
                            sleep=recorder, now=lambda: FIXED_CLOCK)
    assert len(items) == 5
    assert attempts["n"] == 2
    assert recorder.slept == [1], "指数退避第一次 = 2**0"
    assert meta[0]["status"] == "ok"


def test_retry_exhausted_attempts_are_retries_plus_one():
    """重试 2 次 = 最多 3 次尝试，退避序列 1s/2s，随后抛 `ChannelUnavailable`（可隔离）。

    单频道断言用 `fetch_channel`（`fetch_all` 会把这一类失败**隔离**掉，看不到异常）。
    """
    attempts = {"n": 0}

    def always_fail(url, timeout):
        attempts["n"] += 1
        raise unreachable()

    recorder = SleepRecorder()
    with pytest.raises(ChannelUnavailable) as excinfo:
        fetch_channel("gwy", pages=1, n=5, pacer=Pacer(0, recorder),
                      get=always_fail, now=lambda: FIXED_CLOCK)
    assert attempts["n"] == fetch_mod.DEFAULT_RETRIES + 1 == 3
    assert recorder.slept == [1, 2], "指数退避序列 2**0 / 2**1"
    assert "3 次尝试" in str(excinfo.value)


def test_fetch_all_isolates_the_retry_exhausted_channel():
    """同一失败经 `fetch_all` 必须变成 `degraded`（可隔离），而不是抛出去。"""

    def always_fail(url, timeout):
        raise unreachable()

    items, meta = fetch_all(["gwy"], pages=1, n=5, delay=0, get=always_fail,
                            sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    assert items == []
    assert meta[0]["status"] == "degraded"
    assert meta[0]["returned"] == 0 and meta[0]["kept"] == 0
    assert meta[0]["declared_total"] is None
    assert "3 次尝试" in meta[0]["error"]


def test_retryable_5xx_is_retried():
    state = {"n": 0}

    def flaky(url, timeout):
        state["n"] += 1
        if state["n"] == 1:
            return 503, b""
        return 200, sample_bytes(FROZEN[(PARAM["gwy"], 1, 5)])

    items, _meta = fetch_all(["gwy"], pages=1, n=5, delay=0, get=flaky,
                             sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    assert len(items) == 5 and state["n"] == 2


def test_non_retryable_4xx_fails_immediately():
    """404 是"端点或契约变了"，重试只是浪费对方资源 -> 一次即失败。"""
    attempts = {"n": 0}

    def not_found(url, timeout):
        attempts["n"] += 1
        return 404, b"<html>not found</html>"

    with pytest.raises(ExternalError) as excinfo:
        fetch_all(["gwy"], pages=1, n=5, delay=0, get=not_found,
                  sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    assert attempts["n"] == 1
    assert not isinstance(excinfo.value, ChannelUnavailable), "404 属硬失败，不可降级"


# --- 3. 抓取自证（totalCount 对账） -----------------------------------------

def test_reconciliation_line_format_matches_dod():
    """DoD 硬要求：对账行形如 `请求 N 条 / 声明 totalCount M / 实际 K`。"""
    lines = reconciliation_lines([
        {"channel": "gwy", "requested": 20, "declared_total": 6222, "returned": 20,
         "kept": 20, "dropped": 0, "status": "ok", "error": ""},
    ])
    assert re.search(r"请求 20 条 / 声明 totalCount 6222 / 实际 20 条", lines[0])
    assert "合计" in lines[1]


def test_reconciliation_line_says_unknown_for_degraded_channel():
    """连不上时**确实不知道**对方总数 -> 写"未知"，不拿 0 冒充。"""
    lines = reconciliation_lines([
        {"channel": "bm", "requested": 20, "declared_total": None, "returned": 0,
         "kept": 0, "dropped": 0, "status": "degraded", "error": "连不上"},
    ])
    assert "声明 totalCount 未知 / 实际 0 条" in lines[0]
    assert "[degraded]" in lines[0]


def test_mismatch_between_declared_and_actual_is_a_hard_failure():
    """自证不符 -> 硬失败（exit 4 通路），错误里必须同时出现**声明与实际两数**。"""
    entries = entries_of("gwy")
    stub = ApiStub({
        (PARAM["gwy"], 1, 5): (200, derived_payload("gwy", entries[0:5], 10, 5)),
        # 第 2 页声明还有 5 条，却只回 4 条 —— 接口"少给"了
        (PARAM["gwy"], 2, 5): (200, derived_payload("gwy", entries[5:9], 10, 5)),
    })
    with pytest.raises(ExternalError) as excinfo:
        fetch_all(["gwy"], pages=2, n=5, delay=0, get=stub,
                  sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    message = str(excinfo.value)
    assert "抓取自证不符" in message
    assert "声明 totalCount 10" in message
    assert "实际 4 条" in message
    assert not isinstance(excinfo.value, ChannelUnavailable), "自证不符是硬失败，不可降级"


def test_declared_smaller_than_request_is_honored():
    """`totalCount < 请求条数` 时，期望值取 `min(n, total - 已取)`——不是硬要 n 条。"""
    entries = entries_of("gwy")
    stub = ApiStub({
        (PARAM["gwy"], 1, 5): (200, derived_payload("gwy", entries[0:3], 3, 5)),
    })
    items, meta = fetch_all(["gwy"], pages=1, n=5, delay=0, get=stub,
                            sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    assert len(items) == 3
    assert meta[0]["requested"] == 5 and meta[0]["returned"] == 3
    assert "请求 5 条 / 声明 totalCount 3 / 实际 3 条" in reconciliation_lines(meta)[0]


def test_missing_total_count_is_a_hard_failure():
    """`totalCount` 是自证的唯一依据：缺了就没有对账基准 -> 硬失败，不猜。"""
    payload = sample_payload(FROZEN[(PARAM["gwy"], 1, 5)])
    del payload["searchVO"]["totalCount"]
    stub = ApiStub({(PARAM["gwy"], 1, 5): (200, payload)})
    with pytest.raises(ExternalError) as excinfo:
        fetch_all(["gwy"], pages=1, n=5, delay=0, get=stub,
                  sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    assert "totalCount" in str(excinfo.value)


# --- 4. 结构异常与字段合规（硬失败） ---------------------------------------

def test_structure_anomaly_is_a_hard_failure():
    """取数路径漂移（没有 `searchVO.listVO`）必须硬失败，不得静默按最宽松规则解析。"""
    stub = ApiStub({(PARAM["gwy"], 1, 5): (200, {"data": {"listVO": []}})})
    with pytest.raises(ExternalError) as excinfo:
        fetch_all(["gwy"], pages=1, n=5, delay=0, get=stub,
                  sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    assert "searchVO" in str(excinfo.value)
    assert not isinstance(excinfo.value, ChannelUnavailable)


def test_non_json_response_is_a_hard_failure():
    stub = ApiStub({(PARAM["gwy"], 1, 5): (200, "<html>维护中</html>".encode("utf-8"))})
    with pytest.raises(ExternalError) as excinfo:
        fetch_all(["gwy"], pages=1, n=5, delay=0, get=stub,
                  sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    assert "JSON" in str(excinfo.value)


def test_missing_required_field_is_dropped_not_patched(capsys, tmp_path):
    """FR-11 既定处置：必填字段缺失的条目**不落库、不补编**，计进 `dropped` 并降级 exit 1。

    **实测依据**（M2 真跑抓到）：部委频道第 2 页存在 `summary` 为空的真实条目
    （id 26549375）——M1 观测池只看了前 30 条，没覆盖到。一条脏数据不该让整个工具
    拒绝工作，但也不许它带着「补编出来的字段」流进快照。
    """
    payload = sample_payload(FROZEN[(PARAM["gwy"], 1, 5)])
    payload["searchVO"]["listVO"][0]["summary"] = ""
    dropped_id = payload["searchVO"]["listVO"][0]["id"]
    stub = ApiStub({(PARAM["gwy"], 1, 5): (200, payload)})
    items, meta = fetch_all(["gwy"], pages=1, n=5, delay=0, get=stub,
                            sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)

    assert len(items) == 4, "脏条目不得落库"
    assert all(it.id != dropped_id for it in items)
    assert meta[0]["returned"] == 5 and meta[0]["kept"] == 4 and meta[0]["dropped"] == 1
    assert meta[0]["dropped_details"] == [
        {"id": dropped_id, "reason": "required_fields_missing", "missing": ["summary"]}]

    # 对账行必须**点名**被丢弃的条目（不能静默少一条）。
    line = [ln for ln in reconciliation_lines(meta) if ln.startswith("丢弃")][0]
    assert dropped_id in line and "required_fields_missing" in line

    # CLI 面：产物照写，但退出码 1（降级完成）。
    out = os.path.join(str(tmp_path), "dropped.json")
    code = _run_cli(stub, ["--channel", "gwy", "--n", "5", "--delay", "0", "--out", out])
    assert code == errors.EXIT_DEGRADED
    artifact = json.loads(io.open(out, "r", encoding="utf-8").read())
    assert artifact["item_count"] == 4
    assert artifact["reconciliation"]["returned_total"] == 5
    assert artifact["reconciliation"]["kept_total"] == 4
    assert artifact["reconciliation"]["dropped_total"] == 1
    assert dropped_id not in [it["id"] for it in artifact["items"]]
    assert "丢弃 1 条" in capsys.readouterr().out


def test_impossible_date_is_dropped_with_reason():
    """`2026.13.45` 这种"月日各自合法但组合不存在"的日期 -> 丢弃并记原因，不静默放过。"""
    payload = sample_payload(FROZEN[(PARAM["gwy"], 1, 5)])
    payload["searchVO"]["listVO"][0]["pubtimeStr"] = "2026.13.45"
    bad_id = payload["searchVO"]["listVO"][0]["id"]
    stub = ApiStub({(PARAM["gwy"], 1, 5): (200, payload)})
    items, meta = fetch_all(["gwy"], pages=1, n=5, delay=0, get=stub,
                            sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    assert len(items) == 4
    assert meta[0]["dropped_details"] == [
        {"id": bad_id, "reason": "pubtime_invalid", "value": "2026.13.45"}]


def test_dropping_does_not_break_the_self_check():
    """丢弃发生在**自证之后**：自证比的是「API 真返回几条」，不是「我留下了几条」。"""
    payload = sample_payload(FROZEN[(PARAM["gwy"], 1, 5)])
    payload["searchVO"]["listVO"][0]["summary"] = ""
    stub = ApiStub({(PARAM["gwy"], 1, 5): (200, payload)})
    _items, meta = fetch_all(["gwy"], pages=1, n=5, delay=0, get=stub,
                             sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    # 声明 totalCount 仍是样本的真实总数，实际仍是 5 条 —— 丢弃不改这两个数。
    assert "实际 5 条" in reconciliation_lines(meta)[0]
    assert meta[0]["declared_total"] == payload["searchVO"]["totalCount"]


def test_legacy_item_url_fields_never_reach_the_output():
    """`url` 只做非空校验；`PolicyItem` 白名单之外的 API 字段（含 UI 字段）不入产物。"""
    payload = sample_payload(FROZEN[(PARAM["gwy"], 1, 5)])
    payload["searchVO"]["listVO"][0]["piclinksurl"] = "https://example.invalid/x.png"
    payload["searchVO"]["listVO"][0]["content"] = "正文不该入库"
    stub = ApiStub({(PARAM["gwy"], 1, 5): (200, payload)})
    items, _meta = fetch_all(["gwy"], pages=1, n=5, delay=0, get=stub,
                             sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    output = build_output(items, _meta, FIXED_CLOCK)
    for item in output["items"]:
        assert set(item) == set(SCHEMA_FIELDS)
        assert not (set(item) & set(FORBIDDEN_SNAPSHOT_FIELDS))


# --- 5. 失败隔离与退出码（走真 CLI 入口） -----------------------------------

def _run_cli(stub, argv, tmp_path=None):
    """在**进程内**跑 CLI（网络/时钟/睡眠三点都替换成测试替身）：`main_guarded` 是真入口。"""
    original = (fetch_mod._default_get, fetch_mod._default_now, fetch_mod._default_sleep)
    fetch_mod._default_get = stub
    fetch_mod._default_now = lambda: FIXED_CLOCK
    fetch_mod._default_sleep = lambda _seconds: None
    try:
        return main_guarded(["fetch"] + list(argv))
    finally:
        (fetch_mod._default_get, fetch_mod._default_now,
         fetch_mod._default_sleep) = original


def test_full_success_exit_0_and_artifact_written(tmp_path):
    out = os.path.join(str(tmp_path), "fetched.json")
    stub = ApiStub({(PARAM["gwy"], 1, 5): frozen_route("gwy"),
                    (PARAM["bm"], 1, 5): frozen_route("bm")})
    code = _run_cli(stub, ["--pages", "1", "--n", "5", "--delay", "0", "--out", out])
    assert code == errors.EXIT_OK
    # 声明总数取自冻结样本本身（**不硬编码 6222/12803**：那是会漂移的实测数字）。
    declared = sum(sample_payload(FROZEN[(PARAM[ch], 1, 5)])["searchVO"]["totalCount"]
                   for ch in ("gwy", "bm"))
    payload = json.loads(io.open(out, "r", encoding="utf-8").read())
    assert payload["format"] == fetch_mod.FETCH_FORMAT
    assert payload["format_version"] == fetch_mod.FETCH_FORMAT_VERSION
    assert payload["item_order"] == "api", "抓取层不重排（规范排序是 M3 快照层的事）"
    assert payload["item_count"] == len(payload["items"]) == 10
    assert payload["reconciliation"] == {
        "requested_total": 10, "declared_total": declared, "returned_total": 10,
        "kept_total": 10, "dropped_total": 0,
        "channels_ok": 2, "channels_degraded": 0,
    }
    assert payload["captured_at"] == FIXED_CLOCK


def test_transport_failure_is_isolated_and_exit_1(tmp_path, capsys):
    """一频道挂不中断另一频道：好的照常产出，坏的记 degraded，退出码 1（降级完成）。"""
    out = os.path.join(str(tmp_path), "partial.json")
    stub = ApiStub({(PARAM["gwy"], 1, 5): frozen_route("gwy"),
                    (PARAM["bm"], 1, 5): unreachable()})
    code = _run_cli(stub, ["--pages", "1", "--n", "5", "--delay", "0", "--out", out])
    assert code == errors.EXIT_DEGRADED

    payload = json.loads(io.open(out, "r", encoding="utf-8").read())
    by_channel = dict((m["channel"], m) for m in payload["channels"])
    assert by_channel["gwy"]["status"] == "ok" and by_channel["gwy"]["kept"] == 5
    assert by_channel["bm"]["status"] == "degraded" and by_channel["bm"]["kept"] == 0
    assert by_channel["bm"]["declared_total"] is None
    assert payload["item_count"] == 5
    assert all(it["source"] == "gwy" for it in payload["items"])

    out_text = capsys.readouterr().out
    assert "声明 totalCount 未知 / 实际 0 条" in out_text
    assert "[degraded]" in out_text


def test_partial_channel_pages_are_dropped_not_half_kept(tmp_path):
    """频道抓到第 2 页才挂 -> 该频道条目**整频道丢弃**（半份数据比没数据更危险）。"""
    entries = entries_of("gwy")
    out = os.path.join(str(tmp_path), "half.json")
    stub = ApiStub({
        (PARAM["gwy"], 1, 5): (200, derived_payload("gwy", entries[0:5], 10, 5)),
        (PARAM["gwy"], 2, 5): (200, derived_payload("gwy", entries[5:10], 10, 5)),
        (PARAM["bm"], 1, 5): (200, derived_payload("bm", entries_of("bm")[0:5], 10, 5)),
        (PARAM["bm"], 2, 5): unreachable(),
    })
    code = _run_cli(stub, ["--pages", "2", "--n", "5", "--delay", "0", "--out", out])
    assert code == errors.EXIT_DEGRADED
    payload = json.loads(io.open(out, "r", encoding="utf-8").read())
    by_channel = dict((m["channel"], m) for m in payload["channels"])
    assert by_channel["gwy"]["kept"] == 10
    assert by_channel["bm"]["status"] == "degraded"
    assert by_channel["bm"]["kept"] == 0, "第 1 页的 5 条不得以「完整频道」的样子留下"
    assert payload["item_count"] == 10
    assert all(it["source"] == "gwy" for it in payload["items"])


def test_all_channels_unreachable_exit_4_and_no_product(tmp_path, capsys):
    """网络不可达且**全频道**失败 -> exit 4，且**不留半个产物**（原子写的前置语义）。"""
    out = os.path.join(str(tmp_path), "never.json")
    stub = ApiStub({}, default=unreachable())
    code = _run_cli(stub, ["--pages", "1", "--n", "5", "--delay", "0", "--out", out])
    assert code == errors.EXIT_EXTERNAL
    assert not os.path.exists(out), "全部失败时不得产出任何文件"
    leftovers = [n for n in os.listdir(str(tmp_path)) if n.startswith(".tmp-")]
    assert leftovers == [], "原子写不得残留临时文件：%r" % leftovers
    captured = capsys.readouterr()
    assert "未产出任何文件" in captured.err
    assert "声明 totalCount 未知" in captured.out


def test_hard_failure_beats_isolation_and_leaves_nothing(tmp_path):
    """结构异常是**硬失败**：哪怕另一频道已抓成功，也 exit 4 且不落任何文件。"""
    out = os.path.join(str(tmp_path), "hard.json")
    stub = ApiStub({(PARAM["gwy"], 1, 5): frozen_route("gwy"),
                    (PARAM["bm"], 1, 5): (200, {"unexpected": True})})
    code = _run_cli(stub, ["--pages", "1", "--n", "5", "--delay", "0", "--out", out])
    assert code == errors.EXIT_EXTERNAL
    assert not os.path.exists(out)


def test_unwritable_out_path_is_usage_error(tmp_path):
    """`--out` 指向一个目录 -> exit 2（用法错误），不逃逸成 traceback。"""
    stub = ApiStub({(PARAM["gwy"], 1, 5): frozen_route("gwy")})
    code = _run_cli(stub, ["--channel", "gwy", "--n", "5", "--delay", "0",
                           "--out", str(tmp_path)])
    assert code == errors.EXIT_USAGE


# --- 6. 确定性与"时间戳只进元信息" ------------------------------------------

def test_timestamp_is_meta_only(tmp_path):
    """两个不同时钟跑出的产物，除 `captured_at` 外**必须逐字段一致**——时间戳不参与判定。"""
    stub = ApiStub({(PARAM["gwy"], 1, 5): frozen_route("gwy")})
    items, meta = fetch_all(["gwy"], pages=1, n=5, delay=0, get=stub,
                            sleep=SleepRecorder(), now=lambda: FIXED_CLOCK)
    first = build_output(items, meta, FIXED_CLOCK)
    second = build_output(items, meta, "2030-01-01T09:09:09")
    assert first["captured_at"] != second["captured_at"]
    for payload in (first, second):
        payload.pop("captured_at")
    assert first == second


def test_double_run_is_byte_identical_with_frozen_clock(tmp_path):
    """冻结时钟下双跑逐字节一致（产物确定性；真实运行时时间戳会变，那是元信息）。"""
    stub = ApiStub({(PARAM["gwy"], 1, 5): frozen_route("gwy"),
                    (PARAM["bm"], 1, 5): frozen_route("bm")})
    paths = []
    for name in ("a.json", "b.json"):
        out = os.path.join(str(tmp_path), name)
        assert _run_cli(stub, ["--pages", "1", "--n", "5", "--delay", "0",
                               "--out", out]) == errors.EXIT_OK
        paths.append(out)
    with io.open(paths[0], "rb") as f1, io.open(paths[1], "rb") as f2:
        assert f1.read() == f2.read()


def test_module_has_no_wall_clock_in_judgment():
    """源码级守门：判定路径不得直接调用 `time.*`（时钟只能经注入的 `now` 进元信息）。"""
    with io.open(fetch_mod.__file__, "r", encoding="utf-8") as fh:
        source = fh.read()
    body = source[source.index("def fetch_channel"):source.index("def fetch_all")]
    assert "time.time()" not in body and "time.localtime" not in body
    assert "import datetime" not in source, "判定路径不得引入日期时间库"


def test_sys_is_imported_for_cli_output():
    """`cmd_fetch` 真打印（对账行 stdout / 失败 stderr），不是"算完就丢"。"""
    assert fetch_mod.sys is sys


# --- 7. 默认传输层真跑（本地关闭端口，不依赖外网） --------------------------

def test_default_transport_maps_real_unreachable_host_to_channel_unavailable(monkeypatch):
    """**真的走一遍 stdlib `urllib`**：连不上 -> 重试耗尽 -> `ChannelUnavailable`。

    指向 `127.0.0.1:9`（discard 端口，本机无人监听）——不需要外网、不会打到真站点，
    但走的是 `_default_get` 的真实现，而不是测试替身。这条守的是"真传输层的失败
    也被归一成可隔离的那一类"：只测假替身的话，真传输层抛别的异常就漏过去了。
    """
    monkeypatch.setattr(fetch_mod, "API_BASE", "https://127.0.0.1:9/search-gov/data")
    attempts = {"n": 0}
    real_get = fetch_mod._default_get

    def counting_get(url, timeout):
        attempts["n"] += 1
        return real_get(url, timeout)

    with pytest.raises(ChannelUnavailable):
        fetch_channel("gwy", pages=1, n=5, pacer=Pacer(0, SleepRecorder()),
                      timeout=2, retries=0, get=counting_get,
                      now=lambda: FIXED_CLOCK)
    assert attempts["n"] == 1


def test_default_transport_rejects_non_http_scheme(monkeypatch):
    """非 HTTP URL 不得让 `int(None)` 的 TypeError 逃逸成"程序崩了"——必须归一成领域异常。

    用**必然不存在**的路径（跨平台都取不到），避免"某个平台上文件恰好存在"导致假绿。
    """
    monkeypatch.setattr(fetch_mod, "API_BASE",
                        "file:///policy-radar-definitely-missing-path")
    with pytest.raises(errors.RadarError) as excinfo:
        fetch_channel("gwy", pages=1, n=5, pacer=Pacer(0, SleepRecorder()),
                      timeout=2, retries=0, now=lambda: FIXED_CLOCK)
    assert excinfo.value.code in (errors.EXIT_DEGRADED, errors.EXIT_USAGE,
                                  errors.EXIT_EXTERNAL)