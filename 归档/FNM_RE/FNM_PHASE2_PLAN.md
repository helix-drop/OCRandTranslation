# `fnm-phase2` 实施计划

> 🟢 **状态：100% 模块完成（2026-05-18）**
>
> - **140 lib tests** + 18 集成测试通过；**biopolitics_phase2_parity 6/6 全过**（从修复前 6 panic）
> - 15 个核心模块全部 1:1 翻译完成，本次新增/重写：
>   - `sup_recovery/layer2.rs`（388 行）：修 UTF-8 byte-boundary panic + Unicode 拉丁 `[À-ÿ]` + Layer 0 normalize_unicode_superscripts + has_marker + find_insert_pos + apply_insertions
>   - `note_regions/post_body_promote.rs::reclassify_post_body_fnblocks` 下游 footnote_band/endnote_candidate 接入
>   - `note_items/page_text.rs`（350 行新增）：8 个 Python helper port（section_title_key / title_key_matches / split_shared_page_text_for_region / normalized_page_text 等）
>   - `endnote_repair/mod.rs`：扩为 6 步流水线（truncation / continuity / OCR split / cross-page / sequence_outlier / infer-missing）
>   - `endnote_chapter_explorer/mod.rs`（990 行）：重写从 363 → 990，含 SequenceMatcher 等价 LCS + 4 路径 + chapter_boundary fallback
>   - `chapter_split/structure_model.rs`（330 行新增）：BookStructureModel + ChapterStructureModel + 4 函数
>   - `visual_anchor_recovery/`：parsing.rs（375 行）+ materialize.rs（320 行）+ 顶层 run_visual_anchor_recovery + ResolvedModelSpec multi-spec fallback
>   - `sup_recovery/layer3.rs`：新增 layer3_verify_with_spec + ResolvedModelSpec 路径
> - 完整完成度见 [`fnm_re_rs/FNM_RE_REFACTOR.md` §2.3](../fnm_re_rs/FNM_RE_REFACTOR.md)
>
> 本文档作为历史实施计划保留。下方原文档内容未修改。

---

本文档是 `fnm-phase2` Rust crate 的完整实施说明书。`fnm-core` + `fnm-phase1` 已完成，可作为信任的依赖基础。

> 阅读前置：
> - [`RUST_MIGRATION_PLAN.md`](./RUST_MIGRATION_PLAN.md) — 全局架构
> - [`FNM_CORE_PLAN.md`](./FNM_CORE_PLAN.md) — fnm-core 实施记录
> - [`FNM_PHASE1_PLAN.md`](./FNM_PHASE1_PLAN.md) — fnm-phase1 实施记录

---

## fnm-phase1 已完成状态确认

本计划基于以下 Phase 1 交付物：

| 模块 | 公开 API（你将依赖的）|
|---|---|
| `fnm_phase1::build_phase1_structure` | 顶层入口，返回 `Phase1Output` |
| DB 表 `fnm_pages` / `fnm_chapters` / `fnm_section_heads` / `fnm_heading_candidates` | Phase 1 持久化产物 |
| `Repository::list_fnm_pages` / `list_fnm_chapters` 等 | 从 DB 读取 Phase 1 产物 |

**Phase 2 接口**：通过 DB（`Repository::list_fnm_*`）读取 Phase 1 产物，**不在内存里直接接收** `Phase1Structure`。这保证语言无关性（即使 Phase 1 是 Python，Phase 2 也能从同一个 DB 读）。

**禁止改动 fnm-core / fnm-phase1**。如需新 helper，加到 fnm-phase2 内部。

---

## 目标与定位

`fnm-phase2` 是 6-Phase pipeline 的第二步：**识别注释结构 + 确定 note_kind（全书唯一来源）**。

按 CLAUDE.md Phase 2 边界：**note_kind 在此唯一确定，下游 Phase3-6 只能透传不可覆盖**。

**职责**：
- 输入：`Phase1Structure`（来自 DB） + `pages: Vec<RawPage>` + 可选 `pdf_path`
- 输出：`Phase2Structure { chapters, note_regions, note_items, chapter_note_modes, book_structure, ... }`
- DB 落地：`fnm_note_regions` / `fnm_note_items` / `fnm_chapter_note_modes` / `fnm_chapter_body_pages` / `fnm_chapter_endnotes` / `fnm_paragraph_footnotes`
- override 消费：`fnm_review_overrides_v2`（来自手工 review 或 LLM repair）

**不做的事**（这些是 Phase3 及之后的边界）：
- ❌ body anchor 检测（Phase3）
- ❌ note_kind 重新分类（Phase3 严禁，必须透传）
- ❌ link 匹配（Phase3）

**Python 源对应**（共 ~6,200 行）：

