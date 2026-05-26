# 阶段 4 计划：Orchestrator、PyO3 与 LLM repair 接线闭合

创建时间：2026-05-23
上位目标：`FNM_REPAIR_MASTER_PLAN.md`

本文给接手阶段 4 的人使用。读完本文，应能知道当前管道编排层（orchestrator）和 LLM repair 接线存在哪些流程闭合缺陷、每个缺陷的根因和修复方向、具体要改哪些文件的哪段代码、怎么验证。

**重要区分**：本阶段修的是 orchestrator → LLM repair → PyO3 的**接线和流程闭合**问题，不是 `fnm-phase4` crate 内部的引用冻结/翻译单元逻辑（那属于阶段 5 的 Phase4 引用冻结修复）。

> 2026-05-26 状态更新：repair/orchestrator/PyO3 的无模型回放接线已按其是否向阶段 5 交付真实且不伪造失败的 Phase3/回放事实完成复核，并随阶段 5 程序合同验收关闭。实施顺序和完成判定以 `FNM_REPAIR_MASTER_PLAN.md` 与阶段 5 文档为准；当前不调用真实 API。

## 一、阶段职责与口径

### 本阶段目标

1. **repair 结果本轮生效**：LLM repair auto-apply 写入 overrides 后，同一次 pipeline run 的 Phase4-6 必须消费更新后的 link table，而不是跑旧数据。
2. **Phase3.5 不越权**：LLM repair 不允许新建 note item 或重分类 `note_kind`，这些是 Phase2 的专属决策。
3. **action/cluster 身份可信**：auto-apply 前必须验证 LLM 返回的 ID 属于当前 cluster；partial-write 状态必须被明确记录。
4. **不支持的能力明确拒绝**：`start_phase` 续跑未实现时，直接报错而非静默全量重跑。
5. **PyO3 边界安全**：Rust 错误进入 Python 时不得 panic，config 不得静默丢失。

### 本阶段不做

- `fnm-phase4` crate 内部的双路径合并、freeze blocker、UTF-8 offset panic 修复（阶段 5）。
- Phase5/Phase6 内部的 markdown merge 和 export audit 边界（阶段 6）。
- 逐段 parity 差异、弱 OCR 精调（阶段 7）。
- P3 级工程清理（clippy、大文件拆分、Mutex regex cache）——有余力时可附带处理，但不作为门禁。

## 二、必须先掌握的上下文

### 1. 上游历史验收基线（当前只复核阶段 5 直接依赖）

| 阶段 | 状态 | 关键结论 |
|---|---|---|
| 阶段 1 | 历史验收记录 | DB/error/trace/PyO3 panic 边界/Gemini provider 当时已修 |
| 阶段 2 | 历史验收记录 | Biopolitics + Goldstein 历史批次 `ready`、`blocked=0` |
| 阶段 3 | 历史交接记录 | 当时记录 4 个 P0 已清零；后续追溯发现仍须重新打开合同复核 |

阶段 2 的双书批跑证据：

| 书 | 证据目录 | 结论 |
|---|---|---|
| Biopolitics | `output/fnm_real_batch/phase2_note_capture_v2/` | `ready`, `blocked=0`, LLM repair 请求 20 |
| Goldstein | `output/fnm_real_batch/phase2_note_capture_v2_goldstein/` | `ready`, `blocked=0`, Notes 第 331 页 |

### 2. 当前管道流程概览

```
mainline::run_pipeline_for_doc()
  ├─ Phase1 → persist
  ├─ Phase2 → persist
  ├─ Phase3 → persist
  ├─ Phase3.5: run_llm_repair_sync()  ← 写 overrides 到 DB
  ├─ Phase4 ← 仍用 pre-repair 的 phase3 内存对象（BUG）
  ├─ Phase5
  └─ Phase6
```

```
post_translate::run_post_translate_export_checks()
  ├─ load Phase6 → audit
  ├─ if !can_ship:
  │   ├─ run LLM repair（写 overrides 到 DB）
  │   ├─ reload Phase6（BUG：没重跑 Phase3-6）
  │   └─ re-audit（读到旧 Phase6 数据）
  └─ 返回 can_ship 状态
```

### 3. LLM repair 内部流程

`run_llm_repair()` 位于 `fnm-llm-repair/src/run.rs`：

1. 从 DB 拉取 chapters/note_items/body_anchors/note_links → 构建 `unresolved_clusters`。
2. 逐 cluster：构建 page_contexts + chapter_body_text → 预过滤重复 anchor → 调 LLM → 解析 actions → `select_auto_applicable_actions` → `apply_action` 物化 overrides → `batch_save_fnm_review_overrides_v2`。
3. 返回 `LlmRepairReport`（含 suggestions、auto_applied、usage_summary、error、clusters_completed）。

