# HANDOFF-M3：交接给"diff 与解析"里程碑

> 用法（新对话启动命令，用户侧拼绝对路径）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M3.md" 继续完成任务`
> 上一棒：**M2 抓取**（本对话完成）
> 下一棒：**M3 diff 与解析**（快照存储 + 新增/重复判定 + 文号解析 + 部门归一 + 未解析显式标记）

---

## 一、当前进度 + 证据（本对话实测）

### 已完成

| 项 | 证据 |
|---|---|
| **`fetch.py` 真实现（不是填桩）** | `src/policy_radar/fetch.py`；取数路径 `searchVO.listVO`（复用 `items_from_listvo`）；逐请求延时（默认 1.5s，可配）、无并发、多频道串行（`Pacer` 单点）；超时 20s + 重试 2 次（退避 1s/2s，`5xx/429` 可重试、其它 4xx 立即失败）；**不拼 URL**（只请求 API 端点，不发正文请求） |
| **抓取自证 + 对账行真打印** | 逐页断言 `len(实际) == min(n, totalCount - 已取)`；对账行 `请求 N 条 / 声明 totalCount M / 实际 K`；**真跑实测**：`对账 合计：请求 80 条 / 声明 totalCount 19025 / 实际 80 条` |
| **失败隔离 vs 硬失败（两类分开）** | 传输层失败 → 该频道 `degraded` + 整频道丢弃条目、不中断他频道（`ChannelUnavailable`）；硬失败（结构异常 / 非 JSON / 缺 `totalCount` / **自证不符**）→ 立即 exit 4 且不产文件 |
| **网络不可达 exit 4 且不留半个产物** | **真 CLI 实测**：`https_proxy=http://127.0.0.1:9` 下跑 `fetch` → 两频道均 degraded、`exit=4`、目标文件**不存在**、`out/` 里只有先前两次成功产物；另有离线用例（产物不存在 + 无 `.tmp-` 残留） |
| **离线回归（不打真站点）** | `tests/test_samples_regression.py` 第六节：假传输层**只回放 `data/samples/` 的冻结字节**跑完整抓取链路，4 形态逐字段比对（`items == items_from_listvo(sample)`）；请求 URL 与 `samples/manifest.json` 登记 URL 逐字一致 |
| **真跑一次实测（真站点）** | ① `fetch --pages 2 --n 20`（两频道 80 条）：`returned 80 / kept 79 / dropped 1`、**exit 1**；② `fetch --channel gwy --pages 1 --n 5`：5/5、**exit 0**，且产出 id 序列与冻结样本 `gwy-p1-n5.json` **完全相同**、字段集合相同 |
| **CLI `fetch` 整项退役 exit 3** | `NOT_READY_COMMANDS` 删条目；CLI 真接线 `cmd_fetch`；`test_cli_contract.py` 三处处置 + 新增 3 项契约断言；README 命令表/退出码/新增「双源抓取（M2）」节；`plan/00` 决策记录 D21–D24 |
| **退出码 3 的第五处落点（新发现）** | `.github/workflows/ci.yml` 里原本有一条 `python -m policy_radar fetch` + `test $code = 3` 的断言步骤——**不在"四处同步"清单里，漏改即首推红**。已换成 `bench`（M4），并新增一条"用法错误 exit 2 且不发请求"的联网无关冒烟 |
| **测试套件** | **230 项**（3.8 与 3.12 **同数**），双解释器全绿；新增 `tests/test_fetch.py`（38 项）+ `tests/test_samples_regression.py` 第六节（46 项，原 29） |
| **数据/真值面未回退** | 四生成器 `--check` 各 exit 0（两层）；`capture_samples.py --check` exit 0（4 份 sha256 一致）；`verify-data --data-root data` → **exit 0，3 套件自洽（比对 119 条）** |
| **CLI 契约未回退** | `selftest --data-root data` → exit 0（9/9）；空数据根 → exit 1；`bench` / `diff` / `parse` → exit 3；`fetch --channel nope` → **exit 2**；`fetch --pages 0` → **exit 2**（且在发请求前拦下） |
| **哨兵桩排查** | `grep -rn "NotImplementedError\|TODO: 实现\|placeholder" src/ tools/` → **0 命中** |

