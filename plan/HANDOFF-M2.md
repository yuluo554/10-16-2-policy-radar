# HANDOFF-M2：交接给"抓取"里程碑

> 用法（新对话启动命令，用户侧拼绝对路径）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M2.md" 继续完成任务`
> 上一棒：**M1 数据先行**（本对话完成）
> 下一棒：**M2 抓取**（双源抓取 + 统一 schema + 限频/超时/重试 + totalCount 对账）

---

## 一、当前进度 + 证据（本对话实测）

### 已完成

| 项 | 证据 |
|---|---|
| **真实 API 样本 4 份入仓** | `data/samples/`：`gwy-p1-n5.json`（22698 B, sha256 `cd583632f597…`）、`bm-p1-n5.json`（25276 B, `21b1ed4e94c6…`）、`gwy-p1-n30.json`（69097 B, `e403d43bb530…`）、`bm-p1-n30.json`（74581 B, `41e9a8420b1b…`）；全 HTTP 200，抓取日 2026-10-17 |
| **样本登记表（机器可读）** | `data/samples/manifest.json`：逐份记 URL / 抓取日期 / HTTP 状态 / 字节数 / sha256 / `totalCount` / 样本内条数；`tools/capture_samples.py --check` → exit 0 |
| **抓取工具** | `tools/capture_samples.py`：只用 stdlib `urllib`，逐请求延时（默认 3s）、超时 20s、重试 2 次；**落原始响应字节**（不重新序列化）；结构性断言取数路径 |
| **预置快照对 + 两层位级守门** | `data/snapshots/pair-A.json`（20 条）/ `pair-B.json`（21 条）/ `manifest.json`；`tools/gen_snapshot_pairs.py --check` → **exit 0（两层均 OK）** |
| **快照对五形态覆盖** | `carried` 13 / `fresh` 5 / `pcode_dup` 1 / `empty_pcode_new` 1 / `empty_pcode_same` 1（逐类 ≥1，`role_counts` 登记） |
| **diff 真值** | `data/truth/diff-truth.json`：应判新增 **6** 条 / 应判重复 **15** 条；`matched_by` 逐条登记命中键（含 1 条 `pcode` 键命中） |
| **文号解析真值** | `data/truth/pcode-truth.json`：人工标注 **11** 条 + 观测池语料 **57** 条真实文号；形态 `std_bracket` 54 / `fullwidth_bracket` 2 / `std_bracket_spaced_serial` 2 / `decree_no_bracket` 9 / `empty` 1 |
| **订阅命中真值** | `data/truth/subscribe-truth.json`：命中 32 条（覆盖 13 个条目）/ 剔除 3 条 / 0 命中 5 条；六类边界形态逐类 ≥1 |
| **规则数据 3 份** | `data/config/org-aliases.json`（39 原始名 → 38 规范名，含唯一真变体对）、`subscribe.json`（含重复词）、`normalize.json`（长度保持归一表） |
| **真值总清单** | `data/truth/manifest.json`：覆盖声明（**规则包总数/采样数/采样清单三登记** + "抽样覆盖、非穷举"声明）+ **验收门槛**（随数据下发） |
| **参照实现 + 对账语义（包内单点）** | `src/policy_radar/cases.py`：`naive_diff` / `naive_parse_pcode` / `naive_match`（**不用正则、双重循环**）+ `compare_diff` / `compare_pcode` / `compare_subscribe`（**逐条点名差异**）+ `find_observed_fields` |
| **真值台账的真调用方** | `src/policy_radar/verify.py` + CLI `verify-data`：`policy-radar verify-data --data-root data` → **exit 0，3 套件全部自洽（比对 119 条）** |
| **`verify-data` 可证伪（实测两项）** | ① 删一条 `new_ids` → 报 `new_ids 多出：['26782365']`、exit 1；② 注入 `observed_hits` → 报 K11 违规、exit 1 |
| **四生成器 `--check` 全绿** | `gen_snapshot_pairs` / `gen_pcode_cases` / `gen_subscribe_cases` / `gen_truth_manifest` 各 **exit 0**（两层） |
| **测试套件** | **171 项**（3.8 与 3.12 **同数**），双解释器全绿；新增 4 个测试文件（truth_gate / generators_check / cases_independence / samples_regression） |
| **CLI 契约未回退** | `selftest --data-root data` → exit 0（9/9）；空数据根 → exit 1；`fetch` → exit 3 |

