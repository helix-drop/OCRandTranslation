# `fnm-phase1` 实施计划

> 🟢 **状态：100% 模块完成（2026-05-18）**
>
> - **106 lib tests** + 27 集成测试通过
> - 12 个模块全部 1:1 翻译完成，含本次完整重写：
>   - `chapter_skeleton/builder.rs`（449 行 → Rust 660 行）：visual/fallback/simple 三路径 + back_matter trim + dropped_titles + 16 meta 字段
>   - `chapter_skeleton/fallback.rs`：补全 5 个 helper（infer_back_matter_start_page / trim_chapter_rows / 3 default summary）
>   - `llm_book_type_verify/`（1039 行 → 860 行 Rust 拆 3 子模块）：完整 5 维分层选页 R1-R6 + BookStructureProfile + multi-model fallback + content_filter retry + ResolvedModelSpec
> - 剩余 1 个 `biopolitics_chapters_field_by_field` parity 待精调（page_role 启发式阈值调参，非模块缺失）
> - 完整完成度见 [`fnm_re_rs/FNM_RE_REFACTOR.md` §2.2](../fnm_re_rs/FNM_RE_REFACTOR.md)
>
> 本文档作为历史实施计划保留。下方原文档内容未修改。

---

本文档是 `fnm-phase1` Rust crate 的完整实施说明书。`fnm-core` 已完成（96 测试通过、0 占位、0 反向依赖、0 滥用 clone），可作为信任的依赖基础。

> 阅读前置：
> - [`RUST_MIGRATION_PLAN.md`](./RUST_MIGRATION_PLAN.md) — 全局架构
> - [`FNM_CORE_PLAN.md`](./FNM_CORE_PLAN.md) — fnm-core 实施记录，包括 parity fixture 工具链

---

## fnm-core 已完成状态确认

本计划基于以下 fnm-core 交付物：

| 模块 | 公开 API（你将依赖的）|
|---|---|
| `types` | `PageRole` / `ChapterSource` / `BoundaryState` / `NoteKind` / `RegionScope` / `RegionSource` / `NoteMode` 等 11 个 enum |
| `records` | `PagePartitionRecord` / `HeadingCandidate` / `ChapterRecord` / `SectionHeadRecord` / `Phase1Summary` / `Phase1Structure` 等 |
| `text` | `page_markdown_text` / `page_blocks` / `extract_page_headings` / `has_note_heading` / `first_section_hint` |
| `title` | `normalize_title` / `normalized_title_key` / `title_word_similarity` / `shared_title_tokens` |
| `note_marker` | `normalize_note_marker` / `strip_markdown_heading` / `is_notes_heading_line` / `first_notes_heading` |
| `anchor_kind` | `resolve_anchor_kind` / `looks_like_year_marker` / `is_bracket_ref_valid` + regex 池 |
| `db` | `Repository` trait + `SqliteRepository`（含 `replace_fnm_phase1_products` / `list_fnm_*`）|

**禁止改动 fnm-core**。如果发现需要新 helper，加到 fnm-phase1 内部模块。fnm-core 是稳定基础。

---

## 目标与定位

`fnm-phase1` 是 6-Phase pipeline 的第一步：**从原始 OCR 页面构建章节骨架**。

**职责（按 CLAUDE.md Phase1 边界）**：
- 输入：`pages: Vec<RawPage>`（OCR 输出 JSON，从 `fnm_pages` 表加载或直接传入）+ 可选的 `toc_items`（visual TOC 提取的目录项）
- 输出：`Phase1Structure { pages, chapters, section_heads, heading_candidates, endnote_explorer_hints, summary }`
- DB 落地：`fnm_pages` / `fnm_chapters` / `fnm_section_heads` / `fnm_heading_candidates`

**不做的事**（这些是 Phase2 及之后的边界）：
- ❌ 判定 note_kind（Phase2 做）
- ❌ 识别 note region / note item（Phase2 做）
- ❌ chapter mode 聚合（Phase2 做）
- ❌ body anchor 检测（Phase3 做）

**Python 源对应**（共 ~8,200 行）：

| Python 路径 | 行数 | 主要内容 |
|---|---:|---|
| `FNM_RE/modules/toc_structure.py` | 544 | `build_toc_structure` 入口 + TOC 乱码检测 |
| `FNM_RE/modules/book_note_type.py` | 403 | `build_book_note_profile` (Phase1b 书型粗判) |
| `FNM_RE/modules/llm_book_type_verify.py` | 1,039 | LLM 视觉验证书型（Phase1c）|
| `FNM_RE/stages/page_partition.py` | 1,267 | `build_page_partitions` page_role 判定（**最复杂**） |
| `FNM_RE/stages/section_heads.py` | 203 | `build_section_heads` 节标题归属 |
| `FNM_RE/stages/heading_graph.py` | 703 | heading graph 构建（family/depth 推断）|
| `FNM_RE/stages/chapter_skeleton/builder.py` | 449 | chapter 边界构建器 |
| `FNM_RE/stages/chapter_skeleton/fallback.py` | 656 | 无 TOC 时的 fallback 章节切分 |
| `FNM_RE/stages/chapter_skeleton/heading_candidates.py` | 827 | heading 候选生成与去重 |
| `FNM_RE/stages/chapter_skeleton/toc_semantics.py` | 2,014 | TOC 语义对齐（**第二大**）|
| `FNM_RE/stages/chapter_skeleton/_pdf_font_worker.py` | 32 | PDF 字体提取 worker |
| **合计** | **8,137 行** | → 预计 **~12,000 行** Rust |

