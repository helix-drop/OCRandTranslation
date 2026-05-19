# B 模型 Rust 重构任务清单 — V2（C1 + F2+/F3+/F4+/F7+ + F12+ + V1）

R1-R4 + G1-G5 全部通过（你之前做的）。这份是**下一批任务**。

> R1-R4 + G1-G5 验收结论：你的代码风格已经对齐高保真标准（Lazy regex、单例 + 速率限制并发、子模块拆分、复用 fnm-core）。**这批任务继续按这个标准执行**。

---

## 0. 必读前置

- **[`/Users/hao/OCRandTranslation/AGENTS.md`](/Users/hao/OCRandTranslation/AGENTS.md)** 的 "Rust 重构代码规范" 12 条铁律——**做之前再看一遍**
- **[`/Users/hao/OCRandTranslation/FNM_RE/FNM_PHASE12_B_TASKS.md`](/Users/hao/OCRandTranslation/FNM_RE/FNM_PHASE12_B_TASKS.md)** V1 任务（R+G 已做完，作参考）
- **[`/Users/hao/OCRandTranslation/FNM_RE/FNM_PHASE12_AUDIT.md`](/Users/hao/OCRandTranslation/FNM_RE/FNM_PHASE12_AUDIT.md)** 审计发现

---

## 1. 任务总览

| 任务 | 主题 | 工时 | 顺序 |
|---|---|---:|:---:|
| C1 | fnm-core 加 `vision` 模块：抽 PDFIUM + HTTP_CLIENT + render_page_to_base64_png | 0.5 天 | 1（先做）|
| F7+ | `page_partition/role_heuristics.rs` 严格保真补完（534 → ~800 行）| 2 天 | 2 |
| F4+ | `heading_candidates.rs` 字体检测 + family 聚类 + reject 启发式（150 → ~700 行）| 3 天 | 3 |
| F2+ | `note_regions/mod.rs` 拆 5 子模块 + 补完（461 → ~700 行）| 3 天 | 4 |
| F3+ | `note_items/mod.rs` 拆子模块 + 补完（348 → ~500 行）| 2 天 | 5 |
| F12+ | parity 断言收紧 + Biopolitics 端到端 byte-equal | 2 天 | 6（最后做）|
| V1 | 19 个 SPEC 测试翻译验证（已有 17 个 spec_test，补齐剩余 2 个）| 0.5 天 | 与 F12+ 并行 |
| **总计** | | **~13 天** | |

完成顺序严格按 1→6（C1 是基础，F12+ 是最终验收）。

---

## 2. C1: fnm-core 加 vision 模块（0.5 天，**先做**）

### 现状

PDFIUM 单例 + HTTP_CLIENT 单例 + `render_page_to_base64_png` 在 phase1 和 phase2 各重复一份：

| 模块 | phase1 位置 | phase2 位置 |
|---|---|---|
| `Lazy<Mutex<Pdfium>>` | `llm_book_type_verify/mod.rs:17` | `sup_recovery/pdf_render.rs:12` |
| `Lazy<Client>` | `llm_book_type_verify/mod.rs:24` | `sup_recovery/layer3.rs:12` |
| `render_page_to_base64_png` | `llm_book_type_verify/mod.rs:61-83` | `sup_recovery/pdf_render.rs` |

phase1 不能引用 phase2，所以重复。

### 目标

在 `fnm-core` 新增 `vision` 模块，phase1/phase2 都从这里 use。

### 步骤

#### C1.1 — 新增 `fnm_re_rs/fnm-core/src/vision/`

```
fnm_re_rs/fnm-core/src/vision/
├── mod.rs          # 公开 API
├── pdfium.rs       # Lazy<Mutex<Pdfium>> + render_page_to_base64_png
└── http.rs         # Lazy<Client> + VisionConfig
```

#### C1.2 — `fnm-core/src/vision/pdfium.rs`

```rust
//! PDFIUM 单例 + PDF 页渲染。
//! ←→ FNM_RE/modules/_pdf_render_worker.py

use anyhow::{Context, Result};
use base64::Engine;
use once_cell::sync::Lazy;
use pdfium_render::prelude::*;
use std::sync::Mutex;

/// 全局 Pdfium 实例（懒加载、线程安全）。
pub static PDFIUM: Lazy<Mutex<Pdfium>> = Lazy::new(|| {
    let bindings = Pdfium::bind_to_system_library()
        .or_else(|_| Pdfium::bind_to_library(Pdfium::pdfium_platform_library_name_at_path("./")))
        .expect("无法加载 PDFium 二进制库");
    Mutex::new(Pdfium::new(bindings))
});

/// 渲染 PDF 单页为 base64 PNG（供 vision LLM 调用）。
/// 
/// ←→ Python `_pdf_render_worker.render_page_to_image_png_base64()`
pub fn render_page_to_base64_png(pdf_path: &str, page_index: i64, dpi: u32) -> Result<String> {
    // 把现有 fnm-phase2/src/sup_recovery/pdf_render.rs 的实现搬过来
    // 参数签名保持 (pdf_path, page_index: i64, dpi: u32)
    // ...
}
```

