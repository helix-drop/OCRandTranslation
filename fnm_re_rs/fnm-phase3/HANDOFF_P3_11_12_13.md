# Phase 3 接通方案（P3.11 + P3.12 + P3.13）

**目标**：把已有的 13 个 `note_linking/` 子模块串成完整 pipeline，让 `build_phase3_structure` 真正等价 Python `note_linking.build_note_link_table`（1730 行），跑通 byte-equal Biopolitics parity。

**当前状态**：
- 31 个 `.rs` 文件全部编译通过，0 errors / 0 warnings。
- 43 个单测过；2 个 SPEC 测试 ignored；biopolitics parity 只有 1 个 smoke + 1 个 ignored（**没有 golden fixture 生成器，没有 byte-equal 比对**）。
- `note_linking/mod.rs::build_note_link_table` 是 stub——只调 `body_anchors` + `note_links`，**13 个子模块完全不接通**。
- `lib.rs::build_phase3_structure` 跳过 `note_linking` 顶层；summary 全空；`persist_phase3` 只写 2 张表（plan 要 5 张）。
- **缺失依赖**：Rust 端无 `endnote_repair` crate（Python `FNM_RE/modules/endnote_repair.py` 325 行，3 个 public 函数：`project_priority` / `repair_endnote_links_for_contract` / `suppress_endnote_residual_orphans`）。

**预估工时**：12-15 天（P3.11 接通 6 天，P3.12 持久化 2 天，P3.13 golden + parity 4-5 天，加 endnote_repair 缺口 1-2 天）。

---

## Part A：必读文档（按优先级 + 大致内容）

### 🔴 P0 — 强制先读

| 文档 | 行数 | 大致内容 |
|---|---:|---|
| `AGENTS.md` §「Rust 重构代码规范」（12 条铁律，行 281-540） | ~260 行 | **不可绕过的硬约束**。重点：①翻译保真度禁简化 ②Regex 必须 `Lazy<Regex>` 静态 ③复用 fnm-core 不重复造 ⑦Parity byte-equal Python ⑧关键参数禁 `let _ = ...` ⑨Stub 用 `anyhow::bail!` 不静默返空 |
| `AGENTS.md` §「Phase 3：锚点检测与链接匹配」（行 109-125） | ~17 行 | Phase 3 决策权 / 输入 / 产出 / **禁止项**（不重分类 note_kind / 不用 chapter_mode 跳过 link 修复 / 不广播 anchor_kind） |
| `AGENTS.md` §「树枝状条件处理」+「五条铁律」（行 41-67） | ~27 行 | 分类源头唯一、分支穷尽互斥、禁止广播、上下游隔离、集中 dispatch |
| `CLAUDE.md` 第 8 / 12 条（项目根） | 全文 ~30 行 | Phase 边界 + 树枝状条件——所有改动都要过这两条 |
| `FNM_RE/FNM_PHASE3_PLAN.md` §3-§5（行 113-435） | ~320 行 | P3.0-P3.13 任务规格。**重点 §3.13**：`modules/note_linking.py` 子模块拆分对照表；**§4 实施顺序**列了 P3.11 是 6 天「最大头」；**§5.11**：14 子模块的 Python 函数对应 |

### 🟡 P1 — 接通前细看

| 文档 | 行数 | 大致内容 |
|---|---:|---|
| `FNM_RE/modules/note_linking.py` 行 1430-1659 | 230 行 | **`build_note_link_table` 完整流程**——20 步顺序，每个 helper 的 input/output 都要逐行对照翻译 |
| `FNM_RE/modules/note_linking.py` 行 1-50 | 50 行 | imports 清单——直接告诉你 Rust 端**还差哪些依赖**（`endnote_repair.repair_endnote_links_for_contract` / `suppress_endnote_residual_orphans` / `_group_review_overrides` 是否就绪） |
| `FNM_RE/modules/endnote_repair.py` 全文 | 325 行 | **Rust 端不存在**。需补一个 `fnm-phase3/src/endnote_repair.rs`（或独立 crate `fnm-endnote-repair`）。3 个 pub 函数 |
| `FNM_RE/RUST_MIGRATION_PLAN.md` Step 3 段（行 235-265） | ~30 行 | Step 3 模块对应表 + 性能关注点 + SPEC 测试列表 |
| `FNM_RE/RUST_MIGRATION_PLAN.md` §「DB schema」（行 481-499） | ~20 行 | Phase 3 写哪 5 张表 |
| `fnm_re_rs/fnm-phase3/FNM_PHASE3_PLAN.md` 不存在 | - | （别找）真正的 plan 在 `FNM_RE/FNM_PHASE3_PLAN.md` |

