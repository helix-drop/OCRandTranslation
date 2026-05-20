# FNM_RE → Rust 重构大纲

目标：把 FNM_RE 整个 6-Phase pipeline（含 LLM repair）用 Rust 重写，追求极致性能。

---

## 🟢 当前进度（2026-05-18）

| Phase | crate | 状态 | 测试 |
|---|---|---|---|
| 0 基础设施 | `fnm-core` | ✅ **100% 完成** | 110 lib + 9 其他 |
| 1 章节骨架 | `fnm-phase1` | ✅ **100% 完成** | 106 lib + 27 集成（1 chapter_boundary 待精调）|
| 2 注释结构 + note_kind | `fnm-phase2` | ✅ **100% 完成** | 140 lib + 18 集成 + biopolitics 6/6 |
| 3 body anchor + link 匹配 | `fnm-phase3` | ✅ **100% 完成** | 26 lib + 27 集成（5 ignored cascade）|
| **4 引用注入 + 翻译单元** | **`fnm-phase4`** | ✅ **100% M1-M5 完成** | **106 lib + 6 parity + 8 spec = 120 tests** |
| 5 章 markdown 合并 | `fnm-phase5` | ⏳ 未开始 | — |
| 6 导出 + 审计 | `fnm-phase6` | ⏳ 未开始 | — |
| LLM repair (3.5) | `fnm-llm-repair` | ✅ **100% 完成 + 二次审计通过** | **121 lib + 4 integration + 39 spec = 164 tests** |
| 横切 | `fnm-orchestrator` | ⏳ 未开始 | — |

**workspace 测试**：27 套件 · ~664 passed · 1 failed · 多 ignored。
完整报告：[`fnm_re_rs/FNM_RE_REFACTOR.md`](../fnm_re_rs/FNM_RE_REFACTOR.md)。

### 重要 ✅：所有 LLM 调用统一走 ResolvedModelSpec

fnm-core 新增基建 `model_capabilities.rs` / `config.rs` / `vision/spec.rs` 完整 port 了
Python `model_capabilities.py` + `config.py` + `persistence/storage.py` 的 LLM 配置链路：

- **5 家 provider**：DeepSeek / Qwen（含 VL / MT）/ MiMo / GLM / Kimi
- **fnm_model_pool 槽位**：通过 `config.json` 配置，运行时按 `provider_type` 自动路由
  base_url + API key
- **multi-spec fallback**：每个 LLM 调用按 pool 顺序遍历，第一槽失败自动尝试下一槽
- **环境变量降级**：`DASHSCOPE_API_KEY / DEEPSEEK_API_KEY / GLM_API_KEY / KIMI_API_KEY / MIMO_API_KEY`

使用场景：
- `fnm-phase1::llm_book_type_verify`
- `fnm-phase2::sup_recovery::layer3`
- `fnm-phase2::visual_anchor_recovery`
- `fnm-phase2::llm_bare_digit_verify`

---

## 历史 Python 规模

当前 Python 规模：**35,033 行 / 81 文件 / 5 个分层**

| 层 | 文件数 | 行数 | 角色 |
|---|---:|---:|---|
| shared | 17 | 2,678 | 工具与契约 |
| stages | 28 | 14,179 | 单步原子操作 |
| modules | 19 | 12,367 | 业务封装 |
| app | 9 | 6,535 | 顶层入口 |
| dev | 8 | 2,144 | 调试工具（不 port） |

Rust 项目结构：Cargo workspace `fnm_re_rs`，9 个 crate（2 个横切层 + 7 个阶段层）。

---

