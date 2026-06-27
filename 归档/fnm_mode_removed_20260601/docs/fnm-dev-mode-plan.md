# FNM 开发者模式 —— 实施计划

> 目标：为 FNM 模式（Phase 1~6）增加一个独立的「开发者模式」网页，支持多本书并行调试、按阶段单独运行/重置、每阶段独立 Gate、报错时提供 PDF ↔ 中间产物 ↔ 导出文件的三方对照视图。
>
> 决策基线：
> - 单阶段执行 = 只跑该 Phase，从 SQLite 上游表读输入（方案 A）
> - 重置某阶段会级联清该阶段及下游所有产物表
> - 独立路由 `/dev/fnm`，不污染生产首页
> - 翻译模式提供 test/real 切换开关
> - Gate 硬约束 + 显式"强制跳过"按钮（二次确认）
> - 多书并发：每本书一个独立后台线程
> - PDF 渲染用 pixel-perfect 的 PDF.js；三栏高亮段落级即可
> - 测试用书重用 `raw_pages.json`，可跳过 OCR

---

## 一、范围与边界

**In scope**
- 新路由 `/dev/fnm`（HTML 页面）与 API 前缀 `/api/dev/fnm/*`
- 每阶段独立 run / reset / diagnose 能力
- 每阶段 Gate 报告（`GateReport`）
- 三方对照诊断视图（PDF 页 / 产物 JSON·MD / 导出 MD）
- 翻译测试开关（test 模式默认、real 模式开关）
- 快照与回放（`fnm_dev_snapshots`）

**Out of scope**
- 不改造 FNM_RE 算法本身（只读调用其 `build_phase{N}_structure`）
- 不动生产首页 FNM 卡片逻辑
- 不做权限体系（本地工具，假定单用户）
- 不做 OCR 重跑（开发者模式假定 `raw_pages.json` 已存在）

---

## 二、数据模型改动

### 2.1 新表 `fnm_phase_runs`
```sql
CREATE TABLE IF NOT EXISTS fnm_phase_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    phase INTEGER NOT NULL,           -- 1..6
    status TEXT NOT NULL,             -- idle|running|ready|failed|skipped_forced
    gate_pass INTEGER NOT NULL DEFAULT 0,  -- 0/1
    gate_report_json TEXT,            -- GateReport 序列化
    errors_json TEXT,                 -- [{code, message, evidence_refs}]
    started_at TEXT,
    ended_at TEXT,
    execution_mode TEXT DEFAULT 'test',  -- test|real（仅 phase=5 使用）
    forced_skip INTEGER NOT NULL DEFAULT 0,
    UNIQUE(doc_id, phase)
);
CREATE INDEX IF NOT EXISTS idx_fnm_phase_runs_doc ON fnm_phase_runs(doc_id);
```
写到 `persistence/sqlite_schema.py`，在现有 `fnm_runs` 之后插入；同时加到 `sqlite_split_migration.py` 的 per-doc 表列表。

### 2.2 新表 `fnm_dev_snapshots`
```sql
CREATE TABLE IF NOT EXISTS fnm_dev_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    phase INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    size_bytes INTEGER,
    blob_path TEXT NOT NULL           -- 相对 doc_dir 的路径，如 dev_snapshots/phase3_20260416_143000.json
);
CREATE INDEX IF NOT EXISTS idx_fnm_dev_snapshots_doc_phase
    ON fnm_dev_snapshots(doc_id, phase, created_at);
```

### 2.3 不改现有表
`fnm_runs`、`fnm_pages`、`fnm_chapters` 等全部保持原样，开发者模式只「读产物表」+「写自己的 phase_runs / snapshots」。

---

## 三、后端模块设计

### 3.1 新文件