### 🟢 P2 — 实施期对照

| 文档 | 行数 | 大致内容 |
|---|---:|---|
| `fnm_re_rs/fnm-phase3/src/note_linking/mod.rs` | 109 行 | **当前 stub 入口**——你要把它从 60 行扩到 ~250 行 |
| `fnm_re_rs/fnm-phase3/src/lib.rs` | 125 行 | `build_phase3_structure` 顶层——要改成调 `note_linking::build_note_link_table` |
| `fnm_re_rs/fnm-core/src/records.rs` 行 85-95、162-266、433-466 | ~80 行 | **真实 Rust struct 定义**——`ChapterRecord` 只有 7 字段，`ChapterLayer`（在 fnm-phase2）才有 `body_pages` / `policy_applied` / `footnote_items` / `endnote_items`。C 在这里栽过跟头 |
| `fnm_re_rs/fnm-phase2/src/chapter_split/mod.rs` 行 15-68 | ~55 行 | `ChapterLayer` / `ChapterLayers` 真实定义 |
| `fnm_re_rs/fnm-core/src/db/repository.rs` 全文 | ~600 行 | Repository trait + SqliteRepository——你要补 3 个新方法 |
| `fnm_re_rs/fnm-core/migrations/0001_initial.sql` 行 219-308 | ~90 行 | **3 张 Phase 3 表的 SQL 已存在**（`fnm_chapter_anchor_alignment` / `fnm_chapter_endnotes` / `fnm_paragraph_footnotes` / `fnm_review_overrides_v2`），只需补 trait 方法和 INSERT |
| `fnm_re_rs/fnm-phase2/tests/biopolitics_phase2_parity.rs` 行 1-100 | ~100 行 | **抄它的模板**——golden JSON 加载、逐字段断言、`#[derive(Deserialize)] struct GoldenFixture` |
| `tools/gen_biopolitics_phase2_golden.py` | ~150 行 | **抄它的模板**——生成 Phase 3 golden 的脚手架 |
| `fnm_re_rs/fnm-phase3/tests/known_python_bugs.md` | 短 | 任何 Rust ≠ Python 的 diff 都要记录这里，附根因 |

---

## Part B：当前缺口清单（按依赖顺序）

### B1. fnm-core 缺口

**严格对齐 Python `sqlite_repo_fnm.py` 的 4 method 设计**（不要合并进 `Phase3Products`，铁律 §1 翻译保真度 + §7 byte-equal）：

| 缺口 | 位置 | 修法 |
|---|---|---|
| `Phase3Products` **保持现状**（仅 2 字段） | `fnm-core/src/db/repository.rs:34` | **不要**扩字段。`replace_fnm_phase3_products` 严格对齐 Python：只 INSERT `body_anchors` + `note_links` 2 张表 |
| Repository trait 缺 3 个写方法 | `fnm-core/src/db/repository.rs:55-57` | 补 3 个，**对应 Python 同名方法**：<br>① `replace_fnm_chapter_endnotes(doc_id, chapter_id, rows: &[ChapterEndnoteRecord])`（**按章 scope**，每次只清/写该章）<br>② `replace_fnm_paragraph_footnotes(doc_id, chapter_id, rows: &[ParagraphFootnoteRecord])`（**按章 scope**）<br>③ `upsert_fnm_chapter_anchor_alignment(doc_id, rows: &[ChapterAnchorAlignmentRecord])`（**整批 upsert**，UNIQUE(doc_id, chapter_id) 上 ON CONFLICT REPLACE） |
| Repository trait 缺 4 个读方法 | `fnm-core/src/db/repository.rs:55-57` | 补：`list_fnm_chapter_anchor_alignments` / `list_fnm_chapter_endnotes` / `list_fnm_paragraph_footnotes` / `list_fnm_review_overrides_v2`（read-side，Phase 4+ 会用） |
| `replace_fnm_phase3_products` DELETE 顺序 | `fnm-core/src/db/repository.rs:534` | **照 Python `sqlite_repo_fnm.py:956-966`**：phase>=3 时 DELETE 5 张表（含 chapter_anchor_alignment / paragraph_footnotes / chapter_endnotes），但 INSERT 只 2 张。另外 3 张由上面 3 个新方法独立调用 |
| `Phase3Output` 字段不全 | `fnm-phase3/src/output.rs` | 当前只含 `structure`。要加 `note_link_table` / `evidence` / `diagnostics` / `gate_report`（参考 Python `ModuleResult[NoteLinkTable]`） |

