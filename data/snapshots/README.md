# data/snapshots/：预置快照对（字节冻结 fixtures）

本目录存放**真值基准用的预置快照对**——旧快照 A + 新快照 B，B 相对 A 的新条目即
"应判为新增"的真值，A∩B 条目即"应判为重复"的真值。

| 文件 | 产出里程碑 | 说明 |
|---|---|---|
| `pair-A.json` | M1 | 旧快照（20 条） |
| `pair-B.json` | M1 | 新快照（21 条） |
| `manifest.json` | M1 | 快照元信息 + 逐份 sha256 + 形态覆盖声明 + 验收门槛 |

## 一、快照文件形态

```json
{
  "format": "policy-radar-snapshot",
  "format_version": 1,
  "note": "…",
  "item_count": 20,
  "items": [ { "source": "gwy", "id": "…", "index": "…", "pcode": "…",
               "title": "…", "pubtimeStr": "2026.10.08", "puborg": "…",
               "url": "…", "summary": "…", "channel": "国务院" } ]
}
```

- `items` 按 **`(pubtimeStr 倒序, id 升序)`** 规范排序（K5，全程不读时钟）。
- 字段**白名单 = `PolicyItem` 全部字段**（K10）；出现 `content`/`body`/`fulltext`
  一类字段即红——**不做全文归档**（边界 2）。
- 产物**无时间戳**：`--check` 重跑逐字节比对才有意义。

## 二、合成素材取自实采（不编造）

条目来自 `data/samples/gwy-p1-n30.json` / `bm-p1-n30.json`（真实抓取的两频道各 30 条
**观测池**）：真实 `id` / `pcode` / `title` / `puborg` / `url`，**不虚构机关代字与数值**。

合成只做"**选哪些条目进 A/B**"与"**一条 (id, pcode) 的配对关系**"（`pcode_dup` 形态）：
后者的 `id` 是真实值，只把另一条的 `pcode` 赋给它，用来专测副键。**不新增任何字段**。

## 三、五类形态覆盖（逐类至少 1 条）

| 角色 | 条数 | 应判 | 说明 |
|---|---|---|---|
| `carried` | 13 | 重复 | `id` 键命中 |
| `fresh` | 5 | 新增 | B 中全新条目 |
| `pcode_dup` | 1 | 重复 | **id 新但 pcode 相同**——只按 id 判会漏 |
| `empty_pcode_new` | 1 | 新增 | **边界**：`pcode` 空 + id 新 |
| `empty_pcode_same` | 1 | 重复 | **边界**：`pcode` 空 + id 同（只能按 id 判） |

## 四、字节冻结纪律

- 本目录是**生成器产物**（`tools/gen_snapshot_pairs.py`），**禁手改**；
- 改体例/生成器 → 用固定 seed（`20261017`）重跑整目录提交，配"再生成位级一致"守门
  （**两层**：① 冻结产物自身形态正确；② 重跑生成器到临时目录 → 与冻结产物逐字节比对）；
- `--check` 命令：
  `py -3.8 -X utf8 tools/gen_snapshot_pairs.py --check`
- `.gitattributes` 已标 `data/snapshots/*.json -text`（防克隆时 EOL 归一化改写字节 → sha256 失配）；
- 验证手段 = 克隆/检出后比对快照实际 sha256 与 `manifest.json` 登记值
  （`git status` 看不出来）。

**注意**：本目录是**基准数据**，不是运行时快照目录。运行时快照写入 `.gitignore` 覆盖的
`snapshots/`（仓库根）——真值基准用的预置快照对才入版本管理。

## 五、验收门槛随数据下发

`manifest.json` 的 `thresholds` 字段（`diff_new_accuracy` / `diff_dup_accuracy` 等）
**随数据下发**：基准层只读，缺失即报配置错误，**不得回落代码里的默认值**——
门槛内联进代码就是"抄进代码的第二份真相"。