| 文件 | 职责 |
|---|---|
| `web/dev_routes.py` | Flask blueprint，注册 `/dev/fnm` 与 `/api/dev/fnm/*` |
| `FNM_RE/dev/phase_runner.py` | 单阶段执行器（读上游表 → 调 `build_phase{N}_structure` → 写下游表） |
| `FNM_RE/dev/gates.py` | 6 个 Gate 的判据函数，产出 `GateReport` |
| `FNM_RE/dev/diagnostics.py` | 构建三方对照 payload（PDF 页号、产物 row、导出片段） |
| `FNM_RE/dev/reset.py` | 阶段级联重置（清下游表 + phase_runs 状态回落） |
| `FNM_RE/dev/thread_pool.py` | 每本书一个后台线程的管理（dict\<doc_id, Thread\>，防重入） |
| `persistence/sqlite_repo_dev.py` | `fnm_phase_runs` / `fnm_dev_snapshots` 的 DAO |

### 3.2 API 清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/dev/fnm` | 开发者模式主页（HTML） |
| GET | `/api/dev/fnm/books` | 所有书 + 每本的 `phase_states[1..6]` 矩阵 |
| POST | `/api/dev/fnm/import` | 「从现有 doc 导入」：读 `raw_pages.json`，创建 `fnm_phase_runs` 的初始行 |
| GET | `/api/dev/fnm/book/<doc_id>/status` | 该书完整状态：phase_runs、gate reports、是否有线程在跑 |
| POST | `/api/dev/fnm/book/<doc_id>/phase/<n>/run` | body: `{execution_mode?, force_skip?}`；启动单阶段后台线程 |
| POST | `/api/dev/fnm/book/<doc_id>/phase/<n>/reset` | 级联清 phase≥n 的产物与 phase_runs |
| POST | `/api/dev/fnm/book/<doc_id>/phase/<n>/force-skip` | 把该 phase 标记 `skipped_forced` + `gate_pass=1`（二次确认） |
| GET | `/api/dev/fnm/book/<doc_id>/phase/<n>/diagnostics` | 返回 `{failures: [...], evidence: {...}}` |
| GET | `/api/dev/fnm/book/<doc_id>/pdf/page/<p>` | 透传 PDF.js 所需字节流（range 支持） |
| GET | `/api/dev/fnm/book/<doc_id>/artifact/<phase>/<table>/<row_id>` | 产物表单行 JSON |
| GET | `/api/dev/fnm/book/<doc_id>/export-fragment/<chapter_id>` | Phase 6 导出 MD 片段 |
| GET | `/api/dev/fnm/book/<doc_id>/phase/<n>/snapshots` | 快照列表 |
| POST | `/api/dev/fnm/book/<doc_id>/phase/<n>/snapshot` | 为当前产物建快照 |

### 3.3 单阶段执行逻辑（以 Phase 3 为例）

```
phase3_run(doc_id):
  assert phase2_gate_pass(doc_id)  # 除非 forced_skip
  pages       = repo.load_pages(doc_id)
  chapters    = repo.load_fnm_chapters(doc_id)     # Phase1 产物
  note_items  = repo.load_fnm_note_items(doc_id)   # Phase2 产物
  note_regions= repo.load_fnm_note_regions(doc_id)
  phase3 = build_phase3_structure(pages, chapters, note_items, note_regions, ...)
  repo.save_body_anchors(doc_id, phase3.body_anchors)
  repo.save_note_links(doc_id, phase3.note_links)
  report = gates.phase3(phase3)
  repo.upsert_phase_run(doc_id, 3, status='ready' if report.pass else 'failed', gate_report=report)
```

各 Phase 所需上游表（落到 `phase_runner.py`）：

| Phase | 读 | 写 |
|---|---|---|
| 1 | `fnm_pages`（从 `raw_pages.json` 导入）、toc items | `fnm_pages`, `fnm_chapters`, `fnm_section_heads`, `fnm_heading_candidates` |
| 2 | Phase1 三表 | `fnm_note_regions`, `fnm_note_items`, `fnm_chapter_note_modes` |
| 3 | Phase1~2 所有表 | `fnm_body_anchors`, `fnm_note_links` + ref_freeze 注入（写回 `fnm_pages.frozen_text`） |
| 4 | Phase1~3 所有表 + `fnm_review_overrides_v2` | `fnm_structure_reviews`, `fnm_runs.blocking_reasons` |
| 5 | Phase1~4 + `fnm_structure_reviews` | `fnm_translation_units`（test 模式伪造译文；real 模式走 FNM Worker） |
| 6 | 所有上游 | 生成导出 markdown 到 `dev_exports/` 目录（不覆盖生产导出）+ `export_audit` |

