# fnm-py 审计记录

审计时间：2026-05-22

审计范围：

- `fnm-py/src/lib.rs`
- `fnm-py/Cargo.toml`
- `fnm-py/pyproject.toml`
- `fnm-py/smoke_test.py`
- `fnm-py/tests/*.py`
- Python 调用入口参考：`/Users/hao/OCRandTranslation/FNM_RE/__init__.py`

## 结论

`fnm-py` 是一个薄 PyO3 绑定层，但现在已经承载了太多策略：pipeline 入口、DB 入口、LLM repair、导出审计、翻译任务、sup recovery、PDF render、token trace 都集中在单个 `lib.rs` 中。

最主要问题不是绑定能不能调用，而是 Python API 暴露了若干“看似支持”的能力，底层实际没有闭合：`start_phase`、diagnostic entries、LLM repair 后重导出、doc status、sup recovery chapter scope 都存在分叉或弱化。测试数量不少，但多是 shape/smoke 测试，很多会在结果为空时直接跳过关键断言。

## P1：必须优先修复

### 1. `run_llm_repair_json()` 用 `expect()`，会把可恢复错误变成 panic

位置：`src/lib.rs`

`run_llm_repair_json()` 在释放 GIL 后创建 runtime 并运行 repair：

```rust
.build().expect("tokio runtime");
runtime.block_on(run_llm_repair(params)).expect("llm repair")
```

问题：

- DB 缺表、LLM 请求失败、schema 错误等都可能触发 `Err`。
- 这些错误应该返回 `PyRuntimeError`，而不是 panic。
- panic 进入 PyO3 边界后调用方难以稳定捕获，也不利于批处理继续跑下一本书。

建议：

- 把闭包返回类型改成 `Result<LlmRepairReport, anyhow::Error>`。
- `tokio runtime` 和 `run_llm_repair` 的错误都用 `map_err(PyRuntimeError::new_err)` 转换。
- 加测试：人为破坏 DB schema 或传不存在 doc_id，应抛 Python exception，不应 panic。

### 2. 高层 `run_doc_pipeline_json()` 丢失关键配置

位置：`src/lib.rs`、`/Users/hao/OCRandTranslation/FNM_RE/__init__.py`

`run_doc_pipeline_json()` 只暴露：

- `db_path`
- `doc_id`
- `max_body_chars`
- `start_phase`

然后内部硬编码：

```rust
slug: doc_id
pdf_path: ""
toc_offset: 0
include_diagnostic_entries: false
manual_toc_ready: false
pipeline_state: "done"
review_overrides: None
visual_toc_bundle: None
```

Python 的 `FNM_RE.run_doc_pipeline()` 正是调用这个入口。也就是说常用高层入口无法传入真实 PDF path、visual TOC bundle、manual TOC 状态、review overrides、diagnostic 需求。

问题：

- 高层入口与 Python pipeline 同名能力不对齐。
- real batch 如果走这个入口，会天然丢 visual/diagnostic/review 信息。
- `start_phase` 也被暴露给 Python，但 orchestrator 审计已确认底层没有实际续跑语义。

建议：

- `run_doc_pipeline_json()` 改为接收完整 `config_json`，或扩展签名覆盖全部关键字段。
- 未支持的字段遇到非默认值时直接报错，不要静默丢弃。
- 在 Python `FNM_RE.run_doc_pipeline()` 中同步暴露这些参数。

### 3. `build_doc_status_json()` 基于默认 status，状态报告不可信

位置：`src/lib.rs`

`build_doc_status_json()` 调用 `fnm_orchestrator::load_phase6_structure()`，然后读取：

```rust
let s = &phase6.status;
let summary = &phase6.summary;
```

但 orchestrator loader 当前会把 `status` 和 `summary` 构造成 default。结果是 Python 侧拿到的 doc status 多数字段来自默认值，而不是真实 Phase6 audit / persisted status。

问题：

