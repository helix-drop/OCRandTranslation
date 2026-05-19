# `fnm-phase3` 实施计划

> 🟢 **状态：100% 完成（2026-05-17）**
>
> - 26 lib tests + 27 集成测试通过（25 SPEC + 2 smoke）
> - 10 个核心模块全部 1:1 翻译完成：
>   - `body_anchors/` 19/19 函数
>   - `note_linking/` 23 函数拆 14 子模块（含 OCR repair 3 loops + chapter_contracts + evidence_assemble）
>   - `endnote_links` / `footnote_links` / `chapter_anchor_alignment`（DP + rayon 并行）/ `paragraph_footnotes` / `paragraph_endnotes`
> - 5 个 byte-equal parity `#[ignore]` 等 Phase 2 cascade（详见 [`fnm_re_rs/fnm-phase3/tests/known_python_bugs.md`](../fnm_re_rs/fnm-phase3/tests/known_python_bugs.md) §7）
> - 完整完成度见 [`fnm_re_rs/FNM_RE_REFACTOR.md` §2.4](../fnm_re_rs/FNM_RE_REFACTOR.md)
>
> 本文档作为历史实施计划保留。下方原文档内容未修改。

---

本文档是**自包含的**——新 session 接手者读完本文件 + AGENTS.md Rust 规范 + 一份 audit 报告，即可开工 Phase 3。不需要任何前序对话上下文。

---

## 0. 项目背景（30 秒读完）

正在做 Python `FNM_RE/` 到 Rust `fnm_re_rs/` 的全量重写，按 6-Phase pipeline 拆分：

| Phase | crate | 状态 |
|---|---|---|
| 0 基础设施 | `fnm-core` | ✅ 已完成（91 测试）|
| 1 章节骨架 | `fnm-phase1` | ✅ 已完成（Biopolitics chapter 12/12 byte-equal Python）|
| 2 注释结构 + note_kind | `fnm-phase2` | ✅ 已完成（region 75/75 byte-equal，items +35 over-extraction 非阻塞）|
| **3 body anchor + link 匹配** | **`fnm-phase3`** | **🔄 本文档** |
| 4 翻译单元 | `fnm-phase4` | ⏳ 未开始 |
| 5 章 markdown 合并 | `fnm-phase5` | ⏳ 未开始 |
| 6 导出审计 | `fnm-phase6` | ⏳ 未开始 |
| LLM repair (3.5) | `fnm-llm-repair` | ⏳ 未开始 |

当前测试套件：282 passed, 5 ignored, 0 failed。`cargo clippy -D warnings` clean。

---

## 1. 必读前置（按顺序）

| # | 路径 | 重点章节 | 必读理由 |
|--:|---|---|---|
| 1 | `/Users/hao/OCRandTranslation/AGENTS.md` | "Rust 重构代码规范（fnm_re_rs/）" 12 条铁律 | 风格 / 反模式禁止 |
| 2 | `/Users/hao/OCRandTranslation/CLAUDE.md` | 全文 + 第 12 条"树枝状条件处理" | 项目级业务约束 |
| 3 | `/Users/hao/OCRandTranslation/FNM_RE/RUST_MIGRATION_PLAN.md` | "Step 3: 锚点 + 链接" 段 | 全局架构定位 |
| 4 | `/Users/hao/OCRandTranslation/FNM_RE/FNM_PHASE12_AUDIT.md` | 全文 | 看 Phase 1/2 历史问题，避免重蹈 |
| 5 | `/Users/hao/OCRandTranslation/FNM_RE/fnm-phase1/tests/known_python_bugs.md` 和 phase2 同名文件 | 全文 | 知道上游 Phase 1/2 与 Python 的当前 diff |

**特别看 AGENTS.md 的 12 条铁律**——任何违反都会被审计拒绝。简版：

