# `fnm-phase4` 实施计划

本文档是自包含的——新 session 接手者读完本文件 + AGENTS.md Rust 规范 +
fnm-phase3 完成情况，即可开工 Phase 4。

---

## 0. 项目背景（30 秒）

正在做 Python `FNM_RE/` 到 Rust `fnm_re_rs/` 的全量重写。

| Phase | crate | 状态 | 测试 |
|---|---|---|---|
| 0 基础设施 | `fnm-core` | ✅ **100% 完成（2026-05-18）** | 110 lib + 9 集成 |
| 1 章节骨架 | `fnm-phase1` | ✅ **100% 模块完成** | 106 lib + 27 集成（1 chapter_boundary parity 待精调）|
| 2 注释结构 + note_kind | `fnm-phase2` | ✅ **100% 完成** | 140 lib + 18 集成 + biopolitics 6/6 |
| 3 body anchor + link 匹配 | `fnm-phase3` | ✅ **100% 完成** | 26 lib + 27 集成（5 ignored cascade） |
| **4 引用注入 + 翻译单元** | **`fnm-phase4`** | **🔄 M1 (ref_freeze) 完成（2026-05-18）** | 69 unit tests |
| 5 章 markdown 合并 | `fnm-phase5` | ⏳ 未开始 | — |
| 6 导出审计 | `fnm-phase6` | ⏳ 未开始 | — |
| LLM repair (3.5) | `fnm-llm-repair` | ⏳ 未开始（fnm-core vision/spec 已就绪）| — |

**workspace 测试**：23 套件 · 477 passed · 1 failed · 8 ignored。
完整状态见 [`fnm_re_rs/FNM_RE_REFACTOR.md`](../fnm_re_rs/FNM_RE_REFACTOR.md)。

---

## 0a. Phase 4 启动就绪清单（2026-05-18 验证）

| 依赖项 | 状态 | 备注 |
|---|---|---|
| **fnm-core** | ✅ 100% | 含 `model_capabilities` + `config` + `vision/spec`（5 家 provider）|
| **fnm-phase1** | ✅ 100% | 12 模块完整，含 LLM book type verify |
| **fnm-phase2** | ✅ 100% | 15 模块完整，含 visual_anchor_recovery 全 port |
| **fnm-phase3** | ✅ 100% | 10 模块完整，含 1730 行 note_linking |
| **DB Phase 1-3 持久化** | ✅ | Repository trait 含 replace_fnm_phase1/2/3_products |
| **LLM 5 家 provider** | ✅ | DeepSeek / Qwen / MiMo / GLM / Kimi 通过 fnm_model_pool 路由 |
| **fnm-core `ref_rewriter` / `segments` / `token_counter` / `db CRUD translation_units`** | ✅ | Phase 4 直接消费的基建全在 |

---

## 1. 必读前置（按顺序）

| # | 路径 | 重点章节 |
|--:|---|---|
| 1 | `/Users/hao/OCRandTranslation/AGENTS.md` | "Rust 重构代码规范" 12 条铁律（行 281-540）|
| 2 | `/Users/hao/OCRandTranslation/CLAUDE.md` | 第 8/12 条 Phase 边界 + 树枝状条件 |
| 3 | `/Users/hao/OCRandTranslation/FNM_RE/RUST_MIGRATION_PLAN.md` | "Step 4" 段（行 322-346）|
| 4 | `/Users/hao/OCRandTranslation/FNM_RE/FNM_PHASE3_PLAN.md` | 参考 Phase 3 plan 任务粒度与 PR 流程 |
| 5 | `fnm_re_rs/fnm-phase3/tests/known_python_bugs.md` | Phase 3 已知遗留（Phase 2 cascade 5 个 ignored）|

**特别看 AGENTS.md 的 12 条铁律**——任何违反都会被审计拒绝。简版：
1. 翻译保真度禁简化（Rust ~ Python 80-120% 行数）
2. Regex 必须 `Lazy<Regex>` 静态
3. 复用 fnm-core 基础设施
4. mod.rs < 400 行
5. 每个 pub fn 标 `←→ Python xxx()` doc comment
6. 测试用真实 fixture
7. Parity byte-equal Python
8. 不允许 `let _ = ...` 忽略关键参数
9. Stub 用 `anyhow::bail!`，不静默返空
10. 0 `Rc<RefCell>` / 0 滥用 `Arc<Mutex>`
11. `.clone()` 节制
12. PR 验收 checklist 12 项

---

## 2. Phase 4 目标与职责

### 输入

通过 DB / 直接消费 Phase 1/2/3 输出：

| 来源 | 内容 | Rust 类型 |
|---|---|---|
| Phase 1 (`fnm_chapters` / `fnm_section_heads` / `fnm_pages`) | 章节骨架 + page_role | `ChapterRecord` / `SectionHeadRecord` / `PagePartitionRecord` |
| Phase 2 (`fnm_note_items` / `fnm_note_regions` / `fnm_chapter_note_modes`) | note 定义（含 note_kind）+ 区域 + chapter mode | `NoteItemRecord` / `NoteRegionRecord` / `ChapterNoteModeRecord` |
| Phase 3 (`fnm_body_anchors` / `fnm_note_links`) | body anchors + effective links | `BodyAnchorRecord` / `NoteLinkRecord` |
| `phase2::ChapterLayer`（内存） | chapter-level 聚合数据（body_pages + items + regions）| `ChapterLayer` |
| `raw_pages.json` | markdown / blocks / fnBlocks | `RawPage` |

