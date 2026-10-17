# HANDOFF-M4：交接给"基准"里程碑

> 用法（新对话启动命令，用户侧拼绝对路径）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M4.md" 继续完成任务`
> 上一棒：**M3 diff 与解析**（本对话完成）
> 下一棒：**M4 基准**（关键词订阅 + 真值基准一键跑通，含探活可证伪、双边门）

---

## 一、当前进度 + 证据（本对话实测）

### 已完成

| 项 | 证据 |
|---|---|
| **`snapshot.py` 真实现（不是填桩）** | `src/policy_radar/snapshot.py`（约 300 行）：`build_snapshot` / `canonical_order`（K5 生产侧单点）/ `detect_new`（K4 双键）/ `build_diff_product` / `load_items_file`（K23 按 `format` 分派）/ `ensure_item_fields`（K10 门禁，**读、写两条路径都拦**）/ `cmd_diff`（K24 首跑语义） |
| **快照重建与冻结产物逐字节一致** | `build_snapshot` 重建 `data/snapshots/pair-A.json` / `pair-B.json` **逐字节相等**（14470 / 15096 字节）；**输入乱序也不变**（规范排序收口在生产层）。包内不 import `tools/`，`_genlib.canonical_order` 仍是生成侧实现，两者一致性由测试守门 |
| **生产 diff 对真值逐条一致（真喂生产实现，K14 的意义）** | `detect_new(pair-A, pair-B)` → `cases.compare_diff` → **ok**：新增 6 / 重复 15 / `matched_by` 逐键一致，含 1 条 `pcode` 键命中（id `26276349`）；空 pcode 边界（`empty_pcode_same` 只按 id 判）有专项断言 |
| **`parse.py` 真实现（不是填桩）** | `src/policy_radar/parse.py`（约 260 行）：`parse_pcode`（K6 三态 + 哨兵 `未解析`）/ `parse_orgs`（K7 最长优先 + E5 `\s` 拆分）/ `load_org_aliases`（单一来源 + `match_rule` 口径校验）/ `build_parse_product` / `cmd_parse` |
| **生产解析对真值 58 键全对** | 真值全量（人工 11 + 观测池 57，去重 58 键）→ `cases.compare_pcode` → **ok**；E6 全角 `﹝﹞` / E7 序号空格 / `国令第847号` 不编造年份 / 空 pcode 三字段全未解析，各有专项用例 |
| **部门归一实测核验** | 别名表 39 原始名 → 38 规范名；**观测池 60 条 puborg 全 token 归一 0 缺失**；7 对前缀嵌套（`国务院` ⊂ `国务院办公厅` 等）最长优先命中正确；未识别 token 原样保留 + `alias_missing` |
| **CLI `diff` / `parse` 整项退役 exit 3** | `NOT_READY_COMMANDS` 现只剩 `digest/run/bench`；`test_cli_contract.py`：`_min_args` 删两处 + `test_fetch_and_diff_parse_are_retired_from_not_ready` + `test_other_commands_still_not_ready`（`{"digest","run","bench"}`）+ **`test_retired_commands_do_real_work_offline`**（退役 ≠ 删语义的行为级证明：diff/parse 真跑真值一致）；README 命令表 + 新增「快照 diff 与解析（M3）」节（第九节，原九/十节顺延为十/十一）；`plan/00` 决策 D25–D27 |
| **退出码 3 落点 grep 复核（D23 教训）** | `grep -rn "exit 3\|EXIT_NOT_READY\|尚未就绪\|NOT_READY"` 全仓跑过：`ci.yml` 断言 `bench` exit 3（M4 才退役）与 `fetch --pages 0` exit 2，**均仍成立、无需改**；`plan/HANDOFF-M1/M2` 里的 `fetch exit 3` 是历史记录（描述当时状态），不改 |
| **CLI 实测（退出码逐个跑）** | `diff`（冻结对）→ **0**（stdout：`上次快照 20 条 → 本次 21 条；新增 6 条 / 重复 15 条（命中键 id 14 / pcode 1）`）；`diff` 首跑（省略 --snapshot）→ **0**（明示"首次运行"）；`diff --snapshot nope.json` → **2**；`diff` 缺 `--current` → **2**（argparse）；`parse --input pair-B.json --data-root data` → **0**；`parse --input nope.json` → **2**；`parse` 喂 parse 产物（未知 format 再入）→ **2**；`bench` → **3**（未就绪通路未被误伤） |
| **测试套件** | **287 项**（3.8 与 3.12 **同数**），双解释器全绿；新增 `tests/test_snapshot_diff.py`（29 项）+ `tests/test_parse_pcode.py`（29 项）；`test_cli_contract.py` 净 +1 项（两改一加） |
| **数据/真值面未回退** | 四生成器 `--check` 各 exit 0（两层）；`capture_samples.py --check` exit 0（4 份 sha256 一致）；`verify-data --data-root data` → **exit 0，3 套件自洽（比对 119 条）**；`selftest` → exit 0（9/9）；**M3 未新增 `data/` 资产**（产物全在 `out/`，不入库） |
| **哨兵桩排查** | `grep -rn "NotImplementedError\|TODO: 实现\|placeholder" src/ tools/` → **0 命中** |