1. 翻译保真度（Rust 行数应是 Python 80-120%）
2. Regex 必须用 `Lazy<Regex>` 静态
3. 复用 fnm-core 基础设施
4. 单文件 mod.rs < 400 行
5. 每个 pub fn 标 `←→ Python xxx()`
6. 测试用真实 fixture
7. Parity 必须 byte-equal Python，不接受 simplified
8. 不允许 `let _ = ...` 忽略关键参数
9. Stub 用 `anyhow::bail!`，不静默返回空值
10. 0 `Rc<RefCell>` / 0 滥用 `Arc<Mutex>`
11. `.clone()` 节制
12. PR 验收 checklist 12 项

---

## 2. Phase 3 目标与职责

### 输入

通过 SQLite DB 读取 Phase 1 + Phase 2 产物（**不在内存里接收 Phase2Structure**——所有 phase 间通信走 DB）：

| 表 | 内容 |
|---|---|
| `fnm_pages` | page_role / has_note_heading / note_scan_summary |
| `fnm_chapters` | chapter_id / start_page / end_page |
| `fnm_section_heads` | section heads（参考） |
| `fnm_note_regions` | region_id / chapter_id / note_kind / pages |
| `fnm_note_items` | note_item_id / chapter_id / marker / note_kind / text |
| `fnm_chapter_note_modes` | chapter_id / note_mode |

加上 raw_pages.json（含 markdown / blocks / fnBlocks 等）。

### 输出

| 表 | 内容 | Phase 3 入口函数 |
|---|---|---|
| `fnm_body_anchors` | anchor_id / chapter_id / page_no / marker / anchor_kind | `build_body_anchors` |
| `fnm_note_links` | link_id / anchor_id / note_item_id / status (matched/orphan_note/orphan_anchor) | `build_note_links` + `build_endnote_links` + `build_footnote_links` |
| `fnm_chapter_anchor_alignment` | 章级 DP 对齐结果 | `build_chapter_anchor_alignment` |
| `fnm_paragraph_footnotes` | 段落级 footnote 引用（layout-based） | `build_paragraph_footnotes` |
| `fnm_chapter_endnotes` | 章级 endnote 参考 | `build_paragraph_endnotes` |

### Phase 边界纪律（CLAUDE.md 第 8 条 + 12 条最高优先级）

Phase 3 **绝对不做**：
- ❌ **重分类 note_kind**（Phase 2 唯一来源，Phase 3 只透传 `region.note_kind` / `item.note_kind`）
- ❌ **用 chapter_mode 跳过修复**（Phase 3 必须对所有 chapter 跑同一套 anchor 检测 + link 匹配）
- ❌ 修改 note_regions / note_items / chapter_note_modes（Phase 2 已写入 DB）
- ❌ 合并章 markdown（Phase 5 的事）
- ❌ 调 LLM repair（Phase 3.5 的事）

Phase 3 **该做**：
- ✅ 在正文中检测 body anchor（上标 / 方括号 / Unicode 上标 / OCR 修复后的 bare digit）
- ✅ 匹配 anchor ↔ note_item（按 marker + chapter + kind）
- ✅ DP 对齐章级 anchor 序列与 note_item 序列
- ✅ 标记 orphan_anchor（找到 anchor 但无对应 note_item）/ orphan_note（note_item 但无 anchor）
- ✅ 段落级 footnote 检测（用 paragraph layout）

---

## 3. Python 源对应

| Python 路径 | 行数 | 函数数 | Rust 子模块建议 |
|---|---:|---:|---|
| `FNM_RE/stages/body_anchors.py` | 682 | 19 | `body_anchors/` 拆 3-4 子模块（regex pool / context guard / gap recovery） |
| `FNM_RE/stages/note_links.py` | 189 | 2 | `note_links.rs` 单文件 |
| `FNM_RE/stages/endnote_links.py` | 305 | 4 | `endnote_links.rs` |
| `FNM_RE/stages/footnote_links.py` | 239 | 2 | `footnote_links.rs` |
| `FNM_RE/stages/chapter_anchor_alignment.py` | 210 | 5 | `chapter_anchor_alignment.rs`（DP 算法）|
| `FNM_RE/stages/paragraph_footnotes.py` | 308 | 7 | `paragraph_footnotes.rs` |
| `FNM_RE/stages/paragraph_endnotes.py` | 257 | 8 | `paragraph_endnotes.rs` |
| `FNM_RE/stages/_link_utils.py` | 141 | 7 | `link_utils.rs`（共享工具）|
| `FNM_RE/modules/note_linking.py` | 1,730 | 23 | `lib.rs` + 多子模块（**最大头**）|
| **合计** | **4,061 行** Python | — | → 预计 **5,500-6,500 行** Rust |