#### C1.3 — `fnm-core/src/vision/http.rs`

```rust
//! HTTP 客户端单例 + Vision API 配置。

use once_cell::sync::Lazy;
use reqwest::Client;
use std::time::Duration;

/// 全局 HTTP client（180s timeout，rustls-tls）。
/// 供所有 LLM/Vision 调用共享，避免每次新建。
pub static HTTP_CLIENT: Lazy<Client> = Lazy::new(|| {
    Client::builder()
        .timeout(Duration::from_secs(180))
        .build()
        .expect("构造 HTTP client 失败")
});

/// Vision LLM 配置（从环境变量或默认值构造）。
#[derive(Debug, Clone)]
pub struct VisionConfig {
    pub api_key: String,
    pub model: String,
    pub base_url: String,
}

impl Default for VisionConfig {
    fn default() -> Self {
        Self {
            api_key: std::env::var("OPENAI_API_KEY").unwrap_or_default(),
            model: "gpt-4o".into(),
            base_url: "https://api.openai.com/v1".into(),
        }
    }
}
```

#### C1.4 — `fnm-core/src/vision/mod.rs`

```rust
//! Vision LLM 共享基础设施：PDFIUM 单例 + HTTP_CLIENT 单例 + 配置。
//! 
//! 被 fnm-phase1::llm_book_type_verify 和 fnm-phase2::sup_recovery / visual_anchor_recovery
//! / llm_bare_digit_verify 共享。

pub mod pdfium;
pub mod http;

pub use pdfium::{render_page_to_base64_png, PDFIUM};
pub use http::{HTTP_CLIENT, VisionConfig};
```

#### C1.5 — `fnm-core/src/lib.rs` 加 `pub mod vision;`

#### C1.6 — fnm-core/Cargo.toml 加依赖

```toml
[dependencies]
# ... 已有
pdfium-render = { version = "0.8", features = ["bindings", "thread_safe"] }
reqwest = { version = "0.12", features = ["json", "rustls-tls"] }
base64 = "0.22"
image = { version = "0.25", default-features = false, features = ["png"] }
```

注意：`reqwest` 加 fnm-core 后会拉 tokio。**fnm-core 不引入 tokio runtime**——只用 reqwest 的 async client，runtime 由调用方（phase crate）提供。

#### C1.7 — 删除 phase1/phase2 各自的副本

修改：
- `fnm-phase2/src/sup_recovery/pdf_render.rs` → 内容改为 `pub use fnm_core::vision::{render_page_to_base64_png, PDFIUM};`
- `fnm-phase2/src/sup_recovery/layer3.rs:12` 删除自己的 `HTTP_CLIENT`，改 `use fnm_core::vision::HTTP_CLIENT;`
- `fnm-phase2/src/sup_recovery/layer3.rs:36-50` 删 `VisionConfig` 定义，改 `pub use fnm_core::vision::VisionConfig;`
- `fnm-phase1/src/llm_book_type_verify/mod.rs:17-29` 删 PDFIUM + HTTP_CLIENT，改 `use fnm_core::vision::{PDFIUM, HTTP_CLIENT, render_page_to_base64_png};`
- `fnm-phase1/src/llm_book_type_verify/mod.rs:61-83` 删自己的 render 函数

#### C1.8 — 验收

- [ ] `grep -rn "Lazy<Mutex<Pdfium>>" fnm-phase1/src fnm-phase2/src` → 0 处
- [ ] `grep -rn "Lazy<Client>" fnm-phase1/src fnm-phase2/src` → 0 处
- [ ] `grep -rn "fn render_page_to_base64_png" fnm-phase1/src fnm-phase2/src` → 0 处
- [ ] `cargo test --all` 通过（202 测试不变）

---

## 3. F7+: page_partition 严格保真补完（2 天）

### 现状

`fnm-phase1/src/page_partition/role_heuristics.rs`：534 行。Python `page_partition.py`：1267 行，60 个函数。

虽然之前 R1-R4 已经把 Regex 都改成 Lazy 了，但**业务函数还少**。

### 目标

补完到 ~800 行。**重点是 Python 的 60 个函数中缺失的 ~40 个**。

### Python 函数清单（必须 port 的）

按 Python `stages/page_partition.py` 顺序：

