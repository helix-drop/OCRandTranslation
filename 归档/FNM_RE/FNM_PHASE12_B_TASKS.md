# B 模型 Rust 重构任务清单

本文档是给"B 模型"（接手 Phase 1/2 后续重构 + LLM 模块新写）的完整工作说明。文档自包含，新 session 不依赖任何上下文也能开工。

---

## 0. 必读前置

按顺序读：

1. **[`/Users/hao/OCRandTranslation/AGENTS.md`](/Users/hao/OCRandTranslation/AGENTS.md)** 的 "Rust 重构代码规范（`fnm_re_rs/`）" 章节（最后 ~230 行，共 12 条铁律）
2. **[`/Users/hao/OCRandTranslation/FNM_RE/FNM_PHASE12_AUDIT.md`](/Users/hao/OCRandTranslation/FNM_RE/FNM_PHASE12_AUDIT.md)** 了解前一轮审计发现的问题
3. **[`/Users/hao/OCRandTranslation/FNM_RE/FNM_CORE_PLAN.md`](/Users/hao/OCRandTranslation/FNM_RE/FNM_CORE_PLAN.md)** 了解 fnm-core 提供的 API

**没读完不要动代码**。

---

## 1. 当前 Rust 项目状态

代码位置：`/Users/hao/OCRandTranslation/fnm_re_rs/`

```
fnm_re_rs/
├── fnm-core/       ✅ 已完成（96 测试，0 allow 抑制，0 反向依赖）
├── fnm-phase1/     ⚠️ 部分完成（5,533 行，~60%）
├── fnm-phase2/     ⚠️ 部分完成（2,237 行，~40%）
└── fnm-phase3-6/   ⏳ 未开始
```

测试：`~/.cargo/bin/cargo test --manifest-path /Users/hao/OCRandTranslation/fnm_re_rs/Cargo.toml --all` 当前 199 个测试通过。

---

## 2. 你的任务范围

### 必做（P0 + P1）

**P0 反模式重构**：R1-R4，目标把已写代码符合 AGENTS.md 规范。

**P1 LLM 模块新写**：G1-G5，按规范从零实现 Vision LLM + PDF render。

### 不要碰

**F2+ / F3+ / F4+ / F7+** — 这几个模块（`note_regions` / `note_items` / `heading_candidates` / `page_partition/role_heuristics`）的深度业务逻辑补完留给另一个模型，**你不要碰内部业务逻辑**。

但你做 R1-R4 时会**机械地修改**这几个文件里的 Regex 编译位置——这种纯形式重构是 OK 的（且必须做）。**判断标准**：你的修改如果只是改 `let re = Regex::new(...).unwrap()` → `static RE: Lazy<Regex> = Lazy::new(...)`，那是 R1；如果你要改算法分支、加条件判断、改返回值结构，那就是 F2+/F3+/F4+/F7+，**停下来**。

---

## 3. P0 任务：R1-R4 反模式重构（**先做**）

### R1: 把所有循环内 `Regex::new()` 改为 `Lazy<Regex>` 静态

#### R1.1 — `fnm-phase1/src/page_partition/role_heuristics.rs`

文件顶部已有部分 `Lazy<Regex>`，但函数内部还有大量局部 `Regex::new()`。把以下 11 处全部上移：

| 行号 | 当前 | 改为 |
|---:|---|---|
| 99 | `let re = Regex::new(r"\s+").unwrap();` | 顶部 `static WHITESPACE_RE: Lazy<Regex>` |
| 153 | `Regex::new(r"(?i)cours (?:de\|au).*(?:coll[eè]ge de france)")` | 顶部 `static COURS_CF_RE` |
| 172 | `let re = Regex::new(...)` | 顶部 |
| 252 | `Regex::new(r"\d{4}\s*$").unwrap()` 在条件判断里 | 顶部 `static TRAILING_YEAR_RE` |
| 256 | `Regex::new(r"\b\d{1,4}\s*$")` | 顶部 `static TRAILING_PAGENO_RE` |
| 335 | `Regex::new(r"(?i)[a-zà-ÿ]{4,}")` | 顶部 `static PROSE_WORD_RE` |
| 415 | `Regex::new(&format!("(?i){}", pattern))` | **特殊**：动态拼接的，用 `RegexBuilder::case_insensitive(true)` 或预编译已知 pattern 集 |
| 443 | `Regex::new(r"\^\{\d+\}\|...")` | 顶部 `static SUP_MARKER_RE` |
| 454 | `let sentence_re = Regex::new(r"[.!?。！？]")` | 顶部 `static SENTENCE_END_RE` |
| 467 | `.filter(\|l\| Regex::new(r"[a-zà-ÿ]").unwrap().is_match(l))` | 顶部 `static LATIN_LETTER_RE`（filter 闭包内引用）|
| 491 | `Regex::new(r"\{\{(?:NOTE\|FN\|EN)_REF:...")` | 顶部 `static FROZEN_REF_RE`（**先看 fnm-core 的 `refs::NOTE_REF_RE` 等**，能复用就复用）|

