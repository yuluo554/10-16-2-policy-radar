# HANDOFF-M1：交接给"数据先行"里程碑

> 用法（新对话启动命令，用户侧拼绝对路径）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M1.md" 继续完成任务`
> 上一棒：**M0 计划先行 + 可运行骨架**（本对话完成）
> 下一棒：**M1 数据先行**（预置快照对 + 真值台账 + 真实 API 样本 + 三个生成器）

---

## 一、当前进度 + 证据（本对话实测）

### 已完成

| 项 | 证据 |
|---|---|
| `plan/00–07` 全套计划文档 | 文件存在；00 含决策记录 D1–D15、待定决策表 P1–P6、M0 实测勘误 E1–E4 |
| 可运行骨架（`src/policy_radar/` 7 个模块） | `py -3.8 -X utf8 -m policy_radar selftest --data-root data` → **exit 0**，9 项全 OK |
| 未就绪子命令 exit 3 契约 | `python -m policy_radar fetch` → **exit 3**（stderr 写明"M2 双源抓取"） |
| `selftest` 可证伪 | 空数据根 → **exit 1**（`tests/test_selftest.py` 阴性对照 + 变异验证） |
| 测试套件 | 3.8 与 3.12 **双解释器全绿**（各 **101 项**收集，同数；命令见第五节） |
| CI workflow 预置 | `.github/workflows/ci.yml` 四矩阵（win/ubuntu × 3.8/3.12）+ `PYTHONUTF8=1` + pip 升级前置 |
| `data/` 四类目录 + README | `config/ snapshots/ truth/ samples/` 各带 README；`data/README.md` 含 M0 勘误 |
| **干净环境验证（新 clone + 全新 venv 3.8）** | 按 README 逐条跑通：pip 升级 → `pip install -e ".[dev]"` → `pytest` **101 项绿** → CLI 冒烟 |
| **实测抓出并修复的真缺陷 ①** | `.gitignore` 未锚定的 `snapshots/` 会连 `data/snapshots/`（冻结 fixtures）一起忽略 → 改为锚定 `/snapshots/` + `/out/` + `/reports/*.html`；新增 `tests/test_repo_hygiene.py` 守门（含反向断言"运行时目录仍被忽略"） |
| **实测抓出并修复的真缺陷 ②** | **Python 3.8 全新 venv 自带 pip 20.2.3 不支持 PEP 660** → 直接 `pip install -e .` 报 `editable mode currently requires a setup.py based build`。修复 = README 快速开始与 CI 都先 `python -m pip install --upgrade pip`；新增守门断言"升级行必须在 editable 安装行**之前**"（顺序反了同样装不上） |

### M0 实测勘误（**对题面的四处修正，已同步 `data/README.md`**）

| # | 原说法 | 实测（2026-10-17） | 影响 |
|---|---|---|---|
| E1 | 部委库 `total=12801` | `searchVO.totalCount=12803` | 正常漂移；**代码/测试不得内嵌该数** |
| E2 | 字段"与 API 实测字段一一对应"（未指明取数路径） | 条目在 **`searchVO.listVO`**，顶层 `data` 为 `null` | `model.items_from_listvo()` 已按此实现 |
| E3 | 去重"同 `index` 或同 `pcode`" | 部委 `index` **30/30 为空** | 主键改 `id`（决策 D12），`index` 降副键 |
| E4 | 文号如"国办发〔2026〕28 号" | 实采**六形态**（含 `国令第847号` 无年份、`国知发服字`/`工信部联规函` 多字代字）；`pcode` 可空（部委 3/30）；`fwzh`/`wenhao`/`wjlx` **60/60 全空** | 解析器需支持六形态 + 三态 |

### 诚实口径（**无远端，CI 从未跑过**）

- 全程**没有远端**、**一次 CI 都没跑过** → 凡 CI 类判据一律写"**本地等价校验（未接远端，CI 待首推验证）**"，**不写"CI 绿"**。
- 本机可实跑的等价物清单：① 双解释器（3.8.8 + 3.12.10）pytest 全量；② `selftest` 阳性/阴性对照；③ CLI 退出码契约（子进程真跑，不是函数断言）；④ 序列化双跑逐字节一致。
- **不可本机实跑的缺口**：CI 矩阵的 ubuntu/Windows 环境差异、`actions/setup-python` 的 3.8 可用性 → **待首推验证**。M6 首推后据实补记真实 run id（补记是追加事实，不改写历史措辞）。

---

## 二、下一棒（M1）待办

按 `plan/05-数据计划.md` 第六节执行，**顺序建议如下**（先真数据、再生成器、最后守门）：

1. **真跑一次真实 API，落 `data/samples/`**：`gwy-p1-n5.json` + `bm-p1-n5.json`（完整 URL、抓取日期、HTTP 状态、sha256 记进 `data/samples/README.md`）。**逐页加延时**（≥1.5s）。
2. `tools/gen_snapshot_pairs.py`：合成快照对 + **独立朴素 oracle** + 生成守卫 + `--check`（**两层**位级守门）。
   - 必须覆盖五类形态：应判新增 / 应判重复（id 键）/ **应判重复（pcode 键）** / 边界（pcode 空 + id 新）/ 边界（pcode 空 + id 同）。