### 输出

| 表 / 字段 | 内容 | 入口函数 |
|---|---|---|
| `Phase4Output.frozen_units` | 章 body + note units（已注入 `{{NOTE_REF:N}}` token） | `build_frozen_units` |
| `Phase4Output.frozen_refs` | FrozenRefEntry 列表（含 decision: injected/skipped + reason）| 同上 |
| `fnm_translation_units` | 翻译单元（body chunk / footnote / endnote 三类） | `build_translation_units` |
| `fnm_structure_reviews` | 结构复核记录（9 类 review type）| `build_structure_reviews` |
| `Phase4Output.status` | StructureStatusRecord + summary | `build_phase4_structure` |

### Phase 边界纪律（CLAUDE.md §12）

Phase 4 **绝对不做**：
- ❌ **重新检测 anchor / link**（Phase 3 唯一来源，Phase 4 只透传 matched links）
- ❌ **重分类 note_kind**（Phase 2 唯一来源）
- ❌ **重新切分章节**（Phase 1 唯一来源）
- ❌ 修改上游 DB 表（只读 phase1/2/3 表）

Phase 4 **该做**：
- ✅ 把 matched link 的 anchor 坐标注入 body markdown（`{{NOTE_REF:N}}` token 替换）
- ✅ 检测 unsupported link（matched 但 anchor 坐标缺失 / synthetic）→ blocker
- ✅ 切分翻译单元（按段落 / 章 / 跨页边界 + max_body_chars 预算）
- ✅ 生成结构复核记录（structure_reviews：boundary / orphan / ambiguous / toc）

---

## 3. 功能模块清单（按数据流顺序）

完整数据流：**Phase1/2/3 输入 → ref_freeze（注入 token）→ units（结构化页 + 切块）→ reviews（复核）→ persist**

### 数据流图

```
┌─────────────────────────────────────────────────────────────────────┐
│ INPUTS                                                              │
│   ChapterLayers (phase2) + NoteLinkTable (phase3)                   │
│   + raw_pages + Phase1Structure + BookStructureModel                │
└─────────────┬───────────────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ M1. ref_freeze/ — frozen_units 构建                                  │
│   1. chapter_order_map + chapter_page_bounds                        │
│   2. 收集 matched_links + anchor_to_note_ids → conflict_anchor_ids  │
│   3. 章级 body_pages 收集（page_no → text）                          │
│   4. inject loop：遍历 matched_links                                 │
│        - resolve_note_item_owner                                    │
│        - inject_token_once（按 source_marker / [N] / <sup>N</sup>）  │
│        - shift_coords_out_of_note_ref_token                         │
│        - skip 决策（6 reasons）+ clean_skipped_marker                │
│   5. unit_contract_issues（blocker 检查）                            │
│   6. compute_unit_hash + 输出 FrozenUnits + FrozenRefEntry[]        │
└─────────────┬───────────────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ M2. units/ — translation_units 构建                                  │
│   1. ref_materialization_context（anchor map + conflict + marker）   │
│   2. 章级循环：                                                       │
│        a. build_structured_body_pages_for_chapter                   │
│           - chapter heading split                                   │
│           - trailing note block trim                                │
│           - gap page prefix sanitize                                │
│        b. materialize_refs_for_chapter（注入 NOTE_REF token）        │
│        c. segment_paragraphs_from_body_pages（→ page_segments）      │
│        d. chunk_body_page_segments（→ chunks，按 max_body_chars）    │
│        e. 每 chunk → TranslationUnitRecord(kind=body)                │
│   3. note_items 排序后生成 footnote/endnote unit                     │
│   4. 全 units 统一排序：(chapter_order, kind_body_first, page_start) │
└─────────────┬───────────────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ M3. reviews.rs — structure_reviews                                  │
│   遍历 chapters + body_anchors + effective_links + summary：         │
│      触发 9 类 review_type（boundary / uncertain_anchor /            │
│      footnote_orphan_note / footnote_orphan_anchor /                │
│      endnote_orphan_note / endnote_orphan_anchor / ambiguous /      │
│      toc_alignment / toc_semantic）                                 │
│   去重 + 排序 + count 汇总                                          │
└─────────────┬───────────────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ M4. lib.rs::build_phase4_structure — 顶层编排                        │
│   组装 Phase4Output { frozen_units, frozen_refs, units, reviews,    │
│                       status, summary, diagnostics }                │
└─────────────┬───────────────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ M5. persist_phase4 — DB 持久化                                       │
│   replace_fnm_phase4_products(doc_id, products)                     │
│      → fnm_translation_units / fnm_structure_reviews 写入            │
└─────────────────────────────────────────────────────────────────────┘
```

### 模块到 Python 函数的 1:1 映射

#### M1: `ref_freeze/` — 引用冻结（Python `modules/ref_freeze.py` 678 行）