**415 行的动态正则**：如果 pattern 集合有限，预编译一个 HashMap：
```rust
static DYN_PATTERN_CACHE: Lazy<HashMap<&'static str, Regex>> = Lazy::new(|| {
    HashMap::from([
        ("pattern1", Regex::new("(?i)pattern1").unwrap()),
        // ...
    ])
});
```

#### R1.2 — `fnm-phase2/src/note_items/mod.rs`

| 行号 | 当前 | 改为 |
|---:|---|---|
| 140-141 | `Regex::new(r"^([a-zA-Z])\s{1,3}(\S.*)$").unwrap().captures(trimmed)` 在 for 循环内 | 顶部 `static LETTER_BODY_RE: Lazy<Regex>` |
| 149 | `Regex::new(r"^[a-zA-Z]$").unwrap().is_match(m)` | 顶部 `static SINGLE_LETTER_RE`（**或直接用 `m.chars().count()==1 && m.chars().next().unwrap().is_alphabetic()`，更快**）|

#### R1.3 — `fnm-phase2/src/note_regions/mod.rs`

| 行号 | 当前 | 改为 |
|---:|---|---|
| 310 | `let re = regex::Regex::new(r"^\s{0,3}#{1,6}\s*")` | 顶部 `static MD_HEADING_PREFIX_RE`（或复用 fnm-core 的 `note_marker` 模块里的同名常量）|

#### R1.4 — `fnm-phase2/src/sup_recovery/layer1.rs`

| 行号 | 当前 | 改为 |
|---:|---|---|
| 13 | `let sup_re = regex::Regex::new(r"<sup>\s*(\d{1,4})\s*</sup>")` | **复用 `fnm_core::anchor_kind::patterns::HTML_SUP_RE`**（已存在）|
| 25 | `let ref_re = regex::Regex::new(r"\[\^(\d{1,4})\]")` | **复用 `fnm_core::anchor_kind::patterns::FOOTNOTE_REF_RE`**（已存在）|

#### R1.5 — `fnm-phase2/src/sup_recovery/layer2.rs`

| 行号 | 当前 | 改为 |
|---:|---|---|
| 11 | `let digit_re = regex::Regex::new(r"\b(\d{1,4})\b")` | 顶部 `static DIGIT_BOUNDARY_RE: Lazy<Regex>` |

#### R1.6 — `fnm-phase1/src/section_heads.rs`

| 行号 | 当前 | 改为 |
|---:|---|---|
| 47 | `let stripped = regex::Regex::new(r"(?i)^\s*(?:\d+\|[ivxlcdm]+)[\.\):\-–—]?\s+")` | 顶部 `static LEADING_NUMBER_PREFIX_RE` |

#### R1.7 — `fnm-phase1/src/chapter_skeleton/toc_semantics/title_utils.rs`

虽然这个文件主要是 A 模型写的（顶部已有 35+ Lazy 常量），但 166-334 行还有几处局部 `Regex::new`：

| 行号 | 改为 |
|---:|---|
| 166 | 顶部 `static DOT_LEADER_RE` |
| 169 | 顶部 `static EMB_TYPO_RE` |
| 172 | 顶部 `static EQUAL_LIGATURE_RE` |
| 224 | 顶部 `static NON_ALPHANUM_RE` |
| 287 | 顶部 `static YEAR_19XX_20XX_RE` |
| 334 | 顶部 `static NOTES_TO_SOMETHING_RE` |

#### R1.8 — `fnm-phase1/src/chapter_skeleton/toc_semantics/role_inference.rs`

| 行号 | 改为 |
|---:|---|
| 32 | 顶部 `static APPENDIX_RE` |
| 104 | 顶部已有，但 104 行又出现重复？检查后挪到顶部唯一定义 |
| 135 | 复用 fnm-core 的 `note_marker::NOTES_HEADING_RE` 或顶部新建 |

### R2: 移除所有 `#![allow(clippy::regex_creation_in_loops)]`

R1 全部完成后，搜并删除：

```bash
grep -rn "regex_creation_in_loops" /Users/hao/OCRandTranslation/fnm_re_rs/
```

预期出现位置：
- `fnm-phase1/src/lib.rs:1`
- `fnm-phase2/src/lib.rs:1`
- `fnm-phase2/src/note_regions/mod.rs`（如果文件级别有）
- `fnm-phase2/src/sup_recovery/layer2.rs`（顶部 `#![allow(dead_code)]` 保留）
- `fnm-phase2/src/endnote_chapter_explorer/mod.rs`

