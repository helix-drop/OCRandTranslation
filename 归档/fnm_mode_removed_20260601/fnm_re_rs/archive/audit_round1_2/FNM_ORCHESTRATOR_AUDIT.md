# fnm-orchestrator 审计记录

审计时间：2026-05-22

审计范围：

- `fnm-orchestrator/src/lib.rs`
- `fnm-orchestrator/src/types.rs`
- `fnm-orchestrator/src/pipeline.rs`
- `fnm-orchestrator/src/mainline.rs`
- `fnm-orchestrator/src/load.rs`
- `fnm-orchestrator/src/page_translate.rs`
- `fnm-orchestrator/src/post_translate.rs`
- `fnm-orchestrator/src/error.rs`

## 结论

`fnm-orchestrator` 当前能跑通最小内存/DB 流程，但它还不是可信的“管道编排层”。多个配置字段只进入 metadata 或完全未使用；`start_phase` 没有实际续跑语义；Phase 3.5 LLM repair 写入 DB 后没有被本轮 Phase4/5/6 消费；Phase5 diagnostic 产物没有持久化；post-translate repair 循环也没有重跑后续 phase。

从代码质量看，crate 本体没有动态 Regex、Mutex、Rc/RefCell 这类明显反模式；但 `page_translate.rs` 过大，且大量接口以 `serde_json::Value` 返回软错误，容易让 Python binding 或调用方漏判。

## P1：必须优先修复

### 1. `start_phase` 只写入 meta，没有实际续跑逻辑

位置：`src/pipeline.rs`、`src/mainline.rs`、`src/types.rs`

`PipelineConfig.start_phase` 定义了：

- `Toc`
- `ChapterLayers`
- `NoteLinkTable`
- `FrozenUnits`

但 `run_pipeline()` 和 `run_pipeline_for_doc()` 无论配置是什么，都从 Phase1 跑到 Phase6。`start_phase` 只被写入 `run_meta`。

问题：

- 调用方以为可以从 Phase3/Phase4 续跑，实际会重跑并覆盖前序产物。
- 已人工确认的 Phase1/2/3 数据可能被无意覆盖。
- `mainline.rs` 文件头承诺“下次可从 start_phase 续跑”，但实现没有做到。

建议：

- `start_phase != Toc` 时必须从 DB 加载对应前置产物，而不是重新计算。
- 对不支持的 start phase 直接 `bail`，不要写进 meta 后继续全量跑。
- 增加 DB fixture 测试：设置 `start_phase=FrozenUnits` 时 Phase1-3 不应被重写。

### 2. Phase 3.5 LLM repair 本轮不生效

位置：`src/mainline.rs`、`src/pipeline.rs`

`run_pipeline_for_doc()` 在 Phase3 持久化后调用 `run_llm_repair_sync()`。注释说 auto-apply 会写 `fnm_review_overrides`，Phase4 会“自然消费”。

实际 Phase4 调用是纯内存：

```rust
let phase4 = pipeline::run_phase4(&phase1, &phase3, &chapter_layers, ...)?;
```

`run_phase4()` 不读取 DB，也不重新加载或重新构造已应用 override 后的 Phase3 link table。本轮 Phase4/5/6 仍然使用 repair 前的 `phase3` 内存对象。

问题：

- LLM repair 即使 auto-applied，也不会影响本轮导出。
- `run_meta.llm_repair.auto_applied_count > 0` 可能和导出结果不一致。
- 用户看到“已修复”但 Phase4/5/6 仍基于旧 orphan/matched 状态运行。

建议：

- repair 后重新读取 materialized overrides，并从 Phase3 起重跑。
- 或让 `run_llm_repair` 返回已应用的 override/link delta，由 orchestrator 显式更新 Phase3Snapshot。
- 加测试：构造一个 repair override，断言 Phase4 输入 link table 已变化。

### 3. Phase5 diagnostic pages/notes 被丢弃

位置：`src/mainline.rs`、`fnm-phase5/src/lib.rs`、`fnm-phase5/src/phase5_shadow.rs`

`build_chapter_markdown_set()` 内部会构造 Phase5 shadow，其中包含 `diagnostic_pages`。但返回类型 `ChapterMarkdownSet` 只有：

- `chapters`
- `chapter_contract_summary`
- `merge_summary`

`run_pipeline_for_doc()` 持久化 Phase5 时直接写空：

