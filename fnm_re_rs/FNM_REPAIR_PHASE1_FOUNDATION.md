# 阶段 1 修复文档：基础设施与可复现性

创建时间：2026-05-22

本文是第一阶段的执行说明。接手人只读本文，应能知道为什么先修基础设施、要改哪些文件、每个文件怎么改、怎么验证。

> 2026-05-25 状态覆盖：当前执行以 `FNM_REPAIR_PROGRAM_CONTRACT_PLAN.md` 为准。本文保留阶段 1 的历史任务与证据，不表示当前工作区已经重新验收；在用户重新授权前不进行真实批跑或模型请求。

## 阶段目标

先让 FNM Rust pipeline 的入口、DB contract、LLM 错误、trace、批测脚本稳定可信。

本阶段不解决 `endnote_region_marker_misalignment` 本身；那个是阶段 2 的 Phase2 业务修复。但如果本阶段不先做，后续会出现这些问题：

- 批测读写错 DB，导致结果不是当前文档的真实结果。
- app `documents` 表 schema 与 Rust Repository 预期不一致，pipeline 启动即失败。
- LLM 400/429 变成 PyO3 panic，脚本无法稳定捕获。
- LLM trace 缺失，无法判断 provider 错误还是业务错误。
- `load_phase6_structure()` 用默认空 status 掩盖真实 blocker。
- `start_phase`、post-translate repair 等公开能力看起来可用，实际没有完整接线。

## 本阶段输入证据

### Biopolitics 实测

产物目录：

`/Users/hao/OCRandTranslation/output/fnm_real_batch/biopolitics_gemini31_full_20260522_rerun3/phase_artifacts/Biopolitics`

关键文件：

- `summary.json`
- `final/final_structure_status.json`
- `final/final_export_verify.json`
- `post_resume_report.md`
- `final_effective_token_summary.json`
- `batch_llm_traces/`
- `resume_llm_repair_traces/`

实测发现：

- document DB path 必须是 `/Users/hao/OCRandTranslation/local_data/user_data/data/documents/0d285c0800db/doc.db`。
- 不传 DB path 时，部分 Rust/Python 入口会回落到错误默认库。
- Gemini 400 的原始原因是请求里带了 Qwen 专用字段 `extra_body.enable_thinking`。
- LLM repair 曾因 PyO3 `expect()` 变成 panic。
- repair 请求遇到 Gemini 限流时，批测需要 trace 和 partial 状态来判断是否可以 resume。

### 审计文件

本阶段主要读：

- `FNM_CORE_AUDIT.md`
- `FNM_PY_AUDIT.md`
- `FNM_ORCHESTRATOR_AUDIT.md`
- `FNM_LLM_REPAIR_AUDIT.md`
- `FNM_AUDIT_SUMMARY.md`

## 文件级修复计划

### 1. `fnm-core/src/db/repository.rs`

问题：

- Repository API 与 app 当前 `documents` 表 schema 不闭合。
- 旧路径假设存在 `documents(id, slug, state)`。
- app doc DB 中实际常见字段是 `id, name, created_at, updated_at` 等。
- 如果这里失败，整条 pipeline 还没进入 Phase1 就会中断。

要做：

1. 明确 Repository 支持的 `documents` 表 contract。
2. 如果 Rust workspace 应负责建表，则 migration 必须创建 Repository 需要的字段。
3. 如果 Rust workspace 要读 app doc DB，则 Repository 必须 schema-aware：
   - 已存在文档时，不要求 `slug` 字段一定存在。
   - 插入新文档时，根据实际 schema 写 `slug` 或 `name`。
   - 不允许静默写入失败。
4. 把当前临时 schema bridge 整理成正式 helper，例如：
   - `documents_columns(&Connection) -> HashSet<String>`
   - `document_exists(&Connection, doc_id: &str) -> Result<bool>`
   - `insert_document_for_schema(...)`
5. 加测试覆盖两种 schema：
   - Rust legacy schema：`id, slug, state`
   - app schema：`id, name, created_at, updated_at`

验收：

- 用 Biopolitics doc DB 跑 `run_doc_pipeline` 不再因 `documents.slug/state` 缺失失败。
- 测试能证明两种 schema 都可插入/更新。
- 出错时返回 `Result`，不吞错。

### 2. `fnm-core/src/db/migrations.rs` 或实际 migration 模块

问题：

- `FNM_CORE_AUDIT.md` 指出 SQLite migration 与 Repository API 不闭合。
- 如果 migration 建出来的库和 Repository 读写假设不一致，测试库通过不了真实 app DB。

要做：