| Rust 子模块 | Python 函数 | 职责 |
|---|---|---|
| `mod.rs::build_frozen_units` | `build_frozen_units` | 顶层编排，输出 `FrozenUnits` + `FrozenRefEntry[]` + summary |
| `chapter_index.rs` | `_chapter_order_map` + `_chapter_page_bounds` | chapter_id → order + (start_page, end_page) 索引 |
| `inject.rs::inject_token_once` | `_inject_token_once` | 按 source_marker / [N] / <sup>N</sup> 三种格式查找 + 替换为 token |
| `inject.rs::shift_coords_out_of_note_ref_token` | `_shift_coords_out_of_note_ref_token` | char 坐标避开已注入 token |
| `inject.rs::resolve_note_item_owner` | `_resolve_note_item_owner` | note_item → 实际 owner chapter（处理 book-scope 投射）|
| `inject.rs::clean_skipped_marker` | `_clean_skipped_marker` | ceiling_skip / policy_skip 时清理 raw marker |
| `contract.rs::unit_contract_issues` | `_unit_contract_issues` | blocker 检查：body_units 与 note_units 一致性 |
| `hash.rs::compute_unit_hash` | `_compute_unit_hash` | (source_text, page_start, page_end, char_count, page_nos) → unit_hash |

**Skip 6 reasons**（与 Python 对齐）：
1. `missing_anchor` — anchor_id 在 anchors_by_id 找不到（ceiling_skip）
2. `synthetic_anchor` — synthetic + source_marker 空 或 = normalized_marker（ceiling_skip）
3. `conflict_anchor` — anchor → 多个 note_id（error_skip）
4. `duplicate_anchor` — 同 anchor 已注入过（policy_skip）
5. `missing_body_page` — anchor.page_no 不在 chapter body_pages（error_skip）
6. `token_not_found` — inject_token_once 未匹配到任何候选（ceiling_skip）

#### M2: `units/` — 翻译单元（Python `stages/units.py` 868 行）

| Rust 子模块 | Python 函数 | 职责 |
|---|---|---|
| `mod.rs::build_translation_units` | `build_translation_units` | 顶层编排，输出 `TranslationUnitRecord[]` + summary |
| `page_split.rs::normalize_title_key` | `_normalize_title_key` | 章标题归一化用于 split 匹配 |
| `page_split.rs::extract_note_heading_split` | `_extract_note_heading_split` | 找 "## Notes" 切分 (body, note) |
| `page_split.rs::split_page_text_by_chapter_heading` | `_split_page_text_by_chapter_heading` | 按章标题 heading 切分 (before, after) |
| `page_split.rs::split_page_text_at_first_heading` | `_split_page_text_at_first_heading` | 找第一个 # heading 切分 |
| `page_split.rs::trim_trailing_markdown_note_block` | `_trim_trailing_markdown_note_block` | 删除尾部 note 定义块 |
| `page_split.rs::sanitize_gap_page_prefix` | `_sanitize_gap_page_prefix` | 清理 gap page 噪声行（页眉页脚等）|
| `page_split.rs::synthetic_markdown_pages` | `_synthetic_markdown_pages` | 构造合成 markdown page list |
| `body_pages.rs::build_structured_body_pages_for_chapter` | `_build_structured_body_pages_for_chapter` | 章级 body pages 结构化：split + trim + sanitize |
| `ref_inject.rs::ref_materialization_context` | `_ref_materialization_context` | anchors_by_id + conflict_anchor_ids + unresolved_marker_keys 索引 |
| `ref_inject.rs::inject_token_once` | `_inject_token_once`（units.py 版本）| 在结构化 page text 中注入 NOTE_REF |
| `ref_inject.rs::materialize_refs_for_chapter` | `_materialize_refs_for_chapter` | 章级 ref 物化 + cleanup_nested_note_refs |
| `segments.rs::segment_paragraphs_from_body_pages` | `_segment_paragraphs_from_body_pages` | 章 body_pages → `UnitPageSegmentRecord[]` |
| `chunking.rs::chunk_visible_paragraphs` | `_chunk_visible_paragraphs` | 段落可见性过滤 + token budget 切块 |
| `chunking.rs::chunk_body_page_segments` | `_chunk_body_page_segments` | 章级 chunk 切分，输出 body unit chunks |
| `chunking.rs::paragraph_content_dedupe_key` | `_paragraph_content_dedupe_key` | 段落去重 key |
| `endnote_lookup.rs::chapter_endnote_start_page_map` | `_chapter_endnote_start_page_map` | chapter_id → endnote 区起始页 |

**TranslationUnit 三类**：
- `kind="body"`：章 body chunk（unit_id=`body-{chapter_id}-{chunk_idx:04d}`）
- `kind="footnote"`：单个 footnote item（unit_id=`footnote-{chapter_id}-{note_item_id}`）
- `kind="endnote"`：单个 endnote item（unit_id=`endnote-{chapter_id}-{note_item_id}`）

#### M3: `reviews.rs` — 结构复核（Python `stages/reviews.py` 210 行）

| Rust 函数 | Python 函数 | 职责 |
|---|---|---|
| `build_structure_reviews` | `build_structure_reviews` | 顶层入口，输出 `StructureReviewRecord[]` + count summary |
| `sanitize_review_token` | `_sanitize_review_token` | review_id 内 token 清理（非字母数字 → -） |
| `make_review_id` | `_make_review_id` | `review-{type}-{chapter}-{ps}-{pe}-{target}` |
| `append_review` | `_append_review` | 按 whitelist 过滤 + severity 推断 + 追加 |