### 诚实口径（**无远端，CI 从未跑过**）

- 全程**没有远端**、**一次 CI 都没跑过** → 凡 CI 类判据一律写"**本地等价校验（未接远端，CI 待首推验证）**"，**不写"CI 绿"**。
- 本机可实跑的等价物：① 双解释器（3.8.8 + 3.12.10）全量 pytest（各 **287 项**）；② 四生成器 + 样本登记 `--check`（两层）；③ `verify-data` 端到端 exit 0；④ **生产实现对两份真值台账全量逐条对账**（diff 21 条 / pcode 58 键）；⑤ 快照重建与冻结产物**逐字节一致**；⑥ CLI 退出码契约（子进程真跑，含 0/2/3 全路径）。
- **不可本机实跑的缺口**：CI 矩阵的 ubuntu/Windows 环境差异、CI 步骤的 shell 差异（`set +e` / `$?`）、`actions/setup-python` 的 3.8 可用性 → **待首推验证**。

### M3 设计要点（写给下一棒）

1. **K23（新口径）**：承载条目的产物**按 `format` 分派**——`policy-radar-fetch` / `policy-radar-snapshot` /
   `policy-radar-diff` 三类都能互喂（`snapshot.load_items_file()` 单点）；**未知格式显式拒绝（exit 2）**。
   M4 的 `subscribe` / M5 的 `report` 消费 diff 产物时**复用这个入口**，别各写一个 loader。
2. **K24（新口径）**：`diff` 首跑 = **省略** `--snapshot`（全部计入新增 + stdout 明示）；
   给了路径但读不到 = **exit 2**，不静默回落成首跑（D25："路径打错"不得被读成"全是新发的"）。
3. **parse 产物条目按输入序**（`parsed_items` 与输入条目一一对应）；diff 产物与快照才是规范序。
   M5 日报若要按日期排，**消费 diff 产物**（它已按 K5 排好）。
4. **`ensure_item_fields` 是 K10 的公共门禁**：M4/M5 任何"把条目 dict 写进产物"的地方都应过这道门
   （`snapshot.ensure_item_fields(dicts, where)`），别在 subscribe/report 里另写白名单检查。
5. **错误通路的教训**：`load_snapshot` 抛的是 `SnapshotError`（`ValueError` 子类）——
   CLI 层若不显式转 `UsageError`，兜底会打"输入不可用"前缀但语义已对（exit 2）。
   `cmd_diff` 里已显式包了一层；M4 的 `cmd_bench` 读真值文件记得同款处置。

---

## 二、下一棒（M4）待办

按 `plan/06-里程碑.md` 的 M4 节与 `plan/04-模块详设.md` 的**模块 4** 执行：

1. **新建 `src/policy_radar/subscribe.py`**（真文件，不是填桩）：关键词订阅 + 命中判定（K8）。
   - **匹配口径已被 M1 冻结**：子串包含（`keyword in title or keyword in summary`）、
     **全半角归一**（`data/config/normalize.json`，K16 长度保持 → `offset` 归一前后同值）、
     **exclude 命中整条剔除**（记 `include_matched_before_exclusion` 可回溯）、
     **同词按归一后去重、保持配置顺序**；命中字段按 `FIELD_PRIORITY = (title, summary)` 取首次出现。
   - **生产实现大概率用正则/索引**——参照实现 `cases.naive_match` 是归一化 + `str.find`，两路径独立（K14）。
   - 真值侧：`data/truth/subscribe-truth.json`（语料 = pair-B 21 条，六类边界形态）+
     `data/config/subscribe.json`（含重复词 `"规划"`）。**测试真喂生产实现** → `cases.compare_subscribe`。
