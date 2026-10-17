# data/truth/：真值台账（只存输入与期望）

**核心纪律（K11）：本目录只存"输入与期望"，禁 `observed_*` 一类字段。**

判别口诀：**"我的基准，是在'跑被测对象'还是在'比对两份预先算好的答案'？"**
冻结"观测"会让基准退化成后者——引擎整个坏掉也照样全绿。观测由基准运行时**实算**。

| 文件 | 产出里程碑 | 内容 |
|---|---|---|
| `diff-truth.json` | M1 | 新增判定真值：输入 = 快照对 A/B；期望 = `new_ids` / `dup_ids` / `matched_by` |
| `pcode-truth.json` | M1 | 文号解析真值：人工标注 11 条 + 观测池语料 57 条真实文号 |
| `subscribe-truth.json` | M1 | 订阅命中真值：命中清单（含字段与位置）+ 剔除清单 + 0 命中清单 |
| `manifest.json` | M1 | 覆盖声明（**总数/采样数/采样清单三登记**）+ 验收门槛（**随数据下发，代码零默认值**） |
| `README.md` | M1 | 本文件：真值语义一次定清 |

---

## 一、真值语义（**一次定清**，后续里程碑不得各解释一套）

### 1.1 主期望 `expect` + 隐含结论 `also_expect`

每个真值文件都有两组结论：

- **`expect`**：主期望，即被测对象**必须**输出的结论（如 `new_ids` 清单）。
- **`also_expect`**：**隐含结论**——由输入即可推出的、可机器核验的布尔式
  （如"新增条目必然不在 A 中""命中条目必不被剔除"）。

`also_expect` 不是散文备注：它是**布尔值**，基准与 `verify-data` 会直接断言。
它的作用是把"逻辑上必然成立的关系"也变成判据——主期望对但关系破裂，
说明真值库自身不自洽（例如有人手改真值、或输入被换过）。

### 1.2 对账语义**单一实现源**：`src/policy_radar/cases.py` 的 `compare_*`

**这是最关键的一条。** 测试与基准（M4 的 `bench`）**共用** `cases.py` 里的
`compare_diff` / `compare_pcode` / `compare_subscribe`——否则会出现
"基准说达标、测试说不过"的双真相（两处各写一份比对逻辑，迟早漂移）。

对账函数的共同约定：

- 返回**差异清单**，不是模糊的"通过/不通过"——必须能说出**哪几条**不一致；
- **逐条点名**，并区分缺陷性质（如文号解析里"年份编造了"与"代字切错了"
  是不同性质的问题，必须能分开）；
- `matched_by` 判错（该按 `pcode` 命中却按 `id`）也算差异——**命中键判错是缺陷**，
  不能因为"结论碰巧对了"就放过。

### 1.3 参照实现（oracle）与生产实现的关系

`cases.py` 里的 `naive_diff` / `naive_parse_pcode` / `naive_match` 是**参照实现**，
**故意写得笨**（双重循环、位置切片、`str.find`），并且与生产实现走**不同代码路径**：

| 维度 | 参照实现（`cases.py`） | 生产实现（M3/M4） |
|---|---|---|
| diff 判重 | 双重循环逐条比 | 大概率用哈希索引 |
| 文号解析 | `str.find` + 位置切片，**不用正则** | 大概率用 `re` |
| 订阅匹配 | 归一化 + `str.find` | 大概率用正则或切片 |

**独立性守门**：`tests/test_cases_independence.py` 用**源码扫描**断言
生产模块（`snapshot.py` / `parse.py` / `subscribe.py`）**不得 import `cases`**。
判别口诀：**"把生产实现的判定逻辑注释掉，真值还能算出来吗？"**——能，因为真值只依赖
参照实现与输入数据。

> 为什么参照实现放在**包内**（`src/policy_radar/cases.py`）而不是 `tools/`：
> 真值台账要有**真调用方**（见第三节三问之③），用户敲的
> `policy-radar verify-data` 必须真读它；审计命令装在包里，故参照实现也须在包里
> （`src/` 不能反向依赖 `tools/`，`tools/` 不进安装包）。

### 1.4 不许改真值凑引擎

分两情形处置（**必须区分，别一律"改真值"**）：

1. **谓词自身不自洽**（如 `also_expect` 与 `expect` 互相矛盾）→ **只改谓词**；
2. **口径本身定错**（如"重复判定是否该并入 pcode"这个业务判断变了）→
   **引擎与真值同源修正**：两边一起改 + 重跑生成器 + `--check` 仍须位级通过。

判据：改完必须能让 `policy-radar verify-data` 与四个生成器的 `--check` 全部回绿。

---

## 二、三份真值台账的语义细节

### 2.1 `diff-truth.json`（新增判定）

- **输入**：`data/snapshots/pair-A.json`（旧，20 条）、`pair-B.json`（新，21 条）。
- **期望**：`new_ids`（应判新增）、`dup_ids`（应判重复）、`matched_by`
  （每条重复的**命中键**：`id` 或 `pcode`）。
- **判定口径（K4）**：`id` 相同 → 重复；否则 `pcode` **相同且非空** → 重复；
  否则新增。
- **五类形态**（`role_counts` 逐类登记，每类至少 1 条）：

  | 角色 | 含义 | 覆盖 |
  |---|---|---|
  | `carried` | B 保留 A 的条目 | 13 条（应判重复，`id` 键） |
  | `fresh` | B 中的全新条目 | 5 条（应判新增） |
  | `pcode_dup` | B 中 id 新、但 `pcode` 与 A 某条相同 | 1 条（**专测副键**） |
  | `empty_pcode_new` | `pcode` 空 + id 新 | 1 条（**边界**：空 pcode 不得致误判新增） |
  | `empty_pcode_same` | `pcode` 空 + id 同 | 1 条（**边界**：只能按 id 判） |

