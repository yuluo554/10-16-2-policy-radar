"""双源抓取（M2）：两个频道 -> 统一 schema 条目 + 逐频道抓取元信息。

设计纪律（`plan/04-模块详设.md` 模块 1，逐条对应）：

1. **取数路径固定** = `searchVO.listVO`（决策 D13）：复用 `model.items_from_listvo()`，
   该函数对结构异常**显式抛错**，不静默按最宽松规则解析。
2. **限频**：逐请求固定延时（默认 1.5s，可配）、**不做高并发**、同进程内多频道**串行**。
   延时收口在 `Pacer`——"两次请求之间要隔多久"只有一个实现点。
3. **超时 + 重试**：单请求超时 20s；失败重试 2 次（指数退避 1s / 2s）。
4. **三类异常的处置不同**（本模块最容易做错的地方）：

   - **传输层失败**（连不上 / 超时 / 5xx / 429，重试后仍失败）→ 该频道记 `degraded`，
     其条目**整频道丢弃**（不把"抓了一半的频道"当完整数据），**不中断另一频道**——
     即"失败隔离"。全部频道都 degraded → **exit 4 且不产出任何文件**（不留半个产物）。
   - **条目级不合规**（必填字段缺失 / `pubtimeStr` 组合不真实）→ 该条**不落库、
     不补编字段**，计进 `dropped` 并点名 id；**整次运行降级为 exit 1**（"完成但有降级"）。
     这是 FR-11 的既定处置口径（见 `model.PolicyItem.validate` 与 `plan/04` 模块 5）：
     一条真实发文缺 `summary` 是**数据质量问题**，不该让整个工具拒绝工作。
   - **硬失败**（抓取自证不符 / API 结构异常 / 响应非 JSON / 缺 `totalCount`）→
     **立即 exit 4，不做频道级降级**。判别口诀：**"那是接口在说谎，还是环境在抖动？"**
     说谎必须停——把"接口在说谎"降级成"这个频道跳过"，下游会拿着错数据继续跑。

5. **抓取自证**：逐页断言 `len(实际取到) == min(n, totalCount - 已取该频道条数)`。
   **不得**把 `totalCount` 当作"我拿到了这么多"——它是**服务器声明**的总数，
   与实际取到条数是两个数，对账行的价值就在于把两个数都打出来。不符即 exit 4，
   并把**实际/声明两数**写进错误信息。
6. **不拼 URL**（决策 D2）：抓取目标只认请求 URL（API 端点 + 查询参数），条目里的
   `url` 字段只做**非空校验**（随 `PolicyItem.validate()`），**不发正文请求**。
7. **无时钟参与判定**：抓取时间戳只进元信息（`captured_at`），不参与任何判定。

## 可测试性

"外部世界交互"三点全部单点可注入：`get(url, timeout) -> (http_status, bytes)`、
`sleep(seconds)`、`now() -> str`。默认走 stdlib `urllib` / `time`；测试用**冻结的
`data/samples/` 真实响应字节**喂假传输层跑全链路**离线回归**（绝不打真站点：
真站点不可复现、内容会漂移，且会触发对方风控）。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

from .errors import (
    EXIT_DEGRADED, EXIT_EXTERNAL, EXIT_OK,
    ExternalError, UsageError,
)
from .model import items_from_listvo, total_count
from .serialize import write_json

#: API 端点（与 README / `data/README.md` 的示例逐字一致）。
API_BASE = "https://sousuo.www.gov.cn/search-gov/data"

#: 频道标识 -> API 的 `t` 参数（`model.CHANNELS` 给的是中文名，各司其职）。
CHANNEL_PARAMS = {
    "gwy": "zhengcelibrary_gwy",
    "bm": "zhengcelibrary_bm",
}

#: 默认抓取频道（决策 P2：每频道 1 页 20 条）。**串行**抓取，不做并发。
DEFAULT_CHANNELS = ("gwy", "bm")

DEFAULT_PAGES = 1
DEFAULT_N = 20

#: 逐请求延时（秒）：平台礼仪，见 README「平台礼仪」。
DEFAULT_DELAY = 1.5

DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 2

#: 我方自设上限（**未实测对方上限**，故只写"自设"）：防本工具被误用成批量下载器
#: ——题面明确"快照 diff 检测新增，不是每次全量翻页"。超限即 exit 2（用法错误）。
MAX_PAGES = 50
MAX_PAGE_SIZE = 50

#: 默认产出路径（`/out/` 已在 `.gitignore` 覆盖：运行时产物不入库）。
DEFAULT_OUT = "out/fetched.json"

#: 产物格式标识（M3 的 `diff --current` 按 `items` 键读）。
FETCH_FORMAT = "policy-radar-fetch"
FETCH_FORMAT_VERSION = 1

#: 请求头（明确 UA 便于对方识别；只发只读 GET）。
USER_AGENT = "policy-radar/0.1 (+local CLI; metadata only)"

#: 可重试（且可隔离）的 HTTP 状态：5xx 服务端瞬时故障、429 限频。
_RETRYABLE_STATUS = (429, 500, 501, 502, 503, 504, 507, 508)


class ChannelUnavailable(ExternalError):
    """**传输层**失败：该频道重试后仍不可达 -> 记 `degraded`，可被隔离。

    它继承 `ExternalError`（退出码仍是 4）：一旦**所有**频道都 degraded，
    CLI 就返回 exit 4。之所以单独立类，是为了让 `fetch_all()` 能**只**隔离这一类
    失败——硬失败（自证不符 / 结构异常）必须穿透上去 exit 4，不得被降级吞掉。
    """

    code = EXIT_EXTERNAL


class Pacer(object):
    """逐请求限频器。

    "两次请求之间隔多久"只有一个实现点：**第一次请求不延时**，其后每次请求前
    延时 `delay` 秒（请求之间因此恒为 `delay` 间隔——含跨频道边界，即"同进程内
    多频道串行且统一限频"）。
    """

    def __init__(self, delay, sleep):
        self.delay = delay
        self.sleep = sleep
        self.first = True

    def wait(self):
        if self.first:
            self.first = False
            return
        if self.delay and self.delay > 0:
            self.sleep(self.delay)


def _default_now():
    """抓取时间戳（本地时区，**只进元信息**，不参与任何判定）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _default_sleep(seconds):
    """默认睡眠（限频与重试退避共用）。

    单独立成函数而不是直接把 `time.sleep` 传下去：**"外部世界交互"（网络 / 时钟 /
    睡眠）三者都要能在测试里单点替换**——否则跑一遍失败路径的测试要真等 1s + 2s×N。
    """
    time.sleep(seconds)


