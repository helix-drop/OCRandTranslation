# fnm-phase6 审计记录

审计对象：`fnm-phase6`
审计日期：2026-05-22
审计范围：`src/`、内联测试、workspace 构建/格式/测试/lint 状态。

## 结论

`fnm-phase6` 已覆盖导出、ZIP、导出审计、diagnostics 和 book assemble，单测数量不少。但当前存在几个会直接影响最终交付判断的问题：

- endnote 定义行输出为 `[1]:`，而正文引用和 audit contract 使用 `[^1]` / `[^1]:`，这会让 endnote 章节的本地注释 contract 失真。
- `can_ship` 只看文件审计 blocking issue 数，不看 Phase6 status blocking reasons，也不看 order/raw-marker/semantic gates。
- `build_module_export_bundle()` 生成了 ZIP，却审计 `bundle.files`，没有审计实际 ZIP 字节。
- Phase6 会在导出时做乱码修复和相邻重复段落折叠，可能隐藏 Phase5 或更上游的输出问题。

Phase6 是最终出口，任何“报告能 ship”的判断都必须非常保守。现在的 gate 还不够闭合。

## P1：必须优先修复

### P1-1 endnote 定义格式与正文引用 contract 不一致

位置：
- `fnm-phase6/src/export/section_render.rs`
- `fnm-core/src/export_constants.rs`
- `fnm-core/src/ref_rewriter.rs`

`rewrite_body_text_with_local_refs()` 会把正文引用写成 Obsidian footnote 格式 `[^N]`。`LOCAL_FOOTNOTE_DEF_RE` 和 export audit 也只识别 `[^N]:` 定义行。

但 `section_render::emit_definitions()` 输出 endnote 定义时使用：

```rust
rendered.push(format!("[{number}]: {text}"));
```

少了 caret，应该是 `[^N]:`。

影响：
- 正文中有 `[^1]`，尾注定义却是 `[1]:`。
- `LOCAL_FOOTNOTE_DEF_RE` 不会识别 `[1]:`，contract summary 会把定义数算错。
- export audit 可能把合法 endnote 章节判成 missing definition，或者下游 Obsidian 无法按预期解析尾注。
- 现有测试只覆盖了 footnote 的 `emit_local_note_definitions()`，没有覆盖 endnote `emit_definitions()`。

修复方向：
- endnote 定义统一输出 `[^N]: text`。
- 增加 `build_section_markdown()` 的 endnote fixture：body 包含 `{{NOTE_REF:n1}}`，note unit 是 endnote，最终必须包含 `[^1]` 和 `[^1]:`，contract missing/orphan 都为 0。

### P1-2 `can_ship` gate 只看文件审计，忽略 Phase6 状态和语义 gate

位置：
- `fnm-phase6/src/export_audit/mod.rs`
- `fnm-phase6/src/book_assemble/mod.rs`

`audit_phase6_export()` 最终设置：

```rust
can_ship: blocking_issue_count == 0
```

它没有纳入：

- `phase6.status.blocking_reasons`
- `phase6.status.structure_state`
- `export_semantic_contract_ok`
- `gate_order_follows_toc`
- `gate_no_cross_chapter_contamination`
- `gate_no_raw_marker_leak_book_level`
- missing/extra chapter ids

`build_module_export_bundle()` 虽然计算了这些 gate，并写入 `semantic_summary`，但不会改变 `report_record.can_ship`。

影响：
- TOC 顺序错、章节缺失、raw marker leak 或 status blocking 仍可能得到 `can_ship=true`。
- Phase6 最终 gate 与 summary 分叉，调用方如果只看 audit report 会误判。

修复方向：
- 定义唯一的 Phase6 ship gate：文件 audit + status blocking + semantic gates 全部通过才 `can_ship=true`。
- `semantic_summary` 里的 gate false 必须同步进入 `ExportAuditReportRecord.must_fix_before_next_book` 或 blocking file row。

### P1-3 审计没有检查实际 ZIP 字节

位置：
- `fnm-phase6/src/book_assemble/mod.rs`
- `fnm-phase6/src/export_audit/mod.rs`
- `fnm-phase6/src/export/zip.rs`

`build_module_export_bundle()` 在第 8 步生成 `zip_bytes`，但第 11 步调用：

```rust
audit_phase6_export(&phase6, slug, None)
```

