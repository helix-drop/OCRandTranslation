# fnm-phase4 审计记录

审计对象：`fnm-phase4`
审计日期：2026-05-22
审计范围：`src/`、`tests/`、workspace 构建/格式/测试/lint 状态。

## 结论

`fnm-phase4` 的主要问题不是单点算法，而是职责边界不闭合：`ref_freeze` 已经生成冻结引用和冻结单元，但后续 `units` 又从 raw pages 重新构造 body text 并用另一套更简化的注入逻辑生成 translation units。这样会让 Phase4 出现两份不一致的“正文+引用”结果。

更严重的是，matched link 无法注入正文时，当前实现主要记录 summary 或清理 marker，没有形成 `freeze_matched_ref_not_injected` 这类硬 blocker。按照 FNM pipeline 职责，Phase4 不能静默跳过 matched link，也不能把未注入的引用从正文里删掉后继续向后交付。

## P1：必须优先修复

### P1-1 顶层 Phase4 会丢失 note translation units

位置：
- `fnm-phase4/src/lib.rs`
- `fnm-phase4/src/units/mod.rs`

`build_phase4_structure()` 先调用 `ref_freeze::build_frozen_units()`，再通过 `build_phase4_structure_for_units()` 把 frozen units 转回 `Phase4Structure`，最后调用 `units::build_translation_units()`。

问题是 `build_phase4_structure_for_units()` 把 `frozen_units.note_units` 映射成 `NoteItemRecord` 时只填了：

- `note_item_id`
- `chapter_id`
- `page_no`
- `text`
- `..Default::default()`

它没有保留 `region_id`、`marker`、`note_kind`、`source_page_label` 等 Phase2/Phase3 事实。而 `units::build_translation_units()` 生成 note units 时依赖 `note_region_by_id.get(&item.region_id)` 来推断 `note_kind`。结果是：从顶层 Phase4 入口进来时，这些 note items 的 `region_id` 为空，note units 会被跳过。

影响：
- 顶层 `build_phase4_structure()` 的 `translation_units` 可能只剩 body units。
- 直接调用 `build_translation_units()` 的测试不覆盖这个问题，因为测试传入的是完整 `note_items`/`note_regions`。
- Phase5 如果消费 `translation_units`，会在结构上缺少注释翻译单元。

修复方向：
- 不要把 `FrozenUnit` lossy 转回 `NoteItemRecord`。
- `translation_units` 应直接消费 `frozen_units`，或让 `FrozenUnit` 携带完整 note metadata。
- 如果必须重建 `Phase4Structure`，必须保留 `region_id`、`marker`、`note_kind` 和 owner 信息。

### P1-2 matched link 注入失败没有形成硬 blocker

位置：
- `fnm-phase4/src/ref_freeze/mod.rs`
- `fnm-phase4/src/reviews.rs`

`ref_freeze` 会统计 skipped links，并在末尾计算 `_hard` / `_soft`：

- `freeze.closed_without_error`
- `freeze.unit_contract_valid`
- `freeze.ceiling_skip_count`
- `freeze.policy_skip_count`

但这些 gate 结果只停留在局部变量，没有进入 `Phase4Output`、`structure_reviews` 或持久化产品。`token_not_found`、`synthetic_anchor` 等 matched link 无法注入正文的情况被归到 summary/warning，而不是形成 `freeze_matched_ref_not_injected` blocker。

影响：
- Phase4 可能把“matched 但未注入”的引用交给下游。
- Phase5/Phase6 只能看到缺引用后的正文，无法判断这是 Phase4 注入失败。
- 违反 Phase4 职责：matched link 无法注入应报 blocker，而不是静默跳过。

修复方向：
- 将 freeze skip 明细纳入 `structure_reviews` 或单独的 Phase4 blocker 列表。
- `token_not_found`、`synthetic_anchor`、`missing_anchor` 等 matched link 注入失败必须能阻断交付。
- `freeze_summary` 只能作为诊断信息，不能替代 gate。

### P1-3 Phase4 有两套正文引用注入路径，结果可能分叉

位置：
- `fnm-phase4/src/lib.rs`
- `fnm-phase4/src/ref_freeze/mod.rs`
- `fnm-phase4/src/units/mod.rs`
- `fnm-phase4/src/units/ref_inject.rs`

当前路径：

1. `ref_freeze::build_frozen_units()` 基于 `chapter_layers`、anchors、links 生成 `frozen_units.body_units`、`frozen_refs`、`ref_map`。
2. `units::build_translation_units()` 又从 raw pages 重新提取 body pages，并调用 `units/ref_inject.rs` 的 `materialize_refs_for_chapter()` 再注入一遍引用。