**9 类 review_type**（白名单）：
1. `boundary_review_required` — chapter.boundary_state == "review_required"
2. `uncertain_anchor` — anchor.anchor_kind=="unknown" 或 certainty < 1.0
3. `footnote_orphan_note` — link.status==orphan_note + note_kind==footnote
4. `footnote_orphan_anchor` — link.status==orphan_anchor + note_kind==footnote
5. `endnote_orphan_note` — 同上但 endnote
6. `endnote_orphan_anchor` — 同上但 endnote
7. `ambiguous` — link.status==ambiguous（warning 级别）
8. `toc_alignment_review_required` — title/section alignment 失败
9. `toc_semantic_review_required` — toc_semantic_contract_ok==false

**Severity**：`warning`（ambiguous / uncertain_anchor）vs `error`（其他）

#### M4: `lib.rs::build_phase4_structure` — 顶层编排

```rust
pub fn build_phase4_structure(input: Phase4Input<'_>) -> anyhow::Result<Phase4Output>;
```

调用顺序：
1. `ref_freeze::build_frozen_units(...)` → `FrozenUnits` + `FrozenRefEntry[]`
2. `units::build_translation_units(...)` → `TranslationUnitRecord[]`
3. `reviews::build_structure_reviews(...)` → `StructureReviewRecord[]`
4. 组装 `Phase4Structure` + `Phase4Summary` + `StructureStatusRecord`
5. 返回 `Phase4Output { structure, frozen_refs, summary, diagnostics }`

#### M5: `persist_phase4` — DB 持久化

```rust
pub fn persist_phase4(repo: &dyn Repository, doc_id: &str, output: &Phase4Output) -> anyhow::Result<()>;
```

调用 `repo.replace_fnm_phase4_products(doc_id, &Phase4Products { translation_units, structure_reviews, status })`。

---

## 4. crate 结构与实施顺序

### 已就绪
- `fnm-phase4/Cargo.toml`（依赖 phase1/2/3 + fnm-core）
- `fnm-phase4/src/lib.rs`（placeholder）
- workspace member 已加入

### 模块文件布局

```
fnm-phase4/src/
├── lib.rs                                # build_phase4_structure 顶层
├── input.rs                              # Phase4Input + Phase4Config
├── output.rs                             # Phase4Output（薄包装 fnm-core 类型）
├── ref_freeze/
│   ├── mod.rs                            # build_frozen_units 编排
│   ├── chapter_index.rs                  # order_map + page_bounds
│   ├── inject.rs                         # inject_token_once + shift_coords + clean_skipped
│   ├── contract.rs                       # unit_contract_issues
│   └── hash.rs                           # compute_unit_hash
├── units/
│   ├── mod.rs                            # build_translation_units 编排
│   ├── page_split.rs                     # 7 个文本切分 helper
│   ├── body_pages.rs                     # build_structured_body_pages_for_chapter
│   ├── ref_inject.rs                     # ref_materialization_context + materialize_refs_for_chapter
│   ├── segments.rs                       # segment_paragraphs_from_body_pages
│   ├── chunking.rs                       # chunk_body_page_segments + chunk_visible_paragraphs
│   └── endnote_lookup.rs                 # chapter_endnote_start_page_map
└── reviews.rs                            # build_structure_reviews + 4 helper
```

### 实施顺序（13 任务，按数据流顺序）

**Size 单位**（与 [FNM_COMPLETION_PLAN.md](FNM_COMPLETION_PLAN.md) 一致，按 AI 工作量计）：

- **S**：单文件改动，<100 LOC，1 session 内完成
- **M**：跨 2-3 文件，100-300 LOC，1-2 session
- **L**：跨多文件 + 测试，300-700 LOC，2-3 session
- **XL**：架构性改动，>700 LOC 或多模块接线，3+ session

| # | 任务 | 数据流位置 | Size | 状态 |
|--:|---|---|:---:|:---:|
| P4.0 | 启动：删 placeholder + 子模块声明 + 测试 fixture 目录 | — | S | ✅ |
| P4.1 | `input.rs` + `output.rs` 类型契约（消费 fnm-core records）| 入口 | S | ✅ |
| **M1: ref_freeze** | | | | |
| P4.1a | `text/re_utils.rs` — document/text_utils.py 8 个基础 helper | M1 依赖 | S | ✅ |
| P4.1b | `text/markdown_parse.rs` — parse_page_markdown 完整 5 步 + 15 helper | M1 依赖 | L | ✅ |
| P4.2 | `ref_freeze/chapter_index.rs` + `hash.rs`（2 个小 helper）| M1.1, M1.6 | S | ✅ |
| P4.3 | `ref_freeze/inject.rs`（3 个核心算法：inject + shift + clean）| M1.4 | M | ✅ |
| P4.4 | `ref_freeze/contract.rs`（blocker 检查 + skip 6 reasons 分类）| M1.5 | S | ✅ |
| P4.5 | `ref_freeze/mod.rs::build_frozen_units` 顶层编排 | M1 全部 | L | ✅ |
| P4.5a | `segments/mod.rs` + `chunking.rs` — segment + chunk 算法（原 P4.9，M1 需要）| M1 依赖 | M | ✅ |
| **M2: units** | | | | |
| P4.6 | `units/page_split.rs`（7 个文本切分 helper）| M2.1 | M | ⏳ |
| P4.7 | `units/body_pages.rs` + `endnote_lookup.rs`（结构化 body 收集）| M2.2 | M | ⏳ |
| P4.8 | `units/ref_inject.rs`（ref_materialization_context + materialize_refs_for_chapter）| M2.3 | M | ⏳ |
| P4.9 | `units/segments.rs` + `chunking.rs` → 已提前到 P4.5a（M1 依赖）| M2.4-2.5 | L | ✅ |
| P4.10 | `units/mod.rs::build_translation_units` 顶层编排 | M2 全部 | L | ⏳ |
| **M3-M5: reviews + lib + persist** | | | | |
| P4.11 | `reviews.rs::build_structure_reviews`（9 review type + dedup + sort）| M3 | M | ⏳ |
| P4.12 | `lib.rs::build_phase4_structure` 顶层编排 + `persist_phase4` DB 持久化 | M4-M5 | M | ⏳ |
| **测试** | | | | |
| P4.13 | Biopolitics parity（生成 golden + 逐字段比对）+ 3 SPEC 测试翻译 | — | L | ⏳ |