### 4. Phase 职责边界（不可妥协）

- Phase2 是 `NoteItem` 和 `note_kind` 的**唯一分类来源**。
- Phase3 只做 anchor 检测 + link 匹配，不改 note_kind。
- Phase3.5（LLM repair）只允许合成 anchor、建议 link override，**不能创建 note item 或决定 note_kind**。
- Phase4 只消费上游事实做引用注入 + 翻译单元构建。

### 5. 关键审计文件

本阶段缺陷来源于以下审计记录（均位于 `fnm_re_rs/` 下）：

| 审计文件 | 本阶段涉及条目 |
|---|---|
| `FNM_ORCHESTRATOR_AUDIT.md` | P1-1, P1-2, P1-5, P2-1, P2-2, P2-3 |
| `FNM_LLM_REPAIR_AUDIT.md` | P1-1, P1-2, P1-3, P1-4, P2-1, P2-2, P2-3, P2-4 |
| `FNM_PY_AUDIT.md` | P1-1, P1-2, P1-3, P1-5 |
| `FNM_PHASE4_AUDIT.md` | 仅 P2-3（Orchestrator 传入 note_regions 来源） |

### 6. 已在本轮修复的问题（不需再做）

以下问题已在 transport-retry-fix 批次中完成，不纳入本阶段任务：

1. **传输层瞬时失败分类**（`error.rs`）：HTTP 传输层错误（connection refused/reset/broken pipe/DNS）已分类为 `Transient` 并触发重试。
2. **cluster 失败时保留已有 usage**（`run.rs`）：`LlmRepairReport` 新增 `error` 和 `clusters_completed` 字段；cluster 失败后 break 而非 `?` 传播。
3. **post_translate 处理 partial 结果**（`post_translate.rs`）：`run_one_repair_round` 区分 `used`/`partial` 结果标签。
4. **unsupported start_phase 明确报错**（`mainline.rs:253-259`）：`run_pipeline_from_db` 中 `start_phase != Toc` 直接返回错误。

## 三、缺陷清单

按优先级分组。P0 必须修完才能进入阶段 5；P1 必须修完才能宣称阶段 4 闭合；P2 应修但不严格阻断。

### P0：破坏 phase 职责 / 结构性错误

#### P0-1 Phase3.5 LLM repair 本轮不生效

**位置**：`fnm-orchestrator/src/mainline.rs:135-150`

**现状**：`run_pipeline_for_doc()` 在 Phase3 持久化后调用 `run_llm_repair_sync()`。LLM repair 写入 `fnm_review_overrides_v2` 到 DB。但随后 Phase4 调用使用的是 repair 前的内存 `phase3` 对象：

```rust
let phase4 = pipeline::run_phase4(
    &phase1, &phase3,  // ← 仍然是 repair 前的数据
    &chapter_layers, &raw_pages, &pipeline_run_id, &config,
)?;
```

**影响**：
- LLM repair 即使 auto-applied，本轮导出仍基于旧 orphan/matched 状态。
- `run_meta.llm_repair.auto_applied_count > 0` 与导出结果不一致。
- 用户看到"已修复"但 Phase4/5/6 没有消费修复结果。

**修复**：

repair 完成后且 `auto_applied_count > 0` 时：

1. 从 DB 加载已物化的 overrides：`repo.list_fnm_review_overrides_v2(doc_id)`。
2. 将 overrides 注入 `config.review_overrides`。
3. 重新调用 `pipeline::run_phase3(&phase1, &phase2, &raw_pages, &config)`，得到新的 `phase3`。
4. 重新持久化 Phase3 products。
5. 用新 `phase3` 继续 Phase4-6。

注意：`pipeline::run_phase3` 的 `Phase3Input.overrides` 字段已接收 `config.review_overrides`，所以只需确保 overrides 正确传入即可。

**验证**：
- 构造一个 fixture：Phase3 产生 orphan anchor，LLM repair 为它生成 match override。断言 Phase4 输入的 `note_links` 中该 link 状态变为 matched。
- 断言 repair 后的 Phase3 snapshot 与 repair 前不同。

#### P0-2 Phase3.5 允许创建 note item，绕过 Phase2 分类权

**位置**：
- `fnm-llm-repair/src/run.rs:466-474`：`apply_action("synthesize_note_item")` 分支
- `fnm-llm-repair/src/prompt_builder.rs`：`derive_actions()` 将 `synthesize_note_item` 加入允许列表
- `fnm-llm-repair/src/response_parser.rs`：解析 `synthesize_note_item` action

**现状**：LLM repair 允许创建 `synthesize_note_item` action，在 Phase3.5 层级直接创建 note item，用 cluster 的 `note_system` 写 `note_kind`。