### M2 实测勘误（E8，**已同步 `data/README.md` 第六节 + README 局限第 11 条 + `plan/00`**）

| # | M0/M1 未记录的事实 | 实测证据 | 影响 |
|---|---|---|---|
| E8 | **部委频道存在必填字段（`summary`）为空的真实条目**，且**不在前 30 条观测池里** | 两频道各 **60 条**逐字段普查：`bm` 的 `summary` 空 **1/60**（id `26549375`，第 2 页）；`bm` 的 `index` 空 **60/60**；`pcode` 空 **4/60**；`gwy` 60 条**无空字段** | **本条推翻了我最初的实现判断**：我先把"必填字段缺失"写成硬失败（exit 4），真跑时 `fetch --pages 2` 直接 exit 4 拒绝工作。而 FR-11 的既定口径（`model.PolicyItem.validate` 的 docstring + `plan/04` 模块 5 第 4 条）是"该条不进库、计入 `dropped_count`、退出码 1"。→ 已改为**条目级丢弃 + 点名 id + 降级 exit 1**（决策 D21） |

> **教训（写给下一棒）**：M1 的"观测池 = 前 30 条"是抽样的，**真跑一次就能碰到池外的形态**。
> M3 的解析层（`pcode`/`puborg`）同样要假设"池外还有形态"——尤其 `pcode` 空（实测 4/60）
> 与 `index` 空（部委 60/60）之外，未知形态一律走**显式"未解析"**而不是猜。

### 诚实口径（**无远端，CI 从未跑过**）

- 全程**没有远端**、**一次 CI 都没跑过** → 凡 CI 类判据一律写"**本地等价校验（未接远端，CI 待首推验证）**"，**不写"CI 绿"**。
- 本机可实跑的等价物：① 双解释器（3.8.8 + 3.12.10）全量 pytest（各 **230 项**）；② 四生成器 + 样本登记 `--check`（两层）；③ `verify-data` 端到端 exit 0；④ **真实抓取两次**（80 条 / 5 条两条通路）；⑤ 离线回归（冻结字节跑全链路）；⑥ **真 `urllib` 打本地关闭端口**（`127.0.0.1:9`）归一为可隔离失败 + 真 CLI 走本地关闭代理 → exit 4 无产物。
- **不可本机实跑的缺口**：CI 矩阵的 ubuntu/Windows 环境差异、CI 步骤的 shell 差异（`set +e` / `$?`）、`actions/setup-python` 的 3.8 可用性 → **待首推验证**。

---

## 二、下一棒（M3）待办

按 `plan/06-里程碑.md` 的 M3 节与 `plan/04-模块详设.md` 的**模块 2 / 模块 3** 执行：

1. **新建 `src/policy_radar/snapshot.py`**（真文件，不是填桩）：快照存储 + 新增/重复判定。
   - **快照形态已被 M1 冻结**：`data/snapshots/pair-A.json` 的 `format` = `"policy-radar-snapshot"`、
     `format_version` = 1、键 `format/format_version/note/item_count/items`，
     `items` 按 **K5 规范序** `(pubtimeStr 倒序, id 升序)`、**无时间戳**、字段白名单 = `PolicyItem` 十项（K10）。
     `tools/_genlib.py` 里有同名常量与 `canonical_order()`——**包内不得 import `tools/`**，
     故 `snapshot.py` 必须自己实现（生产侧单点），并由测试断言与冻结产物**逐字节一致**。
   - **判定 K4**：`id` 相同 → 重复；否则 `pcode` 相同**且非空** → 重复；两键任一命中即判重复，
     命中键写进 `matched_by`（真值里有一条专门考 `pcode` 键命中）。
   - **双跑逐字节一致**（K3 写盘单点 + K5 排序 + 无时钟）。