删除后 `cargo clippy --all-targets -- -D warnings` 必须通过。如果 clippy 还报，说明 R1 没改完。

### R3: sup_recovery 复用 fnm-core

R1.4 已经把 layer1.rs 的 `<sup>N</sup>` / `[^N]` 正则换成 fnm-core 的常量。这一步**进一步**：

#### R3.1 — layer1.rs 第 37-62 行的 Unicode 上标手写循环

**当前**：
```rust
let unicode_sup: Vec<(char, char)> = vec![
    ('⁰', '0'), ('¹', '1'), ('²', '2'), ('³', '3'), ('⁴', '4'),
    ('⁵', '5'), ('⁶', '6'), ('⁷', '7'), ('⁸', '8'), ('⁹', '9'),
];
let sup_chars: HashSet<char> = unicode_sup.iter().map(|(s, _)| *s).collect();
let mut digits = String::new();
for c in markdown.chars() {
    if sup_chars.contains(&c) {
        if let Some(&(_, d)) = unicode_sup.iter().find(|(s, _)| *s == c) {
            digits.push(d);
        }
    } else if !digits.is_empty() {
        if marker_set.contains(digits.as_str()) && seen.insert(digits.clone()) {
            found.push(digits.clone());
        }
        digits.clear();
    }
}
```

**改为**：
```rust
use fnm_core::anchor_kind::patterns::UNICODE_SUP_RE;
use fnm_core::note_marker::normalize_note_marker;

for cap in UNICODE_SUP_RE.find_iter(markdown) {
    let normalized = normalize_note_marker(cap.as_str());
    if marker_set.contains(normalized.as_str()) && seen.insert(normalized.clone()) {
        found.push(normalized);
    }
}
```

更短、更正确、复用已测试好的 fnm-core 逻辑。

#### R3.2 — layer2.rs 第 21-26 行的硬编码符号映射

**当前**（这是 AGENTS.md §1 明令禁止的反模式）：
```rust
let symbol_map: Vec<(&str, &str)> = vec![("*", "30"), (";", "11"), (":", "11")];
for (symbol, target) in &symbol_map {
    if marker_set.contains(target) && ocr_text.contains(symbol) {
        recovered.push((target.to_string(), format!("ocr_symbol_{}", symbol)));
    }
}
```

**问题**：这是 stub 实现，只为通过特定 test case，遇到新书必崩。

**改为**：**删除这段硬编码 + 加 `anyhow::bail!`**：

```rust
// Layer 2 的 OCR symbol surrogate recovery 需要 block 文本对齐算法，
// 暂未实现。当前返回空让上层走 Layer 3 vision fallback。
// TODO: 见 FNM_PHASE12_AUDIT.md F8+（留给保真型模型完整翻译 Python 版）
```

然后**只保留** layer2.rs 第 10-17 行的"找数字 marker"逻辑（那部分是正确的，不是硬编码）。

如果有测试依赖这个硬编码（如 `find_symbol_proxy`），把测试标 `#[ignore = "stub removed, see G2 layer3"]`。

### R4: 修复 `persist_phase2` 持久化 bug

#### R4.1 — `fnm-phase2/src/lib.rs:60-70`

**当前 bug**：
```rust
pub fn persist_phase2(
    repo: &dyn Repository,
    doc_id: &str,
    output: Phase2Output,
) -> anyhow::Result<()> {
    // 通过 Phase1 表写入 chapters
    repo.replace_fnm_phase1_products(
        doc_id,
        &fnm_core::db::Phase1Products {
            pages: vec![],              // ← 空！清空 Phase 1 已写的 pages
            chapters: output.chapters,
            heading_candidates: vec![],  // ← 空！
            section_heads: vec![],      // ← 空！
        },
    )?;
    // ...
}
```

`replace_fnm_phase1_products` 会 DELETE 旧数据再插入，传空 vec 等于**抹掉 Phase 1 写过的 pages / heading_candidates / section_heads**。

**改为**：Phase 2 不应该写 Phase 1 的表。Phase 1 的 chapters 在 Phase 1 持久化时已经写好了，Phase 2 不要碰。

