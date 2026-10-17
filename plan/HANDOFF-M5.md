# HANDOFF-M5：交接给"交付"里程碑

> 用法（新对话启动命令，用户侧拼绝对路径）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M5.md" 继续完成任务`
> 上一棒：**M4 基准**（本对话完成）
> 下一棒：**M5 交付**（中文 Markdown/HTML 日报 + `run` 端到端编排 + README 完整化）

---

## 一、当前进度 + 证据（本对话实测）

### 已完成

| 项 | 证据 |
|---|---|
| **`subscribe.py` 真实现（不是填桩）** | `src/policy_radar/subscribe.py`（约 250 行）：`match_items`（K8 命中判定，**生产走正则预编译 + `match.start()`**，与 oracle 的 `str.find` 不同代码路径）/ `compile_patterns`（归一后去重 + 保持配置顺序）/ `validate_subscribe_config` / `validate_norm_map`（K16 长度保持校验）/ `sort_hits_like_truth` / `load_subscribe_inputs`（配置 + 归一表单一来源装载，口径不符即 `UsageError` exit 2） |
| **生产订阅实现对真值逐条一致（真喂生产实现）** | `match_items` → `cases.compare_subscribe` → **ok**：命中 32 / 剔除 3 / 零命中 5，`field`/`offset` 逐键一致（含 ASCII 引号关键词命中全角引号正文的归一化样本）；`offset` 切口定位回**原始字段文本**逐条实测（K16 长度保持 → 归一前后同值） |
| **`bench.py` 真实现（M4 核心交付）** | `src/policy_radar/bench.py`（约 300 行）：三套件一键（`bench_diff` / `bench_pcode` / `bench_subscribe`，生产实现实算）→ `cases.compare_*` 对账 → `evaluate_gates` 双边门 → `cmd_bench`（CLI） |
| **门槛随数据下发（K17），同源零默认值** | bench 复用 `verify._load_thresholds`（测试断言**同一函数对象**）；`REQUIRED_THRESHOLDS` 七个门槛键缺任一 → exit 2；**"没门槛"是配置错误（2）不是"未达标"（1）**——`test_bench_missing_threshold_is_usage_error_not_degraded` 锁死 |
| **退出码三语义 0/1/2 锁进测试** | 实测：`bench --data-root data` → **0**（3 套件达标，比对 119 条）；`--only nope` → **2**；空数据根 → **2**；`--only subscribe` → 0（单套件通路也对） |
| **探活可证伪，打到端到端入口** | 三条探活全部经 `main()`（CLI 层）注入缺陷：① diff 的 pcode 键判定打掉 → **exit 1** 且点名 `26276349`；② subscribe 命中短路成空 → **exit 1** 且"命中缺少 / 检出门未达 / 命中召回"三重点名；③ pcode 解析恒 unparsed → **exit 1** 且"文号字段命中率"点名；④ **阳性对照**（不注入 → exit 0）防"怎么都能红"的假门 |
| **双边门** | 第一边 = `compare_*` 的 ok（误报 0：matched_by 键判错 / 命中位置错 / 剔除判错均点名）；第二边 = `evaluate_gates`（diff 新增/重复命中率、pcode 字段与三态命中率、subscribe 命中召回/精确率/剔除召回，缺多少条逐 id 列出） |
| **CLI `bench` 整项退役 exit 3** | `NOT_READY_COMMANDS` 现只剩 `digest/run`；`test_cli_contract.py`：`_min_args` 删条 + `test_fetch_diff_parse_bench_are_retired_from_not_ready` + `test_other_commands_still_not_ready`（`{"digest","run"}`）+ `test_not_ready_stderr_mentions_milestone` **改用 `digest`（断言 M5）** + `test_retired_commands_do_real_work_offline` 扩 bench + 新增 bench 三语义子进程测试；README 命令表 + 新增「真值基准（M4）」节（第十节，原十/十一节顺延为十一/十二）；`plan/00` 决策 D28 |
| **退出码 3 落点 grep 复核（D23 教训）** | `grep -rn "exit 3\|EXIT_NOT_READY\|尚未就绪"` 全仓跑过：**`ci.yml` 已同步**（`bench exit 3` 步骤换成 `digest exit 3`，另新增 `bench exit 0` 达标冒烟）；其余命中均为 errors.py 语义定义 / cli.py 注释 / 历史记录（HANDOFF、plan 各节的当时状态描述），无需改 |
| **测试套件** | **307 项**（3.8 与 3.12 **同数**），双解释器全绿；新增 `tests/test_subscribe_bench.py`（**20 项**）；`test_cli_contract.py` 净变动（改四处 + 加两条 bench 测试） |
| **数据/真值面未回退** | 四生成器 `--check` 各 exit 0；`capture_samples.py --check` exit 0；`verify-data --data-root data` → **exit 0（3 套件自洽，比对 119 条）**；`selftest` → exit 0（9/9）；**M4 未新增 `data/` 资产**；哨兵桩 grep 0 命中 |

