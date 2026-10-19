# CHANGELOG

本文件记录每次**发版**的对外可见变更。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)、
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 判据纪律：**破坏性变更必须写在 `### Changed` 或独立的 `### Breaking` 段里并点名**，
> 不许只改版本号不写改动（`tests/test_readme_gate.py` 的
> `test_changelog_exists_and_covers_current_version` 会拦"当前版本没有标题节"这种情况）。

---

## [0.2.0] — 2026-10-20（M7：发布后卫生与契约）

### Breaking

- **Python 底线 3.8 → 3.12**（`requires-python = ">=3.12"`）。**3.8 用户无法再安装本版本。**
  - 原因不是口味选择，是构建链倒推出来的硬约束：`license` 改用 PEP 639 的 SPDX 字符串
    （`license = "MIT"`）要求 `setuptools>=77`；而 setuptools 76.0.0 起自身要求 Python>=3.9，
    py3.8 能装到的最后一版 75.x 遇到 SPDX 字符串会**直接报配置错误**
    （`project.license` must be valid exactly by one definition，不是警告）。
  - 3.8 / 3.9 / 3.10 均已 EOL，故对齐到 CI 原有最高矩阵 3.12。
  - CI 矩阵随之从 `{ubuntu,windows} × {3.8,3.12}`（4 格）收缩为 `{ubuntu,windows} × 3.12`（2 格）。
  - 决策留痕：`plan/00-README总览.md` 的 D30（明确写"修订 D10"）。

### Changed

- **license 元数据现代化（PEP 639）**：`license = { text = "MIT" }` → `license = "MIT"` +
  `license-files = ["LICENSE"]`；`build-system.requires` 抬到 `setuptools>=77`。
  元数据生成从 `SetuptoolsDeprecationWarning`（硬期限 2027-02-18）变为**零 warning**。
  wheel 元数据显示 `License-Expression: MIT`。
- **README 的测试数改为实测值并对账**：原「全量测试 99 项绿」是 M0 期的陈旧陈述
  （`git log -S"99 项绿"` → 那句话是 M0 收尾写的，M1–M5 加了 222 项测试却没跟着改）。
  现由 `tests/test_readme_gate.py` 真跑 `pytest --collect-only` 与 README 声明的数字对账。
- **非 editable 安装的数据口径升级为显式契约**（原为"已知局限"）：
  wheel/sdist 安装只提供 CLI 与解析能力，数据相关命令须显式 `--data-root`；
  不给则 `selftest` exit 1（点名 `data_root_complete missing=[...]`）、
  `bench` / `verify-data` exit 2。由 `tests/test_selftest.py` 三条守门钉住。
- **CI 卫生**：`actions/checkout@v4`→`@v5`、`actions/setup-python@v5`→`@v6`；
  新增 `permissions: contents: read`（最小权限）与 `concurrency`（同 ref 取消旧运行）。
- **生成器命令**：README 里的 `py -3.8 -X utf8` → `py -3.12 -X utf8`。

### Added

- `CHANGELOG.md`（本文件）。
- `tests/test_readme_gate.py` 新增守门：
  - README 声明的测试数 == 实测收集数（含"恰好一处声明"的自证）；
  - 解释器地板三处一致（pyproject / README / CI 矩阵，版本号按数值比较）；
  - `license = "MIT"` 与 `setuptools>=77` 的**因果链**（单独看任一处都发现不了不兼容）；
  - CI actions 大版本不回退、permissions/concurrency 存在；
  - 版本号三处一致（pyproject / `__init__` / README）+ CHANGELOG 覆盖当前版本。
- `tests/test_selftest.py` 新增三条**安装态契约**守门（把包复制到源树外跑 CLI，
  等价于安装态 `sys.path` 布局）：`selftest` exit 1 且点名缺失项、`bench`/`verify-data` exit 2、
  包内不得出现 `data/`（钉住前提，防前两条假绿）。
- `tests/test_plan_count_gate.py`（新文件，6 条）：**`plan/` 的测试数与实测收集数对账**。
  只钉"当前口径"、**不动历史快照**——带"当时 / 本对话实测 / 尾注（M<n>）"等**行内显式限定语**
  的段落按历史豁免（M1 171 / M2 230 / M4 287 / M5–M6 307→321 因此原样保留），
  其余断言等于 `pytest --collect-only` 的实测值。另含**扫描面自证**（聚合口径命中 <10 即红），
  防措辞改动导致零命中假绿。**词表用 5 条负控校准**：初版把"已退役"当历史限定语，
  使 `plan/07` 的当前值"99 项绿（3.8 通道已退役）"静默逃逸；已改为按行判断并收紧词表。
- `plan/00-README总览.md` 新增决策 D30（地板）、D31（数据契约）、D32（README 测试数对账）、
  D33（plan/ 测试数对账，且不篡改历史）、D34（权威数字落 `plan/00`「测试数口径」一节）。

### 未变（口径明确）

- **运行时仍零第三方依赖**（仅 stdlib）；`dev` 仍是唯一 extras（仅 pytest）。
- **冻结数据字节未动**：`data/snapshots`、`data/truth`、`data/samples`、`data/config`。
- **对账语义未动**：`verify-data` 与 `bench` 共用同一份语义；`data/truth/manifest.json` 的
  `thresholds` 未改；`src/policy_radar/cases.py`（参照实现）未改。
- **退出码语义未动**：0/1/2/3/4 五档含义与 `v0.1.0` 一致。
- **发布物形态未变**：源码包 + `pip install -e ".[dev]"`；不含 exe。

---

## [0.1.0] — 2026-10-17（M6 首次发布）

- 首个公开版本：M0–M6 全部里程碑收官。
- 形态：纯本地 Python CLI，运行时零第三方依赖；Python 底线 **3.8**。
- 数据源：中国政府网搜索 API 两个公开频道（国务院政策库 + 部委政策库）。
- 命令：`version` / `selftest` / `verify-data` / `fetch` / `diff` / `parse` / `bench` / `digest` / `run`。
- 发布留档：`plan/RELEASE-M6.md`、`plan/WRAPUP-M6.md`。
- 已知局限（原样披露于 README 第三节）：日期过滤参数未生效、gov.cn 旧路径 404、
  部委 `index` 字段全空、只接两个频道、只存元数据不抓正文、真值基准为抽样覆盖。