1. 找到实际 migration 定义位置。
2. 对照 `repository.rs` 所有 public DB 写入/读取路径，列出表字段矩阵。
3. 让 migration 与 Repository contract 一致。
4. 如果 app DB schema 与 Rust internal schema 不同，文档里明确：
   - 哪些表是 app 原生表。
   - 哪些表是 FNM Rust 管理表。
   - app 原生表不得由 Rust 随意改结构。

验收：

- 新建空库后，Repository 所有基础方法能通过。
- 真实 app doc DB 不需要 destructive migration。

### 3. `fnm-core/src/records.rs`、`fnm-core/src/types.rs`

问题：

- 审计指出 `NoteLinkRecord::default()` 默认为 `Matched + Footnote`。
- 非法/缺失 `note_kind` 读回时可能 fallback 到 `Footnote`。
- 这违反“分类源头唯一”：坏数据会被伪装成合法 footnote。

要做：

1. 检查所有 `Default` impl：
   - `NoteLinkRecord`
   - `NoteItemRecord`
   - `BodyAnchorRecord`
   - 与 status/kind 有关的 record。
2. 对状态型字段，默认值只能是显式 unknown/review/empty，不得是业务成功态。
3. DB 读回非法 `note_kind` 时返回错误，或保留 `Unknown` 并形成 blocker；不能 fallback 到 `Footnote`。
4. 加测试：
   - 非法 `note_kind='bad_kind'` 读回应失败或进入 unknown，不得变 footnote。
   - default link 不得是 matched。

验收：

- 坏数据不会被静默改成 footnote/matched。
- 下游测试需要显式处理 unknown/review。

### 4. `fnm-core/src/segment_codec.rs`

问题：

- 审计指出 paragraphs 为空时可能丢顶层正文。
- 这会污染 Phase4/5 翻译单元与正文引用冻结。

要做：

1. 找到 encode/decode segment 的入口。
2. 构造真实或最小 fixture：
   - 顶层 text 有内容。
   - paragraphs 为空。
3. 断言 round-trip 后正文不丢。
4. 修实现，使顶层正文与 paragraphs 两种形态都保留。

验收：

- round-trip byte-equal 或语义等价。
- Phase4 units 不再因为 segment codec 丢 text。

### 5. `fnm-core/src/ref_rewriter.rs`

问题：

- `replace_frozen_refs` 的 `endnote_mode` 参数无效。
- 如果不同 mode 本该影响 `[1]` / `[^1]` / local label 输出，现在会造成导出 contract 分叉。

要做：

1. 查 Python 对照行为。
2. 如果 Python 确实区分 endnote mode，则 Rust 实现对应分支。
3. 如果 Python 不区分，则删除参数或在 doc comment 明确无效，避免调用方误解。
4. 增加 mode 差异测试。

验收：

- 参数要么有行为，要么不存在。
- Phase6 diagnostics 不再依赖一个假参数。

### 6. `fnm-core/src/vision/spec.rs`

问题：

- Biopolitics 实测中 Gemini 400 的原因是 custom provider 继承了 Qwen builtin request override。
- Gemini 收到 `extra_body.enable_thinking` 后返回 HTTP 400。

要做：

1. 自定义 provider 不能默认继承 Qwen spec。
2. 只有明确支持的 builtin provider 可以继承 builtin request override：
   - `qwen`
   - `qwen_mt`
   - `deepseek`
   - `glm`
   - `kimi`
   - `mimo`
   - `mimo_token_plan`
3. 为 Gemini custom slot 加单测：
   - provider=`gemini`
   - model_id=`gemini-3.1-flash-lite`
   - request_overrides 必须为 `None` 或不含 `enable_thinking`。
4. 为 Qwen custom slot 加回归：
   - Qwen 仍按既有逻辑带对应 override。

验收：

- Gemini request trace 中不再出现 `enable_thinking`。
- Qwen 行为不退化。

### 7. `fnm-py/src/lib.rs`

问题：

- `run_llm_repair_json()` 曾用 `expect("tokio runtime")` 和 `expect("llm repair")`。
- LLM provider 错误会越过 Python 批测错误处理，变成 PyO3 panic。
- `run_doc_pipeline_json()` 丢失大量 config。
- `fnm-py` 单文件过大，但本阶段先修稳定性，不做大拆分。

要做：

1. 移除 LLM repair 路径上的 `expect()`：
   - tokio runtime 创建失败返回 `PyRuntimeError`。
   - `run_llm_repair` 返回错误时返回 `PyRuntimeError`。
2. `run_llm_repair_json()` 接收并透传 `trace_callback`。
3. Python callback 报错不能让 Rust panic；但 trace 写入失败要可观测，至少在 returned report 中计数或记录 warning。
4. 梳理 `run_doc_pipeline_json()` 参数：
   - `pdf_path`
   - visual/manual TOC 输入
   - review overrides
   - diagnostic 开关
   - repair 开关
   - db_path