这两条路径的注入能力不同。`ref_freeze/inject.rs` 有较完整的 marker 候选处理，而 `units/ref_inject.rs` 只处理 `source_marker`、`[marker]` 和一个 bracket fallback。它不等价于冻结路径。

影响：
- `frozen_units` 与 `translation_units` 可能不是同一份正文。
- `Phase4Output::to_products()` 只持久化 `translation_units` 和 reviews，`frozen_refs/ref_map` 不落库，后续无法追踪差异。
- 修复一个注入路径不一定修复另一个路径，维护成本会持续上升。

修复方向：
- Phase4 应只保留一条权威引用冻结路径。
- `translation_units` 应由 `frozen_units` 派生，不应重新扫描 raw pages 和重新注入。
- 持久化产品至少应保留 freeze diagnostics 或 ref map，方便 Phase5/Phase6 和审计回溯。

### P1-4 `inject_token_once()` 对 UTF-8 坐标切片可能 panic

位置：
- `fnm-phase4/src/ref_freeze/inject.rs`

`inject_token_once()` 使用 `payload[..ce]`、`payload[cs..]`、`payload[cs..ce]` 直接按 byte offset 切片，只检查 `ce <= payload.len()`，没有检查 `is_char_boundary()`。

如果 anchor 坐标来自 LLM、视觉恢复、override 或其它非 Rust regex byte offset 来源，坐标落在 UTF-8 字符中间时会 panic。

影响：
- 含中文、法文重音、希腊字母等正文时，错误坐标可能直接崩溃 Phase4。
- 这个问题会在 repair/override 接入后更明显。

修复方向：
- 所有外部坐标进入切片前必须验证 `payload.is_char_boundary(start/end)`。
- 非边界坐标应返回结构化 skip/blocker，而不是 panic。
- 明确记录坐标单位：byte offset 还是 char offset。

## P2：重要质量问题

### P2-1 note owner 解析忽略 `owner_chapter_id`

位置：
- `fnm-phase4/src/ref_freeze/inject.rs`

`resolve_note_item_owner()` 只看 `item.chapter_id` 和 `region.chapter_id`，没有使用 `NoteItemRecord.owner_chapter_id`。Phase2/Phase3 中 book-scope、projection 或 rebinding 场景会依赖 owner 字段表达真实归属。

影响：
- book-scope endnote 可能被错误归属或无法归属。
- `append_note_unit()` 的 `owner_id` 当前还写成 `region_id`，与 `unit_id` 中的 chapter owner 概念不一致。

修复方向：
- owner 解析优先使用 `owner_chapter_id`，再回退到 `chapter_id` / `region.chapter_id`。
- `FrozenUnit.owner_id` 的语义要统一：如果表示章节归属，就不要写 region id。

### P2-2 skipped matched link 会清理正文 marker

位置：
- `fnm-phase4/src/ref_freeze/mod.rs`
- `fnm-phase4/src/ref_freeze/inject.rs`

`record_skipped()` 在 `ceiling_skip` / `policy_skip` 场景会调用 `clean_skipped_marker()` 修改正文，删除未能注入的 marker。

影响：
- matched link 注入失败后，正文中的原始引用可能被删除。
- 下游看到的是“没有引用”的正文，而不是“引用未注入”的正文，问题更难定位。

修复方向：
- 注入失败时保留原 marker，并记录 blocker/review。
- 只有明确验证为重复锚点或无效噪声时，才允许清理 marker，且必须留下可追踪诊断。

### P2-3 Phase4 持久化产品不包含冻结引用事实

位置：
- `fnm-phase4/src/output.rs`
- `fnm-core/src/db/repository.rs`

`Phase4Output::to_products()` 只返回：

- `translation_units`
- `structure_reviews`

`frozen_units`、`frozen_refs`、`ref_map`、freeze skip 明细都不进入 `Phase4Products`。

影响：
- Phase4 的核心产物无法从 DB 读回。
- Phase5/Phase6 或调试工具不能基于持久化数据复盘引用冻结状态。

修复方向：
- 明确 Phase4 的权威持久化 contract。
- 如果 `translation_units` 是唯一输出，则它必须承载引用冻结状态；否则需要增加 freeze 相关表/字段。

### P2-4 body page 构造逻辑重复实现

位置：
- `fnm-phase4/src/units/body_pages.rs`

`build_structured_body_pages_for_chapter()` 重新根据 raw markdown、`note_start_page`、`next_chapter`、`page_role` 构造 body pages，而 `ref_freeze` 已经从 `chapter_layers.body_pages` 消费正文层。

影响：
- 同一章的 body pages 在 Phase4 内可能有两个来源。
- Phase1/Phase2 边界修复后，不一定同步影响 `units/body_pages.rs` 的本地逻辑。