| Python 函数 | 行号 | 用途 | 当前 Rust 状态 |
|---|---:|---|---|
| `_strip_markdown_heading` | 106 | 剥离 `# `/`## ` 前缀 | ❓ 复用 fnm-core 的 `note_marker::strip_markdown_heading` |
| `_note_kind_from_id` | 114 | 见 fnm-core `refs::note_kind_from_id` | ✅ 用 fnm-core |
| `_extract_note_refs_with_kind` | 121 | 见 fnm-core `refs::extract_note_refs` | ✅ 用 fnm-core |
| `_plain_text_lines` | 141 | 见 fnm-core `text::plain_text_lines` | ✅ 用 fnm-core |
| `_uppercase_ratio` | 146 | 大写字母占比 | ❌ 缺 |
| `_markdown_body_after_first_heading` | 154 | 提取标题后正文 | ❌ 缺 |
| `_looks_like_prose_after_heading` | 163 | 判断标题后是否散文 | ❌ 缺 |
| `_looks_like_title_page` | 190 | 书名页 | ❌ 缺 |
| `_looks_like_course_listing_page` | 212 | 课程列表页 | ❌ 缺 |
| `_looks_like_copyright_front_matter_page` | 226 | 版权页 | ❌ 缺 |
| `_chapter_keyword_strength` | 246 | 章节关键词强度 | ❌ 缺 |
| `_is_toc_force_export_title` | 257 | 强制导出 TOC 标题 | ❌ 缺 |
| `_is_visual_toc_explicit_chapter_title` | 261 | TOC 显式章标题 | ❌ 缺 |
| `_is_strong_body_boundary_page` | 272 | 强 body 边界 | ❌ 缺 |
| `_is_body_entry_page` | 289 | body 入口页 | ❌ 缺 |
| `_looks_like_early_other_page` | 308 | 早期 other 页 | ❌ 缺 |
| `_looks_like_rear_toc_tail_page` | 327 | 后置 TOC 尾页 | ❌ 缺 |
| `_looks_like_rear_author_blurb_page` | 380 | 作者简介页 | ❌ 缺 |
| `_looks_like_rear_sparse_other_page` | 403 | 后置稀疏 other | ❌ 缺 |
| `_note_def_match` | 425 | note 定义匹配 | ❌ 缺 |
| `_looks_like_note_continuation_page` | 435 | note 续行页 | ❌ 缺 |
| `_looks_like_bibliography_continuation_page` | 478 | bibliography 续行 | ❌ 缺 |
| `_looks_like_index_continuation_page` | 493 | index 续行 | ❌ 缺 |
| `_looks_like_illustrations_continuation_page` | 500 | 插图续行 | ❌ 缺 |
| `_looks_like_back_matter_continuation_page` | 509 | back matter 续行 | ❌ 缺 |
| `_seed_back_matter_family` | 526 | 后置 family 种子 | ❌ 缺 |
| `_RuleMatch` 类型 + 11 条 `_rule_*` | 549-650+ | **规则引擎核心**（11+ 规则）| ❌ 严重缺失 |

### 关键算法：规则引擎

Python 的 `_PageScanContext` + 11 条 `_rule_*` 规则函数是核心。当前 Rust `role_resolver.rs:186` 没有这个抽象。

**目标拆分**（保持 mod.rs < 400 行规范）：

```
fnm-phase1/src/page_partition/
├── mod.rs                      # 入口（保持现状）
├── role_resolver.rs            # 主 resolver（保持现状）
├── role_heuristics.rs          # 顶层规则（保持现状）
├── rules/                      # ← 新增子目录
│   ├── mod.rs                  # RuleMatch 类型 + 规则注册
│   ├── archive_noise.rs        # _rule_archive_noise
│   ├── course_listing.rs       # _rule_early_course_listing
│   ├── copyright.rs            # _rule_copyright_front_matter
│   ├── early_other.rs          # _rule_early_other_list
│   ├── rear_toc.rs             # _rule_rear_toc_tail
│   ├── rear_author.rs          # _rule_rear_author_blurb
│   ├── rear_sparse.rs          # _rule_rear_sparse_other
│   ├── note_scan.rs            # _rule_note_scan
│   ├── notes_heading.rs        # _rule_notes_heading
│   └── title_page.rs           # _rule_title_page
└── continuation/               # ← 新增子目录
    ├── mod.rs
    ├── note_cont.rs            # _looks_like_note_continuation_page
    ├── bibliography_cont.rs    # _looks_like_bibliography_continuation_page
    ├── index_cont.rs           # _looks_like_index_continuation_page
    ├── illustrations_cont.rs   # _looks_like_illustrations_continuation_page
    └── back_matter_cont.rs     # _looks_like_back_matter_continuation_page
```

### 实现要点

1. **每个 `_rule_*` 函数都对应一个独立子文件**（单一职责）
2. **`RuleMatch` 类型**：

