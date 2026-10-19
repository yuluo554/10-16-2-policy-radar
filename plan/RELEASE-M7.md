# RELEASE-M7（发布留档，2026-10-20）

> 仓库：https://github.com/yuluo554/10-16-2-policy-radar（public）
> 版本：`0.1.0` → **`0.2.0`**
> tag / Release：`v0.2.0`（`v0.1.0` 保留不动，仍指向 `9b82986`）
> 前次发布留档：`plan/RELEASE-M6.md`

## 一、这一版为什么发 minor

**地板从 Python 3.8 抬到 3.12 是破坏性变更**，按语义化版本必须进 minor，不能当补丁发。

而抬地板本身不是"想升级"，是构建链倒推出来的硬约束 —— 因果链逐环实测：

| # | 事实 | 实测证据 |
|---|---|---|
| 1 | PEP 639 的 `license = "MIT"`（SPDX 字符串）要求 `setuptools>=77` | setuptools 84 下 `WARNINGS: []`；setuptools 75.3.4 下 **硬报错** `configuration error: project.license must be valid exactly by one definition` |
| 2 | setuptools 76.0.0 起自身要求 Python>=3.9 | PyPI JSON：`76.0.0 / 77.0.3 / 78.1.1` 的 `requires_python` 均为 `>=3.9` |
| 3 | 故 py3.8 无法同时满足"SPDX license"与"能构建" | 1 + 2 直接推出 |
| 4 | 3.8/3.9/3.10 均已 EOL | 常识口径；且 CI 原有最高矩阵就是 3.12 |

**若不改 license**：`license = { text = "MIT" }` 的弃用硬期限是 **2027-02-18**
（setuptools 84 实测原文：「By 2027-Feb-18, you need to update your project and remove
deprecated calls or your builds will no longer be supported.」）。
即两条路都通向"必须动"，只是动哪一边。选了"抬地板 + 现代化 license"。

决策留痕：`plan/00-README总览.md` 的 **D30**（明确写"修订 D10"）、D31（数据契约）、D32（测试数对账）。

## 二、改动清单

| 批次 | 内容 | 文件 |
|---|---|---|
| 1 | README「全量测试 99 项绿」→ 实测值；新增**实测收集数**对账守门 | `README.md`、`tests/test_readme_gate.py` |
| 2 | `license` 改 SPDX + `license-files`；`build-system.requires` → `setuptools>=77`；`requires-python` → `>=3.12` | `pyproject.toml` |
| 3 | 数据安装口径从"已知局限"升级为**显式契约 + 3 条安装态门禁** | `README.md`、`tests/test_selftest.py` |
| 4 | CI：`checkout@v5`、`setup-python@v6`、`permissions`、`concurrency`、矩阵收缩为 3.12 两格 | `.github/workflows/ci.yml` |
| 收尾 | 版本 0.2.0 三处一致 + CHANGELOG + 版本守门 | `pyproject.toml`、`src/policy_radar/__init__.py`、`README.md`、`CHANGELOG.md`、`tests/test_readme_gate.py` |

**3.8 表述的处理原则**（刻意区分，不做全线替换）：

- **当前状态文档**同步：`README.md`、`plan/00`、`plan/03`、`plan/04`、`src/policy_radar/__init__.py`。
- **历史里程碑留档不改**：`plan/HANDOFF-M1..M5.md`、`plan/06`（各棒当时的 DoD 数字）、
  `plan/RELEASE-M6.md`、`plan/07`（M3–M5 的历史陈述）。
  **改写它们等于篡改历史记录** —— "M2 当时各 230 项通过"是事实，不能因为现在 339 就改成 339。

## 三、门禁（发布前全量复跑，均在本机 `.venv`，py3.12）