2. **新建 M4 基准（`bench` 子命令）**——M4 的核心交付：
   - **一键跑通三个套件**：diff / pcode / subscribe（生产实现实算 → `cases.compare_*` 对账）；
   - **门槛随数据下发**（K17）：读 `data/truth/manifest.json` 的 `thresholds`（与 `verify.py::_load_thresholds`
     **同源**，别再写一份 loader）；缺失即 exit 2，**代码零默认值**；
   - **退出码三语义**：0 达标 / 1 未达标 / 2 用法错误，**锁进测试**；
   - **每套件配可证伪探活**：注入缺陷（如把生产实现的 pcode 键判定注释掉）→ 基准必须报未达标；
     探活打到**端到端入口**（CLI 层），不是只调函数；
   - **双边门**：既守误报率 0（不该有的结论一条不能多），也守检出率 ≥ 阈值（该有的逐样本点名）；
   - **真值库全量实跑**：三份真值全部喂生产实现（M3 已有 diff/pcode 两套件对账测试，M4 收进 bench）。
3. **CLI `bench` 整项退役 exit 3**：
   - 删 `NOT_READY_COMMANDS` 里 `bench` 条目 → CLI 接线 `cmd_bench` → `test_cli_contract.py` 的
     `_min_args` / 参数化自动生效；**`test_not_ready_stderr_mentions_milestone` 现在显式断言
     `run_cli(["bench"])` stderr 含 "M4" → 必须改**（bench 落地后改用 `digest`（M5）断言里程碑字样）；
     `test_other_commands_still_not_ready` 的集合断言要改成 `{"digest", "run"}`；
     **同款加一条"退役 ≠ 删语义"的行为级证明**（M3 的 `test_retired_commands_do_real_work_offline`）。
   - **D23 教训：落点不止"四处"**——`grep -rn "exit 3\|EXIT_NOT_READY\|尚未就绪" .`（排除 `.git/`）。
     当前已知落点：`cli.py` / `test_cli_contract.py` / `README.md`（命令表两处 + 退出码表）/
     `plan/00` / `plan/03` / `plan/06` / **`.github/workflows/ci.yml`（该文件现在断言 `bench` exit 3
     ——M4 落地时必须换，比如换成 `digest` 或"已落地命令的用法错误"类联网无关冒烟）**。
4. **双解释器全量测试绿** → 回写 `plan/00` / `06`（+ `03` / `04` / `07` 相应行）→ **`plan/HANDOFF-M5.md`** → commit。

**M4 的 DoD 全文见 `plan/06-里程碑.md` 的 M4 节。**

---

## 三、既定口径清单（K 编号，"动了会打挂测试"的约定）

**改任何一条前先对照本表，改完重跑全量测试 + 生成器 `--check` + `verify-data` 确认不回退。**