**规模合计**：4 S + 5 M + 4 L = 单 AI dev 串行约 21-25 session（按每任务 1-2 session 估）。

可并行点（多 AI 协作时）：M1 链（P4.2-P4.5）、M2 起步（P4.6-P4.7）、M3 reviews（P4.11）三路完全独立，可拆三路并行。M2.8 起合流（P4.8 需要 P4.5 + P4.7）。

---

## 5. 各任务详细规格

### P4.0: 启动（S）

1. 删除 `lib.rs::placeholder()` + test
2. 创建空文件：
   - `input.rs` / `output.rs`
   - `ref_freeze/mod.rs` + `chapter_index.rs` + `inject.rs` + `contract.rs` + `hash.rs`
   - `units/mod.rs` + `page_split.rs` + `body_pages.rs` + `ref_inject.rs` + `segments.rs` + `chunking.rs` + `endnote_lookup.rs`
   - `reviews.rs`
3. lib.rs 加 `pub mod` 声明（暂时全空 stub）
4. 创建 `tests/fixtures/` 目录 + `tools/gen_biopolitics_phase4_golden.py` 脚手架

**验收**：`cargo build -p fnm-phase4` 通过；`cargo clippy -p fnm-phase4 -- -D warnings` clean。

### P4.1: 类型契约（S）

`fnm-core` 已经定义了所有 Phase 4 Record 类型：
- `StructureReviewRecord` / `StructureStatusRecord`
- `TranslationUnitRecord` / `UnitPageSegmentRecord` / `UnitParagraphRecord`
- `FrozenUnit` / `FrozenRefEntry` / `FrozenUnits`
- `Phase4Summary` / `Phase4Structure`

```rust
// input.rs
use fnm_core::records::*;
use fnm_phase1::input::RawPage;
use fnm_phase2::chapter_split::{ChapterLayer, ChapterLayers};
use fnm_phase2::chapter_split::structure_model::BookStructureModel;
use fnm_phase3::output::Phase3Output;  // 或直接传 NoteLinkTable

pub struct Phase4Input<'a> {
    pub chapter_layers: &'a ChapterLayers,
    pub note_link_table: &'a Phase3Output,
    pub book_structure_model: Option<&'a BookStructureModel>,
    pub raw_pages: &'a [RawPage],
    pub phase1_pages: &'a [PagePartitionRecord],
    pub config: Phase4Config,
}

#[derive(Default)]
pub struct Phase4Config {
    pub max_body_chars: i64,         // 默认 6000
    pub pipeline_run_id: String,
}

// output.rs
pub struct Phase4Output {
    pub structure: Phase4Structure,
    pub frozen_refs: Vec<FrozenRefEntry>,
    pub frozen_units: FrozenUnits,
    pub summary: Phase4Summary,
    pub diagnostics: serde_json::Value,
}
```

### P4.2: `ref_freeze/chapter_index.rs` + `hash.rs`（S）

**Python 源**：`ref_freeze.py:34-46, 184-194`

两个小 helper：

```rust
// chapter_index.rs
pub fn chapter_order_map(chapter_layers: &ChapterLayers) -> HashMap<String, i64>;
pub fn chapter_page_bounds(chapter: &ChapterLayer) -> (i64, i64);

// hash.rs
pub fn compute_unit_hash(
    source_text: &str, page_start: i64, page_end: i64,
    char_count: i64, page_nos: &[i64],
) -> (String, String); // (content_hash, scope_hash)
```

`compute_unit_hash` 用 SHA-256（Rust `sha2` crate）对齐 Python `hashlib.sha256`。

### P4.3: `ref_freeze/inject.rs`（M，**最大头之一**）

**Python 源**：`ref_freeze.py:47-157`（4 个函数 ~110 行）

```rust
pub fn resolve_note_item_owner(
    note_item_id: &str,
    note_items_by_id: &HashMap<String, &NoteItemRecord>,
    chapter_layers: &ChapterLayers,
) -> String;

pub fn shift_coords_out_of_note_ref_token(
    text: &str, char_start: usize, char_end: usize,
) -> (usize, usize);

pub fn inject_token_once(
    text: &str,
    anchor: &BodyAnchorRecord,
    marker: &str,
    note_id: &str,
) -> (String, bool); // (updated_text, injected)

pub fn clean_skipped_marker(text: &str, marker: &str) -> String;
```