### M1 实测勘误（**对 M0 台账的三处新增修正，已同步 `data/README.md`**）

| # | M0 未记录的事实 | 实测证据 | 影响 |
|---|---|---|---|
| E5 | **`puborg` 分隔符不止 U+0020**：含 **U+2002 EN SPACE**，且**同一条内混用**两种空格 | `中国人民银行␂金融监管总局␂…`（8 部门全 U+2002）；`商务部␂…工业和信息化部␠民政部␂…`（同串混用） | 只按 `' '` 拆分 → 多部门串变成**单个不可识别 token**；必须按 `\s` 类空白拆分 |
| E6 | **文号括号有全角 `﹝﹞` 变体**：U+FE5D/U+FE5E，与 `〔〕` 的 U+3014/U+3015 **不同码位** | `工信部联规﹝2026﹞210号` | 按 `〔〕` 硬匹配 → 该条被判 `unparsed`（真实发文被误判"未解析"） |
| E7 | **序号与"号"之间可出现空格** | `农农发〔2026〕9 号` | 序号抽取须容忍空白（`9` 而非 `9 `） |

> M0 的四条勘误 E1–E4 在 M1 复测中**全部复现**：`bm` 的 `totalCount` 仍为 12803、条目仍在 `searchVO.listVO`（顶层 `data` 为 null）、部委 `index` 30/30 空、`pcode` 3/30 空、`fwzh/wenhao/wjlx` 60/60 全空。

### 诚实口径（**无远端，CI 从未跑过**）

- 全程**没有远端**、**一次 CI 都没跑过** → 凡 CI 类判据一律写"**本地等价校验（未接远端，CI 待首推验证）**"，**不写"CI 绿"**。
- 本机可实跑的等价物：① 双解释器（3.8.8 + 3.12.10）全量 pytest（各 171 项）；② 四生成器 `--check`（两层）；③ `verify-data` 端到端 + 两项可证伪验证；④ CLI 退出码契约（子进程真跑）；⑤ 重跑生成器到临时目录逐字节比对。
- **不可本机实跑的缺口**：CI 矩阵的 ubuntu/Windows 环境差异、`actions/setup-python` 的 3.8 可用性 → **待首推验证**。

---

## 二、下一棒（M2）待办

按 `plan/06-里程碑.md` 的 M2 节执行：

1. **新建 `src/policy_radar/fetch.py`**（**真文件，不是填桩**）：
   - 取数路径 `searchVO.listVO`（决策 D13）——复用 `model.items_from_listvo()`；
   - 限频：逐页延时（默认 1.5s，可配）、**不做高并发**、同进程内两频道串行；
   - 超时 20s + 重试 2 次（指数退避）；两次不同渠道都失败 → 该频道记 `degraded`，**不中断另一频道**（失败隔离）；
   - **抓取自证**：断言 `len(实际取到) == min(请求条数, totalCount - 已取)`；不符即 **exit 4** 并打印实际/声明两数（**不得**用 `totalCount` 当"我拿到了这么多"）；
   - 抓取目标只从 API 返回的 `url` 字段取值（**不拼 URL**，决策 D2）；
   - 抓取时间戳**只进元信息**，不参与任何判定（无时钟参与判定）。
2. **CLI `fetch` 整项退役 exit 3**（K2 **四处同步**：删 `NOT_READY_COMMANDS` 里的 `fetch` 条目 → 改 `tests/test_cli_contract.py` 的 `_min_args` 与参数化 → 改 README 命令表与退出码表 → 改 `plan/00` 决策记录）。**注意**：`NOT_READY_COMMANDS` 仍含 `diff/parse/digest/run/bench`，`_not_ready` 通路与 `EXIT_NOT_READY` 常量**不能整体删除**（M3/M4/M5 还要用）。
3. **离线回归测试**：真实抓取产出与 `data/samples/` 留档样本 schema **逐字段一致**（**用冻结样本，不打真站点**——`tests/test_samples_regression.py` 已铺好 `items_from_listvo` 通路）。
4. **网络不可达 exit 4 且不留半个产物**（原子写）；总条数对账行真打印（`请求 N 条 / 声明 totalCount M / 实际 K`）。
5. 双解释器全量测试绿 → 回写 `plan/00`/`06` 状态 → **写 `plan/HANDOFF-M3.md`** → commit。