```rust
// rules/mod.rs
use fnm_core::types::PageRole;

#[derive(Debug, Clone)]
pub struct RuleMatch {
    pub role: PageRole,
    pub confidence: f64,
    pub reason: String,
}

#[derive(Debug, Clone)]
pub enum RuleResult {
    Match(RuleMatch),
    NoMatch,
}

pub struct PageScanContext<'a> {
    pub page_no: i64,
    pub total_pages: i64,
    pub markdown_text: &'a str,
    pub headings: &'a [String],
    pub note_scan: Option<&'a serde_json::Value>,
    pub page: &'a fnm_phase1::input::RawPage,
}

/// 注册所有规则（按优先级）。
pub fn all_rules() -> Vec<fn(&PageScanContext) -> RuleResult> {
    vec![
        archive_noise::rule,
        course_listing::rule,
        copyright::rule,
        early_other::rule,
        rear_toc::rule,
        rear_author::rule,
        rear_sparse::rule,
        note_scan::rule,
        notes_heading::rule,
        title_page::rule,
        // 续行规则
        crate::page_partition::continuation::note_cont::rule,
        // ...
    ]
}
```

3. **每个规则函数签名一致**：`fn rule(ctx: &PageScanContext) -> RuleResult`

4. **顶层 `resolve_role` 改为遍历规则**：

```rust
pub fn resolve_role(ctx: &PageScanContext) -> RuleMatch {
    for rule in rules::all_rules() {
        if let RuleResult::Match(m) = rule(ctx) {
            return m;
        }
    }
    // 兜底
    RuleMatch {
        role: PageRole::Body,
        confidence: 0.5,
        reason: "fallback".into(),
    }
}
```

### 验收

- [ ] `role_heuristics.rs` + `rules/` + `continuation/` 合计 ≥ 800 行
- [ ] Python 60 个函数全部 port（除了已用 fnm-core 替代的）
- [ ] 每个 `_rule_*` 单独子文件
- [ ] **不动 R1 的 Lazy regex 模式**——所有正则继续上移
- [ ] `cargo test --all` 通过
- [ ] Biopolitics page_partition 测试断言收紧（`note_count >= 50`，原 `>= 15`）

---

## 4. F4+: heading_candidates 字体检测 + family 聚类（3 天）

### 现状

`fnm-phase1/src/chapter_skeleton/heading_candidates.rs`：150 行。Python `heading_candidates.py`：827 行。

当前实现只做了简单的 `extract_page_headings` 包装，缺：
- 字体特征检测（font_height / font_weight / x / y）
- family 聚类
- top_band 判定
- reject 启发式
- TOC heading 候选
- PDF font band 候选
- composite heading 合成

### 目标

补完到 ~700 行，拆 5 个子模块。

### Python 函数清单

| Python 函数 | 行号 | 用途 |
|---|---:|---|
| `_normalize_font_weight_hint` | 121 | 字重规范化 |
| `_normalize_align_hint` | 127 | 对齐规范化 |
| `_width_ratio` | 133 | 宽度比 |
| `_align_hint` | 141 | 对齐推断 |
| `_heading_level_hint` | 158 | heading level 推断 |
| `_build_pdf_page_by_file_idx` | 182 | PDF 页索引 |
| `_legacy_page_rows` | 194 | legacy page 行数据 |
| `_heading_family_guess` | 225 | family 推断 |
| `_append_heading_candidate` | 255 | 添加候选 |
| `extract_heading_candidates_from_page` | 321 | **入口** |
| `_collect_page_heading_candidates` | 420 | 收集页级候选 |
| `_collect_toc_heading_candidates` | 445 | TOC 候选 |
| `_pdf_file_hash` | 501 | PDF 文件哈希 |
| `_run_pdf_font_subprocess` | 510 | PDF 字体子进程（**Rust 直接调** pdfium-render）|
| `_collect_pdf_font_band_candidates` | 537 | PDF font band 候选 |
| `_extract_candidates_from_pdf_pages` | 618 | PDF 页提取 |
| `_collect_heading_candidate_rows` | 726 | 收集候选行 |
| `_is_sentence_like_heading` | 767 | 像句子的 heading |
| `_chapter_keyword_strength` | 777 | 章关键词强度 |
| `_normalize_heading_candidates` | 788 | 规范化候选 |

### 目标拆分

```
fnm-phase1/src/chapter_skeleton/heading_candidates/
├── mod.rs                # 入口 extract_heading_candidates_from_page
├── font_features.rs      # _normalize_font_weight_hint / _normalize_align_hint / _width_ratio / _align_hint
├── family_guess.rs       # _heading_family_guess / _chapter_keyword_strength
├── page_rows.rs          # _legacy_page_rows / _collect_page_heading_candidates
├── toc_candidates.rs     # _collect_toc_heading_candidates
├── pdf_font_band.rs      # _collect_pdf_font_band_candidates + _extract_candidates_from_pdf_pages
└── normalize.rs          # _normalize_heading_candidates + _is_sentence_like_heading
```

### 实现要点

