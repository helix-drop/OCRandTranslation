# fnm-phase1 / fnm-phase2 代码审计报告

**审计时间**：完成 P1/P2 实施后第一轮  
**审计结论**：⚠️ **实际完成度远低于声称**，不可进入 Phase 3，需补完 F1-F12

---

## 1. 表面状态 vs 实际状态

| 维度 | 声称 | 实际 |
|---|---|---|
| 测试通过 | ✅ 133 测试 | ⚠️ 全部是浅层 unit test，0 个 parity / 0 个 SPEC 覆盖 |
| clippy clean | ✅ | ✅ |
| fmt clean | ✅ | ✅ |
| Phase 1 完成 | "已完成" | ❌ **~18% 完成**（2,215 行 / 计划 12,000 行） |
| Phase 2 完成 | "已完成" | ❌ **~13% 完成**（1,239 行 / 计划 9,500 行） |
| LLM 集成 | "已实施" | ❌ 全部 deferred，PDF render 返回空串 |
| SPEC 测试翻译 | 计划 19 个（P1=8, P2=11）| ❌ **0 个翻译** |
| Biopolitics 端到端 | 计划必备 | ❌ 没有 fixture，没有集成测试 |
| Parity fixture 比对 | 计划必备 | ❌ 全无 |

**核心教训**：`cargo test` 通过 + clippy clean **不等于** 业务功能完成。Phase 1/2 的"完成"实际是骨架 + 部分核心逻辑，关键算法大量是 stub。

---

## 2. 模块完成度细表

### Phase 1（2,215 行 / 计划 12,000 行 → 18%）

| 模块 | Python 行 | Rust 行 | 完成度 | 状态 |
|---|---:|---:|---:|---|
| `page_partition/role_heuristics` + `role_resolver` + `mod` | 1267 | 851 | 67% | 部分（缺关键启发式）|
| `section_heads` | 203 | 232 | 100%+ | ✅ |
| `heading_graph/mod` | 703 | 85 | **12%** | 🔴 stub（只透传 family/depth）|
| `chapter_skeleton/builder` | 449 | 77 | **17%** | 🔴 stub |
| `chapter_skeleton/heading_candidates` | 827 | 46 | **6%** | 🔴 严重 stub |
| `chapter_skeleton/fallback` | 656 | 102 | **16%** | 🔴 stub |
| `chapter_skeleton/toc_semantics`（全部子模块）| 2014 | 388 | **19%** | 🔴 stub |
| `book_note_type/mod` | 403 | 51 | **13%** | 🔴 stub |
| `llm_book_type_verify/mod` | 1039 | 64 | **6%** | 🔴 完全 deferred |
| `chapter_skeleton/pdf_font` | 32 | 41 | 占位 | 🔴 返回空串 |
| `toc_structure` | 544 | 119 | 22% | 🔴 简单编排 |

### Phase 2（1,239 行 / 计划 9,500 行 → 13%）

| 模块 | Python 行 | Rust 行 | 完成度 | 状态 |
|---|---:|---:|---:|---|
| `note_kind_resolver` | (新增) | 170 | ✅ | ✅ 完整 + 5 测试 |
| `chapter_split/mod` + `overrides_apply` | 1089 | 163 | **15%** | 🔴 stub |
| `sup_recovery/mod` + `layer1` + `layer2` + `layer3` + `pdf_render` | 915 | 241 | 26% | 🔴 stub |
| `visual_anchor_recovery/mod` | 1017 | **6** | **0.6%** | 🔴 **完全空函数**返回 `json!({})` |
| `llm_bare_digit_verify/mod` | 221 | **6** | **3%** | 🔴 **完全空函数** |
| `endnote_chapter_explorer/mod` | 722 | 147 | 20% | 🔴 stub |
| `endnote_repair/mod` | 325 | 112 | 34% | 部分 |
| `note_regions/mod` | 825 | 92 | **11%** | 🔴 严重 stub（见 §3.1）|
| `note_items/mod` | 658 | 106 | **16%** | 🔴 stub（见 §3.2）|

---

## 3. 严重问题深入分析

