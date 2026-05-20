# `fnm-phase5` + `fnm-phase6` 实施计划（方案 B 合并 port）

本文档是自包含的——新 session 接手者读完本文件 + AGENTS.md Rust 规范 +
fnm-phase4 完成情况，即可开工 M0。

---

## 0. 项目背景（30 秒）

正在做 Python `FNM_RE/` 到 Rust `fnm_re_rs/` 的全量重写。

| Phase | crate | 状态 | 测试 |
|---|---|---|---|---|
| 0 基础设施 | `fnm-core` | ✅ **100% 完成** | 110 lib + 9 集成 |
| 1 章节骨架 | `fnm-phase1` | ✅ **100% 完成** | 106 lib + 15 集成（1 chapter_boundary parity 待精调）|
| 2 注释结构 + note_kind | `fnm-phase2` | ✅ **100% 完成** | 140 lib + 18 集成 + biopolitics 6/6 |
| 3 body anchor + link 匹配 | `fnm-phase3` | ✅ **100% 完成** | 26 lib + 27 集成（5 ignored cascade）|
| 4 引用注入 + 翻译单元 | `fnm-phase4` | ✅ **100% 完成** | 106 lib + 6 parity + 8 spec |
| LLM repair (3.5) | `fnm-llm-repair` | ✅ **100% 完成 + 二次审计通过** | 121 lib + 4 integration + 39 spec |
| **5 章 markdown 合并** | **`fnm-phase5`** | **✅ 100% 完成** | **44 lib** |
| **6 导出 + 审计 + 组装** | **`fnm-phase6`** | **✅ 100% 完成** | **148 lib** |

**workspace 测试**：~801 lib tests · 1 known parity fail（phase1 chapter_boundary）· clippy 0 warning。

## 0a. 为什么合并 port（方案 B 而非方案 A）

Python 端 phase5 通过 `chapter_merge.py` 调用 `stages/export_contract.py`（**phase6 stage**），
而后者又依赖 `stages/export.py` 的 8 个私有 helper。phase5 在 Python 里**倒挂依赖** phase6。

**方案 A 单做 phase5**：把 export 子集临时放进 fnm-phase5 子模块，phase6 启动时**必须迁移**
→ 双倍 refactor + 接口已被使用的迁移风险。

**方案 B 合并 port**：M0-M5 按 DAG 拓扑序逐个完成，每个 milestone 独立可测。export helpers
**一开始就放 fnm-phase6 最终位置**，phase5 通过 `use fnm_phase6::export::*` 直接消费。

每个 milestone：500-1700 LOC / 1 PR / 1 session，独立验收。

## 0b. M0-M5 启动就绪清单

| 依赖项 | 状态 | 备注 |
|---|---|---|
| **fnm-core** | ✅ 100% | 含 `Phase5Structure` / `Phase5Summary` / `DiagnosticPageRecord` / `Phase6Structure` / `ExportChapterRecord` |
| **fnm-phase1** | ✅ 100% | |
| **fnm-phase2** | ✅ 100% | ChapterLayers / ChapterNoteModeRecord |
| **fnm-phase3** | ✅ 100% | NoteLinkTable |
| **fnm-phase4** | ✅ 100% | FrozenUnits / TranslationUnitRecord / FrozenRefEntry |
| **fnm-llm-repair** | ✅ 100% | 审计通过，不阻塞 |
| **缺：fnm-core ChapterMarkdownRecord** | ❌ | M0 任务 |
| **缺：Repository.list/replace_fnm_chapter_markdowns** | ❌ | M0 任务 |
| **缺：fnm-core ExportBundleRecord / ExportAuditReport** | ❌ | M0 任务（部分类型已在 records.rs 占位）|

---

## 1. 必读前置（按顺序）