2. **新建 `src/policy_radar/parse.py`**：文号三态解析（K6）+ 部门归一（K7）。
   - **三态** `parsed / partial / unparsed`，失败显式标 `未解析`（哨兵串 `未解析` 与 `data/truth/pcode-truth.json` 同值）；
   - **代字不做白名单硬编码**；
   - **实测形态必须全部覆盖**：标准 `〔〕`、**全角 `﹝﹞`（U+FE5D/FE5E，E6）**、
     `国令第847号`（无括号、**年份不得编造**）、多字代字 `国知发服字`、联发代字 `工信部联规函`、
     **序号与"号"之间有空格**（`农农发〔2026〕9 号`，E7）、空 `pcode`（三字段全未解析）；
   - **部门归一**：`puborg` 必须按 **`\s` 类空白**拆分（**E5：分隔符含 U+2002 EN SPACE 且同串混用**，
     只按 `' '` 拆会把 8 部门串变成单个不可识别 token）；别名表**单一来源**
     `data/config/org-aliases.json`（39 原始名 → 38 规范名）；**最长优先匹配**；认不出的原样保留 + 标 `alias_missing`。
3. **真值对账走生产实现**：把 `data/truth/diff-truth.json` 的**输入**（`snapshots/pair-A.json` /
   `pair-B.json`）喂**生产** `snapshot.py`，用 `cases.compare_diff`（K15 共用对账语义）
   与**期望**逐条比对：应判新增 **6** / 应判重复 **15** / `matched_by` 含 1 条 `pcode` 键命中。
   文号侧同理：`data/truth/pcode-truth.json`（人工 11 + 观测池 57 条，5 类形态）。
   **注意 `verify-data` 现在走的是 oracle（`cases.naive_*`）**——它核的是"真值库自身自洽"，
   不等于"生产实现达标"；M3 的测试要**真喂生产实现**（这正是 K14 的意义）。
4. **未挂原文不落库的代码级门禁**：快照出现 `content/body/fulltext` 一类字段即红（K10）。
5. **CLI `diff` / `parse` 整项退役 exit 3**：
   - 删 `NOT_READY_COMMANDS` 里对应条目 → CLI 接线 → `tests/test_cli_contract.py` 的 `_min_args` /
     参数化自动生效；
   - **D23 教训：落点不止"四处"**——用 `grep -rn "exit 3\|EXIT_NOT_READY\|尚未就绪" .`（排除 `.git/`）
     找全所有"断言某命令 exit 3"的地方。当前已知落点：`cli.py` / `test_cli_contract.py` /
     `README.md` / `plan/00` / `plan/03` / `plan/06` / `.github/workflows/ci.yml`（**该文件现在断言 `bench` exit 3，M4 落地时才会轮到它**）。
   - `test_not_ready_stderr_mentions_milestone` 现在断言的是 `bench`（M4）→ **M3 退役 `diff`/`parse` 时它仍成立**，不用改。
6. **双解释器全量测试绿** → 回写 `plan/00` / `06`（+ `03` / `04` / `07` 相应行）→ **`plan/HANDOFF-M4.md`** → commit。

**M3 的 DoD 全文见 `plan/06-里程碑.md` 的 M3 节。**

---

## 三、既定口径清单（K 编号，"动了会打挂测试"的约定）

**改任何一条前先对照本表，改完重跑全量测试 + 生成器 `--check` + `verify-data` 确认不回退。**