5. 对暂不支持的参数，不要静默忽略；返回 unsupported 或写入明确 warning。

验收：

- 人为配置坏 LLM endpoint 时，Python 捕获普通 exception，不是 panic。
- trace callback 能收到 started/success/failed。
- 高层 Python 入口传入的关键 config 能到 Rust。

### 8. `FNM_RE/__init__.py`

问题：

- Python wrapper 曾接受 `trace_callback` 但没有传给 Rust。
- `_resolve_db_path` 的使用必须在所有高层入口一致。

要做：

1. `run_llm_repair()` 将 `trace_callback` 传给 `fnm_re_rs.run_llm_repair_json()`。
2. 检查所有调用 Rust wrapper 的函数：
   - 必须显式传 document DB path，或清楚调用 `_resolve_db_path`。
   - 不得无意回落到 `/data/fnm/fnm_books.db` 这类默认路径。
3. 对每个 wrapper 增加最小 Python 测试：
   - 传入 doc DB path。
   - wrapper 传参到 Rust。

验收：

- Biopolitics 批测所有 Rust 入口都读写 doc DB。
- trace_callback 生效。

### 9. `fnm-llm-repair/src/llm_client/request.rs`

问题：

- provider 非 2xx 时，如果只抽 `error.message`，容易丢掉原始错误。
- 实测 Gemini 400 需要完整 body 才能看见 `enable_thinking` 字段问题。

要做：

1. 非 2xx 响应保留 raw body fallback。
2. trace 中保存：
   - HTTP status
   - provider error body
   - request model/provider
   - request stage
   - token 估算或 usage
3. 对 400、429、5xx 分类：
   - 400：配置/请求错误，不应自动无限重试。
   - 429：限流，可 resume/retry。
   - 5xx：provider 临时错误，可 retry。

验收：

- `/tmp/biopolitics_llmrepair_400_probe3` 中那类错误能在 trace 中看到原始 provider message。
- 429 报告为 rate limit，不和 400 混淆。

### 10. `fnm-llm-repair/src/llm_client/error.rs`

问题：

- provider error 结构不同，当前抽取字段过窄。

要做：

1. `extract_provider_error_detail()` 支持：
   - `error.message`
   - `error.status`
   - `error.code` 为 string 或 number
   - 无 message 时序列化整个 `error` object
2. 加单测覆盖 Gemini 格式：
   - `code: 400`
   - `status: INVALID_ARGUMENT`
   - `details: google.rpc.BadRequest`
3. 加单测覆盖普通 OpenAI-compatible 格式。

验收：

- 错误摘要足够定位请求字段问题。

### 11. `fnm-orchestrator/src/mainline.rs`

问题：

- `start_phase` 只进 metadata，没有真实续跑语义。
- LLM repair auto-apply 后，本轮 Phase4/5/6 可能仍消费 repair 前的内存结构。
- `fnm_run finalize` 错误可能被 `let _ = ...` 忽略。

要做：

1. 本阶段先做安全处理：
   - 如果 `start_phase != toc` 且未实现真实续跑，直接返回 unsupported error。
   - 不允许调用方以为续跑成功。
2. `update_fnm_run` 等关键结果不得 `let _ = ...`。
3. 明确 run metadata：
   - db path
   - doc id
   - input asset hash
   - model id
   - repair enabled
   - trace dir
4. 为后续阶段预留 repair 后 rerun hook，但本阶段不必完成完整 Phase3-6 重跑。

验收：

- `start_phase=FrozenUnits` 之类调用不会静默从 Phase1 重跑并覆盖前序产物。
- run finalize 失败会返回错误。

### 12. `fnm-orchestrator/src/pipeline.rs`

问题：

- Pipeline 配置字段未完全接线。
- Phase5 diagnostic pages/notes 写空是 Orchestrator 层的可观测性问题。
- loader 默认补空 Phase6 status 会掩盖真实缺失。

要做：

1. 梳理 `PipelineConfig` 每个字段：
   - 已支持：接线并测试。
   - 不支持：返回 unsupported 或记录 hard warning。
2. Phase5 diagnostic products 必须从 Phase5 输出带出并持久化。
3. `load_phase6_structure()` 缺 bundle/status/audit 时返回 incomplete 状态或错误；不能构造 default status 并清空 blocker。
4. 加测试：
   - 缺 Phase6 audit 时，状态不是成功空对象。
   - diagnostic entries 非空时能落库。

验收：

- 状态接口不会把缺失产物报告成成功。
- diagnostic 数据能用于 page translate jobs。

### 13. `scripts/test_fnm_batch.py`