**M2 的 DoD 全文见 `plan/06-里程碑.md` 的 M2 节。**

---

## 三、既定口径清单（K 编号，"动了会打挂测试"的约定）

**改任何一条前先对照本表，改完重跑全量测试 + 四生成器 `--check` + `verify-data` 确认不回退。**

| K | 口径 | 落点（单点） | 守卫 |
|---|---|---|---|
| K1 | 统一 schema 字段集合与**顺序** = `SCHEMA_FIELDS` 十项 | `src/policy_radar/model.py` | `tests/test_model.py::test_schema_fields_exact_and_ordered` |
| K2 | 退出码语义 `0/1/2/3/4`；**3 退役走四处同步** | `src/policy_radar/errors.py` | `tests/test_cli_contract.py` |
| K3 | 序列化冻结参数 + LF + 尾换行 + 原子写 | `src/policy_radar/serialize.py` | `tests/test_serialize.py`（含"写盘单点"源码扫描） |
| K4 | 去重主键 = **`id`**；`index` 副键；`pcode` 非空时并入判定 | `snapshot.py`（M3 新建）；**M1 已落 oracle 版** `cases.naive_diff` | M3 测试 + `tests/test_truth_gate.py` |
| K5 | 清单排序键 = `(pubtimeStr 倒序, id 升序)`，**全程不读时钟** | `snapshot.py` / `report.py`；M1 在 `_genlib.canonical_order` | `tests/test_truth_gate.py::test_snapshots_are_canonically_ordered` |
| K6 | 文号解析三态 `parsed/partial/unparsed`；**代字不做白名单硬编码** | `parse.py`（M3 新建）；**M1 已落 oracle 版** `cases.naive_parse_pcode` | M3 测试 + `tests/test_truth_gate.py` |
| K7 | 部门别名表**单一来源** `data/config/org-aliases.json`；**最长优先匹配** | `parse.py`；**M1 已生成表** | M3 测试 |
| K8 | 订阅匹配 = 子串包含 + 全半角归一；**exclude 命中整条剔除**；同词去重 | `subscribe.py`（M4 新建）；**M1 已落 oracle 版** `cases.naive_match` | M4 测试 + `tests/test_truth_gate.py` |
| K9 | 渲染层**零判定** + 渲染出口**常驻零外链断言** | `report.py`（M5 新建） | M5 测试（AST 守门） |
| K10 | 快照字段白名单（**无全文**）；出现 `content/body/fulltext` 即红 | `snapshot.py` + `model.FORBIDDEN_SNAPSHOT_FIELDS` | M3 测试 + `tests/test_truth_gate.py` |
| K11 | 真值库**只存输入与期望**，禁 `observed_*`；观测由基准运行时实算 | `data/truth/` + `bench` | `tests/test_truth_gate.py` + `cases.find_observed_fields` + `verify-data` 运行时检 |
| K12 | 无 LLM、**零第三方运行时依赖**、**3.8 语法底线** | 全仓 | `test_readme_gate.py` 测试面/安装面 |
| K13 | 数据根定位优先级：**显式参数 > 环境变量 `POLICY_RADAR_DATA` > 源码树相对** | `src/policy_radar/paths.py` | `tests/test_selftest.py`（测试**显式传** `--data-root`） |
| **K14** | 参照实现（oracle）在包内 `cases.py`；**生产模块不得 import 它** | `src/policy_radar/cases.py` | `tests/test_cases_independence.py`（源码扫描：`snapshot.py`/`parse.py`/`subscribe.py` 不得 import `cases`） |
| **K15** | 对账语义**单一实现源** = `cases.compare_*`（测试与基准共用） | `src/policy_radar/cases.py` | M4 基准与 `tests/test_truth_gate.py` 共用同一份 |
| **K16** | 归一表**长度保持**（单字符 → 单字符），使 `offset` 语义唯一 | `data/config/normalize.json` | `tools/gen_subscribe_cases.py::assert_norm_map_is_length_preserving` |
| **K17** | 验收门槛**随数据下发**（`data/truth/manifest.json` 的 `thresholds`），**代码零默认值**；缺失即 exit 2 | `src/policy_radar/verify.py::_load_thresholds`；M4 基准同源 | `tests/test_truth_gate.py::test_verify_data_rejects_missing_thresholds` |
| **K18** | 真值台账须有**真调用方**：`verify-data` 真读并实算比对 | `src/policy_radar/verify.py` | `tests/test_truth_gate.py` 端到端真跑 |

