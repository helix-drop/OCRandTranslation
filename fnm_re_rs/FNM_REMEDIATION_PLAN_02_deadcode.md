# 批次 2 详细计划 — 死代码清理

> 隶属 `FNM_REMEDIATION_PLAN_00_MASTER.md` 批次 B2。建议在批次 3（LLM 接入）**之前**做。
> 性质：删除 / 私有化，零行为变更。分支 `chore/b2-deadcode`。
> 验证主轴：删后 `cargo build --workspace` + `cargo test --workspace` + `cargo clippy --workspace --all-targets`（**0 warning**）。若删除触发新的 `dead_code` 警告，说明有连带未清，继续清。

---

## ⚠ 关键边界（务必先读）

**以下「未接入子系统」不是死代码，禁止在本批次删除——它们是批次 3 的 LLM 接入对象：**
- `fnm-phase1/src/llm_book_type_verify/*`、`fnm-phase1/src/book_note_type/mod.rs`
- `fnm-phase2/src/visual_anchor_recovery/*`、`fnm-phase2/src/llm_bare_digit_verify/*`
- `fnm-phase3/src/body_anchors/context_guard.rs` 的 `llm_candidates` 相关路径

本批次只清「无任何接入意图、纯无效计算/无引用」的代码。

---

## 1. 明确死代码（直接删）

> 来源均为 `FNM_AUDIT2_REMEDIATION.md` §2（双轮一致）。删除后该处逻辑无行为变化（本就是无效计算/无引用）。

### B2-1　「构建后丢弃」无效计算（6 处）
| 位置 | 删除内容 |
|---|---|
| `fnm-phase1/src/page_partition/mod.rs:153` | `let _synthetic = build_synthetic_page_by_no(&page_info_cache);` —— **连同 `build_synthetic_page_by_no` 函数整体删除**（~40 行，无其他调用者；删后确认 import 清理） |
| `fnm-phase1/src/section_heads.rs:75` | `let _chapter_title_key_map = chapter_title_keys(...);` —— 若 `chapter_title_keys` 无其他调用者一并删 |
| `fnm-phase1/src/chapter_skeleton/toc_semantics/mod.rs:171` | `let _missing: Vec<String> = ...;`（整段收集删除） |
| `fnm-phase1/src/chapter_skeleton/toc_semantics/mod.rs:480` | `let _page_row_by_no: HashMap = ...;` |
| `fnm-phase3/src/paragraph_footnotes.rs:195` | `let _anchor_matched_count = ...;`（A 档 crate，仅此一处，谨慎确认无副作用后删） |
| `fnm-orchestrator/src/page_translate/apply.rs:17` | `let _section_title = ...;`（确认后续真未用） |

**做法**：删变量绑定 + 其唯一服务的函数/中间结构；`cargo build` 若报某 helper 变 unused 一并删。
**验证**：build + test 通过；clippy 无新增 unused。

### B2-2　死 regex（`_` 前缀、定义未用，3 处）
- `fnm-phase1/src/heading_graph/title_key.rs:11` `_TRAILING_NOTE_MARKER_RE`
- `fnm-phase1/src/chapter_skeleton/toc_semantics/title_utils.rs:102` `_CHAPTER_KEYWORD_RE`
- `fnm-phase1/src/chapter_skeleton/toc_semantics/title_utils.rs:149` `_YEAR_RANGE_RE`
**做法**：直接删 `static _XXX: Lazy<Regex>` 定义。**验证**：build/clippy 通过。

### B2-3　`#[allow(dead_code)]` 掩盖项（fallback.rs，3 处）
位置：`fnm-phase1/src/chapter_skeleton/fallback.rs:85,222,665`。
- `:665` `merge_section_heads` —— pub 但无生产/测试调用者：**删函数 + 删 `#[allow]`**。
- `:85` `SectionRow` / `:222` `ClassifiedSection` 的未读字段：**删未读字段**（先 `cargo build` 看哪些字段真未读，逐个删）+ 删 `#[allow(dead_code)]`，让 clippy 重新守门。
**验证**：删 `#[allow]` 后 clippy 不得再报 dead_code（报了说明还有未读字段没删干净）。