## 数据流总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          fnm-core （横切：类型、工具、DB）                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   raw_pages (JSON)                                                          │
│        │                                                                    │
│        ▼                                                                    │
│   ┌──────────────────┐                                                      │
│   │ Step 1: 章节骨架 │  crate: fnm-phase1                                   │
│   │  TOC / chapters  │  ── 写入 fnm_pages / fnm_chapters / fnm_section_heads│
│   └────────┬─────────┘                                                      │
│            ▼                                                                │
│   ┌──────────────────────────────────┐                                      │
│   │ Step 2: 注释识别                 │  crate: fnm-phase2                   │
│   │  note_regions + note_items       │  ↳ 子模块：fnm-sup-recovery          │
│   │  chapter_note_modes              │  ── 写入 fnm_note_* / fnm_chapter_* │
│   └────────┬─────────────────────────┘                                      │
│            ▼                                                                │
│   ┌──────────────────────────────────┐                                      │
│   │ Step 3: 锚点 + 链接              │  crate: fnm-phase3                   │
│   │  body_anchors + note_links       │  ── 写入 fnm_body_anchors           │
│   │  (orphan_note / orphan_anchor)   │       fnm_note_links                │
│   └────────┬─────────────────────────┘                                      │
│            ▼                                                                │
│   ┌──────────────────────────────────┐                                      │
│   │ Step 3.5: LLM 修复               │  crate: fnm-llm-repair               │
│   │  vision 调用 → override 物化     │  ── 写入 fnm_review_overrides       │
│   │  ↺ 触发 Step 1-3 重跑消费 override│                                     │
│   └────────┬─────────────────────────┘                                      │
│            ▼                                                                │
│   ┌──────────────────────────────────┐                                      │
│   │ Step 4: 引用注入 + 翻译单元      │  crate: fnm-phase4                   │
│   │  frozen_refs + translation_units │  ── 写入 fnm_translation_units      │
│   │  structure_reviews               │       fnm_structure_reviews         │
│   └────────┬─────────────────────────┘                                      │
│            ▼                                                                │
│   ┌──────────────────────────────────┐                                      │
│   │ Step 5: 章 markdown 合并         │  crate: fnm-phase5                   │
│   │  chapter_markdowns               │  ── 写入 fnm_chapter_markdowns      │
│   └────────┬─────────────────────────┘                                      │
│            ▼                                                                │
│   ┌──────────────────────────────────┐                                      │
│   │ Step 6: 导出 + 审计              │  crate: fnm-phase6                   │
│   │  export_chapters + audit         │  ── 写入 fnm_export_chapters        │
│   │  diagnostic_notes                │       fnm_diagnostic_*              │
│   └──────────────────────────────────┘                                      │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                fnm-orchestrator （横切：pipeline 编排 + pyo3）              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Phase 间通信走 SQLite**——每个 Phase 把产物写到对应表，下一个 Phase 从表读。这是天然语言无关接口，允许 Rust/Python 混跑。

---

## 横切层

### 横切 A: `fnm-core` — 基础类型 / 工具 / DB

所有 Phase 都依赖。先做完这层再开始 Step 1。

**Python 对应**：
```
FNM_RE/constants.py                    → src/types.rs (Literal → enum)
FNM_RE/models.py                       → src/records.rs (dataclass → struct + serde)
FNM_RE/shared/text.py                  → src/text.rs (Unicode 规范化、上标解析)
FNM_RE/shared/anchors.py               → src/anchors.rs (resolve_anchor_kind)
FNM_RE/shared/refs.py                  → src/refs.rs (NOTE_REF token + 嵌套清理)
FNM_RE/shared/marker_sequences.py      → src/marker_seq.rs
FNM_RE/shared/notes.py                 → src/notes.rs
FNM_RE/shared/note_lookup.py           → src/note_lookup.rs
FNM_RE/shared/note_modes.py            → src/note_modes.rs (canonical↔alias 双向 dict)
FNM_RE/shared/segments.py              → src/segments.rs
FNM_RE/shared/segment_codec.py         → src/segment_codec.rs
FNM_RE/shared/title.py                 → src/title.rs
FNM_RE/shared/chapters.py              → src/chapters.rs
FNM_RE/shared/review_overrides.py      → src/review_overrides.rs
FNM_RE/shared/ref_rewriter.py          → src/ref_rewriter.rs
FNM_RE/shared/export_constants.py      → src/export_constants.rs
FNM_RE/shared/token_counter.py         → src/token_counter.rs (用 tokenizers crate)
FNM_RE/shared/review.py                → src/review.rs
persistence/sqlite_schema.py           → migrations/*.sql
                                       → src/db.rs (rusqlite 连接池)
```

