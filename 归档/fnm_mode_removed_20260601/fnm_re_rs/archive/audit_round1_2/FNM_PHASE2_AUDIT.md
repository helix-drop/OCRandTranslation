# fnm-phase2 审计记录

审计对象：`fnm-phase2`

审计时间：2026-05-22

审计范围：

- `src/lib.rs`
- `src/book_structure.rs`
- `src/chapter_split/**`
- `src/note_regions/**`
- `src/note_items/**`
- `src/endnote_chapter_explorer/mod.rs`
- `src/endnote_repair/mod.rs`
- `src/sup_recovery/**`
- `src/visual_anchor_recovery/**`
- `src/llm_bare_digit_verify/**`
- `tests/**`

结论：`fnm-phase2` 的 release build 和测试可以通过，但质量门禁没有通过。核心风险集中在 Phase 2 的事实边界：`note_kind`/region/chapter 本应是后续阶段的不可变事实，但 note item 后处理、上标恢复、章节绑定探索里仍有跨 region、跨 chapter 或旧路径残留，会让后续 Phase 3/4 接收到被污染的输入。

## P1 阻塞问题

### P1-1 多页 footnote region 会按 marker 去重，可能删除合法脚注

位置：

- `fnm-phase2/src/note_regions/footnote_band.rs:124`
- `fnm-phase2/src/note_regions/footnote_band.rs:139`
- `fnm-phase2/src/note_items/mod.rs:116`
- `fnm-phase2/src/note_items/mod.rs:145`

`footnote_band` 会把连续脚注页合成一个 region：

```rust
for (run_index, run_pages) in split_contiguous_ranges(&footnote_pages)
```

随后 `build_note_items()` 在同一 region 内按 marker 去重：

```rust
rows = dedupe_region_items(rows);
```

`dedupe_region_items()` 只用 normalized marker 做 key：

```rust
if !marker.is_empty() && seen.contains(&marker) {
    continue;
}
```

脚注常见模式是每页从 `1` 重新编号。如果两个连续正文页都有脚注 `1`，它们会被合进同一个 footnote region，第二页的 `1` 会被当成重复项删除。这会直接造成 note item 缺失，并把错误传给 Phase 3 link matching。

修复方向：

- footnote 去重 key 至少包含 `page_no`，或者 footnote band 按页切 region。
- endnote 可以继续按 region+marker 去重，但 footnote 不应共用同一策略。

### P1-2 年份误标修复没有 region/chapter 边界，可能跨区域删除或改 marker

位置：

- `fnm-phase2/src/note_items/mod.rs:135`
- `fnm-phase2/src/note_items/mod.rs:138`
- `fnm-phase2/src/note_items/year_filter.rs:19`
- `fnm-phase2/src/note_items/year_filter.rs:28`
- `fnm-phase2/src/note_items/year_filter.rs:42`

`build_note_items()` 先全局合并，再全局调用年份修复：

```rust
let items = merge_continuation_notes(all_items);
let items = fix_year_markers_in_place(items);
```

`fix_year_markers_in_place()` 只看相邻三条记录的 marker 数字关系，没有检查 `region_id`、`chapter_id`、`note_kind`：

```rust
let prev_val = try_parse_int(&updated[i - 1].marker);
let curr_val = try_parse_int(&updated[i].marker);
let next_val = try_parse_int(&updated[i + 1].marker);
```

同文件里的 `fix_sequence_outlier_markers_in_place()` 已经检查 region/chapter 连续性，说明这里缺少边界守卫不是刻意设计。跨 region 边界上如果恰好形成 `prev + 1 == next` 或 `prev + 2 == next`，合法 note item 会被删除或改 marker。

修复方向：

- 按 `(chapter_id, region_id, note_kind)` 分组后再执行年份修复。
- 或在循环内加入和 sequence outlier 一致的 region/chapter/kind 边界检查。

### P1-3 引文续行合并按字符串 marker 排序，数字顺序会错

位置：

- `fnm-phase2/src/note_items/mod.rs:164`
- `fnm-phase2/src/note_items/mod.rs:169`
- `fnm-phase2/src/note_items/mod.rs:173`

`merge_continuation_notes()` 的排序条件是：

```rust
items.sort_by(|a, b| {
    a.region_id
        .cmp(&b.region_id)
        .then_with(|| a.page_no.cmp(&b.page_no))
        .then_with(|| a.marker.cmp(&b.marker))
});
```

