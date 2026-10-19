# 政策文件雷达（policy-radar）

> **定位宣言**：本地定时抓取中国政府网政策文件库，把"今日新发政策 + 发文字号 + 发布部门 + 摘要"
> 变成一份可订阅关键词的中文日报——**快照 diff 检测新增，不是每次全量翻页**。
> 企业法务 / 合规 / 政策研究 / 申报人员要盯发文，分散逐条翻页极易漏。

- 形态：**纯本地 Python CLI**（无服务器、无 GPU、无账号、无遥测）
- 数据源：中国政府网搜索 API 两个公开频道（国务院政策库 + 部委政策库）
- 版本：`0.1.0`（M4 基准；里程碑进度见 `plan/06-里程碑.md`）
- 方法论与全套计划文档：`plan/00-README总览.md`

---

## 一、快速上手

```bash
# 安装（唯一 extras = dev，测试期依赖）
python -m pip install --upgrade pip
pip install -e ".[dev]"

# 查看版本与自检
policy-radar version
policy-radar selftest --data-root data

# 双源抓取：抓取国务院 + 部委两频道，写统一 schema 的条目文件
policy-radar fetch --pages 1 --n 20 --delay 1.5 --out out/fetched.json

# 快照 diff：相对上次快照判新增/重复（省略 --snapshot = 首次运行，全部计入新增）
policy-radar diff --snapshot out/snapshot.json --current out/fetched.json

# 文号解析 + 部门归一：三态（parsed/partial/unparsed），未解析显式标记
policy-radar parse --input out/diff.json --data-root data

# 数据自审：真值台账一致性核对（实算观测 vs 期望）
policy-radar verify-data --data-root data

# 真值基准：三套件（diff/pcode/subscribe）生产实现实算 + 门槛判定
policy-radar bench --data-root data          # 0 达标 / 1 未达标 / 2 用法错误
policy-radar bench --only subscribe --data-root data

# 自检必须"可证伪"：把数据根指向空目录会返回非 0
policy-radar selftest --data-root ./empty-dir
```

> **为什么先升级 pip**：Python 3.8 自带的 pip 20.2.3 **不支持 PEP 660 可编辑安装**，
> 直接 `pip install -e .` 会报 `editable mode currently requires a setup.py based build`
> （实测，见第四节「已知环境问题」）。**本项目当前底线是 Python 3.12**，该坑已不再触发；
> 这一行保留是因为它对更老的解释器/更旧的 pip 仍是必要前置，且成本为零。

**退出码语义**（判据以本节为准，非 0 不等于"跑挂了"）：

| 退出码 | 语义 |
|---|---|
| 0 | 成功完成 |
| 1 | 完成但有降级 / 检出问题（有频道抓取失败、有条目未过 schema 校验被丢弃、基准未达标） |
| 2 | 用法错误 / 输入不可用（未知子命令、参数错、输入文件缺失、坏格式） |
| 3 | **能力未就绪**（语义保留的对外契约；M5 后全部子命令已落地，无调用方） |
| 4 | 外部依赖不可用（网络不可达且**所有**频道都失败、API 返回非 200、API 结构异常、抓取自证不符） |

## 二、命令总表

| 命令 | 里程碑 | 当前行为 |
|---|---|---|
| `policy-radar version` | M0 | 打印版本号，exit 0 |
| `policy-radar selftest` | M0 | 自检（可证伪），exit 0/1 |
| `policy-radar verify-data` | M1 | 数据自审：真值台账一致性核对，exit 0/1/2 |
| `policy-radar fetch` | M2 | 双源抓取：统一 schema 条目文件 + totalCount 对账，exit 0/1/2/4 |
| `policy-radar diff` | M3 | 快照 diff：id/pcode 双键判定 + 规范序更新快照，exit 0/2 |
| `policy-radar parse` | M3 | 文号三态解析 + 部门归一（别名表单一来源），exit 0/2 |
| `policy-radar bench` | M4 | 真值基准：三套件生产实现实算 + 门槛判定（随数据下发），exit 0/1/2 |
| `policy-radar digest` | M5 | 中文日报生成：新增条目 + 订阅命中 → Markdown/HTML 双格式，exit 0/1/2 |
| `policy-radar run` | M5 | 端到端编排：抓取→diff→解析→订阅→日报一条命令出结果，exit 0/1/2/4 |