3. `tools/gen_pcode_cases.py`：文号样本集（覆盖实测六形态）+ 期望结构 + **反向样例**（`国令第847号` 无年份、空 pcode 无代字）。
4. `tools/gen_subscribe_cases.py`：订阅配置样例（多词 / 排除词 / 重复词）+ 命中真值（含"命中 0 次""只命中 exclude"边界样本）。
5. `data/truth/README.md`：真值语义一次定清（`expect` + `also_expect`；对账语义单一实现源）。
6. `data/snapshots/manifest.json` + 逐份 sha256 + **门槛**（随数据下发，代码零默认值）。
7. 守门测试：`--check` 位级一致（两层）+ 真值无 `observed` 字段 + **真值库有真调用方**（不是"文件存在"）。
8. 真实 API 样本的**离线回归**测试（不打真站点；用冻结样本喂 `model.items_from_listvo()`）。
9. DoD 逐项验证 → 回写 `plan/00`/`06` 状态 → **写 `plan/HANDOFF-M2.md`** → commit。

**M1 的 DoD 全文见 `plan/06-里程碑.md` 的 M1 节（9 项）。**

---

## 三、既定口径清单（K 编号，"动了会打挂测试"的约定）

**改任何一条前先对照本表，改完重跑全量测试 + `--check` 确认不回退。**

| K | 口径 | 落点（单点） | 守卫 |
|---|---|---|---|
| K1 | 统一 schema 字段集合与**顺序** = `SCHEMA_FIELDS` 十项 | `src/policy_radar/model.py` | `tests/test_model.py::test_schema_fields_exact_and_ordered` |
| K2 | 退出码语义 `0/1/2/3/4`；**3 退役走四处同步**（常量/CLI+测试/README/决策记录） | `src/policy_radar/errors.py` | `tests/test_cli_contract.py` |
| K3 | 序列化冻结参数：`sort_keys=True, ensure_ascii=False, indent=2` + **LF** + **结尾恰好一个换行** + 原子写 | `src/policy_radar/serialize.py` | `tests/test_serialize.py`（含"写盘单点"源码扫描） |
| K4 | 去重主键 = **`id`**；`index` 副键；`pcode` 非空时并入判定 | `snapshot.py`（M3 新建） | M3 测试 |
| K5 | 清单排序键 = `(pubtimeStr 倒序, id 升序)`，**全程不读时钟** | `snapshot.py` / `report.py` 共用 | M3/M5 测试 |
| K6 | 文号解析三态 `parsed/partial/unparsed`；**代字不做白名单硬编码**（实测有 `国知发服字` 类） | `parse.py`（M3 新建） | M3 测试 |
| K7 | 部门别名表**单一来源** `data/config/org-aliases.json`；**最长优先匹配** | `parse.py` | M3 测试 |
| K8 | 订阅匹配 = 子串包含 + 全半角归一；**exclude 命中整条剔除**；同词去重 | `subscribe.py`（M4 新建） | M4 测试 |
| K9 | 渲染层**零判定** + 渲染出口**常驻零外链断言** | `report.py`（M5 新建） | M5 测试（AST 守门） |
| K10 | 快照字段白名单（**无全文**）；出现 `content/body/fulltext` 即红 | `snapshot.py` + `model.FORBIDDEN_SNAPSHOT_FIELDS` | M3 测试 |
| K11 | 真值库**只存输入与期望**，禁 `observed_*`；观测由基准运行时实算 | `data/truth/` | M1 守门测试 |
| K12 | 无 LLM、**零第三方运行时依赖**、**3.8 语法底线** | 全仓 | `test_readme_gate.py` 测试面/安装面 |
| K13 | 数据根定位优先级：**显式参数 > 环境变量 `POLICY_RADAR_DATA` > 源码树相对** | `src/policy_radar/paths.py` | `tests/test_selftest.py`（测试**显式传** `--data-root`） |

---

## 四、本机环境坑（**只写实测过的**）