**影响**：
- 绕过 Phase2 的 note item 分类权，违反 phase 职责边界。
- endnote 的 orphan anchor 也可能在 body page 创建 note item。
- 下游看见 "LLM 创建的注释事实"，但上游 Phase2 没有真实 region/item 支撑。

**修复**：

1. 在 `run.rs` 的 `apply_action` 中，将 `"synthesize_note_item"` 分支改为：
   - 记录 warning 到 report（不静默丢弃），但**不物化 override**。
   - 或在 `derive_actions()` 中直接从允许的 action 列表中移除 `synthesize_note_item`。
2. 在 `prompt_builder.rs` 的 `derive_actions()` 中，移除对 `synthesize_note_item` 的所有 action derive。
3. 在 `response_parser.rs` 的 `select_auto_applicable_actions()` 中，添加硬拒绝：如果 `action == "synthesize_note_item"`，跳过 auto-apply。

推荐方案：从 prompt 层面移除，这样 LLM 不会生成这种 action；parser 层面加硬拒绝作为兜底。

**验证**：
- 修改 `prompt_builder.rs` 的 `derive_actions` 测试：任何输入组合下，返回的 allowed actions 不得包含 `synthesize_note_item`。
- 在 `run.rs` 层面添加测试：构造含 `synthesize_note_item` 的 LLM 返回，断言它不被 auto-apply，不写入 overrides。

#### P0-3 Phase4 输入使用 Phase3 重建的 note_regions

**位置**：`fnm-orchestrator/src/pipeline.rs:285`

**现状**：`run_phase4()` 的 `Phase4Input` 传入：
```rust
note_regions: &phase3.structure.note_regions
```
但 Phase3 审计已确认 `Phase3Structure` 有重建 Phase1/Phase2 事实的风险。Phase3 阶段 3 修复后已做 upstream facts 等值透传，但 orchestrator 应从源头消除这个依赖。

**修复**：

`pipeline::run_phase4()` 增加 `phase2` 参数，显式传入 Phase2 的 `note_regions`：
```rust
pub(crate) fn run_phase4(
    phase1: &Phase1Snapshot,
    phase2: &Phase2Snapshot,  // 新增
    phase3: &Phase3Snapshot,
    chapter_layers: &ChapterLayers,
    pages: &[RawPage],
    pipeline_run_id: &str,
    config: &PipelineConfig,
) -> Result<Phase4Snapshot> {
    // ...
    note_regions: &phase2.note_regions,  // 从 Phase2 取
```

同步更新 `mainline.rs` 和 `pipeline.rs` 中所有调用点。

**验证**：
- 编译通过即可确认接线正确。
- 可选：构造一个 Phase3 structure 中 note_regions 与 Phase2 不同的 fixture，断言 Phase4 使用的是 Phase2 版本。

### P1：流程闭合错误

#### P1-1 auto-apply 没有校验 action ID 属于当前 cluster

**位置**：
- `fnm-llm-repair/src/response_parser.rs`：`select_auto_applicable_actions()`
- `fnm-llm-repair/src/run.rs:346-358`：`apply_action` 调用

**现状**：`select_auto_applicable_actions()` 只检查 confidence 阈值和同批重复，不校验 `note_item_id` 或 `anchor_id` 是否属于当前 cluster 的 unmatched 集合。LLM 返回跨 cluster 或不存在的 ID 时可能被 auto-apply。

**修复**：

1. 在 `run_llm_repair()` 中，每个 cluster 处理前收集允许的 ID 白名单：
   ```
   allowed_note_ids: cluster["unmatched_note_items"] 的所有 note_item_id
   allowed_anchor_ids: cluster["unmatched_anchors"] 的所有 anchor_id
   ```
2. 在 `select_auto_applicable_actions()` 或 `apply_action()` 前，验证 action 中引用的 ID 属于白名单。不属于的 action 不进入 auto-apply，记录 warning 到 request_metrics。

**验证**：
- 构造 LLM 返回含不属于当前 cluster 的 `note_item_id` 的 match action，断言不被 auto-apply。
- 构造 LLM 返回含不存在的 `anchor_id`，断言不被 auto-apply。

#### P1-2 duplicate anchor 预过滤没有物化 override

**位置**：`fnm-llm-repair/src/run.rs:188`（`prefilter_duplicate_anchors` 调用）

**现状**：`prefilter_duplicate_anchors()` 直接从 `cluster["unmatched_anchors"]` 中删除条目，只记录 `_prefilter_duplicates_removed` 计数。被删除的 orphan anchor 没有生成 `ignore_ref` override，因此 DB 中原始 unresolved link 仍存在。

**修复**（二选一）：

方案 A（推荐）：预过滤后，对每个被删除的 anchor 生成等价的 `ignore_ref` override，并加入 `cluster_overrides`。