| # | 路径 | 重点章节 |
|--:|---|---|
| 1 | `/Users/hao/OCRandTranslation/AGENTS.md` | 行 281-540 "Rust 重构代码规范" 12 条铁律 |
| 2 | `/Users/hao/OCRandTranslation/CLAUDE.md` | 第 8/12 条 Phase 边界 + 树枝状条件 |
| 3 | `/Users/hao/OCRandTranslation/FNM_RE/RUST_MIGRATION_PLAN.md` | "Step 5/6" 段 |
| 4 | `/Users/hao/OCRandTranslation/FNM_RE/FNM_PHASE4_PLAN.md` | 参考 phase4 M1-M5 任务粒度与 PR 流程 |
| 5 | `fnm_re_rs/fnm-llm-repair/src/` | 参考审计后的工程规范（lib.rs <400 / ProviderError 风格 / clone 注释）|

**特别看 AGENTS.md 的 12 条铁律**——任何违反都会被审计拒绝。简版：
1. 翻译保真度禁简化（Rust ~ Python 80-120% 行数，可因 struct/类型膨胀到 200%）
2. Regex 必须 `Lazy<Regex>` 静态
3. 复用 fnm-core 基础设施
4. mod.rs / lib.rs < 400 行
5. 每个 pub fn 标 `←→ Python xxx()` doc comment
6. 测试用真实 fixture
7. Parity byte-equal Python（对 export 输出 markdown 严格要求）
8. 不允许 `let _ = ...` 忽略关键参数
9. Stub 用 `anyhow::bail!`，不静默返空
10. 0 `Rc<RefCell>` / 0 滥用 `Arc<Mutex>`
11. `.clone()` 节制
12. PR 验收 checklist 12 项

---

## 2. phase5 + phase6 目标与职责

### 输入

通过 DB / 直接消费 phase1-4 输出：

| 来源 | 内容 |
|---|---|
| Phase 1 (`fnm_chapters` / `fnm_section_heads` / `fnm_pages`) | 章节骨架 + page_role |
| Phase 2 (`fnm_note_items` / `fnm_note_regions` / `fnm_chapter_note_modes`) | note 定义 + 区域 + chapter mode |
| Phase 3 (`fnm_body_anchors` / `fnm_note_links`) | body anchors + effective links |
| Phase 4 (`fnm_translation_units` / `fnm_structure_reviews` / `frozen_units`) | 翻译单元 + 结构复核 + 冻结引用 |
| `phase2::ChapterLayers` / `phase3::NoteLinkTable` / `phase4::FrozenUnits` | 内存中间产物 |

### 输出

| 表 / 字段 | 内容 | Crate |
|---|---|---|
| `fnm_chapter_markdowns` | 章级 markdown（含 ref 重写、本地脚注、TOC）| fnm-phase5 |
| `fnm_diagnostic_pages` / `fnm_diagnostic_notes` | 诊断投影 | fnm-phase5（phase5_shadow 内嵌）|
| `fnm_export_chapters` | 章级导出 markdown（清洗 + 语义合同）| fnm-phase6 |
| `fnm_export_audit` | 导出审计（重复 / 缺失 / 标记泄漏）| fnm-phase6 |
| `ExportBundleRecord` | 全书导出 bundle（ZIP 元数据）| fnm-phase6 |

### Phase 边界纪律（CLAUDE.md §12）

**phase5 仅做**：
- ✅ 章 body markdown 重写（替换 frozen NOTE_REF token 为本地 `[^N]` / `<sup>N</sup>` 标记）
- ✅ 本章脚注块格式化（`## Notes` heading + footnote definitions）
- ✅ 章级 issue diagnostics（残留 raw marker / 重复 heading）
- ✅ 调 `build_export_chapters`（M2 提供）封装为 `ChapterMarkdownSet`

**phase6 仅做**：
- ✅ TOC 整理 + 章节重排
- ✅ Markdown 清洗（adjacent duplicate / garbled blocks / semantic canonicalization）
- ✅ ZIP 打包
- ✅ 全书级审计（raw marker leak / mid-sentence opening / 重复检测）

**phase5/6 都不做**：
- ❌ 重新检测 anchor / link / note_kind / chapter boundary
- ❌ 修改 phase1-4 表

---

## 3. 数据流图 + 依赖 DAG

