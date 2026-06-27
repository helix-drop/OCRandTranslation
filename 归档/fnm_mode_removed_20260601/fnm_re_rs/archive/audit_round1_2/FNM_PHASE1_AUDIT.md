# FNM Phase1 Crate Audit

审计对象：`fnm-phase1`

审计时间：2026-05-22

## 结论

`fnm-phase1` 已经有较完整的模块拆分和 Biopolitics parity 覆盖，核心流程能跑通；但当前质量门禁没有通过，且存在一个会让 TOC semantics 诊断被顶层静默忽略的 P1 问题。整体风格上仍有多处“为了兼容而保留但未接线”的中间结构、过宽默认值和重复防御逻辑，后续修复应优先删除无效兜底或把它们接回真实数据流。

## P1 阻断问题

### P1-1 `toc_structure` 读取了不存在的 `toc_semantic_meta`，导致语义 gate 默认放行

位置：
- `fnm-phase1/src/toc_structure.rs:217`
- `fnm-phase1/src/toc_structure.rs:326`
- `fnm-phase1/src/toc_structure.rs:371`
- `fnm-phase1/src/toc_structure.rs:379`
- `fnm-phase1/src/chapter_skeleton/builder.rs:526`

`build_chapter_skeleton()` 产出的 diagnostics 是顶层字段：

- `toc_semantic_contract_ok`
- `chapter_title_alignment_ok`
- `visual_toc_conflict_count`
- `normalized_toc_rows`
- `container_titles` / `post_body_titles` / `back_matter_titles`

但 `build_phase1_structure()` 统一从 `skeleton.diagnostics["toc_semantic_meta"]` 读取。该 key 在当前 builder 输出里不存在，所以：

- `build_toc_tree()` 收到空 meta，TOC role/tree 会丢掉 sanitize 后的语义上下文。
- `toc_semantic_contract_ok` 缺失后 `unwrap_or(true)`，硬 gate 默认通过。
- `chapter_titles_aligned` 缺失后 `unwrap_or(true)`，标题错配默认通过。
- `visual_toc_conflict_count` 缺失后 `unwrap_or(0)`，冲突告警默认清零。

这违反“上游事实不可被下游重新解释/默认吞掉”的原则。修复方向：`toc_structure` 应直接读取 `skeleton.diagnostics` 顶层字段，或 builder 明确包一层 `toc_semantic_meta`，但二者只能保留一个契约。

## P2 行为与质量问题

### P2-1 `pages_classified` 把合法 `noise` 页当作未分类

位置：`fnm-phase1/src/toc_structure.rs:322`

`PageRole::Noise` 已被 page partition 使用，Biopolitics parity 里也有 3 个 noise 页；但 hard gate 判定 `unknown | noise` 都是未分类。这会让正常的 archive/title blank noise 页触发 `toc.pages_classified=false`。如果 Phase1 合法 role 里不允许 noise，应在 page partition 阶段转成 front/back/other；如果允许 noise，gate 不应把它等同 unknown。

### P2-2 手工 page override 只应用 `page_role`，忽略 `section_hint` 和 `reason`

位置：
- `fnm-phase1/src/input.rs:18`
- `fnm-phase1/src/page_partition/mod.rs:162`

`ManualPageOverride` 定义了 `page_role`、`section_hint`、`reason`，但 `apply_manual_overrides()` 只改 role，并把 reason 固定为 `"manual_override"`。这会让 review 工具产生的精确信息丢失，后续审计也无法判断人工修正原因。修复时应完整应用三个字段；如果 `section_hint/reason` 不再支持，就从输入结构移除，避免假能力。

### P2-3 `book_note_type` 的 `_overrides` 参数完全未使用

位置：`fnm-phase1/src/book_note_type/mod.rs:166`

函数签名保留 `_overrides`，但没有任何行为。这个模块虽然当前不在 Phase1 主入口里决定 note_kind，但会作为 LLM book-type verify 的 prior；忽略 overrides 会让人工修正无法影响书型验证。建议改为显式支持，或删除参数并更新调用契约。

### P2-4 `page_resolve` 复制了简化版 page role heuristic，容易与主判定分叉

位置：`fnm-phase1/src/chapter_skeleton/toc_semantics/page_resolve.rs:31`

`trim_exportable_chapter_pages()` 内部重新实现了 `looks_like_prose_after_heading`、copyright、course listing、title page 判定，且比 `page_partition::role_heuristics` 简化很多。这属于重复防御逻辑：同一页在 page partition 和 TOC trim 中可能被两套规则不同解释。应复用主 heuristic 或把“是否可作为 chapter 起始页”抽成单一 API。

### P2-5 未接线/无效中间结构仍保留在主流程

位置：
- `fnm-phase1/src/page_partition/mod.rs:152`
- `fnm-phase1/src/page_partition/mod.rs:156`
- `fnm-phase1/src/section_heads.rs:75`
- `fnm-phase1/src/chapter_skeleton/toc_semantics/mod.rs:171`
- `fnm-phase1/src/chapter_skeleton/toc_semantics/mod.rs:480`

这些代码要么构造后完全不用，要么字段永远返回空：

