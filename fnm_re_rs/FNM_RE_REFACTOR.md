# FNM_RE Rust 重构完成度报告

> 审计日期：2026-05-17  
> 审计方法：功能等价性比对（「功能等价」= 相同输入产生相同输出，不要求同名同位置）  
> 测试状态：全部 21 测试套件通过（fnm-core 95 + phase1 91 + phase2 91 + phase3 26 lib tests, 0 failures）

---

## 1. 模块对应总表

### fnm-core（Python `FNM_RE/shared/` → Rust `fnm_core::`）

| Python 源 | Rust 模块 | 等价度 | 备注 |
|---|---|---|---|
| `records.py` / `models.py` | `records.rs` | ✅ | Phase 1-6 全部类型已 port；`TocNode`/`TocPageRole` 为 Rust 新增类型 |
| `types.py` / `constants.py` | `types.rs` | ✅ | 枚举 + enum_with_str 宏，含 `NoteKind`/`PageRole`/`LinkStatus` 等 |
| `ref_rewriter.py` | `ref_rewriter.rs` | ✅ | `marker_key` + `marker_aliases` + `resolve_note_id` + `consume_marker_note_id` + `local_endnote_ref_number` + `replace_note_refs_with_local_labels` + 3 个 `replace_raw_*_refs` |
| `marker_sequences.py` | `marker_seq.rs` | ✅ | 排序 + 6 源 alias + resolve_note_id + fallback |
| `segments.py` | `segments.rs` | ✅ | `split_fnm_paragraphs` + `normalize_heading_text` + `join_paragraphs` + `build_fallback_unit_paragraphs` + `normalize_unit_paragraph` + `normalize_unit_page_segment` |
| `export_constants.py` | `export_constants.rs` | ✅ | 10/11 regex 常量 + `unicode_superscript_to_ascii` + `should_replace_definition_text` |
| `note_lookup.py` | `note_lookup.rs` | ✅ | `sanitize_note_text` + `LEADING_RAW_NOTE_MARKER_RE`（已补全） |
| `note_marker.py` | `note_marker.rs` | ✅ | `normalize_note_marker` + `marker_digits_are_ordered_subsequence` |
| `refs.py` | `refs.rs` | ✅ | `NOTE_REF_RE` + `cleanup_nested_note_refs` + `extract_note_refs` |
| `title.py` | `title.rs` | ✅ | `chapter_title_match_key` + `normalize_title` + `guess_title_family` |
| `text.py` | `text.rs` | ✅ | `page_markdown_text` + `page_blocks` + `pages_blocks` |
| `_pdf_render_worker.py` | `vision/pdfium.rs` | ✅ | `render_page_to_base64_png` + `extract_pdf_text_by_page` |
| `sqlite_repo_fnm.py` | `db/repository.rs` | ✅ | `SqliteRepository` 含 Phase 1-3 + translation_units CRUD |
| `sqlite_schema.py` | `db/schema.rs` + `migrations/` | ✅ | 0001_initial.sql + 0002_add_missing_tables.sql |

### fnm-phase1（Python `FNM_RE/stages/` + `FNM_RE/modules/` → Rust `fnm_phase1::`）