> **M1 新增 K14–K18**。其中 K14 最要紧：M3/M4 落地生产模块时，**不得**为了省事去 import
> `cases` 的 oracle——那会让"参照实现"与"生产实现"同源，真值变成"自己验自己"。
> 生产实现要照 `data/truth/` 的**期望**写，写完由 `verify-data` / `bench` 对账。

---

## 四、本机环境坑（**只写实测过的**）

1. **用 `py` 不是 `python`**（后者可能是商店占位符）；跑脚本一律 `py -X utf8`（中文控制台编码）。
2. **本机双通道**：`py -0p` 实测有 **3.8.8-64** 与 **3.12.10-64**；两条都装了 pytest。**项目底线 3.8**，所有代码只用 3.8 语法。
3. **`/tmp` 与 Windows Python 路径不通**：临时文件一律用工作区相对路径或 `tempfile`。
4. **pytest 计数当轮实测**：M1 实测 `tests/` 收集 **171 项**（3.8 与 3.12 **同数**）。**别抄上一棒的数字**（M0 是 103）。
5. **写盘 API 3.8 差异**：`Path.write_text(newline=)` 是 3.10+ 参数 → 用 `open(..., newline="\n")` 或 `write_bytes`（本项目走 `serialize.py` 的 `os.fdopen(fd,"wb")`）。
6. **`PYTHONDONTWRITEBYTECODE=1`**：pyc 偶发损坏会导致"unknown opcode / 随机 FAIL / 测试数波动"；出怪错先清 `__pycache__` 再跑。
7. **编码三加固已就位**（别在后续里程碑拆掉）：① 入口 `_ensure_utf8_stdio()`；② 子进程调用一律显式 `encoding=`；③ CI `env: PYTHONUTF8=1`。
8. **网络类操作必带超时**：M1 实测 `curl -m 20` 与 `urllib` 20s 超时对 API 均正常；逐页 `sleep 3`（平台礼仪）。
9. **真实 API 响应含每请求不同的字段**（如 `searchVO.startTime`）→ **重抓会改变样本 sha256**：这是正常更新，须连同 `manifest.json` 一起提交并在 `data/samples/README.md` 登记新日期与 sha256。
10. **CI 未实跑**：本机模拟不了 ubuntu/Windows 矩阵 → **预算"首推至少一轮诊断"**。
11. **tools/ 目录不在安装包里**（`packages.find` 只含 `policy_radar*`）：`tools/*.py` 通过 `sys.path.insert` 引 `src/`；**包内不得反向依赖 `tools/`**（这是 M1 把 oracle 放进 `cases.py` 而非 `tools/` 的原因）。

---

## 五、关键命令速查

