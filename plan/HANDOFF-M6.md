# HANDOFF-M6：交接给"发布"里程碑

> 用法（新对话启动命令，用户侧拼绝对路径）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M6.md" 继续完成任务`
> 上一棒：**M5 交付**（本对话完成）
> 下一棒：**M6 发布**（脱敏四步 + 干净环境验证 + 建仓 + CI 首跑 + tag/Release + 留档）

---

## 一、当前进度 + 证据（本对话实测）

### 已完成

| 项 | 证据 |
|---|---|
| **`report.py` 真实现（M5 核心交付）** | `src/policy_radar/report.py`（约 400 行）：`load_digest_inputs`（diff 产物 + subscribe 产物按 `format` 校验装载）/ `report_entries`（单一渲染源；FR-11 未过校验条目**不进日报**、计 `dropped`）/ `render_markdown` + `render_html`（缺字段显式「未提供」、无新增显式"本次无新增"、无时钟）/ `assert_no_external_resources`（**常驻渲染出口**）/ `build_digest_product` + `write_digest` + `cmd_digest` |
| **零外链口径定稿（K9，先在测试 docstring 定稿）** | "零外链" = **渲染资源**（`<script>/<link>/<img>/<iframe>` 等资源标签、`@import`、CSS `url(https://…)`）零外部引用——**条目自带的 `url` 是原文链接（内容字段），`<a href>` 放行**；阳性对照测试锁死（`test_no_external_resources_allows_item_url_as_content`）；口径单点在 `report.FORBIDDEN_CALLS_IN_REPORT` 同级的 `_EXTERNAL_RESOURCE_RE` + `FORBIDDEN_CALLS_IN_REPORT`（后者供 AST 守门） |
| **渲染层零判定（K9，AST 守门）** | `tests/test_report_pipeline.py::test_report_module_has_no_judgement_calls`：AST 扫 `report.py` 的调用与属性引用（**不扫子串**，M3 教训），判定函数（`detect_new`/`parse_pcode`/`parse_orgs`/`match_items`/`build_*_product`）不得出现 |
| **双跑逐字节一致** | `test_double_run_byte_identical`：同输入两次 `build_digest_product` + `write_digest`，Markdown/HTML 逐字节一致（无时间戳、无随机序） |
| **两格式内容对等** | `test_markdown_html_content_equivalence`：同输入下两格式抽文本逐 token 一致 + 条目小节数一致（结构性质，不靠人工比对） |
| **`pipeline.py` 真实现（run 编排）** | `src/policy_radar/pipeline.py`（约 220 行）：`run_pipeline`（**公开函数组单点**：fetch → diff → parse → subscribe → digest；**离线注入面** = `fetch_items`/`fetch_channel_meta`/`captured_at`，CI/测试/演示联网无关）/ `load_subscribe_hits`（订阅产物单点，`format=policy-radar-subscribe`）/ `cmd_run`。判定零复制（全走各模块单点）；中间产物全落 `--out-dir` |
| **run 退出码语义** | 0 完成 / 1 降级（有频道 degraded 或有条目丢弃，fetch 与 digest 降级**合并取重**）/ 2 用法错误（频道名错、`--out-dir` 空）/ 4 全部频道失败（**不产出任何文件**，fetch 语义透传）——四条路径测试锁死（`test_run_pipeline_*`） |
| **行为等价（编排层纪律）** | CLI stdout 统计 == 直调 `run_pipeline` 返回统计 == 报告内容统计；`test_retired_commands_do_real_work_offline` 里 CLI 通路（monkeypatch `pipeline_mod.fetch_all`）与直调通路（注入产物）的 `report.md` **逐字节一致** |
| **CLI `digest`/`run` 整项退役 exit 3** | `NOT_READY_COMMANDS = {}`（**空表**，`test_not_ready_commands_table_is_empty_after_m5` 锁死空集 + 语义保留）；`_min_args` 删表；`test_not_ready_stderr_mentions_milestone` / `test_fetch_diff_parse_bench_are_retired_from_not_ready` / `test_other_commands_still_not_ready` 三条按空集口径改写/删除；`test_retired_commands_do_real_work_offline` 扩 digest（真渲染）+ run（真编排，离线）；cli.py 接线 `cmd_digest`/`cmd_run`，digest 参数升级（`--hits` 必填、`--parse` 可选、`--out` both 派生两格式） |
| **退出码 3 落点 grep 复核（D23 教训）** | `grep -rn "exit 3\|EXIT_NOT_READY\|尚未就绪"` 全仓跑过：`ci.yml` 已同步（`digest exit 3` 步骤换成 **digest 缺参 exit 2** + **digest 离线渲染 exit 0** 冒烟，后者本地逐条模拟通过）；`errors.py`/`cli.py` 的语义保留（退出码 3 是对外契约，README 退出码表已写，**常量不删、无调用方**）；其余命中均为 HANDOFF/plan 历史记录或测试断言，无需改 |
| **CI digest 冒烟本地模拟** | `diff --current data/snapshots/pair-B.json`（首跑 21 条新增）→ 单行 `python -c` 构造零命中 subscribe 产物 → `digest … --format both` → **exit 0**，`out/` 产物齐（CI 步骤用的就是这条命令序列；heredoc 在 YAML 块内缩进会挂，故用单行 `python -c`） |
| **测试套件** | **321 项**（3.8 与 3.12 **同数**），双解释器全绿；新增 `tests/test_report_pipeline.py`（**14 项**：K9 两条 + 确定性 + 对等 + 缺字段/无新增/FR-11 + 输入校验三条 + pipeline 五条）；`test_cli_contract.py` 退役处置 + retired 扩容 |
| **README 完整化** | 命令表两行（digest/run 真行为）+ 参数示例更新（`--hits`/`--snapshot`）+ 退出码表第 3 行改"语义保留"口径 + **新增第十一节「中文日报与端到端编排（M5）」**（原十一/十二顺延为十二/十三）；README 指令面守门（`test_readme_gate.py`）全绿 |
| **plan 同步** | `plan/03` 命令表（digest/run 已实现行 + 退出码 3 语义保留口径）；`plan/06` M5 状态总表 ✅ + M5 DoD checklist 十项全 ✅；`plan/00` 决策 **D29**（零外链口径）+ 里程碑状态（M5 完成）+ **诚实口径尾注（M5）**；`plan/07` 工程质量/交付与表达/测试三行 M5 更新 |
| **数据/真值面未回退** | 四生成器 `--check` 各 exit 0；`capture_samples.py --check` exit 0；`verify-data` → exit 0；`selftest` → exit 0（9/9）；`bench` → exit 0；**M5 未新增 `data/` 资产、未重抓样本**（sha256 不变）；哨兵桩 grep 0 命中 |

