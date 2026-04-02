# FootNoteMachine 集成设计

**日期：** 2026-04-02  
**状态：** 已确认，待实施  
**范围：** 将 FootNoteMachine 的脚注/尾注筛选器与翻译流程接入现有阅读器

---

## 目标

同时解决三件事：

1. **翻译质量**：用冻结 token + 分 unit 翻译，防止大模型重编号或混淆脚注/尾注
2. **阅读显示**：在阅读页新增注释侧栏，展示脚注/尾注原文与译文
3. **Markdown 导出**：新增 FNM Obsidian 导出路径，脚注用 `[^id]`，尾注用 `[EN-id]`

---

## 策略：并行管线

FootNoteMachine (FNM) 作为独立管线叠加在现有系统上，**不替换**现有逐页翻译流程。

- 旧模式（`TASK_KIND_CONTINUOUS`）完全不变
- 新模式（`TASK_KIND_FNM`）独立开关，可回退
- 旧文档无 FNM 数据时，相关 UI 灰掉，不报错

---

## 整体数据流

```
上传 PDF
  └─ OCR（PaddleOCR）→ pages 存 SQLite（不变）
       └─ [新增] FNM 分类器自动运行（同线程，失败不阻断）
            ├─ 读 pages 里的 OCR JSON
            ├─ 调用 FootNoteMachine 状态机
            ├─ 写 fnm_runs / fnm_notes / fnm_translation_units
            └─ status = done / error

翻译
  ├─ 旧模式：TASK_KIND_CONTINUOUS，逐页（不变）
  └─ 新模式：TASK_KIND_FNM，逐 unit
       ├─ body chunk：含冻结 token，送 LLM
       ├─ footnote：每条独立翻译
       ├─ endnote：每条独立翻译
       └─ 完成后回填冻结 token → Obsidian 引用格式

阅读页
  ├─ 原有正文/译文双栏（不变）
  └─ [新增] 注释侧栏：脚注 | 尾注切换，按当前页筛选

导出
  ├─ 旧路径：storage_endnotes.py（不变）
  └─ 新路径：fnm_export.py → FNM Obsidian 格式
```

---

## SQLite Schema 变更（v5 → v6）

新增三张表，现有表不动。

### `fnm_runs`

```sql
CREATE TABLE fnm_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id        TEXT NOT NULL,
    status        TEXT NOT NULL,   -- pending / running / done / error
    error_msg     TEXT,
    page_count    INTEGER,
    section_count INTEGER,
    note_count    INTEGER,
    unit_count    INTEGER,
    created_at    REAL,
    updated_at    REAL
);
```

### `fnm_notes`

```sql
CREATE TABLE fnm_notes (
    row_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id          TEXT NOT NULL,      -- e.g. "fn-02-0003" / "en-02-0001"（仅在同文档内唯一）
    doc_id           TEXT NOT NULL,
    section_id       TEXT NOT NULL,
    kind             TEXT NOT NULL,      -- "footnote" / "endnote"
    original_marker  TEXT NOT NULL,
    start_page       INTEGER,
    pages            TEXT,               -- JSON array of page numbers
    source_text      TEXT,               -- 原文（去掉定义标记后）
    translated_text  TEXT,               -- 译文（回填后）
    translate_status TEXT DEFAULT 'pending',  -- pending / done / error
    UNIQUE (doc_id, note_id)
);
```

### `fnm_translation_units`

```sql
CREATE TABLE fnm_translation_units (
    unit_id         TEXT PRIMARY KEY,   -- "body-sec-02-...-0001" / "footnote-fn-02-0003"
    doc_id          TEXT NOT NULL,
    kind            TEXT NOT NULL,      -- "body" / "footnote" / "endnote"
    section_id      TEXT NOT NULL,
    note_id         TEXT,               -- NULL for body units；与 fnm_notes.note_id + doc_id 联合定位
    page_start      INTEGER,
    page_end        INTEGER,
    char_count      INTEGER,
    source_text     TEXT,               -- 含冻结 token 的原文
    translated_text TEXT,
    status          TEXT DEFAULT 'pending',  -- pending / done / error
    error_msg       TEXT,
    updated_at      REAL
);
```

迁移脚本只做 `CREATE TABLE IF NOT EXISTS`，schema 版本号从 5 升到 6。

---

## FNM 分类管线

**新文件：`fnm_pipeline.py`**

触发时机：OCR 完成后，在同一后台线程里串行运行。失败只写 `fnm_runs.error_msg`，不向上抛异常。

```
build_fnm_manifest(doc_id)
  ├─ 从 SQLite 读所有 pages 的 OCR JSON
  ├─ 将页数据重组为 FNM 期望格式：
  │    [{prunedResult: {parsing_res_list: [...]}, markdown: {text: "..."}}]
  ├─ 调用 FootNoteMachine.scripts.footnote_endnote_filter_prototype.build_manifest()
  ├─ 调用 FootNoteMachine.scripts.footnote_endnote_products.build_rendered_sections()
  ├─ 写 fnm_runs（status=running）
  ├─ 写 fnm_notes（每条脚注/尾注）
  ├─ 写 fnm_translation_units（body chunk + 各注释 unit）
  └─ 更新 fnm_runs.status = done / error
```

**Import 方式：** 直接从 `FootNoteMachine/scripts/` 导入，不复制文件：

```python
from FootNoteMachine.scripts.footnote_endnote_filter_prototype import build_manifest
from FootNoteMachine.scripts.footnote_endnote_products import build_rendered_sections
```