### 3.1 `note_regions::build_note_regions` 几乎是占位

`fnm-phase2/src/note_regions/mod.rs` 整个模块只做一件事：

```rust
// 筛选 page_kind == "endnote_collection" 的页 → 按章节分组 → 连续页合并 → region
let note_page_nos: HashSet<i64> = pages
    .iter()
    .filter(|p| p.note_scan...page_kind == "endnote_collection")
    .map(|p| p.book_page)
    .collect();
```

**完全没有**：
- ❌ 显式 "## NOTES" / "## Endnotes" 标题扫描（Python `_NOTES_HEADING_RE`）
- ❌ footnote_band 检测（页脚连续短行的脚注带）
- ❌ continuation_merge 跨页续行合并
- ❌ post_body_endnote 章后隐式尾注识别
- ❌ manual_rebind 手工 review override
- ❌ region_start / region_end 边界规则
- ❌ Biopolitics 章后隐式尾注（依赖此模块）

**结论**：当前实现完全无法通过任何 Phase 2 SPEC 测试。

### 3.2 `note_items::build_note_items` 缺失大部分解析逻辑

只有一条简单正则：
```rust
static NOTE_DEF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(?:\[(\d{1,4})\]|(\d{1,4})[\.;:,\)\]])\s*(.+)$").unwrap());
```

**完全没有**：
- ❌ OCR split marker 重建（SPEC: `test_ocr_split_marker_can_be_reconstructed`）—— Python `_OCR_SPLIT_NOTE_DEF_RE`
- ❌ inline break 重建（Python `_EMBEDDED_NOTE_DEF_RE` / `_INLINE_NOTE_BREAK_RE`）
- ❌ 引文缩写处理 `vol.` / `n°` / `art.` / `cf.` 等（SPEC: `test_ch5_note_4_definition_is_full_length`）
- ❌ 符号型 marker `*` / `**` / `†` / `‡` / `§` / `¶`
- ❌ 字母型 marker `a` / `b` / `c`
- ❌ Unicode 上标 marker
- ❌ HTML/LaTeX 上标 marker
- ❌ marker-only 单独行（marker 与 body 跨行）
- ❌ noisy 噪声字符处理
- ❌ 跨页 note continuation
- ❌ `is_reconstructed` flag 设置

**结论**：当前实现对真实 OCR 输出几乎全部 miss。

### 3.3 `visual_anchor_recovery` + `llm_bare_digit_verify` 是 6 行空函数

```rust
// visual_anchor_recovery/mod.rs（6 行）
pub fn build_visual_recovery_overrides() -> serde_json::Value {
    serde_json::json!({})
}

// llm_bare_digit_verify/mod.rs（6 行）
pub fn verify_bare_digit_candidates() -> serde_json::Value {
    serde_json::json!({})
}
```

**Python 共 1238 行业务逻辑全部缺失**。这两个模块对生产质量至关重要（vision LLM 修复 anchor 缺口、验证 bare digit 假阳性）。

### 3.4 关键参数被 `let _ = ...` 忽略（8 处）

| 文件:行 | 忽略的参数 | 影响 |
|---|---|---|
| `toc_structure.rs:38` | `config` | 整个 Phase1Config 被忽略！skip_llm_verify、manual_overrides 等都无效 |
| `page_partition/mod.rs:21` | `(page_overrides, endnotes_start_page)` | manual override 无效、endnotes 边界无效 |
| `page_partition/mod.rs:80` | `synthetic_page_by_no` | 合成页处理 miss |
| `chapter_skeleton/fallback.rs:61` | `total_pages` | fallback 边界 miss |
| `chapter_skeleton/pdf_font.rs:25` | `(pdf_path, page_indices)` | PDF 字体提取**完全没实现** |
| `chapter_skeleton/toc_semantics/mod.rs:167` | `(chapters, page_partitions)` | TOC 语义对齐忽略上游 chapter / page_role |
| `book_note_type/mod.rs:20` | `(pages, overrides)` | 书型判定无法用 page 证据 / overrides |
| `llm_book_type_verify/mod.rs:41` | `(toc_structure, book_note_profile, pdf_path, api_config)` | LLM 验证**完全没实现** |