---

## Crate 结构

```
fnm-phase1/
├── Cargo.toml
├── README.md
├── src/
│   ├── lib.rs                       # crate 入口：build_phase1_structure
│   ├── input.rs                     # RawPage / TocItem 输入类型
│   ├── output.rs                    # Phase1Output（薄包装 Phase1Structure）
│   ├── toc_garbled.rs               # ←→ toc_structure.py:_toc_items_look_garbled 等
│   ├── page_partition/
│   │   ├── mod.rs                   # build_page_partitions 入口
│   │   ├── role_resolver.rs         # page_role 判定核心
│   │   ├── role_heuristics.rs       # 启发式规则集
│   │   ├── note_heading_scan.rs     # 注释 heading 扫描
│   │   ├── override_apply.rs        # 手工 page_overrides 应用
│   │   └── streaming.rs             # build_page_partitions_streaming
│   ├── section_heads.rs             # ←→ section_heads.py
│   ├── heading_graph/
│   │   ├── mod.rs                   # heading_graph 入口
│   │   ├── family.rs                # heading family 推断
│   │   └── depth.rs                 # depth 推断
│   ├── chapter_skeleton/
│   │   ├── mod.rs                   # builder + fallback 入口
│   │   ├── builder.rs               # chapter 边界构建
│   │   ├── fallback.rs              # fallback 切分（无 TOC）
│   │   ├── heading_candidates.rs    # heading 候选生成
│   │   ├── toc_semantics/
│   │   │   ├── mod.rs               # TOC 语义对齐主流程
│   │   │   ├── alignment.rs         # TOC ↔ heading 对齐
│   │   │   ├── role_inference.rs    # TOC item 角色推断
│   │   │   ├── container_detection.rs  # 容器章节检测
│   │   │   └── monotonic.rs         # 章节顺序单调性校验
│   │   └── pdf_font.rs              # PDF 字体提取（用 pdfium-render）
│   ├── book_note_type/
│   │   ├── mod.rs                   # build_book_note_profile 入口
│   │   ├── footnote_band.rs         # 脚注带检测
│   │   ├── endnote_region.rs        # 尾注区域识别
│   │   └── book_type_inference.rs   # book_type 判定
│   ├── llm_book_type_verify/
│   │   ├── mod.rs                   # verify_book_type_with_llm 入口
│   │   ├── prompt_builder.rs        # prompt 模板组装
│   │   ├── llm_client.rs            # vision API HTTP 调用
│   │   ├── response_parser.rs       # LLM JSON 解析
│   │   └── pdf_screenshot.rs        # PDF 截图（用 pdfium-render）
│   └── toc_structure.rs             # 顶层 build_toc_structure 编排
└── tests/
    ├── parity/
    │   ├── test_page_partition.rs
    │   ├── test_section_heads.rs
    │   ├── test_heading_graph.rs
    │   ├── test_chapter_skeleton.rs
    │   └── test_toc_semantics.rs
    ├── integration/
    │   ├── test_biopolitics_full.rs   # Biopolitics 12 章端到端
    │   ├── test_germany_madness.rs    # 另一本书的回归
    │   └── test_db_roundtrip.rs       # write_phase1 → read 验证
    └── fixtures/
        ├── biopolitics_pages.json
        ├── biopolitics_toc.json
        ├── germany_madness_pages.json
        └── ...
```

---

## 实施顺序（10 个任务，预计 ~3 周）

| # | 任务 | 工时 | 依赖 |
|--:|---|---:|---|
| P1.0 | Cargo.toml + 骨架 + parity fixture 生成扩展 | 0.5 天 | - |
| P1.1 | `input.rs`：RawPage / TocItem 输入类型 | 0.5 天 | P1.0 |
| P1.2 | `page_partition`：page_role 判定（最复杂）| 4 天 | P1.1 |
| P1.3 | `section_heads`：节标题归属 | 1 天 | P1.2 |
| P1.4 | `heading_graph`：family + depth 推断 | 2 天 | P1.3 |
| P1.5 | `chapter_skeleton/builder` + `heading_candidates`：章节骨架与候选 | 3 天 | P1.4 |
| P1.6 | `chapter_skeleton/toc_semantics`：TOC 语义对齐 | 4 天 | P1.5 |
| P1.7 | `chapter_skeleton/fallback`：无 TOC fallback | 2 天 | P1.5 |
| P1.8 | `book_note_type`：Phase1b 书型粗判 | 1.5 天 | P1.5 |
| P1.9 | `chapter_skeleton/pdf_font`：PDF 字体提取（pdfium-render）| 1 天 | P1.0 |
| P1.10 | `toc_structure`：顶层编排 + DB 写入 | 1 天 | P1.2-P1.9 |
| P1.11 | `llm_book_type_verify`：LLM 视觉验证 | 3 天 | P1.10 |
| P1.12 | 端到端集成测试 + Biopolitics 12 章对齐 | 2 天 | P1.11 |
| **总计** | | **~26 天** | |