1. **PDF 字体提取**：复用 C1 的 `fnm_core::vision::PDFIUM`，**不要**再写子进程（Python 用子进程是因为 PyMuPDF 内存泄漏，Rust 没这问题）

2. **`HeadingCandidate` 字段必须填**（之前 B 版本全为 None/默认）：
   - `font_height: Option<f64>` — 从 PDF 字体提取
   - `font_name: String` — 从 PDF
   - `font_weight_hint: String` — "bold" / "normal" / "unknown"
   - `align_hint: String` — "left" / "center" / "right" / "unknown"
   - `x: Option<f64>`、`y: Option<f64>`、`width_estimate: Option<f64>`
   - `top_band: bool` — y < 阈值
   - `heading_level_hint: i64`
   - `reject_reason: String` — 不为空时 suppressed_as_chapter = true

3. **family 推断算法**（按 Python 行 225-254）：基于 keyword（chapter/chapitre/lecture/leçon）+ 数字编号 + 长度 + 大写比例

### 验收

- [ ] 拆分为 7 个子模块
- [ ] Python 20 个函数全部 port
- [ ] `HeadingCandidate` 全字段填充（不再 None / "unknown" 默认）
- [ ] Biopolitics 12 章 heading_candidates 数与 Python 一致（**byte-equal**，不接受简化）
- [ ] 测试加 parity fixture：`tests/fixtures/biopolitics_heading_candidates_expected.json`

---

## 5. F2+: note_regions 拆 5 子模块（3 天）

### 现状

`fnm-phase2/src/note_regions/mod.rs`：461 行，单文件。Python 825 行，17 个函数。

### Python 函数清单

| Python 函数 | 行号 | 用途 |
|---|---:|---|
| `_chapter_id_for_page` | 28 | 章节归属 |
| `_nearest_prior_chapter` | 33 | 最近前章 |
| `_page_payload_by_no` | 37 | page 索引 |
| `_build_footnote_band_regions` | 50 | **footnote band region** |
| `_looks_like_illustration_list_page` | 91 | 插图列表页 |
| `_is_endnote_candidate_page` | 130 | endnote 候选页 |
| `_endnote_scope_for_page` | 162 | endnote scope（chapter/book）|
| `_start_reason_for_page` | 176 | start_reason 推断 |
| `_build_endnote_regions_raw` | 192 | **endnote regions raw（核心）**|
| `_promote_post_body_regions` | 407 | **章后隐式尾注晋升** |
| `_merge_adjacent_endnote_regions` | 442 | 相邻 region 合并 |
| `_split_book_regions_by_heading` | 480 | book region 按 heading 切分 |
| `_rebind_book_regions` | 550 | book region 重绑定 |
| `_chapter_endnote_start_page_map` | 581 | 章 endnote 起始页 map |
| `_normalize_region_ids` | 595 | region_id 规范化 |
| `_reclassify_post_body_fnblocks_as_endnote` | 620 | post body fnblocks 重分类 |
| `build_note_regions` | 723 | **入口** |

### 目标拆分

```
fnm-phase2/src/note_regions/
├── mod.rs                          # 入口 build_note_regions（编排）
├── chapter_lookup.rs               # _chapter_id_for_page / _nearest_prior_chapter
├── page_payload.rs                 # _page_payload_by_no（或复用 fnm-core text）
├── footnote_band.rs                # _build_footnote_band_regions
├── endnote_candidate.rs            # _is_endnote_candidate_page + _endnote_scope_for_page + _start_reason_for_page + _looks_like_illustration_list_page
├── endnote_regions_raw.rs          # _build_endnote_regions_raw（核心算法 ~200 行）
├── post_body_promote.rs            # _promote_post_body_regions + _reclassify_post_body_fnblocks_as_endnote
├── merge_adjacent.rs               # _merge_adjacent_endnote_regions
├── book_regions.rs                 # _split_book_regions_by_heading + _rebind_book_regions + _chapter_endnote_start_page_map
└── normalize.rs                    # _normalize_region_ids
```

### 实现要点

1. **编排顺序**（Python `build_note_regions` 行 723-825）：

```rust
pub fn build_note_regions(...) -> Vec<NoteRegionRecord> {
    let footnote_regions = footnote_band::build_footnote_band_regions(...);
    let raw_endnote_regions = endnote_regions_raw::build_endnote_regions_raw(...);
    let promoted = post_body_promote::promote_post_body_regions(...);
    let merged = merge_adjacent::merge_adjacent_endnote_regions(...);
    let split = book_regions::split_book_regions_by_heading(...);
    let rebound = book_regions::rebind_book_regions(...);
    let reclassified = post_body_promote::reclassify_post_body_fnblocks_as_endnote(...);
    let normalized = normalize::normalize_region_ids(rebound);
    
    // 合并所有 region 类型
    let mut regions = Vec::new();
    regions.extend(footnote_regions);
    regions.extend(normalized);
    regions
}
```