`marker` 是字符串，所以 `"10"` 会排在 `"2"` 前面。如果当前 item 文本命中 `PAGE_CITATION_PREFIX_RE`，续行合并会拿错下一条记录，导致两条 note 的正文被错误拼接。

修复方向：

- 保留解析原始顺序用于续行合并。
- 若必须排序，marker 应使用数字 sort key，并对非数字 marker 明确分支。

## P2 重要问题

### P2-1 `ChapterNoteModeRecord` 用 `note_mode` 反推事实布尔值

位置：

- `fnm-phase2/src/chapter_split/mod.rs:117`
- `fnm-phase2/src/chapter_split/mod.rs:289`
- `fnm-phase2/src/chapter_split/mod.rs:293`
- `fnm-phase2/src/chapter_split/mod.rs:294`
- `fnm-phase2/src/chapter_split/mod.rs:295`

当前记录：

```rust
primary_region_scope: "chapter".into(),
has_footnote_band: mode == NoteMode::FootnotePrimary,
has_endnote_region: mode == NoteMode::ChapterEndnotePrimary,
```

这把聚合判断 `note_mode` 反推成事实字段。混合章节、`ReviewRequired`、book-scope endnote 都会丢失真实布尔信息。按 FNM 规则，章级 mode 是摘要信号，不能广播或反推个体事实。

修复方向：

- `has_footnote_band` 从实际 footnote region/source 或 footnote items 计算。
- `has_endnote_region` 从实际 endnote regions/items 计算。
- `primary_region_scope` 从实际主 region scope 计算；无法唯一时显式 review，而不是固定 `"chapter"`。

### P2-2 `note_kind` 兜底仍返回 `Footnote`

位置：

- `fnm-phase2/src/note_kind_resolver.rs:105`
- `fnm-phase2/src/note_kind_resolver.rs:106`
- `fnm-phase2/src/note_kind_resolver.rs:107`
- `fnm-phase2/src/note_kind_resolver.rs:110`

注释写的是“不要默认 footnote”，但返回值仍是：

```rust
note_kind: NoteKind::Footnote,
review_required: true,
```

只要下游没有强制检查 `review_required`，这个不确定 region 就会以 footnote 身份进入普通流程。`note_kind` 是 Phase 2 的唯一分类源头，这里不应把未知事实编码成 footnote。

修复方向：

- 类型层面增加 unknown/review 状态，或阻止 fallback region 进入普通 note item/link 流程。
- 至少在 `build_note_regions`/`build_note_items` 对 `review_required` 做显式门禁。

### P2-3 `build_note_regions()` 接入旧 explorer stub 但丢弃结果

位置：

- `fnm-phase2/src/note_regions/mod.rs:100`
- `fnm-phase2/src/note_regions/mod.rs:101`
- `fnm-phase2/src/note_regions/mod.rs:103`
- `fnm-phase2/src/note_regions/mod.rs:104`

代码明确写着：

```rust
// 当前 stub（20% 完成度），接入但不期望实际修改 regions。
let _explorations =
    crate::endnote_chapter_explorer::explore_endnote_chapter_regions(pages, phase1_chapters);
```

主流程 `src/lib.rs` 后面又会调用 full explorer。这条旧路径既不改变输出，也会误导维护者以为 explorer 已经参与 region rebind。

修复方向：

- 删除旧 stub 调用。
- 只保留一个 endnote chapter explorer 入口，并让数据流清晰地进入 regions 输出。

### P2-4 `sup_recovery` 名义按章，实际全书扫描

位置：

- `fnm-phase2/src/sup_recovery/mod.rs:24`
- `fnm-phase2/src/sup_recovery/mod.rs:33`
- `fnm-phase2/src/sup_recovery/mod.rs:37`
- `fnm-phase2/src/sup_recovery/mod.rs:54`
- `fnm-phase2/src/sup_recovery/mod.rs:79`

`recover_book_chapter_scoped()` 按 chapter marker 循环，但 Layer 1、Layer 2、Layer 3 都扫描 `pages` 全量输入，没有使用 chapter page range。不同章节重复 marker 是常态，当前实现可能用其它章节的正文证明当前章节的 marker 已恢复。

当前结果只进入 diagnostics，影响还没扩散；一旦后续接入为真实 anchor/recovery 输出，就会跨章污染。

修复方向：

