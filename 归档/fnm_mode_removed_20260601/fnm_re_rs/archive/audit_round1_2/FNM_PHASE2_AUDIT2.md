# FNM-PHASE2 审计报告（独立第二轮）

> 审计范围：`fnm-phase2` crate 全部 49 个 `.rs` 文件（约 9,457 行）。
> 维度：程序逻辑、Rust 风格、过度防御/偷懒/AI 常见病。业务规则（书型/阈值）不评判。
> 方法：逐文件精读核心 + 反模式 grep 全覆盖 + 调用关系核实。审计期间未参考现有 `audit/`。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

---

## 0. 总体印象

phase2 是 **note_kind 全书唯一来源**（CLAUDE.md §8/§12）。核心做得不错：
- `note_kind_resolver::resolve_note_kind` 是单一权威函数，被 `note_regions` 子模块统一调用（已核实 endnote_regions_raw / footnote_band 两个构建点都走它）；
- `chapter_split` 的 note_mode 升级用 **4 分支显式 reason**（§12 合规），并写入 `policy_applied` 审计；
- `note_capture_summary` 的 `captured_pages = footnote ∪ endnote`（修了 §11 提到的「只收 footnote」假阳性）；
- `year_filter` 按 `(chapter, region, kind)` 分组、不跨边界推断；
- marker 解析（marker_parse / sequence_repair / endnote_repair）覆盖 OCR split、年份、离群、跨页续行等，测试充分。

但 phase2 暴露两类突出问题：**(A) 大量 pub 代码未接入主流程（~2000+ 行）**；**(B) 一个因传错参数而静默失效的 fallback**。

---

## 1. 🔴 高 / 🟠 中-高优先级

### P2-1　`split_book_region_by_chapter_boundaries` 的 heading 切分恒失效（传错参数）
- **位置**：[endnote_chapter_explorer/signal_select.rs](fnm-phase2/src/endnote_chapter_explorer/signal_select.rs) `split_book_region_by_chapter_boundaries` 中 `extract_page_headings(&page.pruned_result)`
- **类别**：程序逻辑 bug（静默失效）
- **分析**：`fnm_core::text::extract_page_headings(page)` 内部 `page_blocks(page)` 取 `page.get("prunedResult").get("parsing_res_list")`，要求传入的是**完整 page dict**。这里传的是 `page.pruned_result`（已经是 prunedResult 的值本身），于是内部再找 `pruned_result["prunedResult"]` = None → 返回空 headings → `page_chapter` 恒空 → 函数恒走 `return vec![(region.chapter_id, sorted_pages)]`（不切分）。
- **同源坑**：phase1 [page_partition/mod.rs:72-75](fnm-phase1/src/page_partition/mod.rs) 已有注释明确警告「不能走 extract_page_headings(&page.pruned_result)，会再套一层 prunedResult 永不命中」——此处重蹈覆辙且无注释。
- **后果**：book-scope endnote region 的「按章节标题切分」fallback 永远退化为「整段归一章」，下游 chapter 归属可能错。
- **修复**：传完整 page 结构，或改调 `extract_headings_from_pruned_result` 式直接吃 `parsing_res_list` 的入口。
- **关联**：[note_items/page_text.rs:199](fnm-phase2/src/note_items/page_text.rs) `normalized_page_text` 同样 `page_markdown_text(&p.pruned_result)`（首选分支恒空），但有 `p.markdown` 兜底，实际影响小——仍建议修正首选分支。

### P2-2　`sup_recovery` 在循环内反复创建 tokio Runtime
- **位置**：[sup_recovery/mod.rs:107](fnm-phase2/src/sup_recovery/mod.rs)
  ```rust
  for (chapter_id, candidates) in &layer3_candidates {
      let rt = tokio::runtime::Runtime::new();   // 每章一个 Runtime
      if let Ok(runtime) = rt { ... runtime.block_on(...) }
  }
  ```
- **类别**：性能 / 资源
- **分析**：`Runtime::new()` 是重量级（线程池）。N 个有 Layer3 候选的章 = 创建 N 个运行时。已核实这是 phase2 **唯一**在生产代码循环内建 Runtime 的点（其余 5 处均在测试）。
- **修复**：循环外建一个 Runtime（或整函数 async），一次 `block_on` 聚合所有 chapter 的 future。