### `modules/note_linking.py` 内部子拆分

Python 端 1,730 行单文件混了 9 个职责。Rust 端必须按以下子模块拆（mod.rs < 400 行）：

```
fnm-phase3/src/note_linking/
├── mod.rs                          # build_note_link_table 顶层编排
├── anchor_summary.rs               # _refresh_anchor_summary
├── layer_conversion.rs             # _to_anchor_layers / _to_link_layers
├── link_summary.rs                 # _summarize_links / _link_quality_gate
├── chapter_meta.rs                 # _build_note_item_meta_by_id / _build_book_endnote_stream_summary
├── note_kind_inference.rs          # _infer_note_kind_from_anchor / _anchor_kind_compatible
├── chapter_body_text.rs            # _chapter_body_text_by_page
├── anchor_overrides.rs             # _materialize_anchor_overrides + _has_existing_explicit_anchor_for_override + _find_existing_explicit_anchor_for_link_override
├── note_item_overrides.rs          # _materialize_note_item_overrides
├── link_overrides.rs               # _apply_link_overrides
├── ocr_repair.rs                   # _repair_explicit_footnote_anchor_ocr_variants
├── phase2_rebuild.rs               # _phase2_from_chapter_layers (从 DB 重建用)
├── chapter_contracts.rs            # _chapter_contracts (合同检查 + 修复决策)
└── for_chapter.rs                  # build_note_links_for_chapter (单章入口)
```

---

## 4. crate 结构与实施顺序

### Cargo.toml

```toml
[package]
name = "fnm-phase3"
version = "0.1.0"
edition = "2021"

[dependencies]
fnm-core = { path = "../fnm-core" }
fnm-phase1 = { path = "../fnm-phase1" }
fnm-phase2 = { path = "../fnm-phase2" }

serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
regex = "1.10"
once_cell = "1.19"
thiserror = "1.0"
anyhow = "1.0"
tracing = "0.1"
rayon = "1.10"
aho-corasick = "1.1"

[dev-dependencies]
insta = { version = "1.34", features = ["json"] }
pretty_assertions = "1.4"
tempfile = "3.10"
```

`fnm_re_rs/Cargo.toml` workspace 加 `fnm-phase3` member。

### 模块拆分

```
fnm-phase3/src/
├── lib.rs                          # crate 入口 + build_phase3_structure
├── input.rs                        # Phase3Input（从 fnm-core records 重用）
├── output.rs                       # Phase3Output 薄包装
├── body_anchors/
│   ├── mod.rs                      # build_body_anchors 编排
│   ├── pattern_scan.rs             # 11 个正则模式扫描（HTML_SUP_RE 等已在 fnm-core）
│   ├── context_guard.rs            # _positive_gate_bare_digit + bare_digit_false_positive
│   ├── gap_recovery.rs             # _recover_expected_gap_bare_digit_anchors + _recover_expected_gap_symbol_anchors
│   └── chapter_marker_sets.rs     # _build_chapter_endnote_marker_set + _build_chapter_note_items_set
├── note_links.rs                   # build_note_links（orphan_anchor 路径）
├── endnote_links.rs                # build_endnote_links + 模糊匹配
├── footnote_links.rs               # build_footnote_links
├── chapter_anchor_alignment/
│   ├── mod.rs                      # build_chapter_anchor_alignment 入口
│   └── dp_alignment.rs             # DP 算法（Needleman-Wunsch 风格）
├── paragraph_footnotes.rs          # build_paragraph_footnotes（layout-based）
├── paragraph_endnotes.rs           # build_paragraph_endnotes
├── link_utils.rs                   # _link_candidate_anchors / _is_fallback_chapter_id 等
└── note_linking/                   # ← modules/note_linking.py 的子拆分（见 §3）
    ├── mod.rs                      # build_note_link_table 顶层编排（~300 行）
    └── ...                         # 13 个子模块
```