### 诚实口径（**无远端，CI 从未跑过**）

- 全程**没有远端**、**一次 CI 都没跑过** → 凡 CI 类判据一律写"**本地等价校验（未接远端，CI 待首推验证）**"，**不写"CI 绿"**。
- 本机可实跑的等价物：① 双解释器（3.8.8 + 3.12.10）全量 pytest（各 **307 项**）；② 四生成器 + 样本登记 `--check`；③ `verify-data` 端到端 exit 0；④ **bench 三套件生产实现全量实跑达标（exit 0）**；⑤ **探活三连**（注入缺陷 → exit 1 逐条点名；阳性对照 exit 0）；⑥ CLI 退出码契约（子进程真跑，0/1/2/3 全路径）。
- **不可本机实跑的缺口**：CI 矩阵的 ubuntu/Windows 环境差异、CI 步骤的 shell 差异、`actions/setup-python` 的 3.8 可用性 → **待首推验证**。

### M4 设计要点（写给下一棒）

1. **订阅命中接口（M5 直接复用）**：`subscribe.match_items(items, include, exclude, norm_map)`
   → `(hits, excluded, zero_hit_ids)`；每条 hit = `{item_id, keyword, field, offset}`
   （`field` ∈ title/summary，`offset` 是原始字段文本里的起始下标——日报高亮直接用）；
   `excluded` 含 `include_matched_before_exclusion` 可回溯。**被剔除条目整条不进日报**。
2. **条目装载一律走 `snapshot.load_items_file()`**（K23 三类产物通吃）；
   **日报要按日期排 → 消费 diff 产物**（它已按 K5 规范序排好），不要自己再排。
3. **M5 的 `run` 编排**照 `fetch → diff → parse → subscribe → digest` 串：`--out-dir`
   已在 parser 预置；`--channels` 默认 `gwy,bm`。产物一律写 `out/`（`.gitignore` 已覆盖）。
4. **K9（渲染层零判定）**：`report.py` 只做渲染，判定/过滤/排序都不进渲染层；
   渲染出口**常驻零外链断言**（AST 守门，M5 测试写）；AST 扫描只扫 import 语句，
   别扫子串（M3 教训，见本文件第四节第 15 条）。
5. **错误通路**：`cmd_bench` 读真值/门槛已显式包 `UsageError`（exit 2）；
   `cmd_digest` 同款处置。渲染层"无新增"显式写"本次无新增"（不落空文件，
   `plan/04` 模块 5 的既定口径）。

---

## 二、下一棒（M5）待办

按 `plan/06-里程碑.md` 的 M5 节与 `plan/04-模块详设.md` 的**模块 5 + 编排层**执行：

1. **新建 `src/policy_radar/report.py`**（真文件，不是填桩）：中文日报生成。
   - 输入：diff 产物（新增条目，规范序）+ parse 产物（文号/部门）+ 订阅命中；
   - 输出：Markdown + HTML 双格式（`--format md/html/both`，parser 已预置）；
   - **渲染层零判定（K9）** + 渲染出口**常驻零外链断言**（HTML 无 `http://`/`https://`
     外部引用——条目自带的 `url` 是**原文链接**属正常字段，"零外链"指**渲染资源**
     （脚本/样式/字体）零外部引用，口径在测试里写清）；
   - 两格式**内容对等断言**（同输入下信息等价）；双跑逐字节一致（无时间戳）。