- 输入改为 chapter page range 或 chapter pages。
- 每一层 recovery 都只能扫描当前章的 body pages。

### P2-5 `endnote_chapter_explorer` 用 printed page 和 book page 直接比较

位置：

- `fnm-phase2/src/endnote_chapter_explorer/mod.rs:545`
- `fnm-phase2/src/endnote_chapter_explorer/mod.rs:576`
- `fnm-phase2/src/endnote_chapter_explorer/mod.rs:601`
- `fnm-phase2/src/endnote_chapter_explorer/mod.rs:631`

`toc_subentries_for_page(page_no, hints)` 取 TOC subentry 的 `printed_page`，然后直接比较：

```rust
if pp <= page_no {
    active_index = idx as i64;
}
```

这里 `page_no` 来自 raw page/book page，`printed_page` 来自 TOC 视觉语义。两者不一定同一坐标系。前言罗马页、扫描偏移、PDF page 与印刷页不一致时，TOC subentry 绑定会漂移到错误章节。

修复方向：

- 先建立 printed page 到 book/pdf page 的映射。
- 没有映射时不要使用 TOC subentry 做强 rebind，只能降级为 review signal。

### P2-6 旧视觉恢复路径按 marker 回推 chapter，重复 marker 会错绑

位置：

- `fnm-phase2/src/visual_anchor_recovery/mod.rs:41`
- `fnm-phase2/src/visual_anchor_recovery/mod.rs:44`
- `fnm-phase2/src/visual_anchor_recovery/mod.rs:101`
- `fnm-phase2/src/visual_anchor_recovery/mod.rs:108`
- `fnm-phase2/src/visual_anchor_recovery/mod.rs:112`

旧入口 `build_visual_recovery_overrides()` 将 vision 结果按 marker 分组：

```rust
by_chapter.entry(result.marker.clone())
```

然后扫描 `chapter_markers`，把 marker 属于的第一个 chapter 当成结果归属：

```rust
for (cid, expected) in chapter_markers {
    if expected.contains(marker) {
        return cid.clone();
    }
}
```

同一个 marker 在每章都会重复，这条路径会把恢复结果挂到错误章节。新入口 `run_visual_anchor_recovery()` 使用 `ChapterAnchorGap`，方向更正确，但旧入口仍是 public API。

修复方向：

- 删除旧入口，或改为携带 gap/chapter_id 的结果结构。

## P3 质量与风格问题

### P3-1 `sup_recovery/layer2.rs` 违反 Rust 重构规范

位置：

- `fnm-phase2/src/sup_recovery/layer2.rs:90`
- `fnm-phase2/src/sup_recovery/layer2.rs:120`
- `fnm-phase2/src/sup_recovery/layer2.rs:144`
- `fnm-phase2/src/sup_recovery/layer2.rs:168`
- `fnm-phase2/src/sup_recovery/layer2.rs:194`
- `fnm-phase2/src/sup_recovery/layer2.rs:211`

问题：

- 多处在循环里动态 `Regex::new(&pattern_str)`。
- 使用 `Lazy<Mutex<HashMap<String, Regex>>>` 做 marker regex cache，违反当前仓库 Rust 规范里“除 token_counter 外不使用 Mutex”的要求。
- 文件里 `chars_before`、`chars_after`、`truncate_to_chars` 是未使用 helper，造成 build warning 和 clippy dead code。
- SPEC 测试里 3 个 Layer 2 真实需求被 `#[ignore]` 标记为未实现。

这块不只是 lint 问题，而是实现保真度不足。AGENTS 规则要求 Python 逻辑默认 1:1 port，不能用硬编码/简化路径替代。

### P3-2 大文件和 allow 抑制需要拆分

位置：

- `fnm-phase2/src/endnote_chapter_explorer/mod.rs`
- `fnm-phase2/src/endnote_regions_raw.rs:67`

`endnote_chapter_explorer/mod.rs` 约 1331 行，远超仓库规则里 `mod.rs` 不超过 400 行的拆分线。当前文件混合了标题解析、TOC subentry、page signal、region split、fallback、测试 fixture。

`endnote_regions_raw.rs` 使用 `#[allow(clippy::too_many_arguments)]`，这类 allow 不应作为长期结构。可以抽上下文 struct 代替多参数传递。

### P3-3 endnote candidate 对 `page_role == note` 的条件过宽

位置：

