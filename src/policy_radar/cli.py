"""CLI 入口：argparse 子命令、退出码、编码守卫。

- `selftest` / `version` / `verify-data` / `fetch` / `diff` / `parse` / `bench` /
  `digest` / `run` **已实现且可证伪**；
- 骨架期的"未就绪 exit 3"已随 M5 落地 `digest`/`run` **整项退役**：
  `NOT_READY_COMMANDS` 现为**空表**（退出码 3 的语义与常量保留——它是对外契约
  的一部分，README 退出码表已写；`NotReadyError` 保留但不再有调用方）。
  退役史：`fetch`（M2）、`diff`/`parse`（M3）、`bench`（M4）、`digest`/`run`（M5）。
"""

import argparse
import sys

from . import __version__
from .errors import (
    EXIT_OK, EXIT_USAGE, EXIT_NOT_READY, EXIT_EXTERNAL, EXIT_DEGRADED,
    RadarError, NotReadyError, UsageError,
)
from .paths import ENV_DATA_ROOT, find_data_root, missing_subdirs

PROG = "policy-radar"

#: 未就绪子命令 -> 计划落地的里程碑（退出码 3 的提示语，README 退出码表同源）。
#: 全部子命令已随 M5 落地，此表为**空**（K2 退役完成；保留结构供将来扩展，
#: 退出码 3 语义不删——README 退出码表与 tests/test_cli_contract.py 仍锁它）。
NOT_READY_COMMANDS = {}