**关键设计**：
- `NoteKind` / `AnchorKind` / `NoteMode` / `PageRole` / `LinkStatus` 全部 `#[derive(Serialize, Deserialize)] enum`
- 所有 Record struct 派生 `serde::Serialize/Deserialize` → 能直接 JSON 互通 Python
- DB 访问统一封装：`Repository` trait 暴露 `read_pages` / `write_phase1_products` 等方法
- `chapter_id` 用 `String`（Rust 类型系统自然解决 Python 70+ 防御转换）

**工作量**：1 周

---

### 横切 B: `fnm-orchestrator` — pipeline 编排 + Python FFI

最后做。这层把所有 phase crate 串起来，并暴露 pyo3 接口给 Python 调用。

**Python 对应**：
```
FNM_RE/app/pipeline.py                 → src/pipeline.rs (build_module_pipeline_snapshot)
FNM_RE/app/pipeline_converters.py      → src/converters.rs
FNM_RE/app/mainline.py                 → src/mainline.rs (run_phase6_pipeline_for_doc)
FNM_RE/app/mainline_repo.py            → src/mainline_repo.rs (DB ↔ Record 互转)
FNM_RE/app/persist_helpers.py          → src/persist_helpers.rs (serialize_*_for_repo)
FNM_RE/app/db_reconstruct.py           → src/db_reconstruct.rs (DB → Structure 重建)
FNM_RE/app/status.py                   → src/status.rs (build_phase4/6_status)
FNM_RE/app/page_translate.py           → src/page_translate.rs (翻译 worker)
FNM_RE/subprocess_*.py                 → 不需要（Rust 无 GIL，子进程内存隔离意义消失）
FNM_RE/__init__.py 公开 API            → pyo3 wrapping
```

**Python ↔ Rust 集成**：
```rust
#[pyfunction]
fn run_doc_pipeline(doc_id: &str, pdf_path: &str) -> PyResult<PipelineResult> { ... }

#[pymodule]
fn fnm_re_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_doc_pipeline, m)?)?;
    Ok(())
}
```

Python 端 `FNM_RE/__init__.py` 切换：
```python
from fnm_re_rs import run_doc_pipeline  # 100% Rust，不再有 Python fallback
```

**工作量**：2 周

---

## 数据流顺序步骤

### Step 1: 章节骨架 — `fnm-phase1`

**输入**：`pages: Vec<Page>`（从 raw_pages.json 或 fnm_pages 表）
**输出**：`Phase1Structure { pages, chapters, section_heads, heading_candidates }`
**DB 表**：写入 `fnm_pages` / `fnm_chapters` / `fnm_section_heads` / `fnm_heading_candidates`

**Python 对应**：
```
FNM_RE/modules/toc_structure.py                       → src/lib.rs (build_toc_structure 入口)
FNM_RE/modules/book_note_type.py                      → src/book_note_profile.rs
FNM_RE/stages/page_partition.py                       → src/page_partition.rs (page_role 判定)
FNM_RE/stages/section_heads.py                        → src/section_heads.rs
FNM_RE/stages/chapter_skeleton/builder.py             → src/skeleton/builder.rs
FNM_RE/stages/chapter_skeleton/fallback.py            → src/skeleton/fallback.rs
FNM_RE/stages/chapter_skeleton/heading_candidates.py  → src/skeleton/heading_candidates.rs
FNM_RE/stages/chapter_skeleton/toc_semantics.py       → src/skeleton/toc_semantics.rs
FNM_RE/stages/chapter_skeleton/_pdf_font_worker.py    → src/skeleton/pdf_font.rs (用 pdfium-render)
FNM_RE/stages/heading_graph.py                        → src/heading_graph.rs
FNM_RE/modules/llm_book_type_verify.py                → src/llm_book_type_verify.rs (用 reqwest)
```

**性能关注点**：
- markdown 解析：`pulldown-cmark` 替代正则
- page_role 判定：大量正则，用 `regex` crate（RE2，比 Python `re` 快 5-20x）
- PDF 字体提取：`pdfium-render` 直接读 PDF 字体信息

**SPEC 测试覆盖**：
- `test_biopolitics_toc_gate_and_exportable_chapters`（12 章）

**工作量**：2 周

---