### 诚实口径（**无远端，CI 从未跑过**）

- 仍**无远端**、**一次 CI 都没跑过** → 凡 CI 类判据一律写"**本地等价校验（未接远端，CI 待首推验证）**"。
- 本机可实跑的等价物：① 双解释器（3.8.8 + 3.12.10）全量 pytest（各 **321 项**）；② 四生成器 + 样本登记 `--check`；③ `verify-data` exit 0；④ `bench` exit 0；⑤ **digest 离线渲染 exit 0 + run 离线编排端到端 0**；⑥ **CI digest 冒烟步骤本地逐条模拟（exit 0/2 对上）**；⑦ 退出码 3 退役落点 grep 复核。
- **不可本机实跑的缺口**：CI 矩阵的 ubuntu/Windows 差异、CI 步骤的 shell 差异、`actions/setup-python` 的 3.8 可用性 → **待首推验证**（M6 预算多轮诊断）。

### M5 设计要点（写给下一棒）

1. **订阅产物是 M5 新增的一类产物**：`format = "policy-radar-subscribe"`（v1），
   字段 = `hits/excluded/zero_hit_ids + 三个计数`；`digest --hits` 消费它。
   它由 `pipeline.load_subscribe_hits` 产出（run 编排内）——独立跑 digest 时
   用该函数构造（测试里有现成样例）。