def _default_get(url, timeout):
    """默认传输层：stdlib `urllib` 只读 GET。返回 `(http_status, 原始字节)`。

    返回**原始字节**而不是解析后的对象：解析与结构判定归 `fetch_channel()`，
    传输层只管"把字节拿回来"，便于测试替换（注入冻结样本）。
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", None)
        if status is None:
            status = resp.getcode()
        if not isinstance(status, int):
            # 非 HTTP 响应（如 file:// 或畸形响应）没有状态码 —— 显式报错，
            # 别让 `int(None)` 的 TypeError 逃逸成用户眼里的"程序崩了"。
            raise ExternalError("传输层未返回 HTTP 状态码（%r）：%s" % (status, url))
        return status, resp.read()


def build_url(channel, page, n):
    """按**实测通过**的形态拼请求 URL（与 README / `data/README.md` 逐字一致）。

    这是"API 端点 + 查询参数"，不是决策 D2 所禁的"自行拼正文链接"——正文链接
    一律只认 API 返回的 `url` 字段。
    """
    param = CHANNEL_PARAMS[channel]
    return "%s?t=%s&q=&p=%d&n=%d&sort=pubtime&sortType=1" % (
        API_BASE, param, page, n)


def _is_retryable_status(status):
    try:
        return int(status) in _RETRYABLE_STATUS
    except (TypeError, ValueError):
        return False


def _get_with_retry(url, timeout, retries, get, sleep):
    """带重试的取字节；返回 `(http_status, bytes)`。

    重试策略（口径"超时 20s + 重试 2 次，指数退避"）：
    - 连接类错误（`URLError`/`OSError`，含超时）→ 重试；
    - 5xx / 429 → 重试（服务端瞬时故障）；
    - 其它 4xx（404/403…）→ **立即失败不重试**：端点或契约变了，重试只是浪费对方资源。

    重试耗尽统一抛 `ChannelUnavailable`（可隔离）；4xx 抛裸 `ExternalError`（硬失败）。
    """
    last_error = None
    for attempt in range(retries + 1):
        try:
            status, body = get(url, timeout)
        except ExternalError:
            raise
        except urllib.error.HTTPError as exc:
            last_error = "HTTP %s %s" % (exc.code, exc.reason)
            if not _is_retryable_status(exc.code):
                raise ExternalError("API 返回 HTTP %s（%s）" % (exc.code, url))
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
        else:
            try:
                code = int(status)
            except (TypeError, ValueError):
                raise ExternalError("传输层返回了非数字状态码：%r（%s）" % (status, url))
            if code == 200:
                return status, body
            last_error = "HTTP %s" % (status,)
            if not _is_retryable_status(code):
                raise ExternalError("API 返回 HTTP %s（%s）" % (status, url))

        if attempt < retries:
            sleep(2 ** attempt)  # 指数退避 1s / 2s
    raise ChannelUnavailable(
        "抓取失败（%d 次尝试后仍不可达）：%s（%s）" % (retries + 1, last_error, url))


def parse_payload(raw):
    """原始字节 -> JSON 对象；不是合法 UTF-8 JSON 即抛 `ExternalError`（硬失败）。"""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ExternalError("响应不是合法 UTF-8 JSON：%s" % exc)
    if not isinstance(payload, dict):
        raise ExternalError("响应顶层不是 JSON 对象（%r）" % type(payload).__name__)
    return payload


def partition_valid_items(items):
    """按 FR-11 把条目分成「可落库」与「丢弃」两堆。返回 `(kept, dropped)`。

    **不补编字段、不放行半条**，也**不为一条脏数据打断整次抓取**：
    丢弃的条目逐条记 id 与原因，进元信息、进 stdout、退化成 exit 1。
    """
    kept = []
    dropped = []
    for item in items:
        missing = item.validate()
        if missing:
            dropped.append({"id": item.id, "reason": "required_fields_missing",
                            "missing": missing})
            continue
        if not item.date_valid():
            dropped.append({"id": item.id, "reason": "pubtime_invalid",
                            "value": item.pubtimeStr})
            continue
        kept.append(item)
    return kept, dropped


def fetch_channel(channel, pages=DEFAULT_PAGES, n=DEFAULT_N, pacer=None,
                  timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES,
                  get=None, now=None):
    """抓一个频道（逐页、限频、带自证）。返回 `(可落库条目, 频道元信息)`。

    元信息里的三个条数是**三个不同的数**，不得混用：
    `returned`（服务器真返回了几条）/ `kept`（通过 schema 校验几条）/ `dropped`（丢了几条）。
    """
    if channel not in CHANNEL_PARAMS:
        raise UsageError("未知频道：%r（可选 %r）"
                         % (channel, sorted(CHANNEL_PARAMS)))
    get = get or _default_get
    now = now or _default_now
    if pacer is None:
        pacer = Pacer(DEFAULT_DELAY, _default_sleep)

    kept_items = []
    dropped_items = []
    page_details = []
    declared_total = None
    returned_total = 0

    for page in range(1, pages + 1):
        # 已取满服务器声明的总数 -> 不再发多余请求（省对方带宽，也不把"请求条数"
        # 虚报成比实际存在的还多）。
        if declared_total is not None and returned_total >= declared_total:
            break

        pacer.wait()
        url = build_url(channel, page, n)
        status, body = _get_with_retry(url, timeout, retries, get, pacer.sleep)
        payload = parse_payload(body)

        # 先判取数路径（结构漂移是更根本的诊断），再判自证基准（totalCount）。
        try:
            page_items = items_from_listvo(payload, channel)
        except ValueError as exc:
            raise ExternalError("API 结构异常（取数路径应为 searchVO.listVO）：%s（%s）"
                                % (exc, url))

        total = total_count(payload)
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ExternalError(
                "响应缺少合法 searchVO.totalCount（抓取自证失去基准）：%r（%s）"
                % (total, url))

        # --- 抓取自证：本页实际条数 == min(每页请求数, 声明总数 - 已取) ---------
        expected = min(n, max(total - returned_total, 0))
        if len(page_items) != expected:
            raise ExternalError(
                "抓取自证不符：%s 第 %d 页请求 %d 条 / 声明 totalCount %d / 已取 %d 条"
                " → 期望 %d 条，实际 %d 条（%s）"
                % (channel, page, n, total, returned_total, expected,
                   len(page_items), url))

        kept_here, dropped_here = partition_valid_items(page_items)
        kept_items.extend(kept_here)
        dropped_items.extend(dropped_here)
        returned_total += len(page_items)
        declared_total = total
        page_details.append({
            "page": page,
            "url": url,
            "http_status": int(status),
            "entries": len(page_items),
            "declared_total": total,
        })

    return kept_items, {
        "channel": channel,
        "channel_param": CHANNEL_PARAMS[channel],
        "status": "ok",
        "pages": pages,
        "n": n,
        "requested": pages * n,
        "returned": returned_total,
        "kept": len(kept_items),
        "dropped": len(dropped_items),
        "dropped_details": dropped_items,
        "declared_total": declared_total,
        "captured_at": now(),
        "page_details": page_details,
        "error": "",
    }


def fetch_all(channels=None, pages=DEFAULT_PAGES, n=DEFAULT_N, delay=DEFAULT_DELAY,
              timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES,
              get=None, sleep=None, now=None):
    """**串行**抓多个频道，失败隔离。返回 `(可落库条目, 逐频道元信息列表)`。

    只有 `ChannelUnavailable`（传输层）被隔离成 `degraded`；硬失败穿透抛出。
    degraded 频道的条目**整频道丢弃**（`kept`/`returned` 记 0）——"抓了一半"比
    "没抓到"更危险：它会以完整数据的样子流进快照 diff。
    """
    if channels is None:
        channels = list(DEFAULT_CHANNELS)
    channels = list(channels)
    if not channels:
        raise UsageError("至少要指定一个频道")
    for channel in channels:
        if channel not in CHANNEL_PARAMS:
            raise UsageError("未知频道：%r（可选 %r）"
                             % (channel, sorted(CHANNEL_PARAMS)))

    sleep = sleep or _default_sleep
    get = get or _default_get
    now = now or _default_now
    pacer = Pacer(delay, sleep)

    items = []
    channel_meta = []
    for channel in channels:
        try:
            channel_items, meta = fetch_channel(
                channel, pages=pages, n=n, pacer=pacer, timeout=timeout,
                retries=retries, get=get, now=now)
        except ChannelUnavailable as exc:
            channel_meta.append({
                "channel": channel,
                "channel_param": CHANNEL_PARAMS[channel],
                "status": "degraded",
                "pages": pages,
                "n": n,
                "requested": pages * n,
                "returned": 0,
                "kept": 0,
                "dropped": 0,
                "dropped_details": [],
                "declared_total": None,
                "captured_at": now(),
                "page_details": [],
                "error": str(exc),
            })
            continue
        items.extend(channel_items)
        channel_meta.append(meta)
    return items, channel_meta


def build_output(items, channel_meta, captured_at):
    """组装产物对象（字段白名单 = `PolicyItem` 的十项；**不含正文**）。

    `item_order` 明写 `api`：条目顺序 = API 返回序。规范排序
    `(pubtimeStr 倒序, id 升序)`（K5）是 M3 快照层的事——本模块不重排，
    免得"排序口径"出现第二个实现点。
    """
    ok_meta = [m for m in channel_meta if m["status"] == "ok"]
    declared = [m["declared_total"] for m in channel_meta
                if isinstance(m.get("declared_total"), int)]
    return {
        "format": FETCH_FORMAT,
        "format_version": FETCH_FORMAT_VERSION,
        "note": "双源抓取产出（M2）：统一 schema 元数据 + 逐频道抓取元信息，不含正文。",
        "captured_at": captured_at,
        "item_order": "api",
        "item_count": len(items),
        "reconciliation": {
            "requested_total": sum(m["requested"] for m in channel_meta),
            "declared_total": (sum(declared) if len(declared) == len(channel_meta)
                               else None),
            "returned_total": sum(m["returned"] for m in channel_meta),
            "kept_total": len(items),
            "dropped_total": sum(m["dropped"] for m in channel_meta),
            "channels_ok": len(ok_meta),
            "channels_degraded": len(channel_meta) - len(ok_meta),
        },
        "channels": channel_meta,
        "items": [it.to_dict() for it in items],
    }


def reconciliation_lines(channel_meta):
    """对账行（DoD 硬要求：`请求 N 条 / 声明 totalCount M / 实际 K` 必须**真打印**）。

    逐频道一行 + 一行合计 + （有丢弃时）一行丢弃点名。degraded 频道的
    `declared_total` 记"未知"——连不上时我们**确实不知道**对方总数，不能拿 0 冒充。
    """
    lines = []
    for meta in channel_meta:
        declared = meta.get("declared_total")
        lines.append("对账 %s：请求 %d 条 / 声明 totalCount %s / 实际 %d 条  [%s]%s" % (
            meta["channel"], meta["requested"],
            declared if isinstance(declared, int) else "未知",
            meta["returned"], meta["status"],
            ("（%s）" % meta["error"]) if meta.get("error") else ""))
    declared_values = [m["declared_total"] for m in channel_meta
                       if isinstance(m.get("declared_total"), int)]
    lines.append("对账 合计：请求 %d 条 / 声明 totalCount %s / 实际 %d 条" % (
        sum(m["requested"] for m in channel_meta),
        sum(declared_values) if len(declared_values) == len(channel_meta) else "部分未知",
        sum(m["returned"] for m in channel_meta)))

    dropped_total = sum(m["dropped"] for m in channel_meta)
    if dropped_total:
        lines.append("丢弃 %d 条（schema 校验未过：不落库、不补编字段，本次降级）：%s" % (
            dropped_total,
            ", ".join("%s(%s)" % (d["id"], d["reason"])
                      for m in channel_meta for d in m.get("dropped_details", []))))
    return lines


def dropped_total(channel_meta):
    """被丢弃的条目总数（决定本次是否降级为 exit 1）。"""
    return sum(m["dropped"] for m in channel_meta)


def _validate_options(pages, n, delay):
    """参数校验（非法即 exit 2）。上限是我方自设——**未实测对方上限**，故只当护栏。"""
    if pages < 1:
        raise UsageError("--pages 必须 >= 1（收到 %r）" % (pages,))
    if pages > MAX_PAGES:
        raise UsageError("--pages 不得超过 %d（本工具是「盯新发」，不是批量下载器）"
                         % MAX_PAGES)
    if n < 1:
        raise UsageError("--n 必须 >= 1（收到 %r）" % (n,))
    if n > MAX_PAGE_SIZE:
        raise UsageError("--n 不得超过 %d（实测 n=30 可用；本工具不做全量翻页）"
                         % MAX_PAGE_SIZE)
    if delay < 0:
        raise UsageError("--delay 必须 >= 0（收到 %r）" % (delay,))


def resolve_channels(values):
    """归一 `--channel`（可重复）为去重后的频道列表；不传 = 两频道。"""
    if not values:
        return list(DEFAULT_CHANNELS)
    out = []
    for value in values:
        if value not in CHANNEL_PARAMS:
            raise UsageError("未知频道：%r（可选 %r）"
                             % (value, sorted(CHANNEL_PARAMS)))
        if value not in out:
            out.append(value)
    return out


def cmd_fetch(args):
    """`fetch` 子命令：抓取 -> 对账行 -> 原子写产物 -> 退出码。

    退出码：0 = 全部频道成功且无丢弃；1 = 有频道 degraded 或有条目被丢弃
    （其余照常产出）；4 = 全部频道都失败（**不产出任何文件**）或硬失败；
    2 = 用法错误。
    """
    channels = resolve_channels(getattr(args, "channel", None))
    # 注意：这里**不能**写 `value or DEFAULT`——`--pages 0` 是非法值（该报 exit 2），
    # 而 `0 or 1` 会把它悄悄改成合法默认值，"非法输入被静默接受"是最坏的一类缺陷。
    pages = getattr(args, "pages", None)
    pages = DEFAULT_PAGES if pages is None else int(pages)
    n = getattr(args, "n", None)
    n = DEFAULT_N if n is None else int(n)
    delay = getattr(args, "delay", None)
    delay = DEFAULT_DELAY if delay is None else float(delay)
    out_path = getattr(args, "out", None) or DEFAULT_OUT
    _validate_options(pages, n, delay)

    now = _default_now
    items, channel_meta = fetch_all(channels, pages=pages, n=n, delay=delay,
                                    sleep=_default_sleep, now=now)

    for line in reconciliation_lines(channel_meta):
        sys.stdout.write("  %s\n" % line)

    ok = [m for m in channel_meta if m["status"] == "ok"]
    if not ok:
        for meta in channel_meta:
            sys.stderr.write("fetch: 频道 %s 抓取失败（degraded）：%s\n"
                             % (meta["channel"], meta["error"]))
        sys.stderr.write("fetch: %d 个频道全部失败，未产出任何文件\n"
                         % len(channel_meta))
        return EXIT_EXTERNAL

    output = build_output(items, channel_meta, now())
    try:
        write_json(out_path, output)
    except (IOError, OSError) as exc:
        raise UsageError("无法写出抓取产物：%s（%s）" % (out_path, exc))

    degraded = len(ok) < len(channel_meta)
    sys.stdout.write("已写出 %s（落库 %d 条；%d/%d 频道成功%s）\n" % (
        out_path, len(items), len(ok), len(channel_meta),
        "；丢弃 %d 条" % dropped_total(channel_meta) if dropped_total(channel_meta) else ""))
    if degraded or dropped_total(channel_meta):
        return EXIT_DEGRADED
    return EXIT_OK