### Step 2: 注释识别 — `fnm-phase2` + `fnm-sup-recovery`

**输入**：`Phase1Structure`
**输出**：`Phase2Structure { chapters, note_regions, note_items, chapter_note_modes }`
**DB 表**：写入 `fnm_note_regions` / `fnm_note_items` / `fnm_chapter_note_modes` / `fnm_chapter_body_pages`

**这是最大的 Phase**（按 CLAUDE.md，note_kind 在此唯一确定，全书源头）。

**Python 对应**：
```
FNM_RE/modules/chapter_split.py                  → src/lib.rs (build_chapter_layers, ~2000 行)
FNM_RE/modules/endnote_chapter_explorer.py       → src/endnote_chapter_explorer.rs
FNM_RE/modules/endnote_repair.py                 → src/endnote_repair.rs
FNM_RE/modules/visual_anchor_recovery.py         → src/visual_anchor_recovery.rs
FNM_RE/modules/llm_bare_digit_verify.py          → src/llm_bare_digit_verify.rs (reqwest 调 vision LLM)
FNM_RE/stages/note_regions.py                    → src/note_regions.rs
FNM_RE/stages/note_items.py                      → src/note_items.rs
FNM_RE/stages/marker_sequences.py                → src/marker_sequences.rs

—— 子 crate: fnm-sup-recovery ——
FNM_RE/modules/sup_recovery.py                   → src/lib.rs (Layer 1/2/3 OCR 上标修复)
FNM_RE/modules/_sup_recovery_worker.py           → 不需要（Rust 无 GIL，子进程隔离意义消失）
FNM_RE/modules/_pdf_render_worker.py             → src/pdf_render.rs (用 pdfium-render)
FNM_RE/modules/pdf_render_subprocess.py          → 不需要（直接调用）
```

**性能关注点**：
- chapter_split 是热路径：扫大量 markdown 找 note region 边界，正则密集
- Sup recovery Layer 2 的 block 对齐：可 SIMD 加速
- PDF 渲染：`pdfium-render` 比 PyMuPDF 慢一些，但避开子进程通信开销

**SPEC 测试覆盖**：
- `test_ocr_split_marker_can_be_reconstructed`
- `test_chapter_scope_endnote_region_count`（Biopolitics 章后隐式尾注）
- `test_each_lecture_chapter_has_endnote_region`
- `test_chapter_7_fevrier_has_single_endnote_region`
- `test_book_scope_endnotes_are_projected_by_marker_to_chapters`
- 全部 6 个 sup_recovery 测试

**工作量**：4 周（最大头）

---

### Step 3: 锚点 + 链接 — `fnm-phase3` ✅ **100% 完成**

10 个模块全 port，含 1730 行的 `note_linking.py` 拆为 14 子模块。
- 26 lib + 50+ 集成测试通过
- 5 个 byte-equal parity `#[ignore]` 等 Phase 2 cascade 修完（详见 [`fnm_re_rs/fnm-phase3/tests/known_python_bugs.md`](../fnm_re_rs/fnm-phase3/tests/known_python_bugs.md) §7）
- 完整任务历史见 [`FNM_PHASE3_PLAN.md`](FNM_PHASE3_PLAN.md)

**输入**：`Phase2Structure`
**输出**：`Phase3Structure { body_anchors, note_links, paragraph_footnotes, paragraph_endnotes, ... }`
**DB 表**：写入 `fnm_body_anchors` / `fnm_note_links`

**Python 对应**：
```
FNM_RE/modules/note_linking.py                   → src/lib.rs (build_note_link_table 编排, ~1730 行)
FNM_RE/stages/body_anchors.py                    → src/body_anchors.rs (anchor 检测 + gap 启发式)
FNM_RE/stages/note_links.py                      → src/note_links.rs (orphan_anchor 处理)
FNM_RE/stages/endnote_links.py                   → src/endnote_links.rs
FNM_RE/stages/footnote_links.py                  → src/footnote_links.rs
FNM_RE/stages/chapter_anchor_alignment.py        → src/chapter_anchor_alignment.rs (DP 序列对齐)
FNM_RE/stages/paragraph_footnotes.py             → src/paragraph_footnotes.rs
FNM_RE/stages/paragraph_endnotes.py              → src/paragraph_endnotes.rs
FNM_RE/stages/_link_utils.py                     → src/link_utils.rs
FNM_RE/stages/diagnostics.py 一部分              → src/diagnostics.rs (Phase 3 部分)
```