| K | 口径 | 落点（单点） | 守卫 |
|---|---|---|---|
| K1 | 统一 schema 字段集合与**顺序** = `SCHEMA_FIELDS` 十项 | `src/policy_radar/model.py` | `tests/test_model.py::test_schema_fields_exact_and_ordered` |
| K2 | 退出码语义 `0/1/2/3/4`；**3 退役落点要 grep 找全（不止四处）** | `src/policy_radar/errors.py` + CI | `tests/test_cli_contract.py` |
| K3 | 序列化冻结参数 + LF + 尾换行 + 原子写 | `src/policy_radar/serialize.py` | `tests/test_serialize.py`（含"写盘单点"源码扫描：`json.dump(` 不得出现在其它模块） |
| K4 | 去重主键 = **`id`**；`index` 副键；`pcode` 非空时并入判定 | `snapshot.py`（M3 新建）；M1 已落 oracle 版 `cases.naive_diff` | M3 测试 + `tests/test_truth_gate.py` |
| K5 | 清单排序键 = `(pubtimeStr 倒序, id 升序)`，**全程不读时钟** | `snapshot.py` / `report.py`；M1 在 `_genlib.canonical_order`（tools，包内不得 import） | M3 测试断言与 `data/snapshots/pair-*.json` 逐字节一致 + `test_truth_gate.py::test_snapshots_are_canonically_ordered` |
| K6 | 文号解析三态 `parsed/partial/unparsed`；**代字不做白名单硬编码** | `parse.py`（M3 新建）；M1 已落 oracle 版 `cases.naive_parse_pcode` | M3 测试 + `tests/test_truth_gate.py` |
| K7 | 部门别名表**单一来源** `data/config/org-aliases.json`；**最长优先匹配** | `parse.py`；M1 已生成表 | M3 测试 |
| K8 | 订阅匹配 = 子串包含 + 全半角归一；**exclude 命中整条剔除**；同词去重 | `subscribe.py`（M4 新建）；M1 已落 oracle 版 `cases.naive_match` | M4 测试 + `tests/test_truth_gate.py` |
| K9 | 渲染层**零判定** + 渲染出口**常驻零外链断言** | `report.py`（M5 新建） | M5 测试（AST 守门） |
| K10 | 快照字段白名单（**无全文**）；出现 `content/body/fulltext` 即红 | `snapshot.py` + `model.FORBIDDEN_SNAPSHOT_FIELDS` | M3 测试 + `tests/test_truth_gate.py` |
| K11 | 真值库**只存输入与期望**，禁 `observed_*`；观测由基准运行时实算 | `data/truth/` + `bench` | `tests/test_truth_gate.py` + `cases.find_observed_fields` + `verify-data` 运行时检 |
| K12 | 无 LLM、**零第三方运行时依赖**、**3.8 语法底线** | 全仓 | `test_readme_gate.py` 测试面/安装面 |
| K13 | 数据根定位优先级：**显式参数 > 环境变量 `POLICY_RADAR_DATA` > 源码树相对** | `src/policy_radar/paths.py` | `tests/test_selftest.py`（测试**显式传** `--data-root`） |
| K14 | 参照实现（oracle）在包内 `cases.py`；**生产模块不得 import 它** | `src/policy_radar/cases.py` | `tests/test_cases_independence.py`（源码扫描：`snapshot.py`/`parse.py`/`subscribe.py` 不得 import `cases`——**M3 新建的两个模块正落在这个扫描面里**） |
| K15 | 对账语义**单一实现源** = `cases.compare_*`（测试与基准共用） | `src/policy_radar/cases.py` | M4 基准与 `tests/test_truth_gate.py` 共用同一份 |
| K16 | 归一表**长度保持**（单字符 → 单字符），使 `offset` 语义唯一 | `data/config/normalize.json` | `tools/gen_subscribe_cases.py::assert_norm_map_is_length_preserving` |
| K17 | 验收门槛**随数据下发**（`data/truth/manifest.json` 的 `thresholds`），**代码零默认值**；缺失即 exit 2 | `src/policy_radar/verify.py::_load_thresholds`；M4 基准同源 | `tests/test_truth_gate.py::test_verify_data_rejects_missing_thresholds` |
| K18 | 真值台账须有**真调用方**：`verify-data` 真读并实算比对 | `src/policy_radar/verify.py` | `tests/test_truth_gate.py` 端到端真跑 |
| **K19** | 抓取三类异常**处置分离**：传输层失败可隔离 / 条目级不合规丢弃降级 / 硬失败立即 exit 4 | `src/policy_radar/fetch.py`（`ChannelUnavailable` + `partition_valid_items`） | `tests/test_fetch.py` |
| **K20** | 抓取产物的**三个条数不得混用**：`returned`（服务器真返回）/ `kept`（通过校验）/ `dropped`（丢弃） | `fetch.fetch_channel` 元信息 + 产物 `reconciliation` | `tests/test_fetch.py` |
| **K21** | 对账行格式 `请求 N 条 / 声明 totalCount M / 实际 K` **必须真打印**（degraded 时 M 记"未知"，不得拿 0 冒充） | `fetch.reconciliation_lines()` 单点 | `tests/test_fetch.py::test_reconciliation_line_*` |
| **K22** | `fetch` 产出条目顺序 = **API 返回序**（`item_order: "api"`）；规范排序（K5）只在快照/渲染层 | `fetch.build_output()`；M3 `snapshot.py` 负责重排 | `tests/test_fetch.py` + `test_samples_regression.py` |

