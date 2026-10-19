# WRAPUP-M7（收尾，2026-10-20）——发布后卫生棒

## 结论

**M7 发布完成（`0.2.0`），M0–M7 全部里程碑收官。**

- 公开仓库：https://github.com/yuluo554/10-16-2-policy-radar
- 本版发布：tag `v0.2.0` + Release https://github.com/yuluo554/10-16-2-policy-radar/releases/tag/v0.2.0
- 前一版保留：tag/Release `v0.1.0`（→ `9b82986`）**未动**，3.8 用户可继续用旧版
- 逐项证据：见 `plan/RELEASE-M7.md`（未跑项已留 ⬜ 并注明原因）
- 版本号：`policy-radar 0.2.0`（pyproject = `__version__` = README = CHANGELOG 标题节，**四处一致**）

## 本棒（M7）产出清单

| 类别 | 内容 |
|---|---|
| 破坏性变更 | `requires-python` **3.8 → 3.12**；CI 矩阵 **4 格 → 2 格**（ubuntu/windows × 3.12） |
| 元数据 | `license` 改 PEP 639 SPDX 字符串 + `license-files`；`build-system.requires` → `setuptools>=77`（元数据生成 `WARNINGS: []`） |
| 契约 | 非 editable 安装的数据口径从"已知局限"升级为**显式契约**（`selftest` exit 1 / `bench`·`verify-data` exit 2） |
| CI 卫生 | `actions/checkout@v5`、`actions/setup-python@v6`、`permissions: contents: read`、`concurrency`（Node20 弃用注解清零） |
| 守门（新增 13 条） | `test_readme_gate.py` +9（地板/构建下限/矩阵/actions/README 计数/版本三处/CHANGELOG 覆盖）、`test_selftest.py` +4（安装态契约）、`test_plan_count_gate.py` 6 条（plan 计数，独立文件） |
| 文档 | `CHANGELOG.md`（新建）、`plan/RELEASE-M7.md`、`plan/WRAPUP-M7.md`、plan/00 决策 D30–D34 |
| 测试数 | 321（M6）→ **339**（`pytest -o addopts="" -q`，py3.12） |

## 里程碑全览（最终态）

| 里程碑 | 状态 |
|---|---|
| M0 骨架 / M1 数据先行 / M2 抓取 / M3 diff 与解析 / M4 基准 / M5 交付 | ✅（见 HANDOFF-M1…M6 与 plan/06） |
| M6 发布 | ✅（`plan/RELEASE-M6.md`，`v0.1.0`） |
| M7 发布后卫生 | ✅（`plan/RELEASE-M7.md`，`v0.2.0`） |

## 本棒最关键的三条判据（写给下一个维护者）

1. **地板是倒推出来的，不是口味**：PEP 639 的 `license = "MIT"` 要求 `setuptools>=77`，
   而 setuptools 76 起要求 Python>=3.9 → 3.8 通道在"SPDX license"下无解。
   若有人想降回 3.8，`test_build_requires_supports_spdx_license` 会立刻红。
2. **数据契约是双向的**：只验"装了跑不起来"（exit 1/2）不够，还要验"给了 `--data-root` 就跑得通"（exit 0）。
   只钉前一半，日后真有人把 `data/` 打进包，契约会静默失效——所以另有
   `test_no_data_dir_inside_package` 独立钉住"数据在包外"这个前提。
3. **数字要守两类，处理方式相反**：README 的测试数是**当前值**（必须等于实测收集数）；
   `plan/` 里大量数字是**历史快照**（改了就篡改历史）。`test_plan_count_gate.py`
   用"行内显式限定语"区分二者——**加限定语 ≠ 改数字**。

## 遗留事项（不阻塞发布）

1. **`ubuntu-latest` 将迁移到 Ubuntu 26**（2026-10-19 起，GitHub runner 公告）。
   当前不影响结论（job 全 success），但半年内可能需要跟进镜像差异。
2. **Release 零附件**是既定形态（用户拍板），与同系列部分仓（附 wheel + SHA256SUMS）不一致，
   属**已知差异**。README 未承诺附件，不存在自述不符。
3. **`v0.1.0` 的 tag 是 annotated**，`git rev-parse v0.1.0` 返回 tag 对象 `ba82049`，
   其 `^{commit}` 才是 `9b82986`。查 tag 时别把两者当漂移。
4. **`plan/06` 四处诚实口径尾注的「（当时）」是后加的限定语**（数字未改）。
   若未来要求历史文件零改动，需回退这 4 处并同步调整 `test_plan_count_gate.py`。
5. **`plan/00` 的 D33 与 D34** 描述同一件事的两面（判据 / 落点），嫌重复可合并。

## 后续可扩展方向（未立项）

地方政策库频道、部委站点直抓、全文归档、定时任务调度、PyPI 分发、Release 附件
（wheel + sdist + SHA256SUMS）——均在 README「局限」列过的扩展项，未计入首期验收。