**每一个 `let _ = ...` 都是一个静默的功能缺失**。

### 3.5 持久化 bug：Phase 2 清空 Phase 1 表

`fnm-phase2/src/lib.rs:60` 的 `persist_phase2`：

```rust
repo.replace_fnm_phase1_products(
    doc_id,
    &fnm_core::db::Phase1Products {
        pages: vec![],              // ← 空！
        chapters: output.chapters,
        heading_candidates: vec![],  // ← 空！
        section_heads: vec![],      // ← 空！
    },
)?;
```

调用 `replace_fnm_phase1_products` 会 DELETE 所有旧数据再插入，传 `vec![]` 等于**清空** Phase 1 写过的 pages / heading_candidates / section_heads。后续 Phase 3+ 读不到任何 Phase 1 产物。

**正确做法**：Phase 2 不应该写 Phase 1 的表。Phase 1 的 chapters 应该已经在 Phase 1 持久化时写好，Phase 2 不要重复写。

### 3.6 没有 parity fixture，没有 SPEC 测试

| 检查项 | 状态 |
|---|---|
| `tests/fixtures/biopolitics_pages.json` | ❌ 不存在 |
| `tests/fixtures/biopolitics_phase1_expected.json` | ❌ 不存在 |
| `tools/gen_phase1_fixtures.py` | ❌ 没生成真实 fixture |
| `tools/gen_phase2_fixtures.py` | ❌ 没生成真实 fixture |
| 19 个 SPEC 测试翻译（11 P2 + 8 P1）| ❌ 0 个 |
| `test_phase2_pipeline.rs` 内容 | 17 个 hand-crafted unit test，0 个 Biopolitics |

**结论**：133 测试通过没有意义——它们只验证了"代码能跑"，没验证"输出对"。

---

## 4. 必须补完任务（F1-F12，~34.5 天，**阻塞 Phase 3**）

| # | 任务 | 工时 | 关键产出 |
|--:|---|---:|---|
| **F1** | **Biopolitics 真实 fixture 生成** | 1 天 | `tests/fixtures/biopolitics_phase1_output.json`、`biopolitics_phase2_expected.json`，由 Python 跑出 |
| **F2** | `note_regions` 完整补完 | 5 天 | 显式 heading 扫描、footnote_band 检测、continuation_merge、post_body_endnote、manual_rebind |
| **F3** | `note_items` 完整补完 | 4 天 | OCR split 重建、引文缩写、符号 marker、字母 marker、跨页续行、`is_reconstructed` flag |
| **F4** | `chapter_skeleton/heading_candidates` 完整补完 | 4 天 | 字体检测、family 聚类、reject 启发式、top_band 判定 |
| **F5** | `toc_semantics` 完整补完 | 4 天 | fuzzy 对齐、单调性恢复、容器章节展开、role hint 复杂推断 |
| **F6** | `heading_graph` 补完 | 3 天 | family/depth 推断算法、关系图构建、冲突解决 |
| **F7** | `page_partition` 关键参数补完 | 2 天 | page_overrides 应用、endnotes_start_page 边界、synthetic_page 处理 |
| **F8** | `chapter_split` 补完 | 3 天 | path_selector（heading_scan / footnote_band / explorer 路径选择）+ overrides_apply 真实实现 |
| **F9** | `book_note_type` 补完 | 3 天 | footnote band 检测、endnote region 识别、book_type 推断（footnote_only / endnote_only / mixed / no_notes）|
| **F10** | Phase2 持久化 bug 修复 | 0.5 天 | 不清空 Phase 1 表；正确的 phase2-only INSERT 路径 |
| **F11** | **19 个 SPEC 测试翻译** | 3 天 | P1: 8 个；P2: 11 个 |
| **F12** | Biopolitics 端到端 parity 比对 | 2 天 | `cargo test biopolitics_phase12_parity` byte-equal 通过 |
| **小计** | | **~34.5 天** | |

---

## 5. 可延后任务（G1-G5，~12 天，Phase 3 之前必做）