方案 B：移除预过滤，让重复 anchor 走正常 LLM → `ignore_ref` 路径。

**验证**：
- 构造含同页同 marker 重复 anchor 的 cluster，断言被预过滤的 anchor 在 DB 中有 `ignore` override。
- 或方案 B 下，断言这些 anchor 出现在 LLM 请求中。

#### P1-3 fuzzy anchor 坐标字符/字节偏移混用

**位置**：
- `fnm-llm-repair/src/strategies/fuzzy.rs`：`locate_anchor_phrase_in_body()` 返回 `char_start/char_end`（字符偏移）
- `fnm-llm-repair/src/page_context.rs`：`build_chapter_body_text()` 生成 `BodySpan`，使用 `text.len()` （byte 长度）
- `fnm-llm-repair/src/override_materializer.rs`：`enrich_synthesize_anchor_actions()` 混合使用二者

**现状**：fuzzy 返回字符偏移，BodySpan 使用字节偏移。非 ASCII 正文（中文、法文重音、希腊字母）会导致 page span 和 char offset 错位，最终写入 override 的 `page_no`/`char_start`/`char_end` 可能错误。

**修复**：

统一坐标单位为字节偏移（与下游 anchor 坐标 contract 一致）：

1. `build_chapter_body_text()` 的 `BodySpan` 已使用 byte 偏移，保持不变。
2. `locate_anchor_phrase_in_body()` 改为返回 byte offset，而非 char offset。具体做法：用 `find()` 或 `rfind()` 定位字节位置，或在 char offset 基础上通过 `text[..char_idx].len()` 方式转换。
3. `enrich_synthesize_anchor_actions()` 和 `resolve_page_span_from_range()` 中删除字符/字节混用逻辑。
4. 文档化：在 `BodySpan` 和 `RepairAction` 的 `char_start/char_end` 字段上明确注释"单位：byte offset"。

**验证**：
- 构造含中文/重音字符的正文 fixture，fuzzy 命中位于非 ASCII 字符之后的 marker，断言写入 override 的 page_no 和 offset 与真实位置一致。
- 构造跨页的非 ASCII 正文，断言 span 不错页。

#### P1-4 `run_llm_repair_json()` 用 `expect()` 会 panic

**位置**：`fnm-py/src/lib.rs`（搜索 `run_llm_repair_json`）

**现状**：
```rust
runtime.block_on(run_llm_repair(params)).expect("llm repair")
```
DB 缺表、LLM 请求失败、schema 错误等 `Err` 都会触发 panic。panic 进入 PyO3 边界后，Python 调用方难以稳定捕获。

**修复**：
```rust
let report = runtime
    .block_on(run_llm_repair(params))
    .map_err(|e| PyRuntimeError::new_err(format!("llm repair: {e}")))?;
```
同样检查 `tokio runtime` 的 `build()` 调用。

**验证**：
- Python 测试：传入不存在的 `doc_id` 或人为破坏 DB schema，断言抛出 `RuntimeError` 而非 panic/SIGABRT。

#### P1-5 `run_doc_pipeline_json()` 丢失关键配置

**位置**：`fnm-py/src/lib.rs`（搜索 `run_doc_pipeline_json`）

**现状**：高层入口只暴露 `db_path`、`doc_id`、`max_body_chars`、`start_phase`，其余硬编码：
```rust
pdf_path: ""
include_diagnostic_entries: false
visual_toc_bundle: None
review_overrides: None
```

**修复**：

改为接收完整 `config_json`（复用已有的 `parse_pipeline_config()`），或扩展签名支持所有关键字段。至少需要暴露：

- `pdf_path`
- `include_diagnostic_entries`
- `visual_toc_bundle`
- `review_overrides`

未支持的字段遇到非默认值时应报错，不静默丢弃。

同步更新 Python `FNM_RE/__init__.py` 中 `run_doc_pipeline()` 的签名和传参。

**验证**：
- Python 测试：传入 `include_diagnostic_entries=True` 和真实 `pdf_path`，断言它们被 Rust 侧正确消费。

#### P1-6 `build_doc_status_json()` 基于默认 status

**位置**：
- `fnm-py/src/lib.rs`（搜索 `build_doc_status_json`）
- `fnm-orchestrator/src/load.rs`（`load_phase6_structure()`）

**现状**：`load_phase6_structure()` 把 `status` 和 `summary` 构造为 `default()`。Python 拿到的 doc status 多数字段来自默认值。

**修复**：

`load_phase6_structure()` 中：
1. 优先从 DB 的最新 `fnm_runs` 表和 `export_audit` 构建真实 status。
2. 如果 Phase6 数据不存在，返回明确的 "phase6_not_available" 状态，而非默认空对象。
3. `status.blocking_reasons` 必须从真实 export_audit 中读取。