| K | 口径 | 落点（单点） | 守卫 |
|---|---|---|---|
| K1 | 统一 schema 字段集合与**顺序** = `SCHEMA_FIELDS` 十项 | `src/policy_radar/model.py` | `tests/test_model.py::test_schema_fields_exact_and_ordered` |
| K2 | 退出码语义 `0/1/2/3/4`；**3 退役落点要 grep 找全（不止四处）** | `src/policy_radar/errors.py` + CI | `tests/test_cli_contract.py` |
| K3 | 序列化冻结参数 + LF + 尾换行 + 原子写 | `src/policy_radar/serialize.py` | `tests/test_serialize.py`（含"写盘单点"源码扫描：`json.dump(` 不得出现在其它模块） |
| K4 | 去重主键 = **`id`**；`index` 副键；`pcode` 非空时并入判定 | `snapshot.detect_new()`；M1 已落 oracle 版 `cases.naive_diff` | `tests/test_snapshot_diff.py` + `tests/test_truth_gate.py` |
| K5 | 清单排序键 = `(pubtimeStr 倒序, id 升序)`，**全程不读时钟** | `snapshot.canonical_order()`（生产单点）/ `report.py`（M5）；`tools/_genlib.canonical_order` 是生成侧实现（包内不得 import） | `tests/test_snapshot_diff.py::test_rebuilt_snapshot_is_byte_identical_to_frozen` + `test_truth_gate.py::test_snapshots_are_canonically_ordered` |
| K6 | 文号解析三态 `parsed/partial/unparsed`；**代字不做白名单硬编码**；哨兵 `未解析` | `parse.parse_pcode()`；M1 已落 oracle 版 `cases.naive_parse_pcode` | `tests/test_parse_pcode.py` + `tests/test_truth_gate.py` |
| K7 | 部门别名表**单一来源** `data/config/org-aliases.json`；**最长优先（前缀匹配）** | `parse.load_org_aliases()` / `parse.parse_orgs()` | `tests/test_parse_pcode.py`（含 `match_rule` 口径校验拒绝） |
| K8 | 订阅匹配 = 子串包含 + 全半角归一；**exclude 命中整条剔除**；同词去重 | `subscribe.py`（M4 新建）；M1 已落 oracle 版 `cases.naive_match` | M4 测试 + `tests/test_truth_gate.py` |
| K9 | 渲染层**零判定** + 渲染出口**常驻零外链断言** | `report.py`（M5 新建） | M5 测试（AST 守门） |
| K10 | 快照字段白名单（**无全文**）；出现 `content/body/fulltext` 即红；**白名单外字段同样拒** | `snapshot.ensure_item_fields()`（读、写两条路径）；`model.FORBIDDEN_SNAPSHOT_FIELDS` | `tests/test_snapshot_diff.py` + `tests/test_truth_gate.py` |
| K11 | 真值库**只存输入与期望**，禁 `observed_*`；观测由基准运行时实算 | `data/truth/` + `bench` | `tests/test_truth_gate.py` + `cases.find_observed_fields` + `verify-data` 运行时检 |
| K12 | 无 LLM、**零第三方运行时依赖**、**3.8 语法底线** | 全仓 | `test_readme_gate.py` 测试面/安装面 |
| K13 | 数据根定位优先级：**显式参数 > 环境变量 `POLICY_RADAR_DATA` > 源码树相对** | `src/policy_radar/paths.py` | `tests/test_selftest.py`（测试**显式传** `--data-root`） |
| K14 | 参照实现（oracle）在包内 `cases.py`；**生产模块不得 import 它** | `src/policy_radar/cases.py` | `tests/test_cases_independence.py`（源码扫描：`snapshot.py`/`parse.py`/`subscribe.py` 不得 import `cases`——M3 两个新模块已在扫描面里且实测绿） |
| K15 | 对账语义**单一实现源** = `cases.compare_*`（测试与基准共用） | `src/policy_radar/cases.py` | M3 测试与 M4 基准共用同一份 |
| K16 | 归一表**长度保持**（单字符 → 单字符），使 `offset` 语义唯一 | `data/config/normalize.json` | `tools/gen_subscribe_cases.py::assert_norm_map_is_length_preserving` |
| K17 | 验收门槛**随数据下发**（`data/truth/manifest.json` 的 `thresholds`），**代码零默认值**；缺失即 exit 2 | `src/policy_radar/verify.py::_load_thresholds`；**M4 基准同源复用** | `tests/test_truth_gate.py::test_verify_data_rejects_missing_thresholds` |
| K18 | 真值台账须有**真调用方**：`verify-data` 真读并实算比对 | `src/policy_radar/verify.py` | `tests/test_truth_gate.py` 端到端真跑 |
| K19 | 抓取三类异常**处置分离**：传输层失败可隔离 / 条目级不合规丢弃降级 / 硬失败立即 exit 4 | `src/policy_radar/fetch.py`（`ChannelUnavailable` + `partition_valid_items`） | `tests/test_fetch.py` |
| K20 | 抓取产物的**三个条数不得混用**：`returned`（服务器真返回）/ `kept`（通过校验）/ `dropped`（丢弃） | `fetch.fetch_channel` 元信息 + 产物 `reconciliation` | `tests/test_fetch.py` |
| K21 | 对账行格式 `请求 N 条 / 声明 totalCount M / 实际 K` **必须真打印**（degraded 时 M 记"未知"，不得拿 0 冒充） | `fetch.reconciliation_lines()` 单点 | `tests/test_fetch.py::test_reconciliation_line_*` |
| K22 | `fetch` 产出条目顺序 = **API 返回序**（`item_order: "api"`）；规范排序（K5）只在快照/渲染层 | `fetch.build_output()`；`snapshot.canonical_order()` 负责重排 | `tests/test_fetch.py` + `tests/test_snapshot_diff.py::test_rebuilt_snapshot_is_order_independent` |
| **K23** | 承载条目的产物**按 `format` 分派**（`policy-radar-fetch` / `policy-radar-snapshot` / `policy-radar-diff`）；**未知格式显式拒绝（exit 2）** | `snapshot.load_items_file()` 单点 | `tests/test_snapshot_diff.py::test_load_items_file_*` |
| **K24** | `diff` **首跑语义**：省略 `--snapshot` = 首次运行（全部计入新增 + stdout 明示）；**给了路径但读不到 = exit 2**，不得静默回落成首跑 | `snapshot.cmd_diff()` | `tests/test_snapshot_diff.py::test_cmd_diff_missing_snapshot_is_usage_error_not_first_run` |