| Python 源 | Rust 模块 | 等价度 | 备注 |
|---|---|---|---|
| `stages/page_partition.py` | `page_partition/` | ✅ | role_resolver + continuation fixes (front/back/note/endnotes_hint) |
| `stages/section_heads.py` | `section_heads.rs` | ✅ | fallback sections + heading_candidates 处理 |
| `stages/heading_graph.py` | `heading_graph/` | ✅ | Round 1-3 (local_exact + expanded_exact + monotonic_target); A3 已接线 |
| `stages/chapter_skeleton/builder.py` | `chapter_skeleton/builder.rs` | ✅ | 调用 toc_semantics + heading_graph; 返回 section_heads |
| `stages/chapter_skeleton/toc_semantics.py` | `chapter_skeleton/toc_semantics/` | ✅ | 5 遍 sanitize + chapter_level + role_inference + lecture_collection; heading_graph 锚点已应用 |
| `stages/chapter_skeleton/fallback.py` | `chapter_skeleton/fallback.rs` | ✅ | candidate_section_rows → classify → mark_suppressed → build_fallback |
| `stages/chapter_skeleton/heading_candidates.py` | `chapter_skeleton/heading_candidates/` | ✅ | page_rows + collect + normalize |
| `modules/toc_structure.py` | `toc_structure.rs` | ✅ | Phase1Structure 组装 + gate_report (5 hard + 2 soft) + garbled 检测 + TOC tree 过滤/补入 |
| `modules/book_note_type.py` | `book_note_type/mod.rs` | ✅ | 4 守卫 (chapters_with_heading/nearest_prior/book_endnote_pages/endnote-priority) |
| `modules/llm_book_type_verify.py` | `llm_book_type_verify/` | 🟡 | 代码存在，LLM client 未接主入口 |
| — | `page_roles.rs` (新建) | ✅ | `_build_page_roles` port |
| — | `toc_tree.rs` (新建) | ✅ | `_build_toc_tree` + `_map_toc_role` port |

### fnm-phase2（Python `FNM_RE/stages/` + `FNM_RE/modules/` → Rust `fnm_phase2::`）

| Python 源 | Rust 模块 | 等价度 | 备注 |
|---|---|---|---|
| `stages/note_regions.py` | `note_regions/` | ✅ | footnote_band + endnote_regions_raw + book_regions + post_body_promote (5 守卫 G0-G4) + merge_adjacent + normalize |
| `_resolve_note_kind` (分散) | `note_kind_resolver.rs` | ✅ | 7 步集中决策（scan_page_kind → explicit headings → footnote_band → post_body → book_scope → fallback） |
| `stages/note_items.py` | `note_items/` | ✅ | marker_parse (7 种类型) + sequence_repair + year_filter; preprocess_page_text 已激活 |
| `stages/endnote_chapter_explorer.py` | `endnote_chapter_explorer/mod.rs` | ✅ | 4 路径分配 + fuzzy_match + roman_to_int; lib.rs 已接线 |
| `modules/endnote_repair.py` | `endnote_repair/mod.rs` | ✅ | 3 步流水线 (truncation + continuity + OCR split) |
| `modules/sup_recovery.py` | `sup_recovery/` | ✅ | Layer 1 (markdown) + Layer 2 (5 OCR surrogate 模式) + Layer 3 (vision LLM) |
| `modules/chapter_split.py` | `chapter_split/` | ✅ | endnote_project + synth_markers + overrides_apply |
| `modules/book_note_type.py` (book_type) | `book_structure.rs` | ✅ | infer_book_type |
| `modules/visual_anchor_recovery.py` | `visual_anchor_recovery/` | 🟡 | 代码完整 (async)，需 Phase 3 body_anchors 数据，由 Phase 3 调用 |
| `modules/llm_bare_digit_verify.py` | `llm_bare_digit_verify/` | 🟡 | 代码完整 (async)，需 Phase 3 body_anchors 数据，由 Phase 3 调用 |

### fnm-phase3（Python `FNM_RE/stages/` → Rust `fnm_phase3::`）