> **M2 新增 K19–K22**。其中 K22 直接决定 M3 的接口：`fetch` 的产物是
> `{"format": "policy-radar-fetch", "format_version": 1, "items": [...API 序...], ...}`，
> **M3 的 `diff --current` 要认它**（两个格式都有 `items` 键，按 `format` 分派即可），
> 且**必须在 `snapshot.py` 里做一次 K5 规范排序**——别把"抓来什么顺序就什么顺序"写进快照。

---

## 四、本机环境坑（**只写实测过的**）

1. **用 `py` 不是 `python`**（后者可能是商店占位符）；跑脚本一律 `py -X utf8`（中文控制台编码）。
2. **本机双通道**：`py -0p` 实测有 **3.8.8-64** 与 **3.12.10-64**。**项目底线 3.8**，所有代码只用 3.8 语法。
3. **`/tmp` 与 Windows Python 路径不通**：临时文件一律用工作区相对路径或 `tempfile`。
4. **pytest 计数当轮实测**：M2 实测 `tests/` 收集 **230 项**（3.8 与 3.12 **同数**）。
   **⚠️ 上一棒的数字对不上**：`HANDOFF-M2.md` 写"171 项"，但本对话在 M2 改动**之前**实测是 **173 项**——
   说明那 171 是**中途记下、之后又加了测试**。**别抄任何一棒的数字，每轮重新数**。
5. **写盘 API 3.8 差异**：`Path.write_text(newline=)` 是 3.10+ 参数 → 用 `open(..., newline="\n")` 或 `write_bytes`（本项目走 `serialize.py` 的 `os.fdopen(fd,"wb")`）。
6. **`PYTHONDONTWRITEBYTECODE=1`**：pyc 偶发损坏会导致"unknown opcode / 随机 FAIL / 测试数波动"；出怪错先清 `__pycache__` 再跑。
7. **编码三加固已就位**（别在后续里程碑拆掉）：① 入口 `_ensure_utf8_stdio()`；② 子进程调用一律显式 `encoding=`；③ CI `env: PYTHONUTF8=1`。
8. **网络类操作必带超时**：M2 实测 `urllib` 20s 超时对 API 正常；逐请求 `delay` 是平台礼仪。
   **想让"网络不可达"可控复现**：设 `https_proxy=http://127.0.0.1:9`（本地关闭端口）→
   真 CLI 能稳定跑出 exit 4 且不产文件（M2 实测），**不需要真断网、也不打真站点**。
9. **真实 API 响应含每请求不同的字段** → **重抓会改变样本 sha256**：这是正常更新，须连同
   `manifest.json` 一起提交并在 `data/samples/README.md` 登记新日期与 sha256。**M2 未重抓样本**，故 sha256 不变。
10. **CI 未实跑**：本机模拟不了 ubuntu/Windows 矩阵与 CI 的 shell → **预算"首推至少一轮诊断"**。
11. **tools/ 目录不在安装包里**（`packages.find` 只含 `policy_radar*`）：`tools/*.py` 通过 `sys.path.insert` 引 `src/`；**包内不得反向依赖 `tools/`**。
12. **`fetch` 的产物不入库**：默认 `out/fetched.json`（`/out/` 已锚定在 `.gitignore`）。跑真站点后
    `git status` 应干净；若发现 `out/` 被跟踪，那是 `.gitignore` 的锚定被破坏了。
13. **本对话实测的一处 argparse 陷阱**（值得记住）：`getattr(args, "pages", DEFAULT) or DEFAULT` 会把
   **`--pages 0` 这个非法值静默改成合法默认值**——非法输入被吞掉比报错危险得多。参数解析一律
   显式判 `None`，然后交给校验函数报 exit 2。