**性能关注点**：
- body anchor 检测：扫每页 markdown 找上标/方括号标记，并行化
- chapter_anchor_alignment：经典 DP（Needleman-Wunsch 风格），章级并行（`rayon`）
- regex 一次编译：`once_cell::Lazy<Regex>`

**SPEC 测试覆盖**：
- 3 个 Phase 3 expected_gap 测试
- `test_biopolitics_contract_v2_def_anchor_mismatch_is_resolved`

**工作量**：3 周

---

### Step 3.5: LLM 修复 — `fnm-llm-repair` ✅ **100% 完成 + 二次审计通过（2026-05-18）**

9 个子模块 1:1 对应 Python 51 函数 + translator 4 helper：
- `usage.rs`（4 helper）+ `cluster.rs`（4 函数）+ `page_context.rs`（10 函数 + RepairImageRenderer trait）
- `prompt_builder.rs`（11 函数）+ `response_parser.rs`（2 函数 + RepairAction/SelectParams 类型）
- `strategies/fuzzy.rs`（locate_anchor_phrase_in_body + partial_ratio 算法重写）
- `override_materializer.rs`（7 函数）
- `llm_client/{mod,request,error}.rs`（HTTP + multi-spec fallback + ProviderError 4 类分类 + 内容审核重试）
- `run.rs::run_llm_repair`（顶层编排 + RunLlmRepairParams + LlmRepairReport）
- `lib.rs`：仅 36 行模块声明 + re-export

**总规模**：15 源文件 · ~6,700 LOC · **164 tests 全过**（121 lib + 4 integration + 39 spec）。
Repository trait 扩展：`clear_fnm_review_overrides_v2` + `batch_save_fnm_review_overrides_v2`。
Translator helper 复现：`_classify_provider_exception` / `_build_usage` / `_extract_openai_message_text` /
`_merge_overrides_into_chat_kwargs` 全部在 Rust 端有对应实现。

**两轮独立审计 → 修复**（功能完整 / AGENTS.md / Rust 习惯三路）：
- 🔴 critical：ProviderError 4 类分类（RateLimited/QuotaExceeded/Transient/NonRetryable）已实现
- 🟡 内容审核 4 关键字补齐 + auto_apply=false 不再误 batch_save + 删 dead code + 补 ←→ 注释
- AGENTS.md 12 条铁律全合规（§4 mod.rs<400 / §5 ←→ 全覆盖 / §10 生产 0 Rc/Mutex / §11 clone 仅拓扑必需）
- `cargo clippy --no-deps`：**0 warning** ✓



**输入**：`Phase3Structure`（含 orphan_note / orphan_anchor 链接）+ PDF
**输出**：`Vec<ReviewOverride>` 写入 `fnm_review_overrides` 表
**后续动作**：~~触发 Step 1-3 重跑消费 override~~ 不保留回环（Python 端的"LLM repair 后重跑 pipeline"语义先不实现，等生产观察是否需要）

**Python 对应**：
```
FNM_RE/modules/llm_repair.py                     → src/lib.rs (run_llm_repair, 2087 行)
                                                   src/prompt_builder.rs (prompt 模板与组装)
                                                   src/llm_client.rs (vision API 调用)
                                                   src/response_parser.rs (JSON 解析 + schema 校验)
                                                   src/override_materializer.rs (override 物化)
                                                   src/repair_strategies.rs (Fuzzy Tier 1/2/3、chapter fallback、footnote coverage)
```

**架构拆分**：
```
run_llm_repair()
  ├─ 1. 收集 orphan candidates（按章分组）
  ├─ 2. 章并行（rayon / tokio）：
  │     ├─ a. 构建 prompt（包含 chapter body + 候选 anchor + PDF 截图）
  │     ├─ b. 调 vision LLM (reqwest async)
  │     ├─ c. 解析 LLM JSON 返回
  │     └─ d. 物化为 review_overrides
  └─ 3. 批量写 fnm_review_overrides 表
```