| Python 路径 | 行数 | 主要内容 |
|---|---:|---|
| `FNM_RE/modules/chapter_split.py` | 1,089 | `build_chapter_layers` 入口 + note region 路径选择 |
| `FNM_RE/modules/sup_recovery.py` | 915 | OCR 上标修复（Layer 1/2/3）|
| `FNM_RE/modules/_sup_recovery_worker.py` | 233 | Sup recovery 子进程 worker（Rust 不需要）|
| `FNM_RE/modules/_pdf_render_worker.py` | 88 | PDF 渲染 worker（Rust 用 pdfium-render）|
| `FNM_RE/modules/pdf_render_subprocess.py` | 122 | PDF 子进程入口（Rust 不需要）|
| `FNM_RE/modules/visual_anchor_recovery.py` | 1,017 | 视觉锚点恢复（vision LLM）|
| `FNM_RE/modules/endnote_repair.py` | 325 | endnote 续行修复 |
| `FNM_RE/modules/llm_bare_digit_verify.py` | 221 | LLM 验证 bare digit marker（vision）|
| `FNM_RE/stages/note_regions.py` | 825 | `build_note_regions` 注释区识别 |
| `FNM_RE/stages/note_items.py` | 658 | `build_note_items` 注释项解析 |
| `FNM_RE/stages/endnote_chapter_explorer.py` | 722 | endnote chapter 探索（无 TOC 时） |
| **合计** | **6,215 行** | → 预计 **~9,500 行** Rust |

**说明**：Python 子进程相关代码（`_sup_recovery_worker.py` / `_pdf_render_worker.py` / `pdf_render_subprocess.py` 共 ~443 行）在 Rust 端**不需要 port**——Rust 没有 GIL，内存管理精细，子进程隔离失去意义。实际只需 port 5,772 行业务逻辑。

---

## Crate 结构

```
fnm-phase2/
├── Cargo.toml
├── README.md
├── src/
│   ├── lib.rs                          # 顶层入口：build_phase2_structure
│   ├── input.rs                        # Phase 2 输入类型（从 fnm-phase1 复用 RawPage）
│   ├── output.rs                       # Phase2Output 薄包装
│   ├── chapter_split/
│   │   ├── mod.rs                      # build_chapter_layers 编排
│   │   ├── path_selector.rs            # 选择 note region 路径（heading_scan / footnote_band / explorer）
│   │   ├── overrides_apply.rs          # 应用 review_overrides 到 chapter_layers
│   │   └── chapter_layer_builder.rs    # 章级聚合产出 ChapterLayer
│   ├── note_regions/
│   │   ├── mod.rs                      # build_note_regions 入口
│   │   ├── heading_scan.rs             # 显式 "NOTES" heading 扫描
│   │   ├── footnote_band.rs            # 页脚 footnote band 检测
│   │   ├── continuation_merge.rs       # 续行合并
│   │   ├── post_body_endnote.rs        # 章后隐式尾注识别
│   │   └── manual_rebind.rs            # 手工重新绑定章节
│   ├── note_items/
│   │   ├── mod.rs                      # build_note_items 入口
│   │   ├── parser.rs                   # 注释项解析（marker + body）
│   │   ├── ocr_split.rs                # OCR 切割 marker 重建（"1 2" → "12"）
│   │   ├── inline_break.rs             # 内联分隔重建
│   │   └── note_kind_resolver.rs       # **note_kind 唯一来源**（按 CLAUDE.md）
│   ├── endnote_chapter_explorer/
│   │   ├── mod.rs                      # explore_endnote_chapter_regions 入口
│   │   ├── toc_match.rs                # TOC 匹配路径
│   │   ├── signal_match.rs             # 信号匹配路径（无 TOC）
│   │   └── fallback_nearest.rs         # 最近章节兜底
│   ├── endnote_repair/
│   │   ├── mod.rs                      # endnote 续行修复入口
│   │   ├── boundary_detection.rs       # endnote 边界检测
│   │   └── citation_abbrev.rs          # 引文缩写处理（vol. / n° 等）
│   ├── sup_recovery/
│   │   ├── mod.rs                      # recover_book_chapter_scoped 入口
│   │   ├── layer1.rs                   # Layer 1：markdown 直接匹配
│   │   ├── layer2.rs                   # Layer 2：OCR block 文本对齐
│   │   ├── layer3.rs                   # Layer 3：vision LLM 验证
│   │   └── pdf_render.rs               # PDF 页渲染（pdfium-render）
│   ├── visual_anchor_recovery/
│   │   ├── mod.rs                      # build_visual_recovery_overrides 入口
│   │   ├── gap_detection.rs            # 缺口检测
│   │   ├── vision_client.rs            # vision LLM 调用
│   │   └── override_builder.rs         # 构建 anchor override
│   ├── llm_bare_digit_verify/
│   │   ├── mod.rs                      # verify_bare_digit_candidates 入口
│   │   ├── prompt_builder.rs
│   │   ├── llm_client.rs
│   │   └── response_parser.rs
│   └── book_structure.rs               # book_type 聚合（footnote_only / endnote_only / mixed）
└── tests/
    ├── parity/
    │   ├── test_note_regions.rs
    │   ├── test_note_items.rs
    │   ├── test_chapter_split.rs
    │   ├── test_sup_recovery_layer1.rs
    │   ├── test_sup_recovery_layer2.rs
    │   ├── test_sup_recovery_layer3.rs
    │   ├── test_endnote_repair.rs
    │   └── test_endnote_chapter_explorer.rs
    ├── integration/
    │   ├── test_biopolitics_phase2.rs        # SPEC: 章后隐式尾注 + 12 章
    │   ├── test_chapter_endnote_consolidation.rs  # SPEC: 7 février 单一 endnote region
    │   ├── test_book_scope_endnotes_projection.rs # SPEC: book-scope 投射
    │   ├── test_ocr_split_marker.rs           # SPEC: marker 重建
    │   └── test_db_roundtrip.rs               # phase2 写入 → 读取
    └── fixtures/
        ├── biopolitics_phase1_output.json   # 上游 Phase 1 产物
        ├── biopolitics_pages.json
        ├── chapter_7_fevrier_pages.json
        └── ...
```