2. **日报消费 diff 产物的规范序**（K5 单点在 diff 层），渲染层**不再排序**；
   报告条目 id 关联 parse 产物（`--parse` 可选，缺了显式「未提供」）。
3. **K9 的 AST 守门常量** `report.FORBIDDEN_CALLS_IN_REPORT` 是口径单点，
   新增判定函数要同步进该元组。
4. **hit_count 是命中记录数（每词一条），不是条目数**——条目级口径 =
   命中条目 ∪ 剔除条目 ∪ 零命中条目 == 全部新增（两处测试已按此写，别改回
   `hit+excl+zero == new` 的错误断言）。
5. **`run` 的离线注入面**：`run_pipeline(fetch_items=…, fetch_channel_meta=…,
   captured_at=…)`；CI/测试**不打真站**（fetch 语义透传已测）。真网编排
   `python -m policy_radar run` 可跑（遵守 `--delay` 限频）。

---

## 二、下一棒（M6）待办

按 `plan/06-里程碑.md` 的 M6 节执行：

1. **脱敏四步**：① 全仓扫密钥/令牌（本仓无凭据，grep 复核）；② `out/`/临时文件
   清理（`.gitignore` 已覆盖，确认 `git status` 干净）；③ 个人信息面复查
   （git 用户名/邮箱按发布口径定）；④ 数据面终检（四生成器 + `capture_samples
   --check` + `verify-data`）。
2. **干净环境验证**：新目录 clone（本地 `git clone` 仓库副本即可）+ 全新 venv
   按 README 逐条跑通，**逐条记退出码与语义判定**（3.8 venv 记得 README 那条
   `pip install --upgrade pip` 前置）。
3. **建仓**：`gh repo create yuluo554/10-16-2-policy-radar --public` → push。
4. **CI 首跑**：**预算多轮诊断**（本机模拟不了 ubuntu/Windows 矩阵与 shell 差异；
   M5 的 ci.yml digest 冒烟步骤已在本地逐条模拟，首跑若红优先看环境差异）。
5. `gh run list` 对账 push 数 = run 数 → tag + Release → 发布留档
   `plan/RELEASE-M6.md`（未跑的项留 ⬜ 并说明原因）→ 收尾 `plan/WRAPUP-M6.md`。

**M6 的 DoD 全文见 `plan/06-里程碑.md` 的 M6 节。**

---

## 三、既定口径清单（K 编号）

**与 `HANDOFF-M5.md` 第三节完全同表（K1–K26，无新增无删除）**——M5 只按 K9
把"渲染层零判定 + 渲染出口常驻零外链断言"落进了 `report.py` 与测试，口径未动。
**M6 是发布里程碑，不写生产代码；动了任何 K 口径前先跑全量测试 + 生成器
`--check` + `verify-data` 确认不回退。**

要点重申（M6 会碰到的）：

- **K2**：退出码 3 语义**保留**（README 退出码表、`errors.py` 常量都在），
  `NOT_READY_COMMANDS` 空表是终态——CI/README 里不再有"某命令 exit 3"的断言。
- **K3**：日报也走 `serialize.write_text`（LF + 尾换行 + 原子写）——发布留档时
  不要在仓库里留下手工生成的日报（`out/` 不入库）。
- **K12**：零第三方运行时依赖——发布物就是源码包 + editable 安装（README 第四节
  已声明 wheel 未验证的口径，M6 发布时**原样保留**该披露）。
- **K13**：wheel/sdist 安装后数据根可能解析不到 → README 已写"显式传
  `--data-root`"；干净环境验证时如遇此现象**按 README 口径记录**，不改代码。