### B2-4　空操作 if（orchestrator）
位置：`fnm-orchestrator/src/post_translate.rs:155-160`。
```rust
// 整段删除（什么都不做）：
// if repair_result.is_none() && !model_attempts.is_empty() {
//     if let Some(last) = model_attempts.last() { let _ = last; }
// }
```
**验证**：build/test 通过。

### B2-5　其他确认后清理
- `fnm-phase2/src/note_kind_resolver.rs:25` `NoteRegionContext.explicit_markers` 死字段（`resolve_note_kind` 从不读，所有调用传 `&[]`）：删字段 + 调整构造点。
- `fnm-phase2/src/endnote_chapter_explorer/matching.rs:16,53,56` 3× `#[allow(dead_code)]` 未读字段（`ChapterRow.order_index`、`PageChapterSignal.page_no/chapter_title`）：删字段 + 删 `#[allow]`。
- `fnm-phase2/src/chapter_split/structure_model.rs:27` `OCRProfile.placeholder` 占位死字段：删（确认 structure_model 本身去留，见 §2）。
**验证**：build/clippy/test 通过。

---

## 2. 需对照 Python 确认去留（不要盲删，也不要盲修）

> 这些是 `pub` 但**项目内 0 引用**的函数，可能是「Rust 漏接的功能」或「移植冗余死代码」。判据：**对照 Python `FNM_RE` 主流程是否调用等价逻辑**。

### B2-6　phase2 `chapter_split/{endnote_project, overrides_apply, synth_markers}`
- 函数：`compute_endnote_projections` / `compute_fallback_assignments` / `apply_note_item_overrides` / `compute_synthetic_markers`（grep 确认 0 非测试引用）。
- **确认步骤**：
  1. 在 Python 仓库 grep 对应函数（endnote 投影 / note-item override 应用 / 合成 marker）的调用点；
  2. 看 Python phase2 主流程（`chapter_split` 等价）是否在该阶段执行这些；
  3. 对照 Rust `build_chapter_layers` / `build_phase2_structure_sync` 是否遗漏。
- **处置**：
  - 若 Python 在 phase2 做、Rust 漏接 → **功能缺口**：接入到 `build_chapter_layers`（独立小批次，记入 B4 或新批次），此时再修 B1-11 的 endnote_project 哨兵 bug；
  - 若 Python 也不在 phase2 做（override 实际在 phase3 `note_item_overrides`、合成 marker 在别处）→ **死代码**：删除三个文件 + `chapter_split/mod.rs` 的 `mod` 声明。
- **默认倾向**：`overrides_apply`/`synth_markers` 倾向死代码（phase3 已有 override 通道）；`endnote_project` 需重点确认（可能是 §8 note 投影的遗漏）。

### B2-7　phase1 pub 无项目内调用者函数
- `alignment::align_toc_to_chapters`、`container_detection::{is_container_chapter, expand_container_chapters}`、`monotonic::reorder_chapters_monotonic`、`normalize::role_by_no`、`fallback::build_chapter_skeleton_fallback`（builder 走分步调用而非它）。
- **确认**：grep 全 workspace + Python 对照；确认无外部消费后**删除或降为私有**（`pub`→无）。
- 注意 `build_chapter_skeleton_fallback` 有测试调用——若仅测试用，评估是删测试+函数还是保留为公开 API。

---

## 3. 完成标准（DoD）
- [ ] §1 全部删除，`cargo build/test/clippy`（0 warning）通过。
- [ ] §2 每项有明确的「Python 对照结论 + 处置（删/接入/保留）」记录在提交信息。
- [ ] 删除 `#[allow(dead_code)]` 后 clippy 不再报 dead_code（B2-3/B2-5）。
- [ ] **未触碰** §「关键边界」列出的 LLM 验证层文件。

## 风险与回滚
- 删 struct 字段可能牵连 serde/Default/构造点，逐个 `cargo build` 驱动。
- §2 不可盲目删——`endnote_project` 若实为 §8 投影遗漏，删了会掩盖功能缺口；必须先做 Python 对照。
- 全为删除操作，回滚 = git revert 对应提交。