**Rust struct 已就绪**（不需新建）：
- `ChapterEndnoteRecord` — `fnm-core/src/records.rs:378`
- `ParagraphFootnoteRecord` — `fnm-core/src/records.rs:400`
- `ChapterAnchorAlignmentRecord` — `fnm-core/src/records.rs:418`

### B2. fnm-phase3 缺失模块

| 缺口 | 位置 | Python 源 |
|---|---|---|
| `endnote_repair.rs` 不存在 | 应建 `fnm-phase3/src/endnote_repair.rs`（~325 行） | `FNM_RE/modules/endnote_repair.py` 全文 |
| `build_note_link_table` 只是 stub | `fnm-phase3/src/note_linking/mod.rs:55` | `FNM_RE/modules/note_linking.py:1430-1658` |
| `build_phase3_structure` 跳过 note_linking | `fnm-phase3/src/lib.rs:31` | 改造为先调 phase2_rebuild → 再调 `build_note_link_table` → 最后填 `Phase3Structure` |
| `persist_phase3` 只写 2 张表 | `fnm-phase3/src/lib.rs:114` | 扩写 5 张表（依赖 B1 改完） |

### B3. 测试与 fixture 缺口

| 缺口 | 位置 | 修法 |
|---|---|---|
| 无 Phase 3 golden 生成器 | 应建 `tools/gen_biopolitics_phase3_golden.py` | 抄 `tools/gen_biopolitics_phase2_golden.py` 模板，跑 Python `build_note_link_table` 输出 JSON |
| `biopolitics_phase3_parity.rs` 只有 smoke | `fnm-phase3/tests/biopolitics_phase3_parity.rs:64` | 加 4 个 field-by-field 测试（body_anchors / note_links / chapter_anchor_alignment / chapter_link_contracts） |
| `spec_biopolitics_contract_v2_def_anchor_mismatch` 一直 ignored | 同上，行 95 | P3.11 接通后改 `#[test]`，确认通过 |

---

## Part C：5 个 PR 分解（推荐串行）

### PR-1：`endnote_repair` 模块前置（1.5 天）

**为什么先做**：B2 的所有其他模块都依赖它。`build_note_link_table` 第 1463 行就调 `repair_endnote_links_for_contract`。

**任务**：
1. 新建 `fnm-phase3/src/endnote_repair.rs`，翻译 `FNM_RE/modules/endnote_repair.py` 全部 3 个 pub 函数：
   - `project_priority(mode: &str) -> i32`（最简单，先做练手）
   - `repair_endnote_links_for_contract(links, anchors, note_item_meta_by_id, book_type) -> (Vec<NoteLinkRecord>, Value)`（核心，~200 行）
   - `suppress_endnote_residual_orphans(links, book_type) -> (Vec<NoteLinkRecord>, Value)`（~80 行）
2. 注册到 `fnm-phase3/src/lib.rs`：`pub mod endnote_repair;`
3. 每个函数写至少 1 个 hand-crafted 单测（不必 byte-equal，先确保编译过 + 基本 assert）

**验收**：`cargo test -p fnm-phase3 endnote_repair` 全过；`cargo clippy -p fnm-phase3 -- -D warnings` 0 警告。

**铁律检查**：每个 `pub fn` 加 `←→ Python xxx()` doc comment（铁律 §5）；不要循环内 `Regex::new`（§2）；不要 `Rc<RefCell>`（§10）。

---

### PR-2：fnm-core DB 扩展（1.5 天）

**为什么这步**：P3.11 写完时 P3.12 顶层要调这些方法持久化。提前扩好。

**核心原则**：**严格 1:1 对应 Python**——Python 是 4 个独立方法（`replace_fnm_phase3_products` 只写 2 张表，另外 3 张表用 3 个独立方法），Rust 端**不要合并**进一个 `Phase3Products`。