两条等价通路（`sys.path` 来源不同，**两者都要能跑**）：

```bash
policy-radar version                              # 安装后的 console script
python -m policy_radar version                    # 模块形态（需要 __main__.py）
```

参数示例（各命令的完整参数见 `policy-radar <command> --help`）：

```bash
policy-radar fetch --pages 1 --n 20 --delay 1.5 --out out/fetched.json
policy-radar fetch --channel gwy --channel bm --pages 2 --n 20
policy-radar diff --snapshot snapshots/last.json --current out/fetched.json
policy-radar diff --current out/fetched.json
policy-radar parse --input out/new-items.json --data-root data
policy-radar digest --new-items out/diff.json --hits out/subscribe.json --format both
policy-radar run --channels gwy,bm --out-dir out
policy-radar run --snapshot out/snapshot.json --out-dir out
policy-radar bench --only diff --data-root data
policy-radar verify-data --data-root data
```

## 三、数据源与局限（⚠️ 局限原样披露）

**数据源**：中国政府网搜索 API（公开 JSON 接口，基准日 2026-10-15 实测，M0 复测日 2026-10-17）：

- 国务院政策库：`https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_gwy&q=&p=1&n=5&sort=pubtime&sortType=1`
- 部委政策库：同 URL 换 `t=zhengcelibrary_bm`

取数路径与字段依据逐条留档在 `data/README.md`（含 M0 实测勘误表）。

### ⚠️ 局限（必须披露，不得省略）

1. **日期过滤参数未生效**：API 的 `mintime/maxtime`（`timetype=timedef`）实测**仍返回全量** →
   本工具**不依赖日期参数做增量**，变更检测一律走"上次快照 diff"。
2. **gov.cn 旧路径大面积 404**：直连 `www.gov.cn/zhengce/zuixin/home.htm` 实测返回 404 →
   抓取目标 URL 一律以 API 返回的 `url` 字段为准，**不自行拼路径**。
3. **部委频道 `index` 字段为空**：实测 30/30 为空 → 去重主键用 `id`，`index` 只作副键。
4. **`pcode` 可空**：部委频道实测 3/30 为空 → 文号字段可空，解析失败**显式标"未解析"**，不编造。
5. **文号形态比题面更杂**：实测含 `国令第847号`（无年份）、`国知发服字〔2026〕29号`（多字代字）、
   **全角括号 `﹝﹞`**（码位与 `〔〕` 不同）、**序号与"号"间有空格**（`农农发〔2026〕9 号`）等形态。
6. **`puborg` 多部门分隔符不止半角空格**：实测含 **U+2002 EN SPACE**，且**同一条内混用**两种空格 →
   归一化按 `\s` 类空白拆分，**不能只按 `' '`**。
7. **首期只接两个频道**：地方政策库、部委站点直抓**未覆盖**（列扩展项，不计入首期验收）。
8. **只存元数据与链接**：不做全文下载归档；快照不含政策正文。
9. **不做政策解读/咨询**：只做"新发变更提醒"，不输出任何解读观点。
10. **真值基准是抽样覆盖**：预置快照对取自两频道各 30 条观测池（非全量普查）；
    覆盖声明逐形态登记"规则包总数 / 采样数 / 采样清单"，并显式标注"抽样覆盖、非穷举"。
11. **上游数据存在字段缺失**（M2 真跑实测）：部委频道第 2 页有 `summary` 为空的条目
    （实测 60 条里 1 条，id 26549375）；`index` 在部委频道 60/60 全空，`pcode` 4/60 为空。
    → 必填字段缺失的条目**不落库、不补编**，计进 `dropped` 并**点名 id**，
    本次运行降级为 exit 1；产品文件里不会出现凭猜测补出来的字段。

**平台礼仪**：遵守 gov.cn 限频，逐页抓取加延时，不做高并发压测。
**隐私红线**：纯本地运行，无任何遥测、无账号、无上传；运行时零第三方依赖，只对该域名发只读 GET。

## 四、已知环境问题