### 实施顺序（13 个任务，~5 周）

| # | 任务 | 工时 | 依赖 |
|--:|---|---:|---|
| P3.0 | Cargo 骨架 + parity fixture 工具扩展 | 0.5 天 | - |
| P3.1 | `input.rs` + `output.rs` 类型契约 | 0.5 天 | P3.0 |
| P3.2 | `body_anchors/pattern_scan` — 正则扫描 + Lazy 模式 | 1.5 天 | P3.1 |
| P3.3 | `body_anchors/context_guard` — bare digit 正向门 | 2 天 | P3.2 |
| P3.4 | `body_anchors/gap_recovery` — 缺口恢复（含 SPEC 2,3） | 2.5 天 | P3.3 |
| P3.5 | `body_anchors/chapter_marker_sets` + `mod.rs` 编排 | 1 天 | P3.4 |
| P3.6 | `note_links.rs` + `link_utils.rs` — orphan_anchor 路径 | 1.5 天 | P3.5 |
| P3.7 | `endnote_links.rs` — 模糊匹配 + chapter 范围检查 | 2 天 | P3.6 |
| P3.8 | `footnote_links.rs` — 页级精确匹配 | 1 天 | P3.6 |
| P3.9 | `chapter_anchor_alignment/dp_alignment` — DP 算法 | 2 天 | P3.6 |
| P3.10 | `paragraph_footnotes.rs` + `paragraph_endnotes.rs` — layout-based | 2 天 | P3.1 |
| P3.11 | `note_linking/` — 顶层编排 + 13 子模块（**最大头**） | 6 天 | P3.6-P3.10 |
| P3.12 | `lib.rs::build_phase3_structure` + DB 持久化 | 1 天 | P3.11 |
| P3.13 | Biopolitics parity + 4 SPEC 测试翻译 | 2 天 | P3.12 |
| **总计** | | **~25 天** | |

可并行点：P3.10（段落 footnote/endnote）和 P3.7-P3.9 之间可以双人分头做。

---

## 5. 各任务详细规格

### P3.0: Cargo 骨架（0.5 天）

1. `fnm_re_rs/Cargo.toml` workspace 加 `fnm-phase3` member
2. 创建 `fnm_re_rs/fnm-phase3/{Cargo.toml, src/lib.rs}`
3. `tools/gen_biopolitics_phase3_golden.py` 脚手架（参考 phase1/2 同名脚本）
4. 测试目录 `tests/fixtures/`

**验收**：`cargo build -p fnm-phase3` 通过。

### P3.1: 类型契约（0.5 天）

`fnm-core` 已经定义了所有 Phase 3 Record 类型（`BodyAnchorRecord` / `NoteLinkRecord` / `ChapterAnchorAlignmentRecord` / `ParagraphFootnoteRecord` / `ChapterEndnoteRecord` / `Phase3Structure` / `Phase3Summary`），**不要重新定义**。

`input.rs`：
```rust
use fnm_core::records::*;
use fnm_phase1::input::RawPage;

pub struct Phase3Input<'a> {
    pub phase1_chapters: &'a [ChapterRecord],
    pub phase1_pages: &'a [PagePartitionRecord],
    pub phase2_note_regions: &'a [NoteRegionRecord],
    pub phase2_note_items: &'a [NoteItemRecord],
    pub phase2_chapter_note_modes: &'a [ChapterNoteModeRecord],
    pub raw_pages: &'a [RawPage],
    pub pdf_path: Option<&'a str>,
    pub config: Phase3Config,
}

#[derive(Default)]
pub struct Phase3Config {
    pub skip_llm_verify: bool,
}
```