### 3.4 Gate 判据（正式版）

在 `FNM_RE/dev/gates.py` 中每个 Gate 返回：
```python
@dataclass
class GateFailure:
    code: str             # e.g. "phase3.orphan_anchor"
    message: str
    evidence_refs: list[EvidenceRef]  # 指向 PDF 页 / 产物 row / 导出片段

@dataclass
class GateReport:
    phase: int
    pass_: bool
    failures: list[GateFailure]
    warnings: list[GateFailure]  # 软告警不计入 pass 判定
```

判据：

| Phase | pass 条件 | warning（不阻塞） |
|---|---|---|
| 1 | `page_partitions` 非空、每章有至少 1 页、`toc_alignment_review_required==0` | 个别章节无 section_heads |
| 2 | 所有 `note_regions.note_kind` 非空、`region_marker_alignment_ok==True`、无 `chapter_note_modes=="review_required"` | 有 `no_notes` 章节 |
| 3 | `footnote_orphan_note / footnote_orphan_anchor / endnote_orphan_* / ambiguous` 全为 0、`freeze.only_matched_frozen`、`freeze.no_duplicate_injection` | `synthetic_anchor` 计数 > 0 |
| 4 | `structure_state=="ready"` 且 `blocking_reasons==[]` | `footnote_orphan_anchor_warn` |
| 5 | 所有 `translation_units.source_text` 非空；real 模式下所有 unit `status=done` 且无不可重试错误；test 模式下所有 unit 标记 `pseudo_done` | 慢 unit > 阈值 |
| 6 | `can_ship==True`、`NOTE_REF` 残留 == 0、章节覆盖 == TOC | raw marker 残留（警示但可过） |

### 3.5 多书并发（`thread_pool.py`）

```python
_workers: dict[str, Thread] = {}
_lock = Lock()

def spawn(doc_id, phase, fn):
    with _lock:
        existing = _workers.get(doc_id)
        if existing and existing.is_alive():
            raise Busy(doc_id)
        t = Thread(target=_run, args=(doc_id, phase, fn), daemon=True)
        _workers[doc_id] = t
        t.start()
```
- 不同 `doc_id` 并发；同 `doc_id` 串行（返回 409 Busy）。
- 线程状态反映到 `fnm_phase_runs.status=running`。
- 进程重启后看到 `running` 且无线程存活 → 自动回落为 `failed`（`errors_json` 写入 "interrupted"）。

### 3.6 级联重置

```
reset(doc_id, phase=N):
  # 清 phase_runs 中 phase >= N 的行
  # 清下列表中该 doc_id 的行（按 phase 映射）
  for p in range(N, 7):
      for table in PHASE_OUTPUT_TABLES[p]:
          conn.execute(f"DELETE FROM {table} WHERE doc_id=?", (doc_id,))
  # dev_exports/ 下该 doc 目录清空（若 N<=6）
```
事务内完成，失败回滚。

---

## 四、前端设计

### 4.1 页面路由
- `/dev/fnm` → `templates/dev/fnm_home.html`（书列表 + 卡片）
- `/dev/fnm/book/<doc_id>` → `templates/dev/fnm_book.html`（单本详情 + 诊断抽屉）

### 4.2 卡片组件（列表页）
```
┌─────────────────────────────────────────────┐
│ 《某书》 doc_id=abc123    [从 raw_pages 导入]│
│ P1 ✓  P2 ✓  P3 ●running  P4 ○  P5 ○  P6 ○  │
│ [跑 P3] [重置 P3+] [诊断 P3] [强制跳过 P3]   │
└─────────────────────────────────────────────┘
```
- 状态颜色：✓ 绿 / ● 蓝（跑动画） / ✗ 红 / ○ 灰（未解锁） / ⚠ 橙（forced_skip）
- 未解锁按钮禁用；「强制跳过」始终可点但弹二次确认。

