# FNM-PHASE5 审计报告（独立第二轮）

> 审计范围：`fnm-phase5` crate 全部 20 个 `.rs` 文件（约 3,067 行）。章 markdown 合并。
> 维度：程序逻辑、Rust 风格、过度防御/偷懒/AI 常见病。业务规则不评判。
> 方法：逐文件精读核心 + 反模式 grep 全覆盖 + P4-1 跨 crate 数据契约验证。审计期间未参考现有 `audit/`。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

---

## 0. 总体印象：高质量（与 phase3/4 同档）

phase5（章 markdown 合并）质量高：
- crate 级 `#![deny(unused_must_use)]`。
- **铁律合规**：`phase5_shadow` 透传 Phase2 权威 `chapter_note_modes`（不重推导，§1），章节边界仅含正文页（`chapter_pages_from_layer` 排除 endnote region/items 页，§4）——均有专门测试断言。
- **不猜测替换正文 raw marker**：[marker_rewrite.rs:8-11](fnm-phase5/src/marker_rewrite.rs) 注释明确移除了 `rewrite_residual_raw_markers_for_chapter`，改为 diagnostics + merge_reviews 结构化 blocker（符合 CLAUDE.md §7「正向验证而非猜测」）。
- merge reviews 输出结构化 blocker（merge_chapter_file_missing / merge_frozen_ref_leak / merge_raw_marker_leak / merge_local_refs_unclosed）。
- 全 crate **无** `#[allow]`/`Runtime`/`as` 窄化；非测试 unwrap 仅 diagnostics.rs 3 处；生产代码无 panic（marker_rewrite.rs:194 的 `panic!` 在 `#[cfg(test)]` 内）；clippy clean。

---

## 1. P4-1 跨 crate 验证结论（phase4 遗留疑点 → 降级为低）

phase4 审计留下的 **P4-1**（`FrozenUnit.page_segments` 恒空）在此验证：
- **链路确认**：[convert.rs:110](fnm-phase5/src/convert.rs) `to_page_segments(unit)` 遍历 `unit.page_segments`（phase4 恒空）→ 故 `TranslationUnitRecord.page_segments` 恒空。
- **但正文渲染不依赖它**：[render/body_render.rs:21-63](fnm-phase5/src/render/body_render.rs) `resolve_body_unit_text` 取正文的优先级是 **`translated_text` → diagnostic_machine_by_page → `source_text`**（含已注入的 NOTE_REF token），**完全不读 page_segments 渲染正文**。
- `page_segments` 在 phase5 **仅** 用于 diagnostic 模式提取 `page_numbers`（body_render.rs:31-46），且为空时 fallback 到 `page_start..=page_end`。
- **结论**：phase4 page_segments 恒空**不会导致章节正文丢失**。唯一影响：`include_diagnostic_entries=true` 且章节页码非连续（中间夹 note 页）时，diagnostic 的 page_numbers 退化为连续范围 —— 有合理 fallback。**P4-1 从「待定」降级为低优先级**（建议：要么 phase4 真正持久化 page_segments，要么删除该字段 + convert::to_page_segments 死链路，消除「算了又丢」的认知负担）。

---

## 2. 🟡 低优先级
- **P4-1 残留**（见上）：`convert::to_page_segments` + `FrozenUnit.page_segments` 字段构成「phase4 算→丢→phase5 读空」的冗余链路，建议二选一清理。
- [diagnostics.rs](fnm-phase5/src/diagnostics.rs) 3 处非测试 unwrap（leak 诊断模块）——经 grep 定位，属诊断路径；建议复核是否均为 regex/已知结构 unwrap。
- [render/body_render.rs:142-146](fnm-phase5/src/render/body_render.rs) 手动 `updated.find(old)` + byte 切片替换 frozen ref——`pos`/`old.len()` 来自 `find`/capture（char boundary 安全），但循环内 `format!` 重建整串（O(n·m)），可用 `replacen` 或一次性 builder。低优先级（章节文本不大）。

---

## 3. 正面实践
- `resolve_body_unit_text` 三级 fallback（translated → diagnostic → source）保证正文永不空（最终 `[待翻译]` 占位）。
- `rewrite_body_text_with_local_refs` 多步 ref 改写：条件 `[N]→[^N]` 仅对已在 `local_ref_numbers` 中的 marker（不误转日期/页码，§7）。
- `emit_definitions` endnote 定义用 `[^N]:` 格式，skipped（无正文引用）用 `> marker. text` 引用块区分。
- `build_section_markdown` 区分 mixed+footnote_primary 的 inline footnote 路径 vs endnote 路径。

---

## 4. 文件覆盖确认（20/20）
lib｜convert｜diagnostic_helpers｜diagnostics｜marker_rewrite｜phase5_shadow｜render/{mod,body_render,book_type,chapter_pages,diagnostic_text,filename,footnote,markdown_clean,merge,note_lookup,section_builder,section_head,section_render,title}

> 逐字精读 lib + convert + phase5_shadow + section_render + body_render + marker_rewrite（核心渲染链路）；其余经反模式 grep（clean）+ 去注释 cat 覆盖。

**核心结论**：phase5 质量高、铁律合规、不猜测改写正文。无真 bug。主要价值是**确认了 P4-1 不致正文丢失（降级为低）**，建议清理「page_segments 算了又丢」的冗余链路。