- **Python 3.8 全新 venv 的 pip 太老，装不上 editable**（历史记录，当前底线已抬到 3.12）：
  3.8 自带 pip 20.2.3 不支持 PEP 660，`pip install -e .` 会报
  `editable mode currently requires a setup.py based build`。
  **处置** = 安装前先 `python -m pip install --upgrade pip`（快速开始已含此行）；
  实测升级到 pip 25.0.1 后安装一次成功，全量测试 **336 项绿**（新 clone + 全新 venv 实测；
  py3.12.10 单解释器 336 collected / 336 passed——地板抬到 3.12 后 3.8 通道已退役。
  **本数字由 `tests/test_readme_gate.py` 对账**：新增/删除测试必须同步改这里，否则守门红）。
- **构建下限 setuptools>=77**（PEP 639 SPDX license 的要求）。setuptools 76 起要求 Python>=3.9，
  py3.8 能装到的最后一版 75.x 会**直接报配置错误**（`project.license` must be valid exactly by
  one definition，实测非警告而是硬失败）→ 故 `requires-python` 一并抬到 **>=3.12**。
- **首期发布物是源码包 + editable 安装**（`pip install -e .`）。数据文件以**包外相对路径**定位，
  非 editable 安装（wheel/sdist）**只提供 CLI 与解析能力**，数据相关命令需显式传 `--data-root`；
  不传时 `selftest` 会 exit 1 并点出 `data_root_complete missing=[...]`，
  `bench`/`verify-data` 会 exit 2「找不到数据根」。**这是显式契约，不是缺陷**——
  `tests/test_readme_gate.py` 与 `tests/test_selftest.py` 钉住这个退出码，
  防它"悄悄变成 0"而没人发现。
- Windows 控制台编码：入口内置编码守卫（按 `stream.encoding` 探针决定是否 reconfigure）；
  非 ASCII 输出在 cp1252 管道下不会崩。CI 侧另有 `PYTHONUTF8=1` 兜底。
- 本机 Python 通道：`py -0p` 实测有 3.8.8-64 与 3.12.10-64 两条；**项目底线 3.12**，
  CI 矩阵同口径（ubuntu/windows × 3.12）。

## 五、开发

```bash
pip install -e ".[dev]"
python -m pytest -q
```

测试面 = 安装面 = README 指令面：README 用到的 extras 与 pyproject 双向对账，README 里的
命令与旗标由 `tests/test_readme_gate.py` 反射核对（**查可执行性，不查字符串**）。

## 六、文档与数据

| 文档 | 说明 |
|---|---|
| `plan/00-README总览.md` | 索引 + 决策记录 + 待定决策 + 里程碑状态 |
| `plan/01-题目文档.md` | 题面（原样保留） |
| `plan/02-需求解读与边界.md` | FR 清单 + 边界与非目标 |
| `plan/03-架构与技术选型.md` | 分层、统一 schema、CLI 退出码 |
| `plan/04-模块详设.md` | 五模块 + 编排层 + K 清单（既定口径） |
| `plan/05-数据计划.md` | 数据资产、生成器纪律、真值语义 |
| `plan/06-里程碑.md` | M0–M6 逐棒 DoD |
| `plan/07-交付对标.md` | 评分维度逐条对标 |
| `plan/HANDOFF-M2.md` | 跨会话交接（本棒入口） |
| `plan/HANDOFF-M3.md` | 跨会话交接（M2 收尾产出，历史） |
| `plan/HANDOFF-M4.md` | 跨会话交接（M3 收尾产出，本棒入口） |
| `plan/HANDOFF-M5.md` | 跨会话交接（下一棒零上下文续接） |
| `data/README.md` | 数据源三态记录 + M0/M1/M2 实测勘误 |
| `data/config/README.md` | 规则数据（别名表/订阅/归一表）语义 |
| `data/snapshots/README.md` | 预置快照对（字节冻结 fixtures）+ 五形态覆盖 |
| `data/truth/README.md` | 真值台账语义（expect/also_expect、对账单一源、三问） |
| `data/samples/README.md` | 真实 API 响应样本（离线回归）+ 逐份 sha256 |

## 七、数据自审（M1）

```bash
policy-radar verify-data --data-root data
```

把 `data/truth/` 的**输入**喂给**参照实现**（`src/policy_radar/cases.py`）**实算**一遍，
再用**共用对账语义**与真值库里的**期望**逐条比对 → 输出
`3 套件全部自洽（比对 119 条）`、exit 0。