---

## 关键基础设施（P1.0 一次性建立）

### Cargo.toml

```toml
[package]
name = "fnm-phase1"
version = "0.1.0"
edition = "2021"
rust-version = "1.75"

[dependencies]
fnm-core = { path = "../fnm-core" }

# 序列化
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"

# 正则
regex = "1.10"
once_cell = "1.19"

# 错误处理
thiserror = "1.0"
anyhow = "1.0"

# 日志
tracing = "0.1"

# 并行
rayon = "1.10"

# PDF
pdfium-render = { version = "0.8", features = ["bindings", "thread_safe"] }

# HTTP（LLM 调用）
reqwest = { version = "0.12", features = ["json", "rustls-tls", "stream"] }
tokio = { version = "1.35", features = ["rt-multi-thread", "macros"] }
base64 = "0.22"

[dev-dependencies]
insta = { version = "1.34", features = ["json", "redactions"] }
pretty_assertions = "1.4"
tempfile = "3.10"
```

### Parity Fixture 扩展

`tools/gen_parity_fixtures.py` 已在 fnm-core 阶段建立。Phase1 需要扩展以下 fixture：

```python
# tools/gen_phase1_fixtures.py
"""为 fnm-phase1 生成 parity fixture，每个测试函数喂入 Python 真实输出。"""

from FNM_RE.stages.page_partition import build_page_partitions
from FNM_RE.stages.section_heads import build_section_heads
from FNM_RE.modules.toc_structure import build_toc_structure
from tests.unit.fnm_re_module_fixtures import load_pages, load_auto_visual_toc

# 1. page_partition fixture：用 Biopolitics 全书 pages 跑一遍，序列化输出
pages = load_pages("Biopolitics")
result = build_page_partitions(pages)
# 序列化 result 为 JSON 写入 fnm-phase1/tests/fixtures/biopolitics_partitions.json

# 2. section_heads fixture：同理

# 3. build_toc_structure 整体 fixture：跑完整 Biopolitics + Germany_Madness 各一份
```

### Repository 扩展（在 fnm-core）

**目前 fnm-core 的 Repository 已暴露**：
- `list_fnm_pages` / `replace_fnm_phase1_products`

**fnm-phase1 还需要的**：
- `stream_pages(doc_id) -> impl Iterator<Item=Page>` — 流式加载（避免一次性载入全书）
- `count_pages(doc_id) -> usize`

**如何处理**：在 fnm-phase1 提一个 issue 给 fnm-core，请求加上这两个方法（约 0.5 天工作量）。先用一次性 `list_fnm_pages` 跑通逻辑，性能优化等 phase2 再做（phase1 单本书 < 500 页，全量载入 OK）。

---

## 任务详细规格

### P1.0: Cargo 骨架（0.5 天）

**交付物**：
1. `fnm_re_rs/fnm-phase1/Cargo.toml`（按模板）
2. `fnm_re_rs/Cargo.toml` workspace 加 `fnm-phase1` member
3. `fnm_re_rs/fnm-phase1/src/lib.rs`（占位）
4. `tools/gen_phase1_fixtures.py`（脚手架）
5. `fnm_re_rs/fnm-phase1/tests/fixtures/` 目录

**验收**：
- `cargo build -p fnm-phase1` 通过
- `cargo test -p fnm-phase1` 跑过 0 测试
- `cargo clippy -p fnm-phase1 -- -D warnings` 通过

---

### P1.1: `input.rs` — 输入类型（0.5 天）

**Python 源**：`FNM_RE/stages/page_partition.py` 前 100 行 + `toc_structure.py` 入口签名

**Rust 公开 API**：