### Python 内部依赖（Python `import` 关系）

```
                    ┌─ stages/export.py (751)
                    │   ├─ 8 私有 helper（M1 提取）
                    │   ├─ build_export_bundle (666)
                    │   ├─ build_export_zip (723)
                    │   ▲      ▲
        共享 helpers│      │（forward import 循环依赖技巧）
                    │      │
                    │   ┌──┴── stages/export_contract.py (224)
                    │   │      └─ build_export_chapters (116)
                    │   │
                    │   └──── stages/export_footnote.py (407)
                    │
                    ├─ stages/export_audit.py (688) 独立
                    │   ├─ audit_markdown_file (349)
                    │   └─ audit_phase6_export (510)
                    │
                    └─ stages/diagnostics.py (336) 独立
                        └─ build_diagnostic_projection (197)

顶层：
  modules/chapter_merge.py (827) → export / export_audit / export_contract
  modules/book_assemble.py (543) → export / export_audit / audit_phase6_export
```

### M0-M5 拓扑序

```
M0 (fnm-core 类型 + crate 骨架)
    ├─ ChapterMarkdownRecord / ExportChapterRecord / ExportBundleRecord
    ├─ ExportAuditReport / DiagnosticPageRecord（已有部分）
    └─ Repository CRUD 方法
        ↓
M1 (fnm-phase6/src/export/ helpers)
    ├─ build_chapter_filename / build_section_markdown
    ├─ chapter_page_numbers / diagnostic_machine_text_by_page
    ├─ infer_book_note_type_from_modes / normalized_paragraph_key
    ├─ sanitize_obsidian_chapter_title / strip_trailing_image_only_block
    └─ build_section_heads_by_page / ...（共 ~19 helpers）
        ↓
   ┌────┴──────────────┬──────────────────┐
   ↓                    ↓                  ↓
M2a (export_contract)  M2b (export_footnote)  M3 (export_audit + diagnostics)
   ├─ build_export_       ├─ build_inline_      ├─ audit_markdown_file
   │   chapters            │   footnote_section_  ├─ audit_phase6_export
   ├─ compute_export_      │   markdown          └─ build_diagnostic_
   │   semantic_contract   ├─ emit_local_note_       projection
   └─ is_semantic_         │   definitions
      duplicate_candidate  └─ emit_symbol_footnotes
        ↓                    ↓                  ↓
        └────────┬───────────┴──────────────────┘
                 ↓
        M4 (fnm-phase5 顶层)
            ├─ chapter_merge.py 24 函数
            └─ build_chapter_markdown_set
                 ↓
        M5 (fnm-phase6 顶层)
            ├─ book_assemble.py 12 函数
            └─ build_export_bundle (顶层)
```

每个 milestone 完成后跑 `cargo test -p fnm-phaseN` + `cargo clippy --no-deps`，
独立 PR，独立可验证。

---

## 4. M0-M5 详细任务清单

### M0：fnm-core 类型扩展 + 两个 crate 骨架

**Size**：S（~300 LOC）· 1 session

**任务**：
1. **fnm-core/src/records.rs 扩展**：
   - 添加 `ChapterMarkdownRecord` / `ChapterMarkdownEntry` / `ChapterMarkdownSet`（参考 Python `FNM_RE/modules/types.py`）
   - 添加 `ExportChapterRecord` / `ExportBundleRecord` / `ExportAuditReport` 完整字段（Phase6Structure 已部分存在）
   - 添加 `DiagnosticNoteRecord`（Phase5Structure 已引用）
2. **fnm-core/src/db/repository.rs 扩展**：
   - `fn list_fnm_chapter_markdowns(&self, doc_id: &str) -> Result<Vec<ChapterMarkdownRecord>>`
   - `fn replace_fnm_chapter_markdowns(&self, doc_id, payload: &Phase5Products) -> Result<()>`
   - `fn list_fnm_export_chapters(&self, doc_id: &str) -> Result<Vec<ExportChapterRecord>>`
   - `fn replace_fnm_phase6_products(&self, doc_id, payload: &Phase6Products) -> Result<()>`