**关键算法**：`inject_token_once` 按 3 个候选顺序查找：
1. `anchor.source_marker`（如 `[7]` / `<sup>7</sup>`）
2. `[{marker}]` 包裹形式
3. 正则 `\[\s*(?:\^)?\s*{marker}\s*\]` fallback

找到即用 `frozen_note_ref(note_id) = "{{NOTE_REF:{note_id}}}"` 替换第一处。

### P4.4: `ref_freeze/contract.rs`（S）

**Python 源**：`ref_freeze.py:159-194`

```rust
pub enum SkipCategory { CeilingSkip, ErrorSkip, PolicySkip }

pub enum SkipReason {
    MissingAnchor,       // CeilingSkip
    SyntheticAnchor,     // CeilingSkip
    ConflictAnchor,      // ErrorSkip
    DuplicateAnchor,     // PolicySkip
    MissingBodyPage,     // ErrorSkip
    TokenNotFound,       // CeilingSkip
}

pub fn skip_reason_to_category(reason: SkipReason) -> SkipCategory;

pub fn unit_contract_issues(
    body_units: &[FrozenUnit],
    note_units: &[FrozenUnit],
) -> Vec<String>;
```

`unit_contract_issues` 输出问题列表（如 `freeze_matched_ref_not_injected`），由上游 `build_frozen_units` 决定是否 `bail!`。

### P4.5: `ref_freeze/mod.rs::build_frozen_units`（L）

**Python 源**：`ref_freeze.py:196-`（顶层 ~250 行）

```rust
pub fn build_frozen_units(
    chapter_layers: &ChapterLayers,
    note_link_table: &Phase3Output,
    book_structure_model: Option<&BookStructureModel>,
    max_body_chars: i64,
    pipeline_run_id: &str,
) -> anyhow::Result<(FrozenUnits, Vec<FrozenRefEntry>, serde_json::Value)>;
```

编排：
1. `chapter_index::chapter_order_map`
2. 构建 anchor_by_id / region_by_id 索引
3. 计算 matched_links + anchor_to_note_ids → conflict_anchor_ids
4. 章级 body_pages 收集（page_no → text）
5. inject loop：遍历 matched_links → skip 决策 → inject_token_once
6. `unit_contract_issues` → 严重错误 `bail!`，警告归入 summary
7. `compute_unit_hash` 计算每 unit
8. 输出 `FrozenUnits` + `FrozenRefEntry[]` + summary

### P4.6: `units/page_split.rs`（M）

**Python 源**：`units.py:55-156`（7 个 helper）

```rust
pub fn normalize_title_key(text: &str) -> String;
pub fn extract_note_heading_split(text: &str) -> Option<(String, String)>;
pub fn split_page_text_by_chapter_heading(text: &str, title: &str) -> (String, String);
pub fn split_page_text_at_first_heading(text: &str) -> (String, String);
pub fn trim_trailing_markdown_note_block(text: &str) -> String;
pub fn sanitize_gap_page_prefix(text: &str) -> String;
pub fn synthetic_markdown_pages(pages_by_no: &HashMap<i64, String>) -> Vec<Value>;
```

**正则**：
- `_NOTE_HEADING_RE` ←→ `r"(?i)^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*)\s*$"`（multiline）
- `_MARKDOWN_HEADING_LINE_RE` ←→ `r"^\s{0,3}#{1,6}\s*(.+?)\s*$"`
- `_MARKDOWN_NOTE_DEF_START_RE` ←→ `r"^\s*(?:\d{1,4}[A-Za-z]?\s*[\.\)\]]|\[[0-9]{1,4}\])\s+"`
- `_GAP_PAGE_NOISE_LINE_RE` ←→ 页眉页脚噪声行（参考 Python `units.py:33-50` 常量）

### P4.7: `units/body_pages.rs` + `endnote_lookup.rs`（M）

**Python 源**：`units.py:386-507`

```rust
// endnote_lookup.rs
pub fn chapter_endnote_start_page_map(
    note_regions: &[NoteRegionRecord],
) -> HashMap<String, i64>;

// body_pages.rs
pub fn build_structured_body_pages_for_chapter(
    chapter: &ChapterRecord,
    raw_page_by_no: &HashMap<i64, &RawPage>,
    page_role_by_no: &HashMap<i64, String>,
    note_start_page: i64,
    next_chapter: Option<&ChapterRecord>,
) -> Vec<StructuredBodyPage>;

pub struct StructuredBodyPage {
    pub page_no: i64,
    pub text: String,
    pub source_label: String, // "body" / "split_chapter_heading" / "trim_note_block" 等
}
```

### P4.8: `units/ref_inject.rs`（M）

**Python 源**：`units.py:509-687`

