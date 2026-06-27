# fnm-phase5 审计记录

审计时间：2026-05-22

审计范围：

- `fnm-phase5/src/lib.rs`
- `fnm-phase5/src/convert.rs`
- `fnm-phase5/src/marker_rewrite.rs`
- `fnm-phase5/src/diagnostics.rs`
- `fnm-phase5/src/phase5_shadow.rs`

## 结论

`fnm-phase5` 目前不是一个只负责“章节 Markdown 合并”的独立 phase。它会重建 Phase1/Phase2 的章节与 note mode 事实，又反向调用 Phase6 的 export contract 生成章节内容，再执行一套本地 marker rewrite。这样会让 Phase5/Phase6 职责倒挂，也让同一类引用重写存在两条路径。

从质量看，当前 crate 能 build、fmt、test；在放宽前序 crate 已知 lint 后，本体 clippy 也能通过。但测试基本是 hand-crafted unit tests，没有真实 fixture / Python parity，覆盖不到最关键的跨 phase 数据合同。

## P1：必须优先修复

### 1. Phase5 反向依赖 Phase6 export，phase 职责倒挂

位置：`src/lib.rs`

`build_chapter_markdown_set()` 先构造 `Phase5Structure`，然后调用：

```rust
fnm_phase6::export::contract::build_export_chapters(...)
```

也就是说 Phase5 的章节 Markdown 不是自己基于 Phase4 输出合并出来，而是借 Phase6 export 逻辑生成。随后它又调用 `marker_rewrite::rewrite_chapters_for_merge()` 做二次重写。

问题：

- Phase5/Phase6 的职责边界被打穿。
- Phase6 export 逻辑变成 Phase5 的内部实现细节。
- 后续 Phase6 再 audit/export 时，已经消费过一轮自己的 export contract，问题定位会变得困难。

建议：

- Phase5 自己只做 body text + note definitions 的合并。
- Phase6 只消费 Phase5 的章节 Markdown，不参与 Phase5 生成。
- 把 `build_export_chapters()` 中属于 Phase5 的合并逻辑下沉到 Phase5，Phase6 保留整书组装和最终审计。

### 2. raw marker rewrite 名义存在，实际没有消费 marker 序列

位置：`src/marker_rewrite.rs`

`rewrite_residual_raw_markers_for_chapter()` 的签名包含 `_marker_note_sequences`，但参数被忽略：

```rust
_marker_note_sequences: &HashMap<String, Vec<String>>,
```

函数内部实际只 token 化 legacy `[EN-*]`，再调用 `replace_note_refs_with_local_labels()` 处理已有 token。它没有使用 Phase2/Phase3 的 marker sequence，也不会根据 `chapter_layers.note_items` 去重写正文残留的 `[1]`、Unicode superscript、HTML sup 等 raw marker。

问题：

- 函数名承诺“rewrite residual raw markers”，但没有处理核心 raw marker。
- `_marker_note_sequences` 是关键参数，被静默忽略，违反当前 Rust 重构规范。
- 测试没有覆盖“raw marker 应按 sequence 重写”的真实场景。

建议：

- 要么删除这条名义修复路径，让 raw marker leak 作为 blocker 暴露。
- 要么按 Phase3 matched links / Phase4 frozen refs 的权威坐标做重写，不在 Phase5 重新猜。

### 3. Phase5 重新推断 chapter note mode，违反分类源头唯一

位置：`src/convert.rs`

`effective_note_mode_from_layer()` 根据 `ChapterLayer` 聚合状态重新判断：

- 有 `endnote_items` 就返回 endnote 模式。
- 否则有 `footnote_items` 就返回 footnote 模式。
- 否则 `no_notes`。

同章同时存在 footnote 和 endnote 时，footnote 会被聚合结果覆盖为 endnote 主导。Phase5 又用这个结果构造新的 `ChapterNoteModeRecord`。

问题：

- Phase2 是 `note_kind` 和 `chapter_note_mode` 的唯一分类来源；Phase5 不应重新推断。
- 这是典型的“把章级聚合属性广播给章内实体”的风险。
- 混合注释章节会被错误摘要，后续 export/audit 的判断会偏离上游事实。

建议：

- Phase5 输入应显式携带 Phase2 的 `ChapterNoteModeRecord`。
- `ChapterLayer` 只能作为 note item 容器，不应被 Phase5 用来重建分类事实。

### 4. Phase5 重新计算章节边界，并把 note 页扩入章节

位置：`src/convert.rs`

`chapter_pages_from_layer()` 会把 body pages、footnote item pages、endnote item pages、endnote region pages 都合进 `ChapterRecord.pages`。`to_chapter_records()` 再用这些 pages 重新计算 `start_page/end_page`，并把 source 固定为 `ChapterSource::Fallback`、boundary 固定为 `Ready`。

问题：

- Phase1 已经决定章节边界，Phase5 不应重算。
- book-scope endnote 页可能把章节边界拉到全书尾注区。
- Phase1 的 source/boundary evidence 被丢弃，全部变成 fallback ready。

建议：

- Phase5 直接消费 Phase1/Phase4 传入的章节记录。
- note region 页只用于合并定义，不应改变章节正文边界。

### 5. merge gate 结果只写 summary，缺少硬 blocker

位置：`src/lib.rs`、`src/diagnostics.rs`

`build_chapter_markdown_set()` 计算了：

- `local_refs_closed`
- `no_frozen_ref_leak`
- `no_raw_marker_leak_in_body`

但这些只进入 `merge_summary`，没有形成结构化 blocking status。`_chapter_files_emitted` 被计算后也没有进入 summary 或 blocker。

