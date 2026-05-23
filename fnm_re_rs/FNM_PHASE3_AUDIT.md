# fnm-phase3 审计记录

审计对象：`fnm-phase3`

审计时间：2026-05-22

审计范围：

- `src/lib.rs`
- `src/body_anchors/**`
- `src/note_links.rs`
- `src/endnote_links.rs`
- `src/footnote_links.rs`
- `src/endnote_repair/**`
- `src/note_linking/**`
- `src/paragraph_footnotes.rs`
- `src/paragraph_endnotes.rs`
- `src/chapter_anchor_alignment/**`
- `tests/**`

结论：`fnm-phase3` 的 release build、fmt、测试可以跑通；在放宽前序 crate 已知 clippy 问题后，本 crate 本体 clippy 可通过。但业务质量仍未达可接下游的标准：Phase 3 有几处重新构造 Phase 1/2 事实、把 unknown anchor 当 endnote、跨章恢复 gap anchor、混合 footnote/endnote 计算 contract 的问题。这些都违反“Phase 3 只消费 Phase 2 分类事实，不重新分类、不广播、不跳层修补”的原则。

## P1 阻塞问题

### P1-1 Phase 3 输出会用 lossy `phase2_rebuild` 覆盖 Phase 1/2 事实

位置：

- `fnm-phase3/src/lib.rs:71`
- `fnm-phase3/src/lib.rs:119`
- `fnm-phase3/src/lib.rs:120`
- `fnm-phase3/src/lib.rs:121`
- `fnm-phase3/src/lib.rs:122`
- `fnm-phase3/src/note_linking/phase2_rebuild.rs:136`
- `fnm-phase3/src/note_linking/phase2_rebuild.rs:142`
- `fnm-phase3/src/note_linking/phase2_rebuild.rs:210`
- `fnm-phase3/src/note_linking/phase2_rebuild.rs:254`

`build_phase3_structure()` 把 `note_linking::build_note_link_table()` 返回的 `phase2` 直接写进 `Phase3Structure`：

```rust
pages: phase2.pages,
heading_candidates: phase2.heading_candidates,
chapters: phase2.chapters,
section_heads: phase2.section_heads,
```

但这个 `phase2` 不是原始 Phase 1/2 输出，而是 `phase2_rebuild.rs` 从 `ChapterLayers` 重新拼出来的：

- chapter `source` 被写死为 `ChapterSource::Fallback`。
- pages 只来自 `cl.body_pages`，并全部写成 `PageRole::Body`。
- `heading_candidates`、`section_heads` 被置空。
- `Phase2Summary::default()` 留空。

这会让 Phase 3 输出结构携带退化后的 Phase 1/2 事实。现有测试 `spec_phase3_contains_phase2_fields_without_mutating_phase2` 只断言非空，没有检查 byte-equal 保留，因此覆盖不到这个问题。

修复方向：

- Phase 3 输出的 `pages/chapters/heading_candidates/section_heads` 应直接使用输入的原始 Phase 1/2 事实。
- `phase2_rebuild` 只应用于内部 note link materialization，不能替代 persisted/output structure。
- 给 `spec_phase3_contains_phase2_fields_without_mutating_phase2` 补充 page role、chapter source、note page 保留、section/headings 保留的断言。

### P1-2 `unknown` orphan anchor 被写成 endnote link

位置：

- `fnm-phase3/src/note_links.rs:159`
- `fnm-phase3/src/note_links.rs:162`
- `fnm-phase3/src/note_links.rs:173`
- `fnm-phase3/src/note_links.rs:189`
- `fnm-phase3/src/note_links.rs:199`

`build_orphan_anchor_links()` 先把 anchor_kind 非 footnote/endnote 的 anchor 标成 `"unknown"`：

```rust
let inferred_kind = match anchor.anchor_kind.as_str() {
    "footnote" => "footnote",
    "endnote" => "endnote",
    _ => "unknown",
};
```

但创建 orphan link 时：

```rust
note_kind: if inferred_kind == "footnote" {
    NoteKind::Footnote
} else {
    NoteKind::Endnote
}
```

也就是说 unknown anchor 会被强制记为 endnote orphan_anchor。Phase 3 下游 contract 会把这些 unknown 噪声当 endnote 缺口处理，制造 `link_endnote_only_orphan_anchor_remaining` 或 `contract_def_anchor_mismatch`。

