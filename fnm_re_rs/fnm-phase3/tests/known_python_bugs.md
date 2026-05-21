# Phase 3 Known Python Bugs / Diffs

本文档记录 Rust Phase 3 与 Python 的已知差异，以及当前 ignored 的 SPEC 测试根因。
按 AGENTS.md 铁律 §7「Parity 断言必须 byte-equal Python」——任何 ≠ Python 的输出都必须在本文档登记根因。

---

## §1 SPEC 2/3: bare_digit gate edge case

- **位置**：`tests/test_phase3_spec.rs` — `spec_expected_gap_recovery_keeps_weak_endnote_digits`、`spec_expected_gap_recovery_disambiguates_by_text`（`#[ignore]`）
- **状态**：Python 测试本身 `@unittest.skip("[rust-migration: SPEC] ...")`，Rust 端 behavior 与预期有 gap
- **根因**：`_is_bare_digit_false_positive_context` 对 "Migué 9" 类法语上下文判断可能过严
- **影响范围**：bare_digit 边界例，未触发 blocker
- **下一步**：用 Biopolitics 真实数据回归后决定是调 gate 还是调预期

---

## §2 LLM bare_digit_verifier 暂不支持

- **位置**：`src/note_linking/mod.rs:130-134`、`src/lib.rs:43-48`
- **状态**：`Phase3Config::skip_llm_verify` 默认 `true`，传 `false` 触发 `anyhow::bail!`
- **根因**：Rust 端无 vision LLM 客户端，属 Phase 3.5 `fnm-llm-repair` crate 范畴
- **影响**：年份类 bare_digit 误识别率可能略高于 Python（Python 端可调 LLM 二次确认）
- **解除条件**：`fnm-llm-repair` crate 落地后，加 `bare_digit_verifier` 参数到 `build_note_link_table`

---

## §3 OCR repair 三循环全部实现

- **位置**：`src/note_linking/ocr_repair.rs`
- **状态**：✅ 已完整实现
  - Loop 1：orphan_anchor rebind（行 71-168）
  - Loop 2：ambiguous follow-up（行 170-313）
  - Loop 3：cross-chapter same-page rebind（行 315-388）
- **测试**：4 个单测覆盖 empty / Loop 1 / Loop 2 / Loop 3 各场景
- **anchor 字段写回**：`normalized_marker` / `anchor_kind` / `certainty` / `ocr_repaired_from_marker` 全部正确写入（对齐 Python 行 102-105 + 行 900-905）

---

## §4 review_seed_summary 已实现

- **位置**：`src/note_links.rs:188-194`（`ReviewSeedSummary` struct）+ `mod.rs:421-427`（注入 evidence）
- **状态**：✅ 5 个字段全部填充：`boundary_review_required_count` / `uncertain_anchor_ids` / `orphan_link_ids` / `ambiguous_link_ids` / `synthetic_anchor_ids`
- **对照 Python**：`note_linking.py:165-178`

---

## §5 paragraph_footnotes / paragraph_endnotes 已实现

- **位置**：`src/paragraph_footnotes.rs`（384 行）、`src/paragraph_endnotes.rs`（363 行）
- **状态**：✅ 真实实现，非 stub
- **历史**：早期版本曾返回空 Vec，已在 P3.10 完成

---

## §6 anchor_summary base 合并

- **位置**：`src/note_linking/anchor_summary.rs::merge_with_base`
- **状态**：✅ 实现 `{**base, **computed}` 合并语义（Python `note_linking.py:60-68`）
- **合并字段**：base 独有 `year_like_filtered_count` 保留；computed 6 字段 (`total_count` / `explicit_count` / `synthetic_count` / `kind_counts` / `uncertain_count` / `ocr_repaired_count`) 覆盖

---

## §7 Biopolitics Phase 3 byte-equal parity 暂未达成（上游 cascade）

**这是当前 Phase 3 唯一 active known bug。其余 §1-§6 都是已修复或文档性的。**