> **M3 新增 K23–K24**。其中 K23 直接决定 M4/M5 的接口：订阅与日报消费条目一律走
> `snapshot.load_items_file()`（三类产物通吃），**不要**各写一个 loader。

---

## 四、本机环境坑（**只写实测过的**）

1. **用 `py` 不是 `python`**（后者可能是商店占位符）；跑脚本一律 `py -X utf8`（中文控制台编码）。
2. **本机双通道**：`py -0p` 实测有 **3.8.8-64** 与 **3.12.10-64**。**项目底线 3.8**，所有代码只用 3.8 语法。
3. **`/tmp` 与 Windows Python 路径不通**：临时文件一律用工作区相对路径或 `tempfile`（pytest 的 `tmp_path` 可用）。
4. **pytest 计数当轮实测**：M3 实测 `tests/` 收集 **287 项**（3.8 与 3.12 **同数**）。
   **别抄任何一棒的数字，每轮重新数**（M2 已实测过一次上一棒数字对不上）。
5. **写盘 API 3.8 差异**：`Path.write_text(newline=)` 是 3.10+ 参数 → 用 `open(..., newline="\n")` 或 `write_bytes`（本项目走 `serialize.py` 的 `os.fdopen(fd,"wb")`）。
6. **`PYTHONDONTWRITEBYTECODE=1`**：pyc 偶发损坏会导致"unknown opcode / 随机 FAIL / 测试数波动"；出怪错先清 `__pycache__` 再跑。
7. **编码三加固已就位**（别在后续里程碑拆掉）：① 入口 `_ensure_utf8_stdio()`；② 子进程调用一律显式 `encoding=`；③ CI `env: PYTHONUTF8=1`。
8. **网络类操作必带超时**；**想让"网络不可达"可控复现**：设 `https_proxy=http://127.0.0.1:9` → 真 CLI 稳定 exit 4 且不产文件（M2 实测），不需要真断网、也不打真站点。
9. **真实 API 响应含每请求不同的字段** → **重抓会改变样本 sha256**：正常更新，须连同 `manifest.json` 一起提交。**M3 未重抓样本**，sha256 不变。
10. **CI 未实跑**：本机模拟不了 ubuntu/Windows 矩阵与 CI 的 shell → **预算"首推至少一轮诊断"**。
11. **tools/ 目录不在安装包里**：**包内不得反向依赖 `tools/`**；M3 的 `snapshot.canonical_order` 与 `tools/_genlib.canonical_order` 是两份独立实现（生成侧 vs 生产侧），一致性靠逐字节测试守门——**别"顺手统一"成一个 import**。
12. **`fetch`/`diff`/`parse` 的产物不入库**：默认都在 `out/`（已锚定在 `.gitignore`）。跑完 CLI 后 `git status` 应干净。
13. **argparse 陷阱**（M2 教训，M3 又用到一次）：`getattr(args, "x", DEFAULT) or DEFAULT` 会把** falsy 合法值静默改成默认值**。参数解析一律显式判 `None`（M3 的 `--snapshot` 省略语义就是"显式判 None"落地成首跑，路径失效则报 2）。
14. **docstring 里的 `\s`** 会触发 3.12 的 `DeprecationWarning: invalid escape sequence`（M3 实测）→ 模块/函数 docstring 含正则记号时用 **raw string（`r"""…"""`）**。
15. **源码扫描测试要扫 import 语句而非子串**：`assert "tools" not in src` 会被 docstring 里的"tools/"字样误伤（M3 实测踩过）→ 用 `re.search(r"import\s+_genlib|from\s+.*\btools\b", src)`。