### P2-3　Layer 2 用 `markdown.contains(&marker)` 子串匹配定位页
- **位置**：[sup_recovery/mod.rs:60-68](fnm-phase2/src/sup_recovery/mod.rs)
- Layer2 找到 recovery 后，遍历 `pages` 用 `page.markdown.contains(&rec.marker)` 找归属页。marker="1" 会匹配 "10"/"21"/"page 1" 等任意含 "1" 的页，可能 attach 到错误页。建议用与 Layer2 一致的带边界正则定位。

---

## 2. 🟠 中：大量未接入主流程的 pub 代码

`build_phase2_structure_sync`（lib.rs）只串了 `build_note_regions → explore_full → build_note_items → sup_recovery → endnote_repair → build_chapter_layers → infer_book_type`。以下 pub 代码**经 grep 核实无主流程调用**（仅测试/0 引用），靠 `pub` 豁免 clippy dead_code：

| 模块/函数 | 规模 | 非测试引用 |
|---|---|---|
| `visual_anchor_recovery/*`（整个子系统）| ~1360 行 | lib 仅设 `visual_anchor_recovery_ready` 标志 |
| `llm_bare_digit_verify/*`（整个子系统）| ~355 行 | lib 仅设 `llm_bare_digit_verify_ready` 标志 |
| `chapter_split::endnote_project::{compute_endnote_projections, compute_fallback_assignments}` | 142 行 | **0** |
| `chapter_split::overrides_apply::apply_note_item_overrides` | 84 行 | **0** |
| `chapter_split::synth_markers::compute_synthetic_markers` | 30 行 | **0** |
| `chapter_split::structure_model::{note_capture_summary, chapter_binding_summary, build_book_structure_model}` | 366 行 | 各 1（需确认是否在主流程） |
| `endnote_chapter_explorer::explore_endnote_chapter_regions`（旧 API）| — | 注释自标「建议改用 _full」 |

**评价**：与 phase1 的 book_note_type / llm_book_type_verify 同样是「完整 port Python 但只接一部分」。建议路线图明确各模块状态（待接入 / 废弃），避免被当活代码维护，并允许 `endnote_project`/`overrides_apply`/`synth_markers` 这类 0 引用文件直接删除或私有化暴露真实 dead_code。

---

## 3. 🟡 死代码 / 死字段 / 未用参数

- **死字段**：
  - [note_kind_resolver.rs:25](fnm-phase2/src/note_kind_resolver.rs) `NoteRegionContext.explicit_markers` —— `resolve_note_kind` 从不读取（所有调用传 `&[]`）。
  - [endnote_chapter_explorer/matching.rs:16,53,56](fnm-phase2/src/endnote_chapter_explorer/matching.rs) `#[allow(dead_code)]` 三个写而不读的字段（`ChapterRow.order_index`、`PageChapterSignal.page_no`、`PageChapterSignal.chapter_title`）。
  - [chapter_split/structure_model.rs:27](fnm-phase2/src/chapter_split/structure_model.rs) `OCRProfile.placeholder` 占位死字段（「与 Python 默认对齐」）。
- **未用参数**：[chapter_split/gate.rs](fnm-phase2/src/chapter_split/gate.rs) `_chapter_note_modes`；[note_regions/book_regions.rs](fnm-phase2/src/note_regions/book_regions.rs) `_heading_candidates`。
- **抑制告警 hack**：[visual_anchor_recovery/materialize.rs:179](fnm-phase2/src/visual_anchor_recovery/materialize.rs) `let _ = cs;`（消除 unused，未实际使用计算结果）。

---

## 4. 🟡 重复 / AI 代码味 / 风格

### AI 推导草稿留在代码里（典型）
- [note_items/sequence_repair.rs:230-272](fnm-phase2/src/note_items/sequence_repair.rs) `fix_backward_run` 测试内留有 **~40 行 AI 思考流水账注释**（`// Let me think of a valid case... // Wait, maybe... // I think the formula is wrong in my reading... // Hmm, when would this trigger?`）。这是调试推导草稿被当注释提交，应删除只留最终用例 + 一句说明。

### 重复
- `PAGE_CITATION_PREFIX_RE` 在 [endnote_repair/mod.rs:8](fnm-phase2/src/endnote_repair/mod.rs) 与 [note_items/mod.rs:29](fnm-phase2/src/note_items/mod.rs) 各一份（`\b` vs `$` 细微差异）。
- `compute_body_bounds` 式「按 end_page 排序 + windows gap>30 + cut_idx」在 [endnote_regions_raw.rs:130](fnm-phase2/src/note_regions/endnote_regions_raw.rs) 与 [post_body_promote.rs:28](fnm-phase2/src/note_regions/post_body_promote.rs) 重复。
- `serde_json::to_value(RawPage)` 在 [chapter_split/mod.rs:216](fnm-phase2/src/chapter_split/mod.rs) 把强类型转 Value 再调 `page_markdown_text`（phase1 同款浪费）。