**验证**：
- 构造一个 pipeline run 后的 DB，调用 `build_doc_status_json()`，断言 `structure_state` 和 `blocking_reasons` 与最新 run/export_audit 一致。
- 对空 DB（无 Phase6 数据），断言返回 "not available" 而非空 status。

#### P1-7 Python renderer callback 错误被静默吞掉

**位置**：`fnm-py/src/lib.rs:53-60`（`PyRepairRenderer`）

**现状**：
```rust
let result = self.callback.call1(py, args).ok()?;
result.extract::<Option<String>>(py).ok().flatten()
```
callback 抛异常、类型错误、渲染失败都变成 `None`。LLM repair 会在无图像上下文时继续运行。

**修复**：

1. callback 异常时记录错误到一个可外部读取的 error 通道（如 `Arc<Mutex<Vec<String>>>`），或直接返回 `Err`。
2. 至少在 repair report 的 `request_metrics` 中记录 "renderer_error"。
3. 可选：renderer 失败次数超过阈值时，对 `synthesize_anchor` 禁用 auto-apply（因为缺乏视觉证据）。

**验证**：
- Python 测试：传入一个会抛异常的 renderer callback，断言 repair report 中有 renderer error 记录。

#### P1-8 LLM 请求失败时留下部分已保存 overrides

**位置**：`fnm-llm-repair/src/run.rs:361-363`

**现状**：每处理完一个 cluster 就调用 `batch_save_fnm_review_overrides_v2()`。如果后续 cluster 失败，前面已保存的 overrides 不回滚。

**修复**（三选一）：

方案 A（推荐）：先收集全部 overrides，整轮成功后一次性写入。需要调整 `cluster_overrides` 的生命周期。

方案 B：用 `pipeline_run_id` 标记本轮 overrides，失败时清理本轮写入。

方案 C：保持当前行为（partial-write），但在 `LlmRepairReport.error` 中明确记录 partial-write 状态，下游消费者需要知道 overrides 可能不完整。

方案 C 的代价最低，但需要在 `mainline.rs` 消费 report 时判断：如果 `report.error.is_some()`，不自动消费 overrides 进入 Phase4。

**验证**：
- 构造 3 个 cluster，模拟第 2 个 cluster LLM 调用失败。
- 方案 A：断言 DB 中无任何 overrides。
- 方案 C：断言 report.error 非空，且 mainline.rs 不消费 partial overrides。

#### P1-9 post-translate repair 循环不重跑 Phase3-6

**位置**：`fnm-orchestrator/src/post_translate.rs:240-253`

**现状**：repair round 后只 `load_phase6_structure()` 并 re-audit，没有重跑 Phase3-6。由于 repair 写的是 overrides，reload 的 Phase6 仍然是旧数据。

**修复**：

这是一个架构问题，完整修复需要 `run_post_translate_export_checks()` 能触发 Phase3-6 re-run。有两种方案：

方案 A（完整修复）：扩展 `run_post_translate_export_checks()` 签名，接收 pipeline 重跑所需的全部输入（pages、toc_items、phase1、phase2、config），repair 后调用 Phase3-6。

方案 B（最小修复，推荐本阶段采用）：承认 post-translate repair 只在**下一次** pipeline run 生效。在返回值中明确标记 `repair_applied_but_not_reexported: true`，不报告修复后的 `can_ship`（因为它不可信）。

**验证**：
- 方案 B：断言返回 JSON 中，当 repair 应用了 overrides 时，`repair_applied_but_not_reexported` 为 true，且 `post_round_can_ship` 不被报告为最终结论。

#### P1-10 Phase5 diagnostic pages/notes 被丢弃

**位置**：`fnm-orchestrator/src/mainline.rs:164-168`

**现状**：
```rust
let phase5_products = Phase5Products {
    chapter_markdowns: phase5.chapter_markdowns.chapters.clone(),
    diagnostic_pages: Vec::new(),   // ← 写空
    diagnostic_notes: Vec::new(),   // ← 写空
};
```

**修复**：

Phase5 输出类型 `ChapterMarkdownSet` 需要携带 diagnostic pages/notes。当前 `build_chapter_markdown_set()` 内部构造了 Phase5 shadow 含 `diagnostic_pages`，但返回类型不包含。

1. 扩展 `fnm_phase5::build_chapter_markdown_set()` 的返回类型，包含 `diagnostic_pages` 和 `diagnostic_notes`。
2. 或从 Phase5 shadow 中提取 diagnostic 数据。
3. `mainline.rs` 持久化时使用真实数据而非空 Vec。