**任务**：
1. **不要**改 `Phase3Products`——保持当前 2 字段（body_anchors + note_links）。
2. `Repository` trait（`fnm-core/src/db/repository.rs:41`）加 3 个写方法 + 4 个读方法：
   ```rust
   // 写方法（与 Python sqlite_repo_fnm.py 同名）
   fn replace_fnm_chapter_endnotes(
       &self, doc_id: &str, chapter_id: &str, rows: &[ChapterEndnoteRecord]
   ) -> Result<()>;
   fn replace_fnm_paragraph_footnotes(
       &self, doc_id: &str, chapter_id: &str, rows: &[ParagraphFootnoteRecord]
   ) -> Result<()>;
   fn upsert_fnm_chapter_anchor_alignment(
       &self, doc_id: &str, rows: &[ChapterAnchorAlignmentRecord]
   ) -> Result<()>;
   
   // 读方法
   fn list_fnm_chapter_endnotes(&self, doc_id: &str) -> Result<Vec<ChapterEndnoteRecord>>;
   fn list_fnm_paragraph_footnotes(&self, doc_id: &str) -> Result<Vec<ParagraphFootnoteRecord>>;
   fn list_fnm_chapter_anchor_alignment(&self, doc_id: &str) -> Result<Vec<ChapterAnchorAlignmentRecord>>;
   fn list_fnm_review_overrides_v2(&self, doc_id: &str) -> Result<Vec<ReviewOverrideRecord>>;
   ```
3. `SqliteRepository` 实现这 7 个方法。对照参考：
   - `replace_fnm_chapter_endnotes` → Python `sqlite_repo_fnm.py:1626-1700`
   - `replace_fnm_paragraph_footnotes` → Python `sqlite_repo_fnm.py:1703-1770`
   - `upsert_fnm_chapter_anchor_alignment` → Python `sqlite_repo_fnm.py:1777-1820`（**注意是 `INSERT ... ON CONFLICT(doc_id, chapter_id) DO UPDATE SET ...`**，整批写）
4. `replace_fnm_phase3_products` **保持只 INSERT 2 张表**——但确认 DELETE 时清 5 张表（对照 Python 行 956-966）。
5. 查 `fnm-core/migrations/0001_initial.sql` 行 219-308 确认 schema 已就绪（**已确认存在**，包括 `fnm_chapter_anchor_alignment` / `fnm_chapter_endnotes` / `fnm_paragraph_footnotes` / `fnm_review_overrides_v2`，**不用写新 migration**）。

**`ReviewOverrideRecord` 不存在**（已核实——Python 端用裸 `dict[str, dict[str, Any]]`，没有 dataclass）。Rust 端新建一个轻量 struct，字段照 `persistence/sqlite_schema.py:664-674` 的 SQL 列：
```rust
// fnm-core/src/records.rs
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ReviewOverrideRecord {
    pub doc_id: String,
    pub scope: String,        // "anchor" / "note_item" / "link" / "page" / "chapter" / ...
    pub target_id: String,
    pub payload_json: String, // 原 JSON，由调用方反序列化
    pub created_at: i64,
    pub updated_at: i64,
}
```
读时直接 `serde_json::from_str(&row.payload_json)` 拿到 Value，再喂给 `group_review_overrides()`。

**验收**：
- `cargo build` 全 workspace 0 warnings；
- `cargo test -p fnm-core db` 通过；
- 写 4 个新单测：建临时 SQLite，分别调 4 个新写方法（包括 upsert 的 ON CONFLICT 路径），用 raw SQL 查回断言 row 数 + 字段值。

---

### PR-3：P3.11 接通——`build_note_link_table` 真实编排（5-6 天，**最大头**）

**严格按 Python `note_linking.py:1437-1658` 顺序翻译**。每一步都对应一个已有子模块或 PR-1 的新模块。

**翻译对照表**（Python 行号 → Rust 应调子模块）：