也就是说，audit 使用 `bundle.files`，不是刚生成的 ZIP。另一方面，如果外部调用 `audit_phase6_export(..., Some(zip_bytes))`，`read_zip_markdown_files(bytes).unwrap_or_default()` 会把 ZIP 读取失败静默变成空 markdown 文件集合。

影响：
- ZIP 路径清洗、文件丢失、重复路径、损坏 ZIP 都可能绕过 audit。
- ZIP 读取失败可能变成 `can_ship=true` 的空报告。

修复方向：
- `build_module_export_bundle()` 应传入 `Some(&zip_bytes)` 审计实际交付物。
- `read_zip_markdown_files()` 失败必须生成 blocking issue，不能 `unwrap_or_default()`。
- 审计应比较 `bundle.files` 与 ZIP 中 markdown 文件集合是否一致。

### P1-4 Phase6 审计上下文缺少 note_items，raw marker leak 判断失真

位置：
- `fnm-phase6/src/book_assemble/mod.rs`
- `fnm-phase6/src/export_audit/mod.rs`
- `fnm-phase6/src/export_audit/helpers.rs`

`build_module_export_bundle()` 构造 `Phase6Structure` 时只填了 export bundle、status、summary，其它字段走 `Default::default()`。因此 `phase6.note_items` 为空。

`audit_phase6_export()` 调 `chapter_note_markers_by_section(phase6)` 得不到任何章节 marker 集合，随后 `audit_markdown_file()` 对 `chapter_note_markers` 传入 `None`。

影响：
- raw marker leak 检测无法基于本章真实 note marker 做正向约束。
- `RAW_BRACKET_NOTE_REF_RE` 会把所有 `[N]` 形态都当成潜在 raw note marker，容易误报页码、编号、引用格式。
- 这与“正向验证优于黑名单排除”的原则相反。

修复方向：
- Phase6 audit 必须接收 Phase5/Phase4 的 note item marker 数据。
- 没有 marker 数据时，raw marker leak 检测应降级为 diagnostic，而不是 blocking。
- `build_module_export_bundle()` 不应构造缺字段的 `Phase6Structure` 来执行最终 audit。

## P2：重要质量问题

### P2-1 Phase6 会修补最终导出内容，容易掩盖上游问题

位置：
- `fnm-phase6/src/book_assemble/canonicalize.rs`
- `fnm-phase6/src/book_assemble/garbled_repair.rs`

`apply_semantic_canonicalization()` 会在 Phase6 中执行：

- `repair_garbled_markdown_blocks()`
- `canonicalize_adjacent_duplicate_paragraphs()`

这会改变 Phase5 输出后的最终章节 markdown。

影响：
- Phase6 不只是“组装与审计”，还在修正文档内容。
- 上游 Phase4/5 的乱码或重复段落问题可能被最终导出掩盖。
- 后续 debug 时，DB 中 Phase5 markdown 与 ZIP 内容不再 1:1。

修复方向：
- Phase6 可保留 normalization（换行、路径、ZIP 格式），但内容级修复应前移到 Phase5 或作为 blocker。
- 如果保留，必须把每个改动写入 blocking/diagnostic report，不能只在 summary 里显示 count。

### P2-2 `doc_id` 被忽略，audit report 写成 slug

位置：
- `fnm-phase6/src/book_assemble/mod.rs`
- `fnm-phase6/src/export_audit/mod.rs`

`build_module_export_bundle()` 接收 `_doc_id` 但未使用；`audit_phase6_export()` 构造报告时：

```rust
doc_id: slug.to_string()
```

影响：
- slug 与 doc_id 不同时，审计报告无法绑定真实文档。
- 多书批处理或 DB 回写时容易错链。

修复方向：
- `audit_phase6_export()` 接收 `doc_id`。
- `build_module_export_bundle()` 不应把 doc_id 参数命名为 `_doc_id`。

### P2-3 `export_semantic_contract_ok` 与 audit report 没有闭合

位置：
- `fnm-phase6/src/export/contract.rs`
- `fnm-phase6/src/book_assemble/mod.rs`

`compute_export_semantic_contract()` 会产生：

- `front_matter_leak_detected`
- `toc_residue_detected`
- `mid_paragraph_heading_detected`
- `duplicate_paragraph_detected`
- `export_semantic_contract_ok`