```rust
pub fn persist_phase2(
    repo: &dyn Repository,
    doc_id: &str,
    output: Phase2Output,
) -> anyhow::Result<()> {
    // Phase 2 只写 Phase 2 的表（note_regions / note_items / chapter_note_modes 等）
    // Phase 1 的表（pages / chapters / heading_candidates / section_heads）已在 persist_phase1 写入
    repo.replace_fnm_phase2_products(
        doc_id,
        &fnm_core::db::Phase2Products {
            // 这些字段虽然在 Phase2Products struct 里，但实际不应该重写——
            // 注意 fnm-core Repository::replace_fnm_phase2_products 的契约：
            // 它内部已经委托 phase1 写入这些表。
            // 如果重新写，会用 output.chapters 覆盖 Phase 1 的 chapters。
            //
            // 选项 A：传 output 里实际存在的值（chapters 是 Phase 2 也可能修改的）
            // 选项 B：从 DB 读出 Phase 1 数据再传（保证不丢）
            //
            // 选 B，避免数据竞争：
            pages: repo.list_fnm_pages(doc_id)?.into_iter()
                .map(|p| p_to_partition_record(p))
                .collect(),
            chapters: output.chapters,
            heading_candidates: vec![],  // 不写这个表
            section_heads: repo.list_fnm_section_heads(doc_id)?,
            note_regions: output.note_regions,
            chapter_note_modes: output.chapter_note_modes,
            note_items: output.note_items,
        },
    )?;
    Ok(())
}
```

或者更彻底的方案：**修改 `fnm-core` 的 `Repository::replace_fnm_phase2_products` 让它不再委托 phase1 写入**——但这需要改 fnm-core。**先用 read-back 方案**，发 issue 给 fnm-core 维护者后续重构。

**验收测试**：写一个 round-trip 测试

```rust
// fnm-phase2/tests/integration/test_persist_phase2_preserves_phase1.rs
#[test]
fn persist_phase2_does_not_clear_phase1_tables() {
    let (repo, _tmp) = setup_db("doc-1");
    
    // 1. 先写 Phase 1 数据
    let phase1 = Phase1Products {
        pages: vec![make_page(1), make_page(2), make_page(3)],
        chapters: vec![make_chapter("ch-1", 1, 3)],
        heading_candidates: vec![make_heading_candidate()],
        section_heads: vec![make_section_head()],
    };
    repo.replace_fnm_phase1_products("doc-1", &phase1).unwrap();
    
    assert_eq!(repo.list_fnm_pages("doc-1").unwrap().len(), 3);
    assert_eq!(repo.list_fnm_section_heads("doc-1").unwrap().len(), 1);
    
    // 2. 写 Phase 2
    let phase2_output = Phase2Output { ... };
    persist_phase2(&repo, "doc-1", phase2_output).unwrap();
    
    // 3. 验证 Phase 1 表没被清空
    assert_eq!(repo.list_fnm_pages("doc-1").unwrap().len(), 3, "pages 不能被 Phase 2 清空");
    assert_eq!(repo.list_fnm_section_heads("doc-1").unwrap().len(), 1, "section_heads 不能被 Phase 2 清空");
}
```

### R0: PR 验收

R1-R4 完成后，作为**一个 PR 提交**（不要拆 4 个）。PR 描述：

```markdown
## R1-R4: Phase 1/2 反模式重构

按 AGENTS.md Rust 规范修复反模式。

### R1: 循环内 Regex 改 Lazy
- role_heuristics.rs: 11 处 → Lazy
- note_items/mod.rs: 2 处 → Lazy（letter marker）
- note_regions/mod.rs: 1 处 → Lazy
- sup_recovery/layer1.rs: 2 处 → 复用 fnm-core HTML_SUP_RE / FOOTNOTE_REF_RE
- sup_recovery/layer2.rs: 1 处 → Lazy
- section_heads.rs: 1 处 → Lazy
- toc_semantics/title_utils.rs: 6 处 → Lazy
- toc_semantics/role_inference.rs: 3 处 → Lazy

### R2: 移除 lint 抑制
- fnm-phase1/lib.rs: 删 #![allow(clippy::regex_creation_in_loops)]
- fnm-phase2/lib.rs: 同上
- 等

### R3: sup_recovery 复用 fnm-core
- layer1.rs Unicode 上标手写循环 → fnm_core::anchor_kind::patterns::UNICODE_SUP_RE + note_marker::normalize_note_marker
- layer2.rs 删除硬编码 symbol_map（stub，留 anyhow::bail! 等 Layer 3 实现）

### R4: 修 persist_phase2 持久化 bug
- 不再用空 vec 调 replace_fnm_phase1_products
- 加 round-trip 测试

### 验收
- [x] cargo build --release 通过
- [x] cargo clippy --all-targets -- -D warnings 通过
- [x] cargo fmt --check 通过
- [x] cargo test --all 通过（199 测试 + 1 新增 round-trip = 200）
- [x] 0 个 #![allow(clippy::regex_creation_in_loops)]
- [x] 0 个 let _ = ... 新增
- [x] sup_recovery 复用 fnm-core API（在 PR 描述列出复用的具体常量名）
```

---

## 4. P1 任务：G1-G5 LLM 模块新写