**性能关注点**：
- LLM 调用本身的网络延迟是大头（不可优化）
- 但 prompt 构建、PDF 截图编码（base64）、JSON 解析、override 物化都是 CPU 密集
- 章并行：用 `tokio::join_all` 同时发起多个 LLM 请求（Python 受 GIL 限制，并发难做）
- 期望吞吐：Python 顺序跑 N 章 vs Rust 并发跑 N 章 → 时间从 N×T 降到 max(T)

**关键依赖**：
- `reqwest` + `tokio`：HTTP/2 长连接、自动重试、流式响应
- `serde_json` 严格 schema 校验
- `base64`：PDF 截图编码
- `pdfium-render`：PDF 截图（可与 Step 2 共享渲染逻辑）

**SPEC 测试覆盖**：当前未失败，但有覆盖测试：
- `test_llm_repair_chapter_fallback.py`
- `test_llm_repair_footnote_coverage.py`
- `test_llm_repair_fuzzy_tier1.py`

**工作量**：3 周

---

### Step 4: 引用注入 + 翻译单元 — `fnm-phase4` ✅ **100% 完成**

**状态**：M1-M5 全完成，21 个文件 / 6,348 LOC / 120 tests 全过。
所有上游依赖（fnm-core / phase1 / phase2 / phase3 + 5 家 provider LLM + DB 1-4 持久化）已 100% 就绪。
完整任务历史见 [`FNM_PHASE4_PLAN.md`](FNM_PHASE4_PLAN.md)。

**输入**：`Phase3Structure`（最终版，已应用 LLM repair override）
**输出**：`Phase4Structure { translation_units, structure_reviews, frozen_refs, frozen_units }`
**DB 表**：写入 `fnm_translation_units` / `fnm_structure_reviews`

**Python 对应**：
```
FNM_RE/modules/ref_freeze.py                     → src/ref_freeze.rs (build_frozen_units)
FNM_RE/stages/units.py                           → src/units.rs (build_translation_units)
FNM_RE/stages/reviews.py                         → src/reviews.rs (build_structure_reviews)
FNM_RE/stages/notes.py                           → 共用 fnm-core
```

**性能关注点**：
- 翻译单元切分：反复扫 markdown 找段落边界
- ref token 注入：避免嵌套 `{{NOTE_REF:...}}`（cleanup_nested_note_refs）
- 注入算法是 O(n×m) 的字符串替换，Rust 用 `aho_corasick` 优化为 O(n)

**SPEC 测试覆盖**：
- `test_load_phase6_for_doc_keeps_synthesized_note_items_from_overrides`
- `test_ch5_note_4_definition_is_full_length`（长注完整保留）
- `test_superscript_note_definition_lines_are_filtered`

**工作量**：2 周

---

### Step 5: 章 markdown 合并 — `fnm-phase5`

**输入**：`Phase4Structure`
**输出**：`Phase5Structure { chapter_markdowns, segment_index }`
**DB 表**：写入 `fnm_chapter_markdowns`

**Python 对应**：
```
FNM_RE/modules/chapter_merge.py                  → src/lib.rs (build_chapter_markdown_set)
```

**性能关注点**：
- 字符串拼接：`String::with_capacity` 预分配；避免反复 alloc
- token 计数：`tokenizers` crate（Rust 原生 HF tokenizer，速度比 Python tiktoken 快 ~20x）

**SPEC 测试覆盖**：
- `test_run_post_translate_export_checks_preserves_existing_translations_when_rebuilding_snapshot`

**工作量**：1 周

---

### Step 6: 导出 + 审计 — `fnm-phase6`

**输入**：`Phase5Structure`
**输出**：`Phase6Structure { export_chapters, export_audit, diagnostic_notes, diagnostic_pages }`
**DB 表**：写入 `fnm_export_chapters` / `fnm_export_audit` / `fnm_diagnostic_*`