注意：这可能涉及修改 `fnm-phase5` crate 的公开 API，需要与阶段 5/6 协调。如果本阶段时间不足，可先记录为 P1 并在阶段 5 一并修复，但需在 `mainline.rs` 加注释标记 TODO。

**验证**：
- `include_diagnostic_entries=true` 时，断言持久化的 Phase5 products 中 `diagnostic_pages` 和 `diagnostic_notes` 非空（针对有 diagnostic 条目的 fixture 输入）。

### P2：重要质量问题

#### P2-1 fnm_run finalize 错误被忽略

**位置**：`fnm-orchestrator/src/mainline.rs:328`

**现状**：失败路径使用 `let _ = repo.update_fnm_run(...)`。

**修复**：
- 成功路径：已正确使用 `?`。
- 失败路径：`update_fnm_run` 失败时，把 finalize 错误并入原始错误上下文，不静默丢弃。

#### P2-2 关键配置字段未使用或硬编码覆盖

**位置**：`fnm-orchestrator/src/pipeline.rs`、`fnm-orchestrator/src/types.rs`

**现状**：`skip_sup_recovery: true`、`skip_llm_verify: true`、`manual_page_overrides: None`、`endnotes_start_page: None` 等被硬编码。

**修复**：这些字段应由 config 控制。至少：
- `skip_sup_recovery` 和 `skip_llm_verify` 从 `PipelineConfig` 读取。
- `endnotes_start_page` 从 config 或 Phase1 输出读取。

#### P2-3 page role 读取失败静默放宽正文范围

**位置**：`fnm-llm-repair/src/page_context.rs`

**现状**：`fnm_page_role_by_no()` 读取 DB 失败时直接返回空 `HashMap`，导致 note/back matter 页可能被当作正文。

**修复**：读取失败时返回 `Err` 或设置标志位，禁用 `synthesize_anchor` auto-apply。

#### P2-4 `derive_actions()` 对 endnote 也允许 `synthesize_note_item`

**位置**：`fnm-llm-repair/src/prompt_builder.rs`

**现状**：`derive_actions()` 不按 `note_system` 分流，endnote 也可能产生 `synthesize_note_item`。

**修复**：如果 P0-2 的修复是完全移除 `synthesize_note_item`，则此项自动解决。如果只是限制条件，则需要在 `derive_actions()` 中按 `note_system` 分流：endnote 只允许 `ignore_ref` 或 `needs_review`。

#### P2-5 `safe_float()` 接受文字置信度

**位置**：`fnm-llm-repair/src/usage.rs`、`fnm-llm-repair/src/response_parser.rs`

**现状**：parser 把 `"high"` 映射成 `0.9`、`"medium"` 映射成 `0.7`，模型违反输出 contract 时仍可能 auto-apply。

**修复**：auto-apply 路径要求 confidence 必须是 JSON number。文字置信度最多保留为 suggestion。

#### P2-6 `page_translate` 用 JSON error 替代 Result

**位置**：`fnm-orchestrator/src/page_translate.rs`

**现状**：段落数不一致时返回 `{"error": "..."}`。

**修复**：内部函数改为 `Result<Value, anyhow::Error>`；PyO3 层转 `PyRuntimeError`。

#### P2-7 `load_phase6_structure()` export/audit 缺失时默认补空

**位置**：`fnm-orchestrator/src/load.rs`

**现状**：Phase6 数据缺失时用 `unwrap_or_default()` 返回空对象。

**修复**：返回结构化 incomplete 状态或 `Err`，不默认构造 status/summary。与 P1-6 配合修复。

## 四、实施步骤

按依赖关系分为 5 个 Task，建议顺序执行。每个 Task 完成后运行对应测试即可推进，不需要等全部做完再测。

### Task 1：LLM repair 安全边界（P0-2 + P1-1 + P2-4 + P2-5）

**目标**：让 Phase3.5 不越权、action ID 可信。

**文件改动**：

| 文件 | 改动 |
|---|---|
| `fnm-llm-repair/src/prompt_builder.rs` | `derive_actions()` 移除 `synthesize_note_item`；endnote 分流 |
| `fnm-llm-repair/src/response_parser.rs` | `select_auto_applicable_actions()` 硬拒绝 `synthesize_note_item`；增加 `allowed_ids` 参数 |
| `fnm-llm-repair/src/run.rs` | `apply_action` 中 `synthesize_note_item` 分支改为记录 warning；收集 cluster ID 白名单传给 select |
| `fnm-llm-repair/src/usage.rs` | `safe_float()` 对非 number confidence 在 auto-apply 路径标记为不合格 |