2. **`note_kind` 必须通过 `note_kind_resolver`**（不要回退到硬编码 NoteKind::Endnote）

3. **删除当前 `mod.rs:431,454` 的测试 fixture stub**——改为用 fnm-core 提供的辅助构造函数

### 验收

- [ ] 拆分为 10 个文件
- [ ] Python 17 个函数全部 port
- [ ] `note_kind_resolver` 是唯一 note_kind 来源
- [ ] **3 个 SPEC 测试通过**：
  - `test_chapter_scope_endnote_region_count`（≥ 11 章有 endnote region）
  - `test_each_lecture_chapter_has_endnote_region`
  - `test_chapter_7_fevrier_has_single_endnote_region`（连续 region 不被切碎）
- [ ] Biopolitics 测试断言收紧：必须找出 **65 个 note 页**（之前 `>= 15`）

---

## 6. F3+: note_items 拆子模块（2 天）

### 现状

`fnm-phase2/src/note_items/mod.rs`：348 行。Python 658 行，22 个函数。

### Python 函数清单

| Python 函数 | 行号 | 用途 |
|---|---:|---|
| `_infer_marker_type` | 28 | marker 类型推断 |
| `_annotated_page_by_no` | 37 | 注解 page 索引 |
| `_region_pages` | 50 | region 页列表 |
| `_parse_items_from_structured_scan` | 59 | 从 structured scan 解析 |
| `_raw_scan_items_by_kind` | 63 | raw scan 按 kind 分组 |
| `_section_title_key` | 86 | 节标题 key |
| `_chapter_title_by_id` | 96 | 章标题 map |
| `_region_title_keys` | 104 | region 标题 keys |
| `_filter_shared_page_rows_for_region` | 116 | 共享页过滤 |
| `_title_key_matches` | 143 | 标题匹配 |
| `_all_chapter_title_keys` | 162 | 全章标题 keys |
| `_matching_markdown_heading_indices` | 170 | markdown heading 索引匹配 |
| `_split_shared_page_text_for_region` | 191 | 共享页文本切分 |
| `_last_numeric_marker_value` | 216 | 最后数字 marker |
| `_normalized_page_text` | 226 | 规范化页文本 |
| `_dedupe_region_items` | 251 | region item 去重 |
| `_repair_parsed_row_sequence_markers` | 264 | **修复 marker 序列**（核心）|
| `_chapter_id_set` | 324 | chapter_id 集 |
| `_fix_year_markers_in_place` | 328 | 修复年份误识 |
| `_fix_sequence_outlier_markers_in_place` | 357 | 修复序列异常 |
| `_try_parse_int` | 389 | int 解析 |
| `build_note_items` | 396 | **入口** |

### 目标拆分

```
fnm-phase2/src/note_items/
├── mod.rs                  # 入口 build_note_items
├── parser.rs               # _parse_items_from_structured_scan + _raw_scan_items_by_kind + 现有 parse_page
├── region_filter.rs        # _filter_shared_page_rows_for_region + _split_shared_page_text_for_region + _title_key_matches
├── marker_repair.rs        # _repair_parsed_row_sequence_markers + _fix_year_markers + _fix_sequence_outlier_markers
└── dedupe.rs               # _dedupe_region_items
```

### 实现要点

1. **保留 R3.1 的 fnm-core 复用**：`use fnm_core::note_marker::normalize_note_marker;` + `use fnm_core::anchor_kind::patterns::*;`

2. **OCR split marker 重建**（SPEC 测试）：当前已实现，**不要破坏**

3. **新增**：
   - 年份误识别（Python `_fix_year_markers_in_place`）：如果 marker 是 4 位数字且像年份（1500-2100），降级
   - 序列异常修复（Python `_fix_sequence_outlier_markers_in_place`）：检测 1,2,3,**50**,4,5 这种异常跳号
   - 引文缩写处理：已部分实现，**补足** `PAGE_CITATION_PREFIX_RE` 的全部模式

### 验收

- [ ] 拆分为 5 个文件
- [ ] Python 22 个函数全部 port
- [ ] **2 个 SPEC 测试通过**：
  - `test_ocr_split_marker_can_be_reconstructed`（当前已通过，**保持**）
  - `test_ch5_note_4_definition_is_full_length`（长 note 不被截断到 vol.）
- [ ] note_kind 永远从 `region.note_kind` 透传，不重新判定

---

## 7. F12+: parity 断言收紧（2 天）

### 现状

`fnm-phase1/tests/test_biopolitics_parity.rs` 当前断言：
```rust
assert!(note_count >= 15, "Python finds 65, Rust simplified");
```

### 目标

**byte-equal Python 输出**，不接受 simplified。

### 步骤

#### F12.1 — 生成 Python 黄金 fixture