**Python 对应**：
```
FNM_RE/modules/book_assemble.py                  → src/book_assemble.rs (build_module_export_bundle)
FNM_RE/stages/export.py                          → src/export.rs
FNM_RE/stages/export_audit.py                    → src/export_audit.rs
FNM_RE/stages/export_contract.py                 → src/export_contract.rs
FNM_RE/stages/export_footnote.py                 → src/export_footnote.rs
FNM_RE/stages/diagnostics.py 剩余部分            → src/diagnostics.rs (Phase 6 部分)
```

**性能关注点**：
- 主要是 IO 和 JSON 序列化，性能不是瓶颈
- `serde_json` 与 Python 输出位级兼容（用相同 key 顺序）

**工作量**：1 周

---

## 实施时间表（按数据流顺序）

### 已完成（截至 2026-05-18）

| 步骤 | 状态 | 实际完成日 |
|---|---|---|
| 横切 A — `fnm-core` | ✅ 100% + 5 家 LLM provider 基建 | 2026-05-18 |
| Step 1 — `fnm-phase1` | ✅ 100%（12 模块）| 2026-05-18 |
| Step 2 — `fnm-phase2` | ✅ 100%（15 模块）| 2026-05-18 |
| Step 3 — `fnm-phase3` | ✅ 100%（10 模块）| 2026-05-17 |

### 剩余规划

| 周次 | 步骤 | 内容 | 累计 |
|---:|---|---|---:|
| 1-2 | Step 4 | `fnm-phase4`：frozen refs + translation units + reviews | 2 周 |
| 3 | Step 3.5 | `fnm-llm-repair`：vision API + override 物化（基建已就绪）| 3 周 |
| 4 | Step 5 | `fnm-phase5`：chapter markdown merge | 4 周 |
| 5 | Step 6 | `fnm-phase6`：export + audit + diagnostics | 5 周 |
| 6-7 | 横切 B | `fnm-orchestrator`：pipeline + pyo3 入口 | 7 周 |
| 8-9 | 验证 | 全 pipeline 端到端对齐、性能调优、生产切换 | 9 周 |

**剩余**：~ 9 周（约 2 个月，单人 full-time）。已完成 ~ 14 周工作量。

---

## 验证策略：影子模式 + 渐进切换

### 阶段 A: 影子模式（每个 Step 完成后立即启用）
Rust 与 Python 并行跑同一份输入，比对 JSON 输出。所有 diff 都告警。

```bash
FNM_SHADOW_RUST_PHASES=1,2 python -m FNM_RE ...  # Rust 跑 Phase 1+2 同步运行 Python，比对结果
```

### 阶段 B: 单 Step 切换
```bash
FNM_USE_RUST_PHASES=1,2  # Phase 1+2 用 Rust，3+ 用 Python
```
逐 Step 验证生产正确性。

### 阶段 C: 全量切换
所有 Step 通过后，`FNM_USE_RUST_PHASES=all`。Python 代码保留 3 个月作 fallback。

### 阶段 D: 移除 Python
Rust 稳定运行 3 个月后，删除 Python 实现，保留 `tests/unit/` 中标 `rust-migration: SPEC` 的测试翻译到 Rust 端。

---

## 技术选型

| 用途 | Crate |
|---|---|
| Async runtime | `tokio` |
| Regex | `regex`（RE2） |
| 字符串多模式匹配 | `aho-corasick` |
| Markdown | `pulldown-cmark` |
| JSON | `serde` + `serde_json` |
| SQLite | `rusqlite` + `r2d2_sqlite` |
| PDF | `pdfium-render` |
| HTTP（LLM 调用） | `reqwest`（HTTP/2 + tokio） |
| Tokenizer | `tokenizers`（HF Rust 实现） |
| Base64 | `base64` |
| Python FFI | `pyo3` + `maturin` |
| 错误处理 | `thiserror` + `anyhow` |
| 日志 | `tracing` |
| 并行 | `rayon` |
| Lazy 全局变量 | `once_cell` |
| 单元测试 | `cargo test` + `insta`（snapshot） |

---

## SPEC 测试清单（来自 `[rust-migration: SPEC]` 标签）

Rust 重写时必须翻译为 Rust 测试。grep 命令：

```bash
grep -rn "rust-migration: SPEC" tests/unit/ --include="*.py"
```

完整清单已在 `tests/unit/test_*.py` 中以 `@unittest.skip("[rust-migration: ...]")` 标注。按数据流位置分布：