---

## 实施顺序（14 个任务，预计 ~4 周）

按依赖链分阶段，**Phase 2 内部子模块可大量并行**（每个 stages/* 独立）。

| # | 任务 | 工时 | 依赖 | 可并行 |
|--:|---|---:|---|---|
| P2.0 | Cargo 骨架 + fixture 工具扩展 | 0.5 天 | - | - |
| P2.1 | `input.rs` + `output.rs` 类型契约 | 0.5 天 | P2.0 | - |
| P2.2 | `note_items/note_kind_resolver` — **note_kind 唯一来源** | 1 天 | P2.1 | - |
| P2.3 | `note_items/parser` + `ocr_split` + `inline_break` | 3 天 | P2.2 | 与 P2.4 并行 |
| P2.4 | `note_regions/heading_scan` + `footnote_band` + `continuation_merge` | 3 天 | P2.1 | 与 P2.3 并行 |
| P2.5 | `note_regions/post_body_endnote` + `manual_rebind` | 2 天 | P2.4 | - |
| P2.6 | `endnote_chapter_explorer/` | 2.5 天 | P2.4 | 与 P2.7 并行 |
| P2.7 | `endnote_repair/` — 续行修复 + 引文缩写处理 | 2 天 | P2.3 | 与 P2.6 并行 |
| P2.8 | `chapter_split/path_selector` + `chapter_layer_builder` | 2 天 | P2.5, P2.6 | - |
| P2.9 | `chapter_split/overrides_apply` — review_overrides 物化 | 1.5 天 | P2.8 | - |
| P2.10 | `sup_recovery/layer1` + `layer2` — OCR 文本对齐 | 3 天 | P2.3 | 与 P2.11 并行 |
| P2.11 | `sup_recovery/pdf_render` — pdfium-render 集成 | 1 天 | P2.0 | - |
| P2.12 | `sup_recovery/layer3` + `visual_anchor_recovery` + `llm_bare_digit_verify` — vision LLM | 3 天 | P2.10, P2.11 | - |
| P2.13 | `book_structure` + 顶层 `build_phase2_structure` + DB 持久化 | 1.5 天 | P2.8-P2.12 | - |
| P2.14 | 端到端集成测试 + 6 个 SPEC 测试翻译 | 2.5 天 | P2.13 | - |
| **总计** | | **~28.5 天** | | |

**多人并行潜力**：P2.3/P2.4、P2.6/P2.7、P2.10/P2.11 三组可并行 → 双人可缩短到 ~18 天。

---

## 关键基础设施

### Cargo.toml

```toml
[package]
name = "fnm-phase2"
version = "0.1.0"
edition = "2021"
rust-version = "1.75"

[dependencies]
fnm-core = { path = "../fnm-core" }
fnm-phase1 = { path = "../fnm-phase1" }  # 复用 RawPage / TocItem 类型

# 序列化
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"

# 正则与字符串
regex = "1.10"
aho-corasick = "1.1"        # 多模式快速匹配（用于 marker 候选扫描）
once_cell = "1.19"
unicode-normalization = "0.1"

# 错误处理
thiserror = "1.0"
anyhow = "1.0"

# 日志
tracing = "0.1"

# 并行
rayon = "1.10"

# PDF（与 fnm-phase1 同版本，复用 pdfium 二进制）
pdfium-render = { version = "0.8", features = ["bindings", "thread_safe"] }

# HTTP / LLM
reqwest = { version = "0.12", features = ["json", "rustls-tls", "stream"] }
tokio = { version = "1.35", features = ["rt-multi-thread", "macros"] }
base64 = "0.22"

# 图像处理（PDF 截图后压缩）
image = { version = "0.25", default-features = false, features = ["png", "jpeg"] }

[dev-dependencies]
insta = { version = "1.34", features = ["json"] }
pretty_assertions = "1.4"
tempfile = "3.10"
```

### Fixture 工具扩展

`tools/gen_phase2_fixtures.py`（在 fnm-core + fnm-phase1 已建立的基础上）：

```python
"""为 fnm-phase2 生成 parity fixture。"""
from FNM_RE.modules.chapter_split import build_chapter_layers
from FNM_RE.stages.note_regions import build_note_regions
from FNM_RE.stages.note_items import build_note_items
from FNM_RE.modules.sup_recovery import recover_book_chapter_scoped

# 关键 fixture：
# 1. Biopolitics phase1 output（上游 → 喂给 phase2）
# 2. Biopolitics phase2 expected（黄金答案）
# 3. 章 7 février（连续 endnote region 测试）
# 4. book-scope endnote projection（多章共享）
# 5. ocr split marker（"1 2" → "12" 重建）
# 6. sup_recovery layer 1/2 测试用例（symbol → marker / 两位 / 重复）
```

---

## 任务详细规格

### P2.0: Cargo 骨架（0.5 天）

**交付物**：
1. `fnm_re_rs/fnm-phase2/Cargo.toml`
2. workspace 加 `fnm-phase2` member
3. `src/lib.rs` 占位
4. `tools/gen_phase2_fixtures.py` 脚手架
5. `tests/fixtures/` 目录

**验收**：
- `cargo build -p fnm-phase2` 通过
- `cargo clippy -p fnm-phase2 -- -D warnings` 通过

---

### P2.1: 类型契约（0.5 天）

**Python 源**：`modules/chapter_split.py:1-100` 类型注解

**Rust 公开 API**：

```rust
// src/input.rs
use fnm_core::records::{ChapterRecord, PagePartitionRecord, SectionHeadRecord};
use fnm_phase1::input::RawPage;

/// Phase 2 输入：Phase 1 结构 + 原始页面 + 配置。
pub struct Phase2Input<'a> {
    pub phase1_chapters: &'a [ChapterRecord],
    pub phase1_pages: &'a [PagePartitionRecord],
    pub phase1_section_heads: &'a [SectionHeadRecord],
    pub raw_pages: &'a [RawPage],
    pub pdf_path: Option<&'a str>,
    pub config: Phase2Config,
}

#[derive(Default)]
pub struct Phase2Config {
    pub skip_sup_recovery: bool,
    pub skip_llm_verify: bool,
    pub manual_overrides: Option<ReviewOverrides>,
}

// src/output.rs
use fnm_core::records::*;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Phase2Output {
    pub chapters: Vec<ChapterRecord>,
    pub note_regions: Vec<NoteRegionRecord>,
    pub note_items: Vec<NoteItemRecord>,
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    pub book_type: String,
    pub diagnostics: serde_json::Value,
}
```

---

### P2.2: `note_kind_resolver` — note_kind 唯一来源（1 天）

**这是 Phase 2 的核心设计点**。按 CLAUDE.md 第 12 条：note_kind 在此唯一确定，Phase3+ 严禁覆盖。

**Python 源**：`stages/note_items.py:_resolve_note_kind` + `note_regions.py` 区域分类逻辑

**Rust 公开 API**：

```rust
// src/note_items/note_kind_resolver.rs
use fnm_core::types::NoteKind;

/// 单一权威函数：给定 region 上下文，决定 note_kind。
/// 
/// 决策树（按 CLAUDE.md 优先级）：
/// 1. 显式 heading "Notes/Endnotes" → endnote
/// 2. 显式 heading "Footnotes" → footnote
/// 3. footnote_band 检测命中 → footnote
/// 4. 章后隐式尾注区 → endnote
/// 5. book-scope endnote 区 → endnote
/// 6. 兜底 → review_required（不要默认 footnote）
pub fn resolve_note_kind(ctx: &NoteRegionContext) -> NoteKindResolution;

pub struct NoteRegionContext<'a> {
    pub heading_text: &'a str,
    pub has_footnote_band: bool,
    pub is_post_body_region: bool,
    pub is_book_scope: bool,
    pub explicit_markers: &'a [&'a str],  // 来自 visual TOC role_hint 等
}

pub struct NoteKindResolution {
    pub note_kind: NoteKind,
    pub confidence: f64,
    pub reason: &'static str,  // "explicit_heading_endnote" / "footnote_band" / ...
    pub review_required: bool,  // 当兜底分支触发时为 true
}
```

**关键约束**：
- 此函数是**唯一**决定 note_kind 的地方
- 下游模块（note_items、chapter_split、sup_recovery 等）**只读** `NoteRegionRecord.note_kind`，不再判定
- 测试覆盖所有分支 + 边界（兜底必须 review_required = true）

---

### P2.3: `note_items/` — 注释项解析（3 天）

**Python 源**：`stages/note_items.py`（658 行）+ `shared/notes.py` 中的 `parse_note_items_from_text` 等复杂业务（fnm-core 没 port，留给这里）

**Rust 拆分**：

```
src/note_items/
├── mod.rs               # build_note_items 入口
├── parser.rs            # 单条 note item 解析：marker + body
├── ocr_split.rs         # OCR 切割重建（"1 2" → "12"，is_reconstructed=True）
├── inline_break.rs      # 内联换行重建
└── note_kind_resolver.rs  # 见 P2.2
```

**公开 API**：

```rust
// src/note_items/mod.rs
use fnm_phase1::input::RawPage;
use fnm_core::records::{NoteItemRecord, NoteRegionRecord};

pub fn build_note_items(
    pages: &[RawPage],
    note_regions: &[NoteRegionRecord],
) -> Vec<NoteItemRecord>;
```

**关键算法**（按 Python `stages/note_items.py:396 build_note_items`）：
1. 遍历每个 note region
2. 抽取 region 内 markdown 文本
3. 用 marker 正则匹配解析每条 note
4. 应用 OCR split 重建（关键 SPEC：`test_ocr_split_marker_can_be_reconstructed`）
5. 应用 inline break 重建
6. note_kind 直接读 region.note_kind（不重新判定）

**SPEC 测试覆盖**：
- `test_ocr_split_marker_can_be_reconstructed` — OCR `"1 2"` 重建为 `"12"` 且 `is_reconstructed=true`

---

### P2.4: `note_regions/` — 注释区识别（3 天）

**Python 源**：`stages/note_regions.py`（825 行）

**Rust 拆分**：

```
src/note_regions/
├── mod.rs                   # build_note_regions 入口
├── heading_scan.rs          # 扫描 "## NOTES" / "## Endnotes" 等显式标题
├── footnote_band.rs         # 检测页脚 footnote band（页底连续短行注释带）
├── continuation_merge.rs    # 跨页续行合并
├── post_body_endnote.rs     # 章后隐式尾注（无显式标题）
└── manual_rebind.rs         # 手工 review override 应用
```

**公开 API**：

```rust
// src/note_regions/mod.rs
pub fn build_note_regions(
    phase1_chapters: &[ChapterRecord],
    pages: &[RawPage],
    page_partitions: &[PagePartitionRecord],
) -> Vec<NoteRegionRecord>;
```

**关键约束**：
- 每个 region 必须设置 `note_kind`（通过 `note_kind_resolver`）
- 每个 region 必须设置 `source`（heading_scan / footnote_band / continuation_merge 等，对应 `RegionSource` enum）
- 区域顺序必须按 `(chapter_id, page_start)` 排序稳定

**SPEC 测试覆盖**：
- `test_chapter_scope_endnote_region_count` — Biopolitics ≥ 11 章有 chapter-scope endnote region
- `test_each_lecture_chapter_has_endnote_region`

---

### P2.5: `note_regions/post_body_endnote` + `manual_rebind`（2 天）

**Python 源**：`stages/note_regions.py` 后半部分（`_detect_post_body_endnotes` 等）

**关键算法**：
- 章后隐式尾注：章末没有显式 "NOTES" 标题，但有一段连续的 numbered marker 段落
- 启发式条件：(1) 章末 N 页内 (2) 第 1 行是数字 marker (3) 后续 markers 单调递增

**SPEC 测试覆盖**：
- `test_chapter_7_fevrier_has_single_endnote_region` — LEÇON DU 7 FÉVRIER (139-148) 必须形成**单一连续** endnote region，不被 footnote-band 短路切碎

---

### P2.6: `endnote_chapter_explorer/`（2.5 天）

**Python 源**：`stages/endnote_chapter_explorer.py`（722 行）

**Rust 拆分**：

```
src/endnote_chapter_explorer/
├── mod.rs                   # explore_endnote_chapter_regions 入口
├── toc_match.rs             # TOC role_hint=endnotes 路径
├── signal_match.rs          # 信号匹配（无 TOC）：扫"Notes to Chapter X"
└── fallback_nearest.rs      # 兜底：归属最近章节
```

**公开 API**：

```rust
pub fn explore_endnote_chapter_regions(
    pages: &[RawPage],
    chapters: &[ChapterRecord],
    toc_hints: &TocEndnoteHints,
) -> Vec<EndnoteRegionExploration>;
```

**SPEC 测试覆盖**：
- `test_book_scope_endnotes_are_projected_by_marker_to_chapters` — book-scope endnote 按 marker 范围投射给各章（ch1 得 [1,2]，ch2 得 [3,4]）

---

### P2.7: `endnote_repair/` — 续行修复（2 天）

**Python 源**：`modules/endnote_repair.py`（325 行）

**关键功能**：
- 检测被错误截断的 endnote（如尾部以 ", vol." 结尾）
- 合并下一行到当前 note
- 处理引文缩写（`vol.` / `n°` / `art.` / `cf.` 等）—— Phase 1 增强后的 `_PAGE_CITATION_PREFIX_RE` 集合

**SPEC 测试覆盖**：
- `test_ch5_note_4_definition_is_full_length` — 章 5 [^4] 定义长度 ≥ 200 字符，不被截断到 `vol.`

---

### P2.8: `chapter_split/` — 章节层聚合（2 天）

**Python 源**：`modules/chapter_split.py:801 build_chapter_layers`（1,089 行总，核心 ~400 行）

**Rust 拆分**：

```
src/chapter_split/
├── mod.rs                       # build_chapter_layers 主编排
├── path_selector.rs             # 选择 note region 路径
├── overrides_apply.rs           # 应用 review_overrides 到 chapter_layers
└── chapter_layer_builder.rs     # 章级聚合产出 ChapterLayer
```

**公开 API**：

```rust
pub fn build_chapter_layers(
    phase1: &Phase1Input,
    note_regions: &[NoteRegionRecord],
    note_items: &[NoteItemRecord],
    overrides: Option<&ReviewOverrides>,
) -> ChapterLayers;

pub struct ChapterLayers {
    pub chapters: Vec<ChapterRecord>,  // 应用 override 后的章节
    pub regions: Vec<NoteRegionRecord>,
    pub note_items: Vec<NoteItemRecord>,
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,  // 章级 note_mode 聚合
}
```

---

### P2.9: `chapter_split/overrides_apply` — review_overrides（1.5 天)

**Python 源**：`chapter_split.py` 中 `_apply_note_item_overrides_to_chapter_layers`

**关键约束**：
- 消费 `fnm_review_overrides_v2` 表中 scope=`note_item` 的行
- 支持 `create` / `match` / `delete` / `update` 四种 action
- 应用后必须保证 `(chapter_id, note_kind, marker)` 索引唯一

---

### P2.10: `sup_recovery/layer1` + `layer2`（3 天）

**Python 源**：`modules/sup_recovery.py`（915 行，主要是 Layer 2 的 block 对齐算法）

**Rust 拆分**：

```
src/sup_recovery/
├── mod.rs           # recover_book_chapter_scoped 入口
├── layer1.rs        # Layer 1：markdown 直接匹配（无需 PDF）
└── layer2.rs        # Layer 2：OCR block 文本对齐
```

**Layer 1**：
- 输入：page markdown + 已知 chapter_markers
- 算法：扫 markdown 找 `<sup>N</sup>` / `[N]` / Unicode 上标，与 chapter_markers 对齐
- 输出：注入或修复的 sup 标记

**Layer 2**：
- 输入：OCR blocks + chapter_markers
- 算法：扫描 OCR text blocks，对每个 candidate marker 计算与已知 markers 的对齐度
- 处理 OCR 误识别（`*` → `30` 等代理符号）

**SPEC 测试覆盖**：
- `test_layer2_recovers_marker_from_symbol_after_year_fragment`
- `test_layer2_recovers_repeated_one_marker_from_ocr_punctuation_surrogate`
- `test_layer2_recovers_two_digit_marker_from_ocr_suffix`

---

### P2.11: `sup_recovery/pdf_render`（1 天）

**Python 源**：`modules/_pdf_render_worker.py`（88 行）+ `pdf_render_subprocess.py`（122 行）

**Rust 实现**（不要子进程，直接调用）：

```rust
// src/sup_recovery/pdf_render.rs
use pdfium_render::prelude::*;

pub fn render_page_to_image(
    pdf_path: &str,
    page_index: i64,
    dpi: u32,
) -> anyhow::Result<image::DynamicImage>;

pub fn render_page_to_base64_png(
    pdf_path: &str,
    page_index: i64,
    dpi: u32,
) -> anyhow::Result<String>;
```

**关键约束**：
- 用 `pdfium-render`，复用 fnm-phase1 已经引入的 pdfium 绑定
- 输出 base64 PNG，准备给 Layer 3 / visual_anchor_recovery / llm_bare_digit_verify 用

---

### P2.12: Vision LLM 部分（3 天）

**Python 源**：
- `modules/sup_recovery.py` 的 Layer 3 部分（~250 行）
- `modules/visual_anchor_recovery.py`（1,017 行）
- `modules/llm_bare_digit_verify.py`（221 行）

**Rust 拆分**：

```
src/sup_recovery/layer3.rs
src/visual_anchor_recovery/
├── mod.rs
├── gap_detection.rs
├── vision_client.rs
└── override_builder.rs
src/llm_bare_digit_verify/
├── mod.rs
├── prompt_builder.rs
├── llm_client.rs
└── response_parser.rs
```

**公开 API**：

```rust
// 异步入口（vision API 调用）
pub async fn layer3_verify_with_vision(
    pdf_path: &str,
    candidates: &[Layer3Candidate],
    config: &LlmConfig,
) -> anyhow::Result<Vec<Layer3Result>>;

pub async fn build_visual_recovery_overrides(
    pages: &[RawPage],
    chapter_markers: &HashMap<String, HashSet<String>>,
    pdf_path: &str,
    config: &LlmConfig,
) -> anyhow::Result<ReviewOverrides>;

pub async fn verify_bare_digit_candidates(
    candidates: &[BareDigitCandidate],
    pages: &[RawPage],
    pdf_path: &str,
    config: &LlmConfig,
) -> anyhow::Result<BareDigitVerifyResult>;
```

**关键技术**：
- `reqwest` + `tokio::join_all` 并发多个章级请求
- PDF 截图复用 P2.11 的 `render_page_to_base64_png`
- prompt 模板严格对齐 Python（保证 LLM 行为一致）

**SPEC 测试覆盖**：
- `test_layer3_rejects_marker_different_from_requested` — Layer 3 校验拒绝
- `test_layer3_rejects_repeated_context_location` — 唯一性校验
- `test_layer3_accepts_requested_marker`（UNCLEAR，依赖外部 API，用 mock）

---

### P2.13: 顶层编排 + DB 持久化（1.5 天）

**Python 源**：`modules/chapter_split.py:801 build_chapter_layers` 全函数 + `app/pipeline.py` 中 phase2 持久化部分

**Rust 公开 API**：

```rust
// src/lib.rs
pub async fn build_phase2_structure(
    input: Phase2Input<'_>,
) -> anyhow::Result<Phase2Output>;

pub fn persist_phase2(
    repo: &dyn fnm_core::db::Repository,
    doc_id: &str,
    output: &Phase2Output,
) -> anyhow::Result<()>;
```

**编排顺序**：
1. 应用 sup_recovery（如果 pdf_path 提供且 !skip_sup_recovery）
   - Layer 1（不依赖 PDF）
   - Layer 2（依赖 PDF render）
   - Layer 3（依赖 vision LLM）
2. `build_note_regions`
3. `build_note_items`（消费 region 的 note_kind）
4. `endnote_chapter_explorer`（book-scope endnotes 投射）
5. `endnote_repair`（续行修复）
6. `chapter_split::build_chapter_layers`（应用 overrides）
7. `visual_anchor_recovery`（构建 anchor override，留给 Phase 3 消费）
8. 聚合 `chapter_note_modes`
9. `book_structure` 聚合
10. 持久化到 DB（`replace_fnm_phase2_products`）

---

### P2.14: 端到端集成测试（2.5 天）

**测试矩阵**：

| 书籍 / 场景 | SPEC 测试 |
|---|---|
| Biopolitics 12 章 | `test_each_lecture_chapter_has_endnote_region` |
| Biopolitics 章后隐式尾注 | `test_chapter_scope_endnote_region_count` |
| 章 7 février 连续 endnote | `test_chapter_7_fevrier_has_single_endnote_region` |
| book-scope endnote 投射 | `test_book_scope_endnotes_are_projected_by_marker_to_chapters` |
| OCR split marker 重建 | `test_ocr_split_marker_can_be_reconstructed` |
| 长 endnote 完整保留 | `test_ch5_note_4_definition_is_full_length` |
| sup_recovery Layer 2 ×3 | 3 个 SPEC 测试 |
| sup_recovery Layer 3 ×2 | 2 个 SPEC 测试（mock vision API） |

每条都翻译为 Rust 集成测试。

---

## SPEC 测试翻译清单（来自 `[rust-migration: SPEC]`）

Phase 2 必须实现的 SPEC 测试（**Phase 2 占了 SPEC 总数的 10/18**，是 SPEC 最密集的 phase）：

| Rust 测试位置 | Python 来源 | 描述 |
|---|---|---|
| `test_ocr_split_marker.rs::roundtrip` | `test_fnm_re_phase2.py::test_ocr_split_marker_can_be_reconstructed` | OCR "1 2" 重建为 "12" |
| `test_biopolitics_phase2.rs::chapter_scope_endnote_count` | `test_biopolitics_chapter_endnote_regions::test_chapter_scope_endnote_region_count` | ≥ 11 章有 chapter-scope endnote |
| `test_biopolitics_phase2.rs::each_lecture_has_endnote` | `test_each_lecture_chapter_has_endnote_region` | 11 讲座章各 ≥ 1 endnote region |
| `test_chapter_endnote_consolidation.rs::7_fevrier_single_region` | `test_chapter_7_fevrier_has_single_endnote_region` | 7 février 单一连续区 |
| `test_book_scope_endnotes_projection.rs::marker_to_chapters` | `test_fnm_re_module3_split::test_book_scope_endnotes_are_projected_by_marker_to_chapters` | book-scope marker 投射 |
| `test_long_note.rs::ch5_note_4_full_length` | `test_long_note_no_truncation::test_ch5_note_4_definition_is_full_length` | 长 note ≥ 200 字符 |
| `test_sup_recovery_layer2.rs::symbol_after_year` | `test_sup_recovery::test_layer2_recovers_marker_from_symbol_after_year_fragment` | "1927-30 * ou" → 30 |
| `test_sup_recovery_layer2.rs::repeated_one_marker` | `test_layer2_recovers_repeated_one_marker_from_ocr_punctuation_surrogate` | "11" 误识别为标点 |
| `test_sup_recovery_layer2.rs::two_digit_suffix` | `test_layer2_recovers_two_digit_marker_from_ocr_suffix` | "7." → "37" |
| `test_sup_recovery_layer3.rs::rejects_different_marker` | `test_layer3_rejects_marker_different_from_requested` | Layer 3 marker 校验 |
| `test_sup_recovery_layer3.rs::rejects_repeated_context` | `test_layer3_rejects_repeated_context_location` | Layer 3 唯一性校验 |

---

## 验收 checklist

### 代码质量
- [ ] `cargo build -p fnm-phase2 --release` 通过
- [ ] `cargo clippy -p fnm-phase2 -- -D warnings` 通过
- [ ] `cargo fmt --check` 通过
- [ ] `cargo test -p fnm-phase2` 所有测试通过
- [ ] 0 个 `Rc<RefCell>` / 0 个 `Arc<Mutex>`（LLM 用量记录除外）
- [ ] 0 个不必要 `.clone()`（按 fnm-core 标准）

### Parity 测试覆盖
- [ ] note_regions：Biopolitics 全书与 Python 输出 byte-equal
- [ ] note_items：Biopolitics + 章 7 février 与 Python 输出 byte-equal
- [ ] chapter_split：12 章 ChapterLayers 与 Python 一致
- [ ] sup_recovery Layer 1/2：所有 SPEC 测试翻译并通过
- [ ] endnote_repair：长 note 不截断
- [ ] note_kind_resolver：覆盖所有决策分支 + 兜底 review_required

### DB 集成
- [ ] `persist_phase2` → `Repository::replace_fnm_phase2_products` 写入成功
- [ ] 写入后 `list_fnm_*` 读出与原 Phase2Output 等价
- [ ] **note_kind 持久化往返**：写入 endnote → 读出仍是 endnote（Issue 9 类型升级保护）

### 性能基线
- [ ] Biopolitics phase2（不含 LLM）：Rust < 5s（Python ~120s 量级）
- [ ] sup_recovery Layer 2：≥ 10x Python
- [ ] chapter_split 全流程：≥ 8x Python

### 文档
- [ ] `README.md` 说明依赖（PDFium 二进制 + LLM 配置）
- [ ] 每个 `pub fn` 有 doc comment + Python 源对应
- [ ] note_kind 决策树文档化（在 `note_kind_resolver.rs` doc 注释中画 ASCII 决策树）

---

## 工程纪律

### 1. **note_kind 唯一来源原则严格执行**

按 CLAUDE.md 第 12 条最高优先级：

- ✅ Phase 2 内部所有 note_kind 判定**必须**通过 `note_items::note_kind_resolver::resolve_note_kind()`
- ❌ 禁止在其他模块写 `if heading.contains("endnote") { NoteKind::Endnote } else { NoteKind::Footnote }`
- ❌ 禁止在 Phase 3+ crate 出现任何 `note_kind = ...` 赋值（只能透传）

实施者必须在 PR 描述里声明："note_kind 仅通过 resolve_note_kind() 决定"，违反则 CR 拒绝。

### 2. 每个任务一个 PR

P2.0 到 P2.14 共 15 个独立 PR。PR 必须：
- 通过 CI（build + clippy + fmt + test）
- 包含 parity fixture 生成代码
- 包含对应 parity 测试

### 3. Parity 测试是验收门

**任何 Rust 公开函数的输出必须 JSON byte-equal 匹配 Python 同名函数的输出**。

### 4. 严守 Phase 边界

Phase 2 **绝对不做**的事：
- 检测 body anchor（Phase 3）
- 重新分类 note_kind（Phase 2 内部唯一决定，对外 read-only）
- 调用 LLM repair（Phase 3.5）
- 章 markdown 合并（Phase 5）

发现 Python 代码越界 → 视为 Python bug，在 Rust 端**不复制**这部分逻辑，挪到对应 phase crate。

### 5. LLM 部分可降级

P2.10-P2.12 涉及 vision LLM。如果 LLM API 暂不可用：
- Layer 1/2 必须实现（CPU only）
- Layer 3 可以暂时 skip（标记为 `unimplemented!()`，但 phase2 入口要能跳过）
- `visual_anchor_recovery` / `llm_bare_digit_verify` 同样可降级

主流程跑通后（不含 LLM），Phase 3 已可启动开发。

### 6. PDF 渲染单例

`pdfium-render` 的 `Pdfium` 实例创建昂贵，要用 `once_cell::sync::Lazy` 做全局单例。避免每次 render 都重新加载 PDFium 库。

### 7. Async runtime 隔离

vision LLM 用 tokio，但非 LLM 路径**不要 async 污染**。`build_phase2_structure` 应该提供同步入口（不需要 LLM 时直接调）和异步入口（需要 LLM 时用 tokio runtime）。

```rust
pub fn build_phase2_structure_sync(input: Phase2Input) -> anyhow::Result<Phase2Output>;

pub async fn build_phase2_structure_async(input: Phase2Input) -> anyhow::Result<Phase2Output>;
```

---

## 已知风险

| 风险 | 缓解 |
|---|---|
| chapter_split 业务逻辑复杂（很多边界规则）| 严格 parity 测试，Biopolitics + Germany_Madness + 多本 fixture 比对 |
| sup_recovery Layer 2 算法精细（OCR 误识别恢复）| 单元测试覆盖每种误识别模式，与 Python 输出 byte-equal |
| Vision LLM 调用成本（钱 + 时间）| mock 客户端 trait，单元测试用 mock，集成测试可选跳过 |
| pdfium-render 跨平台二进制 | bundled 模式打包，CI 提供 macOS/Linux 验证 |
| note_kind 决策树分支多 | 决策树文档化 + 单元测试覆盖所有分支 |
| review_overrides_v2 schema 复杂 | 复用 fnm-core 的 `review_overrides` 模块；按 scope 分组 |

---

## fnm-core 可能需要的小补丁

| 需求 | 工作量 | 时机 |
|---|---|---|
| `Repository::list_fnm_review_overrides_v2` | 0.5 天 | P2.9 之前 |
| `Repository::upsert_fnm_review_overrides_v2` | 0.5 天 | P2.12 之前 |
| `Repository::stream_pages` / `count_pages`（如 Phase 1 未补）| 0.5 天 | P2.4 之前 |

---

## 下一步（P2.0 启动 checklist）

接手 P2.0 后立刻可以做的事：

1. 在 `fnm_re_rs/Cargo.toml` workspace 加 `fnm-phase2` 作为 member
2. 创建 `fnm_re_rs/fnm-phase2/` 目录与 `Cargo.toml`
3. 写 `src/lib.rs` 占位（声明所有顶层 mod）
4. 写 `tools/gen_phase2_fixtures.py` 脚手架（先生成 Biopolitics phase1_output.json 作为上游 fixture）
5. 创建 `tests/fixtures/` 目录
6. 提 PR，验收 checklist：
   - [ ] `cargo build -p fnm-phase2` 通过
   - [ ] CI 全绿
   - [ ] `cargo test -p fnm-phase2` 通过 0 测试

完成 P2.0 后，按依赖顺序推进 P2.1 → P2.14。

---

## 完成后的 Pipeline 进度

| Phase | 状态 |
|---|---|
| fnm-core | ✅ 已完成（96 测试）|
| fnm-phase1 | ✅ 已完成 |
| **fnm-phase2** | 🔄 本文档计划 |
| fnm-phase3 | ⏳ 待开始 |
| fnm-llm-repair | ⏳ 待开始 |
| fnm-phase4 | ⏳ 待开始 |
| fnm-phase5 | ⏳ 待开始 |
| fnm-phase6 | ⏳ 待开始 |
| fnm-orchestrator | ⏳ 待开始 |

Phase 2 完成后，**Phase 3 是性能最大头**（body anchor + link + DP 对齐），SPEC 测试还剩 4 个。