修复方向：

- unknown anchor 不应转换为 `NoteKind::Endnote`。
- 如果 schema 暂无 Unknown note_kind，应跳过并写 review seed，或增加显式 unknown/review 状态。

### P1-3 endnote orphan recovery 只从已有 anchor 推导 body pages

位置：

- `fnm-phase3/src/endnote_links.rs:276`
- `fnm-phase3/src/endnote_links.rs:278`
- `fnm-phase3/src/endnote_links.rs:279`
- `fnm-phase3/src/endnote_links.rs:297`
- `fnm-phase3/src/endnote_links.rs:305`

orphan endnote 正文搜索恢复时，chapter body page 集合来自已有 anchors：

```rust
for a in anchors.iter() {
    chapter_body_pages.entry(a.chapter_id.clone()).or_default().insert(a.page_no);
}
```

如果某章当前没有任何 anchor，但有 orphan endnote notes，`page_nos` 会是空，正文搜索恢复完全不会扫描该章 raw pages。这正是需要 recovery 的场景，却被前置条件排除了。

修复方向：

- `build_endnote_links()` 应接收 chapter body pages 或 Phase 1 page partitions。
- recovery 页集合必须来自 Phase 1/ChapterRecord，而不是“已经检测出的 anchors”。

### P1-4 gap recovery 跨章扫描，会把其它章节文本物化成当前章 anchor

位置：

- `fnm-phase3/src/body_anchors/mod.rs:193`
- `fnm-phase3/src/body_anchors/gap_recovery.rs:306`
- `fnm-phase3/src/body_anchors/gap_recovery.rs:329`
- `fnm-phase3/src/body_anchors/gap_recovery.rs:399`
- `fnm-phase3/src/body_anchors/gap_recovery.rs:413`

`recover_expected_gap_bare_digit_anchors()` 和 `recover_expected_gap_symbol_anchors()` 都遍历全书 `page_text_by_no`。bare digit 至少有 sequence page window，但仍不是严格 chapter page set；symbol recovery 没有 page window，直接全书扫描：

```rust
for (page_no, text) in page_text_by_no {
    ...
    anchors.push(BodyAnchorRecord {
        chapter_id: chapter_id.to_string(),
        page_no: *page_no,
```

结果可能是：在 B 章页面上找到 `*`，却生成 A 章的 endnote anchor。这个问题和 Phase 2 `sup_recovery` 的全书扫描是同类跨章污染。

修复方向：

- gap recovery 输入必须包含 chapter page set。
- symbol recovery 至少要复用 bare digit 的 sequence window，并限制在当前章 body pages。
- 当前被 ignore 的 gap recovery spec 应解除 ignore 后作为修复验收。

### P1-5 contract v2 把 footnote definitions 计入 endnote def/anchor mismatch

位置：

- `fnm-phase3/src/note_linking/chapter_contracts.rs:287`
- `fnm-phase3/src/note_linking/chapter_contracts.rs:288`
- `fnm-phase3/src/note_linking/chapter_contracts.rs:289`
- `fnm-phase3/src/note_linking/chapter_contracts.rs:304`
- `fnm-phase3/src/note_linking/chapter_contracts.rs:336`

`chapter_contracts()` 的 endnote contract 中：

```rust
let all_def_items: Vec<_> = chapter
    .footnote_items
    .iter()
    .chain(chapter.endnote_items.iter())
    .collect();
```

但 `anchor_total` 只统计 endnote anchors。混合章节里，footnote definitions 会抬高 `def_count`，然后与 endnote anchor 数比较，导致 `contract_def_anchor_mismatch` 假阳性。这违反 footnote/endnote dispatch 分离原则。

修复方向：

- endnote contract 只计算 endnote definitions。
- footnote 如需 contract，单独做 footnote contract，不要混在 endnote contract 里。

## P2 重要问题

### P2-1 bare digit LLM 候选被收集后丢弃

位置：

- `fnm-phase3/src/body_anchors/context_guard.rs:174`
- `fnm-phase3/src/body_anchors/context_guard.rs:181`
- `fnm-phase3/src/body_anchors/context_guard.rs:186`
- `fnm-phase3/src/body_anchors/context_guard.rs:194`
- `fnm-phase3/src/body_anchors/mod.rs:189`
- `fnm-phase3/src/body_anchors/mod.rs:190`