它**可证伪**（实测过）：把真值改坏 → 报差异并**点名哪几条**（如
`new_ids 多出：['26782365']`）、exit 1；真值库注入 `observed_*` 字段 → 报 K11 违规、exit 1。

**它不是基准**：本命令只核"真值库自身是否自洽"（期望可否由输入独立复算）；
跑生产实现的达标判定是 `bench`（M4 已落地，见第十节）。

四个生成器各有**两层位级守门**（`--check`）：

```bash
py -3.12 -X utf8 tools/gen_snapshot_pairs.py --check
py -3.12 -X utf8 tools/gen_pcode_cases.py --check
py -3.12 -X utf8 tools/gen_subscribe_cases.py --check
py -3.12 -X utf8 tools/gen_truth_manifest.py --check
```

## 八、双源抓取（M2）

```bash
policy-radar fetch --pages 1 --n 20 --delay 1.5 --out out/fetched.json
```

- **抓什么**：国务院政策库 + 部委政策库两个频道（`--channel` 可重复，默认两频道），
  **同进程串行**抓取、逐请求延时（`--delay`，默认 1.5s），不做并发。
- **取数路径固定** `searchVO.listVO`（实测：响应顶层 `data` 为 `null`）；条目字段一律
  经统一 schema（`PolicyItem` 十项），**只存元数据与链接，不抓正文**。
- **抓取自证**（不做"接口说多少就是多少"）：逐页断言
  `实际返回条数 == min(--n, totalCount - 已取)`；对账行真打印三个数：

  ```text
    对账 gwy：请求 40 条 / 声明 totalCount 6222 / 实际 40 条  [ok]
    对账 bm：请求 40 条 / 声明 totalCount 12803 / 实际 40 条  [ok]
    对账 合计：请求 80 条 / 声明 totalCount 19025 / 实际 80 条
    丢弃 1 条（schema 校验未过：不落库、不补编字段，本次降级）：26549375(required_fields_missing)
  ```

- **失败隔离**：某频道连不上（重试 2 次 + 指数退避后仍失败）-> 该频道记 `degraded`，
  其条目**整频道丢弃**，另一频道照常产出，exit 1；**所有**频道都失败 -> exit 4 且
  **不产出任何文件**（写盘走原子写：临时文件 -> rename）。
- **硬失败**（exit 4）：API 结构异常、响应非 JSON、缺 `totalCount`、**抓取自证不符**。
  判别口径：传输层抖动可以隔离，**"接口在说谎"必须停**——否则下游会拿着错数据继续跑。

## 九、快照 diff 与解析（M3）

```bash
policy-radar diff --snapshot out/snapshot.json --current out/fetched.json
policy-radar parse --input out/diff.json --data-root data
```

- **diff（模块 2）**：输入认本仓三类承载条目的产物（`policy-radar-fetch` /
  `policy-radar-snapshot` / `policy-radar-diff`，按 `format` 分派，未知格式 exit 2）；
  判定为 **id / pcode 双键**（`id` 相同 → 重复；否则 `pcode` 相同且非空 → 重复，
  命中键写进 `matched_by` 供回溯）；产出**新增清单**（`--out`，默认 `out/diff.json`，
  规范序）与**更新后的快照**（`--snapshot-out`，默认 `out/snapshot.json`，
  按 `(pubtimeStr 倒序, id 升序)` 重排、无时间戳，与 M1 冻结快照形态逐字节同构）。
- **首跑语义**：省略 `--snapshot` = 首次运行，全部计入新增且 stdout 明示；
  **给了路径但读不到 = exit 2**，不静默回落成首跑（"路径打错"不得被读成"全是新发的"）。
- **parse（模块 3）**：文号三态解析 `parsed/partial/unparsed`——支持 `〔〕` 与全角
  `﹝﹞` 两对括号、`国令第847号` 无括号形态（**年份标"未解析"，不编造**）、
  序号与"号"之间的空格；空 `pcode` 三字段全"未解析"。部门归一按 **`\s` 类空白**
  拆分 `puborg`（实测分隔符含 U+2002），别名表**单一来源** `data/config/org-aliases.json`
  （最长优先匹配），认不出的部门原样保留 + `alias_missing`，**不猜**。
- **未挂原文不落库（K10 代码级门禁）**：快照/清单条目出现 `content`/`body`/`fulltext`
  一类字段即拒——读、写两条路径都拦。

## 十、真值基准（M4）