修复方向：
- 统一使用 `chapter_layers.body_pages` 或 Phase3/Phase4 structure 中的权威正文层。
- 本地 raw page heuristic 只应作为明确标记的 fallback，不能作为常规路径。

### P2-5 reviews 没有纳入 freeze skip 错误

位置：
- `fnm-phase4/src/reviews.rs`

`build_structure_reviews()` 主要消费 Phase3 orphan/ambiguous/uncertain/toc 问题，没有接收 `ref_freeze` 的 skip 明细。因此 Phase4 自己产生的注入失败不会进入 review 队列。

影响：
- review 输出不能代表 Phase4 真实交付质量。
- 用户看到 reviews 通过，不代表引用冻结已经闭合。

修复方向：
- 将 `FrozenRef` 的 skipped/error 状态转换成 structure review。
- 对 matched link 注入失败使用明确 reason，例如 `freeze_matched_ref_not_injected`。

## P3：代码质量与测试缺口

### P3-1 大文件超过拆分标准

超过或接近 400 行的文件：

- `fnm-phase4/src/text/markdown_parse.rs`：1122 行
- `fnm-phase4/src/ref_freeze/mod.rs`：756 行
- `fnm-phase4/src/reviews.rs`：491 行
- `fnm-phase4/src/units/ref_inject.rs`：452 行
- `fnm-phase4/src/units/mod.rs`：423 行

`markdown_parse.rs` 和 `ref_freeze/mod.rs` 已经明显混合了多类职责，应按 parser pass、contract、skip handling、unit assembly 拆分。

### P3-2 动态 regex 和 Mutex cache 违反 Rust 规范

位置：
- `fnm-phase4/src/text/markdown_parse.rs`
- `fnm-phase4/src/ref_freeze/inject.rs`
- `fnm-phase4/src/units/ref_inject.rs`
- `fnm-phase4/src/units/body_pages.rs`

问题：
- `markdown_parse.rs` 多处在循环内 `Regex::new()`，已被 clippy 报出。
- `ref_freeze/inject.rs` 每次按 marker 构造 regex。
- `units/ref_inject.rs` 使用 `Lazy<Mutex<HashMap<String, Regex>>>` 做 regex cache，违反“除 token_counter 外不使用 Mutex”的约束。
- `body_pages.rs` 本地重复定义 note/anchor regex，未复用 `fnm-core::anchor_kind::patterns` 与 note marker 工具。

修复方向：
- 固定模式全部改为模块级 `Lazy<Regex>`。
- marker-specific 情况优先用解析逻辑或小范围无锁缓存，避免全局 Mutex。
- 优先复用 `fnm-core` 已有 patterns。

### P3-3 Phase4 parity 测试没有真正比对 Rust 输出

位置：
- `fnm-phase4/tests/biopolitics_phase4_parity.rs`

这些测试主要 `include_str!` 读取 golden fixture，然后断言 fixture 自身的字段数量和格式。它没有运行 Rust Phase4 pipeline 输出并与 Python golden byte-equal 比对。

影响：
- 顶层 `build_phase4_structure()` 丢 note units 的问题不会被发现。
- `frozen_units` 与 `translation_units` 分叉也不会被发现。

修复方向：
- 增加真实 fixture 输入，运行 Rust Phase4 入口。
- 输出 `frozen_units`、`frozen_refs`、`translation_units` 后与 Python expected JSON byte-equal 或结构等价比对。
- 将“只验证 golden 文件格式”的测试改名，避免伪装成 parity。

### P3-4 当前 fmt/clippy 未达验收标准

验证结果：

- `cargo build --release -p fnm-phase4`：通过，但继承 `fnm-phase2` warning。
- `cargo test -p fnm-phase4`：通过。
- `cargo fmt --check -p fnm-phase4`：失败，`fnm-phase4/src/units/body_pages.rs` 有格式差异。
- `cargo clippy -p fnm-phase4 --all-targets -- -D warnings`：被前序 crate 既有 lint 阻断。
- 放宽前序已知 lint 后，`fnm-phase4` 本体仍有 11 个 clippy 错误，包括循环内 regex、`while_let_loop`、`needless_lifetimes`、`useless_vec`。

## 建议修复顺序

1. 先收敛 Phase4 数据流：`translation_units` 只能从 `frozen_units` 派生。
2. 把 matched link 注入失败升级为 blocker/review，禁止静默清理 marker。
3. 修复 note owner 元数据丢失，保留 `owner_chapter_id`、`note_kind`、`region_id`。
4. 明确 Phase4 持久化 contract，保存足够的 freeze diagnostics。
5. 拆分大文件，清理动态 regex 和 Mutex cache。
6. 补真正运行 Rust 输出的 Biopolitics parity 测试。

