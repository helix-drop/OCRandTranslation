# FNM-ORCHESTRATOR 审计报告（独立第二轮）

> 审计范围：`fnm-orchestrator` crate 全部 15 个 `.rs` 文件（约 3,407 行）。主线编排 + 按页翻译 job。
> 维度：程序逻辑、Rust 风格、过度防御/偷懒/AI 常见病。业务规则不评判。
> 方法：逐文件精读核心 + 反模式 grep 全覆盖 + page_segments 跨 crate 数据契约追踪。审计期间未参考现有 `audit/`。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

---

## 0. 总体印象

编排骨架（`pipeline.rs` / `mainline.rs`）质量高：phase1→6 串联清晰、每 phase 消费上游 snapshot、错误用 `OrchestratorError::PhaseN` 包装、`run_pipeline_from_db` 错误路径也 finalize `fnm_run`（不留悬挂 `running`）、用 `#[expect(clippy::too_many_arguments)]`（比 `#[allow]` 严格）、生产代码无 unwrap（17 个全在测试）、MVP 未实现范围诚实标注。

但 **`page_translate`（按页翻译）子系统暴露一个跨 4-crate 的数据契约缺陷（O-1）**，是本轮审计最有价值的发现——单看任一 crate 都不明显。

---

## 1. 🟠 中-高优先级

### O-1　`page_segments` 跨 crate 恒空，致按页翻译正文 job 全跳过
- **链路**（4 crate）：
  1. **phase4** [ref_freeze/mod.rs:489,558](fnm-phase4/src/ref_freeze/mod.rs)：`FrozenUnit { page_segments: Vec::new(), ... }`（注释「JSON → 暂不反序列化」）——chunk 算出的 page_segments 仅用于导出 page_nos，**未持久化进 unit**（即 phase4 审计的 P4-1）。
  2. **phase5/convert** [convert.rs:178](fnm-phase5/src/convert.rs)：`to_translation_unit_records` → `to_page_segments(unit)` 遍历空 `unit.page_segments` → `TranslationUnitRecord.page_segments` 空。
  3. **持久化**：`replace_fnm_translation_units` 写 `page_segments_json = "[]"`；`list_fnm_translation_units` 读回空。
  4. **orchestrator** [page_translate/jobs.rs:9-25,211-225](fnm-orchestrator/src/page_translate/jobs.rs)：`frozen_body_text_for_page` **只**遍历 `unit.page_segments` 取 `source_text`，**无 source_text 字段 fallback**；空 → `frozen` 空 → `frozen_parts` 空 → 正文段循环 `text="" && i>=0 → continue` 全跳过 → `para_jobs` 仅剩 note job。
- **活跃性确认**：`prepare_page_translate_jobs` 经 [fnm-py/src/lib.rs:1124](fnm-py/src/lib.rs) + [translate.rs:38](fnm-py/src/translate.rs) 暴露给 Python，是**真实按页翻译入口**（非死代码）。
- **后果**：若按页翻译模式被使用，**正文段落翻译 job 全空**（用户拿不到正文，只有 note）。注意：章合并模式（phase5 `build_chapter_markdown_set`）走 `source_text` fallback **不受影响**——故该 bug 仅在 page-translate 路径显现，可能因主用 chapter-merge 而长期潜伏。
- **建议**（二选一）：① phase4 真正把 chunk 的 page_segments 反序列化持久化到 `FrozenUnit.page_segments`；② `frozen_body_text_for_page` 在 page_segments 空时 fallback 到 `unit.source_text`（与 phase5 `resolve_body_unit_text` 一致）。
- **置信度**：静态代码分析确证 page_segments 恒空链路；建议补一个 page-translate 端到端 fixture 测试钉死正文非空，运行时确认。

---

## 2. 🟡 低-中优先级

### O-2　`tokio` runtime 在 model fallback 循环内创建
- [post_translate.rs:100](fnm-orchestrator/src/post_translate.rs)：遍历候选 model 的循环内每次 `Builder::new_current_thread().build()`。`new_current_thread` 远比 `Runtime::new()` 轻量，且成功即 `break`（通常 1-3 次），影响小；仍建议循环外建一个 runtime 复用。
- [mainline.rs:522](fnm-orchestrator/src/mainline.rs) `run_llm_repair_sync` 的 runtime 是 per-pipeline 一次（非循环），可接受。

### O-3　`apply.rs` 构建后丢弃 `_section_title`
- [page_translate/apply.rs:17](fnm-orchestrator/src/page_translate/apply.rs) `let _section_title = unit.get("section_title")...` 提取后从未使用（同 phase1 的「构建后丢弃」死代码模式，但仅一处、开销小）。

---

## 3. 正面实践
- `run_pipeline` / `run_pipeline_from_db` 双入口（内存 / DB-driven），后者完整管理 `fnm_run` create→finalize 生命周期，**错误也 finalize**。
- 每 `run_phaseN` 薄包装 + `OrchestratorError::PhaseN(e)` 错误归类，pipeline 失败可定位到 phase。
- `generate_run_id` 用 doc_id + 时间戳 hash（确定性 + 唯一）。
- LLM repair 同步包装（`run_llm_repair_sync`）对齐 Python 同步语义，caller 无需持有 runtime。

---

## 4. 文件覆盖确认（15/15）
lib｜error｜types｜load｜pipeline｜mainline｜post_translate｜page_translate/{mod,apply,format,jobs,jobs_builder,progress,retry,tests}

> 逐字精读 pipeline + mainline 核心 + post_translate + jobs + page_segments 全链路追踪；其余（retry/apply/format/jobs_builder/progress/load/types/error）经反模式 grep（clean）+ 去注释 cat + 调用核实覆盖。

**核心结论**：编排骨架质量高。**O-1（page_segments 恒空致按页翻译正文丢失）是必须运行时验证并修复的跨 crate 缺陷**——它把 phase4 的「算了又丢」字段从「无害冗余」变成了 page-translate 路径的「正文丢失」。其余为轻量清理（循环内 runtime、死变量）。