2. **新建 `pipeline.py`（`run` 子命令）**：`fetch → diff → parse → subscribe → digest`
   一条命令出结果；`--channels`/`--out-dir` 已预置；网络异常按 fetch 的 1/4 语义透传。
3. **CLI `digest` / `run` 整项退役 exit 3**（M4 同款流程）：
   - 删 `NOT_READY_COMMANDS` 两条目 → 接线 → `test_cli_contract.py`：
     `_min_args` 删条 / `test_not_ready_stderr_mentions_milestone`（此时**没有**未就绪
     命令了，该测试要改写成"NOT_READY_COMMANDS 为空"类断言）/ 
     `test_other_commands_still_not_ready` 的集合断言改成 **空集** /
     退役 ≠ 删语义的行为级证明（digest 真渲染 + run 真编排，离线样本跑）；
   - **D23 教训：grep 找全落点**。当前已知：`cli.py` / `test_cli_contract.py` /
     `README.md`（命令表两处：digest、run） / `plan/00` / `plan/03` / `plan/06` /
     **`.github/workflows/ci.yml`（现在断言 `digest --new-items n.json` exit 3
     ——M5 落地时必须换，比如换成"已落地命令的用法错误"类联网无关冒烟）**；
     `errors.py` 的 `EXIT_NOT_READY` 常量与 `NotReadyError`：全部命令落地后
     **保留语义但不再有调用方**——保留（退出码 3 是对外契约的一部分，README 退出码表已写）。
4. **双解释器全量测试绿** → 回写 `plan/00` / `06`（+ `03` / `04` / `07` 相应行）→
   **`plan/HANDOFF-M6.md`** → commit。

**M5 的 DoD 全文见 `plan/06-里程碑.md` 的 M5 节。**

---

## 三、既定口径清单（K 编号，"动了会打挂测试"的约定）

**改任何一条前先对照本表，改完重跑全量测试 + 生成器 `--check` + `verify-data` 确认不回退。**