**前置**：R1-R4 已合入。

### 工具栈

按 AGENTS.md Rust 规范工作，重点使用：

```toml
# 已在 fnm-phase2/Cargo.toml 中
reqwest = { version = "0.12", features = ["json", "rustls-tls", "stream"] }
tokio = { version = "1.35", features = ["rt-multi-thread", "macros"] }
base64 = "0.22"
pdfium-render = { version = "0.8", features = ["bindings", "thread_safe"] }
image = { version = "0.25", default-features = false, features = ["png", "jpeg"] }
```

### G1: `sup_recovery/pdf_render.rs` 真实 pdfium-render（**先做**）

**当前**（11 行 stub）：
```rust
pub fn render_page_to_base64_png(_pdf_path: &str, _page_index: i64, _dpi: u32) -> Result<String> {
    Ok(String::new())
}
```

**目标**：

```rust
//! ←→ FNM_RE/modules/_pdf_render_worker.py (88 行)
//! PDF 单页渲染（pdfium-render 直接调用，不需要子进程）。

use anyhow::{Context, Result};
use base64::Engine;
use once_cell::sync::Lazy;
use pdfium_render::prelude::*;
use std::sync::Mutex;

/// 全局 Pdfium 实例（懒加载、线程安全）。
/// 创建 Pdfium 实例代价高，不能每次 render 都新建。
static PDFIUM: Lazy<Mutex<Pdfium>> = Lazy::new(|| {
    let bindings = Pdfium::bind_to_system_library()
        .or_else(|_| Pdfium::bind_to_library(
            Pdfium::pdfium_platform_library_name_at_path("./")
        ))
        .expect("无法加载 PDFium 二进制库");
    Mutex::new(Pdfium::new(bindings))
});

/// 渲染 PDF 单页为 base64 PNG（供 vision LLM 调用）。
/// 
/// ←→ Python `_pdf_render_worker.render_page_to_image_png_base64()`
pub fn render_page_to_base64_png(pdf_path: &str, page_index: i64, dpi: u32) -> Result<String> {
    let pdfium = PDFIUM.lock().expect("PDFIUM mutex poisoned");
    let document = pdfium
        .load_pdf_from_file(pdf_path, None)
        .with_context(|| format!("加载 PDF 失败: {}", pdf_path))?;
    
    let page = document
        .pages()
        .get(page_index as u16)
        .with_context(|| format!("PDF 页 {} 不存在", page_index))?;
    
    let render_config = PdfRenderConfig::new()
        .set_target_width(2000)  // 与 Python 端一致
        .render_form_data(false);
    
    let bitmap = page.render_with_config(&render_config)?;
    let image = bitmap.as_image();
    
    let mut png_bytes: Vec<u8> = Vec::new();
    image
        .write_to(&mut std::io::Cursor::new(&mut png_bytes), image::ImageFormat::Png)
        .context("PNG 编码失败")?;
    
    Ok(base64::engine::general_purpose::STANDARD.encode(&png_bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    #[ignore = "需要 PDFium 二进制 + 测试 PDF"]
    fn render_biopolitics_page_1() {
        let pdf_path = "/Users/hao/OCRandTranslation/test_example/Biopolitics/Biopolitics.pdf";
        let result = render_page_to_base64_png(pdf_path, 0, 150).unwrap();
        assert!(!result.is_empty());
        assert!(result.starts_with("iVBOR")); // PNG base64 头
    }
}
```

**验收**：
- 实际渲染 Biopolitics 第 1 页，base64 长度 > 100KB
- 测试加 `#[ignore]` 因为 PDFium 二进制是外部依赖
- README 加 PDFium 安装说明

### G2: `sup_recovery/layer3.rs` Vision LLM

**当前** 40 行 stub，全部返回 reject。

**目标**：实现真实的 Vision API 调用 + marker 校验。