| Python 行 | Python 调用 | Rust 应调 | 状态 |
|---:|---|---|:-:|
| 1437 | `_phase2_from_chapter_layers(chapter_layers)` | `note_linking::phase2_rebuild::*`（已存在） | ✅ |
| 1438 | `_group_review_overrides(overrides)` | `fnm_core::review_overrides::group_review_overrides` | ✅ |
| 1439 | `_materialize_note_item_overrides(...)` | `note_linking::note_item_overrides::*`（已存在） | ✅ |
| 1443 | `_build_note_item_meta_by_id(chapter_layers)` | `note_linking::chapter_meta::build_note_item_meta_by_id`（已存在） | ✅ |
| 1461 | `build_body_anchors(phase2, pages, pdf_path, bare_digit_verifier)` | `body_anchors::build_body_anchors`（已存在） | ✅ |
| 1462 | `build_note_links(...)` | `note_links::build_note_links`（已存在） | ✅ |
| 1463 | `_repair_endnote_links_for_contract(...)` | `endnote_repair::repair_endnote_links_for_contract` | 🆕 PR-1 |
| 1469 | `_repair_explicit_footnote_anchor_ocr_variants(...)` | `note_linking::ocr_repair::*`（已存在） | ✅ |
| 1474 | `_materialize_anchor_overrides(...)` | `note_linking::anchor_overrides::materialize_anchor_overrides`（已存在） | ✅ |
| 1477 | `_chapter_body_text_by_page(chapter_layers)` | `note_linking::chapter_body_text::*`（已存在） | ✅ |
| 1479 | `_refresh_anchor_summary(...)` | `note_linking::anchor_summary::refresh_anchor_summary`（已存在） | ✅ |
| 1480 | `_apply_link_overrides(...)` | `note_linking::link_overrides::apply_link_overrides`（已存在） | ✅ |
| 1487 | `_suppress_endnote_residual_orphans(...)` | `endnote_repair::suppress_endnote_residual_orphans` | 🆕 PR-1 |
| 1493 | `_chapter_contracts(...)` | `note_linking::chapter_contracts::chapter_contracts`（已存在） | ✅ |
| 1531-1533 | `_summarize_links` + `_link_quality_gate` | `note_linking::link_summary::*`（已存在） | ✅ |
| 1617 | `_build_book_endnote_stream_summary(...)` | `note_linking::chapter_meta::build_book_endnote_stream_summary`（已存在） | ✅ |
| 1645-1647 | `_to_anchor_layers` + `_to_link_layers` | `note_linking::layer_conversion::*`（已存在） | ✅ |
| 1634-1658 | 装配 `GateReport` + `ModuleResult` | **新增类型**，参考 Python `NoteLinkTable` / `GateReport` 定义 | 🆕 |

**接通时的边界纪律**（每步都过一遍）：
- ❌ 不要 `let _ = ...` 丢弃 Python 显式返回的 summary（铁律 §8）
- ❌ 不要把多 step 合并成「优化版」——保持逐步对应 Python 行号（铁律 §1，便于审查）
- ❌ 不要重新分类 note_kind——`phase2_rebuild` 已经做完一次源头分类，下游所有 step 只透传（AGENTS.md Phase 3 禁止项）
- ❌ chapter_contracts 计算 `def_anchor_mismatch` 时**不能用 chapter_mode 跳过**（CLAUDE.md §12）
- ✅ 每一步用了哪个子模块、对应 Python 哪行，写到 doc comment

**`Phase3Config::skip_llm_verify` 字段已存在**——若 `true`，不调 `llm_bare_digit_verifier`（Rust 端没有 vision LLM 客户端，**初版强制 `true`**，加 `anyhow::bail!` 防误用：「skip_llm_verify=false 暂不支持，等 fnm-llm-repair crate」）。

**验收**：
- `cargo test -p fnm-phase3 --lib` 17/17 单测仍过；
- 新建集成测试 `tests/build_note_link_table_smoke.rs`：用 Biopolitics raw_pages，端到端调一次 `note_linking::build_note_link_table`，断言：
  - `anchors.len() > 0`
  - `links.len() > 0`
  - `chapter_link_contracts.len() == 12`（Biopolitics 12 章）
  - `evidence["book_type"]` 非空
- `cargo clippy -p fnm-phase3 -- -D warnings` 0 警告。

---

### PR-4：P3.12 lib.rs 顶层 + 持久化（1.5 天）

**前置**：PR-2 + PR-3 都合。