1. **用 `py` 不是 `python`**（后者可能是商店占位符）；跑脚本一律 `py -X utf8`（中文控制台编码）。
2. **本机双通道**：`py -0p` 实测有 **3.8.8-64** 与 **3.12.10-64**；两条都装了 pytest（3.8 → 7.4.4，3.12 → 8.4.2）。**项目底线 3.8**，所有代码只用 3.8 语法。
3. **`/tmp` 与 Windows Python 路径不通**：Git Bash 的 `/tmp` 下写文件，`py -3.8` 读不到（实测 `FileNotFoundError: '/tmp/gwy.json'`）。**临时文件一律用工作区相对路径**。
4. **pytest 计数当轮实测**：M0 实测 `tests/` 收集 **101 项**（3.8 与 3.12 **同数**，均 101）。**别抄上一棒的数字**（skill 实录：计数抄写链会漂）。
5. **写盘 API 3.8 差异**：`Path.write_text(newline=)` 是 **3.10+** 参数 → 用 `open(..., newline="\n")` 或 `write_bytes`（本项目走 `serialize.py` 的 `os.fdopen(fd,"wb")`）。
6. **`PYTHONDONTWRITEBYTECODE=1`**：pyc 偶发损坏会导致"unknown opcode / 随机 FAIL / 测试数波动"；出怪错先清 `__pycache__` 再跑。
7. **编码三加固已就位**（别在后续里程碑拆掉）：① 入口 `_ensure_utf8_stdio()`（按 `stream.encoding` 探针，救用户）；② 子进程调用一律显式 `encoding=`（救一切环境）；③ CI `env: PYTHONUTF8=1`（救 CI 全部步骤）。**本机加 `-X utf8` 只证明"我们敲的那条命令"没编码问题**。
8. **网络类操作必带超时**：M0 实测 `curl -m 20` 对 API 正常；`sleep 2~3` 间隔逐页抓取（平台礼仪）。
9. **CI 未实跑**：本机模拟不了 ubuntu/Windows 矩阵 → **预算"首推至少一轮诊断"**；修 CI 配置与测试环境依赖**不算动内核**。

---

## 五、关键命令速查

```bash
# --- 测试（双解释器，全量） ---
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q

# --- 单文件跑 ---
py -3.8 -X utf8 -m pytest -q tests/test_selftest.py

# --- CLI 冒烟（两条通路都要跑） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar version
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar selftest --data-root data   # 期望 exit 0
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar selftest --data-root /nonexistent  # 期望 exit 1
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch                        # 期望 exit 3

# --- 退出码断言（Git Bash 里取 $?） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch; echo "exit=$?"

# --- 干净环境（M6 用；M0 未跑） ---
py -3.8 -m venv .venv && ./.venv/Scripts/python.exe -m pip install -e ".[dev]"

# --- 真实 API 探测（M1 用；逐页加延时） ---
curl -s -m 20 "https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_gwy&q=&p=1&n=5&sort=pubtime&sortType=1" -o data/samples/gwy-p1-n5.json
sleep 3
curl -s -m 20 "https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_bm&q=&p=1&n=5&sort=pubtime&sortType=1" -o data/samples/bm-p1-n5.json

# --- 哨兵桩排查（收尾期固定动作） ---
# 注意：`tests/test_readme_gate.py` 自身含这三个 token（它就是探测器），扫 tests/ 时会命中它自己。
# 判据 = `src/` 与 `tools/` 下 0 命中；M0 实测 src/ 干净。
grep -rn "NotImplementedError\|TODO: 实现\|placeholder" src/ tools/
```

---

## 六、DoD 逐项 checklist（M0）

| # | 判据 | 验证方式（**在哪验的**） | 状态 |
|---|---|---|---|
| 1 | plan/00–07 齐备，含边界与非目标 + 待定决策表 | 文件存在 + 用户拍板 | ✅ |
| 2 | CLI 可跑：`--help` / `version` / `selftest` / 未就绪子命令 exit 3 | 子进程实测退出码（`tests/test_cli_contract.py`） | ✅ |
| 3 | `selftest` **可证伪**（空数据根必须非 0） | `tests/test_selftest.py` 阴性对照 + 2 项变异验证 | ✅ |
| 4 | 退出码常量齐备且锁进测试 | `tests/test_cli_contract.py` | ✅ |
| 5 | 序列化单点：双跑逐字节一致 | `tests/test_serialize.py` | ✅ |
| 6 | 双解释器（3.8 + 3.12）pytest 全量绿 | 两条命令 exit 0；各收集 **101 项**（同数，本对话实测） | ✅ |
| 7 | README 指令面可执行（路径存在 + 模块可执行） | `tests/test_readme_gate.py`（反射核对，非子串断言） | ✅ |
| 8 | CI workflow 预置（**未接远端，待首推验证**） | 文件存在 + `PYTHONUTF8`/`pytest` 结构断言 | ✅（**本地等价校验，未接远端，CI 待首推验证**） |
| 9 | HANDOFF-M1 落盘 | 本文件 | ✅ |
| 10 | 无临时产物入库 | `git status` 干净（`.scratch/` 已清） | ✅ |

**偏差说明**：无。第 8 项按诚实口径写"本地等价校验，未接远端，CI 待首推验证"——**不是"CI 绿"**。

---

## 七、续接指针

- **本棒产出**：`plan/00–07`、`README.md`、`pyproject.toml`、`.gitattributes`、`.gitignore`（已修锚定缺陷）、`.github/workflows/ci.yml`、`src/policy_radar/`（7 模块）、`tests/`（6 文件，101 项）、`data/`（四目录 + 5 份 README）。
- **下一棒入口**：`plan/05-数据计划.md` 第六节（M1 待办）+ 本文件第二节。
- **下一棒出口**：`plan/HANDOFF-M2.md`（六节，**先落盘再结束对话**）。
- **待用户拍板**：`plan/00-README总览.md` 的待定决策表 P1–P6（未答复则按推荐项 A 执行并如实记"按推荐默认执行"）。