| K | 口径 | 落点（单点） | 守卫 |
|---|---|---|---|
| K1 | 统一 schema 字段集合与**顺序** = `SCHEMA_FIELDS` 十项 | `src/policy_radar/model.py` | `tests/test_model.py::test_schema_fields_exact_and_ordered` |
| K2 | 退出码语义 `0/1/2/3/4`；**3 退役落点要 grep 找全（不止四处）** | `src/policy_radar/errors.py` + CI | `tests/test_cli_contract.py` |
| K3 | 序列化冻结参数 + LF + 尾换行 + 原子写 | `src/policy_radar/serialize.py` | `tests/test_serialize.py`（含"写盘单点"源码扫描：`json.dump(` 不得出现在其它模块） |
| K4 | 去重主键 = **`id`**；`index` 副键；`pcode` 非空时并入判定 | `snapshot.detect_new()`；M1 已落 oracle 版 `cases.naive_diff` | `tests/test_snapshot_diff.py` + `tests/test_truth_gate.py` |
| K5 | 清单排序键 = `(pubtimeStr 倒序, id 升序)`，**全程不读时钟** | `snapshot.canonical_order()`（生产单点）/ `report.py`（M5）；`tools/_genlib.canonical_order` 是生成侧实现（包内不得 import） | `tests/test_snapshot_diff.py` + `test_truth_gate.py` |
| K6 | 文号解析三态 `parsed/partial/unparsed`；**代字不做白名单硬编码**；哨兵 `未解析` | `parse.parse_pcode()`；M1 已落 oracle 版 `cases.naive_parse_pcode` | `tests/test_parse_pcode.py` + `tests/test_truth_gate.py` |
| K7 | 部门别名表**单一来源** `data/config/org-aliases.json`；**最长优先（前缀匹配）** | `parse.load_org_aliases()` / `parse.parse_orgs()` | `tests/test_parse_pcode.py` |
| K8 | 订阅匹配 = 子串包含 + 全半角归一；**exclude 命中整条剔除**；同词去重 | `subscribe.match_items()`（M4 已落地）；M1 已落 oracle 版 `cases.naive_match` | `tests/test_subscribe_bench.py` + `tests/test_truth_gate.py` |
| K9 | 渲染层**零判定** + 渲染出口**常驻零外链断言** | `report.py`（M5 新建） | M5 测试（AST 守门） |
| K10 | 快照字段白名单（**无全文**）；出现 `content/body/fulltext` 即红；**白名单外字段同样拒** | `snapshot.ensure_item_fields()`（读、写两条路径）；`model.FORBIDDEN_SNAPSHOT_FIELDS` | `tests/test_snapshot_diff.py` + `tests/test_truth_gate.py` |
| K11 | 真值库**只存输入与期望**，禁 `observed_*`；观测由基准运行时实算 | `data/truth/` + `bench` | `tests/test_truth_gate.py` + `cases.find_observed_fields` + `verify-data` 运行时检 |
| K12 | 无 LLM、**零第三方运行时依赖**、**3.8 语法底线** | 全仓 | `test_readme_gate.py` 测试面/安装面 |
| K13 | 数据根定位优先级：**显式参数 > 环境变量 `POLICY_RADAR_DATA` > 源码树相对** | `src/policy_radar/paths.py` | `tests/test_selftest.py`（测试**显式传** `--data-root`） |
| K14 | 参照实现（oracle）在包内 `cases.py`；**生产模块不得 import 它** | `src/policy_radar/cases.py` | `tests/test_cases_independence.py`（源码扫描：`snapshot.py`/`parse.py`/`subscribe.py` 不得 import `cases`——**M4 的 subscribe.py 已在扫描面里且实测绿**） |
| K15 | 对账语义**单一实现源** = `cases.compare_*`（测试与基准共用） | `src/policy_radar/cases.py` | M4 基准与测试共用同一份（`bench.py` 显式 import） |
| K16 | 归一表**长度保持**（单字符 → 单字符），使 `offset` 语义唯一 | `data/config/normalize.json`；**M4 生产侧 `subscribe.validate_norm_map` 同口径校验** | `tools/gen_subscribe_cases.py::assert_norm_map_is_length_preserving` + `tests/test_subscribe_bench.py` |
| K17 | 验收门槛**随数据下发**（`data/truth/manifest.json` 的 `thresholds`），**代码零默认值**；缺失即 exit 2 | `src/policy_radar/verify.py::_load_thresholds`；**M4 基准已同源复用**（`bench._load_thresholds` 即 `verify` 同一函数） | `tests/test_truth_gate.py` + `tests/test_subscribe_bench.py::test_bench_missing_threshold_is_usage_error_not_degraded` |
| K18 | 真值台账须有**真调用方**：`verify-data` 真读并实算比对 | `src/policy_radar/verify.py` | `tests/test_truth_gate.py` 端到端真跑 |
| K19 | 抓取三类异常**处置分离**：传输层失败可隔离 / 条目级不合规丢弃降级 / 硬失败立即 exit 4 | `src/policy_radar/fetch.py`（`ChannelUnavailable` + `partition_valid_items`） | `tests/test_fetch.py` |
| K20 | 抓取产物的**三个条数不得混用**：`returned`（服务器真返回）/ `kept`（通过校验）/ `dropped`（丢弃） | `fetch.fetch_channel` 元信息 + 产物 `reconciliation` | `tests/test_fetch.py` |
| K21 | 对账行格式 `请求 N 条 / 声明 totalCount M / 实际 K` **必须真打印**（degraded 时 M 记"未知"，不得拿 0 冒充） | `fetch.reconciliation_lines()` 单点 | `tests/test_fetch.py::test_reconciliation_line_*` |
| K22 | `fetch` 产出条目顺序 = **API 返回序**（`item_order: "api"`）；规范排序（K5）只在快照/渲染层 | `fetch.build_output()`；`snapshot.canonical_order()` 负责重排 | `tests/test_fetch.py` + `tests/test_snapshot_diff.py` |
| K23 | 承载条目的产物**按 `format` 分派**（`policy-radar-fetch` / `policy-radar-snapshot` / `policy-radar-diff`）；**未知格式显式拒绝（exit 2）** | `snapshot.load_items_file()` 单点 | `tests/test_snapshot_diff.py::test_load_items_file_*` |
| K24 | `diff` **首跑语义**：省略 `--snapshot` = 首次运行（全部计入新增 + stdout 明示）；**给了路径但读不到 = exit 2**，不得静默回落成首跑 | `snapshot.cmd_diff()` | `tests/test_snapshot_diff.py::test_cmd_diff_missing_snapshot_is_usage_error_not_first_run` |
| **K25** | **基准双边门**：对账 ok（误报 0）**之外**必须配检出门（真值期望逐样本点名，阈值随 manifest）；生产实现整条空转时第一边可能漏红，检出门必红 | `bench.evaluate_gates()` | `tests/test_subscribe_bench.py`（探活②：命中短路成空 → "命中召回"点名） |
| **K26** | **探活打到端到端入口**（CLI 层经 `main()` 注入缺陷），不是只调函数；阳性对照（不注入 → exit 0）防假门 | `tests/test_subscribe_bench.py` 三条探活 + 一条阳性对照 | 同左 |