- `_synthetic = build_synthetic_page_by_no(...)` 构建后丢弃。
- `PagePartitionResult.pre_extracted_page_candidates` 恒为 `vec![]`。
- `_chapter_title_key_map` 构造后未使用。
- `_missing` 和 `_page_row_by_no` 只做了无效收集。

这类代码会制造“已有 fallback/缓存/诊断”的假象。建议删除；如果确实需要，必须接入实际调用点并加测试。

### P2-6 `page_roles` 分支重复，且 `other` 默认映射成 front matter 过宽

位置：`fnm-phase1/src/page_roles.rs:78`

该函数把多个不同条件都映射为相同结果，clippy 也报 `if_same_then_else`。更重要的是，所有非章节内的 `source_role == "other"` 都会先映射成 `front_matter`，只有满足 rear hint 的才会是 `back_matter`。这把“other”这个不确定分区广播成 front matter，语义过宽。建议先拆成明确 dispatch：note、chapter、back_matter、front_matter、other，并把 reason/page window 作为 front/back 的正向证据。

### P2-7 LLM book-type verify 仍用近似 endnote region

位置：`fnm-phase1/src/llm_book_type_verify/selection.rs:111`

注释说明 Rust 端没有独立 `endnote_regions`，于是用 `chapter_endnote_primary` 章末 3 页近似。这会影响 LLM 抽样页面，尤其是长章、书末统一尾注或 note region 不在最后 3 页的书。既然这是验证模块，输入应来自 Phase2 的真实 `NoteRegion` / `ChapterNoteMode`，不能在 Phase1 用章节边界猜 region。

### P2-8 质量门禁未通过

验证命令：

- `cargo fmt --check -p fnm-phase1` 失败，主要在 `chapter_skeleton/builder.rs` 和 `chapter_skeleton/fallback.rs`。
- `cargo clippy -p fnm-phase1 --all-targets -- -D warnings` 被 `fnm-core` 已有 clippy 错误阻断。
- 放宽已知 `fnm-core` lint 后，`fnm-phase1` 本体仍有 11 个 clippy 错误，集中在：
  - `chapter_skeleton/fallback.rs:801` needless borrow
  - `chapter_skeleton/fallback.rs:802` manual contains
  - `llm_book_type_verify/selection.rs:249` manual clamp
  - `page_roles.rs:82` map clone
  - `page_roles.rs:87` / `94` / `96` 重复分支
  - `page_roles.rs:113` unnecessary sort_by
  - `toc_structure.rs:95` redundant closure
  - `toc_tree.rs:138` map clone
  - `toc_tree.rs:224` collapsible if

## P3 风格问题

### P3-1 `role_heuristics.rs` 过重并用 crate-level `allow(dead_code)`

位置：`fnm-phase1/src/page_partition/role_heuristics.rs:2`

该文件 700+ 行，聚合大量正则、文本工具和具体判定，并以 `#![allow(dead_code)]` 覆盖整模块。当前很多函数确实只服务个别规则或未来路径，但整模块 allow 会隐藏真实死代码。建议按 page role 类型拆文件，并删除 crate-level allow。

### P3-2 `RuleMatch::no_match()` 携带 `PageRole::Body`

位置：`fnm-phase1/src/page_partition/rules/mod.rs:36`

`matched=false` 时仍携带 `role=Body`，现在调用方正确检查 `matched`，但结构本身容易被误用。更清晰的表达是 `Option<RuleMatch>`，或拆成 `RuleOutcome::{Matched, NoMatch}`。

### P3-3 每页 role resolve 都重新分配规则 Vec

位置：`fnm-phase1/src/page_partition/rules/mod.rs:58`

`all_rules()` 每次返回新 `Vec`。`resolve_page_role()` 每页调用，会重复分配。建议改为静态 slice/const array。

## 验证结果

通过：

- `cargo build --release -p fnm-phase1`
- `cargo test -p fnm-phase1`：118 个 lib 测试 + 4 个 Biopolitics parity + 12 个 spec 测试通过。
- `cargo test -p fnm-phase1 --test test_biopolitics_parity -- --nocapture`：4 个测试通过；Biopolitics chapters 12/12 byte-equal，page role agreement 358/370。

未通过：

- `cargo fmt --check -p fnm-phase1`
- `cargo clippy -p fnm-phase1 --all-targets -- -D warnings`

## 建议修复顺序

1. 修 `toc_semantic_meta` 契约错位，并补一个 regression test：构造 `visual_toc_conflict_count > 0` 或 `toc_semantic_contract_ok=false`，断言 gate 不会默认通过。
2. 明确 `noise` 是否是合法分类；同步调整 `pages_classified` 或 page partition 输出。
3. 删除未接线中间结构：`_synthetic`、`pre_extracted_page_candidates`、`_chapter_title_key_map`、`_missing`、`_page_row_by_no`。
4. 合并 `page_roles` 重复分支，收窄 `other -> front_matter` 的默认映射。
5. 复用 `page_partition::role_heuristics`，移除 `page_resolve` 的简化重复判定。
6. 跑通 fmt/clippy，并删除 `#![allow(dead_code)]` 级别的抑制。