问题：

- 部分 verify/materialize/export helper 曾不传 doc DB path，导致 Rust wrapper 回落默认库。
- 占位翻译阶段曾因 DB path 问题失败。

要做：

1. 所有 Rust wrapper 调用都显式传 `db_path=str(get_document_db_path(doc_id))`。
2. `verify_fnm_structure()`、`materialize_test_placeholders()`、`verify_export()` 参数保留 `db_path`。
3. 对输出报告写入：
   - doc DB path
   - batch tag
   - phase artifact dir
   - final blocking reasons
4. 如果 helper 收到空 db_path，应在日志中记录 resolved path。

验收：

- 占位翻译能稳定完成。
- 报告能追踪每一步用的是哪个 DB。

### 14. `scripts/test_fnm_real_batch.py`

问题：

- 真实批测同时涉及 reingest、visual TOC、LLM repair、placeholder translation、export verify；任何一步 trace 缺失都会影响交接判断。

要做：

1. 对每个阶段写 phase artifact：
   - Phase0 input asset manifest
   - Phase1 pages/chapters/headings
   - Phase2 regions/items/modes
   - Phase3 anchors/links/overrides
   - Phase4 translation units/reviews
   - Phase5 markdown/diagnostics
   - Phase6 export bundle/audit
   - final structure/export status
2. LLM trace 复制到 artifact dir，不只留在 `test_example/.../llm_traces`。
3. token summary 区分：
   - 本轮有效 token
   - 包含失败/重试的 observed token
4. 失败也要落 `runtime_status.json`、`results.json`、`batch_report.md`。

验收：

- 即使 LLM repair 429 中断，也能从 artifact dir 看见已完成阶段和失败 trace。
- resume 后能写 `post_resume_report.md` 或等价报告。

## 本阶段必须新增的测试

最少测试集：

1. `fnm-core` repository schema 测试：
   - legacy `documents(id, slug, state)`
   - app `documents(id, name, created_at, updated_at)`
2. `fnm-core` bad enum 测试：
   - 非法 `note_kind` 不得 fallback 到 footnote。
3. `fnm-core` segment round-trip 测试：
   - paragraphs 为空时顶层正文不丢。
4. `fnm-core` custom Gemini spec 测试：
   - `gemini-3.1-flash-lite` 不含 `enable_thinking`。
5. `fnm-py` LLM repair error 测试：
   - provider error 返回 Python exception，不 panic。
6. `fnm-llm-repair` error extraction 测试：
   - Gemini 400 body 能抽出 `INVALID_ARGUMENT` 和 unknown field 信息。
7. `scripts` smoke：
   - Biopolitics placeholder materialize 使用 doc DB path。

## 本阶段验证命令

优先执行：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo fmt --check -p fnm-core
cargo clippy -p fnm-core --all-targets -- -D warnings
cargo test -p fnm-core
cargo test -p fnm-llm-repair
```

重建 PyO3：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs/fnm-py
../../.venv/bin/python -m maturin develop
```

注意：`maturin develop` 要从 `fnm_re_rs/fnm-py` 目录运行，这样会使用 `fnm_re_rs/.cargo/config.toml`。从仓库根目录运行可能会因为 PyO3 link args 不对而失败。

Python 编译检查：

```bash
cd /Users/hao/OCRandTranslation
.venv/bin/python -m py_compile FNM_RE/__init__.py scripts/test_fnm_batch.py scripts/test_fnm_real_batch.py
```

Biopolitics smoke：

```bash
cd /Users/hao/OCRandTranslation
.venv/bin/python scripts/test_fnm_real_batch.py --slug Biopolitics --group all --include-all --batch-tag phase1_foundation_smoke --verbose
```

阶段 1 不要求最终导出通过，因为 Phase2 blocker 仍在。阶段 1 只要求失败可复现、可追踪、不会 panic、不会读错 DB。

## 阶段完成判定

满足以下条件才进入阶段 2：

- Gemini custom provider 不再带 Qwen `enable_thinking`。
- LLM 400/429 都有明确 trace。
- PyO3 边界无 repair panic。
- 所有批测 helper 都使用 document DB path。
- `documents` schema/API 闭合，有测试覆盖。
- `load_phase6_structure()` 不再用默认空 status 掩盖缺失产物。
- Biopolitics 全量批测能稳定产出 phase artifacts；最终可以仍 blocked，但 blocker 必须是业务 blocker，例如 `endnote_region_marker_misalignment`。

## 交接提醒

本阶段修完后，不要直接在 Phase3/4/6 绕过 Biopolitics blocker。下一阶段必须进入 Phase2，修 note item 捕获边界，让 `endnote_region_marker_misalignment` 在源头消失。