> **M4 新增 K25–K26**。K25/K26 是"基准可信"的两根支柱：空转的生产实现骗不过
> 检出门，假绿的基准逃不过阳性对照。M5 不需要动它们，但**别拆**。

---

## 四、本机环境坑（**只写实测过的**）

1. **用 `py` 不是 `python`**（后者可能是商店占位符）；跑脚本一律 `py -X utf8`（中文控制台编码）。
2. **本机双通道**：`py -0p` 实测有 **3.8.8-64** 与 **3.12.10-64**。**项目底线 3.8**，所有代码只用 3.8 语法。
3. **`/tmp` 与 Windows Python 路径不通**：临时文件一律用工作区相对路径或 `tempfile`（pytest 的 `tmp_path` 可用）。
4. **pytest 计数当轮实测**：M4 实测 `tests/` 收集 **307 项**（3.8 与 3.12 **同数**）。
   **别抄任何一棒的数字，每轮重新数**（M2 已实测过一次上一棒数字对不上）。
5. **写盘 API 3.8 差异**：`Path.write_text(newline=)` 是 3.10+ 参数 → 用 `open(..., newline="\n")` 或 `write_bytes`。
6. **`PYTHONDONTWRITEBYTECODE=1`**：pyc 偶发损坏会导致"unknown opcode / 随机 FAIL / 测试数波动"；出怪错先清 `__pycache__` 再跑。
7. **编码三加固已就位**（别在后续里程碑拆掉）：① 入口 `_ensure_utf8_stdio()`；② 子进程调用一律显式 `encoding=`；③ CI `env: PYTHONUTF8=1`。
8. **网络类操作必带超时**；**想让"网络不可达"可控复现**：设 `https_proxy=http://127.0.0.1:9` → 真 CLI 稳定 exit 4 且不产文件。
9. **真实 API 响应含每请求不同的字段** → **重抓会改变样本 sha256**：正常更新，须连同 `manifest.json` 一起提交。**M4 未重抓样本**，sha256 不变。
10. **CI 未实跑**：本机模拟不了 ubuntu/Windows 矩阵与 CI 的 shell → **预算"首推至少一轮诊断"**。
11. **tools/ 目录不在安装包里**：**包内不得反向依赖 `tools/`**；M4 的 `subscribe.compile_patterns`（正则去重）与 oracle 的 `dedup_keywords` 是两份独立实现——**别"顺手统一"成一个 import**（K14 扫描会红）。
12. **`fetch`/`diff`/`parse`/`bench` 的产物不入库**：默认都在 `out/`（已锚定在 `.gitignore`）。跑完 CLI 后 `git status` 应干净。
13. **argparse 陷阱**：`getattr(args, "x", DEFAULT) or DEFAULT` 会把 falsy 合法值静默改成默认值。参数解析一律显式判 `None`（M4 的 `--only` 就是显式判 `None`——`--only ""` 与省略不同）。
14. **docstring 里的 `\s`** 会触发 3.12 的 `DeprecationWarning: invalid escape sequence` → 模块/函数 docstring 含正则记号时用 **raw string（`r"""…"""`）**（M4 的 `subscribe.py` docstring 已照此处理）。
15. **源码扫描测试要扫 import 语句而非子串**：用 `re.search(r"from\s+\.?cases\s+import|import\s+cases\b|policy_radar\.cases", src)`（M3 教训，M4 复用同款）。
16. **中文 heredoc 进 `py - <<'EOF'` 会挂**（stdin 编码声明）：改写临时 `.py` 脚本文件再 `py -3.8 -X utf8 <script>` 跑（M4 实测：内联 UTF-8 源码触发 `SyntaxError: Non-UTF-8 code`）。
17. **monkeypatch 生产函数要打在调用方模块上**：`bench.py` 里是 `from .snapshot import detect_new` 的**模块级名绑定** → 探活 patch `bench_mod.detect_new`（不是 `snapshot.detect_new`），否则 bench 走的仍是原函数（M4 实测同款注意事项写进了测试注释）。