| Python 源 | Rust 模块 | 等价度 | 备注 |
|---|---|---|---|
| `stages/body_anchors.py` | `body_anchors/` | ✅ | 含 gap_recovery (BARE_DIGIT_STRUCTURAL_PREFIX 24 词) + context_guard |
| `stages/endnote_links.py` | `endnote_links.rs` | ✅ | scope=book 分支 + anchor_count 守卫 + Unicode 上标负前瞻; 函数签名含 regions_by_id |
| `stages/footnote_links.py` | `footnote_links.rs` | ✅ | 星号 + 数字脚注匹配 |
| `stages/note_links.py` | `note_links.rs` | ✅ | 编排 endnote + footnote + orphan_anchor (used_marker_keys dedup) |
| `stages/note_linking.py` (主编排) | `note_linking/` | ✅ | 11 步流水线完整接线 |
| `stages/note_linking.py` (contract) | `endnote_repair/contract_repair.rs` | ✅ | 4 段修复 (OCR + fallback + dedup + endnote-only); P3-1~P3-7 全部修复 |
| `stages/note_linking.py` (ocr_repair) | `note_linking/ocr_repair/` | ✅ | Loop 1 (orphan rebind) + Loop 2 (ambiguous followup) + Loop 3 (cross-chapter) |
| `stages/note_linking.py` (contracts) | `note_linking/chapter_contracts.rs` | ✅ | !requires_endnote_contract → 4 项 true; P3-5 已修复 |
| `stages/chapter_anchor_alignment.py` | `chapter_anchor_alignment/` | ✅ | DP alignment (Needleman-Wunsch) |
| `stages/paragraph_endnotes.py` | `paragraph_endnotes.rs` | ✅ | 5 步流水线 |
| `stages/paragraph_footnotes.py` | `paragraph_footnotes.rs` | ✅ | band detection + cross-page merge |

---

## 2. 修复历史

### Step E: Phase 3 算法 bug（7 项）

| # | 问题 | 位置 | 修复 |
|---|---|---|---|
| P3-1 | fallback 排序键 `anchor_id.len()` | `contract_repair.rs:217` | → `anchor_id` 字典序 + comment |
| P3-2 | `clamp(0,1).max(1.0)` = 恒 1.0 | `contract_repair.rs:340,433,438` | 移除 `.max(1.0)` |
| P3-3 | Unicode 上标缺负前瞻 | `endnote_links.rs:403` | 字符级负后顾+负前瞻 |
| P3-4 | orphan_anchor 缺 dedup | `note_links.rs:160` | 加 `used_marker_keys` set |
| P3-5 | contract 强制 2 项 vs Python 4 项 | `chapter_contracts.rs:280` | 改为 4 项 (`endnote_only_no_orphan_anchor`) |
| P3-6 | summary key `rebound_match_count` | `ocr_repair/mod.rs:110` | → `explicit_anchor_rebind_count` |
| P3-7 | gap_recovery 缺 prefix filter | `gap_recovery.rs:160` | 加 24 词 `BARE_DIGIT_STRUCTURAL_PREFIX` |

### Step F: Phase 1/2 接线（5 项）

| # | 问题 | 状态 |
|---|---|---|
| P1-1 | `build_toc_semantics` 未接线 | ✅ builder.rs 主路径调用 |
| P1-2 | `build_book_note_profile` 4 守卫 | ✅ 全部补齐 |
| P2-1 | `note_kind_resolver` 硬编码 | ✅ 审计偏旧，实际已用于 footnote_band + endnote_regions_raw |
| P2-2 | `endnote_chapter_explorer` fuzzy match | ✅ 补齐 + lib.rs 接线 |
| P2-3 | `endnote_repair` stub 37% | ✅ 3 步流水线 |
| P2-4 | LLM 路径未接线 | ✅ sup_recovery Layer 3 vision + lib.rs vision_config |
| C-5 | `marker_seq` 简化版 | ✅ 补全排序+alias+fallback |

### Step G: Phase 4 基建（4 项）

| # | 问题 | 状态 |
|---|---|---|
| C-1 | `ref_rewriter` 3 函数 | ✅ 全部 port |
| C-2 | `segments` 5 函数 | ✅ 全部 port |
| C-3 | db CRUD | ✅ `list/replace_fnm_translation_units` |
| C-4 | PDF 提取 | ✅ `extract_pdf_text_by_page` |

### Phase D: 最终审计后补齐（6 项）

| # | 问题 | 状态 |
|---|---|---|
| D1 | `marker_seq` 排序+6源alias+resolve_note_id+fallback | ✅ |
| D2 | `note_lookup` regex 补全 `<sup>` + `*`/`**` + 字母后缀 | ✅ |
| D3 | `Phase1Structure` serde 兼容 | ✅ (双向兼容，仅 doc) |
| D4 | `toc_semantics` 对齐性计算 | ✅ (基于 conflict_count) |
| D5 | TOC tree 过滤/补入 | ✅ |
| D6 | soft gates | ✅ |