```rust
//! Layer 3：Vision LLM 验证（PDF 截图 → vision API → marker 校验）。
//! ←→ FNM_RE/modules/sup_recovery.py 中的 Layer 3 部分（~250 行）

use crate::sup_recovery::pdf_render::render_page_to_base64_png;
use anyhow::{Context, Result};
use once_cell::sync::Lazy;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::time::Duration;

static HTTP_CLIENT: Lazy<Client> = Lazy::new(|| {
    Client::builder()
        .timeout(Duration::from_secs(180))
        .build()
        .expect("构造 HTTP client 失败")
});

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Layer3Candidate {
    pub page_no: i64,
    pub target_marker: String,
    pub context_region: String,  // 周围文本
}

#[derive(Debug, Clone)]
pub struct Layer3Result {
    pub page_no: i64,
    pub marker: String,
    pub accepted: bool,
    pub confidence: f64,
    pub reason: String,
}

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

/// Vision LLM 验证候选 marker（异步）。
/// 
/// ←→ Python `sup_recovery._layer3_vision_verify()`
pub async fn layer3_verify_with_vision(
    pdf_path: &str,
    candidates: &[Layer3Candidate],
    config: &VisionConfig,
) -> Result<Vec<Layer3Result>> {
    if config.api_key.is_empty() {
        anyhow::bail!("OPENAI_API_KEY 未设置，无法调用 Vision API");
    }
    
    // 并发处理所有候选
    let futures = candidates.iter().map(|c| verify_single_candidate(pdf_path, c, config));
    let results: Vec<Result<Layer3Result>> = futures::future::join_all(futures).await;
    
    results.into_iter().collect()
}

async fn verify_single_candidate(
    pdf_path: &str,
    candidate: &Layer3Candidate,
    config: &VisionConfig,
) -> Result<Layer3Result> {
    // 1. 渲染 PDF 页
    let pdf_path_owned = pdf_path.to_string();
    let page_index = candidate.page_no - 1;  // PDF 0-indexed
    let image_b64 = tokio::task::spawn_blocking(move || {
        render_page_to_base64_png(&pdf_path_owned, page_index, 150)
    }).await??;
    
    // 2. 构建 prompt
    let prompt = build_layer3_prompt(&candidate.target_marker, &candidate.context_region);
    
    // 3. 调 Vision API
    let response = HTTP_CLIENT
        .post(format!("{}/chat/completions", config.base_url))
        .bearer_auth(&config.api_key)
        .json(&json!({
            "model": config.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": format!("data:image/png;base64,{}", image_b64)
                    }}
                ]
            }],
            "max_tokens": 200,
            "temperature": 0.0,
        }))
        .send()
        .await
        .context("Vision API 请求失败")?;
    
    // 4. 解析响应
    let body: serde_json::Value = response.json().await?;
    let content = body["choices"][0]["message"]["content"]
        .as_str()
        .context("Vision API 响应格式错误")?;
    
    parse_layer3_response(content, &candidate.target_marker, candidate.page_no)
}

fn build_layer3_prompt(target_marker: &str, context: &str) -> String {
    // 严格对齐 Python 端的 prompt 模板
    format!(
        "查看页面图像。在以下上下文中是否存在上标 \"{}\"？\n\
        \n\
        上下文：{}\n\
        \n\
        如果存在且只有一个位置，回复 JSON: {{\"accepted\": true, \"confidence\": 0.9, \"reason\": \"unique location found\"}}\n\
        如果不存在，回复 JSON: {{\"accepted\": false, \"confidence\": 0.0, \"reason\": \"not found\"}}\n\
        如果有多个相同位置，回复 JSON: {{\"accepted\": false, \"confidence\": 0.0, \"reason\": \"ambiguous, multiple matches\"}}\n",
        target_marker, context
    )
}

fn parse_layer3_response(content: &str, marker: &str, page_no: i64) -> Result<Layer3Result> {
    // 提取 JSON（容忍 LLM 可能加 markdown ```json ... ``` 包装）
    let json_str = extract_json_block(content);
    let parsed: serde_json::Value = serde_json::from_str(&json_str)
        .with_context(|| format!("无法解析 LLM 响应为 JSON: {}", content))?;
    
    Ok(Layer3Result {
        page_no,
        marker: marker.into(),
        accepted: parsed["accepted"].as_bool().unwrap_or(false),
        confidence: parsed["confidence"].as_f64().unwrap_or(0.0),
        reason: parsed["reason"].as_str().unwrap_or("").into(),
    })
}

fn extract_json_block(content: &str) -> String {
    if let Some(start) = content.find('{') {
        if let Some(end) = content.rfind('}') {
            return content[start..=end].to_string();
        }
    }
    content.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn extract_json_from_markdown() {
        let resp = "```json\n{\"accepted\": true, \"confidence\": 0.9, \"reason\": \"found\"}\n```";
        let extracted = extract_json_block(resp);
        assert!(extracted.contains("\"accepted\": true"));
    }
    
    #[test]
    fn parse_accepted_response() {
        let resp = r#"{"accepted": true, "confidence": 0.9, "reason": "unique"}"#;
        let result = parse_layer3_response(resp, "30", 5).unwrap();
        assert!(result.accepted);
        assert_eq!(result.confidence, 0.9);
    }
    
    #[test]
    fn parse_rejected_response() {
        let resp = r#"{"accepted": false, "confidence": 0.0, "reason": "not found"}"#;
        let result = parse_layer3_response(resp, "30", 5).unwrap();
        assert!(!result.accepted);
    }
    
    #[tokio::test]
    #[ignore = "需要真实 OPENAI_API_KEY"]
    async fn real_vision_call() {
        let candidate = Layer3Candidate {
            page_no: 1,
            target_marker: "1".into(),
            context_region: "...test...".into(),
        };
        let config = VisionConfig::default();
        let pdf = "/Users/hao/OCRandTranslation/test_example/Biopolitics/Biopolitics.pdf";
        let results = layer3_verify_with_vision(pdf, &[candidate], &config).await.unwrap();
        assert_eq!(results.len(), 1);
    }
}
```

**关键点**：
- 用 `tokio::task::spawn_blocking` 包装 PDF render（pdfium-render 是同步的）
- `futures::future::join_all` 并发处理多个候选（不是 Python 的顺序）
- mock 测试覆盖响应解析；真实 API 测试加 `#[ignore]`

