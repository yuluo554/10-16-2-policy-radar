"""端到端编排（M5 编排层）：`run` = fetch → diff → parse → subscribe → digest。

设计纪律（`plan/04-模块详设.md` 编排层）：

1. **上收为公开函数组**：`run_pipeline()` 是编排单点，CLI（`cmd_run`）与任何
   未来形态共用同一函数——测试断言**行为等价**（CLI stdout 的统计 ==
   直调编排的返回值统计 == 报告里的统计），不是"都调了同一个函数"的字面声明。
2. **零判定**：编排层只做装载与串联，判定全部在既有模块单点
   （diff → `snapshot.detect_new`、parse → `parse.parse_pcode`/`parse_orgs`、
   订阅 → `subscribe.match_items`、渲染 → `report`）。本模块不复制任何判定逻辑。
3. **中间产物全落盘**：fetch/diff/parse/subscribe 的产物都写在 `--out-dir`
   （默认 `out/`，`.gitignore` 已覆盖）——每一步都可单独复查与复跑。
4. **退出码透传**（取"整条流水线的最重语义"）：
   fetch 的 0/1/4 语义按 K19/K20 原样透传（1 = 有频道 degraded 或有条目丢弃，
   4 = 全部频道失败——此时无 fetch 产物，**不产出日报**）；
   digest 的降级语义（有条目未过校验被丢弃）与 fetch 降级**合并取重**；
   2 = 用法/输入错误（频道名错、订阅配置坏等）。
5. **`captured_at` 是元信息不参与判定**（M2 既定口径）：编排的确定性判定
   （diff/subscribe/日报内容）不读时钟；fetch 产物带 `captured_at` 但不进
   任何判定，因此"离线注入产物 + 直调编排"与 CLI 编排在统计上逐项一致。
"""

import os
import sys

from .errors import ExternalError, UsageError
from .fetch import (
    DEFAULT_DELAY, DEFAULT_N, DEFAULT_PAGES, build_output, fetch_all,
    reconciliation_lines, resolve_channels, _default_now, _default_sleep,
    _validate_options,
)
from .model import PolicyItem
from .parse import build_parse_product, load_org_aliases
from .paths import find_data_root
from .snapshot import build_diff_product, build_snapshot, load_snapshot
from .subscribe import load_subscribe_inputs, match_items
from .serialize import write_json

#: 编排产物默认目录（与 fetch/diff/parse 的默认 out/ 一致；.gitignore 已覆盖）。
DEFAULT_OUT_DIR = "out"

#: 编排默认参数（CLI 旗标缺省同源；显式判 None，不走 `or DEFAULT`——坑 13）。
DEFAULT_RUN_CHANNELS = "gwy,bm"
DEFAULT_RUN_PAGES = 1
DEFAULT_RUN_N = 20
DEFAULT_RUN_DELAY = 1.5

#: 中间产物文件名（都在 --out-dir 下）。
RUN_FILENAMES = {
    "fetch": "fetched.json",
    "diff": "diff.json",
    "snapshot": "snapshot.json",
    "parse": "parsed.json",
    "subscribe": "subscribe.json",
    "report_md": "report.md",
    "report_html": "report.html",
}


def _out_path(out_dir, name):
    if not out_dir:
        raise UsageError("--out-dir 不能为空")
    return os.path.join(out_dir, name)


def load_subscribe_hits(items, data_root):
    """装载订阅配置（单一来源 `data/config/`）并对条目实算命中 → 产物对象。

    口径校验不符 / 配置缺失 → `UsageError`（exit 2，`subscribe.load_subscribe_inputs`
    同款语义）。返回的产物含 `hits/excluded/zero_hit_ids/counts`（digest 的输入）。
    """
    config, norm_map = load_subscribe_inputs(data_root)
    hits, excluded, zero = match_items(items, config["include"],
                                       config["exclude"], norm_map)
    return {
        "format": "policy-radar-subscribe",
        "format_version": 1,
        "note": "订阅命中产出（M5 编排）：match_items 实算；hits/excluded/zero_hit_ids 供日报消费。",
        "item_count": len(items),
        "hit_count": len(hits),
        "excluded_count": len(excluded),
        "zero_hit_count": len(zero),
        "hits": hits,
        "excluded": excluded,
        "zero_hit_ids": zero,
    }