### 4.3 诊断抽屉（三栏）

```
┌─────────┬──────────────────┬───────────────┐
│ PDF 页  │ 中间产物 JSON/MD │ 导出 MD（若有）│
│ (PDF.js)│ (语法高亮)       │ (语法高亮)     │
│         │                  │                │
│[段落1]  │ {body_anchors:..}│ # Chapter 1    │
│[段落2●] │ {note_links:[..]}│ ...[^1]        │
│        │  ^ 高亮同步       │  ^ 高亮同步     │
└─────────┴──────────────────┴───────────────┘
错误列表：
  - [phase3.orphan_anchor] page=42, anchor_id=a_42_3
    → 建议：该处正文 marker 未匹配到注释条目，检查…
    [定位] [查看 override 记录]
```

- PDF.js 用本地打包资源（`static/vendor/pdfjs/`），首次加载懒加载。
- 段落级同步：每条 `EvidenceRef` 包含 `{page_no, paragraph_idx, artifact_row_id, export_line_range}`，点击任一栏时三栏滚到对应位置并高亮。
- 错误条目可展开「修复建议」—— Gate 函数内嵌的启发式文案（见 4.4）。

### 4.4 修复建议文案（写在 `gates.py` 里）

每个 GateFailure.code 配一个中文修复建议模板，例：
- `phase3.orphan_anchor` → "该处正文有编号但无匹配注释。常见原因：注释页未被纳入 note_region（检查 Phase 2 的 `region_marker_alignment_ok`）、或编号格式不在识别白名单。修复入口：[Phase 2 诊断](…) / [编辑 note_regions override](…)"
- `phase6.note_ref_residual` → "导出文件中残留 `{{NOTE_REF:…}}` 占位符。表示 Phase 3 注入后没有在 `chapter_merge` 阶段替换。检查 `ref_freeze.accounting_closed` 是否为真。"

### 4.5 翻译开关（Phase 5）
卡片里 Phase 5 格子旁放 toggle：`[test] | [real]`。
- test：用 `source_text` 前加 `【TEST】` 前缀作伪译文，零 API 调用；便于验证下游导出。
- real：走现有 FNM Worker（`web/translation_routes.py` 的路径），API Key 缺失时拒绝。

---

## 五、落地顺序（建议分 6 个 PR / commit）

1. **Schema + DAO + 导入接口**
   - `fnm_phase_runs` / `fnm_dev_snapshots` 建表
   - `sqlite_repo_dev.py`
   - `POST /api/dev/fnm/import`（从 raw_pages.json 初始化）
   - 单测：DAO CRUD、import 幂等

2. **线程池 + Phase 1 / 2 执行器 + reset**
   - `thread_pool.py`、`phase_runner.py`（先实现 Phase 1/2）
   - `reset.py`（级联）
   - API：`/phase/1/run`、`/phase/2/run`、`/phase/N/reset`、`/status`
   - 集成测试：跑一本小书的 P1→P2，reset 回 P1 再跑

3. **Gate 1~3 + Phase 3 执行器 + gate_report**
   - `gates.py` 1~3 的判据
   - Phase 3 执行器
   - 修复建议文案初版

4. **前端骨架**
   - `templates/dev/fnm_home.html` + `fnm_book.html`
   - 书列表、卡片、按钮线框、轮询状态
   - 无诊断抽屉

5. **诊断抽屉（三栏对照）**
   - PDF.js 集成、段落级 EvidenceRef 联动
   - 产物 row API、导出片段 API
   - 错误修复建议渲染

6. **Phase 4 / 5 / 6 执行器 + 翻译开关 + 快照**
   - Phase 4 调 `build_phase4_status`
   - Phase 5 test 模式 + real 模式接线
   - Phase 6 写到 `dev_exports/<doc_id>/`
   - 快照 API + 回放对比（diff 视图，可延后）

---

## 六、风险与缓解