**新增 API：**

- `GET /api/doc/<doc_id>/fnm/status` — 返回 `fnm_runs` 状态
- `GET /api/doc/<doc_id>/fnm/notes?page=<bp>` — 按页筛选返回注释列表

---

## FNM 翻译模式（TASK_KIND_FNM）

**新增常量（`translate_state.py`）：**

```python
TASK_KIND_FNM = "fnm"
```

**新文件：`translate_worker_fnm.py`**

不复用 `run_translate_worker` 骨架（该骨架以整数 bp 为单位，不适配 unit_id），自行实现 `run_fnm_worker` 循环，只复用 `_save_translate_state` 等 helper。

```
run_fnm_worker(doc_id, doc_title, deps)
  ├─ 读 fnm_translation_units（status=pending/error，按 section+kind 排序）
  ├─ 每个 unit：
  │    ├─ body：source_text（含冻结 token）送 LLM，写 translated_text
  │    ├─ footnote/endnote：加专用 system prompt，独立翻译
  │    └─ 完成后：
  │         ├─ 回填冻结 token → Obsidian 引用
  │         ├─ 更新 fnm_translation_units.status = done
  │         └─ 更新 fnm_notes.translated_text（footnote/endnote）
  └─ 全部完成后更新 fnm_runs 汇总状态
```

**冻结 token 回填规则：**

| 冻结 token | 回填结果 |
|---|---|
| `{{FN_REF:fn-02-0003}}` | `[^fn-02-0003]` |
| `{{EN_REF:en-02-0001}}` | `[EN-en-02-0001]` |

**进度映射：**

- `total_pages` = `fnm_translation_units` 总数
- `done_pages` = status=done 的 unit 数
- 前端进度条不需要修改

**启动入口（`translate_launch.py`）：** 新增 `start_fnm_translate_task()`，和现有 `start_translate_task()` 并列。

---

## 阅读页 UI 变更

**改动文件：** `templates/reading.html`、`app.py`（新增路由）

**注释侧栏：**

- 内嵌在现有阅读页，可收起
- 两个标签：**脚注** / **尾注**
- 脚注：展示当前页的脚注列表（`fnm_notes` 按 `start_page` 筛选）
- 尾注：展示当前 section 的尾注列表
- 每条显示：`[marker]` + 原文 + 译文（若已翻译）

**FNM 翻译按钮：**

- 文档详情页新增"FNM 翻译"按钮
- 仅在 `fnm_runs.status = done` 时可用
- 与"连续翻译"按钮互斥（同时只能运行一个任务）

**降级：** `fnm_runs` 不存在或 status=error 时，侧栏显示"注释分类不可用"，不显示空列表。

---

## Markdown 导出变更

**新文件：`fnm_export.py`**

**触发方式：** 现有导出路由新增参数 `format=fnm_obsidian`，旧路径（`storage_endnotes.py`）不变。

```
build_fnm_obsidian_export(doc_id)
  ├─ 读 fnm_notes（含 translated_text）
  ├─ 读 fnm_translation_units（body unit 的 translated_text）
  ├─ 按 section → body chunk → 脚注定义 → 尾注区 拼装
  ├─ 回填冻结 token
  └─ 返回 Obsidian 兼容 Markdown 字符串
```

**输出格式示例：**

```markdown
## Section Title

正文段落，引用示例[^fn-02-0003]，尾注引用[EN-en-02-0001]

### Endnotes

[EN-en-02-0001] 尾注译文

[^fn-02-0003]: 脚注译文
```

**未翻译 unit 的处理：** 用原文填入，不留空白。

**导出 UI：** 现有导出页新增单选："标准导出" / "FNM Obsidian 导出（脚注/尾注分层）"。FNM 选项在 `fnm_runs.status != done` 时灰掉，附 tooltip 说明原因。

---

## 改动文件清单

| 类型 | 文件 |
|---|---|
| 新增 | `fnm_pipeline.py` |
| 新增 | `translate_worker_fnm.py` |
| 新增 | `fnm_export.py` |
| 修改 | `translate_state.py`（新增常量） |
| 修改 | `translate_launch.py`（新增启动函数） |
| 修改 | `app.py`（新增路由、导出参数） |
| 修改 | `templates/reading.html`（注释侧栏） |
| 修改 | SQLite schema 迁移脚本（v5→v6） |
| 不动 | `translate_worker_continuous.py` |
| 不动 | `translate_worker_common.py` |
| 不动 | `storage_endnotes.py` |
| 不动 | `FootNoteMachine/scripts/*.py` |

---

## 边缘情况

1. **FNM 分类失败**：`fnm_runs.status = error`，翻译和导出的 FNM 选项均不可用，不影响旧模式
2. **旧文档无 FNM 数据**：侧栏和 FNM 导出降级显示，不报错
3. **部分 unit 翻译失败**：导出时未翻译的 unit 用原文填入；UI 标记哪些 unit 失败
4. **FNM 分类和旧翻译并存**：同一文档可以先跑旧模式翻译，再跑 FNM 翻译，两套结果互不覆盖
5. **冻结 token 回填缺失**：如果 LLM 删除了冻结 token，回填时检测不到，保留原文位置空白并记录警告
6. **跨页脚注显示**：`fnm_notes.pages` 是数组，侧栏在脚注 `start_page` 所在页展示该条，不重复展示
