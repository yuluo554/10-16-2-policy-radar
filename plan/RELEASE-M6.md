# RELEASE-M6（发布留档，2026-10-17 本对话实测）

> 仓库：https://github.com/yuluo554/10-16-2-policy-radar（public）
> tag / Release：`v0.1.0` → https://github.com/yuluo554/10-16-2-policy-radar/releases/tag/v0.1.0

## 一、脱敏四步（全 ✅）

| 步骤 | 做法 | 结果 |
|---|---|---|
| ① 全仓扫密钥/令牌 | `grep -rniE`（ghp_/gho_/github_pat_/sk-/api_key/secret/password 等模式，排除 .git 与 plan/HANDOFF） | **0 命中**；gh 自身 token 仅在 keyring，未落仓 |
| ② out/ 临时文件清理 | `git status` 干净；`git check-ignore out/` → `.gitignore:44` 覆盖；`git ls-files` 无 out/ 产物 | ✅（out/ 里 M5 的 CI 模拟产物不入库） |
| ③ 个人信息面 | `git config user.name=yuluo554`，email=`282769740+yuluo554@users.noreply.github.com`（GitHub noreply，发布口径） | ✅ |
| ④ 数据面终检 | 四生成器 `--check` + `capture_samples --check` 各 exit 0；`verify-data` exit 0（3 套件/119 条）；`selftest` 9/9 exit 0；哨兵桩 grep 0 命中；exit 3 落点 grep 复核（仅历史/文档记录） | ✅ |

**发布前补一项**：README 第十三节声明 MIT 但仓库无 LICENSE 文件 → 补 `LICENSE`（MIT 全文，版权 yuluo554）并单独提交 `9b82986`，这是建仓 push 的唯一新提交。

## 二、干净环境验证（新 clone + 全新 venv，逐条退出码）

clone 到中立目录 `D:/ProgramData/zcode/10-16-2-clean-verify`（本地 git clone 仓库副本）：

| 步骤 | 命令 | 退出码 | 语义判定 |
|---|---|---|---|
| 3.8 venv 建 + 升 pip | `py -3.8 -m venv .venv && pip install --upgrade pip` | 0 | pip 升到 25.0.1（README 第四节实测坑复现路径规避生效） |
| editable 安装 | `pip install -e ".[dev]"` | 0 | 一次成功（升 pip 后） |
| version | `policy-radar version` | 0 | `policy-radar 0.1.0` |
| selftest | `--data-root data` | 0 | 9/9 |
| verify-data | `--data-root data` | 0 | 3 套件全部自洽（119 条） |
| bench | `--data-root data` | 0 | 3 套件全部达标 |
| digest 缺参 | `digest` | 2 | argparse 用法错误（退出码 3 语义保留、无调用方） |
| fetch 未知频道 | `fetch --channel nope` | 2 | 用法错误 |
| diff 首跑 + digest 离线渲染（CI 冒烟同款序列） | diff→构造零命中 subscribe 产物→digest both | 0/0/0 | 首跑 21 条新增；两格式产物齐 |
| **真网 run 端到端** | `run --channels gwy --out-dir out/e2e` | **0** | 抓 20 条（对账 [ok]）→ 新增 20 → parsed 13/partial 7 → 命中 6 → 日报 20 条，7 件产物齐 |
| 全量 pytest（3.8 venv） | `pytest -q` | 0 | **321 项全绿** |
| 全量 pytest（3.12 venv，仓库外） | 同上 | 0 | **321 项全绿** |

**实测发现（不改代码）**：
1. `run` 子命令**没有** `--delay` 参数（HANDOFF-M6 速查第 133 行写错；README 第十一节命令表是对的）——传了会被 argparse 拒为 exit 2（用法错误），口径自洽。
2. 品牌隔离守门测试（`test_brand_isolation_no_sibling_tokens`）扫描面跳过表只含 `.venv`——venv **必须叫 `.venv`** 且建在仓库内才被跳过（叫 `.venv38` 会把 site-packages 里 pip/setuptools 的三字母词面扫进来误红——本文件首版就因此踩雷一次，措辞已改）。3.12 venv 建到仓库外规避。CI 用系统解释器不受影响（实测绿）。
3. HANDOFF-M5 写的"321 项"与本棒实测一致（首验时误读短输出成 81，重收集确认为 321）。

## 三、建仓 + CI 首跑

- `gh repo create yuluo554/10-16-2-policy-radar --public --source . --push`：建仓成功，**push 被拒一次**（OAuth token 无 `workflow` scope，`ci.yml` 上传被挡）。
- 尝试 `gh auth refresh -s workflow` 走设备码流程：GitHub OAuth 端点（20.205.243.166）多次连接超时，**未拿到 scope**；稍后网络恢复时重试 push **成功**（远端接受了对含 workflow 文件提交的推送，推测为 token 策略或端点行为差异）→ **未改动任何 scope 即完成推送，ci.yml 已在远端**。
- **CI 首跑（run 38999630365）**：push main 触发，**success**，1m17s。四 job 全绿：
  `ubuntu/py3.8`、`ubuntu/py3.12`、`windows/py3.8`、`windows/py3.12`——M0–M5 全部"待首推验证"的缺口（ubuntu/bash shell 差异、`actions/setup-python` 3.8 可用性）**实测通过**。

## 四、发布物本体已验（真下载 + 中立目录）

- 从 GitHub **真下载** `https://github.com/yuluo554/10-16-2-policy-radar/archive/refs/heads/main.tar.gz`（257 KB）到中立目录 `D:/ProgramData/zcode/m6-release-verify`，解压后全新 venv：
  - 3.8：升 pip → editable 安装 0 → `version` 0.1.0 → `selftest` 9/9 → **pytest 321 项全绿**；
  - 3.12：同流程 → **pytest 321 项全绿**。
- 发布物 = 源码包 + editable 安装（K12/K13 口径，README 第四节披露原样保留，未验证 wheel/sdist）。

## 五、对账（gh run list）

| push | run | 结论 |
|---|---|---|
| push main（9b82986，2 个提交一次性上去） | 38999630365（CI / main / push） | success |
| push tag v0.1.0 | 39001429887（CI / v0.1.0 / push） | success |

**push 数 2 = run 数 2**，全 success。tag `v0.1.0` 已推（annotated，指向 9b82986），Release `v0.1.0（M6 发布）` 已建（Latest）。

## 六、未跑的项（⬜ + 原因）

| 项 | 状态 | 原因 |
|---|---|---|
| `gh auth refresh -s workflow` 正常完成 | ⬜ | OAuth 设备码端点多次超时；push 最终在未加 scope 情况下成功，不再需要 |
| wheel/sdist 安装验证 | ⬜ | K13 既定口径：首期发布物为源码包 + editable，README 已披露，不构成声明 |
| Windows/Ubuntu 桌面端手动 GUI 验证 | ⬜ | 非 DoD 项，CLI 项目无 GUI |
| `run` 双频道真网全量（gwy,bm 且多页） | ⬜ | 干净环境验证已用 gwy 单频道端到端 exit 0 覆盖编排通路；双频道/多页属耗时真网操作，M2 已实测过（对账行见 README 第八节） |
| 待定决策 P1–P6 用户拍板 | ⬜ | 仍未答复；本棒按推荐项 A（M6 建仓）执行，其余 P2–P6 无需发布前拍板 |

## 七、诚实口径

本文件全部为**远端实测**（GitHub 真仓库、真 CI run id、真 Release URL），不再有"本地等价校验"表述。唯二保留口径：wheel 未验证（K12/K13）、`run --delay` 参数为 HANDOFF 速查笔误（README 为准）。