---

## 五、关键命令速查

```bash
# --- 测试（双解释器，全量） ---
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest 2>&1 | tail -2   # 看"307 passed"这类计数

# --- 单文件跑 ---
py -3.8 -X utf8 -m pytest -q tests/test_subscribe_bench.py
py -3.8 -X utf8 -m pytest -q tests/test_cli_contract.py

# --- CLI 冒烟（退出码语义） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar version                        # 0
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar selftest --data-root data      # 0（9/9）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar verify-data --data-root data   # 0（3 套件 / 119 条）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar bench --data-root data          # 0（3 套件达标，比对 119 条）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar bench --only subscribe --data-root data  # 0
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar bench --only nope --data-root data       # 2
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar digest --new-items n.json       # 3（M5 未就绪）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar run                             # 3（M5 未就绪）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar diff --snapshot data/snapshots/pair-A.json --current data/snapshots/pair-B.json --out out/diff.json --snapshot-out out/snapshot.json   # 0；新增 6 / 重复 15（pcode 键 1）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar parse --input data/snapshots/pair-B.json --data-root data          # 0；parsed 17 / partial 2 / unparsed 2
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --channel nope   # 2
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --pages 0        # 2（发请求前拦下）

# --- 抓取（真站点；产物在 out/，不入库） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --channel gwy --pages 1 --n 5 --delay 1.5 --out out/live-gwy-n5.json   # 期望 0

# --- 数据生成与位级守门（两层） ---
py -3.8 -X utf8 tools/gen_snapshot_pairs.py --check       # 0
py -3.8 -X utf8 tools/gen_pcode_cases.py --check          # 0
py -3.8 -X utf8 tools/gen_subscribe_cases.py --check      # 0
py -3.8 -X utf8 tools/gen_truth_manifest.py --check       # 0
py -3.8 -X utf8 tools/capture_samples.py --out-dir data/samples --check   # 0（4 份 sha256 一致）

# --- 哨兵桩排查（收尾期固定动作） ---
grep -rn "NotImplementedError\|TODO: 实现\|placeholder" src/ tools/

# --- 退出码 3 退役落点排查（M5 退役 digest/run 时用；D23 教训） ---
grep -rn "exit 3\|EXIT_NOT_READY\|尚未就绪" --include=*.py --include=*.md --include=*.yml . | grep -v "^./.git/"
```

---

## 六、DoD 逐项 checklist（M4）