**Cargo.toml 加**：
```toml
futures = "0.3"
```

### G3: `visual_anchor_recovery/` 完整实现

**当前**（6 行空函数）：
```rust
pub fn build_visual_recovery_overrides() -> serde_json::Value {
    serde_json::json!({})
}
```

**目标**：拆为 4 个子模块。

```
fnm-phase2/src/visual_anchor_recovery/
├── mod.rs                  # 主入口 build_visual_recovery_overrides
├── gap_detection.rs        # 检测缺口（已知 markers vs 实际找到的 anchors）
├── vision_client.rs        # 调用 vision LLM（复用 G2 的 HTTP_CLIENT）
└── override_builder.rs     # 构建 ReviewOverride 写回 DB
```

**详细规格**：

```rust
//! ←→ FNM_RE/modules/visual_anchor_recovery.py (1017 行)
//! 视觉锚点恢复：检测正文中缺失的 marker → 调 vision LLM 验证 → 写 review_override。

// src/visual_anchor_recovery/mod.rs
pub async fn build_visual_recovery_overrides(
    pages: &[fnm_phase1::input::RawPage],
    chapter_markers: &std::collections::HashMap<String, std::collections::HashSet<String>>,
    pdf_path: &str,
    config: &crate::sup_recovery::layer3::VisionConfig,
) -> anyhow::Result<Vec<ReviewOverride>>;

// src/visual_anchor_recovery/gap_detection.rs
/// 检测每章 marker 缺口：已知 markers 集合 - 已找到的 anchors 集合。
/// ←→ Python `_detect_chapter_marker_gaps()`
pub fn detect_chapter_marker_gaps(
    chapter_id: &str,
    expected_markers: &HashSet<String>,
    found_anchors: &[BodyAnchorRecord],
) -> Vec<GapCandidate>;

pub struct GapCandidate {
    pub chapter_id: String,
    pub marker: String,
    pub expected_page_range: (i64, i64),
    pub context_pages: Vec<i64>,
}

// src/visual_anchor_recovery/override_builder.rs
/// 把 LLM 接受的 marker 构建为 anchor override（写到 fnm_review_overrides_v2）。
/// ←→ Python `_build_visual_anchor_override()`
pub fn build_anchor_override(
    chapter_id: &str,
    page_no: i64,
    marker: &str,
    confidence: f64,
) -> ReviewOverride;
```

**关键算法**（按 Python 1017 行逐段翻译）：
1. 对每章构建 expected_markers（来自 note_items）
2. 对比 found_anchors，找缺口
3. 对每个缺口，确定候选页范围（从 chapter.start_page 到 end_page）
4. 调 G2 的 vision 验证
5. 接受的 marker 构建 override

**测试**：
- 单元测试：mock vision client，验证 gap detection 逻辑
- 集成测试：Biopolitics 真实数据，至少 10 个章的缺口检测正确

### G4: `llm_bare_digit_verify/` 完整实现

**当前**（7 行空函数）。**目标**：拆 4 个子模块。

```
fnm-phase2/src/llm_bare_digit_verify/
├── mod.rs              # 主入口 verify_bare_digit_candidates
├── prompt_builder.rs   # prompt 模板
├── llm_client.rs       # API 调用（复用 G2 HTTP_CLIENT）
└── response_parser.rs  # JSON 解析
```

**职责**：
- 对 Phase 3 body_anchors 中 `source = "bare_digit"` 的候选（高假阳性率），用 vision LLM 二次确认
- 输出：哪些 candidate 接受（保留）哪些拒绝（删除）

按 Python 221 行翻译。算法不复杂，主要是 prompt 工程 + 响应解析。

### G5: `llm_book_type_verify/` Phase 1c 完整实现

**当前**（64 行 stub，显式 `deferred`）。

**目标**：拆 4 个子模块（参考 G3 / G4 的结构）。