**测试**：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo test -p fnm-llm-repair -- synthesize_note_item
cargo test -p fnm-llm-repair -- cluster_id_whitelist
cargo test -p fnm-llm-repair -- confidence_number
cargo test -p fnm-llm-repair
```

### Task 2：repair 结果本轮生效（P0-1 + P1-8 + P1-9）

**目标**：repair 后 Phase4-6 消费更新后的 link table。

**文件改动**：

| 文件 | 改动 |
|---|---|
| `fnm-orchestrator/src/mainline.rs` | repair 后判断 `auto_applied_count > 0`：从 DB 加载 overrides → 重跑 Phase3 → 持久化 → 更新 phase3 变量 |
| `fnm-orchestrator/src/pipeline.rs` | `run_phase4` 签名加 `phase2` 参数（配合 P0-3） |
| `fnm-llm-repair/src/run.rs` | 可选：方案 C 下无需改动；方案 A 下改为收集后批量写入 |
| `fnm-orchestrator/src/post_translate.rs` | 返回值增加 `repair_applied_but_not_reexported` 字段 |

**具体实现**（`mainline.rs`）：

在 Phase3.5 和 Phase4 之间插入：

```rust
// ── repair 结果本轮生效 ──
let phase3 = if let Some(ref report) = llm_repair_report {
    if report.auto_applied_count > 0 && report.error.is_none() {
        // 从 DB 加载物化后的 overrides
        let overrides = repo.list_fnm_review_overrides_v2(doc_id)
            .map_err(|e| OrchestratorError::Phase3(
                anyhow::anyhow!("load overrides after repair: {}", e)
            ))?;
        // 构建 config with overrides
        let mut config_with_overrides = config.clone();
        config_with_overrides.review_overrides = Some(overrides);
        // 重跑 Phase3
        let new_phase3 = pipeline::run_phase3(
            &phase1, &phase2, &raw_pages, &config_with_overrides
        )?;
        // 重新持久化
        let new_phase3_products = Phase3Products {
            body_anchors: new_phase3.body_anchors.clone(),
            note_links: new_phase3.note_links.clone(),
        };
        repo.replace_fnm_phase3_products(doc_id, &new_phase3_products)
            .map_err(|e| OrchestratorError::Phase3(
                anyhow::anyhow!("re-persist phase3 after repair: {}", e)
            ))?;
        // 更新 snapshot
        snapshot.phase3 = Some(SerPhase3 {
            body_anchors: new_phase3_products.body_anchors,
            note_links: new_phase3_products.note_links,
        });
        new_phase3
    } else {
        phase3
    }
} else {
    phase3
};
```

注意：`config.review_overrides` 的类型需要与 `repo.list_fnm_review_overrides_v2()` 的返回类型对齐。检查 `Phase3Input.overrides` 期望的格式并做必要转换。

**测试**：

```bash
cargo test -p fnm-orchestrator -- repair_affects_phase4
cargo test -p fnm-orchestrator
```

### Task 3：Phase4 输入来源修正（P0-3）

**目标**：Phase4 从 Phase2 获取 note_regions。

**文件改动**：

| 文件 | 改动 |
|---|---|
| `fnm-orchestrator/src/pipeline.rs` | `run_phase4` 签名加 `phase2: &Phase2Snapshot` 参数；`note_regions` 取自 `phase2.note_regions` |
| `fnm-orchestrator/src/mainline.rs` | 调用 `run_phase4` 时传入 `&phase2` |

这是一个小改动，可与 Task 2 合并。

**测试**：

```bash
cargo test -p fnm-orchestrator
cargo build --release -p fnm-orchestrator
```

### Task 4：PyO3 边界安全（P1-4 + P1-5 + P1-6 + P1-7）

**目标**：Rust 错误不 panic 进 Python；config 不丢；status 可信；renderer 错误可追踪。

**文件改动**：

| 文件 | 改动 |
|---|---|
| `fnm-py/src/lib.rs` | (1) `run_llm_repair_json` 去掉 `expect()`，改 `map_err(PyRuntimeError)` |
|  | (2) `run_doc_pipeline_json` 扩展签名或改为接收 `config_json` |
|  | (3) `build_doc_status_json` 改为从真实 audit/run 构建 status |
|  | (4) `PyRepairRenderer` 的 callback 错误记录到 error 通道 |
| `fnm-orchestrator/src/load.rs` | `load_phase6_structure` 不默认补空 status |
| `FNM_RE/__init__.py` | `run_doc_pipeline()` 同步暴露新参数 |

**测试**：

```bash
# Rust 编译
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo build --release -p fnm-py

# PyO3 rebuild
cd /Users/hao/OCRandTranslation/fnm_re_rs/fnm-py
CARGO_TARGET_AARCH64_APPLE_DARWIN_RUSTFLAGS="-C link-arg=-undefined -C link-arg=dynamic_lookup" \
  ../../.venv/bin/python -m maturin develop --release

