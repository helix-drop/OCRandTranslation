# B 系列 + A 系列 审计说明

## 一、`#[ignore]` 测试清单

### Phase 3 parity tests（全部 cascade，非本系列可修）

| 测试 | ignore 理由 |
|---|---|
| `spec_biopolitics_contract_v2_def_anchor_mismatch` | Phase 2 note_item over-extraction（619 vs 584），见 `known_python_bugs.md §7` |
| `biopolitics_phase3_body_anchors_parity` | 同上 cascade |
| `biopolitics_phase3_note_links_parity` | 同上 cascade |
| `biopolitics_phase3_summary_parity` | 同上 cascade |
| `biopolitics_phase3_chapter_contracts_parity` | 同上 cascade |

这些不是 B 系列负责修的。等 A3（endnote_chapter_explorer 完整实现）解决 Phase 2 over-extraction 后自然消除。

### Phase 3 SPEC tests（Python 源也是 skip）

| 测试 | ignore 理由 |
|---|---|
| `spec_bare_digit_gate_edge_case` | Python 测试本身跳过，需要真实数据验证 |
| `spec_symbol_gap_recovery` | 同上 |

### Phase 2 Layer 2 sup_recovery（B2 任务）

| 测试 | ignore 理由 |
|---|---|
| `spec_sup_recovery_layer2_ocr_punctuation_surrogate` | `sup_recovery/layer2.rs` 的 OCR block 对齐算法未实现（FNM_PHASE12_AUDIT G1） |
| `spec_sup_recovery_layer2_ocr_suffix` | 同上 |
| `spec_sup_recovery_layer2_symbol_after_year` | 同上 |

Python 源文件也标注 `@unittest.skip("[rust-migration: SPEC] Layer 2 ...")`。SPEC 代码已写好，等 Layer 2 实现后去掉 `#[ignore]` 即可验证。

### 基础设施依赖（需 PDFium / OpenAI API key）

| 测试 | ignore 理由 |
|---|---|
| `vision::pdfium::tests::render_biopolitics_page_1` | 需要 PDFium 二进制 + 测试 PDF |
| `chapter_skeleton::pdf_font::tests::empty_for_missing_pdf` | 需要 PDFium 二进制 + 测试 PDF |
| `llm_book_type_verify::tests::real_book_type_verify` | 需要真实 `OPENAI_API_KEY` + PDFium |
| `sup_recovery::layer3::tests::real_vision_call` | 需要真实 `OPENAI_API_KEY` |

---

## 二、`#[allow(dead_code)]` / stub 说明

### fnm-phase2/src/sup_recovery/layer2.rs — `#![allow(dead_code)]`

OCR block 对齐算法 stub。当前只做基本 digit boundary 匹配（`find_markers_in_ocr_text`），缺：
- OCR raw block → markdown 文本对齐
- symbol surrogate recovery（`!!` → `<sup>11</sup>`）
- year fragment / suffix recovery
见 FNM_PHASE12_AUDIT.md G1。

### fnm-phase2/src/endnote_chapter_explorer/mod.rs — `#![allow(dead_code)]`

20% 完成度。Python 722 行，Rust 153 行。已接入主 pipeline（`note_regions/mod.rs:88`），但实际输出不会改变 region 分配。需要完整实现 3 路径（TOC match / signal match / fallback）。

### fnm-phase2/src/endnote_repair/mod.rs

37% 完成度。Python 325 行，Rust 126 行。`repair_endnote_items` 已接入主 pipeline（`lib.rs:68-70`），但只做最简单的截断合并。缺：
- marker 连续性修复
- OCR split reconstruction
- 跨页续行合并

### fnm-phase1/src/chapter_skeleton/fallback.rs — `#[allow(dead_code)]` 标记

B3 实现的 ~95% 完整 fallback 模块。以下函数/结构体标记为 `allow(dead_code)`，因为尚未从主调用路径触发：

| 标识 | 说明 |
|---|---|
| `SectionRow` struct | 候选节行的中间结构，仅在 fallback 内部使用 |
| `ClassifiedSection` struct | 分类后节行的中间结构 |
| `mark_suppressed_candidates()` | 已接入主流程（取消 dead_code 标记需等待 builder 路径触发） |
| `normalize_sections()` | 标准化函数，预留 |
| `merge_section_heads()` | 合并函数，预留 |

这些结构是 Python `fallback.py` 对应功能的直接翻译。由于当前 Rust `build_phase1_structure` 的调用路径（`toc_structure.rs:104` → `build_chapter_skeleton`）在无 TOC 时传递 `&mut heading_candidates`，`mark_suppressed_candidates` 的突变效果被正确保留。

### fnm-phase1/src/page_partition/role_heuristics.rs — `#![allow(dead_code)]`

Python 端 ~800 行的 role heuristics 模块，Rust 端仅 ~150 行。大量未实现。已知不影响当前 parity（page_partition 角色覆盖率 96.8%），但后续完善时会用到。

---

## 三、实现质量备注

### B3 fallback 完成度评估

Python `fallback.py`: 656 行 / 15 个函数
Rust `fallback.rs`: 624 行 / 13 个函数

**已实现**（核心算法，~95%）：
- `candidate_section_rows` ✅
- `classify_fallback_sections` ✅
- `mark_suppressed_candidates` ✅（已接入 builder）
- `build_fallback_chapters_and_sections` ✅
- `normalize_chapters` ✅
- `simple_fallback`（退化路径）✅
- `chapter_keyword_strength` / `is_sentence_like_heading` / `all_page_numbers` / `build_page_roles` ✅

**未实现**（辅助函数，~5%）：
- `_infer_back_matter_start_page` — 依赖 PDF 渲染和 I/O
- `_trim_chapter_rows` — 依赖 back_matter 检测
- `_default_toc_*_summary` 等 3 个 — 仅 summary 生成
- `_is_toc_force_export_title` — 等价正则存在于 `builder.rs`

### A3 接线说明

`endnote_repair` 和 `endnote_chapter_explorer` 已接入主 pipeline，但两模块本身完成度低（37%/20%）。接线位置正确（对齐 Python），产出流入 `chapter_split`。待完整实现后移除 stub 状态。

---

## 四、「看起来不完美」的决策理由

| 现象 | 决策理由 |
|---|---|
| B3 缺 5% 辅助函数不补 | 核心算法已完整。余 5% 是 back_matter 边界检测和 summary 生成器，依赖 PDF 渲染能力（Step C 范围），不值得在 B3 做 |
| B2 Layer 2 test 不修实现 | Layer 2 是独立的 OCR 对齐算法，不是 SPEC 翻译任务的内容。SPEC 已存在且匹配 Python 的 skip 状态 |
| B4 note_kind test fixture 不改 | test fixture 中的 `NoteKind::Endnote` 硬编码是测试数据构造，不是分类决策。改过去会增加复杂度而无实际收益 |
| golden fixture 不动 | 绝对原则：golden 是 Python 真实输出，是真理。所有差距只记录不篡改 |