这些字段写入 `ExportBundleRecord` 和 `semantic_summary`，但不直接决定 `ExportAuditReportRecord.can_ship`。

影响：
- 同一个 Phase6 输出可能同时显示 `export_semantic_contract_ok=false` 和 `can_ship=true`。
- 调用方需要知道读哪个字段，contract 不清晰。

修复方向：
- `export_semantic_contract_ok=false` 应转换为 blocking issue。
- 最终报告只保留一个权威 ship 状态。

### P2-4 diagnostics 中 `replace_frozen_refs()` 继续使用 Legacy 模式

位置：
- `fnm-phase6/src/diagnostics.rs`
- `fnm-core/src/refs.rs`

diagnostics 多处调用 `replace_frozen_refs(..., EndnoteMode::Legacy)`。但 `fnm-core` 审计已经指出 `EndnoteMode` 当前没有真实控制输出模式，容易让调用者误以为 diagnostics 能按不同模式处理 endnote。

影响：
- diagnostics 输出和 export 输出可能共享同一个隐藏行为。
- 后续修 `EndnoteMode` 时，Phase6 diagnostics 需要同步验证。

修复方向：
- 等 `fnm-core` 修复 `EndnoteMode` 后，为 diagnostics 增加对应测试。
- 当前文档中标注 diagnostics 依赖 core 行为，不能单独假设 legacy 生效。

## P3：代码质量与测试缺口

### P3-1 大文件超过拆分标准

超过 400 行的文件：

- `fnm-phase6/src/export/tests.rs`：1089 行
- `fnm-phase6/src/export_audit/helpers.rs`：717 行
- `fnm-phase6/src/diagnostics.rs`：630 行
- `fnm-phase6/src/export/footnote.rs`：595 行
- `fnm-phase6/src/export/section_render.rs`：483 行
- `fnm-phase6/src/export_audit/file_audit.rs`：454 行

`export_audit/helpers.rs` 尤其需要按标题检查、note contract、raw marker、重复检测拆分。

### P3-2 `export_audit/helpers.rs` 存在函数内动态 Regex

位置：
- `fnm-phase6/src/export_audit/helpers.rs`

多个 helper 在函数体内直接 `Regex::new(...).unwrap()`，例如：

- `looks_like_running_prose()`
- `looks_like_mid_sentence_opening()`
- `looks_like_missing_tail()`
- `duplicate_paragraph_count()`

这些应全部改为模块级 `Lazy<Regex>`。当前没有循环内大量创建的性能灾难，但违反 Rust 重构规范。

### P3-3 测试主要是 hand-crafted unit tests，没有真实 fixture parity

`fnm-phase6` 没有独立 `tests/` 目录，147 个测试全部来自内联 unit tests。它们能覆盖基础 helper，但没有真实书籍 fixture，也没有 Python expected JSON byte-equal parity。

当前缺口：

- endnote 完整章节导出没有测试到 `[^N]:` 定义。
- `build_module_export_bundle()` 没有用真实 Phase5/Phase1 输入跑整包导出。
- audit 没有验证 ZIP 字节与 bundle.files 一致。
- `can_ship` gate 没有 status blocking / semantic gate 测试。

### P3-4 当前 clippy 未达验收标准

验证结果：

- `cargo build --release -p fnm-phase6`：通过，但继承 `fnm-phase2` warning。
- `cargo fmt --check -p fnm-phase6`：通过。
- `cargo test -p fnm-phase6`：通过，147 个测试，0 ignored。
- `cargo clippy -p fnm-phase6 --all-targets -- -D warnings`：先被 `fnm-core` 既有 lint 阻断。
- 放宽前序已知 lint 后，`fnm-phase6` 本体仍有 3 个 clippy 错误，均为测试中的 `field_reassign_with_default`。

## 建议修复顺序

1. 先修 endnote 定义格式，并补 endnote 章节导出 contract 测试。
2. 重做 Phase6 `can_ship`：文件 audit、status blocking、semantic gates、ZIP audit 全部纳入。
3. 让 build path 审计实际 ZIP 字节，ZIP 读取失败必须 blocking。
4. 给 audit 传入真实 note marker 数据，避免 raw marker leak 误报。
5. 将 garbled/duplicate 内容修复前移或改为 blocker，不在 Phase6 静默改正文。
6. 拆分大文件，迁移动态 regex 到 `Lazy<Regex>`。