# Python 测试
cd /Users/hao/OCRandTranslation
.venv/bin/python -m pytest fnm_re_rs/fnm-py/tests -q
```

### Task 5：Orchestrator 流程收尾（P1-9 + P1-10 + P2-1 + P2-2 + P2-3 + P2-6 + P2-7）

**目标**：post-translate 结果可信、diagnostic 不丢、错误不被吞。

**文件改动**：

| 文件 | 改动 |
|---|---|
| `fnm-orchestrator/src/post_translate.rs` | 增加 `repair_applied_but_not_reexported` 字段 |
| `fnm-orchestrator/src/mainline.rs` | diagnostic 持久化用真实数据；fnm_run finalize 错误不丢 |
| `fnm-orchestrator/src/load.rs` | Phase6 缺失时返回结构化 incomplete |
| `fnm-orchestrator/src/pipeline.rs` | skip_* config 从 PipelineConfig 读取 |
| `fnm-orchestrator/src/page_translate.rs` | JSON error 改为 `Result` |
| `fnm-llm-repair/src/page_context.rs` | page role 读取失败不静默 |

**测试**：

```bash
cargo test -p fnm-orchestrator
cargo test -p fnm-llm-repair
```

## 五、验收标准

### 1. 单元/集成测试

所有新增和修改的测试必须通过：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo test -p fnm-llm-repair
cargo test -p fnm-orchestrator
cargo build --release -p fnm-py
```

### 2. 双书全量批

阶段 4 收尾前必须运行 Biopolitics + Goldstein 完整批次：

```bash
cd /Users/hao/OCRandTranslation
.venv/bin/python scripts/test_fnm_real_batch.py --slug Biopolitics --group all --include-all --verbose
.venv/bin/python scripts/test_fnm_real_batch.py --slug Goldstein --group all --include-all --verbose
```

最低证据：
- 两书均 `ready`，`blocked=0`。
- `batch_report.md` 列出 status 与 blocker。
- `token_summary.json` 记录 LLM 调用。
- 如果 Biopolitics 有 repair，`llm_traces/` 中应有 trace 文件。

### 3. 关键行为断言

| 断言 | 验证方法 |
|---|---|
| repair 后 Phase4 消费新 link table | Task 2 测试 |
| `synthesize_note_item` 不被 auto-apply | Task 1 测试 |
| Phase4 使用 Phase2 的 note_regions | Task 3 测试 |
| PyO3 不 panic | Task 4 Python 测试 |
| cross-cluster ID 不被 auto-apply | Task 1 测试 |

### 4. 不要求

- 逐段 parity 与根底本完全对齐（阶段 7）。
- Phase4 内部 ref_freeze 双路径合并（阶段 5）。
- Phase5/Phase6 内部边界修复（阶段 6）。
- clippy 全通过（P3 工程清理，不阻门禁）。

## 六、风险与注意事项

1. **P0-1 的 overrides 格式对齐**：`repo.list_fnm_review_overrides_v2()` 返回的格式需要与 `Phase3Input.overrides` 期望的格式一致。检查 `fnm-phase3/src/input.rs` 中 `overrides` 字段的类型定义，和 `fnm-core/src/db/repository.rs` 中 `list_fnm_review_overrides_v2` 的返回类型，必要时做 adapter。

2. **P0-1 的 raw_pages 可用性**：在 `mainline.rs` 中，`raw_pages` 作为参数传入 `run_pipeline_for_doc`，在 Phase3.5 后仍然可用（未被 move）。确认 `run_llm_repair_sync` 对 `raw_pages` 是借用而非消费。

3. **P1-9 的阶段边界**：post-translate 完整修复（repair 后重跑 Phase3-6）可能需要大幅改造接口签名和数据流。如果本阶段时间不足，方案 B（标记 `not_reexported`）是安全的最小修复。

4. **P1-10 的跨 crate 改动**：diagnostic 持久化需要修改 `fnm-phase5` 的公开 API。如果这会与阶段 5 的 Phase4 修复冲突，可在本阶段只在 `mainline.rs` 中标记 TODO。

5. **PyO3 编译特殊性**：macOS + Python 3.14 + pyo3 0.21.2 需要特殊 linker flags。编译命令：
   ```bash
   CARGO_TARGET_AARCH64_APPLE_DARWIN_RUSTFLAGS="-C link-arg=-undefined -C link-arg=dynamic_lookup" \
     .venv/bin/python -m maturin develop --release
   ```

6. **不要在本阶段做的事**：
   - 不要修改 `fnm-phase4/src/ref_freeze/` 内部逻辑（阶段 5）。
   - 不要修改 `real_golden_template/`。
   - 不要用 Rust actual 覆盖 fixture。
   - 不要为了让 batch report 变绿而跳层修补。