`build_chapter_issue_diagnostics()` 在缺少 chapter contract row 时默认 missing/orphan 为 0，相当于把缺失 contract 的章节报成 clean。

问题：

- Phase5 blocker 如 `merge_local_refs_unclosed`、`merge_frozen_ref_leak` 没有可靠落地。
- 章节文件缺失、contract 缺失都可能被 summary 掩盖。
- 后续 Phase6 只能看到已经合成后的结果，定位会滞后。

建议：

- Phase5 输出增加明确 `status/blocking_reasons`。
- contract row 缺失应作为 blocking issue，而不是 clean fallback。
- `_chapter_files_emitted` 应纳入 summary 并与 expected chapter count 对齐。

## P2：需要修复的质量问题

### 1. marker rewrite 丢失 note_kind

位置：`src/marker_rewrite.rs`

`rewrite_residual_raw_markers_for_chapter()` 调用 `replace_note_refs_with_local_labels()` 时传入空的 `note_kind_by_id`：

```rust
&HashMap::new()
```

这会让 core 层无法知道 note id 对应 footnote 还是 endnote。Phase5 不应在合并阶段丢掉 Phase2 的 `note_kind` 事实。

### 2. raw marker leak 检测依赖已有 local refs

位置：`src/marker_rewrite.rs`

`has_raw_marker_in_body()` 先从现有 refs/defs 收集 allowed markers；如果集合为空就直接返回 `false`。这意味着某章如果没有任何 local refs/defs，即使正文残留 `[1]` 或 superscript，也不会被标记为 raw marker leak。

建议改成基于 Phase2 note item marker / Phase3 anchor marker 的正向集合，而不是基于已合并 Markdown 反推。

### 3. book-level note text fallback 可能跨章取定义

位置：`src/marker_rewrite.rs`

`rewrite_residual_raw_markers_for_chapter()` 会把 `book_note_text_by_id` 作为 fallback 合入当前章。若 note id 或 alias 在异常数据中重复，Phase5 有机会跨章拿到不属于当前章的 note text。

Phase5 应以 matched link / note item owner 为边界，不应做全书兜底式定义查找。

### 4. `apply_notes_block_format()` 改写定义正文格式

位置：`src/lib.rs`

该函数把：

```markdown
[^1]: text
```

重写为：

```markdown
[^1]: 1. text
```

这是内容级格式变换，不只是合并。它会让最终 definition text 与 Phase2 note text 不再 1:1。若这是目标格式，需要在 contract 中明确；否则应避免在 Phase5 增加文本内容。

### 5. `unlinked_note_ids` 依赖字符串状态并有覆盖风险

位置：`src/lib.rs`

`unlinked_note_ids` 通过字符串判断 `link.status.as_str()`，而不是 typed enum。并且同一 note 若先因 frozen ref decision `skipped` 加入，再因 effective link `matched` 被移除，可能隐藏“matched 但未注入/被跳过”的问题。

建议使用结构化状态，并区分：

- link matched
- freeze injected
- freeze skipped
- merge emitted

## P3：工程质量问题

### 1. 文件偏大，职责可拆

当前行数：

- `marker_rewrite.rs`：604 行
- `convert.rs`：522 行
- `lib.rs`：202 行
- `diagnostics.rs`：182 行
- `phase5_shadow.rs`：155 行

`marker_rewrite.rs` 同时包含 ref/def 提取、raw marker 检测、legacy token rewrite、note text sanitize、definitions 补齐等职责，建议拆成独立模块。

### 2. 缺少真实 fixture / parity 测试

当前 `fnm-phase5` 没有 `tests/` 目录，只有 crate 内 hand-crafted unit tests。它们能验证局部函数，但覆盖不到：

- 真实 Phase4 frozen units 输入。
- 混合 footnote/endnote 章节。
- book-scope endnote 页不应影响章节边界。
- raw marker leak 与 merge blockers。
- Python parity。

建议补：

- `build_chapter_markdown_set()` 的真实 fixture 测试。
- 与 Python Phase5 输出的 byte-equal parity fixture。
- mixed notes 章节 fixture。
- raw marker leak blocker fixture。

## 验证记录

在 `/Users/hao/OCRandTranslation/fnm_re_rs` 执行：

```bash
cargo build --release -p fnm-phase5
cargo fmt --check -p fnm-phase5
cargo test -p fnm-phase5
cargo clippy -p fnm-phase5 --all-targets -- -D warnings
```

结果：

- `cargo build --release -p fnm-phase5`：通过，但继承 `fnm-phase2` 的 4 个 warning。
- `cargo fmt --check -p fnm-phase5`：通过。
- `cargo test -p fnm-phase5`：通过，44 个测试，0 ignored。
- `cargo clippy -p fnm-phase5 --all-targets -- -D warnings`：被前序 `fnm-core` 已知 clippy 错误阻断。
- 放宽前序 crate 已知 lint 后，`fnm-phase5` 本体 clippy 通过。

## 建议修复顺序

1. 切断 Phase5 对 Phase6 export contract 的反向依赖。
2. Phase5 输入改为透传 Phase1/Phase2/Phase4 权威事实，不再重建章节边界和 note mode。
3. 删除或重做 `rewrite_residual_raw_markers_for_chapter()`，避免静默忽略 marker sequence。
4. 增加 Phase5 `status/blocking_reasons`，把 merge blocker 结构化落地。
5. 补真实 fixture / Python parity 测试，再拆分 `marker_rewrite.rs` 和 `convert.rs`。