| # | 判据 | 验证方式（**在哪验的**） | 状态 |
|---|---|---|---|
| 1 | 基准一键跑通，退出码三语义 0/1/2 锁进测试 | `test_subscribe_bench.py::test_bench_exit_codes_three_semantics` + `test_cli_contract.py` 三条 bench 子进程测试；实测 0/2/2 全对上 | ✅ |
| 2 | 门槛随 manifest 下发、代码零默认值、同源 verify | 同一函数对象断言 + 缺 thresholds/缺键 → exit 2 | ✅ |
| 3 | 每套件可证伪探活，打到端到端入口 | 三条探活（diff 键判错 / subscribe 空转 / pcode 恒未解析）→ exit 1 逐条点名 + 阳性对照 exit 0 | ✅ |
| 4 | 双边门（误报 0 + 检出率 ≥ 阈值逐样本点名） | `evaluate_gates` 七门槛键全量判定；探活②三重点名 | ✅ |
| 5 | 真值库全量实跑（三份真值全喂生产实现） | bench 实测：diff 21 / pcode 58 / subscribe 40，全 ok | ✅ |
| 6 | CLI `bench` 整项退役 exit 3（落点找全，含 CI） | `NOT_READY_COMMANDS={"digest","run"}`；ci.yml 换 `digest` + 新增 `bench exit 0`；grep 复核 | ✅ |
| 7 | 生产订阅实现对真值逐条一致 | `compare_subscribe` ok（32/3/5），field/offset 逐键；offset 切口回定位原始文本 | ✅ |
| 8 | 双解释器全量测试绿 | 两条命令 exit 0；各收集 **307 项**（同数，本对话实测） | ✅ |
| 9 | 数据/真值面未回退 | 四生成器 + capture_samples `--check` exit 0；`verify-data` exit 0（119 条）；`selftest` 9/9；哨兵桩 grep 0 命中；**M4 未新增 `data/` 资产** | ✅ |
| 10 | HANDOFF-M5 落盘 | 本文件 | ✅ |

**偏差说明**：① "CI 绿"类判据按诚实口径写"本地等价校验，未接远端，CI 待首推验证"；
② `bench` 的 stdout 摘要行沿用 `verify-data` 的 `[OK]/[FAIL] 套件 语料/比对` 格式
（两命令输出形态一致，用户心智统一）；③ 探活方式用 monkeypatch 生产函数
（打在 `bench_mod` 的绑定名上）而非改真值/数据文件——**不污染冻结数据**是硬约束。

---

## 七、续接指针

- **本棒产出**：`src/policy_radar/subscribe.py`（真实现）、`src/policy_radar/bench.py`
  （真实现）、`tests/test_subscribe_bench.py`（20 项）、`tests/test_cli_contract.py`
  （bench 退役处置 + 三语义测试）、README（命令表 + 新增第十节「真值基准（M4）」）、
  `.github/workflows/ci.yml`（digest exit 3 + bench exit 0 两步）、
  `plan/00,03,04,06,07` 同步（决策 D28、K25–K26、M4 状态与计数）。
- **下一棒入口**：`plan/06-里程碑.md` 的 M5 节 + `plan/04-模块详设.md` 模块 5 +
  编排层 + 本文件第二节。
- **下一棒出口**：`plan/HANDOFF-M6.md`（先落盘再结束对话）。
- **M5 最要紧的三件事**（按风险排序）：
  1. **K9 渲染层零判定 + 零外链断言的口径**（"零外链"= 渲染资源零外部引用，
     不是"条目 url 字段不许出现"——口径写错测试会自相矛盾，先在测试 docstring 定稿）；
  2. **`digest`/`run` 退役的落点找全**（D23：`ci.yml` 现在断言 `digest` exit 3，
     M5 落地时**必须同步改**；`test_not_ready_stderr_mentions_milestone` 在
     NOT_READY_COMMANDS 清空后要改写成空集断言）；
  3. **双跑逐字节一致**（日报无时间戳；`run` 编排产物的确定性依赖 fetch 的
     `captured_at` 是元信息不参与判定——M2 已守，M5 别破）。
- **待用户拍板**：`plan/00-README总览.md` 的待定决策表 P1–P6（**仍未答复**；
  按推荐项 A 执行并如实记"按推荐默认执行"）。M4 实际按推荐推进的：无新增
  （P4 的"预置订阅词"已在 M1 落为观测池真实关键词，M4 沿用未改）。