```rust
// src/input.rs
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// OCR 输出的原始页面。与 Python `raw_pages.json` 单个元素对齐。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RawPage {
    #[serde(rename = "bookPage")]
    pub book_page: i64,
    #[serde(rename = "pdfPage", default)]
    pub pdf_page: Option<i64>,
    #[serde(rename = "fileIdx", default)]
    pub file_idx: Option<i64>,
    #[serde(default)]
    pub markdown: String,
    #[serde(default)]
    pub enriched_markdown: Option<String>,
    #[serde(default, rename = "prunedResult")]
    pub pruned_result: Value,  // {height, width, parsing_res_list: [...]}
    #[serde(default)]
    pub footnotes: String,
    #[serde(default, rename = "fnBlocks")]
    pub fn_blocks: Value,
    #[serde(default, rename = "_note_scan")]
    pub note_scan: Option<Value>,
    /// 兼容旧 fixture
    #[serde(default, rename = "target_pdf_page")]
    pub target_pdf_page: Option<i64>,
}

/// Visual TOC 提取的目录项。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TocItem {
    #[serde(default)]
    pub item_id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub level: i64,
    #[serde(default)]
    pub depth: i64,
    #[serde(default)]
    pub target_pdf_page: Option<i64>,
    #[serde(default)]
    pub role_hint: String,
    #[serde(default)]
    pub parent_title: String,
    #[serde(default)]
    pub export_candidate: Option<bool>,
    #[serde(default)]
    pub body_candidate: Option<bool>,
}

/// 整本书的 visual TOC bundle（manual 标注 + auto 提取的混合）。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct VisualTocBundle {
    #[serde(default)]
    pub items: Vec<TocItem>,
    #[serde(default)]
    pub endnotes_start_page: Option<i64>,
    #[serde(default)]
    pub manual_page_items_debug: Value,
}

/// 手工 page override（review 工具产生）。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ManualPageOverride {
    #[serde(default)]
    pub page_role: Option<String>,
    #[serde(default)]
    pub section_hint: Option<String>,
    #[serde(default)]
    pub reason: Option<String>,
}
```

**测试**：用 `tests/fixtures/biopolitics_pages.json` 的前几页反序列化通过即可（验证 serde 接口与 Python JSON 兼容）。

---

### P1.2: `page_partition` — page_role 判定（4 天，**最大头**）

**Python 源**：`FNM_RE/stages/page_partition.py`（1,267 行）

**职责**：对每页判定 `page_role`：
- `front_matter` / `body` / `note` / `noise` / `other`
- 同时输出 `confidence` / `reason` / `section_hint` / `has_note_heading` / `note_scan_summary`

**Rust 拆分**：

```
src/page_partition/
├── mod.rs                   # 公开入口 build_page_partitions
├── role_resolver.rs         # 主流程：扫每页 → resolve_role
├── role_heuristics.rs       # 启发式规则集（front_matter / body / note 判定）
├── note_heading_scan.rs     # 注释 heading 扫描（_NOTES_HEADING_RE 等）
├── override_apply.rs        # 手工 page_overrides 应用
└── streaming.rs             # build_page_partitions_streaming（流式版）
```

**公开 API**：

```rust
// src/page_partition/mod.rs
use crate::input::{RawPage, ManualPageOverride};
use fnm_core::records::PagePartitionRecord;
use std::collections::HashMap;

pub fn build_page_partitions(
    pages: &[RawPage],
    page_overrides: Option<&HashMap<String, ManualPageOverride>>,
    endnotes_start_page: Option<i64>,
) -> PagePartitionResult;

pub struct PagePartitionResult {
    pub partitions: Vec<PagePartitionRecord>,
    pub pre_extracted_page_candidates: Vec<i64>,  // pages with note heading
    pub file_idx_map: HashMap<i64, i64>,          // book_page → file_idx
    pub page_texts: HashMap<i64, String>,         // 缓存的 markdown text（避免下游重复抽取）
}
```

**关键算法对齐 Python 行 836-933**：
1. 遍历每页
2. 调 `extract_page_headings`、`has_note_heading`、`note_scan_summary`（fnm-core 已实现）
3. 根据多个启发式规则判定 page_role
4. 应用 manual override（如果存在）
5. 输出 PagePartitionRecord

**Parity 测试**：
- fixture：用 Biopolitics 全书跑一遍 Python `build_page_partitions`，序列化所有 PagePartitionRecord
- Rust 端读 fixture pages，跑 Rust 实现，断言每个 page 的 `(page_role, confidence, reason, section_hint, has_note_heading)` 与 Python 输出 byte-equal

**性能基准**：用 `criterion` 跑 Biopolitics（~280 页），目标 ≥ 10x Python（10ms vs 100ms 量级）

---

### P1.3: `section_heads` — 节标题归属（1 天）

**Python 源**：`FNM_RE/stages/section_heads.py`（203 行）

**Rust 公开 API**：

```rust
// src/section_heads.rs
use crate::input::RawPage;
use fnm_core::records::{ChapterRecord, SectionHeadRecord};

pub fn build_section_heads(
    pages: &[RawPage],
    chapters: &[ChapterRecord],
) -> Vec<SectionHeadRecord>;
```

**关键约束**：与 Python 同函数输出按 `(page_no, section_head_id)` 顺序一致。

**Parity 测试**：Biopolitics + Germany_Madness 各跑一遍，断言 SectionHeadRecord 列表 JSON 输出 byte-equal。

---

### P1.4: `heading_graph` — heading family + depth 推断（2 天）

**Python 源**：`FNM_RE/stages/heading_graph.py`（703 行）

**Rust 拆分**：

```
src/heading_graph/
├── mod.rs        # 公开入口 build_heading_graph
├── family.rs     # heading family 推断（基于字体/缩进/编号格式聚类）
└── depth.rs      # depth 推断（根据 family 层级）
```