---

## 四、本机环境坑（**只写实测过的**）

**与 `HANDOFF-M5.md` 第四节全表共用（17 条全部仍有效），本棒新增三条：**

18. **YAML 块内 heredoc 会挂**：CI 的 `run: |` 块里 heredoc 终止符要求行首顶格，
    YAML 缩进会破坏它 → CI 步骤里的内联 Python 一律**单行 `python -c`（纯 ASCII）**。
19. **monkeypatch 编排传输层打在 `pipeline_mod`**：`pipeline.py` 是
    `from .fetch import fetch_all` 的模块级名绑定 → patch `pipeline_mod.fetch_all`
    （同 HANDOFF-M5 第 17 条的同款纪律）。
20. **测试里"报告内容 == CLI 产物"的逐字节对照**要在**同一次 fixture 内**做
    （`out/` 目录是共享的，跨用例残留会假绿/假红——本棒 run 退役测试用
    `tmp_path` 隔离两个目录再对照）。

---

## 五、关键命令速查

```bash
# --- 测试（双解释器，全量） ---
PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q   # 各 321 项（本棒实测）

# --- CLI 冒烟（退出码语义） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar version                        # 0
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar selftest --data-root data      # 0（9/9）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar verify-data --data-root data   # 0（3 套件 / 119 条）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar bench --data-root data          # 0（3 套件达标）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar digest                          # 2（缺参）
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar fetch --channel nope            # 2

# --- digest 离线渲染（CI 冒烟同款序列） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar diff --current data/snapshots/pair-B.json --out out/ci-diff.json --snapshot-out out/ci-snapshot.json   # 0（首跑 21 条）
py -3.8 -X utf8 -c "import json;d=json.load(open('out/ci-diff.json',encoding='utf-8'));items=d['items'];h={'format':'policy-radar-subscribe','format_version':1,'item_count':len(items),'hit_count':0,'excluded_count':0,'zero_hit_count':len(items),'hits':[],'excluded':[],'zero_hit_ids':[it['id'] for it in items]};json.dump(h,open('out/ci-subscribe.json','w',encoding='utf-8'),ensure_ascii=False,indent=2)"
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar digest --new-items out/ci-diff.json --hits out/ci-subscribe.json --out out/ci-report.md --format both   # 0

# --- run 真网编排（遵守限频；产物在 out/，不入库） ---
PYTHONPATH=src py -3.8 -X utf8 -m policy_radar run --channels gwy --out-dir out --delay 1.5   # 0/1/4

# --- 数据生成与位级守门（两层） ---
py -3.8 -X utf8 tools/gen_snapshot_pairs.py --check       # 0
py -3.8 -X utf8 tools/gen_pcode_cases.py --check          # 0
py -3.8 -X utf8 tools/gen_subscribe_cases.py --check      # 0
py -3.8 -X utf8 tools/gen_truth_manifest.py --check       # 0
py -3.8 -X utf8 tools/capture_samples.py --out-dir data/samples --check   # 0

# --- 哨兵桩排查（收尾期固定动作） ---
grep -rn "NotImplementedError\|TODO: 实现\|placeholder" src/ tools/

# --- 退出码 3 落点排查（M5 已清空表；M6 发布前再复核一遍） ---
grep -rn "exit 3\|EXIT_NOT_READY\|尚未就绪" --include=*.py --include=*.md --include=*.yml . | grep -v "^./.git/"
```

---

## 六、DoD 逐项 checklist（M5）