写脚本 `tools/gen_biopolitics_golden.py`：
```python
from FNM_RE.stages.page_partition import build_page_partitions
from FNM_RE.modules.toc_structure import build_toc_structure
from FNM_RE.stages.note_regions import build_note_regions
from FNM_RE.stages.note_items import build_note_items
from FNM_RE.modules.chapter_split import build_chapter_layers
import json, dataclasses

# 加载 Biopolitics
pages = load_pages("Biopolitics")
toc = load_auto_visual_toc("Biopolitics")

# 跑完整 Phase 1
phase1 = build_toc_structure(pages, toc).data
# 序列化为 JSON
phase1_json = dataclasses_to_dict(phase1)
write("fnm-phase1/tests/fixtures/biopolitics_phase1_golden.json", phase1_json)

# 跑 Phase 2
phase2 = build_chapter_layers(phase1, ...).data
phase2_json = dataclasses_to_dict(phase2)
write("fnm-phase2/tests/fixtures/biopolitics_phase2_golden.json", phase2_json)
```

#### F12.2 — 收紧 Rust 断言

```rust
// fnm-phase1/tests/test_biopolitics_parity.rs
#[test]
fn biopolitics_page_partition_byte_equal_python() {
    let pages: Vec<RawPage> = load_biopolitics_pages();
    let result = build_page_partitions(&pages, None, None);
    
    // 加载 Python 黄金答案
    let expected: serde_json::Value = serde_json::from_str(include_str!(
        "fixtures/biopolitics_phase1_golden.json"
    )).unwrap();
    let expected_partitions = expected["pages"].as_array().unwrap();
    
    // 逐条比对
    assert_eq!(result.partitions.len(), expected_partitions.len(),
        "page count mismatch");
    
    for (i, (actual, exp)) in result.partitions.iter().zip(expected_partitions).enumerate() {
        let actual_role = actual.page_role.as_str();
        let exp_role = exp["page_role"].as_str().unwrap();
        assert_eq!(actual_role, exp_role,
            "page {} role mismatch: Rust={} Python={}", actual.page_no, actual_role, exp_role);
    }
}

#[test]
fn biopolitics_note_count_matches_python_65() {
    // 不再接受 simplified
    let pages = load_biopolitics_pages();
    let result = build_page_partitions(&pages, None, None);
    let note_count = result.partitions.iter()
        .filter(|p| p.page_role == PageRole::Note)
        .count();
    assert_eq!(note_count, 65, "Python finds 65, Rust must match exactly");
}
```

#### F12.3 — 整 Phase 2 也加 parity

```rust
// fnm-phase2/tests/test_biopolitics_parity.rs（新建）
#[test]
fn biopolitics_note_regions_byte_equal_python() { ... }

#[test]
fn biopolitics_note_items_byte_equal_python() { ... }

#[test]
fn biopolitics_chapter_layers_byte_equal_python() { ... }
```

### 验收

- [ ] `tests/fixtures/biopolitics_phase1_golden.json` 由 Python 真实输出生成（含 page_partition / chapters / section_heads）
- [ ] `tests/fixtures/biopolitics_phase2_golden.json` 由 Python 生成（含 note_regions / note_items / chapter_note_modes）
- [ ] Rust parity 测试逐字段对比 Python 输出
- [ ] **不再有 `>= 15` 这种 simplified 断言**
- [ ] **如果 Rust 输出与 Python 不一致**：在 PR 描述里列出每个 diff，说明是 Python bug（要修 FNM_RE）还是 Rust 实现 bug（要修 Rust）

---

## 8. V1: SPEC 测试覆盖补齐（0.5 天）

当前 17 个 spec_test，缺以下 2 个（来自原 19 个 SPEC）：

| 缺失测试 | 应加在 |
|---|---|
| `test_biopolitics_toc_gate_and_exportable_chapters`（TOC 12 章 + post_body 列表为空）| `fnm-phase1/tests/test_phase1_spec.rs` |
| `test_visual_toc_export_candidate_default`（2 个 sub-test）| `fnm-phase1/tests/test_phase1_spec.rs` |

按 Python 测试的语义翻译。SPEC 标签来自 `tests/unit/test_*.py` 中标记的 `@unittest.skip("[rust-migration: SPEC] ...")`。

---

## 9. 与 V1 任务的关系

| V1 任务 | V2 状态 |
|---|---|
| R1-R4（反模式重构） | ✅ V1 已做 |
| G1-G5（LLM 模块新写） | ✅ V1 已做 |
| F1（Biopolitics fixture） | ✅ V1 部分做（`biopolitics_pages_sample.json`），F12.1 要生成完整 golden |
| F2/F3/F4/F7（业务补完）| 🔄 V2 做（F2+/F3+/F4+/F7+）|
| F10（persist bug） | ✅ V1 已做 |
| F11（SPEC 测试）| 🟡 V1 部分（17/19），V2 补齐（V1 任务）|
| F12（端到端 parity）| 🔄 V2 做（F12+）|