---

## 五、关键命令速查

```bash
# --- 测试（双解释器，全量） ---
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest 2>&1 | tail -2   # 看"230 passed"这类计数

# --- 单文件跑 ---
py -3.8 -X utf8 -m pytest -q tests/test_fetch.py
py -3.8 -X utf8 -m pytest -q tests/test_samples_regression.py
py -3.8 -X utf8 -m pytest -q tests/test_truth_gate.py

# --- CLI 冒烟（退出码语义） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar version                        # 0
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar selftest --data-root data      # 0（9/9）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar selftest --data-root /nonexistent  # 1
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar verify-data --data-root data   # 0（3 套件 / 119 条）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar bench                          # 3（M4 未就绪）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar diff --snapshot s.json --current c.json  # 3（M3 未就绪）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar parse --input i.json           # 3（M3 未就绪）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --channel nope           # 2
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --pages 0                # 2（发请求前拦下）

# --- 抓取（真站点；产物在 out/，不入库） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --channel gwy --pages 1 --n 5 --delay 1.5 --out out/live-gwy-n5.json   # 期望 0
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --pages 2 --n 20 --delay 1.5 --out out/live-both-p2.json              # 期望 1（bm 有 1 条 summary 空 → 丢弃降级）
# 网络不可达的**可控复现**（本地关闭端口当代理，不打真站点）：
PYTHONPATH=src https_proxy=http://127.0.0.1:9 py -3.8 -X utf8 -m policy_radar fetch --out out/should-not-exist.json  # 期望 4，且文件不存在

# --- 数据生成与位级守门（两层） ---
py -3.8 -X utf8 tools/gen_snapshot_pairs.py --check       # 0
py -3.8 -X utf8 tools/gen_pcode_cases.py --check          # 0
py -3.8 -X utf8 tools/gen_subscribe_cases.py --check      # 0
py -3.8 -X utf8 tools/gen_truth_manifest.py --check       # 0
py -3.8 -X utf8 tools/capture_samples.py --out-dir data/samples --check   # 0（4 份 sha256 一致）

# --- 哨兵桩排查（收尾期固定动作） ---
# 判据 = `src/` 与 `tools/` 下 0 命中；M2 实测 0 命中。
grep -rn "NotImplementedError\|TODO: 实现\|placeholder" src/ tools/

# --- 退出码 3 退役落点排查（M3 退役 diff/parse 时用；M2 的教训） ---
grep -rn "exit 3\|EXIT_NOT_READY\|尚未就绪" --include=*.py --include=*.md --include=*.yml . | grep -v "^./.git/"
```

---

## 六、DoD 逐项 checklist（M2）