def run_pipeline(channels=None, pages=DEFAULT_RUN_PAGES, n=DEFAULT_RUN_N,
                 delay=DEFAULT_RUN_DELAY, out_dir=DEFAULT_OUT_DIR,
                 data_root=None, snapshot_path=None, fetch_items=None,
                 fetch_channel_meta=None, captured_at="", now=None, sleep=None):
    """端到端编排（公开函数组单点）：抓取 → diff → parse → 订阅 → 日报。

    两种驱动方式（行为等价，测试逐项对账）：

    - **在线**：省略 `fetch_items` → 真抓取（网络异常按 fetch 的 1/4 语义透传）；
    - **离线**：传入 `fetch_items`（`PolicyItem` 列表）+ `fetch_channel_meta`
      （逐频道元信息，形态须满足 `fetch.reconciliation_lines`）→ 跳过网络，
      直接连通 diff 起步（CI/测试/演示通路）。

    返回统计 dict（`channels/new/kept/dup/hit/excluded/zero_hit/report_paths/
    report_dropped/degraded`），CLI stdout 与之同源；**不抛**判定类异常——
    输入/配置类错误抛 `UsageError`（exit 2），全部频道抓取失败抛
    `ExternalError`（exit 4，无任何产物）。
    """
    if not out_dir:
        raise UsageError("--out-dir 不能为空")
    if channels is None:
        channels = resolve_channels(None)
    else:
        channels = resolve_channels(list(channels))
    _validate_options(pages, n, delay)
    now = now or _default_now
    sleep = sleep or _default_sleep

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    # --- 第 1 步：fetch（可离线注入） ----------------------------------------
    if fetch_items is None:
        items, channel_meta = fetch_all(channels, pages=pages, n=n, delay=delay,
                                        sleep=sleep, now=now)
    else:
        items = list(fetch_items)
        channel_meta = fetch_channel_meta
    ok_meta = [m for m in channel_meta if m.get("status") == "ok"]
    if not ok_meta:
        raise ExternalError("全部 %d 个频道抓取失败，未产出任何文件（exit 4）"
                            % len(channel_meta))
    fetch_product = build_output(items, channel_meta,
                                 captured_at or now())
    fetch_path = _out_path(out_dir, RUN_FILENAMES["fetch"])
    write_json(fetch_path, fetch_product)

    # --- 第 2 步：diff（首跑 = 无上次快照；给了路径就必须读得到，K24） ---------
    if snapshot_path:
        previous_items = load_snapshot(snapshot_path)
    else:
        previous_items = []
    diff_product = build_diff_product(previous_items, items)
    new_items = [PolicyItem.from_dict(d) for d in diff_product["items"]]
    updated_snapshot = build_snapshot(items, "run 编排产出快照")
    diff_path = _out_path(out_dir, RUN_FILENAMES["diff"])
    snapshot_out_path = _out_path(out_dir, RUN_FILENAMES["snapshot"])
    write_json(diff_path, diff_product)
    write_json(snapshot_out_path, updated_snapshot)

    # --- 第 3 步：parse（别名表单一来源 data/config/） ------------------------
    if not data_root:
        data_root = find_data_root(None)
        if not data_root:
            raise UsageError("找不到数据根（部门别名表在 data/config/ 下；"
                             "显式传 --data-root 或设 POLICY_RADAR_DATA）")
    aliases = load_org_aliases(data_root)
    parse_product = build_parse_product(new_items, aliases)
    parse_path = _out_path(out_dir, RUN_FILENAMES["parse"])
    write_json(parse_path, parse_product)

    # --- 第 4 步：subscribe（配置与归一表单一来源 data/config/） --------------
    subscribe_product = load_subscribe_hits(new_items, data_root)
    subscribe_path = _out_path(out_dir, RUN_FILENAMES["subscribe"])
    write_json(subscribe_path, subscribe_product)

    # --- 第 5 步：digest（渲染层零判定，消费既有结论） -------------------------
    from .report import build_digest_product, write_digest
    digest = build_digest_product(
        diff_path, subscribe_path, parse_path=parse_path, fmt="both")
    md_path = _out_path(out_dir, RUN_FILENAMES["report_md"])
    html_path = _out_path(out_dir, RUN_FILENAMES["report_html"])
    report_paths = write_digest(md_path, digest, "md") + \
        write_digest(html_path, digest, "html")

    # --- 统计汇总（CLI stdout 与直调返回值同源；报告统计与之行为等价） ---------
    fetch_degraded = len(ok_meta) < len(channel_meta)
    dropped_fetch = sum(m.get("dropped", 0) for m in channel_meta)
    parse_map = dict((r["item_id"], r) for r in parse_product["parsed_items"])
    report_dropped = digest["dropped_count"]
    return {
        "channels": [m["channel"] for m in channel_meta],
        "channels_ok": len(ok_meta),
        "channels_degraded": len(channel_meta) - len(ok_meta),
        "kept": len(items),
        "new_count": diff_product["new_count"],
        "dup_count": diff_product["dup_count"],
        "pcode_status_counts": parse_product["pcode_status_counts"],
        "hit_count": subscribe_product["hit_count"],
        "excluded_count": subscribe_product["excluded_count"],
        "zero_hit_count": subscribe_product["zero_hit_count"],
        "report_paths": report_paths,
        "report_item_count": digest["item_count"],
        "report_dropped": report_dropped,
        "fetch_dropped": dropped_fetch,
        "parse_map": parse_map,
        "channel_meta": channel_meta,
        "degraded": bool(fetch_degraded or dropped_fetch or report_dropped),
    }