```rust
pub struct RefMaterializationContext {
    pub anchors_by_id: HashMap<String, BodyAnchorRecord>,
    pub conflict_anchor_ids: HashSet<String>,
    pub unresolved_marker_keys: HashSet<(String, String, String)>,
    pub matched_link_count: usize,
    pub ignored_skipped_count: usize,
    pub ambiguous_skipped_count: usize,
}

pub fn ref_materialization_context(phase4: &Phase4Structure) -> RefMaterializationContext;

pub fn inject_token_once(
    text: &str,
    anchor: &BodyAnchorRecord,
    marker: &str,
    note_id: &str,
) -> (String, bool);

pub fn materialize_refs_for_chapter(
    chapter: &ChapterRecord,
    body_pages: &[StructuredBodyPage],
    phase4: &Phase4Structure,
    ref_ctx: &RefMaterializationContext,
) -> (Vec<StructuredBodyPage>, RefInjectionSummary);

pub struct RefInjectionSummary {
    pub injected_link_count: usize,
    pub synthetic_skipped_count: usize,
}
```

**注意**：这里的 `inject_token_once` 与 `ref_freeze/inject.rs::inject_token_once` 接口相似但语义不同——`units/ref_inject.rs` 版本在已经 split/trim 后的 structured page text 上注入，且不维护 conflict 状态。

### P4.9: `units/segments.rs` + `chunking.rs`（L）

**Python 源**：`units.py:159-385`

```rust
// segments.rs
pub fn segment_paragraphs_from_body_pages(
    section: &SectionPayload,
) -> Vec<UnitPageSegmentRecord>;

pub struct SectionPayload {
    pub section_id: String,
    pub title: String,
    pub start_page: i64,
    pub end_page: i64,
    pub frozen_body_pages: Vec<StructuredBodyPage>,
    pub obsidian_body_pages: Vec<StructuredBodyPage>,
}

// chunking.rs
pub fn paragraph_content_dedupe_key(text: &str) -> String;

pub fn chunk_visible_paragraphs(
    paragraphs: &[UnitParagraphRecord],
    max_body_chars: i64,
) -> Vec<UnitChunk>;

pub fn chunk_body_page_segments(
    page_segments: &[UnitPageSegmentRecord],
    max_body_chars: i64,
) -> Vec<UnitChunk>;

pub struct UnitChunk {
    pub page_start: i64,
    pub page_end: i64,
    pub char_count: i64,
    pub source_text: String,
    pub page_segments: Vec<UnitPageSegmentRecord>,
}
```

**关键算法**：
- `parse_page_markdown`：fnm-core 已有，复用
- `build_fallback_unit_paragraphs`：fnm-core `segments.rs` 已有
- token budget 切块：贪心算法 + 段落不切断

### P4.10: `units/mod.rs::build_translation_units`（L）

**Python 源**：`units.py:690-868`（顶层 ~180 行）

```rust
pub fn build_translation_units(
    phase4: &Phase4Structure,
    raw_pages: &[RawPage],
    max_body_chars: i64,
) -> (Vec<TranslationUnitRecord>, serde_json::Value);
```

编排（按数据流）：
1. 索引：raw_page_by_no / page_role_by_no / chapter_order / chapter_by_id / note_region_by_id
2. `chapter_endnote_start_page_map`
3. `ref_materialization_context`
4. 章级循环：
   a. `build_structured_body_pages_for_chapter`
   b. `materialize_refs_for_chapter`
   c. `segment_paragraphs_from_body_pages`
   d. `chunk_body_page_segments`
   e. 每 chunk → `TranslationUnitRecord(kind=body)`
5. note_items 排序：(chapter_order, region.page_start, item.page_no, note_kind, note_item_id)
6. 每 note item → `TranslationUnitRecord(kind=footnote|endnote)`
7. 全 units 排序：(chapter_order, body_first, page_start, unit_id)
8. summary 输出 unit_planning + ref_materialization

### P4.11: `reviews.rs::build_structure_reviews`（M）

**Python 源**：`reviews.py:84-209`

```rust
pub fn build_structure_reviews(
    phase3: &Phase3Structure,
    effective_note_links: &[NoteLinkRecord],
    ignored_link_override_count: usize,
    invalid_override_count: usize,
) -> (Vec<StructureReviewRecord>, serde_json::Value);
```

9 类 review type 检测顺序：
1. 遍历 chapters → `boundary_review_required`
2. 遍历 body_anchors → `uncertain_anchor`
3. 遍历 effective_links → `footnote/endnote_orphan_note/anchor` + `ambiguous`
4. 检查 summary → `toc_alignment_review_required` + `toc_semantic_review_required`

去重（按 review_id）+ 排序（review_type → chapter_id → page_start → page_end → review_id）。

### P4.12: `lib.rs::build_phase4_structure` + `persist_phase4`（M）

```rust
pub fn build_phase4_structure(input: Phase4Input<'_>) -> anyhow::Result<Phase4Output> {
    // 1. frozen units
    let (frozen_units, frozen_refs, freeze_summary) = ref_freeze::build_frozen_units(...)?;

    // 2. 组装临时 Phase4Structure（reviews 和 units 还没生成）
    let phase4_intermediate = Phase4Structure { /* ... */ };

    // 3. translation units
    let (units, units_summary) = units::build_translation_units(&phase4_intermediate, ...);

    // 4. structure reviews
    let (reviews, reviews_summary) = reviews::build_structure_reviews(...);

    // 5. 装配最终 Phase4Output
    Ok(Phase4Output { ... })
}

pub fn persist_phase4(
    repo: &dyn fnm_core::db::Repository,
    doc_id: &str,
    output: &Phase4Output,
) -> anyhow::Result<()>;
```