| # | 命令 | 输出 | 退出码 |
|---|---|---|---|
| 1 | `python -m pytest -o addopts="" -q` | `339 passed in 8.75s` | **0** |
| 2 | `python -m pytest -o addopts="" -q --collect-only` | `339 tests collected` | 0 |
| 3 | `policy-radar selftest --data-root data` | `selftest: 9/9 全部通过` | **0** |
| 4 | `policy-radar verify-data --data-root data` | `3 套件全部自洽（比对 119 条）` | **0** |
| 5 | `policy-radar bench --data-root data` | `3 套件全部达标（比对 119 条）` | **0** |
| 6 | `py -3.12 -X utf8 tools/gen_snapshot_pairs.py --check` | （4 份产物逐字节一致） | **0** |
| 7 | `py -3.12 -X utf8 tools/gen_pcode_cases.py --check` | （2 份） | **0** |
| 8 | `py -3.12 -X utf8 tools/gen_subscribe_cases.py --check` | （3 份） | **0** |
| 9 | `py -3.12 -X utf8 tools/gen_truth_manifest.py --check` | （1 份） | **0** |
| 10 | 元数据生成（干净 archive 树 + setuptools 84） | `WARNINGS: []` | — |

## 四、干净环境复验（wheel 真装，不复用开发 `.venv`）

```bash
pip wheel . -w $TEMP/r7 --no-deps
# policy_radar-0.2.0-py3-none-any.whl  75,048 B ／ 22 条目 ／ data 条目 0

py -3.12 -m venv $TEMP/r7v
$TEMP/r7v/Scripts/python.exe -m pip install $TEMP/r7/policy_radar-0.2.0-py3-none-any.whl
```

wheel 内 `METADATA` 实测：

```
Version: 0.2.0
License-Expression: MIT
Requires-Python: >=3.12
License-File: LICENSE
```

装完在**源树外**（cwd = `$TEMP`）逐条实测：

| 命令 | 输出 | 退出码 | 契约期望 |
|---|---|---|---|
| `policy-radar version` | `policy-radar 0.2.0` | 0 | 0 ✅ |
| `policy-radar selftest`（不给 data-root） | `7/9 通过`，含 `data_root_complete` | **1** | 1 ✅ |
| `policy-radar bench`（不给） | 找不到数据根 | **2** | 2 ✅ |
| `policy-radar verify-data`（不给） | 找不到数据根 | **2** | 2 ✅ |
| `selftest --data-root <repo>/data` | `9/9 全部通过` | 0 | 0 ✅ |
| `bench --data-root <repo>/data` | `3 套件全部达标（比对 119 条）` | 0 | 0 ✅ |
| `verify-data --data-root <repo>/data` | `3 套件全部自洽（比对 119 条）` | 0 | 0 ✅ |

→ **数据契约双向成立**：不给数据根按契约降级，给了就全通。

## 五、CI

| 项 | 值 |
|---|---|
| 矩阵 | `{windows-latest, ubuntu-latest} × py3.12`（原 4 格 → 2 格） |
| actions | `actions/checkout@v5`、`actions/setup-python@v6` |
| 权限 | `permissions: contents: read` |
| 并发 | `concurrency: group=ci-<workflow>-<ref>, cancel-in-progress: true` |

**发布前的 CI 证据**（M7 的两个提交，均已 success）：

| 提交 | run id | 结论 |
|---|---|---|
| `8fee6dc`（批次 1–4） | 39303003468 | success，两 job 各 14 steps 全绿 |
| `1c9b6ed`（plan 计数守门） | 39304276774 | success |

## 六、未跑 / 未做（⬜ + 原因）

| 项 | 状态 | 原因 |
|---|---|---|
| 3.8 通道复验 | ⬜ | **有意退役**（本版破坏性变更）。`v0.1.0` 仍保留 3.8 可用 |
| 真网 `run` 端到端 | ⬜ | 本轮只做卫生与契约，未改抓取/编排语义；M6 已实测过（`plan/RELEASE-M6.md`） |
| exe / PyInstaller 打包 | ⬜ | 既定口径不变：首期发布物 = 源码包 + editable 安装 |
| Release 附件 | ⬜ | 本轮拍板"零附件，只写 notes"，与 `v0.1.0` 形态一致；README 未声称附件 |

## 七、诚实口径

- 本文件所有数字均为**本机实测**（命令 + 退出码逐条列出）。
- CI 结论取自 `gh run list`（真 run id）。
- `v0.1.0` 的 tag/Release **未动**（仍指向 `9b82986`）—— 3.8 用户可继续用旧版。
- **发布前的提交顺序是既有事实，须说明**：批次 1–4 与 plan 计数守门由并行会话提交并推送
  （`8fee6dc`、`1c9b6ed`），版本号/CHANGELOG/本留档由本轮提交。
  内容归属的逐条记录留在工作区外的迭代留档（不入库，含本机路径）。