`positive_gate_bare_digit()` 会把高风险 bare_digit 放到 `llm_candidates`，但调用处是：

```rust
let (mut anchors, _llm_candidates) =
    context_guard::positive_gate_bare_digit(&anchors, &chapter_note_items);
```

候选既没有送 LLM，也没有进入 diagnostics/review seed。结果是这些 anchor 静默消失，后续只表现为 orphan_note 或 contract gap。

修复方向：

- `llm_candidates` 必须进入 diagnostics/review_seed_summary。
- `skip_llm_verify=true` 时，应明确记录 skipped candidates 数量，而不是丢弃。

### P2-2 footnote 最终降级会把 missing anchor 变成 matched synthetic

位置：

- `fnm-phase3/src/footnote_links.rs:245`
- `fnm-phase3/src/footnote_links.rs:248`
- `fnm-phase3/src/footnote_links.rs:253`
- `fnm-phase3/src/footnote_links.rs:258`
- `fnm-phase3/src/footnote_links.rs:265`

当 footnote 找不到显式 anchor 时，代码创建 `synthetic-footnote-*`，并直接生成 `Matched + Fallback` link。这个 link 没有正文坐标：

```rust
char_start: 0,
char_end: 0,
synthetic: true,
status: LinkStatus::Matched,
```

Phase 4 引用冻结要求 matched link 必须可注入；synthetic/无坐标 anchor 应成为 blocker，而不应在 Phase 3 被包装成普通 matched。

修复方向：

- synthetic footnote matched 必须进入 hard blocker 或至少明确 review 状态。
- Phase 4 前 gate 应能阻止“matched 但不可注入”的 link 继续流转。

### P2-3 paragraph endnotes/footnotes 重新解析注释内容，绕开 Phase 2 权威结果

位置：

- `fnm-phase3/src/paragraph_footnotes.rs:197`
- `fnm-phase3/src/paragraph_footnotes.rs:234`
- `fnm-phase3/src/paragraph_endnotes.rs:47`
- `fnm-phase3/src/paragraph_endnotes.rs:57`
- `fnm-phase3/src/paragraph_endnotes.rs:107`
- `fnm-phase3/src/paragraph_endnotes.rs:268`

`paragraph_footnotes.rs` 和 `paragraph_endnotes.rs` 都从 raw page markdown/note_scan 重新识别注释条目，而不是消费 Phase 2 的 `NoteItem`/`NoteRegion`。其中 `paragraph_endnotes::is_endnote_page()` 在 `role == "note"` 时直接返回 true，不检查 note kind；book-scope run 又用 `chapter_id_for_page(run[0])` 绑定到最近章节。

这会在 Phase 3 内重新分类注释页，可能和 Phase 2 的 `note_kind` 事实冲突。

修复方向：

- paragraph_* 产物应从 Phase 2 NoteItem/NoteRegion 派生。
- raw page 只能作为文本定位辅助，不应重新决定 footnote/endnote。

### P2-4 chapter anchor alignment 混入非 endnote anchors

位置：

- `fnm-phase3/src/chapter_anchor_alignment/dp_alignment.rs:19`
- `fnm-phase3/src/chapter_anchor_alignment/dp_alignment.rs:115`
- `fnm-phase3/src/chapter_anchor_alignment/dp_alignment.rs:117`
- `fnm-phase3/src/chapter_anchor_alignment/dp_alignment.rs:121`

`body_markers_by_chapter()` 把所有 body anchors 都纳入 alignment：

```rust
for anchor in body_anchors {
    result.entry(anchor.chapter_id.clone()).or_default().push(anchor.normalized_marker.clone());
}
```

但右侧序列是 `paragraph_endnotes`。footnote anchors、unknown anchors、synthetic fallback anchors 都会污染 endnote alignment。

修复方向：

- alignment 输入只允许 `anchor_kind == Endnote` 的 anchors。
- 是否包含 synthetic anchors 需要显式策略；默认不应和真实 body anchors 混在一起。

### P2-5 override 创建 note item 时非法 note_kind fallback 到 Footnote

位置：