3. **fnm-phase5 / fnm-phase6 crate 骨架**：
   - `Cargo.toml`（依赖 fnm-core + fnm-phase1/2/3/4，phase6 依赖 phase5）
   - `src/lib.rs` 仅模块声明
   - 加入 workspace member
4. **fnm-phase6/src/export/ 子模块占位**：
   - `mod.rs` 仅 `pub mod *`

**验收**：`cargo build --workspace` 通过 + `cargo clippy --workspace --no-deps` 0 warning。

### M1：fnm-phase6 export helpers（最大头 leaf）

**Size**：L（~1500 LOC）· 2 session

**Python 源**：`stages/export.py` 行 68-665（不含 build_export_bundle 主体）

**Rust 目标**：`fnm-phase6/src/export/` 19 个 helpers，按职责拆分子模块：

| Python 函数 | Rust 模块 | 说明 |
|---|---|---|
| `_sanitize_obsidian_chapter_title` (68) | `export/filename.rs` | Obsidian 文件名清洗 |
| `_build_chapter_filename` (75) | `export/filename.rs` | 章节文件名 |
| `_escape_leading_asterisks` (91) | `export/markdown_clean.rs` | markdown 转义 |
| `_normalize_markdown_content` (98) | `export/markdown_clean.rs` | 内容规范化 |
| `_clean_export_html` (111) | `export/markdown_clean.rs` | HTML 清洗 |
| `_strip_trailing_image_only_block` (128) | `export/markdown_clean.rs` | 尾部图片块去除 |
| `_looks_like_sentence_section_heading` (139) | `export/section_head.rs` | 句式 heading 检测 |
| `_is_exportable_section_head` (153) | `export/section_head.rs` | 可导出 section 判定 |
| `_build_note_text_by_id_for_chapter` (176) | `export/note_lookup.rs` | note text 索引 |
| `_build_note_kind_by_id_for_chapter` (196) | `export/note_lookup.rs` | note kind 索引 |
| `_build_marker_by_note_id_for_chapter` (214) | `export/note_lookup.rs` | marker 索引 |
| `_diagnostic_machine_text_by_page` (233) | `export/diagnostic_text.rs` | 诊断文本索引 |
| `_resolve_body_unit_text` (252) | `export/body_render.rs` | body unit 文本解析 |
| `_rewrite_body_text_with_local_refs` (284) | `export/body_render.rs` | NOTE_REF → 本地标记 |
| `_chapter_page_numbers` (345) | `export/chapter_pages.rs` | 章页码收集 |
| `_build_section_heads_by_page` (356) | `export/section_head.rs` | section 按页索引 |
| `_infer_book_note_type_from_modes` (378) | `export/book_type.rs` | 全书 note type 推断 |
| `_format_chapter_title` (395) | `export/title.rs` | 章标题格式化 |
| `_build_section_markdown` (402-647) | `export/section_render.rs` | section markdown 渲染（**大函数 ~245 行**）|
| `_build_index_markdown` (648) | `export/index_render.rs` | 索引 markdown |
| `_normalized_paragraph_key` (659) | `export/paragraph_key.rs` | 段落去重 key |

**注意**：`_build_section_markdown` 是这层最大函数（~245 行），可能需要再拆 5 个子函数。

**验收**：`cargo test -p fnm-phase6 --lib export` 通过（每个 helper 至少 2 个 unit test）。

### M2：export_contract + export_footnote stages

**Size**：M（~1500 LOC）· 1-2 session

**M2a：`stages/export_contract.py`（224 行 / 3 函数）→ `fnm-phase6/src/export_contract.rs`**

| Python 函数 | Rust 函数 |
|---|---|
| `_is_semantic_duplicate_candidate` (39) | `is_semantic_duplicate_candidate` |
| `_compute_export_semantic_contract` (53) | `compute_export_semantic_contract` |
| `build_export_chapters` (116) | `build_export_chapters` |

依赖：M1 helpers。