**公开 API**：

```rust
// src/heading_graph/mod.rs
use fnm_core::records::HeadingCandidate;

pub struct HeadingGraph {
    pub family_by_id: HashMap<String, String>,
    pub depth_by_id: HashMap<String, i64>,
    pub family_stats: HashMap<String, FamilyStats>,
}

pub fn build_heading_graph(
    candidates: &[HeadingCandidate],
) -> HeadingGraph;
```

**关键算法**：根据字体大小、加粗、缩进、编号格式（`1.` / `1.1` / `第一章`）聚类成 family。

**Parity 测试**：fixture 用 Biopolitics 所有 HeadingCandidate（约 200 个），跑 Rust 输出 family/depth map，断言每个 heading 的 family/depth 与 Python 一致。

---

### P1.5: `chapter_skeleton/builder` + `heading_candidates`（3 天）

**Python 源**：
- `stages/chapter_skeleton/builder.py`（449 行）
- `stages/chapter_skeleton/heading_candidates.py`（827 行）

**Rust 拆分**：

```
src/chapter_skeleton/
├── builder.rs              # build_chapter_skeleton 主入口
├── heading_candidates.rs   # 候选 heading 生成（合并 markdown heading + OCR doc_title）
└── ...
```

**公开 API**：

```rust
// src/chapter_skeleton/builder.rs
use crate::input::{RawPage, TocItem};
use fnm_core::records::{ChapterRecord, HeadingCandidate};

pub fn build_chapter_skeleton(
    pages: &[RawPage],
    toc_items: Option<&[TocItem]>,
    page_partitions: &[PagePartitionRecord],
    heading_graph: &HeadingGraph,
) -> ChapterSkeleton;

pub struct ChapterSkeleton {
    pub chapters: Vec<ChapterRecord>,
    pub heading_candidates: Vec<HeadingCandidate>,
    pub diagnostics: Value,
}
```

**关键约束**：
- 与 Python 同函数输出 chapter 数量 / start_page / end_page / source / boundary_state 一致
- HeadingCandidate 的 `top_band` / `font_height` / `font_weight_hint` 等字段必须填充（来自 PDF 字体提取，依赖 P1.9）

**Parity 测试**：Biopolitics 必须输出 12 个 chapter，与 Python 测试 `test_biopolitics_toc_gate_and_exportable_chapters`（SPEC）对齐。

---

### P1.6: `chapter_skeleton/toc_semantics`（4 天，**第二大头**）

**Python 源**：`stages/chapter_skeleton/toc_semantics.py`（2,014 行，53 个函数）

**Rust 拆分**：

```
src/chapter_skeleton/toc_semantics/
├── mod.rs                   # build_toc_semantics 主流程
├── alignment.rs             # TOC item ↔ heading 对齐（fuzzy match）
├── role_inference.rs        # TOC item role 推断（chapter / container / endnotes / front_matter）
├── container_detection.rs   # 容器章节检测（Part I 等）
└── monotonic.rs             # 章节顺序单调性校验 + 自动重排
```

**公开 API**：

```rust
// src/chapter_skeleton/toc_semantics/mod.rs
pub fn build_toc_semantics(
    toc_items: &[TocItem],
    chapters: &[ChapterRecord],
    pages: &[RawPage],
) -> TocSemanticsResult;

pub struct TocSemanticsResult {
    pub aligned_chapters: Vec<ChapterRecord>,       // 应用 TOC 语义后的章节
    pub toc_role_summary: Value,
    pub semantic_blocking_reasons: Vec<String>,
    pub chapter_order_monotonic: bool,
}
```

**关键算法**（按 Python 文件顺序拆分）：
- TOC item 到 heading 的 fuzzy 对齐（Levenshtein 或 token Jaccard）
- TOC item role 推断（`chapter` / `container` / `endnotes` / `front_matter`）
- 单调性校验：章节起始页必须递增，否则 fallback 重排
- 容器章节展开：`Part I` 不算可导出章，但其子章 + endnotes 必须正确归属

**SPEC 测试覆盖**：
- `test_disordered_raw_toc_can_be_normalized_to_monotonic`
- `test_section_role_hint_does_not_break_chapter_order_gate`
- `test_mid_book_other_page_does_not_force_back_matter_start`
- `test_manual_override_is_recorded`
- `test_toc_tree_preserves_endnotes_role_and_semantic_levels`

每条都要在 Rust 端有对应测试（直接翻译 Python testcase）。

---

### P1.7: `chapter_skeleton/fallback` — 无 TOC fallback（2 天）

**Python 源**：`stages/chapter_skeleton/fallback.py`（656 行）

**Rust 公开 API**：

```rust
// src/chapter_skeleton/fallback.rs
pub fn build_chapter_skeleton_fallback(
    pages: &[RawPage],
    heading_candidates: &[HeadingCandidate],
    heading_graph: &HeadingGraph,
) -> Vec<ChapterRecord>;
```