| 步骤 | 测试数 | 测试 |
|---|---:|---|
| Step 1 | 1 | test_biopolitics_toc_gate_and_exportable_chapters |
| Step 2 | 10 | test_chapter_scope_endnote_region_count, test_each_lecture_chapter_has_endnote_region, test_chapter_7_fevrier_has_single_endnote_region, test_book_scope_endnotes_are_projected_by_marker_to_chapters, test_ocr_split_marker_can_be_reconstructed, 6× sup_recovery（1 UNCLEAR）|
| Step 3 | 4 | test_expected_gap_recovery_can_disambiguate_symbol_ocr_by_note_text, test_expected_gap_recovery_keeps_weak_endnote_digits_under_positive_gate, test_superscript_note_definition_lines_are_filtered, test_biopolitics_contract_v2_def_anchor_mismatch_is_resolved |
| Step 3.5 | 0 (新失败) | 但有 3 个 llm_repair 测试已通过，Rust 端要保持 |
| Step 4 | 1 | test_load_phase6_for_doc_keeps_synthesized_note_items_from_overrides |
| Step 5 | 1 | test_run_post_translate_export_checks_preserves_existing_translations_when_rebuilding_snapshot |
| Step 6 | 1 | test_ch5_note_4_definition_is_full_length（长注完整性）|

---

## DB schema（Phase 间接口契约）

所有 Phase 间通过 SQLite 表交换数据。已存在表：

| 表 | 谁写 | 谁读 |
|---|---|---|
| `fnm_pages` | Step 1 | Step 2-6 |
| `fnm_chapters` | Step 1 | Step 2-6 |
| `fnm_section_heads` | Step 1 | Step 2-6 |
| `fnm_heading_candidates` | Step 1 | Step 2 |
| `fnm_note_regions` | Step 2 | Step 3-6 |
| `fnm_note_items` | Step 2 | Step 3-6 |
| `fnm_chapter_note_modes` | Step 2 | Step 3-6 |
| `fnm_chapter_body_pages` | Step 2 | Step 3-6 |
| `fnm_body_anchors` | Step 3 | Step 4-6 |
| `fnm_note_links` | Step 3 | Step 4-6 |
| `fnm_review_overrides` | Step 3.5 / 手工 | Step 1-3（下次 run 时消费）|
| `fnm_translation_units` | Step 4 | Step 5-6 |
| `fnm_structure_reviews` | Step 4 | Step 6 |
| `fnm_chapter_markdowns` | Step 5 | Step 6 |
| `fnm_export_chapters` | Step 6 | 外部消费 |
| `fnm_export_audit` | Step 6 | 外部消费 |
| `fnm_diagnostic_pages` | Step 6 | 外部消费 |
| `fnm_diagnostic_notes` | Step 6 | 外部消费 |

Rust 按 schema 读写即可，**不新增表、不改 schema**。

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| Python 业务逻辑隐性约束多，Rust 写漏 | 严格 snapshot 对比 + SPEC 测试翻译 |
| LLM API 调用契约复杂（vision、多模型） | LLM client 抽象为 trait，可注入 mock；保留 Python LLM repair 作金标准 |
| chapter_split.py 太大（~2000 行） | 分解为多个小模块（note_regions / note_items / chapter_layers）逐步移植 |
| llm_repair.py 太大（~2087 行）| 拆为 prompt_builder / llm_client / response_parser / override_materializer / repair_strategies |
| Python 端的隐式类型转换在 Rust 里要显式 | 借机统一类型契约 |
| 部署变复杂（要编译 Rust） | `maturin` 打 wheel，pip 安装无感；CI 提供预编译 wheel |
| pdfium-render 在 macOS/Linux 二进制依赖 | bundled 模式打包 |

---

## 下一步

1. **第 1-2 周**：搭建 Cargo workspace + pyo3 hello-world + CI（cargo test + maturin build）
2. **第 3 周**：实现 `fnm-core`，跑通"读 fnm_pages 表，转 JSON，与 Python `_phase_pages_from_layers` 输出 diff = 0"
3. **第 4 周**：进入 Step 1，先做最小可验证版本（不含 LLM book type verify）