- `fnm-phase3/src/note_linking/note_item_overrides.rs:119`
- `fnm-phase3/src/note_linking/note_item_overrides.rs:124`
- `fnm-phase3/src/note_linking/note_item_overrides.rs:128`
- `fnm-phase3/src/note_linking/note_item_overrides.rs:129`

`note_item` override 的 `note_kind` 若不是 `footnote/endnote`，会落到 `NoteKind::Footnote`：

```rust
} else {
    NoteKind::Footnote
}
```

Phase 3.5/override 是在修补 Phase 3 link，不应在 Phase 3 内重新制造不确定分类事实。

修复方向：

- 非法 `note_kind` 直接 reject override。
- missing `note_kind` 也不应默认 endnote，除非 override schema 明确要求且测试覆盖。

## P3 质量与测试问题

### P3-1 Phase3 parity 测试基本被 ignore

位置：

- `fnm-phase3/tests/biopolitics_phase3_parity.rs`
- `fnm-phase3/tests/known_golden_diffs.md`

`cargo test -p fnm-phase3` 中：

- Biopolitics Phase3 parity：7 个测试，5 个 ignored。
- 当前 active 的两个只是 smoke/count shape。
- `known_golden_diffs.md` 明确记录：`phase3.body_anchors` 与 golden 差约 -101，`phase3.note_links` 差约 -130。

这意味着 Phase 3 当前不能声称 byte-equal parity。后续修复不能只看单元测试通过，必须恢复 ignored parity。

### P3-2 `endnote_repair/contract_repair.rs` 超过 400 行且带 clippy allow

位置：

- `fnm-phase3/src/endnote_repair/contract_repair.rs:1`
- `fnm-phase3/src/endnote_repair/contract_repair.rs:62`
- `fnm-phase3/src/endnote_repair/contract_repair.rs:182`

文件 467 行，超过当前 Rust 规范的拆分线，并用 `#[allow(clippy::needless_range_loop)]` 保护多段 index mutation。注释解释了借用复杂度，但这仍是后续维护风险。

修复方向：

- 抽 `RepairState` struct，按 4 段流程拆成小函数。
- 用集中 state 管理 mutable links/anchors/used ids，去掉 allow。

## 门禁验证

已执行：

```bash
cargo build --release -p fnm-phase3
cargo test -p fnm-phase3
cargo fmt --check -p fnm-phase3
cargo clippy -p fnm-phase3 --all-targets -- -D warnings
```

结果：

- `cargo build --release -p fnm-phase3`：通过，但继承 `fnm-phase2` 的 4 个 warning。
- `cargo fmt --check -p fnm-phase3`：通过。
- `cargo test -p fnm-phase3`：通过。
  - lib tests：26 passed。
  - `biopolitics_phase3_parity`：2 passed，5 ignored。
  - `test_phase3_spec`：25 passed，2 ignored。
- `cargo clippy -p fnm-phase3 --all-targets -- -D warnings`：失败，先被 `fnm-core` 已知 clippy 问题阻断。
- 放宽 `fnm-core`/`fnm-phase1`/`fnm-phase2` 已知 lint 后，`fnm-phase3` 本体 clippy 通过。

## 建议修复顺序

1. 先修 `build_phase3_structure()` 输出保真：保留原始 Phase 1/2 facts，只替换 override 后的 note items/regions。
2. 修 `build_orphan_anchor_links()` 的 unknown kind 处理，禁止 unknown 自动转 endnote。
3. 给 endnote/gap recovery 接入 chapter page set，禁止跨章扫描。
4. 拆分 footnote/endnote contract，修 mixed chapter 的 `def_anchor_mismatch`。
5. 让 bare digit LLM candidates 进入 diagnostics/review seed。
6. 再处理 paragraph_* 与 alignment 的 Phase 2 数据源统一。
7. 最后恢复 ignored parity/spec 测试。

## 边缘情况清单

- 某章有 endnote item，但没有任何已检测 anchor。
- 同一 marker 在多章重复出现。
- unknown/bracket anchor 没有可确认 note kind。
- 同章同时有 footnote 和 endnote。
- synthetic footnote anchor 被 Phase 4 注入。
- book-scope endnote 页不属于任何 chapter page range。
- raw page `book_page` 与 TOC/printed page 不一致。