| # | 任务 | 工时 | 说明 |
|--:|---|---:|---|
| G1 | `sup_recovery/pdf_render` 真实 pdfium-render | 1 天 | 渲染 PDF 单页为 PNG base64 |
| G2 | `sup_recovery/layer3` Vision LLM | 2 天 | reqwest + Vision API 调用，配合 G1 |
| G3 | `visual_anchor_recovery` 完整实现 | 4 天 | Python 1017 行业务逻辑 |
| G4 | `llm_bare_digit_verify` 完整实现 | 2 天 | Python 221 行业务逻辑 |
| G5 | `llm_book_type_verify` Phase 1c 完整实现 | 3 天 | Python 1039 行 |
| **小计** | | **~12 天** | |

---

## 6. 给实施者的明确指南

### 工程纪律违反

| 违反点 | 计划要求 | 实际 |
|---|---|---|
| Parity 测试是验收门 | "Rust 输出必须 byte-equal 匹配 Python" | 全部 hand-crafted Rust 单元测试 |
| 每个任务一个 PR | 17 个独立 PR | 实际 PR 粒度未知，但内容缺失 |
| SPEC 测试翻译 | "Phase2 必须翻译 11 个 SPEC" | 0 个 |
| 不引入新 Python 端没有的功能 | "严格只翻译" | 大量简化（如 note_items 只一条正则）|
| 8 个 `let _ = ...` | 不应存在 | 关键参数被静默忽略 |

### 必须改变的工作方式

1. **先写 fixture，再写实现**
   - 每个模块开工前先用 Python 跑真实数据生成 expected output JSON
   - Rust 实现的目标是**让 parity 测试通过**，不是"看起来差不多"

2. **每个 `let _ = ...` 都是一个 review 阻断点**
   - PR 描述里如果有 `let _ = ...`，必须解释为什么这个参数现阶段可以忽略
   - 否则 CR 直接拒绝

3. **stub 函数必须显式标注**
   ```rust
   #[allow(unused)]
   fn not_yet_implemented(_args: ()) -> Result<()> {
       anyhow::bail!("not yet implemented: see F<N> in FNM_PHASE12_AUDIT.md")
   }
   ```
   而不是默默返回 `json!({})` / `Ok(vec![])`。让上游编译时就知道还没好。

4. **持久化路径必须做 round-trip 测试**
   - F10 的 bug 是因为缺这类测试。写完 `persist_phase2` 后必须验证：写入 → 读出 → 字段不丢

5. **集成测试用 Biopolitics 真书**
   - Hand-crafted 测试只能验证"代码不 panic"
   - 真书 fixture 才能验证"业务规则对"

---

## 7. 验收 checklist（F1-F12 完成后）

### 代码层
- [ ] 0 处 `let _ = ...` 忽略关键参数（unused warning 抑制必须有注释解释）
- [ ] 0 个返回 `json!({})` / `Ok(vec![])` 的占位函数
- [ ] 所有 stub 函数用 `anyhow::bail!("not yet implemented")` 显式标注
- [ ] `persist_phase2` 不清空 Phase 1 表（round-trip 测试通过）

### Parity 层
- [ ] `tests/fixtures/biopolitics_*.json` 存在（来自 Python 真实输出）
- [ ] `tests/fixtures/germany_madness_*.json` 存在
- [ ] `cargo test biopolitics_phase1_parity` 通过（与 Python output byte-equal）
- [ ] `cargo test biopolitics_phase2_parity` 通过

### SPEC 层（19/19）
**Phase 1（8 个）**：
- [ ] `test_biopolitics_toc_gate_and_exportable_chapters`
- [ ] `test_external_page_roles_do_not_expose_noise`
- [ ] `test_disordered_raw_toc_can_be_normalized_to_monotonic`
- [ ] `test_section_role_hint_does_not_break_chapter_order_gate`
- [ ] `test_mid_book_other_page_does_not_force_back_matter_start`
- [ ] `test_manual_override_is_recorded`
- [ ] `test_toc_tree_preserves_endnotes_role_and_semantic_levels`
- [ ] `test_visual_toc_export_candidate_default`（2 个 sub-test）

