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

- **真实数字（commit 3ff8cdf 后实测 2026-05-17）**：
  | 字段 | Rust | Python | 差异 |
  |---|---:|---:|---:|
  | `body_anchors.len()` | 787 | 664 | +123（+18.5%） |
  | `note_links.len()` | 713 | 650 | +63 |
  | `anchor_summary.total_count` | 787 | 664 | +123 |
  | `phase2 note_items.len()` | 619 | 584 | +35（**根因，待 Phase 2 fix**） |

- **chapter_id 前缀差异（已修复）**：
  - Rust 原 `chapter[0].chapter_id == "toc-ch-1"` ≠ Python golden `"toc-toc-ch-1"`
  - 根因：Python `_build_visual_toc_chapters` 用 `f"toc-{item.item_id}"`，而
    `item_id` 已是 `"toc-ch-N"` 格式——双 `toc-` 前缀是 Python 命名约定。
  - 修复（commit 待定）：
    - phase1 `chapter_skeleton/builder.rs`：改用 `format!("toc-{}", item.item_id)`
    - phase3 测试 fixture `biopolitics_phase3_parity.rs::build_chapters`：
      同步用 `toc-toc-ch-N` 字面量模拟 phase1 输出
  - 验证：`chapter_contracts_parity` 现在 fail 在 anchor count（Phase 2 cascade）
    而非 chapter_id 字符串。

- **book_type fix（commit 3ff8cdf P0-A）实测效果**：
  - 此前 phase3 `chapter_contracts:268` `if book_type == "endnote_only"` 永远 false
  - fix 后 phase2 chapter_split 写入 `policy_applied["book_type"]`，phase3 能读到
  - 但 anchor count cascade 上游问题未解，parity 仍 fail（5 ignored 状态未变）
  - **fix 的价值**：根除「sliently-wrong」逻辑分支错误，contract 判定路径正确化，
    但需要先解决 Phase 2 cascade 才能验证 byte-equal。

- **根因（Phase 2 上游 cascade，非 Phase 3 bug）**：Phase 2 `note_items` over-extraction 35 个，propagate 到 Phase 3 后：
  - Phase 3 anchor scanner 在正文找不到对应 anchor → `orphan_anchor` ↑23
  - Phase 3 把额外的 ignored link 也算进去 → `ignored` ↑31
  - 章级最严重：`toc-ch-6` (def=51 anchor=25 diff=26)、`toc-ch-8` (def=57 anchor=39 diff=18)

- **为什么测试 ignore 而不是放弃 byte-equal**：
  按 AGENTS.md 铁律 §7「不接受 'Rust simplified'」+ §1「翻译保真度禁简化」——
  断言本身必须是 byte-equal field-by-field（已落地）；
  上游 cascade 不允许通过降低阈值（如 `>= 80%`）掩盖。
  当上游 Phase 2 修复后，跑 `cargo test ... -- --ignored` 即可验真。

- **shape smoke 测试（active）**：`biopolitics_phase3_count_shape_smoke` 仅做 sanity check（非空 + ±50% 范围），**不冒充 parity**。

- **golden fixture**：`fnm-phase3/tests/fixtures/biopolitics_phase3_golden.json`（837 KB，664 anchors / 650 links / 12 contracts），由 `tools/gen_biopolitics_phase3_golden.py` 生成。

- **解除条件**：Phase 2 `note_items` over-extraction 修复 → 5 个 ignored 测试中任一项不变化（不需要新增字段），直接 `--ignored` 验真。