---

## 五、关键命令速查

```bash
# --- 测试（双解释器，全量） ---
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest 2>&1 | tail -2   # 看"287 passed"这类计数

# --- 单文件跑 ---
py -3.8 -X utf8 -m pytest -q tests/test_snapshot_diff.py
py -3.8 -X utf8 -m pytest -q tests/test_parse_pcode.py
py -3.8 -X utf8 -m pytest -q tests/test_cli_contract.py

# --- CLI 冒烟（退出码语义） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar version                        # 0
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar selftest --data-root data      # 0（9/9）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar verify-data --data-root data   # 0（3 套件 / 119 条）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar bench                          # 3（M4 未就绪）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar diff --snapshot data/snapshots/pair-A.json --current data/snapshots/pair-B.json --out out/diff.json --snapshot-out out/snapshot.json   # 0；新增 6 / 重复 15（pcode 键 1）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar diff --current data/snapshots/pair-B.json --out out/d2.json --snapshot-out out/s2.json   # 0（首跑：21 全新增）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar diff --snapshot nope.json --current data/snapshots/pair-B.json   # 2（读不到不静默当首跑）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar parse --input data/snapshots/pair-B.json --data-root data          # 0；parsed 17 / partial 2 / unparsed 2
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar parse --input nope.json --data-root data                           # 2
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --channel nope   # 2
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --pages 0        # 2（发请求前拦下）

# --- 抓取（真站点；产物在 out/，不入库） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --channel gwy --pages 1 --n 5 --delay 1.5 --out out/live-gwy-n5.json   # 期望 0
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --pages 2 --n 20 --delay 1.5 --out out/live-both-p2.json               # 期望 1（bm 有 1 条 summary 空 → 丢弃降级）
# 网络不可达的可控复现（本地关闭端口当代理，不打真站点）：
PYTHONPATH=src https_proxy=http://127.0.0.1:9 py -3.8 -X utf8 -m policy_radar fetch --out out/should-not-exist.json   # 期望 4，且文件不存在

# --- 数据生成与位级守门（两层） ---
py -3.8 -X utf8 tools/gen_snapshot_pairs.py --check       # 0
py -3.8 -X utf8 tools/gen_pcode_cases.py --check          # 0
py -3.8 -X utf8 tools/gen_subscribe_cases.py --check      # 0
py -3.8 -X utf8 tools/gen_truth_manifest.py --check       # 0
py -3.8 -X utf8 tools/capture_samples.py --out-dir data/samples --check   # 0（4 份 sha256 一致）

# --- 哨兵桩排查（收尾期固定动作） ---
grep -rn "NotImplementedError\|TODO: 实现\|placeholder" src/ tools/

# --- 退出码 3 退役落点排查（M4 退役 bench 时用；D23 教训） ---
grep -rn "exit 3\|EXIT_NOT_READY\|尚未就绪" --include=*.py --include=*.md --include=*.yml . | grep -v "^./.git/"
```

---

## 六、DoD 逐项 checklist（M3）

