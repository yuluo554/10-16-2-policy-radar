# 政策文件雷达（policy-radar）

> **定位宣言**：本地定时抓取中国政府网政策文件库，把"今日新发政策 + 发文字号 + 发布部门 + 摘要"
> 变成一份可订阅关键词的中文日报——**快照 diff 检测新增，不是每次全量翻页**。
> 企业法务 / 合规 / 政策研究 / 申报人员要盯发文，分散逐条翻页极易漏。

- 形态：**纯本地 Python CLI**（无服务器、无 GPU、无账号、无遥测）
- 数据源：中国政府网搜索 API 两个公开频道（国务院政策库 + 部委政策库）
- 版本：`0.1.0`（M0 骨架；里程碑进度见 `plan/06-里程碑.md`）
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

# 自检必须"可证伪"：把数据根指向空目录会返回非 0
policy-radar selftest --data-root ./empty-dir
```

> **为什么先升级 pip**：Python 3.8 自带的 pip 20.2.3 **不支持 PEP 660 可编辑安装**，
> 直接 `pip install -e .` 会报 `editable mode currently requires a setup.py based build`
> （实测，见第四节「已知环境问题」）。这一行不可省略。

**退出码语义**（判据以本节为准，非 0 不等于"跑挂了"）：

| 退出码 | 语义 |
|---|---|
| 0 | 成功完成 |
| 1 | 完成但有降级 / 检出问题（如部分频道抓取失败、基准未达标） |
| 2 | 用法错误 / 输入不可用（未知子命令、参数错、输入文件缺失、坏格式） |
| 3 | **能力未就绪**（骨架期专用；对应模块落地后整项退役） |
| 4 | 外部依赖不可用（网络不可达、API 返回非 200、API 结构异常） |

## 二、命令总表

| 命令 | 里程碑 | 当前行为 |
|---|---|---|
| `policy-radar version` | M0 | 打印版本号，exit 0 |
| `policy-radar selftest` | M0 | 自检（可证伪），exit 0/1 |
| `policy-radar fetch` | M2 | **exit 3**（未就绪） |
| `policy-radar diff` | M3 | **exit 3** |
| `policy-radar parse` | M3 | **exit 3** |
| `policy-radar digest` | M5 | **exit 3** |
| `policy-radar run` | M5 | **exit 3** |
| `policy-radar bench` | M4 | **exit 3** |

两条等价通路（`sys.path` 来源不同，**两者都要能跑**）：

```bash
policy-radar version                              # 安装后的 console script
python -m policy_radar version                    # 模块形态（需要 __main__.py）
```

参数示例（各命令的完整参数见 `policy-radar <command> --help`）：

```bash
policy-radar fetch --channel gwy --pages 1 --n 20 --delay 1.5
policy-radar diff --snapshot snapshots/last.json --current out/today.json
policy-radar parse --input out/new-items.json
policy-radar digest --new-items out/new-items.json --format both
policy-radar run --channels gwy,bm --out-dir out
policy-radar bench --only diff
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
5. **首期只接两个频道**：地方政策库、部委站点直抓**未覆盖**（列扩展项，不计入首期验收）。
6. **只存元数据与链接**：不做全文下载归档；快照不含政策正文。
7. **不做政策解读/咨询**：只做"新发变更提醒"，不输出任何解读观点。

**平台礼仪**：遵守 gov.cn 限频，逐页抓取加延时，不做高并发压测。
**隐私红线**：纯本地运行，无任何遥测、无账号、无上传；运行时零第三方依赖，只对该域名发只读 GET。

## 四、已知环境问题

- **Python 3.8 全新 venv 的 pip 太老，装不上 editable**：3.8 自带 pip 20.2.3 不支持 PEP 660，
  `pip install -e .` 会报 `editable mode currently requires a setup.py based build`。
  **处置** = 安装前先 `python -m pip install --upgrade pip`（快速开始已含此行）；
  实测升级到 pip 25.0.1 后安装一次成功，全量测试 99 项绿（新 clone + 全新 venv 实测）。
- **首期发布物是源码包 + editable 安装**（`pip install -e .`）。数据文件以**包外相对路径**定位，
  `wheel`/`sdist` 安装后可能解析不到数据根 → 此时显式传 `--data-root`。
  **本项为实测现象与规避方式，不构成"已验证 wheel 安装"的声明。**
- Windows 控制台编码：入口内置编码守卫（按 `stream.encoding` 探针决定是否 reconfigure）；
  非 ASCII 输出在 cp1252 管道下不会崩。CI 侧另有 `PYTHONUTF8=1` 兜底。
- 本机 Python 通道：`py -0p` 实测有 3.8.8-64 与 3.12.10-64 两条；项目底线 3.8，
  **全部代码只用 3.8 语法**。

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
| `plan/HANDOFF-M1.md` | 跨会话交接（下一棒零上下文续接） |
| `data/README.md` | 数据源三态记录 + M0 实测勘误 |
| `data/config/README.md` | 规则数据（别名表/订阅/归一表） |
| `data/snapshots/README.md` | 预置快照对（字节冻结 fixtures） |
| `data/truth/README.md` | 真值台账（只存输入与期望） |
| `data/samples/README.md` | 真实 API 响应样本（离线回归） |

## 七、品牌定位

本仓库独立成题，**不与任何其他项目共享品牌、代码或数据**；文档与代码中不含任何其他项目名称。

## 八、许可

MIT。数据来源为中国政府网公开信息，本工具只存元数据与链接，不归档正文。