### P3.2: `body_anchors/pattern_scan` — 正则扫描（1.5 天）

**Python 源**：`stages/body_anchors.py` 第 1-200 行（约 11 个正则模式 + `_scan_inline_refs`）

**关键复用 fnm-core**：所有正则模式已在 `fnm_core::anchor_kind::patterns` 模块（HTML_SUP_RE / LATEX_SUP_RE / FOOTNOTE_REF_RE / BRACKET_REF_RE / UNICODE_SUP_RE / APOSTROPHE_SUP_RE / HTML_SYMBOL_SUP_RE / LATEX_SYMBOL_SUP_RE / BARE_DIGIT_RE / PLAIN_SUP_RE）。**不要重新定义**。

```rust
// pattern_scan.rs 公开 API
use fnm_core::anchor_kind::patterns::*;
use fnm_core::records::BodyAnchorRecord;

pub fn scan_inline_refs(text: &str, page_no: i64, chapter_id: &str) -> Vec<RawAnchor>;

pub struct RawAnchor {
    pub source_marker: String,
    pub normalized_marker: String,
    pub char_start: i64,
    pub char_end: i64,
    pub pattern: String,  // "html_sup" / "footnote_ref" / "bracket" / "bare_digit" 等
    pub certainty: f64,
}
```

特别注意：
- Rust regex 不支持 lookaround，`BRACKET_REF_RE` 已用 `is_bracket_ref_valid()` helper 补偿（在 fnm-core）
- 不要重写 fnm-core 已有的 helper

### P3.3: `body_anchors/context_guard` — bare digit 正向门（2 天）

**Python 源**：`stages/body_anchors.py:_positive_gate_bare_digit` (line 197-285)

bare_digit 是最弱信号（priority 6），假阳性多。Python 用三层守卫：
1. 左侧至少 3 字符的词，词不在结构前缀集（`thesis` / `page` / `chapter` / `vol` 等）
2. 右侧标点后不紧跟数字（排除列表 / 日期 / 千分位）
3. 章级别正向证据：在 chapter_note_items 集合中

按 Python 行为严格 1:1 翻译。

**SPEC 测试**：`test_superscript_note_definition_lines_are_filtered` — note 定义行不应作为 body anchor

### P3.4: `body_anchors/gap_recovery`（2.5 天）

**Python 源**：`stages/body_anchors.py:_recover_expected_gap_*` (line 387-560)

核心算法：已知章级 marker 集合 = `{1,2,...,N}`；如果检测到 anchor 序列只有 `{1,2,4,5}`（缺 3），用启发式从 page text 找缺失的 3：
- 数字 bare_digit 路径
- symbol marker 路径（`*` `**` `†` 等映射到数字）

**SPEC 测试**：
- `test_expected_gap_recovery_keeps_weak_endnote_digits_under_positive_gate`（marker [8,11] gap 中识别 9, 10）
- `test_expected_gap_recovery_can_disambiguate_symbol_ocr_by_note_text`（gap 7,9 中用 endnote 定义文本确定 8）

### P3.5: `body_anchors/mod.rs` 顶层（1 天）

**Python 源**：`stages/body_anchors.py:build_body_anchors` (line 559-682)

```rust
pub fn build_body_anchors(
    phase2: &Phase2Layers,
    pages: &[RawPage],
    pdf_path: &str,
    bare_digit_verifier: Option<Box<dyn Fn(...) -> ...>>,
) -> (Vec<BodyAnchorRecord>, BodyAnchorSummary);
```

**注意**：Python 端 LLM bare digit verify 通过 `bare_digit_verifier` 回调注入（避免 stages → modules 反向依赖）。Rust 端遵循同样模式——`bare_digit_verifier` 是可选 callback，调用方（modules 层 / phase3 顶层编排）注入 fnm-llm-repair 或 mock。