| # | 判据 | 验证方式（**在哪验的**） | 状态 |
|---|---|---|---|
| 1 | 同输入同输出（双跑逐字节） | `test_diff_product_is_byte_identical_across_runs` / `test_parse_product_is_byte_identical_across_runs`（真写盘比字节）；快照重建与冻结 `pair-A/B.json` 逐字节一致（含乱序输入） | ✅ |
| 2 | 预置快照对 diff 与真值逐条一致 | **真喂生产实现**：`snapshot.detect_new` → `cases.compare_diff` → ok（新增 6 / 重复 15 / matched_by 逐键一致，pcode 键 1 条） | ✅ |
| 3 | 未解析显式标记 | 哨兵 `未解析` 与真值 `unparsed_sentinel` 同值；三态齐备且 partial 不当 parsed；空 pcode 三字段全未解析 | ✅ |
| 4 | 部门归一别名表单一来源 + 最长优先 | `load_org_aliases` 只读 K7 文件（`match_rule` 不符即拒绝）；E5 `\s` 拆分实测；观测池 60 条 0 缺失；未识别原样保留 + `alias_missing` | ✅ |
| 5 | 未挂原文不落库的代码级门禁 | K10 `ensure_item_fields` 读、写两路拦截 + 白名单外字段同拒（`test_forbidden_fields_rejected_on_write/on_read`） | ✅ |
| 6 | CLI `diff`/`parse` 整项退役 exit 3（落点找全） | `NOT_READY_COMMANDS` 现为 `digest/run/bench`；`test_cli_contract.py` 四处处置 + 行为级证明；README 命令表/新增第九节；`plan/00` D25–D27；grep 复核 `ci.yml` 无需改（它断言 bench，M4 才轮到） | ✅ |
| 7 | 双解释器全量测试绿 | 两条命令 exit 0；各收集 **287 项**（同数，本对话实测） | ✅ |
| 8 | 数据/真值面未回退 | 四生成器 `--check` + `capture_samples --check` exit 0；`verify-data` exit 0（119 条）；`selftest` 9/9；哨兵桩 grep 0 命中；**M3 未新增 `data/` 资产** | ✅ |
| 9 | HANDOFF-M4 落盘 | 本文件 | ✅ |

**偏差说明**：① "CI 绿"类判据按诚实口径写"本地等价校验，未接远端，CI 待首推验证"——**不是"CI 绿"**；
② 首版实现里 `parse` 产物的"双跑逐字节"测试误用了乱序输入（产物按输入序保持，乱序**应当**产出不同字节）——
实测后把断言改为"同输入双跑一致 + 输入序语义显式记录"，这不是实现缺陷而是断言口径修正；
③ `〔2026〕`（缺代字）实测为 `partial`（代字未解析、年份可解析）——与参照实现同语义，
测试初稿预期 `unparsed` 是错的，已按真值语义修正。

---

## 七、续接指针

- **本棒产出**：`src/policy_radar/snapshot.py`（真实现）、`src/policy_radar/parse.py`（真实现）、
  `tests/test_snapshot_diff.py`（29 项）、`tests/test_parse_pcode.py`（29 项）、
  `tests/test_cli_contract.py`（处置 + 行为级证明）、README（命令表 + 新增第九节）、
  `data/README.md`（新增第七节：M3 解析层对实测形态的处置）、
  `plan/00,03,04,05,06,07` 同步（决策 D25–D27、K23–K24）。
- **下一棒入口**：`plan/06-里程碑.md` 的 M4 节 + `plan/04-模块详设.md` 模块 4 + 本文件第二节。
- **下一棒出口**：`plan/HANDOFF-M5.md`（先落盘再结束对话）。
- **M4 最要紧的三件事**（按风险排序）：
  1. **K17 门槛随数据下发 + 退出码三语义锁进测试**（`bench` 0/1/2，缺失门槛 exit 2，代码零默认值——
     与 `verify.py::_load_thresholds` 同源，别写第二份 loader）；
  2. **探活可证伪打到端到端入口**（注入缺陷 → 基准必须报未达标；"只调函数"的探活防不住 CLI 层接线错误）；
  3. **`bench` 退役 exit 3 的落点找全**（D23：`ci.yml` 现在断言 bench exit 3，M4 落地时**必须同步改**，
     否则首推红；`test_not_ready_stderr_mentions_milestone` 也钉在 bench 上，同样要改）。
- **待用户拍板**：`plan/00-README总览.md` 的待定决策表 P1–P6（**仍未答复**；按推荐项 A 执行并如实记"按推荐默认执行"）。
  M3 实际按推荐执行/推进的：P5（快照只留当前 + git 历史留档 → `diff` 产出的更新快照是**运行时文件**（`out/snapshot.json`），
  `data/` 只放冻结资产）。