### P4.13: Biopolitics parity + 3 SPEC 测试（L）

**SPEC 测试**：
- `test_load_phase6_for_doc_keeps_synthesized_note_items_from_overrides`
- `test_ch5_note_4_definition_is_full_length`
- `test_superscript_note_definition_lines_are_filtered`

**Biopolitics parity**：写 `tools/gen_biopolitics_phase4_golden.py`，输出：
- `biopolitics_phase4_frozen_units.json`
- `biopolitics_phase4_translation_units.json`
- `biopolitics_phase4_structure_reviews.json`

Rust 端 `tests/biopolitics_phase4_parity.rs` 逐字段 byte-equal 比对。

**已知 Phase 2 cascade**：若 phase3 ignored 测试因 phase2 note_items count 仍差异，phase4 unit count 也会有类似差异——参照 `fnm-phase3/tests/known_python_bugs.md §7` 做法，把受影响的 parity 测试标 `#[ignore]` 并写入根因。

---

## 6. Phase 4 验收 checklist（每个 PR）

抄 phase3 PLAN §8：

### 代码层
- [ ] `cargo build --release -p fnm-phase4` 通过
- [ ] `cargo clippy -p fnm-phase4 -- -D warnings` 通过（0 新增 allow）
- [ ] `cargo fmt --check` 通过
- [ ] `cargo test --all` 通过（保持现有测试 0 failed）
- [ ] 0 个 `let _ = ...` 忽略关键参数
- [ ] 0 个静默 stub（必须 `anyhow::bail!`）
- [ ] 0 个循环内 `Regex::new()`
- [ ] 0 `Rc<RefCell>` / 0 滥用 `Arc<Mutex>`

### 复用层
- [ ] PR 描述列出复用的 fnm-core / phase1/2/3 API
- [ ] 复用 `fnm_core::refs::cleanup_nested_note_refs` / `token_counter` 等
- [ ] 不重新定义 fnm-core 已有的类型

### Phase 边界纪律
- [ ] 0 处 `note_kind = ...` 赋值（只透传）
- [ ] 0 处重检测 anchor / link
- [ ] 0 处 chapter 重切分
- [ ] PR 描述声明："Phase 4 严守边界，仅消费上游事实"

### Parity
- [ ] Biopolitics parity 测试通过 OR 在 `known_python_bugs.md` 记录根因
- [ ] SPEC 测试翻译并通过

---

## 7. 已知风险与缓解

| 风险 | 缓解 |
|---|---|
| Phase 2/3 上游 cascade（35 个 over-extraction note_items）| Phase 4 透传不修复，blocker 报但允许进入下游验证；待 Phase 2 endnote_repair 接入主入口后 cascade 自然解 |
| `ref_freeze.py` 678 行复杂度 | 按 §4 拆 3 子模块（inject / contract / cleanup） |
| ref token 注入算法 O(n×m) | 用 `aho-corasick`（fnm-phase3 已是依赖）做多模式匹配优化为 O(n) |
| Python 端 frozen_units 数据结构未在 fnm-core records 直接对应 | 优先在 fnm-core 加 FrozenUnitRecord，避免 phase4 内重新定义 |

---

## 8. Phase 2 cascade 修复任务（独立，不阻塞 Phase 4 启动）

Phase 3 留下的 5 个 `#[ignore]` byte-equal parity 测试根因是 Phase 2 上游
`note_items` over-extraction（35 个）。这是 Phase 4 启动前**可以并行处理**的独立任务：

| 任务 | 描述 | 状态 |
|---|---|---|
| Phase 2 endnote_repair 接入 | `fnm-phase2/src/lib.rs` step 5 真实调用 `endnote_repair::repair_endnote_items` | ✅ 已接入（2026-05-18 扩为 6 步流水线）|
| Phase 2 endnote_chapter_explorer 接入 | step 1a 调用 `explore_endnote_chapter_regions_full` | ✅ 已接入（2026-05-18 完整 4 路径 + SequenceMatcher）|
| 跑 phase3 `--ignored` 验证 | 修完后跑 `cargo test -p fnm-phase3 -- --ignored`，期望 5 个 parity 测试通过 | 🔄 待 phase4 启动后再跑（cascade 缩小但需验证 note_items count 是否对齐）|
| 删 `#[ignore]` 注解 | 验证通过后把 phase3 测试转为 active | ⏳ |

**推荐**：Phase 4 启动后由其他人/同期推进，两者解耦。

---

## 9. PR 流程

每个 P4.x 一个独立 PR。PR title：

```
P4.X: <模块名> — <核心功能>（<行数>）
```

例：`P4.2: ref_freeze — frozen_units 编排 + 注入（约 700 行）`

每个 PR 合并前做代码审查。

---

## 10. 开工 checklist

1. 读完 §1 必读前置（5 个文档）
2. `cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --all`（确认基线全过）
3. 看 phase3 完成参考实现：`fnm-phase3/src/lib.rs::build_phase3_structure`
4. P4.0 开始：替换 placeholder() + 创建子模块占位
5. 每个 P4.X 一个 PR，标题严格按 §9 格式
6. P4.7 完成后通知用户做最终审计