```bash
policy-radar bench --data-root data
policy-radar bench --only diff --data-root data
```

- **一键跑通三个套件**：diff（`snapshot.detect_new`）/ pcode（`parse.parse_pcode`）/
  subscribe（`subscribe.match_items`）——**生产实现实算**，用**共用对账语义**
  （`cases.compare_*`）与真值期望逐条比对（与 `verify-data` 共用同一份，
  不会出现"基准说达标、测试说不过"）。
- **与 `verify-data` 的分工**：`verify-data` 核"真值库自身是否自洽"（喂**参照实现**）；
  `bench` 判"**生产实现**对真值逐条一致"——两边对账语义与门槛装载**同源复用**。
- **门槛随数据下发（K17）**：读 `data/truth/manifest.json` 的 `thresholds`
  （与 `verify-data` 同一 loader），缺失即 exit 2，**代码零默认值**。
- **退出码三语义**：0 达标 / 1 未达标（逐条点名哪几条）/ 2 用法错误。
- **双边门**：既守误报率 0（对账 ok——不该有的结论一条不能多，含命中键判错、
  命中位置错），也守检出率 ≥ 阈值（该有的逐样本点名——生产实现整条空转时
  对账可能漏红，检出门必红）。
- **可证伪探活**：向生产实现注入缺陷（pcode 键判定打掉 / 命中短路成空 /
  解析恒 unparsed）→ 基准必须报未达标（exit 1）并逐条点名；探活打到
  **端到端入口**（CLI 层），见 `tests/test_subscribe_bench.py`。

## 十一、中文日报与端到端编排（M5）

```bash
# 端到端：一条命令出结果（抓取 → diff → 解析 → 订阅 → 日报）
policy-radar run --channels gwy,bm --out-dir out
# 离线复现：diff 产物 + 订阅命中产物 → 日报（不联网）
policy-radar digest --new-items out/diff.json --hits out/subscribe.json --parse out/parsed.json
```

- **日报（digest，模块 5）**：输入 = 新增清单（diff 产物，规范序）+ 订阅命中产物
  （`policy-radar-subscribe`）+ 可选解析产物；输出 = **中文 Markdown + HTML 双格式**
  （`--format md/html/both`，默认 both）。每条含标题 / 发布日期 / 频道 / 文号
  （原文 + 解析结构）/ 发布部门（原文 + 归一结果）/ 原文链接 / 命中关键词 / 摘要；
  缺任一字段显式渲染「**未提供**」，不静默略过、不编造。
- **渲染层零判定（K9）**：日报只消费既有结论（diff 已判新增、subscribe 已判命中、
  parse 已解析），不重算任何判定——AST 守门测试锁死 `report.py` 的调用面。
- **零外链（本地可开）**：HTML 的**渲染资源**（脚本/样式/字体/图片引用）零外部引用，
  CSS 全内联，断言**常驻在渲染出口**；条目自带的 `url` 是**原文链接**（内容字段），
  不在"零外链"扫描面里。
- **确定性**：日报无时间戳、无随机序，同输入**双跑逐字节一致**——可由
  `data/snapshots/` + `data/config/` 完全复现（题面要求）。
- **未过校验不进日报（FR-11）**：渲染前逐条 schema 校验，未过的**该条不进日报**
  并计 `dropped_count`（exit 1 降级完成），不补编字段。
- **无新增**：日报显式写"本次无新增"（不落空文件）。
- **编排（run，一条命令）**：`fetch → diff → parse → subscribe → digest`，
  中间产物全落 `--out-dir`（默认 `out/`，不入库）——每一步可单独复查与复跑；
  `--snapshot` 给上次快照（省略 = 首跑语义与 `diff` 一致）；CLI 与编排函数
  **行为等价**（CLI 统计 == 直调编排统计 == 报告统计，测试逐项对账）。
- **退出码**：0 完成；1 降级完成（有频道 degraded / 有条目被丢弃 / 有条目未进日报）；
  2 用法/输入错误；4 全部频道抓取失败（不产出任何文件）。

## 十二、品牌定位

本仓库独立成题，**不与任何其他项目共享品牌、代码或数据**；文档与代码中不含任何其他项目名称。

## 十三、许可

MIT。数据来源为中国政府网公开信息，本工具只存元数据与链接，不归档正文。