| # | 判据 | 验证方式（**在哪验的**） | 状态 |
|---|---|---|---|
| 1 | 日报可由基准数据完全复现（双跑逐字节） | `test_double_run_byte_identical` + digest 离线渲染实测 | ✅ |
| 2 | HTML 0 外链常驻断言（口径 = 渲染资源） | `assert_no_external_resources` 常驻 `render_html` 出口 + 阳性对照（内容 `<a href>` 不红）+ 三条阴性 | ✅ |
| 3 | 两格式内容对等断言 | `test_markdown_html_content_equivalence`（抽 token 逐项 + 小节数） | ✅ |
| 4 | `run` 一条命令出结果 | `pipeline.run_pipeline` 单点 + 离线编排端到端（7 件产物齐）+ 退出码 0/1/2/4 四路径 | ✅ |
| 5 | 渲染层零判定（AST 守门） | `test_report_module_has_no_judgement_calls` | ✅ |
| 6 | README 完整 | 定位宣言/快速上手/数据源与局限/⚠️ 局限原样披露/品牌定位无姊妹项目字样；`test_readme_gate.py` 绿 | ✅ |
| 7 | 测试覆盖核心路径 + 失败路径 | 新增 14 项 + retired 扩容；缺文件/坏格式/未知 format/全频道失败/降级全测 | ✅ |
| 8 | 双解释器绿 | 各 **321 项**（3.8 与 3.12 同数，本对话实测） | ✅ |
| 9 | 数据/真值面未回退 | 四生成器 + capture `--check` exit 0；`verify-data` exit 0；`selftest` 9/9；`bench` exit 0；哨兵桩 grep 0；**M5 未新增 `data/` 资产** | ✅ |
| 10 | CLI `digest`/`run` 整项退役 exit 3（落点找全，含 CI） | `NOT_READY_COMMANDS = {}` 空集断言；ci.yml 两步本地模拟；README/plan 同步；grep 复核 | ✅ |
| 11 | HANDOFF-M6 落盘 | 本文件 | ✅ |

**偏差说明**：① CI 类判据按诚实口径写"本地等价校验，未接远端，CI 待首推验证"；
② `run` 的 CI 冒烟**没有**加（真网步骤进 CI 不可靠）——CI 里的 digest 冒烟已覆盖
"日报离线可达"；run 的离线通路在 pytest 里端到端锁死；③ digest 的 `--out` 语义
在 both 模式下按"主干派生两格式"实现（`report.md` ↔ `report.html`），与 CLI help
一致；④ 待定决策 P1–P6 仍未答复，M5 按推荐项 A 执行（无新增）。

---

## 七、续接指针

- **本棒产出**：`src/policy_radar/report.py`（真实现）、`src/policy_radar/pipeline.py`
  （真实现）、`tests/test_report_pipeline.py`（14 项）、`tests/test_cli_contract.py`
  （digest/run 退役处置 + retired 扩容）、`src/policy_radar/cli.py`（接线 + 空表）、
  README（命令表 + 第十一节 + 退出码表口径）、`.github/workflows/ci.yml`
  （digest exit 2 / digest exit 0 两步替换）、`plan/00,03,06,07` 同步（D29、M5 状态）。
- **下一棒入口**：`plan/06-里程碑.md` 的 M6 节 + 本文件第二节。
- **下一棒出口**：`plan/RELEASE-M6.md` + `plan/WRAPUP-M6.md`（M6 是最后一棒）。
- **M6 最要紧的三件事**（按风险排序）：
  1. **CI 首跑诊断预算**（本机模拟不了矩阵与 shell；digest 冒烟步骤已本地模拟，
     首跑红时先对比 ubuntu bash 与 Git Bash 的行为差异）；
  2. **干净环境验证逐条记录**（3.8 venv 的 pip 升级前置是 README 实测坑，
     全新 Windows venv 上重演概率高）；
  3. **`git status` 干净 + `out/` 不入库**（M5 跑过真站 diff/digest 冒烟，
     `out/` 里现有一批 CI 模拟产物——发布前清掉或确认 `.gitignore` 覆盖）。
- **待用户拍板**：`plan/00-README总览.md` 的待定决策表 P1–P6（**仍未答复**）。
