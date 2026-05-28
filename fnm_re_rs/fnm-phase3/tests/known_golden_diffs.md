# Phase 3 Known Golden Diffs

本文档记录 Rust Phase 3 输出与持久化 golden（Biopolitics 章节级 ground truth）的已知差异，
以及当前 `#[ignore]` 的回归测试根因。

**Golden 定位（2026-05-21 起）**：

- golden 来源于项目早期 pipeline 输出（M4 前 Python 实现导出），现已脱离 Python 权威源
- M5 起，golden 作为 Rust pipeline 的回归基准，独立存在
- byte-equal 断言保持严格（AGENTS.md 铁律 §7：禁止用阈值/coverage 掩盖差异）；
  当 Rust 输出与 golden 偏离时，差异必须在本文档登记根因，对应测试加 `#[ignore]` + reason

---

## §1 Phase 2 cascade · note_items 数量与 golden 偏离

**当前状态**（截至 M5 主线）：

| 维度 | Rust 实际 | Golden | 差距 |
|---|---:|---:|---:|
| `phase2.note_items.len()` | 564 | 584 | **-20** |
| `phase3.body_anchors.len()` | ~563 | 664 | -101（cascade）|
| `phase3.note_links.len()` | ~520 | 650 | -130（cascade）|
| `chapter_link_contracts` | 部分 def_count 偏差 | — | cascade |

**Cascade 路径**：

```
phase2/note_items 抽取 -20
  ↓
phase3/body_anchors 检测时找不到对应 marker → 少抽
  ↓
phase3/note_links 匹配数量 cascade 下降
  ↓
chapter_link_contracts 中 def_count 与 anchor_count 不平衡
```

**Cascade 涉及测试**（全部 `#[ignore]`，必须显式 `--ignored` 验真）：

1. `biopolitics_phase3_body_anchors_parity`
2. `biopolitics_phase3_note_links_parity`
3. `biopolitics_phase3_chapter_contracts_parity`
4. `biopolitics_phase3_summary_parity`
5. `spec_biopolitics_contract_v2_def_anchor_mismatch`

**2026-05-27 更新**：上述五项已显式运行并全部失败；与此同时
`fnm-phase2` 的 active Biopolitics parity 测试通过。因此“仅因 Phase2
note_items `-20`”已不足以作为当前根因说明。后续应比较 Phase3 测试入口
实际消费的 Phase2 输出、fixture 版本与持久化输入，定位第一处分叉。

**Phase 2 修复方向**：

- 比对 `fnm_re_rs/fnm-phase2/tests/audit_note_items_against_golden.rs` 输出
- 当前差距主要在 endnote region（cascade -61 → -20 已优化，仍未消除）
- 待修复后，本节状态更新为"已闭合"

**Chapter ID 命名约定**：

历史命名 `toc-{item_id}`，而 item_id 已是 `toc-ch-N` —— 形成双 `toc-` 前缀（如 `toc-toc-ch-1`）。
Rust 端透传保持此命名以与 golden byte-equal；新书入库可在 caller 端规范化。

---

## §2 LLM bare_digit_verifier 占位

- **位置**：`src/note_linking/mod.rs:130-134`、`src/lib.rs:43-48`
- **状态**：`Phase3Config::skip_llm_verify` 默认 `true`，传 `false` 触发 `anyhow::bail!`
- **设计**：Rust 端 LLM 客户端隔离在 `fnm-llm-repair` crate（Phase 3.5）
- **影响**：年份类 bare_digit 误识别率略高于完整 LLM 验证模式（无 LLM 二次确认）
- **解除条件**：`fnm-llm-repair` 集成到 Phase 3 主入口后，加 `bare_digit_verifier` 参数到
  `build_note_link_table`

---

## §3 OCR repair 三循环（已完整实现）

- **位置**：`src/note_linking/ocr_repair/`
- **状态**：✅ Loop 1 (orphan_anchor rebind) + Loop 2 (ambiguous follow-up) + Loop 3
  (cross-chapter same-page rebind) 全部实现
- **测试**：4 个单测覆盖 empty / Loop 1 / Loop 2 / Loop 3
- **anchor 字段写回**：`normalized_marker` / `anchor_kind` / `certainty` /
  `ocr_repaired_from_marker` 全部正确

---

## §4 review_seed_summary（已实现）

- **位置**：`src/note_links.rs:188-194` (`ReviewSeedSummary` struct) +
  `mod.rs:421-427`（注入 evidence）
- **状态**：✅ 5 个字段全部填充：`boundary_review_required_count` / `uncertain_anchor_ids` /
  `orphan_link_ids` / `ambiguous_link_ids` / `synthetic_anchor_ids`

---

## §5 paragraph_footnotes / paragraph_endnotes（已实现）

- **位置**：`src/paragraph_footnotes.rs` (384 行)、`src/paragraph_endnotes.rs` (363 行)
- **状态**：✅ 真实实现（早期 stub 已替换）

---

## §6 anchor_summary base 合并（已实现）

- **位置**：`src/note_linking/anchor_summary.rs::merge_with_base`
- **状态**：✅ 实现 `{**base, **computed}` 合并语义
- **字段**：base 独有 `year_like_filtered_count` 保留；computed 6 字段
  (`total_count` / `explicit_count` / `synthetic_count` / `kind_counts` /
  `uncertain_count` / `ocr_repaired_count`) 覆盖

---

## §7 [DEPRECATED] Phase 3 byte-equal parity 状态描述

**注**：本节原描述"Rust 619 vs Python 584"等历史数据点，已统合到 §1。
保留作为历史追溯，新差异请记录在 §1。

旧记录摘要：
- 2026-05-17（实测）：phase2 note_items 573 vs 584 (-11)
- 2026-05-20（M5.2 优化后）：phase2 note_items 564 vs 584 (-20) ← 当前
- 历史 build：Rust 619 vs 584 (+35) → 已通过 sup_recovery / endnote_repair 修复降至当前

**Shape smoke 测试**：`biopolitics_phase3_count_shape_smoke`（active）仅做 sanity check
（非空 + ±50% 范围），**不冒充 parity**。

**Golden fixture**：`fixtures/biopolitics_phase3_golden.json`（837 KB，664 anchors /
650 links / 12 contracts）。

**解除条件**：phase2 note_items 与 golden 达成 byte-equal（差距 → 0），直接
`cargo test biopolitics_phase3 -- --ignored` 验真。