**任务**：
1. `fnm-phase3/src/output.rs` 扩 `Phase3Output`：
   ```rust
   pub struct Phase3Output {
       pub structure: Phase3Structure,
       pub note_link_table: note_linking::NoteLinkTable, // PR-3 输出
       pub evidence: serde_json::Value,
       pub diagnostics: serde_json::Value,
       pub gate_report: GateReport, // 新类型，对照 Python
   }
   ```
2. `fnm-phase3/src/lib.rs:31` 重写 `build_phase3_structure`：
   - 从 `input.phase2_note_regions` + `phase2_note_items` + `phase2_chapter_note_modes` + `phase1_chapters` 重构 `ChapterLayers`（**注意：Rust 端 `ChapterLayers` 在 `fnm_phase2::chapter_split`，要么从 fnm-phase2 拿，要么用 `note_linking::phase2_rebuild` 反构**）；
   - 调 `note_linking::build_note_link_table(chapter_layers, raw_pages, overrides, ...)`；
   - 把返回的 anchors / links / contracts / summary 装到 `Phase3Structure`；
   - 真填 `Phase3Summary`（不再 `default()`）：anchor_summary / note_link_summary / chapter_link_contract_summary 等字段对照 Python 行 1584-1620。
3. `Phase3Input` 加 `overrides: Option<&Value>` 字段（Python 行 1434）。
4. `persist_phase3`（`fnm-phase3/src/lib.rs:114`）扩为**调 4 个 Repository 方法写 5 张表**（严格对齐 Python `pipeline.py` 调用顺序）：
   ```rust
   pub fn persist_phase3(repo: &dyn Repository, doc_id: &str, output: &Phase3Output) -> Result<()> {
       // 1. body_anchors + note_links（保留现有调用）
       repo.replace_fnm_phase3_products(doc_id, &Phase3Products {
           body_anchors: output.structure.body_anchors.clone(),
           note_links: output.structure.note_links.clone(),
       })?;
       // 2. paragraph_endnotes（按章 scope）
       for (chapter_id, rows) in group_by_chapter(&output.structure.paragraph_endnotes) {
           repo.replace_fnm_chapter_endnotes(doc_id, &chapter_id, &rows)?;
       }
       // 3. paragraph_footnotes（按章 scope）
       for (chapter_id, rows) in group_by_chapter(&output.structure.paragraph_footnotes) {
           repo.replace_fnm_paragraph_footnotes(doc_id, &chapter_id, &rows)?;
       }
       // 4. chapter_anchor_alignment（整批 upsert）
       repo.upsert_fnm_chapter_anchor_alignment(doc_id, &output.structure.chapter_anchor_alignments)?;
       Ok(())
   }
   ```
   **`review_overrides_v2` 不写**——那是 Phase 3.5 (`fnm-llm-repair`) 的产物。

**验收**：
- `biopolitics_phase3_smoke` 仍过；
- 现在 `spec_biopolitics_contract_v2_def_anchor_mismatch`（行 95）可以去掉 `#[ignore]`，跑过。

---

### PR-5：P3.13 Golden fixture + byte-equal parity（3 天）

**前置**：PR-4 合。

**任务**：
1. 写 `tools/gen_biopolitics_phase3_golden.py`：抄 `tools/gen_biopolitics_phase2_golden.py` 模板，跑 Python `note_linking.build_note_link_table`，序列化输出到 `fnm_re_rs/fnm-phase3/tests/fixtures/biopolitics_phase3_golden.json`：
   ```json
   {
     "body_anchors": [...],
     "note_links": [...],
     "effective_links": [...],
     "chapter_link_contracts": [...],
     "anchor_summary": {...},
     "link_summary": {...}
   }
   ```
2. `fnm-phase3/tests/biopolitics_phase3_parity.rs` 加 4 个测试（抄 `phase2_parity.rs` 模板）：
   - `biopolitics_body_anchors_match_golden`：anchor_id / chapter_id / page_no / char_start / char_end / source_marker / normalized_marker / anchor_kind / certainty / synthetic **逐字段 byte-equal**
   - `biopolitics_note_links_match_golden`：link_id / status / resolver / note_kind / marker / anchor_id / note_item_id 逐字段
   - `biopolitics_chapter_link_contracts_match_golden`：12 个 contract 的 `first_marker_is_one` / `endnotes_all_matched` / `def_anchor_mismatch` / `marker_sequence` 等字段
   - `biopolitics_phase3_summary_match_golden`：`contract_v2_def_anchor_mismatch_count` 等关键 metric