def _ensure_utf8_stdio():
    """编码守卫（救用户，不救子进程/CI——那两条要显式 `encoding=` 与 `PYTHONUTF8=1`）。

    按 `stream.encoding` 探针决定是否 reconfigure：中文控制台 cp936 保持不动，
    CI 管道 cp1252 时改为 UTF-8，避免中文输出崩 `UnicodeEncodeError`。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        enc = (getattr(stream, "encoding", None) or "").lower()
        if enc.replace("-", "") in ("utf8", "utf8mb4", "cp65001"):
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def build_parser():
    """构建 argparse 解析器（README 指令面守门按本函数反射核对旗标）。"""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="政策文件雷达：本地抓取国务院与部委政策库，快照 diff 检测新发，"
                    "产出可订阅关键词的中文日报。",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("version", help="打印版本号")

    p_self = sub.add_parser("selftest", help="自检（可证伪：数据根不完整即非 0）")
    p_self.add_argument("--data-root", default=None,
                        help="数据根目录（默认自动发现；测试/演示须显式传）")

    p_verify = sub.add_parser("verify-data",
                              help="[M1] 数据自审：真值台账一致性核对（实算观测 vs 期望）")
    p_verify.add_argument("--data-root", default=None,
                          help="数据根目录（默认自动发现；测试/演示须显式传）")

    p_fetch = sub.add_parser("fetch", help="[M2] 双源抓取（统一 schema + totalCount 对账）")
    p_fetch.add_argument("--channel", action="append", choices=["gwy", "bm"],
                         default=None,
                         help="频道，可重复（默认两频道 gwy+bm，同进程串行抓取）")
    p_fetch.add_argument("--pages", type=int, default=1, help="每频道抓取页数")
    p_fetch.add_argument("--n", type=int, default=20, help="每页条数")
    p_fetch.add_argument("--delay", type=float, default=1.5, help="逐请求抓取间延时（秒）")
    p_fetch.add_argument("--out", default=None, help="输出路径（默认 out/fetched.json）")

    p_diff = sub.add_parser("diff", help="[M3] 快照 diff：新增/重复判定（id/pcode 双键）")
    p_diff.add_argument("--snapshot", default=None,
                        help="上次快照文件（省略 = 首次运行，全部计入新增；"
                             "给了路径但读不到即报错，不静默当首跑）")
    p_diff.add_argument("--current", required=True,
                        help="本次条目文件（fetch 产物 / 快照 / diff 产物）")
    p_diff.add_argument("--out", default=None, help="diff 产物路径（默认 out/diff.json）")
    p_diff.add_argument("--snapshot-out", default=None,
                        help="更新后的快照路径（默认 out/snapshot.json）")

    p_parse = sub.add_parser("parse", help="[M3] 文号三态解析 + 部门归一")
    p_parse.add_argument("--input", required=True,
                         help="条目文件（fetch 产物 / 快照 / diff 产物）")
    p_parse.add_argument("--out", default=None, help="解析产物路径（默认 out/parsed.json）")
    p_parse.add_argument("--data-root", default=None,
                         help="数据根目录（部门别名表在 data/config/ 下；默认自动发现）")

    p_digest = sub.add_parser("digest",
                              help="[M5] 中文日报生成：新增条目 + 订阅命中 → Markdown/HTML")
    p_digest.add_argument("--new-items", required=True,
                          help="新增清单（diff 产物，规范序）")
    p_digest.add_argument("--hits", required=True,
                          help="订阅命中产物（run 编排 / load_subscribe_hits 产出）")
    p_digest.add_argument("--parse", default=None,
                          help="解析产物（可选；缺了文号/部门渲染「未提供」）")
    p_digest.add_argument("--out", default=None,
                          help="输出路径（md/html 单文件；both 时作为主干派生两格式，默认 out/report.md + out/report.html）")
    p_digest.add_argument("--format", choices=["md", "html", "both"], default="both",
                          help="日报格式（默认 both 双格式）")

    p_run = sub.add_parser("run",
                           help="[M5] 端到端编排：抓取->diff->解析->订阅->日报（一条命令出结果）")
    p_run.add_argument("--channels", default=None,
                       help="频道，逗号分隔（默认 gwy,bm）")
    p_run.add_argument("--out-dir", default=None,
                       help="产物目录（中间产物与日报都写这里；默认 out/）")
    p_run.add_argument("--snapshot", default=None,
                       help="上次快照文件（省略 = 首次运行，全部计入新增；给了路径但读不到即报错）")
    p_run.add_argument("--data-root", default=None,
                       help="数据根目录（订阅配置/归一表/别名表在 data/config/ 下；默认自动发现）")

    p_bench = sub.add_parser("bench", help="[M4] 真值基准：三套件一键跑通（生产实现实算 + 门槛判定）")
    p_bench.add_argument("--only", default=None, help="只跑指定套件（diff/pcode/subscribe）")
    p_bench.add_argument("--data-root", default=None,
                         help="数据根目录（真值与门槛在 data/truth/ 下；默认自动发现）")

    return parser


def cmd_version(_args):
    sys.stdout.write("%s %s\n" % (PROG, __version__))
    return EXIT_OK


def cmd_selftest(args):
    """自检：真跑断言，任一不成立即 exit 1（防"恒 True 空壳"）。

    阴性对照（tests/test_selftest.py 锁死）：把 `--data-root` 指向空目录必须返回非 0。
    """
    from .model import SCHEMA_FIELDS, REQUIRED_FIELDS, CHANNELS
    from .errors import ALL_EXIT_CODES

    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    check("package_importable", bool(__version__), "version=%s" % __version__)

    try:
        import policy_radar
        mod_ver = getattr(policy_radar, "__version__", "")
        check("version_consistent", mod_ver == __version__, "module=%s" % mod_ver)
    except ImportError as exc:  # pragma: no cover - 包自身导入失败
        check("version_consistent", False, str(exc))

    check("exit_codes_complete", len(ALL_EXIT_CODES) == 5, "codes=%r" % (ALL_EXIT_CODES,))
    check("schema_fields_complete", len(SCHEMA_FIELDS) == 10,
          "fields=%d" % len(SCHEMA_FIELDS))
    check("required_fields_subset", set(REQUIRED_FIELDS) <= set(SCHEMA_FIELDS),
          "required=%d" % len(REQUIRED_FIELDS))
    check("channels_complete", set(CHANNELS) == {"gwy", "bm"}, "channels=%r" % (sorted(CHANNELS),))

    data_root = find_data_root(args.data_root)
    missing = missing_subdirs(data_root)
    check("data_root_found", data_root is not None, "root=%s" % data_root)
    check("data_root_complete", not missing, "missing=%r" % (missing,))

    # 序列化单点可写（在数据根下写临时文件再删；失败即自检不通过）。
    try:
        import os
        import tempfile
        from .serialize import write_json, read_json, dumps_json
        fd, probe = tempfile.mkstemp(prefix=".selftest-", suffix=".json")
        os.close(fd)
        write_json(probe, {"probe": "政策", "n": 1})
        back = read_json(probe)
        ok = back == {"probe": "政策", "n": 1} and "\\u" not in dumps_json(back)
        os.unlink(probe)
        check("serialize_roundtrip", ok, "ensure_ascii=False 中文未转义")
    except (IOError, OSError, ValueError) as exc:
        check("serialize_roundtrip", False, str(exc))

    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        sys.stdout.write("  [%s] %s%s\n" % ("OK" if ok else "FAIL", name,
                                            ("  " + detail) if detail else ""))
    if failed:
        sys.stdout.write("selftest: %d/%d 通过，%d 项失败\n"
                         % (len(checks) - len(failed), len(checks), len(failed)))
        return EXIT_DEGRADED
    sys.stdout.write("selftest: %d/%d 全部通过\n" % (len(checks), len(checks)))
    return EXIT_OK


def _not_ready(command):
    """未就绪子命令：显式拒绝，不伪造空结果。"""
    milestone = NOT_READY_COMMANDS.get(command, "后续里程碑")
    sys.stderr.write(
        "%s: 子命令 `%s` 尚未就绪（计划里程碑：%s）。\n"
        "本骨架期不产出空结果；请见 plan/06-里程碑.md。\n" % (PROG, command, milestone)
    )
    return EXIT_NOT_READY


def main(argv=None):
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return EXIT_USAGE

    if args.command == "version":
        return cmd_version(args)
    if args.command == "selftest":
        return cmd_selftest(args)
    if args.command == "verify-data":
        from .verify import cmd_verify_data
        return cmd_verify_data(args)
    if args.command == "fetch":
        from .fetch import cmd_fetch
        return cmd_fetch(args)
    if args.command == "diff":
        from .snapshot import cmd_diff
        return cmd_diff(args)
    if args.command == "parse":
        from .parse import cmd_parse
        return cmd_parse(args)
    if args.command == "bench":
        from .bench import cmd_bench
        return cmd_bench(args)
    if args.command == "digest":
        from .report import cmd_digest
        return cmd_digest(args)
    if args.command == "run":
        from .pipeline import cmd_run
        return cmd_run(args)
    if args.command in NOT_READY_COMMANDS:
        return _not_ready(args.command)

    # 未知子命令由 argparse choices 拦截（子解析器已注册全部命令）。
    sys.stderr.write("%s: 未知子命令 `%s`\n" % (PROG, args.command))
    return EXIT_USAGE


def main_guarded(argv=None):
    """带异常兜底的入口：领域异常 -> 既定退出码；其余 -> exit 2 并打印一行错误。

    不把 `except` 扩成裸 `Exception`（那会把真 bug 也吞成"输入错误"）——只兜领域异常
    与 ValueError（本领域异常均继承 ValueError）。
    """
    _ensure_utf8_stdio()
    try:
        return main(argv)
    except RadarError as exc:
        sys.stderr.write("%s: %s\n" % (PROG, exc.message))
        return exc.code
    except ValueError as exc:
        sys.stderr.write("%s: 输入不可用：%s\n" % (PROG, exc))
        return EXIT_USAGE
    except KeyboardInterrupt:  # pragma: no cover
        sys.stderr.write("%s: 已中断\n" % PROG)
        return EXIT_DEGRADED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main_guarded())