### P3.6: `note_links.rs` + `link_utils.rs`（1.5 天）

**Python 源**：`stages/note_links.py` (189 行) + `stages/_link_utils.py` (141 行)

`note_links.rs::build_note_links` 处理 orphan_anchor 路径——anchor 找不到对应 note_item 时，生成 status=orphan_anchor 的 NoteLinkRecord。

关键逻辑（line 69-158）：
1. 遍历 body_anchors
2. 跳过 synthetic / used_anchor_ids / 已 matched 的
3. 检查 (chapter_id, anchor_kind, marker) 不在 note_item_marker_keys 中
4. fallback_chapter 守卫：anchor 在 fallback chapter（不是 toc chapter）且 marker 不在 note_kind_with_markers 中，跳过
5. 产出 NoteLinkRecord(status=orphan_anchor, anchor_id, note_item_id="")

### P3.7: `endnote_links.rs`（2 天）

**Python 源**：`stages/endnote_links.py` (305 行)

endnote 是按 chapter 范围匹配——marker 必须在章 endnote marker range 内：
```python
def build_endnote_links(body_anchors, phase2, pages):
    for anchor in body_anchors:
        if anchor.anchor_kind != "endnote": continue
        # 查找匹配的 note_item
        for item in phase2.note_items:
            if item.note_kind != "endnote": continue
            if item.chapter_id != anchor.chapter_id: continue
            if item.marker == anchor.normalized_marker:
                # match
```

加上 OCR 容错（如 `7` vs `1` 互换、`5` vs `S` 等），和模糊匹配候选。

### P3.8: `footnote_links.rs`（1 天）

**Python 源**：`stages/footnote_links.py` (239 行)

footnote 按页精确匹配——同页或相邻页（footnote_band 区域）：
- anchor 在 page P 上找到
- 匹配的 footnote item 应在同章节 P-N..P+M 页范围内
- N/M 由 chapter.note_mode 决定

### P3.9: `chapter_anchor_alignment/dp_alignment` — DP 算法（2 天）

**Python 源**：`stages/chapter_anchor_alignment.py` (210 行)

章级序列对齐：anchor 序列 vs note_item 序列。经典 Needleman-Wunsch 风格 DP，输出对齐路径（match / insert_anchor / delete_anchor）。

```rust
pub fn chapter_anchor_alignment(
    chapter_id: &str,
    anchors: &[&BodyAnchorRecord],
    items: &[&NoteItemRecord],
) -> ChapterAnchorAlignmentRecord;
```

复杂度 O(N×M) 章级数据集 N,M 都 < 100，性能不是问题。但**要并发**——`rayon::par_iter` 按 chapter 并行。

### P3.10: 段落级 footnote/endnote（2 天）

**Python 源**：`stages/paragraph_footnotes.py` (308 行) + `paragraph_endnotes.py` (257 行)

基于 page layout（fnBlocks）的段落级 footnote 检测。补充 anchor scan 不覆盖的 layout-only 引用。

### P3.11: `note_linking/` 顶层编排（6 天，**最大头**）

**Python 源**：`FNM_RE/modules/note_linking.py` (1,730 行)

按 §3 拆为 14 个子模块。最核心的：
- `build_note_link_table` (mod.rs)：顶层编排，调用 P3.2-P3.10 所有子任务并合成 NoteLinkTable
- `_apply_link_overrides`：消费 `fnm_review_overrides_v2` 中 link scope 的 override
- `_materialize_anchor_overrides`：消费 anchor scope override（手工/LLM 创建的合成 anchor）
- `_chapter_contracts`：合同检查（contract_v2_def_anchor_mismatch_count 等）
- `_repair_explicit_footnote_anchor_ocr_variants`：OCR 变体修复

**SPEC 测试**：`test_biopolitics_contract_v2_def_anchor_mismatch_is_resolved`——Biopolitics 的 endnote 定义数与正文 anchor 数应对齐。