**M2b：`stages/export_footnote.py`（407 行 / 11 函数）→ `fnm-phase6/src/export_footnote.rs`**

| Python 函数 | Rust 函数 |
|---|---|
| `_paragraph_attr` (38) | `paragraph_attr` |
| `_visible_segment_paragraphs` (44) | `visible_segment_paragraphs` |
| `_paragraph_render_text` (53) | `paragraph_render_text` |
| `_append_note_ids` (63) | `append_note_ids` |
| `_emit_local_note_definitions` (71) | `emit_local_note_definitions` |
| `_build_inline_footnote_targets` (107) | `build_inline_footnote_targets` |
| `_note_marker` (155) | `note_marker_text` |
| `_is_numeric_note` (160) | `is_numeric_note` |
| `_split_numeric_note_ids` (164) | `split_numeric_note_ids` |
| `_emit_symbol_footnotes` (179) | `emit_symbol_footnotes` |
| `_build_inline_footnote_section_markdown` (204) | `build_inline_footnote_section_markdown` |

依赖：M1 helpers。

**验收**：M2a + M2b 独立单测 + 用 phase4 fixture 跑 `build_export_chapters` 集成测试。

### M3：export_audit + diagnostics

**Size**：L（~1500 LOC）· 1-2 session

**M3a：`stages/export_audit.py`（688 行 / 25 函数）→ `fnm-phase6/src/export_audit.rs`**

23 个内部 helper（split / detect / look_like / iter / add_issue 等）+ 2 个顶层：
- `audit_markdown_file` (349) - 单文件审计
- `audit_phase6_export` (510) - 全书审计

**M3b：`stages/diagnostics.py`（336 行 / 10 函数）→ `fnm-phase6/src/diagnostics.rs`**

注意：`diagnostics.py` 部分函数已在 phase3 port（`build_print_page_map` 等）。M3b 只 port phase5/6 部分：
- `build_diagnostic_projection` (197) - 主入口
- 6 个 helper（_segment_from_any / _entry_status / _build_diagnostic_entry / _note_unit_by_note_id / _chapter_meta_by_id / _note_region_by_id）

**验收**：单测 + spec_tests（参考 Python `tests/unit/test_*export*.py`）。

### M4：fnm-phase5 顶层（chapter_merge.py）✅ 已完成

**Size**：L（~1080 LOC）· 完成

**Python 源**：`modules/chapter_merge.py`（827 行 / 24 函数）

**Rust 实现**：`fnm-phase5/src/` 4 子模块：

| 子模块 | 内容 | 测试 |
|---|---|---|
| `convert.rs` | 11 转换 helper（chapter_pages / to_chapter_records / to_note_item_records / to_body_anchor_records / to_note_link_records / to_translation_unit_records / phase5_book_type / to_diagnostic_pages 等）| 含在 lib tests |
| `phase5_shadow.rs` | `build_phase5_shadow` → Phase5Structure | 含在 lib tests |
| `marker_rewrite.rs` | has_raw_marker_in_body / rewrite_residual_raw_markers / apply_notes_block_format / rewrite_chapters_for_merge / chapter_contract_items / has_legacy_note_token | 含在 lib tests |
| `diagnostics.rs` | build_chapter_issue_diagnostics | 含在 lib tests |
| `lib.rs` | build_chapter_markdown_set 顶层 22 步编排 | 含在 lib tests |

**验收**：`cargo test -p fnm-phase5` 44 passed · 0 failed · 0 ignored。

### M5：fnm-phase6 顶层（book_assemble.py + export.py 剩余）✅ 已完成（含审计修复）

**Size**：L（~1300 LOC）· 完成（2026-05-19）

**Rust 实现**：`fnm-phase6/src/book_assemble/` 7 子模块：