**Phase 2（11 个）**：
- [ ] `test_ocr_split_marker_can_be_reconstructed`
- [ ] `test_chapter_scope_endnote_region_count`
- [ ] `test_each_lecture_chapter_has_endnote_region`
- [ ] `test_chapter_7_fevrier_has_single_endnote_region`
- [ ] `test_book_scope_endnotes_are_projected_by_marker_to_chapters`
- [ ] `test_ch5_note_4_definition_is_full_length`
- [ ] `test_layer2_recovers_marker_from_symbol_after_year_fragment`
- [ ] `test_layer2_recovers_repeated_one_marker_from_ocr_punctuation_surrogate`
- [ ] `test_layer2_recovers_two_digit_marker_from_ocr_suffix`
- [ ] `test_layer3_rejects_marker_different_from_requested`
- [ ] `test_layer3_rejects_repeated_context_location`

### 模块完成度
- [ ] `note_regions` ≥ 700 行，覆盖 5 类 region source
- [ ] `note_items` ≥ 500 行，覆盖 SPEC + 引文缩写
- [ ] `chapter_skeleton/heading_candidates` ≥ 600 行，含字体检测
- [ ] `toc_semantics/*` 全部子模块 ≥ 1500 行
- [ ] `heading_graph` ≥ 500 行
- [ ] `book_note_type` ≥ 300 行
- [ ] `chapter_split` ≥ 800 行
- [ ] G1-G5 涉及模块 ≥ 1500 行（PDF render + 3 个 LLM 模块）

### 性能基线（不阻塞，但 Phase 3 之前要测）
- [ ] Biopolitics phase1：Rust < 2s（Python ~30s 量级，目标 ≥ 15x）
- [ ] Biopolitics phase2（不含 LLM）：Rust < 5s（Python ~120s 量级，目标 ≥ 24x）

---

## 8. 时间表修正

| 阶段 | 原计划 | 实际 | 修正后 |
|---|---:|---:|---:|
| Phase 1 实施 | 26 天 | "完成"但 18% | +20 天补完（F4-F7、F11 部分）|
| Phase 2 实施 | 28.5 天 | "完成"但 13% | +28.5 天补完（F1-F3、F8-F12 + G1-G5）|
| **Phase 1/2 实际累计** | **54.5 天** | **未知** | **~83 天** |
| Phase 3 启动 | 第 55 天 | - | **第 84 天** |
| 整体 Phase 1-6 + LLM repair | 23 周 | - | **~28 周** |

延期约 **5 周**。

---

## 9. 决策点

实施者需要选择：

### 选项 A：补完 F1-F12 + G1-G5（**推荐**）
- 耗时 ~47 天
- 完成后 Phase 1/2 真正达到 SPEC 标准
- 可放心进入 Phase 3
- 风险低

### 选项 B：跳过 G1-G5，先做 F1-F12
- 耗时 ~34.5 天
- LLM 相关模块继续 stub
- Phase 3 可以启动，但 Phase 3.5 (LLM repair) 之前必须回头补 G1-G5
- 风险中

### 选项 C：放弃 parity 严格性，进入 Phase 3
- ❌ **不推荐**
- 浅层 stub 会传染到 Phase 3-6
- 最终 Biopolitics 跑不通时，回溯成本极高
- Rust 整体迁移失败的高风险路径

---

## 10. 给项目负责人的建议

1. **明确告知实施者**：审计已发现实际完成度 ~15%，需要按 F1-F12 + G1-G5 补完
2. **修改验收标准**：从"`cargo test` 通过"改为"19 个 SPEC 测试 + Biopolitics parity byte-equal 通过"
3. **每个 PR 必须 review 通过新标准**：
   - 0 `let _ = ...` 忽略关键参数
   - 涉及业务逻辑的模块必须有 Python parity fixture 比对
   - 涉及 SPEC 测试的模块必须有对应 Rust 集成测试
4. **不要进入 Phase 3** 直到 F1-F12 全部通过

完成后再做一次 Phase 1/2 完整审计，确认达标后启动 Phase 3。