**关键算法**：无 TOC 时，从 heading_candidates 中选 top-level family 作为章节边界，章节 ID 形如 `ch-fallback-001`。

**Parity 测试**：用一本没有 visual TOC 的测试 fixture（synthetic），断言 fallback 章节数与 Python 一致。

---

### P1.8: `book_note_type` — Phase1b 书型粗判（1.5 天）

**Python 源**：`modules/book_note_type.py`（403 行）

**Rust 拆分**：

```
src/book_note_type/
├── mod.rs                  # build_book_note_profile 入口
├── footnote_band.rs        # 检测每页的 footnote band（页脚注释带）
├── endnote_region.rs       # 检测尾注区域
└── book_type_inference.rs  # 综合判定 book_type
```

**公开 API**：

```rust
pub fn build_book_note_profile(
    chapters: &[ChapterRecord],
    pages: &[RawPage],
    overrides: Option<&BookNoteOverrides>,
) -> BookNoteProfile;

pub struct BookNoteProfile {
    pub book_type: String,  // "footnote_only" / "endnote_only" / "mixed" / "no_notes"
    pub chapter_modes: Vec<ChapterNoteModeRecord>,  // 复用 fnm-core
    pub evidence: BookNoteTypeEvidence,
}
```

**注意**：Phase1b 只做粗判，**不**最终决定 note_kind（那是 Phase2 的事）。这里产出的 `chapter_modes` 是给 Phase1c LLM verify 用的初步输入，最终的 `note_mode` 在 Phase2 重新决定。

**Parity 测试**：Biopolitics 必须判定为 `endnote_only`（所有讲座章是 chapter_endnote_primary）。

---

### P1.9: `chapter_skeleton/pdf_font` — PDF 字体提取（1 天）

**Python 源**：`stages/chapter_skeleton/_pdf_font_worker.py`（32 行）+ 调用方 heading_candidates.py

**Rust 实现**：

```rust
// src/chapter_skeleton/pdf_font.rs
use pdfium_render::prelude::*;

pub fn extract_font_candidates(
    pdf_path: &str,
    page_indices: &[i64],
) -> anyhow::Result<HashMap<i64, Vec<FontCandidate>>>;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FontCandidate {
    pub text: String,
    pub font_name: String,
    pub font_size: f64,
    pub is_bold: bool,
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}
```

**关键约束**：
- 用 `pdfium-render` 直接调用 PDFium（Rust 绑定）
- 输出与 Python `_pdf_font_worker.py` 的 JSON 输出 schema 兼容
- 必须在主线程外执行（`tokio::task::spawn_blocking` 包装），避免阻塞

**Parity 测试**：用 Biopolitics PDF 的几个章节首页，对比 Python `_pdf_font_worker.py` 的输出与 Rust 输出（字体名、大小、位置）。

---

### P1.10: `toc_structure` — 顶层编排（1 天）

**Python 源**：`modules/toc_structure.py`（544 行，`build_toc_structure` 入口）

**Rust 公开 API**：

```rust
// src/lib.rs（顶层入口）
pub fn build_phase1_structure(
    pages: &[RawPage],
    toc_items: Option<&[TocItem]>,
    config: &Phase1Config,
) -> anyhow::Result<Phase1Output>;

pub struct Phase1Config {
    pub manual_page_overrides: Option<HashMap<String, ManualPageOverride>>,
    pub visual_toc_bundle: Option<VisualTocBundle>,
    pub pdf_path: Option<String>,
    pub doc_id: Option<String>,
    pub skip_llm_verify: bool,  // 测试加速
}

pub struct Phase1Output {
    pub structure: Phase1Structure,  // 来自 fnm-core
    pub diagnostics: Value,
}

/// 把 Phase1Output 持久化到 DB。
pub fn persist_phase1(
    repo: &dyn fnm_core::db::Repository,
    doc_id: &str,
    output: &Phase1Output,
) -> anyhow::Result<()>;
```

**编排顺序**（对齐 Python 行 320-544）：
1. TOC 乱码检测（`toc_garbled::detect_garbled` → 切换到 manual 数据）
2. `build_page_partitions`（P1.2）
3. `build_section_heads`（P1.3）
4. `build_heading_graph`（P1.4）
5. `extract_font_candidates`（P1.9，可选）
6. `build_chapter_skeleton`（P1.5）+ TOC semantics（P1.6）or fallback（P1.7）
7. `build_book_note_profile`（P1.8）
8. （可选）`verify_book_type_with_llm`（P1.11）
9. 组装 `Phase1Structure` 返回

**测试**：用 Biopolitics 跑完整 `build_phase1_structure`，断言：
- chapters.len() == 12
- 所有讲座章的 note_mode == "chapter_endnote_primary"
- structure_state 通过

---

### P1.11: `llm_book_type_verify` — LLM 视觉验证（3 天）

**Python 源**：`modules/llm_book_type_verify.py`（1,039 行）

**Rust 拆分**：