```rust
diagnostic_pages: Vec::new(),
diagnostic_notes: Vec::new(),
```

问题：

- `include_diagnostic_entries=true` 也不会把 diagnostic pages/notes 落库。
- `prepare_page_translate_jobs()` 依赖 `repo.list_fnm_diagnostic_notes()`，因此翻译任务中的 note jobs 会缺失。
- Phase5 shadow 里生成 diagnostic pages 的代码实际无法通过 orchestrator 出口保存。

建议：

- Phase5 输出类型应携带 diagnostic pages/notes。
- Orchestrator 持久化 Phase5 时不能写空 Vec。
- 加测试：`include_diagnostic_entries=true` 后 DB 中应有 diagnostic pages/notes。

### 4. `load_phase6_structure()` 默认补空 export/status，掩盖缺失数据

位置：`src/load.rs`

`load_phase6_structure()` 在 export bundle/audit 缺失时使用：

```rust
unwrap_or_default()
```

并且无论 DB 中是否有真实 status，都设置：

```rust
status: StructureStatusRecord::default(),
summary: Phase6Summary::default(),
```

问题：

- 缺少 Phase6 export/audit 时不会报错，而是返回默认对象。
- post-translate 检查和 Python 状态接口可能把“不存在的 Phase6 产物”当作空结构处理。
- `phase6.status.blocking_reasons` 被清空，后续逻辑读不到真实 blocker。

建议：

- Phase6 bundle/audit 缺失应返回明确错误或结构化 incomplete 状态。
- 不要在 loader 里默认构造 status/summary；需要从 DB 读取真实状态，或由 audit 重新计算后写入。

### 5. post-translate repair 循环不重跑 Phase3-6

位置：`src/post_translate.rs`

`run_post_translate_export_checks()` 在 `can_ship=false` 时调用 LLM repair，然后只是重新 `load_phase6_structure()` 并 audit：

```rust
let (new_audit, _) = fnm_phase6::export_audit::audit_phase6_export(&phase6, slug, None);
```

它没有重跑 Phase3/4/5/6，也没有重建 export bundle。由于 repair 写的是 overrides，本轮 reload 的 Phase6 持久化产物通常仍然是旧数据。

问题：

- repair round 的 `post_round_can_ship` 大概率不会反映 repair 结果。
- 若 `can_ship` 变化，只可能来自 DB 侧其它副作用，不是完整 pipeline 的确定产物。
- 这个循环名义上是“自修复导出检查”，实际没有把修复接入导出链路。

建议：

- 每轮 repair 后至少从 Phase3 重新 materialize link table，再跑 Phase4-6。
- 若暂不支持，应返回 `repair_applied_but_not_reexported`，不要报告修复后的 can_ship。

## P2：需要修复的质量问题

### 1. fnm_run finalize 错误被忽略

位置：`src/mainline.rs`

成功和失败路径都使用：

```rust
let _ = repo.update_fnm_run(...);
```

问题：

- 文件头承诺错误路径会 finalize run，但 update 失败时会静默留下 `running`。
- 这违反“关键参数/关键结果不能 `let _` 忽略”的 Rust 规范。

建议：

- 成功路径 update 失败应返回错误。
- 失败路径 update 失败应至少把 finalize 错误并入原始错误上下文。

### 2. 关键配置字段未使用或硬编码覆盖

位置：`src/types.rs`、`src/pipeline.rs`

未实际接线或被硬编码的字段/行为包括：

- `toc_offset`
- `manual_toc_ready`
- `pipeline_state`
- `visual_toc_bundle`
- Phase1 `manual_page_overrides: None`
- Phase1 `endnotes_start_page: None`
- Phase1/2/3 `skip_llm_verify: true`
- Phase2 `skip_sup_recovery: true`

问题：

- 调用方传入配置但没有效果。
- Rust pipeline 与 Python pipeline 的实际行为会分叉。
- `skip_sup_recovery=true` 会让需要 superscript recovery 的书直接损失捕获能力。

建议：

- 未实现的配置要么删除，要么遇到非默认值时报错。
- `skip_*` 应由 config 控制，不应在 orchestrator 固定关闭关键能力。

### 3. Phase4 输入使用 Phase3 重建结构中的 note_regions

位置：`src/pipeline.rs`

`run_phase4()` 传入：

```rust
note_regions: &phase3.structure.note_regions
```