| 子模块 | 对应 Python | 函数数 |
|---|---|---|
| `garbled_repair.rs` | `_split_markdown_prefix` / `_looks_like_garbled_export_block` / `_repair_garbled_markdown_blocks` | 3 |
| `canonicalize.rs` | `_is_adjacent_duplicate_candidate` / `_canonicalize_adjacent_duplicate_paragraphs` / `_apply_semantic_canonicalization` | 3 |
| `chapter_order.rs` | `_reorder_chapters` / `_to_export_chapter_records` | 2 |
| `toc_titles.rs` | `_toc_titles_and_summary` | 1 |
| `marker_leak.rs` | `_has_book_level_raw_marker_leak` + `has_leak_issues_in_report` | 2 |
| `audit_convert.rs` | `_to_export_audit_report` | 1 |
| `mod.rs` | `build_export_bundle` → `build_module_export_bundle` | 1 |

额外：`export/zip.rs`（`build_export_zip` ZIP 归档创建）。

**验收**：`cargo test -p fnm-phase6` 148 passed · 0 failed · 0 ignored。

**M5 审计修复**（2026-05-19）：见 `FNM_RE_REFACTOR.md` § M5 审计修复表 —— 5 项关键 bug 修复（LOCAL_DEF_RE `(?m)` / marker_leak 倒置行为 / gate 条件丢弃 / toc_titles role 过滤 / canonicalize 段落 regex）。

---

## 5. 各 milestone 验收 checklist

每个 milestone PR 合并前必须满足：

### 代码层（铁律 §1-12）
- [ ] `cargo build --release -p fnm-phaseN` 通过
- [ ] `cargo clippy -p fnm-phaseN --no-deps -- -D warnings` 通过（0 新增 allow）
- [ ] `cargo fmt --check` 通过
- [ ] `cargo test --all` 通过（保持现有测试 0 failed）
- [ ] 0 个 `let _ = ...` 忽略关键参数
- [ ] 0 个静默 stub（必须 `anyhow::bail!` 带消息）
- [ ] 0 个循环内 `Regex::new()`
- [ ] 0 `Rc<RefCell>` / 0 滥用 `Arc<Mutex>`（测试除外）
- [ ] mod.rs / lib.rs < 400 行

### 复用层
- [ ] PR 描述列出复用的 fnm-core / phase1-4 API
- [ ] 复用 `fnm_core::refs::cleanup_nested_note_refs` / `marker_seq` / `token_counter` / `notes` 等
- [ ] 不重新定义 fnm-core 已有的类型

### Phase 边界纪律
- [ ] phase5 / phase6 都不做 anchor / link / note_kind 重检测
- [ ] phase5 不做 chapter 重切分
- [ ] phase6 不修改 phase5 持久化的 chapter_markdown
- [ ] PR 描述声明边界纪律

### Parity
- [ ] 每个 pub fn 标 `←→ Python xxx() (file:line)` doc comment
- [ ] Biopolitics parity 测试通过 OR 在 `known_python_bugs.md` 记录根因
- [ ] SPEC 测试翻译并通过

---

## 6. SPEC 测试映射

按数据流位置：

| Milestone | 测试 | Python 源 |
|---|---|---|
| M2a | export_contract semantic contract | `tests/unit/test_export_*.py`（待勘查具体文件名）|
| M3a | export_audit raw marker leak | `tests/unit/test_export_audit*.py` |
| M3b | diagnostics projection | `tests/unit/test_diagnostics*.py` |
| M4 | chapter_merge byte-equal | `tests/unit/test_chapter_merge*.py` |
| M5 | book_assemble + ZIP | `test_run_post_translate_export_checks_preserves_existing_translations_when_rebuilding_snapshot` |

启动前用 `grep -rn "rust-migration: SPEC" tests/unit/ --include="*.py"` 锁定全部 SPEC 测试。

---

## 7. 已知风险与缓解