```bash
# --- 测试（双解释器，全量） ---
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q

# --- 单文件跑 ---
py -3.8 -X utf8 -m pytest -q tests/test_truth_gate.py
py -3.8 -X utf8 -m pytest -q tests/test_generators_check.py

# --- CLI 冒烟 ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar version
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar selftest --data-root data          # 期望 exit 0
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar selftest --data-root /nonexistent  # 期望 exit 1
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar verify-data --data-root data       # 期望 exit 0
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch                              # 期望 exit 3（M2 退役）

# --- 数据生成与位级守门（两层） ---
py -3.8 -X utf8 tools/capture_samples.py --out-dir data/samples            # 重抓（会改 sha256，须更新登记）
py -3.8 -X utf8 tools/capture_samples.py --out-dir data/samples --check    # 期望 exit 0
py -3.8 -X utf8 tools/gen_snapshot_pairs.py
py -3.8 -X utf8 tools/gen_snapshot_pairs.py --check                        # 期望 exit 0
py -3.8 -X utf8 tools/gen_pcode_cases.py --check                           # 期望 exit 0
py -3.8 -X utf8 tools/gen_subscribe_cases.py --check                       # 期望 exit 0
py -3.8 -X utf8 tools/gen_truth_manifest.py --check                        # 期望 exit 0

# --- 数据自审（真值库真调用方） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar verify-data --data-root data

# --- 哨兵桩排查（收尾期固定动作） ---
# 判据 = `src/` 与 `tools/` 下 0 命中；M1 实测 0 命中。
grep -rn "NotImplementedError\|TODO: 实现\|placeholder" src/ tools/
```

---

## 六、DoD 逐项 checklist（M1）

| # | 判据 | 验证方式（**在哪验的**） | 状态 |
|---|---|---|---|
| 1 | 快照对生成器 `--check` 位级一致（**两层**） | `gen_snapshot_pairs.py --check` exit 0；`tests/test_generators_check.py`（子进程真跑 + 篡改必红 + 重跑到临时目录逐字节比对 10 份产物） | ✅ |
| 2 | 真值库无 `observed_*` 字段 | `tests/test_truth_gate.py`（K11 断言 + 变异验证 + 文本级双保险）；`verify-data` 运行时检 | ✅ |
| 3 | 期望值可由输入**独立复算** | oracle 在 `src/policy_radar/cases.py`；`tests/test_cases_independence.py`（生产模块不得 import cases）；`tests/test_truth_gate.py`（输入喂 oracle 重算逐条一致，三个套件） | ✅ |
| 4 | 真值含"应判新增"与"应判重复"两类样本 | `diff-truth.json`：新增 6 / 重复 15；五形态逐类 ≥1 | ✅ |
| 5 | 真值台账**有真调用方** | ① 入仓（`.gitignore` 已锚定，`tests/test_repo_hygiene.py`）；② `--check` 位级守门；③ `verify-data` 真读实算（exit 0，比对 119 条） | ✅ |
| 6 | 文号真值含六形态 + 反向样例 | 人工 11 + 语料 57；形态 5 类；反向样例 `国令第847号` / 空 pcode 已断言 | ✅ |
| 7 | 真实 API 样本入仓，记 URL/日期/sha256 | `data/samples/` 4 份 + `manifest.json`；`tests/test_samples_regression.py`（29 项，含 sha256 与登记元信息校验） | ✅ |
| 8 | 双解释器全量测试绿 | 两条命令 exit 0；各收集 **171 项**（同数，本对话实测） | ✅ |
| 9 | HANDOFF-M2 落盘 | 本文件 | ✅ |

**偏差说明**：无。CI 类判据按诚实口径写"本地等价校验，未接远端，CI 待首推验证"——**不是"CI 绿"**。

---

## 七、续接指针

- **本棒产出**：`tools/`（6 文件：`_genlib.py` + 4 生成器 + `capture_samples.py`）、`src/policy_radar/cases.py`、`src/policy_radar/verify.py`、`data/samples/`（4 样本 + 2 登记文件）、`data/snapshots/`（pair-A/B + manifest）、`data/truth/`（3 真值 + manifest + README）、`data/config/`（3 规则数据 + README）、`tests/`（4 新文件，171 项总数）。
- **下一棒入口**：`plan/06-里程碑.md` 的 M2 节 + 本文件第二节。
- **下一棒出口**：`plan/HANDOFF-M3.md`（六节，**先落盘再结束对话**）。
- **待用户拍板**：`plan/00-README总览.md` 的待定决策表 P1–P6（**仍未答复**；按推荐项 A 执行并如实记"按推荐默认执行"）。M1 实际按推荐执行的三项：P2（1 页 20 条默认值，`fetch` 参数已就位）、P3（Markdown + HTML 双份，M5 落地）、P4（**不预置业务热词**——订阅配置关键词全部取自观测池真实文本）。