| # | 判据 | 验证方式（**在哪验的**） | 状态 |
|---|---|---|---|
| 1 | 真实抓取产出与留档样本 schema **逐字段一致**（离线回归，不打真站点） | `tests/test_samples_regression.py` 第六节（4 形态 × 逐字段相等）；`tests/test_fetch.py`（假传输层只回放冻结字节）；**另：真跑 gwy n=5 的 id 序列与样本完全相同** | ✅ |
| 2 | totalCount **对账行真打印** | `fetch.reconciliation_lines()` 单点 + `test_reconciliation_line_format_matches_dod`；真跑输出 `请求 80 条 / 声明 totalCount 19025 / 实际 80 条` | ✅ |
| 3 | 网络不可达 **exit 4 且不留半个产物** | 离线用例（产物不存在 + 无 `.tmp-` 残留）+ **真 CLI 走本地关闭代理实测 exit 4 且文件不存在** + 真 `urllib` 打 `127.0.0.1:9` 归一为可隔离失败 | ✅ |
| 4 | **失败隔离**（一频道挂不中断另一频道） | `test_transport_failure_is_isolated_and_exit_1`；`test_partial_channel_pages_are_dropped_not_half_kept`；`test_hard_failure_beats_isolation_and_leaves_nothing` | ✅ |
| 5 | 抓取自证不符即 exit 4 并打印**实际/声明两数** | `test_mismatch_between_declared_and_actual_is_a_hard_failure`；`test_declared_smaller_than_request_is_honored`；`test_multi_page_stops_when_declared_total_is_reached` | ✅ |
| 6 | 限频 + 超时重试（20s / 2 次退避） | `test_pacer_*`（首发不延时）、`test_two_channels_are_serial_and_delayed`、`test_retry_then_success_uses_exponential_backoff`（退避 `[1]`）、`test_retry_exhausted_attempts_are_retries_plus_one`（3 次 + `[1,2]`）、`test_retryable_5xx_is_retried`、`test_non_retryable_4xx_fails_immediately` | ✅ |
| 7 | 不拼 URL / 不发正文请求（D2） | `test_only_api_endpoint_is_requested`（请求 URL 与条目 `url` 无交集）；`test_fetch_requested_url_equals_registry_url` | ✅ |
| 8 | 条目级不合规按 FR-11 处置（**E8 修正后的口径**） | `test_missing_required_field_is_dropped_not_patched`（丢弃 + 点名 + `丢弃 1 条` 行 + exit 1）、`test_impossible_date_is_dropped_with_reason`、`test_dropping_does_not_break_the_self_check` | ✅ |
| 9 | 时间戳只进元信息、不参与判定 | `test_timestamp_is_meta_only`（两时钟产物除 `captured_at` 外相等）；`test_module_has_no_wall_clock_in_judgment`（源码扫描） | ✅ |
| 10 | CLI `fetch` 整项退役 exit 3（落点找全，含 CI） | `NOT_READY_COMMANDS` + `test_cli_contract.py`（含新增 3 项）+ README + `plan/00` + **CI 步骤换成 `bench`** | ✅ |
| 11 | 双解释器全量测试绿 | 两条命令 exit 0；各收集 **230 项**（同数，本对话实测） | ✅ |
| 12 | 数据/真值面未回退 | 四生成器 `--check` + `capture_samples --check` exit 0；`verify-data` exit 0（119 条） | ✅ |
| 13 | HANDOFF-M3 落盘 | 本文件 | ✅ |

**偏差说明**：① 上一棒 HANDOFF 的测试计数（171）与本轮改动前实测（173）不符，已在第四节第 4 条如实记；② "CI 绿"类判据按诚实口径写"本地等价校验，未接远端，CI 待首推验证"——**不是"CI 绿"**；③ 中途曾把"条目级不合规"实现为硬失败，真跑实测（E8）后按既定 FR-11 口径修正——**这条修正本身就是 M2 最有价值的产出之一**。

---

## 七、续接指针

- **本棒产出**：`src/policy_radar/fetch.py`（真实现，533 行）、`tests/test_fetch.py`（38 项，685 行）、
  `tests/test_samples_regression.py`（第六节新增 17 项，共 46）、CLI/README/CI/`plan/00,03,04,05,06,07`/`data/README.md` 同步。
- **下一棒入口**：`plan/06-里程碑.md` 的 M3 节 + `plan/04-模块详设.md` 模块 2/模块 3 + 本文件第二节。
- **下一棒出口**：`plan/HANDOFF-M4.md`（先落盘再结束对话）。
- **M3 最要紧的三件事**（按风险排序）：
  1. **K5 规范排序与冻结快照逐字节一致**（`snapshot.py` 自己实现，不得 import `tools/`）；
  2. **K6/E5/E6/E7 四类实测形态全覆盖**（全角括号、序号空格、U+2002 多部门、空 pcode 三字段未解析）；
  3. **K14：`snapshot.py`/`parse.py` 不得 import `cases.py`**（源码扫描会红），真值对账要通过
     `cases.compare_*` 在**测试**里做，而不是在生产模块里复用 oracle。
- **待用户拍板**：`plan/00-README总览.md` 的待定决策表 P1–P6（**仍未答复**；按推荐项 A 执行并如实记"按推荐默认执行"）。
  M2 实际按推荐执行/推进的：P2（1 页 20 条默认值）、P5（只留当前快照 + git 历史留档 → 故 `fetch` 产物是**运行时文件**，
  `data/` 只放冻结资产）。