| 风险 | 缓解 |
|---|---|
| Python `stages/export.py` 行 743/749 forward import（循环依赖技巧）→ Rust 必须明确方向 | M1-M2 严格按 DAG 拓扑：M1 helpers → M2 stages，禁止 forward import |
| `_build_section_markdown` 单函数 245 行，复杂 | M1 内部再拆 5 子函数（按 markdown 块类型：title / body / footnote / image / index）|
| `audit_phase6_export` 涉及 ZIP 读取（`_read_zip_markdown_files`）| 复用 fnm-core 已有 zip 抽象 或 直接用 `zip` crate |
| `_apply_semantic_canonicalization` 用 `difflib.SequenceMatcher` | Rust 用 `rapidfuzz::distance::lcs_seq` 等价替代（同 fnm-llm-repair fuzzy 实现路径）|
| Biopolitics parity 跨 phase5+6 才能验证 | M4 完成 chapter_markdown parity；M5 完成 export bundle byte-equal parity |
| ZIP 输出二进制 parity 严格 | `zip-rs` 与 Python `zipfile` 默认压缩级别 / mtime 处理差异——必须在 M5 锁定 deterministic mtime + 压缩 level |

---

## 8. PR 流程

每个 M0-M5 一个独立 PR。PR title：

```
PHASE56-M{0,1,2a,2b,3a,3b,4,5}: <模块名> — <核心功能>（<行数>）
```

例：`PHASE56-M1: fnm-phase6/src/export/ — 19 helpers（~1500 LOC）`

每个 PR 合并前做代码审查（参考 fnm-llm-repair 二次审计模式：分功能完整性 / AGENTS.md / Rust 习惯 三路独立审计）。

---

## 9. 开工 checklist（M0 启动）

1. 读完 §1 必读前置（5 个文档）
2. `cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace`（确认基线 ~664 tests 全过 + 1 known failed）
3. 看 fnm-llm-repair 完成参考实现（lib.rs 36 行 + 二次审计修复模式）
4. M0 开始：扩展 fnm-core records + Repository + 建 fnm-phase5/6 骨架
5. 每个 milestone 一个 PR，标题严格按 §8 格式
6. 每完成 milestone 后通知用户做代码审查

---

## 10. 估算

| 阶段 | LOC | 状态 | 实际 |
|---|---|---|---|
| M0 fnm-core 扩展 + 骨架 | ~300 | ✅ 完成 | — |
| M1 export helpers | ~1500 | ✅ 完成 | 16 子模块 |
| M2a export_contract | ~600 | ✅ 完成 | contract.rs |
| M2b export_footnote | ~900 | ✅ 完成 | footnote.rs |
| M3a export_audit | ~1500 | ✅ 完成 | helpers + file_audit + mod |
| M3b diagnostics | ~400 | ✅ 完成 | diagnostics.rs |
| M4 chapter_merge | ~1080 | ✅ 完成 | 44 tests |
| M5 book_assemble + bundle + ZIP | ~1300 | ✅ 完成（含审计修复 5 bug）| 148 tests |
| **合计** | **~7,580 LOC** | **全完成** | **801 workspace tests**

---

## 11. 完成定义

phase5+6 完成 = 以下全部成立：

1. **✅ 7 个 milestone（M0-M5）全部实现**（M0 类型扩展 + M1 export helpers + M2a/b export_contract/footnote + M3a/b export_audit/diagnostics + M4 chapter_merge + M5 book_assemble）
2. **✅ `cargo test --workspace`** 801 lib tests passed · 0 failed（1 known phase1 parity）
3. **✅ `cargo clippy --workspace --no-deps`** 0 warning（除 phase1/2/4 预存项）
4. **⏳ Biopolitics fixture 端到端 parity** — 尚未运行（缺 test_example Biopolitics 章 markdown golden / ZIP 输出 golden）
5. **⏳ SPEC 测试翻译** — 尚未翻译 Python SPEC 测试到 Rust
6. **✅ AGENTS.md 12 条铁律合规** — 经 M5 审计修复后全部合规（0 `Rc<RefCell>`、0 循环内 Regex::new、0 静默 stub、全 pub fn ←→ Python 注释）

**剩余工作**：
- **fnm-orchestrator**（pyo3 入口 + pipeline 编排，尚未开始）
- **parity 测试**（Biopolitics 端到端 golden 比对）
- **SPEC 测试**（翻译 Python `test_export_*.py` / `test_chapter_merge*.py` 到 Rust）