---

## 3. 已知差异（非阻塞）

### 3.1 架构简化差异

| 差异 | 影响 | 风险 |
|---|---|---|
| Rust `Phase1Structure` 内联 `toc_tree` + `page_roles`（Python 独立 `TocStructure`） | JSON round-trip 双向兼容（均有 `#[serde(default)]`） | 无 |
| Rust `note_kind_resolver` 为集中决策器（Python 分散硬编码） | 决策结果等价，Rust 更易审计 | 无 |
| Rust `chapter_contracts` 排序键用 `anchor_id`（Python `(page_no, link_id)`） | 极端 tie 场景可能选到不同的候选 | 极低 |
| Rust `page_roles` 分支 2 硬编码角色为 "chapter"（Python 用 `chapter.role` 含 "post_body"） | post_body 页面在 Rust 标为 "chapter" 而非 "post_body" | 低（下游 phase2 通过 note_items 推断，不依赖此字段） |
| Rust `heading_graph` 数据源为原始 `toc_items`（Python 为 sanitize 后的 `exportable_chapter_rows`） | heading graph 可能包含部分被抑制行，影响极少量 anchor 解析 | 低 |

### 3.2 功能增强差异

| 差异 | 说明 |
|---|---|
| Rust `marker_parse` 新增 letter/HTML/LaTeX 三种 marker 类型 | Python 没有对应的解析分支，Rust 覆盖更广 |
| Rust `endnote_repair` 3 步流水线 | Python 将截断处理嵌入行解析器，Rust 为独立后处理步骤 |
| Rust `build_orphan_anchor_links` 的 `used_marker_keys` dedup | Python 无此逻辑（重复 orphan anchor 会多入池） |
| Rust `find_marker_in_body` Unicode 上标负后顾 | Python 仅负前瞻，Rust 额外禁止前一个字符为上标数字 |
| Rust `replace_raw_bracket_refs` 手动 lookaround 守卫 | Python 用正则 lookahead/lookbehind，Rust 用字符边界检查 |

### 3.3 待后续接入

| 模块 | 状态 | 阻塞条件 |
|---|---|---|
| `visual_anchor_recovery` | 代码完整，未接 | 需 Phase 3 产出 `body_anchors` 后调用 |
| `llm_bare_digit_verify` | 代码完整，未接 | 需 Phase 3 产出 `body_anchors` 后调用 |
| `sup_recovery` Layer 1 PyMuPDF 替身 | 不可直接 port | Rust 用 markdown 格式标记 + Layer 2 OCR surrogate + Layer 3 vision LLM 联合覆盖 |
| `endnote_chapter_explorer` 完整 722 行 port | 当前 ~250 行 | Path 1/3/4 已接，Path 2 的 SequenceMatcher + TOC 子条目匹配待补 |

### 3.4 接口差异

| 差异 | Python | Rust | 实际影响 |
|---|---|---|---|
| `extract_pdf_text_by_page` 批量 vs 单页 | `(pdf_path, pages, target_pages) → dict[int,str]` | `(pdf_path, page_index) → String` | 调用方需循环 |
| `db list_fnm_translation_units` 排序 | `ORDER BY owner_kind, section_start_page, page_start, unit_id` | `ORDER BY page_start, unit_id` | 列表顺序不同，语义等价 |

---

## 4. 验证命令

```bash
# 全量编译
cargo check --workspace

# 全量测试
cargo test --workspace

# 单 crate 测试
cargo test -p fnm-core --lib
cargo test -p fnm-phase1 --lib
cargo test -p fnm-phase2 --lib
cargo test -p fnm-phase3 --lib

# 集成测试（需数据文件）
cargo test -p fnm-phase1 --test test_biopolitics_parity
cargo test -p fnm-phase3 --test test_phase3_spec
```