- UI/批处理可能看到 `structure_state`、`blocking_reasons`、`page_count` 等默认值。
- 测试只检查字段存在，不检查它们是否和 pipeline 结果一致。
- 这会掩盖 blocker，尤其是导出 audit 已经发现的问题。

建议：

- status 应从真实 `export_audit`、`fnm_runs`、各 phase summary 汇总，不应读 default。
- `build_doc_status_json()` 应增加一致性测试：`pipeline_result.structure_state` 与 `build_doc_status.structure_state` 必须一致。

### 4. `recover_book_json()` 丢失 chapter scope

位置：`src/lib.rs`

该函数名义上调用：

```rust
recover_book_chapter_scoped(...)
```

但它把所有页面的 fnBlocks marker 都放入同一个 `"auto"` chapter：

```rust
markers.entry("auto".to_string()).or_default().insert(marker);
```

并且 marker 排序是字符串排序。

问题：

- 章节边界完全丢失，和 “chapter scoped” 的语义不一致。
- 不同章节重复 marker 会被合并。
- `"10"` 会排在 `"2"` 前，影响序列推断。

建议：

- Python binding 必须接收章节边界或 Phase1/Phase2 产生的 chapter marker map。
- 如果没有 chapter scope 输入，应显式报错或改名为非 chapter scoped 的弱工具。

### 5. Python renderer callback 错误被静默吞掉

位置：`src/lib.rs`

`PyRepairRenderer::render_page_data_url()` 对 Python callback 的调用是：

```rust
let result = self.callback.call1(py, args).ok()?;
result.extract::<Option<String>>(py).ok().flatten()
```

问题：

- callback 抛异常、返回类型错误、渲染失败，都会静默变成 `None`。
- LLM repair 会在没有图像上下文的情况下继续跑，质量下降但调用方不知道。
- 这类错误应该进入 repair report 或直接失败。

建议：

- renderer 错误应至少记录到 report 的 model_attempt/request_metrics。
- 对用户传入 renderer 的场景，callback exception 应返回 `PyRuntimeError`。

## P2：需要修复的质量问题

### 1. `run_post_translate_export_checks_for_doc_json()` 直接 SQL 读取 pages

位置：`src/lib.rs`

该函数不使用 `Repository::load_raw_pages_for_doc()`，而是内联：

```sql
SELECT payload_json FROM pages WHERE doc_id = ?1 ORDER BY book_page ASC
```

问题：

- 绕开了 core repository 中对 pages schema 的兼容读取逻辑。
- 如果 `payload_json` 为空但 `markdown/footnotes` 列有数据，会解析失败。
- 绑定层重复理解 DB schema，后续 migration 容易分叉。

建议统一调用 repository API。

### 2. `apply_body_unit_*` 错误仍作为 JSON 返回

位置：`src/lib.rs`、`fnm-orchestrator/src/page_translate.rs`

`apply_body_unit_translations_json()` / `apply_body_unit_entry_result_json()` 直接序列化 orchestrator 返回的 `Value`。段落数不一致时返回：

```json
{"error": "..."}
```

问题：

- Python 调用方必须手动检查 `"error"`。
- 这类结构错误应是异常或 typed result，不应伪装成正常 JSON。

建议底层改 `Result`，PyO3 层转 `PyRuntimeError`。

### 3. diagnostic 测试没有证明 diagnostic 真的生成

位置：`tests/test_diagnostic_entries.py`、`tests/test_diagnostic_notes.py`

这些测试传入 `include_diagnostic_entries=True`，但断言是：

```python
assert isinstance(entries, list)
if len(entries) > 0:
    ...
```

问题：

- orchestrator 当前 Phase5 diagnostic 落库为空，这些测试仍会通过。
- 这导致 P1 diagnostic 丢失问题没有被测试发现。

建议：

- 对含 diagnostic fixture 的输入断言 `len(entries) > 0`。
- 同时测试 page translate jobs 中 note jobs 存在。

### 4. `audit_export_for_doc_json()` 对不存在 zip_path 静默降级

位置：`src/lib.rs`

如果用户传入 `zip_path` 但路径不存在，函数不会报错，而是把 payload 设为 `None`，改为只审计 DB structure。