Phase3 审计中已经确认 `Phase3Structure` 有重建 Phase1/2 事实的风险。Orchestrator 应优先透传 Phase2 权威 note_regions，而不是从 Phase3 structure 再取一次。

建议：

- `run_phase4()` 显式接收 Phase2Snapshot 或 Phase2 note_regions。
- Phase3 只提供 body anchors / note links / link table。

### 4. `generate_run_id()` 秒级粒度可能碰撞

位置：`src/pipeline.rs`

run id 由 `doc_id + 当前秒` hash 得到。同一 doc 在同一秒启动两次会得到相同 run id。

建议使用 UUID、纳秒时间、或 DB run id 作为 pipeline_run_id。

### 5. `page_translate` 用 JSON error 替代 `Result`

位置：`src/page_translate.rs`

`apply_body_unit_translations()` 和 `apply_body_unit_entry_result()` 遇到段落数不一致时返回：

```json
{"error": "..."}
```

而不是 `Result::Err`。

问题：

- Rust 类型层无法强制调用方处理错误。
- Python binding 只是序列化 JSON，调用方漏判时会把错误对象当正常结果继续写入。

建议：

- 内部函数改为 `Result<Value, anyhow::Error>`。
- Python binding 再决定是否转成异常或结构化错误。

## P3：工程质量问题

### 1. `page_translate.rs` 过大

当前行数：

- `page_translate.rs`：1387 行
- `mainline.rs`：485 行
- `pipeline.rs`：336 行
- `post_translate.rs`：272 行
- `types.rs`：196 行
- `load.rs`：107 行
- `error.rs`：35 行

`page_translate.rs` 混合了：

- unit label/page formatting
- retry summary
- diagnostic entries
- page job construction
- body unit job construction
- translation result application
- tests

建议拆成 `progress.rs`、`jobs.rs`、`apply.rs`、`diagnostics.rs`。

### 2. 测试覆盖偏浅

当前没有独立 `tests/` 目录。`cargo test -p fnm-orchestrator` 只有 21 个 crate 内测试，主要是：

- 最小 DB pipeline smoke test。
- page translate 小函数测试。

缺少：

- `start_phase` 续跑测试。
- LLM repair 后本轮 Phase4 输入变化测试。
- diagnostic pages/notes 落库测试。
- post-translate repair 后重新导出测试。
- 真实 fixture / Python parity。

### 3. clippy 本体仍有 19 个错误

放宽前序 crate 已知 lint 后，`fnm-orchestrator` 本体仍有 19 个 clippy 错误，主要是：

- `load.rs` 16 处 `useless_conversion`
- `page_translate.rs` 1 处 `implicit_saturating_sub`
- `post_translate.rs` 2 处 `iter_cloned_collect`
- `page_translate.rs` 测试中 `manual_str_repeat` / `manual_repeat_n`

这些多为机械问题，但按 PR checklist 仍不能合入。

## 验证记录

在 `/Users/hao/OCRandTranslation/fnm_re_rs` 执行：

```bash
cargo build --release -p fnm-orchestrator
cargo fmt --check -p fnm-orchestrator
cargo test -p fnm-orchestrator
cargo clippy -p fnm-orchestrator --all-targets -- -D warnings
```

结果：

- `cargo build --release -p fnm-orchestrator`：通过，但继承 `fnm-phase2` 的 4 个 warning 和 `fnm-llm-repair` 的 1 个 warning。
- `cargo fmt --check -p fnm-orchestrator`：通过。
- `cargo test -p fnm-orchestrator`：通过，21 个测试，0 ignored。
- `cargo clippy -p fnm-orchestrator --all-targets -- -D warnings`：先被 `fnm-core` 已知 12 个 clippy 错误阻断。
- 放宽前序 crate 已知 lint 后，`fnm-orchestrator` 本体仍有 19 个 clippy 错误。
- 继续放宽本体这 19 个 lint 后，clippy 通过。

## 建议修复顺序

1. 实现或禁用 `start_phase` 续跑语义，避免误覆盖前序产物。
2. 修正 LLM repair 接线：repair 后从 Phase3 起重新 materialize 并跑 Phase4-6。
3. 改 Phase5 输出/持久化，让 diagnostic pages/notes 能落库。
4. 修 `load_phase6_structure()`，缺失 export/audit/status 时不要默认补空。
5. 把 `page_translate` 的 JSON 软错误改为 `Result`，再拆分大文件。
6. 补 start_phase、repair、diagnostic、post-translate 的集成测试。