### 风格 / 观察
- **装饰性 resolve_note_kind 调用**：[endnote_regions_raw.rs:99](fnm-phase2/src/note_regions/endnote_regions_raw.rs)（硬编码 `scan_page_kind="endnote_collection"`）、[footnote_band.rs:145](fnm-phase2/src/note_regions/footnote_band.rs)（硬编码 `has_footnote_band=true`）使 resolve 结果恒定。**倾向接受**——为「note_kind 唯一来源」走统一函数，即使结果可预测；但可加注释说明，或直接断言。
- **冗余计算**：[chapter_split/mod.rs:354](fnm-phase2/src/chapter_split/mod.rs) `build_chapter_layers_from_authoritative_phase2` 先完整 `build_chapter_layers`（含 mode 推导）再用 authoritative_modes 覆盖，mode 推导白做。
- **§12「禁止广播」张力**：[chapter_split/mod.rs:335](fnm-phase2/src/chapter_split/mod.rs) 把全书 `book_type` 广播到每个 `layer.policy_applied`。注释说明是为修「phantom key 致 `book_type=='endnote_only'` 永远 false」的 silently-wrong bug——属全书属性供下游读，可接受，但与 §12 字面冲突，建议在 §12 注明此例外。
- [structure_model.rs:235](fnm-phase2/src/chapter_split/structure_model.rs) `has_explicit_notes_heading` 硬编码 `contains("### NOTES")`（仅 3 级 + 精确大小写），应改用 `is_notes_heading_line`。
- `Phase2Products` 持久化传 4 个空 vec（pages/chapters/heading_candidates/section_heads），结构含 phase2 不写的字段（冗余）。
- [endnote_regions_raw.rs:200](fnm-phase2/src/note_regions/endnote_regions_raw.rs) `flush_region` 是 8 参数闭包（borrow checker workaround），可重构为持 `current_*` 状态的 struct + 方法。
- `MARKER_EXISTS_RE_CACHE.lock().unwrap()`（[layer2.rs:184](fnm-phase2/src/sup_recovery/layer2.rs)）中毒 panic，与 fnm-core token_counter「中毒兜底」哲学不一致（但缓存场景影响小）。

---

## 5. 正面实践
- note_kind 单一权威 + 统一走 resolve_note_kind（§12 分类源头唯一）。
- chapter_split mode 升级 4 分支显式 reason、year_filter 分组不跨边界。
- layer2 运行期 `Regex::new` 用 `if let Ok` 容错；`has_marker` 的 unwrap 因 `regex::escape` 保证合法。
- visual_anchor / layer3 的 async vision：spawn_blocking 渲染、multi-spec fallback、Semaphore 限流、`tracing::warn!`（质量好，惜未接入）。
- clippy clean（强制重编 0 warning）。

---

## 6. 文件覆盖确认（49/49）
lib｜input｜output｜book_structure｜note_kind_resolver｜chapter_split/{mod,gate,endnote_project,overrides_apply,structure_model,synth_markers}｜endnote_chapter_explorer/{mod,boundary_fallback,matching,numbering,page_signals,signal_select}｜endnote_repair/mod｜llm_bare_digit_verify/{mod,llm_client,prompt_builder,response_parser}｜note_items/{mod,marker_parse,note_scan,page_text,sequence_repair,year_filter}｜note_regions/{mod,book_regions,chapter_lookup,endnote_candidate,endnote_regions_raw,footnote_band,illustration_list,merge_adjacent,normalize,post_body_promote}｜sup_recovery/{mod,layer1,layer2,layer3,pdf_render}｜visual_anchor_recovery/{mod,gap_detection,materialize,override_builder,parsing,vision_client}

> 逐字精读 ~30 个核心文件；其余经去注释 cat + 反模式 grep（Runtime/unwrap/as-cast/to_value/let-_/allow/调用计数）覆盖。`visual_anchor_recovery` 与 `llm_bare_digit_verify` 子模块为未接入子系统，按「质量抽样 + 接入状态」审计。

**核心结论**：phase2 note_kind 主链质量好，但应优先修 **P2-1（切分 fallback 静默失效）** 与 **P2-2（循环建 Runtime）**；并就 ~2000 行未接入代码（P2-4）做去留决策。死字段/未用参数/AI 草稿注释为清理项。