### P3.12: 顶层编排 + DB 持久化（1 天）

```rust
// fnm-phase3/src/lib.rs
pub fn build_phase3_structure(input: Phase3Input) -> anyhow::Result<Phase3Output>;

pub fn persist_phase3(
    repo: &dyn fnm_core::db::Repository,
    doc_id: &str,
    output: Phase3Output,
) -> anyhow::Result<()>;
```

DB 写 5 张表：`fnm_body_anchors` / `fnm_note_links` / `fnm_chapter_anchor_alignment` / `fnm_paragraph_footnotes` / `fnm_chapter_endnotes`。

**fnm-core 已有 `replace_fnm_phase3_products`**（参考 fnm-phase2 同样模式）。如果该方法缺字段，先去 fnm-core 补，不要在 phase3 内重写 SQL。

### P3.13: Biopolitics parity + SPEC 测试（2 天）

参考 `fnm-phase2/tests/biopolitics_phase2_parity.rs` 模板：

1. `tools/gen_biopolitics_phase3_golden.py` — 跑 Python `build_note_link_table` 输出 golden
2. `tests/biopolitics_phase3_parity.rs` — 4 个逐字段测试：
   - body_anchors field-by-field（kind + page + marker 严格 byte-equal）
   - note_links field-by-field（status + anchor_id + note_item_id）
   - chapter_anchor_alignment（DP 输出）
   - phase3_coverage_is_documented（自检 + known_python_bugs.md 存在）
3. `tests/test_phase3_spec.rs` — 4 个 SPEC 翻译：
   - `spec_superscript_note_definition_filtered`
   - `spec_expected_gap_keeps_weak_digits`
   - `spec_expected_gap_disambiguates_by_text`
   - `spec_biopolitics_contract_v2_def_anchor_mismatch`
4. `tests/known_python_bugs.md` 占位（如有 diff 才记录）

**Parity 标准**：byte-equal Python，不接受 simplified。任何 diff 必须在 `known_python_bugs.md` 记录根因。

---

## 6. 4 个 SPEC 测试详细位置

| Rust 测试 | Python 来源 | 含义 |
|---|---|---|
| `spec_superscript_note_definition_filtered` | `tests/unit/test_fnm_re_phase3.py:200` | note 定义行（如 `¹ ...`）不应作为 body anchor |
| `spec_expected_gap_keeps_weak_digits` | `test_fnm_re_phase3.py:520` | marker `[8,11]` gap 中 `9`、`10` 应识别为 endnote |
| `spec_expected_gap_disambiguates_by_text` | `test_fnm_re_phase3.py:566` | gap `(7,9)` 中通过 endnote 定义文本确定 `8` |
| `spec_biopolitics_contract_v2_def_anchor_mismatch` | `test_fnm_re_module4_linking.py:201` | Biopolitics endnote 定义数 = anchor 数 |

打开 Python 测试文件查看原始测试代码（`@unittest.skip("[rust-migration: SPEC] ...")` 装饰器下），翻译为 Rust 集成测试。

---

## 7. 性能基线

- chapter_anchor_alignment：`rayon::par_iter` 按 chapter 并行（Biopolitics 12 章可并行）
- regex：全部 `once_cell::Lazy<Regex>` 静态
- DB 写入：用 `Repository::replace_fnm_phase3_products` 批量 INSERT（不要逐行）

**目标**：Biopolitics phase3 < 2 秒（Python 约 30-60 秒）

---

## 8. 验收 checklist（每个 PR）

### 代码层
- [ ] `cargo build --release -p fnm-phase3` 通过
- [ ] `cargo clippy -p fnm-phase3 -- -D warnings` 通过（0 新增 allow）
- [ ] `cargo fmt --check` 通过
- [ ] `cargo test --all` 通过（保持 282+ 测试，0 failed）
- [ ] 0 个 `let _ = ...` 忽略关键参数
- [ ] 0 个静默 stub（必须 `anyhow::bail!`）
- [ ] 0 个循环内 `Regex::new()`
- [ ] 0 `Rc<RefCell>` / 0 滥用 `Arc<Mutex>`