问题：

- 用户明确要求审计某个 ZIP，路径错误却得到另一个审计结果。
- 这会误导导出验证。

建议：非空 `zip_path` 不存在时直接抛 `PyRuntimeError`。

### 5. wrapper 中存在无效参数

位置：`src/lib.rs`

- `prepare_page_translate_jobs_json()` 接收 `t_args_json` 但完全不解析。
- `rebuild_fnm_diagnostic_page_entries_json()` 解析 `pages_json` 后完全不用。
- `build_doc_status_json()` 接收 `_start_phase` 但完全不用。

这些参数如果是 Python 兼容层要求保留，应在文档中标明“暂不支持且不影响结果”；否则应删除或接线。

## P3：工程质量问题

### 1. 单文件过大

当前行数：

- `src/lib.rs`：1246 行
- `tests/*.py`：1952 行
- `smoke_test.py`：149 行

`lib.rs` 混合了至少 9 类接口：

- pipeline
- DB loader
- export bundle/zip/audit
- diagnostics
- LLM repair
- doc status
- page translate
- sup recovery
- PDF render / trace / helper utilities

建议拆成：

- `pipeline.rs`
- `repair.rs`
- `export.rs`
- `diagnostics.rs`
- `page_translate.rs`
- `status.rs`
- `utils.rs`

### 2. 重复打开 DB pool

几乎每个 pyfunction 都手写：

```rust
let pool = open_pool(Path::new(db_path))?;
let repo = SqliteRepository::new(pool);
```

建议抽一个 `with_repo(db_path, |repo| ...)` helper，统一错误格式，减少重复。

### 3. 测试偏 smoke，缺少行为对齐断言

当前 Python 测试数量不少，但缺少以下关键断言：

- `start_phase != "toc"` 不应重跑 Phase1/2。
- `run_pipeline_for_doc_with_llm_repair_json(auto_apply=True)` 的本轮导出应受 repair 影响。
- `build_doc_status_json()` 与最新 run/export audit 一致。
- diagnostic entries 在 `include_diagnostic_entries=True` 时非空。
- renderer callback 抛错能被报告。
- `run_llm_repair_json()` 底层错误不会 panic。
- `recover_book_json()` 对重复 marker 的多章输入不混章。

## 验证记录

在 `/Users/hao/OCRandTranslation/fnm_re_rs` 执行：

```bash
cargo build --release -p fnm-py
cargo fmt --check -p fnm-py
cargo test -p fnm-py
cargo clippy -p fnm-py --all-targets -- -D warnings
```

结果：

- `cargo build --release -p fnm-py`：通过，但继承 `fnm-phase2` 的 4 个 warning 和 `fnm-llm-repair` 的 1 个 warning。
- `cargo fmt --check -p fnm-py`：通过。
- `cargo test -p fnm-py`：通过，但实际 0 个 Rust 测试，0 个 doc tests。
- `cargo clippy -p fnm-py --all-targets -- -D warnings`：先被 `fnm-core` 已知 12 个 clippy 错误阻断。
- 放宽前序 crate 和 orchestrator 已知 lint 后，`fnm-py` clippy 通过。

Python 测试：

```bash
.venv/bin/python -m pytest fnm_re_rs/fnm-py/tests -q
```

结果：

- 78 passed。
- 使用的 Python 模块位置：`/Users/hao/OCRandTranslation/.venv/lib/python3.14/site-packages/fnm_re_rs/__init__.py`。

## 建议修复顺序

1. 去掉 `run_llm_repair_json()` 的 `expect()`，所有错误转 Python exception。
2. 扩展或替换 `run_doc_pipeline_json()`，不要丢关键 config。
3. 修正 `build_doc_status_json()` 的数据来源，避免读 default status。
4. 修 `recover_book_json()` 的 chapter scope 输入。
5. 把 renderer callback 错误显式返回。
6. 把 JSON 软错误改为 `Result`/Python exception。
7. 拆分 `src/lib.rs`，补行为型 Python 测试。