按 Python 1039 行翻译。这是 Phase 1 的 1c 步——用 vision 看代表性页面验证 Phase 1b 的 book_type 判定。

虽然 Python 行数大，但 Rust 实现重点是 HTTP/JSON 处理，预估 600-800 行。

### G6: 共享 LLM HTTP 客户端模块

G1-G5 都用 HTTP_CLIENT。建议抽到 `fnm-core` 加一个 `llm_http` 模块（**先发 issue 给 fnm-core，等批准再加**）。在此之前，G2 把 HTTP_CLIENT 放在 layer3.rs，G3-G5 复用 `crate::sup_recovery::layer3::HTTP_CLIENT`。

---

## 5. 不要碰的任务

以下任务**不在你的范围**，留给另一个高保真模型：

- **F2+**：`note_regions/mod.rs` 拆成 5 个子模块 + 补完所有 5 类 region source
- **F3+**：`note_items/mod.rs` 拆子模块 + 跨页 continuation + 引文缩写多 pass
- **F4+**：`heading_candidates.rs` 字体检测 + family 聚类 + reject 启发式（Python 827 行）
- **F7+**：`page_partition/role_heuristics.rs` 业务分支严格保真（**只做 R1 的 Regex 上移，不动业务逻辑**）

如果你在做 R1-R4 / G1-G5 时**感觉**需要改这些文件的算法分支，**停下来**，写到 PR 描述说"建议挂起，等 F2+/F3+/F4+/F7+ 处理"。

---

## 6. PR 流程

### R0 PR 提交

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
# 完成 R1-R4 后
~/.cargo/bin/cargo fmt
~/.cargo/bin/cargo clippy --all-targets -- -D warnings
~/.cargo/bin/cargo test --all
# 上面三条全绿后再 commit
```

PR title: `R1-R4: Phase 1/2 反模式重构（Lazy regex + fnm-core 复用 + persist bug 修复）`

### G1-G5 PR 提交

**每个 G 一个 PR**（不要合并）。每个 PR 完成后做一轮：
```
~/.cargo/bin/cargo test --all
~/.cargo/bin/cargo clippy --all-targets -- -D warnings
```

---

## 7. 自我验收 checklist（每个 PR 必填）

提交前自查：

### 代码层
- [ ] 0 个新增 `let _ = ...` 忽略关键参数
- [ ] 0 个新增 `#![allow(clippy::*)]` 抑制
- [ ] 0 个返回 `json!({})` / `Ok(vec![])` 的静默 stub（未实现的用 `anyhow::bail!`）
- [ ] 0 个循环内 `Regex::new()`
- [ ] 0 个 `Rc<RefCell>` / 0 个新增 `Arc<Mutex>`（除非用户明确批准）
- [ ] 所有公开函数 doc comment 标 Python 对应 `←→ Python xxx()`

### 复用层
- [ ] PR 描述列出复用的 fnm-core API（具体到模块/常量名）
- [ ] 没复用的部分解释为什么（fnm-core 没有 → 应该先去 fnm-core 加，不是在 phase crate 重新实现）

### 测试层
- [ ] `cargo test --all` 通过
- [ ] 新增功能有对应单元测试
- [ ] 涉及真实数据的功能加 `#[ignore]` 集成测试占位

### 性能层（G1-G5）
- [ ] PDF render 用全局 `Mutex<Pdfium>` 单例（不在每次调用创建）
- [ ] HTTP client 用全局 `Lazy<Client>` 单例
- [ ] LLM 调用支持并发（`futures::join_all` 或 `tokio::join!`）

---

## 8. 完成后通知方式

每个 PR 合并后，更新 `FNM_PHASE12_AUDIT.md` 的对应行（把 🔴 / ⚠️ 改为 ✅），并在 PR 评论里说"完成 R1"、"完成 G1" 等。

R1-R4 + G1-G5 全部完成后，通知用户做最终代码审计。

---

## 9. 风险与边界

| 风险 | 处理 |
|---|---|
| `pdfium-render` 二进制依赖找不到 | macOS: `brew install pdfium-binaries`；Linux: 从 https://github.com/bblanchon/pdfium-binaries 下载 |
| `OPENAI_API_KEY` 在 CI 不可用 | 真实 API 测试都加 `#[ignore]`，CI 跑 mock |
| LLM 响应解析失败 | 用 `extract_json_block` 容错；失败时返回 `Result::Err`，不静默吞 |
| Phase 2 的 `output.chapters` 与 Phase 1 写过的 chapters 冲突 | R4 用 read-back 方案保证不丢；后续可改 fnm-core Repository 契约 |

---

**就这些。开工前最后一遍：先看 AGENTS.md 的 12 条铁律，再看 FNM_PHASE12_AUDIT.md 知道历史问题，然后从 R1 开始**。