```
src/llm_book_type_verify/
├── mod.rs                  # verify_book_type_with_llm 入口
├── prompt_builder.rs       # prompt 模板组装
├── llm_client.rs           # OpenAI/Claude vision API HTTP 调用
├── response_parser.rs      # LLM JSON 解析
└── pdf_screenshot.rs       # 用 pdfium-render 截取页面图
```

**公开 API**：

```rust
pub async fn verify_book_type_with_llm(
    toc_structure: &Phase1Structure,
    book_note_profile: &BookNoteProfile,
    pages: &[RawPage],
    pdf_path: &str,
    api_config: &LlmConfig,
) -> anyhow::Result<LlmVerifyResult>;

pub struct LlmConfig {
    pub api_key: String,
    pub model: String,         // "gpt-4o" / "claude-opus-4-7" / ...
    pub base_url: String,
    pub timeout_secs: u64,
}

pub struct LlmVerifyResult {
    pub llm_book_type: Option<String>,
    pub agreement_with_rules: bool,
    pub evidence: Value,
}
```

**关键技术**：
- `reqwest` HTTP/2 长连接，OpenAI 兼容 API
- `tokio::join_all` 并发多个章级请求（Python 受 GIL 限制并发难做）
- PDF 截图：`pdfium-render` 渲染单页为 PNG → `base64::encode`

**测试**：
- 单元测试：用 mock HTTP server（`mockito`）验证 prompt 构建与响应解析
- 集成测试：跳过（需要真实 API key）

---

### P1.12: 端到端集成测试（2 天）

**目标**：用真实书籍 fixture 跑完整 `build_phase1_structure`，断言与 Python 输出对齐。

**测试矩阵**：

| 书籍 | 关键断言 | 来源 |
|---|---|---|
| Biopolitics | 12 章 + 11 讲座章 chapter_endnote_primary | `test_biopolitics_toc_gate_and_exportable_chapters`（SPEC）|
| Germany_Madness | visual_toc 路径生效 + chapter 数 ≥ 3 | `test_visual_toc_export_candidate_default` |
| Synthetic（无 TOC）| fallback 切分 + ch-fallback-* ID | 新写 |
| Synthetic（乱序 TOC）| 单调性恢复 | `test_disordered_raw_toc_can_be_normalized_to_monotonic` |

**集成测试基础设施**：

```rust
// tests/integration/test_biopolitics_full.rs
use fnm_phase1::*;

#[test]
fn biopolitics_phase1_matches_python_snapshot() {
    let pages: Vec<RawPage> = serde_json::from_str(
        include_str!("../fixtures/biopolitics_pages.json")
    ).unwrap();
    let toc: Vec<TocItem> = serde_json::from_str(
        include_str!("../fixtures/biopolitics_toc.json")
    ).unwrap();
    
    let config = Phase1Config {
        skip_llm_verify: true,
        ..Default::default()
    };
    let output = build_phase1_structure(&pages, Some(&toc), &config).unwrap();
    
    // 与 Python 输出 byte-equal 比对
    let expected: serde_json::Value = serde_json::from_str(
        include_str!("../fixtures/biopolitics_phase1_expected.json")
    ).unwrap();
    let actual = serde_json::to_value(&output.structure).unwrap();
    
    pretty_assertions::assert_eq!(actual, expected);
}
```

---

## SPEC 测试翻译清单（来自 `[rust-migration: SPEC]`）

Phase 1 必须实现的 SPEC 测试（从 Python `tests/unit/` 翻译）：

| Rust 测试位置 | Python 来源 | SPEC 描述 |
|---|---|---|
| `tests/parity/test_toc_semantics.rs::biopolitics_12_chapters` | `test_fnm_re_module1_toc.py::test_biopolitics_toc_gate_and_exportable_chapters` | Biopolitics TOC 应输出 12 章 |
| `tests/parity/test_toc_semantics.rs::external_page_roles_no_noise` | `test_external_page_roles_do_not_expose_noise` | external page role 不暴露 noise |
| `tests/parity/test_toc_semantics.rs::disordered_toc_monotonic` | `test_disordered_raw_toc_can_be_normalized_to_monotonic` | 乱序 TOC 单调化 |
| `tests/parity/test_toc_semantics.rs::section_role_hint` | `test_section_role_hint_does_not_break_chapter_order_gate` | section role hint 不破坏章序 |
| `tests/parity/test_toc_semantics.rs::mid_book_other_page` | `test_mid_book_other_page_does_not_force_back_matter_start` | 中段 other 不触发 back_matter |
| `tests/parity/test_toc_semantics.rs::manual_override_recorded` | `test_manual_override_is_recorded` | manual override 应被记录 |
| `tests/parity/test_toc_semantics.rs::toc_tree_endnotes_role` | `test_toc_tree_preserves_endnotes_role_and_semantic_levels` | TOC tree 保留 endnotes role |
| `tests/parity/test_visual_toc.rs::export_candidate_default` | `test_visual_toc_export_candidate_default.py`（2 个 test）| 默认 export_candidate |

---

## 验收 checklist