3. **任何 diff 写入** `fnm-phase3/tests/known_python_bugs.md`（必带根因，否则不允许 merge——铁律 §7）。
4. 翻译剩余 SPEC 测试（4 个之中已通过 3 个，剩 `spec_expected_gap_recovery_disambiguates_by_text` 和 `spec_expected_gap_recovery_keeps_weak_endnote_digits`——但 plan §6 说这 2 个**Python 端就是 ignored**，所以可以延后到独立 PR）。

**验收**：
- 4 个 parity 测试 0 failed；
- `known_python_bugs.md` 内容 ≤ 5 项，且每项都附 Python 行号 + 根因；
- `cargo test --release` 全 workspace 0 failed；
- 性能：`cargo test --release biopolitics_phase3` 单次 < 2 秒（plan §7 目标，Python 30-60s）。

---

## Part D：验收 checklist（每个 PR 通用 + 整体）

**每个 PR 必过**（抄 `FNM_RE/FNM_PHASE3_PLAN.md` §8）：

- [ ] `cargo build --release -p fnm-phase3` 通过
- [ ] `cargo clippy -p fnm-phase3 -- -D warnings` 通过（0 新增 allow）
- [ ] `cargo fmt --check` 通过
- [ ] `cargo test --all` 通过（保持现有 282+ 测试 0 failed）
- [ ] 0 个 `let _ = ...` 忽略关键参数（铁律 §8）
- [ ] 0 个静默 stub（必须 `anyhow::bail!`，铁律 §9）
- [ ] 0 个循环内 `Regex::new()`（铁律 §2）
- [ ] 0 `Rc<RefCell>` / 0 滥用 `Arc<Mutex>`（铁律 §10）
- [ ] PR 描述列出**复用的 fnm-core / fnm-phase1 / fnm-phase2 API**（铁律 §3）
- [ ] PR 描述明确声明：「Phase 3 严守边界，note_kind 仅透传」
- [ ] 每个 `pub fn` 有 `←→ Python xxx()` doc comment（铁律 §5）

**全部 5 PR 合并后整体验收**：

- [ ] `biopolitics_phase3_parity.rs` 4 个 byte-equal 测试通过
- [ ] `spec_biopolitics_contract_v2_def_anchor_mismatch` 不再 `#[ignore]`，通过
- [ ] DB 持久化能往 5 张表写真实数据（手测：临时 SQLite + Biopolitics → SELECT 5 张表都有 row）
- [ ] `note_linking::build_note_link_table` 调用了**所有 13 个子模块**（grep 检查：`use super::*;` 之后每个子模块都有引用点）
- [ ] `known_python_bugs.md` 维护到位（任何 diff 都有根因）

---

## Part E：风险与陷阱（C 已踩过的坑，别再踩）

### E1. ChapterRecord vs ChapterLayer 字段混淆

**C 在这里写错了 15 处**：`ChapterRecord`（fnm-core）只有 7 字段：`chapter_id` / `title` / `start_page` / `end_page` / `pages` / `source` / `boundary_state`。

富字段 `body_pages` / `footnote_items` / `endnote_items` / `endnote_regions` / `policy_applied` 在 **`ChapterLayer`（fnm-phase2::chapter_split）**。

**判断方法**：迭代 `chapter_layers.chapters` 拿到的是 `ChapterRecord`；迭代 `chapter_layers.chapter_layers` 才是 `ChapterLayer`。

### E2. RegionSource 枚举不包含 Python 字符串

Python `RegionSource = Literal[7 个值]` 但运行时用 `# type: ignore` 写 `"llm"` 字符串。Rust 端无运行时绕过——已在 fnm-core 加 `Llm => "llm"` 变体。**如果发现 Python 端有其他字符串绕过 Literal，同样要在 Rust 端扩枚举**。

### E3. 循环内 `Regex::new` 是 §2 铁律红线

C 在 `endnote_links.rs:355-379` 写过 6 处。**已修**——用 marker-keyed `Lazy<Mutex<HashMap>>` cache。如果接通时再写 `Regex::new(&format!(...))`，**必须先建 cache**（参考 `endnote_links.rs:13-44`）。

### E4. `let _ = ...` 是 §8 红线，但有合法用法