- **位置**：`tests/biopolitics_phase3_parity.rs` 中 5 个 `#[ignore]` 测试：
  - `biopolitics_phase3_body_anchors_parity`
  - `biopolitics_phase3_note_links_parity`
  - `biopolitics_phase3_chapter_contracts_parity`
  - `biopolitics_phase3_summary_parity`
  - `spec_biopolitics_contract_v2_def_anchor_mismatch`

- **当前实测（2026-05-21，M5.2 _note_scan 结构化解析 fix 后，审计实跑 `--ignored` 复核）**：
  | 维度 | Rust vs Python | 状态 |
  |---|---:|---:|
  | `chapter_contracts_parity` | `chapter_id` 字段对齐，但 `contract[1].def_count: 50 vs 42` | ❌ **仍 FAIL**（cascade） |
  | `body_anchors_parity` | count mismatch（实跑仍 FAIL） | ❌ cascade |
  | `note_links_parity` | count mismatch | ❌ cascade |
  | `summary_parity` | count mismatch | ❌ cascade |
  | `spec_contract_v2` | mismatch=87 | ❌ cascade |
  | `phase2 note_items.len()` | 564 vs 584 (-20) | ⏳ 接近，PDF-free baseline |
  | `phase2 common_match` | 506/584 (87%) | ⏳ 多数 mismatch 来自 region_id 命名差异 |

  **审计修正**：M5.2 使用 `_note_scan` 结构化路径后，note_items 从 523 提升到 564（+41），common match 从 ~400 提升到 506。footnote 仍差 2 条（→ text 解析误抽）；endnote 差 18 条（→ 3 个 back-matter region 缺失 + note_scan 年份误标如 1769）。

- **Step A+B1+B2 (M5.2) 修复汇总**：
  1. **Chapter 边界** → Phase 1 production boundaries
  2. **Footnote 文本源** → `page.footnotes`（-49）
  3. **Region 0054 属章** → heading_candidates 匹配
  4. **Embedded note def** → `EMBEDDED_NOTE_DEF_RE`
  5. **OCR split 优先级** → standard marker 优先
  6. **bare_digit 上下文守卫** → `is_bare_digit_marker_context` 在 scan_inline_refs 中调用
  7. **gap recovery symbol 上下文** → `symbol_in_note_context`（替代 Python lookaround）
  8. **gap recovery digit 右文** → 对齐 `_WEAK_EXPECTED_DIGIT_RE` lookahead
  9. **`chapter_contracts_parity`** ✅ **PASS**，**`body_anchors` 已接近（-18）**
  10. **`_note_scan` 结构化解析** → endnote 页优先使用 OCR fnBlocks 结构化数据，回退文本解析
  11. 剩余 4 个 parity：note_links / summary / contract_v2 待修

- **残余根因**（Phase 3 cascade，非本章 scope）：
  - note_items 总数 564 vs 584（-20），endnote region 解析小幅差异  
  - 3 个 back-matter endnote region 缺失（0040 items）
  - region_id 双 toc 前缀命名差异（`toc-ch-N` vs `toc-toc-ch-N`）
  - _note_scan 年份误标（1769 作 marker，filter 未捕获）
  - Footnote text parser 假阳性（pg 37: markers 27/28/29 代替 1/4/*）
  - body_anchors / note_links / summary 仍 cascade

- **为什么测试 ignore 而不是放弃 byte-equal**：
  按 AGENTS.md 铁律 §7「不接受 'Rust simplified'」+ §1「翻译保真度禁简化」——
  断言本身必须是 byte-equal field-by-field（已落地）；
  上游 cascade 不允许通过降低阈值（如 `>= 80%`）掩盖。
  当上游 Phase 2 修复后，跑 `cargo test ... -- --ignored` 即可验真。

- **shape smoke 测试（active）**：`biopolitics_phase3_count_shape_smoke` 仅做 sanity check（非空 + ±50% 范围），**不冒充 parity**。

- **golden fixture**：`fnm-phase3/tests/fixtures/biopolitics_phase3_golden.json`（837 KB，664 anchors / 650 links / 12 contracts），由 `tools/gen_biopolitics_phase3_golden.py` 生成。

- **解除条件**：Phase 2 `note_items` over-extraction 修复 → 5 个 ignored 测试中任一项不变化（不需要新增字段），直接 `--ignored` 验真。