### 2.2 `pcode-truth.json`（文号解析）

- **输入**：`pcode` 原文（**两种来源**：人工标注表 11 条 + 观测池语料 57 条真实文号）。
- **期望**：`{agency_code, year, serial, status}`，`status ∈ parsed/partial/unparsed`。
- **哨兵值**：未解析字段一律用 **`"未解析"`**（`unparsed_sentinel` 字段登记该值，
  生产解析器必须照此输出——不得用 `None`/空串/`"-"` 各写各的）。
- **反向样例**（**必须有**，否则"解析器把什么都填上"永远不红）：
  - `国令第847号` → 年份 **必须** `未解析`（无 `〔〕`，不得编造年份），序号 `847`，状态 `partial`；
  - 空 `pcode` → 三字段**全** `未解析`，状态 `unparsed`。
- **正向对照**（防"适用域写太窄"）：
  - `工信部联规﹝2026﹞210号` → **全角括号变体必须解析出年份 2026**（M1 实测 E6）；
  - `农农发〔2026〕9 号` → 序号 **必须**是 `9`（**不带尾空格**，M1 实测 E7）。

### 2.3 `subscribe-truth.json`（订阅命中）

- **输入**：`data/config/subscribe.json`（订阅配置）+ `normalize.json`（归一表）
  + `data/snapshots/pair-B.json`（语料，21 条）。
- **期望**：
  - `hits`：`{item_id, keyword, field, offset}`（每词一条记录）；
  - `excluded`：被剔除条目 + 命中的 exclude 词 + **剔除前曾命中哪些 include 词**
    （可回溯"exclude 优先"确实生效）；
  - `zero_hit_item_ids`：既无 include 也无 exclude 命中的条目。
- **语义细节**：
  - `field` 按 **`FIELD_PRIORITY = (title, summary)`** 取**首次出现**（title 优先）；
  - `offset` = 命中词在**原始字段文本**中的起始下标。归一表**长度保持**
    （每条映射都是单字符 → 单字符），故 `offset` 在归一前后**同值**——
    `offset` 语义唯一、可审计（见 `data/config/README.md`）；
  - **同词重复配置**：按归一后关键词去重、保持配置顺序，故每词至多一条记录；
  - **exclude 优先**：任一 exclude 命中即**整条剔除**（不是"不标注"）。
- **六类边界形态**（`boundary_shapes` 逐类登记）：

  | 形态 | 条数 | 说明 |
  |---|---|---|
  | `multi_keyword` | 10 | 一条目命中 ≥2 个 include 词 |
  | `zero_hit` | 5 | **命中 0 次** |
  | `exclude_only` | 2 | **只命中 exclude** |
  | `exclude_and_include` | 1 | 命中 include 但也中 exclude（验证 exclude 优先） |
  | `duplicate_keyword_dedup` | 1 | **同词重复配置**（去重后少 1 条） |
  | `normalized_fullwidth` | 10 | **全半角归一**（ASCII 引号关键词命中全角引号正文） |

### 2.4 `manifest.json`（覆盖声明 + 门槛）

- **覆盖声明三登记**（防"只写分子的假覆盖"）：逐形态登记
  **规则包总数 / 真值库采样数 / 采样清单**，并**显式声明"抽样覆盖、非穷举"**。
- **验收门槛随数据下发**：`thresholds` 落在本清单，基准层**只读**；
  缺失即报配置错误（exit 2），**不得回落代码里的默认值**——
  门槛内联进代码就是"抄进代码的第二份真相"。

---

## 三、"冻结"名不副实的三问（M1 实测齐备）

| 问 | 判据 | M1 证据 |
|---|---|---|
| ① **入库件在不在** | `git ls-files` 查得到 | 三份真值 + 清单 + 快照对 + 配置 + 样本全部入版本管理（`.gitignore` 已锚定，见 `tests/test_repo_hygiene.py`） |
| ② **有没有位级守门** | 生成器 `--check` 重跑逐字节一致 | 四个生成器各有 `--check`（两层：形态正确 + 重跑逐字节）；`tests/test_generators_check.py` 真跑它们 |
| ③ **有没有真调用方** | `grep` 得到调用方，且**用户敲的那条命令**真读它 | `policy-radar verify-data --data-root data` 真读真值库并实算观测比对（`src/policy_radar/verify.py`）；`grep -rn "verify" src/` 得到 CLI 挂载点 |

**第③问的运行时证据**：`verify-data` 把真值里的**输入**喂给参照实现**实算**，
再用共用对账语义与**期望**逐条比对 → 输出"3 套件全部自洽（比对 119 条）"。
它是**可证伪**的：把真值改坏（删一条 `new_ids`）→ 报 `new_ids 多出：['26782365']`、
exit 1；注入 `observed_hits` 字段 → 报 K11 违规、exit 1（两项均已实测）。

---

## 四、重生成纪律

- 本目录是**生成器产物**，**禁手改**。改体例/生成器 → 用固定 seed 重跑整目录并提交，
  配 `--check` 位级守门。
- 生成器（`tools/`，不进安装包）：`gen_snapshot_pairs.py` / `gen_pcode_cases.py` /
  `gen_subscribe_cases.py` / `gen_truth_manifest.py`。
- 生成顺序（有依赖）：快照对 → 订阅真值（依赖 pair-B）→ 总清单（汇总三份真值）。
  `gen_pcode_cases.py` 只依赖观测池样本，可任意顺序。
- `.gitattributes` 已标 `data/truth/*.json -text`（防克隆时 EOL 归一化改写字节 →
  sha256 / 逐字节比对失配）。