def cmd_run(args):
    """`run` 子命令：一条命令出结果（fetch → diff → parse → subscribe → digest）。

    退出码：0 = 完成；1 = 降级完成（有频道 degraded / 有条目被丢弃 /
    有条目未进日报）；2 = 用法/输入错误；4 = 全部频道抓取失败（不产出任何文件）。
    """
    out_dir = getattr(args, "out_dir", None) or DEFAULT_OUT_DIR
    channels_value = getattr(args, "channels", None)
    channels_value = DEFAULT_RUN_CHANNELS if channels_value is None else channels_value
    channels = [c.strip() for c in channels_value.split(",") if c.strip()]
    snapshot_path = getattr(args, "snapshot", None)
    data_root = getattr(args, "data_root", None)

    stats = run_pipeline(channels=channels, out_dir=out_dir, data_root=data_root,
                         snapshot_path=snapshot_path,
                         pages=DEFAULT_RUN_PAGES, n=DEFAULT_RUN_N,
                         delay=DEFAULT_RUN_DELAY)

    for line in reconciliation_lines(stats["channel_meta"]):
        sys.stdout.write("  %s\n" % line)
    counts = stats["pcode_status_counts"]
    sys.stdout.write(
        "  run: 抓取落库 %d 条（%d/%d 频道成功）；新增 %d 条 / 重复 %d 条；"
        "文号 parsed %d / partial %d / unparsed %d；订阅命中 %d 条"
        "（剔除 %d 条 / 零命中 %d 条）；日报 %d 条"
        "%s\n"
        % (stats["kept"], stats["channels_ok"], len(stats["channels"]),
           stats["new_count"], stats["dup_count"],
           counts.get("parsed", 0), counts.get("partial", 0),
           counts.get("unparsed", 0), stats["hit_count"],
           stats["excluded_count"], stats["zero_hit_count"],
           stats["report_item_count"],
           ("；丢弃 %d 条（未过 schema 校验，不进日报）" % stats["report_dropped"])
           if stats["report_dropped"] else ""))
    for path in stats["report_paths"]:
        sys.stdout.write("  已写出 %s\n" % path)
    if stats["degraded"]:
        return 1
    return 0