### 复用层
- [ ] PR 描述列出复用的 fnm-core / fnm-phase1 / fnm-phase2 API
- [ ] 所有 14 个 `fnm_core::anchor_kind::patterns::*` 正则已复用
- [ ] Phase 3 不重新定义 `BodyAnchorRecord` 等类型（用 fnm-core 的）

### Phase 边界纪律
- [ ] 0 处 `note_kind = ...` 赋值（只透传 region.note_kind / item.note_kind）
- [ ] 0 处用 `chapter_mode` 跳过 anchor 修复
- [ ] 不修改 `fnm_note_regions` / `fnm_note_items` / `fnm_chapter_note_modes`（只读）
- [ ] PR 描述明确声明："Phase 3 严守边界，note_kind 仅透传"

### Parity
- [ ] `biopolitics_phase3_parity.rs` 4 个 field_by_field 测试通过
- [ ] 4 个 SPEC 测试翻译并通过
- [ ] `known_python_bugs.md` 记录任何 Rust ≠ Python 的 diff（不接受 simplified）

### 文档
- [ ] 每个 `pub fn` 有 `←→ Python xxx()` doc comment
- [ ] 拆分子模块结构清晰（mod.rs < 400 行）

---

## 9. PR 流程

每个 P3.X 一个独立 PR。PR title：

```
P3.X: <模块名> — <核心功能>（<行数>）
```

例：`P3.2: body_anchors/pattern_scan — 11 个正则扫描（约 250 行）`

每个 PR 合并前我会做代码审查。**不要批量提交**——P3.5 没合不要开始 P3.6。

---

## 10. 已知风险与缓解

| 风险 | 缓解 |
|---|---|
| Phase 1/2 上游有 over-extraction（footnote +35 items）| Phase 3 透传不重新分类，over-extraction 由 Phase 4+ 的 contract 检查捕获 |
| `note_linking.py` 1730 行复杂度 | 按 §3 严格拆 14 子模块，每个 < 200 行 |
| DP 对齐算法边界条件 | 用 Biopolitics 真实数据做 fixture，逐章对比 |
| OCR 容错（数字字母混淆） | 在 `endnote_links.rs` / `footnote_links.rs` 实现，参考 Python 端 |
| fnm-core 缺 Phase 3 DB INSERT 逻辑 | P3.12 之前先查 `fnm-core/src/db/repository.rs::replace_fnm_phase3_products`，若 stub 状态先补 fnm-core |

---

## 11. 数据契约（fnm-core 已就绪）

Phase 3 输入输出类型全部在 `fnm-core/src/records.rs`：

| 类型 | 行号 |
|---|---:|
| `BodyAnchorRecord` | 282 |
| `ChapterEndnoteRecord` | 300 |
| `ParagraphFootnoteRecord` | 322 |
| `ChapterAnchorAlignmentRecord` | 340 |
| `NoteLinkRecord` | 356 |
| `Phase3Summary` | 372 |
| `Phase3Structure` | 430 |

每个字段都已对齐 Python `FNM_RE/models.py` 同名 dataclass。**不要重新定义**。

---

## 12. 开工 checklist

1. 读完 §1 必读前置（5 个文档）
2. `cd /Users/hao/OCRandTranslation/fnm_re_rs && ~/.cargo/bin/cargo test --all`（确认当前 282 测试通过）
3. P3.0 开始：建 Cargo 骨架
4. 每个 P3.X 一个 PR，标题严格按 §9 格式
5. 完成 P3.5 后跑一次完整 SPEC 测试验证 body_anchors 模块独立可用
6. P3.13 完成后通知用户做最终审计

---

**严格按计划顺序执行**。`note_linking.py` 6 天工时是最大风险点——如果做到 3 天发现工作量超 60%，立即停下来开 issue，可能需要更细的子拆分。