- `fnm-phase2/src/note_regions/endnote_candidate.rs:49`
- `fnm-phase2/src/note_regions/endnote_candidate.rs:54`
- `fnm-phase2/src/note_regions/endnote_candidate.rs:68`
- `fnm-phase2/src/note_regions/endnote_candidate.rs:71`

`page_role == "note"` 时，只要 `note_scan.items` 非空或 `page_kind` 非空就返回 true，没有要求 `items.kind == endnote` 或 `page_kind` 是 endnote/mixed。纯 footnote note page 可能被送进 endnote region 构建，再靠后续 guard 排除。

修复方向：

- `page_role == note` 分支也应正向验证 endnote heading、endnote items、或 endnote page_kind。

### P3-4 post-body fnBlocks 重分类有过早返回

位置：

- `fnm-phase2/src/note_regions/post_body_promote.rs:82`
- `fnm-phase2/src/note_regions/post_body_promote.rs:89`
- `fnm-phase2/src/note_regions/post_body_promote.rs:96`
- `fnm-phase2/src/note_regions/post_body_promote.rs:98`

`reclassify_post_body_fnblocks()` 一开始要求全书已有任意 `page_role == "note"`：

```rust
if !page_role_by_no.values().any(|v| v == "note") {
    return reclassified_pages;
}
```

如果 Phase 1 没把 post-body note-like pages 标成 note，这个函数不会尝试用 fnBlocks 连续编号证据重分类。另一个风险是 `post_body_titles.contains(&ch.title.to_lowercase())` 只做 lowercase，没有复用统一 title key，容易与上游传入的 normalized title 集合不一致。

## 门禁验证

已执行：

```bash
cargo build --release -p fnm-phase2
cargo test -p fnm-phase2
cargo fmt --check -p fnm-phase2
cargo clippy -p fnm-phase2 --all-targets -- -D warnings
```

结果：

- `cargo build --release -p fnm-phase2`：通过，但有 4 个 warning。
- `cargo test -p fnm-phase2`：通过。
  - lib tests：143 passed，1 ignored。
  - `audit_note_items_against_golden`：1 passed。
  - `biopolitics_phase2_parity`：6 passed。
  - `test_phase2_spec`：12 passed，3 ignored。
- `cargo fmt --check -p fnm-phase2`：失败。
  - `src/endnote_chapter_explorer/mod.rs:464`
  - `src/sup_recovery/layer2.rs:225`
  - `tests/audit_note_items_against_golden.rs:136`
- `cargo clippy -p fnm-phase2 --all-targets -- -D warnings`：失败。
  - 直接运行会先被 `fnm-core` / `fnm-phase1` 的已知 lint 阻断。
  - 放宽前两个 crate 已知 lint 后，`fnm-phase2` 本体仍有 10 个错误：
    - `note_items/marker_parse.rs:56` unused static。
    - `sup_recovery/layer2.rs:54` unused `chars_before`。
    - `sup_recovery/layer2.rs:70` unused `chars_after`。
    - `sup_recovery/layer2.rs:84` unused `truncate_to_chars`。
    - `chapter_split/structure_model.rs:30` derivable impl。
    - `endnote_chapter_explorer/mod.rs:291` manual find。
    - `endnote_repair/mod.rs:227` manual range contains。
    - `note_items/page_text.rs:8` doc lazy continuation。
    - `sup_recovery/layer2.rs:59` explicit counter loop。
    - `visual_anchor_recovery/parsing.rs:140` collapsible str replace。

## 建议修复顺序

1. 先修 `note_items` 的三个事实污染点：footnote 去重、年份修复分组、续行合并排序。
2. 再修 `chapter_split` 的 `ChapterNoteModeRecord` 字段来源，避免从 `note_mode` 反推事实。
3. 删除或合并旧 explorer / 旧 visual recovery public path，保证每个功能只有一个数据流入口。
4. 重写 `sup_recovery/layer2`，通过被 ignore 的 3 个 SPEC 测试后再接入真实输出。
5. 最后处理 fmt/clippy 和大文件拆分。

## 边缘情况清单

- 连续两页脚注都从 `1` 开始。
- 同一章同时有 footnote 和 endnote。
- book-scope endnote region 被 rebind 到多个 chapter。
- TOC 印刷页号与 raw `book_page` 不一致。
- post-body note pages 没被 Phase 1 标成 `note`。
- 同 marker 在多个 chapter 重复出现。
- 年份 marker 出现在 region 边界附近。