---

## 10. 验收 checklist（每个 PR）

### 通用（所有 PR）
- [ ] `cargo build --release` 通过
- [ ] `cargo clippy --all-targets -- -D warnings` 通过（0 新增 `allow`）
- [ ] `cargo fmt --check` 通过
- [ ] `cargo test --all` 通过
- [ ] 0 新增 `let _ = ...` 忽略关键参数
- [ ] 0 静默 stub（必须用 `anyhow::bail!`）
- [ ] 0 循环内 `Regex::new()`
- [ ] 0 `Rc<RefCell>` / 0 新增 `Arc<Mutex>`

### C1 专项
- [ ] phase1 / phase2 都改为 `use fnm_core::vision::*`
- [ ] grep 验证：PDFIUM / HTTP_CLIENT / render_page_to_base64_png **各自只有 1 处定义**

### F7+ 专项
- [ ] Python 60 个函数全部 port（用脚本对比函数清单）
- [ ] 11 个 `_rule_*` 拆独立子文件
- [ ] role_heuristics.rs + rules/ + continuation/ 合计 ≥ 800 行

### F4+ 专项
- [ ] 拆 7 子模块
- [ ] HeadingCandidate 字段全填（font_height / font_name / x / y / weight / align 等）
- [ ] 复用 `fnm_core::vision::PDFIUM`（不再写自己的）

### F2+ / F3+ 专项
- [ ] note_regions 拆 10 文件，note_items 拆 5 文件
- [ ] note_kind 永远走 `note_kind_resolver`
- [ ] 5 个 SPEC 测试通过（chapter_endnote_count / each_lecture / 7_fevrier / ocr_split / ch5_note_4）

### F12+ 专项
- [ ] `biopolitics_phase1_golden.json` 和 `biopolitics_phase2_golden.json` 由 Python 真实跑出
- [ ] 不存在 `>= 15` 这种 simplified 断言
- [ ] 不一致 diff 在 PR 描述里逐条说明

---

## 11. PR 流程

| 顺序 | PR title |
|---:|---|
| 1 | `C1: fnm-core vision 模块（PDFIUM + HTTP_CLIENT + render 单例抽取）` |
| 2 | `F7+: page_partition 严格保真补完（534 → ~800 行 + 规则引擎拆分）` |
| 3 | `F4+: heading_candidates 字体检测 + family 聚类（150 → ~700 行）` |
| 4 | `F2+: note_regions 拆 5 子模块 + 章后隐式尾注 SPEC` |
| 5 | `F3+: note_items 拆子模块 + 序列修复 + 年份过滤` |
| 6 | `F12+: Biopolitics parity 断言收紧 + 19 SPEC 全覆盖` |

每个 PR 完成后等我审计再合下一个。**不要批量提交**。

---

## 12. 风险与边界

### 风险 1：Python 函数依赖未 port 的辅助

每个任务开工前查 Python 函数的 import：

```bash
grep "^from\|^import" /Users/hao/OCRandTranslation/FNM_RE/stages/page_partition.py
```

如果发现依赖未 port 的辅助，**先在 fnm-core 补这个辅助**（短小函数），不要在 phase crate 重新写。

### 风险 2：F4+ 的 PDF 字体提取需要 pdfium 二进制

C1 完成后 fnm-core 有 PDFIUM。F4+ 用 `fnm_core::vision::PDFIUM.lock()`。CI 测试加 `#[ignore]`，本地开发需安装 `pdfium-binaries`。

### 风险 3：Biopolitics parity 可能暴露 Python bug

F12+ 如果 byte-equal 失败，可能是 Python 端的小 bug（如某些 OCR 模式遗漏）。判断流程：
1. 跑 `inspect_page.py` 看真实页面
2. 看 Python 输出是否符合**业务直觉**（不是符合 Python 代码）
3. 如果 Python 错，Rust 实现"正确版"，在 PR 描述说明并加 `tests/known_python_bugs.md` 记录
4. 如果 Rust 错，修 Rust

### 风险 4：F2+/F3+/F4+/F7+ 工作量大

如果某个任务做到一半发现工作量超 50%（比如 F7+ 做到 2 天还没完成），**先停下来发现状报告**——可能需要把任务拆成更小子任务。

---

## 13. 完成后通知

每个 PR 合并后：
1. 在 PR comment 写"完成 C1/F7+/F4+/F2+/F3+/F12+"
2. 更新 `FNM_PHASE12_AUDIT.md` 的对应行（🔴 → ✅）
3. 全部完成后通知用户做最终审计

---

**开工前最后一遍**：先看 AGENTS.md 12 条铁律，再看 FNM_PHASE12_AUDIT.md 历史问题，再看 V1 已做的 R1-R4 + G1-G5 代码风格作参考。然后从 C1 开始。
