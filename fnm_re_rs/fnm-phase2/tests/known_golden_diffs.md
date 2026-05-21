# Phase 2 Known Golden Diffs

本文档记录 Rust Phase 2 输出与持久化 golden（Biopolitics 章节级 ground truth）的已知差异。

**Golden 定位（2026-05-21 起）**：

- golden 来源于项目早期 pipeline 输出（M4 前 Python 实现导出），现已脱离 Python 权威源
- M5 起，golden 作为 Rust pipeline 的回归基准，独立存在

---

## §1 note_items 数量 -20 差距

**当前状态**：

| 维度 | Rust 实际 | Golden | 差距 |
|---|---:|---:|---:|
| `phase2.note_regions.len()` | ~basically aligned | — | gap ≤ 5 |
| `phase2.note_items.len()` | 564 | 584 | **-20** |

**审计工具**：`tests/audit_note_items_against_golden.rs` 输出逐条 extra/missing 列表到
`/tmp/audit_note_items/`。

**根因分析**：

差距主要在 endnote region 内的 marker 抽取过严。审计输出显示 missing items 集中在：
- 部分 footnote_band region 末尾的延续条目（被截断未识别）
- endnote region 跨页延续时的 marker 接续

**修复方向**（待后续 M5+ 工作）：

- 比对 audit 输出，逐 region 分析 missing items 的位置和上下文
- 调整 `note_items/sequence_repair.rs` 或 `note_items/marker_parse.rs` 的边界守卫
- 修复后跑 `biopolitics_note_items_field_by_field` 验真

**影响**：cascade 到 phase3 → body_anchors / note_links / chapter_contracts 数量偏离
（详见 `../fnm-phase3/tests/known_golden_diffs.md §1`）。

---

## §2 chapter_split note_mode 决策（已 byte-equal）

- **位置**：`src/chapter_split/mod.rs`
- **状态**：✅ 4 升级分支决策与 golden 一致（FootnotePrimary / ChapterEndnotePrimary /
  ReviewRequired / NoNotes）
- **测试**：`biopolitics_regions_per_chapter_alignment`、`biopolitics_phase2_smoke`

---

## §3 sup_recovery（chapter-scoped）

- **位置**：`src/sup_recovery/{layer1,layer2,layer3}.rs`
- **状态**：✅ Layer 1 (markdown 直匹配) + Layer 2 (4 种 OCR surrogate) + Layer 3
  (vision LLM, 需 pdf + API key) 全部实现
- **设计**：参 `../fnm-phase3/tests/known_golden_diffs.md §3` 的 OCR repair 三循环对应

---

更多 cascade 相关讨论详见 [`../fnm-phase3/tests/known_golden_diffs.md`](../../fnm-phase3/tests/known_golden_diffs.md)。