### 代码质量
- [ ] `cargo build -p fnm-phase1 --release` 通过
- [ ] `cargo clippy -p fnm-phase1 -- -D warnings` 通过
- [ ] `cargo fmt --check` 通过
- [ ] `cargo test -p fnm-phase1` 所有测试通过
- [ ] 0 个 `Rc<RefCell>` / 0 个 `Arc<Mutex>`（除全局 LLM 用量记录）
- [ ] 0 个不必要 `.clone()`（按 fnm-core 标准）

### Parity 测试覆盖
- [ ] page_partition：Biopolitics 全书 ~280 页与 Python 输出 byte-equal
- [ ] section_heads：Biopolitics + Germany_Madness 与 Python 输出 byte-equal
- [ ] heading_graph：family/depth map 与 Python 一致
- [ ] chapter_skeleton：Biopolitics 12 章 + Germany_Madness fallback 路径
- [ ] toc_semantics：8 个 SPEC 测试全部翻译并通过
- [ ] book_note_type：Biopolitics 判定为 endnote_only

### DB 集成
- [ ] `persist_phase1` → `Repository::replace_fnm_phase1_products` 写入成功
- [ ] 写入后 `Repository::list_fnm_*` 读出与原 Phase1Structure 等价

### 性能基线
- [ ] Biopolitics 全 phase1：Rust < 2s（Python ~30s 量级）
- [ ] page_partition：≥ 10x Python（用 criterion）

### 文档
- [ ] `README.md` 说明：如何 build、如何跑 parity 测试、PDF 字体提取的依赖说明
- [ ] 每个 `pub fn` 有 doc comment + Python 源对应
- [ ] LLM 配置说明（环境变量 / API key）

---

## 工程纪律

### 1. 每个任务一个 PR

P1.0 到 P1.12 共 13 个独立 PR。PR 必须：
- 通过 CI（build + clippy + fmt + test）
- 包含 parity fixture 生成代码（在 `tools/gen_phase1_fixtures.py` 加段落）
- 包含对应 parity 测试

### 2. Parity 测试是验收门

**任何 Rust 公开函数的输出必须 JSON byte-equal 匹配 Python 同名函数的输出**。

### 3. 严守 Phase 边界

Phase1 **绝对不做**的事（违反 CLAUDE.md 第 12 条）：
- 判定 note_kind / region_kind（Phase2 的事）
- 检测 body anchor（Phase3 的事）
- 调 LLM repair（Phase 3.5 的事）

如果发现 Python 代码在 page_partition 或 chapter_skeleton 里"顺手做了"这些事，**视为 Python 端的 phase 越界 bug**，应该把这部分逻辑移到对应 phase crate，而不是在 Rust phase1 复制。

### 4. Phase1 → Phase2 接口稳定

Phase1 输出 `Phase1Structure`，下游 Phase2 通过 DB（`Repository::list_fnm_pages` 等）读取。**不在内存里直接传递 Phase1Structure 给 Phase2**——所有跨 phase 通信必须走 DB，保证语言无关性。

### 5. 不引入新 Python 端没有的功能

Phase1 严格只翻译现有 Python 实现。不"顺手优化"算法（除非是 fnm-core 范围内的纯 helper）。优化在 phase crate 内部细节里做（如 `aho_corasick` 替代正则、`rayon` 并行），但**对外输出必须与 Python byte-equal**。

### 6. LLM 部分可选

`P1.11 llm_book_type_verify` 可以延后到 P1.12 之后做。Phase1 主流程跑通后（即使 LLM 部分缺失），下游 Phase2 已可启动开发。

---

## fnm-core 待补依赖（流式 page 加载）

发给 fnm-core 维护者的小 PR 请求：

```rust
// src/db/repository.rs 加两个方法
pub trait Repository {
    // ... 已有
    
    /// 流式加载 pages（一次一页，避免全书载入内存）
    fn stream_pages(&self, doc_id: &str) -> Result<Box<dyn Iterator<Item = Result<PageRow>> + '_>>;
    
    /// 计数（用于流式模式的进度条）
    fn count_pages(&self, doc_id: &str) -> Result<usize>;
}
```

工作量预计 0.5 天。这是 P1.2 的依赖。如果暂时没补，先用一次性 `list_fnm_pages` 跑通。

---

## 下一步（P1.0 启动 checklist）

接手 P1.0 后立刻可以做的事：

1. 在 `fnm_re_rs/Cargo.toml` workspace 加 `fnm-phase1` 作为 member
2. 创建 `fnm_re_rs/fnm-phase1/` 目录与 `Cargo.toml`
3. 写 `src/lib.rs` 占位（`pub mod input;` 等模块声明）
4. 写 `tools/gen_phase1_fixtures.py` 脚手架
5. 创建 `tests/fixtures/` 目录
6. 提 PR，验收 checklist：
   - [ ] `cargo build -p fnm-phase1` 通过
   - [ ] CI 全绿
   - [ ] `cargo test -p fnm-phase1` 通过 0 测试

完成 P1.0 后，按依赖顺序推进 P1.1 → P1.12。