合法：对齐 Python `_ = chapter_mode` 的「计算但故意丢弃」语义，引用 CLAUDE.md §12（参见 `phase2_rebuild.rs:43-44`）。

非法：丢弃 Python 显式返回的 summary / logs / diagnostics —— 这些必须装到 Rust 端的 `Phase3Output` 里。

### E5. 章级 mode 不能反向影响 entity 分类

CLAUDE.md §12「树枝状条件处理」最高优先级。`chapter_contracts` 里**不能**写：
```rust
if chapter_mode == "no_notes" {
    skip_def_anchor_mismatch_check();
}
```

正确做法：用 entity 自己的 `requires_endnote_contract`（contract 自己计算的 bool）。

### E6. 不要给 `build_note_link_table` 写「优化版」

铁律 §1：**按 Python 行号顺序逐行翻译**。即使发现某步骤可以合并（如 `_refresh_anchor_summary` 在 `_materialize_anchor_overrides` 之后才调用，看起来可以合并），**也不要合并**——后续 parity diff 时根本对不上 Python 行号。

### E7. SqliteRepository::replace_fnm_phase3_products **只写 2 张表**

**Python 真实行为**（已核实 `sqlite_repo_fnm.py:1029-1042`）：
- `replace_fnm_phase3_products(body_anchors, note_links)` **只 INSERT 2 张表**
- 但 DELETE 时清 5 张表（含 chapter_anchor_alignment / paragraph_footnotes / chapter_endnotes）——目的是「写 phase3 前先清下游残留」
- 另外 3 张表由 3 个**独立方法**写入（`replace_fnm_chapter_endnotes` / `replace_fnm_paragraph_footnotes` / `upsert_fnm_chapter_anchor_alignment`）

**Rust 端必须 1:1 对应**——不要把 5 张表塞进同一个 `Phase3Products` 结构，那是简化（违反铁律 §1）。

### E8. golden fixture 必须从生产 Python 跑

不要在 PR-5 写 hand-crafted golden JSON——必须用 `tools/gen_biopolitics_phase3_golden.py` 跑真实 Python 输出。否则 byte-equal 就成笑话（铁律 §6）。

---

## Part F：开工前 checklist（给做事的人）

- [ ] 读完 Part A 🔴 P0 所有文档（~330 行）
- [ ] 在本地能跑通 Python 端：`PYTHONPATH=. python -c "from FNM_RE.modules.note_linking import build_note_link_table; print(build_note_link_table.__doc__)"`
- [ ] 在本地能跑通 Rust 端：`cd fnm_re_rs && cargo test -p fnm-phase3` 17 单测全过
- [ ] 看过 C 模型在 `note_linking/mod.rs:55` 留下的 stub，确认理解「为什么 13 个子模块都不接通也能编译过」
- [ ] 跟项目负责人确认：是否要把 `endnote_repair` 做成独立 crate（`fnm-endnote-repair`），还是放 `fnm-phase3/src/endnote_repair.rs`（推荐后者，325 行不值得独立 crate）
- [ ] 跟项目负责人确认：`Phase3Config::skip_llm_verify` 初版强制 `true` 是否可接受

---

## Part G：如果你想偷懒……

**不要做**：
- ❌ 跳过 PR-1 直接做 PR-3，等做到 1463 行时再补 `endnote_repair`——会让 PR-3 变成 monster PR
- ❌ 跳过 PR-2 直接做 PR-4，最后会发现 `Phase3Products` 改字段时所有 caller 都要回头改
- ❌ 跳过 PR-5 golden fixture，宣称「smoke 测试通过就行」——下游 Phase 4 接 Phase 3 输出时会暴雷
- ❌ 复制 C 模型的「假装实现」做法——不写 `anyhow::bail!` 标记 stub

**可以做**：
- ✅ PR-1 和 PR-2 顺序可换（互不依赖）
- ✅ PR-5 的 4 个 parity 测试可拆 4 个 sub-PR（如果想做更细粒度审查）
- ✅ 跑通 PR-3 smoke 后立刻把 `spec_biopolitics_contract_v2_def_anchor_mismatch` 去 `#[ignore]`——能尽早暴露问题

---

**联系负责人**：任何阶段卡住 4 小时以上，找项目负责人对齐方案；不要硬扛。