| 风险 | 缓解 |
|---|---|
| `FNM_RE/app/pipeline.py` 的 `build_phaseN_structure` 函数签名可能期望从上游**完整对象**入参，而不是零散的 SQLite row | 落地第 2 步时先跑通一本样本书，验证 DAO 装载能还原完整对象；必要时在 `phase_runner.py` 加 adapter |
| `chapter_skeleton.py` 仍有旧 `fnm.fnm_structure` 依赖（见 `FNM_RE/DEV_FNM.md`） | 开发者模式先只读调用，不触发重构；遇到进口失败再单独修 |
| Phase 3 的 ref_freeze 会改写 `fnm_pages.frozen_text`；重跑 Phase 3 需要先回滚 | 在 Phase 3 执行器开头复位该字段，reset(3) 也要清理 |
| 多线程对 SQLite 并发写（不同 doc 但同 DB 文件） | 每个 doc 用独立 `doc.db`，catalog.db 只在 `phase_runs` DAO 里加 busy_timeout=5000 |
| PDF.js 体积 | 仅在抽屉打开时加载（动态 import）；首页不引入 |
| 进程重启遗留 `running` 行 | 启动钩子扫描并标记为 `failed + interrupted` |

---

## 七、边缘情况清单（自验收用）

- [ ] 上传新书后直接跑 Phase 3 → 应被 Gate 拒绝（未解锁）
- [ ] Phase 2 失败后点 Phase 3 → 被硬约束挡住；点强制跳过 → 有二次确认，跳过后 Phase 3 可运行但 UI 上 Phase 2 显示 ⚠
- [ ] 同一本书连点两次同 phase → 第二次返回 409 Busy
- [ ] 不同书同时跑各自的 phase → 两个线程并行成功
- [ ] 跑 Phase 3 时进程被 kill → 重启后状态自动回落为 failed
- [ ] 跑完 Phase 6 后 reset 回 Phase 2 → `dev_exports/<doc_id>/` 被清、phase_runs 回落、Phase 3~6 产物表清空
- [ ] Phase 5 real 模式 API Key 缺失 → 400 错误，UI 红条提示
- [ ] 诊断视图里点某条 orphan_anchor → PDF 页定位到该页、产物栏滚到对应 `note_links` row、导出栏（若有）定位到对应行
- [ ] test 模式翻译后导出 → 导出文件里能看到 `【TEST】` 前缀验证管线贯通
- [ ] 导入 raw_pages.json 但文件缺失 → 返回 404 并在卡片显示「无原始页」
- [ ] 两本书中一本删掉 → 卡片自动消失、phase_runs 级联清

---

## 八、变更文件预估

**新增**：
- `web/dev_routes.py`
- `FNM_RE/dev/__init__.py`
- `FNM_RE/dev/phase_runner.py`
- `FNM_RE/dev/gates.py`
- `FNM_RE/dev/diagnostics.py`
- `FNM_RE/dev/reset.py`
- `FNM_RE/dev/thread_pool.py`
- `persistence/sqlite_repo_dev.py`
- `templates/dev/fnm_home.html`
- `templates/dev/fnm_book.html`
- `static/dev/fnm.css`
- `static/dev/fnm.js`
- `static/vendor/pdfjs/`（第三方资源）
- `tests/unit/test_dev_phase_runner.py`
- `tests/unit/test_dev_gates.py`
- `tests/integration/test_dev_fnm_flow.py`

**修改**：
- `persistence/sqlite_schema.py`（加 2 张表）
- `persistence/sqlite_split_migration.py`（把 phase_runs 加入 per-doc 列表）
- `app.py` 或 `web/services.py`（注册新 blueprint）
- `templates/base.html`（导航加「开发者模式」入口，仅 debug 模式显示）

---

## 九、开发者模式入口可见性

- 默认**只在 `app.debug=True` 或环境变量 `FNM_DEV_MODE=1`** 时才注册 blueprint、显示导航入口。
- 生产启动（`start_managed.sh` 等）默认不开。
- 入口位置：base.html 顶栏加一个「🛠 开发者」链接。
