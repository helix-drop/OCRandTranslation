# 当前进度

本文件只记录**当前口径**、最近实测和下一步工作，不再堆叠历史阶段记录。

## 2026-04-21 Visual TOC 语义型 depth 迁移已落地（最新）

### 当前状态

- `Visual TOC` 现在已经按语义型 depth 解释并落盘：
  - `depth=0`：`chapter / front_matter / back_matter / post_body`
  - `depth=1`：`container / endnotes`
  - `depth=2+`：`section`
- `role_hint=endnotes` 已从 sidecar/提示链升级成 staged 与 module 共用的一等角色，不再在 TOC 树里折叠成 `post_body`。
- `Phase1` 的 `_visual_toc_level()` 已切到语义映射；`endnotes` 与其子项不会进入正文章节树，也不会参与 chapter anchor 决策。
- 快照与运行时 sidecar 已统一：
  - `Goldstein`：`Notes=endnotes, depth=1, parent_title=""`
  - `Biopolitics`：`INDICES=container, depth=1`，其下 `Index des notions / Index des noms de personnes=back_matter`
- `endnotes_summary` 现在会按最终 `items` 回填；即使 prompt 端漏判，只要最终结构已纠正，顶层摘要也会同步正确。

### 最近自测

- `python3 -m unittest tests.unit.test_visual_toc tests.unit.test_fnm_re_phase1 tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_batch_report tests.unit.test_fnm_real_batch_report tests.unit.test_generate_visual_toc_snapshots tests.unit.test_reingest_fnm_from_snapshots tests.unit.test_endnote_chapter_explorer tests.unit.test_fnm_re_phase2 tests.unit.test_fnm_re_module3_split tests.unit.test_fnm_re_pipeline_snapshot tests.unit.test_fnm_re_mainline_snapshot_reuse`
  - `Ran 126 tests, OK`
- 定向快照重刷已确认：
  - `Goldstein` 的 `auto_visual_toc.json` 已包含 `endnotes_summary.present=true`
  - `Biopolitics` 的 `auto_visual_toc.json` 已包含 `INDICES=container`
- 真实主链抽样：
  - `Biopolitics`：批跑中已到 `state=ready`
  - `Germany_Madness`：单书实跑已到 `FNM 重建完成：state=ready`

### 下一步

1. 继续做 8 本整批实跑验收，重点对比 `Goldstein / Napoleon / Heidegger / Neuropsychoanalysis_Introduction`。
2. 若批跑仍出现“长时间无日志但非失败”的情况，单独收口 `scripts/test_fnm_real_batch.py` 的过程输出与收尾落盘阶段。

## 2026-04-20 尾注章节探索模块已落地（最新）

### 当前状态

- 已新增 `FNM_RE/stages/endnote_chapter_explorer.py`，专门处理“书末尾注区按章探索并回绑 chapter”的逻辑。
- 当前尾注 rebind 不再只靠“Notes 页位置 + 邻近章节”弱规则，已经接入两类明确信号：
  - 目录/章节标题文字匹配（以 phase1 产出的 chapter 标题为锚）
  - 尾注页内的小标题与 heading candidate 的版式强信号（`section_title`、`top_band`、`font_weight_hint`、`align_hint`、`heading_level_hint`）
- `FNM_RE/stages/note_regions.py` 已切到这条 explorer 链路；`note_region_summary` 会显式输出：
  - `endnote_explorer_split_count`
  - `endnote_explorer_rebind_count`
  - `endnote_explorer_page_signal_count`
  - `endnote_explorer_signal_titles_preview`

### 最近实测

- `python3 -m unittest tests.unit.test_fnm_re_phase2 tests.unit.test_endnote_chapter_explorer tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_module4_linking tests.unit.test_fnm_re_module5_freeze tests.unit.test_fnm_re_module2_book_type tests.unit.test_note_detection`
  - `Ran 71 tests, OK`
- 新增覆盖：
  - 尾注 `section_title` 可直接把 book-scope endnote region 拆回对应章节
  - heading candidate 的字体/版式强信号可参与尾注章节回绑

### 下一步

1. 在 `Goldstein` 一类全书尾注书上做真实样本回归，观察 explorer 是否能显著减少“全部挂到最后一章”的情况。
2. 若真实书仍有大块未拆开的尾注区，再补“多页连续 section 继承”和更细的章节标题匹配策略。

## 2026-04-20 发布前收尾完成（最新）

### 当前状态

- 已完成发布前收尾三项：
  - 文档同步（`PLANG.md`、`PROGRESS.md`、`verification.md`）
  - 最终验收记录固化（核心回归 + 8 本样本状态）
  - 收尾清单固化（发布边界、观察项、非阻塞噪音）
- 当前主结论：
  - 核心回归入口通过：`96 tests OK`
  - 8 本样本 `build_doc_status()` 全部满足：
    - `structure_state=ready`
    - `blocking_reasons=[]`
    - `export_ready_test/export_ready_real=true`

### 最近实测

- `python3 -m unittest tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type tests.unit.test_fnm_re_module3_split tests.unit.test_fnm_re_module4_linking tests.unit.test_fnm_re_module5_freeze tests.unit.test_fnm_re_module6_merge tests.unit.test_fnm_re_module7_export tests.unit.test_fnm_re_phase6 tests.unit.test_fnm_re_pipeline_snapshot tests.unit.test_fnm_re_status_gate_summary tests.integration.test_fnm_re_mainline_biopolitics tests.unit.test_fnm_re_public_api_surface tests.unit.test_fnm_batch_report`：`Ran 96 tests, OK`
- 8 本样本验收脚本（逐本调用 `build_doc_status`）：
  - `ALL_ACCEPTANCE_PASS=True`

### 下一步

1. 进入观察期：关注真实运行中是否出现新的模块六/七回退。
2. 若出现新的 `export_audit_blocking`，按当前模块顺序重新立项，不在本次收尾中扩范围。
3. 继续保持状态口径与批测口径同步更新（新增字段先写测试再接线）。

## 2026-04-18 Tier 1a 模块完善（最新）

### 变更点

- `FNM_RE/llm_repair.py`
  - `run_llm_repair` 默认 `cluster_limit=None`（全部 cluster），新增 `max_matched_examples / max_unmatched_note_items / max_unmatched_anchors` 覆盖 `LLM_REPAIR_MAX_*` 上限。
  - `_build_chapter_body_text` 在章节原始 page markdown 为空时，回退用 cluster 的 `page_contexts.ocr_excerpt` 拼出兜底正文，使 `synthesize_anchor` 路径仍能获得模糊匹配依据。
  - `run_llm_repair` 返回值新增聚合指标：`action_counts / auto_action_counts / synth_suggestion_count / synth_auto_applied_count / fuzzy_hit_count / fuzzy_ambiguous_count / caps`。
- `scripts/run_fnm_llm_repair.py`：补齐 `--confidence-threshold / --max-matched-examples / --max-unmatched-notes / --max-unmatched-anchors`；`--cluster-limit <=0` 视为全部。
- `scripts/run_fnm_llm_tier1a.py`（新增）：批量跑 Tier 1a 工作流，包含
  - `manual_toc_required` 自动回退（绑定 `test_example/<folder>/目录.pdf` → 重跑视觉 TOC → 重建 FNM）；
  - orphan before/after、`llm-synth-%` anchor 行数、override scope 覆盖等 DB 指标；
  - 单书报告 `test_example/<folder>/FNM_LLM_TIER1A_REPORT.md` + 汇总 `test_example/FNM_LLM_TIER1A_BATCH_REPORT.md`；
  - PaddleOCR `no_pages` 等前置失败统一标 `SKIP`，而非 `FAIL`。

### 自测

- `pytest tests/unit -k "fnm or llm_repair"` 198 passed。
- `python3 scripts/run_fnm_llm_repair.py --help`、`python3 scripts/run_fnm_llm_tier1a.py --help` 输出正常；新脚本模块加载与报告构造在 smoke fixture 上跑通。
- 未实际再跑真实 LLM（未消耗 token），等下一次整批实跑再刷报告。

### 下一步

- 待 shell 侧配置 `DASHSCOPE_API_KEY` 后，使用新脚本整批实跑：
  - `python3 scripts/run_fnm_llm_tier1a.py --group baseline`
- 预计将解锁前 5 本的 `manual_toc_required`；Neuropsy 两本仍需等 PaddleOCR 可用。

## 2026-04-18 Tier 1a 七本实跑结果（上一轮）

### 当前状态

- 已完成：
  - 按 `TEST.md` §9 串行实跑 7 本，批次目录：`output/tier1a_runs/20260418_220958_rerun`。
  - 产出 7 本单书报告 + 1 份汇总报告：
    - `test_example/*/FNM_LLM_TIER1A_REPORT.md`
    - `test_example/FNM_LLM_TIER1A_BATCH_REPORT.md`
- 本轮结果：`0/7 PASS`（全部 FAIL）。

### 最近实测

- 串行执行：
  - `python3 scripts/onboard_example_books.py --group all --slug <SLUG> --skip-existing`
  - `python3 scripts/test_fnm_batch.py --slug <SLUG>`
  - `python3 scripts/run_fnm_llm_repair.py DOC_ID --cluster-limit 3 --no-auto-apply --skip-rebuild`
  - `python3 scripts/run_fnm_llm_repair.py DOC_ID --cluster-limit 3`
  - baseline/after SQL 对比与 DB scope/anchor 校验（详见批次目录 CSV/LOG）

### 主要阻塞

1. Germany_Madness / Goldstein / Heidegger_en_France / Mad_Act / Napoleon：统一卡在 `manual_toc_required`，烟测导出未通过。
2. Neuropsychoanalysis_in_Practice / Neuropsychoanalysis_Introduction：onboard 两次重试均遇 PaddleOCR 500，烟测为 `no_pages`。
3. 7 本均未出现 `llm-synth-%` 锚点，`scope='anchor'` 条件未满足。

## 2026-04-18 Tier 1a 七本开跑准备（最新）

### 当前状态

- 已完成：
  - 对照审计 `TEST.md` §9，确认已覆盖前置条件、7 步标准流程、脚注/尾注专项、单书模板、7 本汇总模板、失败模式速查。
  - 在 `TEST.md` §9 新增“7 本样本映射（slug/doc_id/folder）”，并明确“以 `example_manifest.json` 为准”。
  - 在 `TEST.md` §9 新增开跑前快检（环境变量、关键脚本、manifest 完整性）。
  - 在 `TEST.md` §9 新增串行执行顺序与断点续跑规则，明确中断后的恢复动作。

### 最近实测

- 文档核对：`TEST.md` §9、`test_example/example_manifest.json`、`scripts/onboard_example_books.py`、`scripts/run_fnm_llm_repair.py`、`scripts/test_fnm_batch.py` 一致性检查完成。

### 下一步

1. 你确认“开始执行”后，按 `TEST.md` §9.8 的顺序逐书实跑 7 本。
2. 每跑完一本即落盘 `test_example/SLUG/FNM_LLM_TIER1A_REPORT.md`，并同步更新 `test_example/FNM_LLM_TIER1A_BATCH_REPORT.md`。

## 2026-04-16 FNM 一体化流程入口（最新）

### 当前状态

- 已完成：
  - 新增 `POST /api/doc/<doc_id>/fnm/full-flow`，统一触发“结构处理 + 分段翻译”链路。
  - 首页开始按钮改为一体化入口：未就绪时显示“开始一体化流程”，就绪后按状态显示“开始翻译/继续翻译”。
  - 状态接口新增一体化字段：`fnm_fullflow_running`、`full_flow_available`，并纳入 `workflow_state` 的“流程处理中”态。
  - 尾注冻结/解冻与落库合同保持一致：冻结在 FNM 结构阶段，翻译回写时解冻，最终保持 `original`/`translation` 与标题层级信息。

### 最近实测

- `.venv/bin/python -m pytest -q tests/integration/test_fnm_real_mode.py`：`6 passed`
- `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "home_page_keeps_standard_entry_when_fnm_view_ready or home_page_falls_back_to_existing_doc_when_current_doc_missing"`：`2 passed`
- `.venv/bin/python -m pytest -q tests/integration/test_fnm_real_mode.py tests/integration/test_tasks_streaming.py -k "fnm_full_flow_starts_translate_when_ready or fnm_continue_starts_background_rebuild or workflow_state or home_page_keeps_standard_entry_when_fnm_view_ready or home_page_falls_back_to_existing_doc_when_current_doc_missing"`：`4 passed`

### 下一步

1. 在真实长文档上观察“一体化流程”从结构到翻译的体感耗时和状态文案可读性。
2. 若要支持“真暂停结构重建”，再补任务级中断点（当前流程是可继续，非可中断）。

## 2026-04-16 重启状态与 FNM 继续处理入口修复

### 当前状态

- 已完成：
  - 首页当前文档选择增加回退链路：当 `current_doc_id` 失效时，会自动选中列表里可用文档继续展示状态，不再落到“无文档状态”。
  - `/api/doc/<doc_id>/fnm/status` 增加工作流字段：`workflow_state`、`workflow_state_label`、`state_hint`、`continue_fnm_available`、`resume_translate_available`。
  - 新增 `POST /api/doc/<doc_id>/fnm/continue` 异步继续入口；首页 FNM 卡片新增“继续 FNM 处理”按钮，“开始翻译”会按进度自动切换“继续翻译”。

### 最近实测

- `.venv/bin/python -m pytest -q tests/integration/test_fnm_real_mode.py`：`5 passed`
- `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "home_page_keeps_standard_entry_when_fnm_view_ready or home_page_falls_back_to_existing_doc_when_current_doc_missing"`：`2 passed`
- `.venv/bin/python -m pytest -q tests/integration/test_fnm_real_mode.py tests/integration/test_tasks_streaming.py -k "fnm_continue_starts_background_rebuild or workflow_state or falls_back_to_existing_doc_when_current_doc_missing"`：`2 passed`

### 下一步

1. 在真实长文档运行中观察“继续 FNM 处理”体验，确认状态文案与轮询反馈是否足够清晰。
2. 若需要“真暂停结构重建线程”，再补任务级可中断点（当前仅支持继续，不支持强中断）。

## 2026-04-16 翻译报错与实时状态看板修复

### 当前状态

- 已完成：
  - 翻译上游错误分类新增不可重试分支：`HTTP 400/401/403/404/422` 会标记为致命错误并立即停止任务，避免逐页连续报错刷屏。
  - FNM 状态接口补齐实时翻译字段：`translate_phase`、`translate_last_error`、`translate_log_relpath`、`draft_status`、`draft_para_done`、`draft_para_total`、`draft_note` 等。
  - 首页 FNM 工作流卡片已接入这些字段，实时显示“当前段落进度、流状态、最近错误、日志相对路径”。

### 最近实测

- `.venv/bin/python -m pytest -q tests/unit/test_translator_streaming.py tests/integration/test_fnm_real_mode.py`：`22 passed`
- `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "translate_worker_marks_quota_error_and_pushes_quota_event or translate_worker_stops_on_non_retryable_provider_error or translate_page_stream_raises_quota_error_without_retry or translate_page_stream_retries_after_rate_limit_wait"`：`4 passed`

### 下一步

1. 在真实模型请求场景继续观察致命错误分布（参数错误 vs 鉴权错误），再决定是否拆分更细的前端修复指引。
2. 若用户确认还需“字段级回流清单”（如 original/translation/footnotes），再把该清单作为独立状态字段固化到 API。

## 2026-04-16 FNM 运行异常收敛（最新）

### 当前状态

- 已完成：
  - 视觉目录调用链新增错误分类，非可重试 `HTTP 400` 立即失败并返回可读原因（含 stage/status）。
  - `needs_offset` 判定改为“可导航目录项（chapter/section/post_body）必须可定位”，容器项不再误判阻塞。
  - 上传链路在自动视觉目录抛异常时会明确报错并阻断后续 FNM，避免线程静默继续。
  - 首页 `/api/doc/<doc_id>/fnm/status` 消费增加非 2xx/非 JSON 显示，避免卡在“等待 FNM 状态…”。

### 最近实测

- `.venv/bin/python -m pytest -q tests/unit/test_visual_toc.py`：`42 passed`
- `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "visual_toc_failure_blocks_fnm_and_returns_error or visual_toc_exception_blocks_fnm_and_surfaces_error or process_file_runs_visual_toc_sync_before_fnm_when_fnm_enabled or process_file_manual_toc_pdf_upload_does_not_break_doc_meta_update"`：`4 passed`
- `.venv/bin/python -m pytest -q tests/integration/test_fnm_real_mode.py tests/integration/test_backend_backlog.py -k "fnm_status or toc_visual_status or effective_toc_accepts_auto_visual_needs_offset"`：`3 passed`

### 下一步

1. 继续用真实上传样本观察 DashScope 400 的业务错误文本分布，确认参数级根因是否完全收敛。
2. 在真实文档上复测首页 FNM 状态卡片，确认“失败态可见”与“阻塞原因可读”体验稳定。

## 2026-04-16 FNM 状态可视化与日志分片（最新）

### 当前状态

- 已完成：
  - 首页 FNM 工作流卡片增加实时“运行态 + 通过态 + 阻塞态”显示（含 gate 通过/失败计数与失败项文案）。
  - `/api/doc/<doc_id>/fnm/status` 增加前端友好聚合字段：`run_phase_label`、`gate_pass_count`、`gate_fail_count`、`gate_total_count`、`gate_failed_labels` 等。
  - FNM 解析日志增强：上传链路会写入 `run_id/structure_state/manual_toc_required/export_ready_real/blocking_reasons`。
  - 全局日志系统改为“每次启动单独文件”并自动清理，仅保留最近 30 次启动日志（`logs/sessions/app_*.log`）。
  - 日志策略明确：不记录翻译正文内容，仅保留状态与错误信息。

### 最近实测

- `.venv/bin/python -m pytest -q tests/unit/test_logging_config.py tests/unit/test_translate_runtime_logging_policy.py tests/unit/test_document_tasks_deps.py tests/integration/test_fnm_real_mode.py::FnmRealModeIntegrationTest::test_api_doc_fnm_status_reports_real_mode_blockers`：`6 passed`
- `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "test_process_file_"`：`9 passed`
- `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "test_process_file_done_event_routes_fnm_when_cleanup_enabled or test_process_file_manual_toc_pdf_upload_does_not_break_doc_meta_update"`：`2 passed`

### 下一步

1. 用真实文档再跑一轮首页观测，确认用户侧文案与轮询节奏体验。
2. 继续按 FNM 质量治理计划推进结构阻塞项收敛（不属于本批日志/状态改造范围）。

## 2026-04-16 SQLite 重构推进

### 当前状态

- 已完成：`db-refactor-baseline-audit`、`db-refactor-repo-boundary`、`db-refactor-schema-redesign`、`db-refactor-migration-script`、`db-refactor-mainline-cutover`、`db-refactor-read-path-purify`、`db-refactor-delete-flow`。
- 本轮已落地：
  - `sqlite_store` 拆库路由补齐：`upsert_document` 改为 catalog/doc 双写，避免 doc.db 外键断裂。
  - `catalog.db` schema 升级到 v2，补齐文档元字段兼容列（含迁移补列）。
  - 主链初始化默认不再初始化 legacy `app.db`（`initialize_runtime_databases` 默认 `include_legacy_app_db=False`）。
  - 迁移脚本修复 `translation_segments` 无 `doc_id` 过滤问题，拆库迁移集成测试通过。
  - 读路径去写首批完成：`load_pages_from_disk` 移除修复回写；`GET /`、`GET /input`、`GET /reading` 不再写 `current_doc_id`；`GET /reading` 不再写 `save_entry_cursor`。
  - glossary 持久化切到 doc.db（按 `doc_id` 路由），删除文档时同步清理 `catalog.app_state` 的 doc-scoped 残留 key。

### 最近实测

- 主库定位与体积：
  - `local_data/user_data/data/app.db`：`652,468,224 bytes`
  - 根目录 `app.db`：`0 bytes`（空壳）
- 表与载荷基线（见 `SQLite.md`）：
  - `fnm_translation_units` 约 `480MB`
  - `MAX(LENGTH(translate_runs.task_json)) = 2,136,736`
  - `fnm_runs = 430`、`documents = 7`
- 测试：
  - `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "load_pages_from_disk_does_not_write_back_repair_results or reading_get_does_not_persist_cursor_or_switch_current_doc"`：`2 passed`
  - `.venv/bin/python -m pytest -q tests/integration/test_sqlite_store.py -k "test_catalog_repository_uses_catalog_db_path or test_document_repository_uses_document_db_path or test_initialize_runtime_databases_supports_catalog_and_document_dbs or test_initialize_runtime_databases_defaults_to_catalog_without_legacy_app_db or test_glossary_state_is_written_to_doc_db_in_split_mode or test_delete_document_cleans_catalog_doc_scoped_state_keys"`：`6 passed`
  - `.venv/bin/python -m pytest -q tests/integration/test_sqlite_split_migration.py`：`1 passed`
  - `.venv/bin/python -m pytest -q tests/integration/test_backend_backlog.py -k "test_doc_processing_status_returns_visual_toc_progress_payload or test_glossary_crud_api"`：`2 passed`
  - `.venv/bin/python -m pytest -q tests/integration/test_sqlite_mainline.py -k "test_translate_status_is_task_only_and_reading_view_state_is_separate or test_doc_scoped_glossary_isolated_between_documents or test_fetch_next_uses_doc_scoped_glossary or test_delete_docs_batch_removes_selected"`：`4 passed`
  - `.venv/bin/python -m pytest -q tests/integration/test_sqlite_store.py` 仍有既有失败 `test_repository_persists_fnm_data_without_touching_standard_translation_pages`（当前基线失败项，非本轮新增）

### 下一步

1. 继续补齐 `db-refactor-tests`：扩大并发/迁移/删除场景覆盖到全量 SQLite 主链集。
2. 收口 `db-refactor-doc-sync`：把 README/DEV/SQLite/verification 的拆库口径保持一致。
3. 评估并处理既有基线失败 `test_repository_persists_fnm_data_without_touching_standard_translation_pages`。

## 2026-04-15 旧链硬退役验收完成（最新）

### 当前状态

- 主仓根目录 `fnm/` 已硬删除；旧链代码已迁入 `FootNoteMachine/legacy_fnm/code/fnm/` 只读归档。
- `fnm_v2` 相关 schema/repo API 已退役，主仓运行链路统一到 `FNM_RE`。
- 导入守卫已收紧：主仓运行代码与现行测试禁止 `fnm.*` 与 `legacy_fnm.*` 导入。
- baseline/extension 批测已完整执行并完成定位：失败仅由既有 `structure_review_required` gate 触发，无退役相关新回归。

### 最近实测

- `python3 -m unittest tests.unit.test_fnm_import_guards`：`1 test OK`
- `python3 -m unittest tests.unit.test_fnm_re_phase1 tests.unit.test_fnm_re_phase2 tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_phase5 tests.unit.test_fnm_re_phase6`：`78 tests OK`
- `python3 -m unittest tests.unit.test_audit_fnm_exports tests.unit.test_onboard_example_books tests.unit.test_generate_visual_toc_snapshots tests.unit.test_toc_real_page_resolution tests.unit.test_fnm_export tests.unit.test_fnm_export_audit tests.unit.test_fnm_batch_report`：`34 tests OK`
- `rg -n "from fnm\\.|import fnm\\." --glob "{FNM_RE/**,web/**,pipeline/**,translation/**,scripts/**,persistence/**,tests/**}/*.py"`：无命中
- `rg -n "fnm_re_mainline" --glob "{FNM_RE/**,web/**,pipeline/**,translation/**,scripts/**,persistence/**,tests/**}/*"`：无命中
- `rg -n "replace_fnm_v2_structure|list_fnm_v2_|fnm_structure_issues_v2" --glob "{persistence/**,tests/**}/*.py"`：无命中
- `python3 scripts/test_fnm_batch.py --group baseline`：完整执行（5 本）；均为 `structure_review_required`
- `python3 scripts/test_fnm_batch.py --group extension`：完整执行（3 本）；均为 `structure_review_required`

### 结论（硬退役验收完成）

- 旧链硬退役已完成并通过回归定位验收：未发现退役相关新回归。
- 批测中的 `structure_review_required` 属既有结构质量 gate，不影响“旧链退役完成”结论。

### 剩余事项

- 无退役阻塞；后续按结构质量治理路线继续收敛 `structure_review_required`。

## 2026-04-14 phase7 收口二轮（暂停点，最新）

### 当前状态

- 当前处于 `PLAN7-2` 第一批（链接债）中途暂停，未进入第二批标题对齐。
- 这轮已经完成并落地：
  - `FNM_RE/shared/anchors.py`：把上标脚注定义行（`$^{n}$`/`<sup>n</sup>`/Unicode 上标）纳入“定义行过滤”，减少正文误抽 anchor。
  - `FNM_RE/stages/note_links.py`：增加“最近唯一候选优先”规则，减少 `ambiguous`。
  - `FNM_RE/stages/note_links.py`：为 `ch-fallback-*` 与 `toc-ch-*` 章节增加跨章修复匹配（仅在本章无锚点或明确需要时触发）。
  - `FNM_RE/stages/note_links.py`：收紧 orphan_anchor 产出（已存在同 marker note_item 或已匹配 marker 时不再重复产 orphan；fallback 无 marker 章不产 orphan；toc 章节按章内 marker 范围裁剪离谱 marker）。
  - `tests/unit/test_fnm_re_phase3.py`：补了对应回归测试（定义行过滤、最近唯一候选、跨章修复、orphan 裁剪）。

### 最近实测

- `python3 -m unittest tests.unit.test_fnm_re_phase3`：`18 tests OK`
- `python3 -m unittest tests.unit.test_fnm_re_phase1 ... tests.unit.test_fnm_re_phase7`：`83 tests OK`
- `python3 -m unittest tests.integration.test_fnm_v2_pipeline tests.integration.test_fnm_pipeline_v3`：`6 tests OK`
- `python3 scripts/test_fnm_batch.py --slug Mad_Act`：
  - `matched=172`
  - `footnote_orphan_anchor=1209`
  - `endnote_orphan_note=92`
  - `endnote_orphan_anchor=103`
  - `ambiguous=17`
  - 仍为 `structure_review_required`
- `python3 scripts/test_fnm_batch.py --slug Biopolitics`：
  - `matched=377`
  - `footnote_orphan_anchor=0`（已清零）
  - `endnote_orphan_note=49`
  - `endnote_orphan_anchor=1`
  - `ambiguous=13`
  - 仍为 `structure_review_required`
- `FNM_RE.app.mainline.build_phase6_status_for_doc("7ba9bca783fd")`（Goldstein 快照）：
  - `matched=381`
  - `endnote_orphan_note=2`
  - `endnote_orphan_anchor=0`（已清零）
  - `ambiguous=0`
  - 仍有 `toc_chapter_title_mismatch` 与 `export_audit_blocking`

### 阶段性结论

- 第一步链接债已经“明显下降但未清零”，当前不能判定 gate 通过。
- 这轮最有效的收口点是：
  - 误抽 anchor 压制（尤其上标定义行过滤）；
  - endnote 匹配修复（fallback/toc 跨章补救）；
  - orphan_anchor 去重和范围约束。
- 当前最大的剩余链接债在 `Mad_Act`（`footnote_orphan_anchor` 量级仍高）。

### 暂停后的下一步

1. 继续 `fnm-re-phase7-r2-link-fixes`，优先继续压 `Mad_Act` 的 `footnote_orphan_anchor`。
2. 同步清 `Biopolitics` 的 `endnote_orphan_note` 与 `ambiguous`（已进入收尾区）。
3. 链接债稳定后切到 `fnm-re-phase7-r2-title-fixes`，处理 `toc_chapter_title_mismatch`（Germany/Goldstein/Heidegger）。

## 2026-04-12 Biopolitics 目录组织方式与尾注错绑收口（最新）

### 当前状态

- `Biopolitics` 这一本已经从“目录组织方式已算出来，但单书仍 blocked”收口到：
  - `python3 scripts/test_fnm_batch.py --slug Biopolitics`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Biopolitics --full`：`can_ship=True, blocking=0, major=0`
- 当前最新导出包：
  - [latest.fnm.obsidian.zip](/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.zip)
- 当前最新角色层已经能从状态接口直接读到：
  - `container_titles = ["COURS, ANNÉE 1978-1979"]`
  - `post_body_titles = ["RÉSUMÉ DU COURS", "SITUATION DES COURS"]`
  - `back_matter_titles = ["INDICES"]`

### 这轮刚完成的事情

- 修掉了 `Leçon du 10 janvier 1979` 的跨章尾注错绑：
  - 新增真实书守卫测试，锁第一讲下所有 `matched endnote` 都必须绑回本讲自己的 `note_item`
  - 在 `fnm/fnm_structure.py` 新增最终的同章回绑收口，不再允许外章 `matched endnote` 留在本章
- 修掉了 `RÉSUMÉ DU COURS` 被审计误判成 `front_matter_leak`：
  - `fnm/fnm_export_audit.py` 现在不再把 `post_body` 中的出版说明按前置材料直接拦截
  - `fnm/fnm_v2_status.py` 现在会在 run summary 缺失时，从当前自动视觉目录 items 回填：
    - `toc_role_summary`
    - `container_titles`
    - `post_body_titles`
    - `back_matter_titles`

### 已确认的真实结果

- `Biopolitics` 当前导出文件已经是：
  - 12 个 `Leçon du ...`
  - `RÉSUMÉ DU COURS`
  - `SITUATION DES COURS`
- `COURS, ANNÉE 1978-1979` 现在只保留为 `container`，不再单独导出正文文件
- 第一讲 `chapters/001-Leçon du 10 janvier 1979.md` 当前章末第一条定义已经恢复为：
  - `Citation de Virgile ... Acheronta movebo ... Freud`

### 当前新确认的收尾判断

- 这一步说明：
  - “目录组织方式优先”已经真正进入结构层、状态层、审计层和导出层
  - `Biopolitics` 之前那种“结构里对了，但状态和审计还按旧扁平逻辑误判”的旧链影响已经清掉
- 当前仓库里与旧链相关的剩余残留，主要已经退到：
  - 历史验证记录
  - 显式标历史的旧规格文档
  - 标准翻译与诊断页自己的 `_page_entries` 运行时 payload
  - 不再是 FNM 正式主链的真相来源

### 当前下一步

1. 继续完成剩余旧链口径清理，重点是文档和少量误导性命名
2. 再按书继续推进 `Mad_Act / Napoleon / Neuropsychoanalysis_in_Practice` 这批组织方式问题书

## 2026-04-12 手动目录组织方式重刷结果核对（最新）

### 当前状态

- 4 本重点书的 `apply_manual_toc_to_examples.py` 已全部跑完：
  - `Biopolitics`
  - `Mad_Act`
  - `Napoleon`
  - `Neuropsychoanalysis_in_Practice`
- 当前确认到的真实结果分成两类：
  - `Mad_Act / Napoleon`：样本目录产物已经刷新，`latest.fnm.obsidian.zip` 存在，导出状态为 `ready`
  - `Biopolitics / Neuropsychoanalysis_in_Practice`：手动目录组织方式结果已经在本轮 apply 输出里出现，但样本目录和后续导出状态还没完全跟上，需要继续做单书重跑

### 这一步新确认的事实

- `Biopolitics`
  - 当前手动目录组织方式结果已经明确包含：
    - `container_titles = ["COURS, ANNÉE 1978-1979"]`
    - `post_body_titles = ["RÉSUMÉ DU COURS", "SITUATION DES COURS"]`
    - `back_matter_titles = ["INDICES", "Index des notions", "Index des noms de personnes"]`
  - 结构层按新规则重算后，章节列表是：
    - 12 个 `Leçon du ...`
    - `RÉSUMÉ DU COURS`
    - `SITUATION DES COURS`
  - 但样本目录当前仍停在旧状态：
    - `latest_export_status.json` 还是旧的 `blocked / footnote_orphan_note`
    - 还没有新的 `latest.fnm.obsidian.zip`
  - 这说明：
    - 结构主线已经具备 `container + 12 lecture + 2 post_body`
    - 但样本导出产物还没刷新到这一步

- `Mad_Act`
  - 新的手动目录组织方式结果已经明确包含：
    - `container_titles = [Part One ..., Part Two ...]`
    - `post_body_titles = ["Appendices"]`
    - `back_matter_titles = ["Bibliographies"]`
  - 根正文 `Mad acts, mad speech, and mad people in Chinese medicine and law` 已不再被误降成 `front_matter`
  - 当前样本目录已刷新，`latest.fnm.obsidian.zip` 存在，导出状态为 `ready`

- `Napoleon`
  - 新的手动目录组织方式结果已经明确包含：
    - 5 个 roman-number `container`
    - `Préambule` 为正文
    - `Postambule` 为 `post_body`
    - `APPENDICES / Bibliographie / Index` 为 `back_matter`
  - 当前样本目录已刷新，`latest.fnm.obsidian.zip` 存在，导出状态为 `ready`

- `Neuropsychoanalysis_in_Practice`
  - `apply_manual_toc_to_examples.py` 的本轮输出已经出现新的 `organization_summary`：
    - `Part I~IV` 已被识别为 `container`
    - `Appendix ...` 已被识别为 `post_body`
    - `References / Index` 已被识别为 `back_matter`
  - 但当前 `test_example/Neuropsychoanalysis_in_Practice/auto_visual_toc.json` 仍是旧快照，尚未反映这些组织方式字段
  - 这说明：
    - 视觉目录主链已经能判定该书的组织方式
    - 样本快照与后续导出还需要继续重刷

### 当前新发现的问题

- 当前真正的卡点已经从“目录组织方式是否能判定”转成“组织方式结果何时真正刷进样本快照与导出产物”
- `Biopolitics`
  - 结构层已支持 `RÉSUMÉ / SITUATION`，但样本目录还停在旧 blocked 状态
  - 已完成单书重跑，但当前新的真实阻塞不是目录角色，而是 `footnote_orphan_note`
  - 当前单书批测结果：
    - `sections=14, notes=504, units=542`
    - `structure_state=review_required`
    - `blocking=["footnote_orphan_note"]`
  - 本地结构重算结果已确认是：
    - 12 个 `Leçon du ...`
    - `RÉSUMÉ DU COURS`
    - `SITUATION DES COURS`
  - 说明：
    - 目录组织方式主线已经做对
    - 下一步要继续收的是 `Biopolitics` 的孤注链接，而不是继续改 `COURS / RÉSUMÉ / SITUATION` 的角色判定
- `Neuropsychoanalysis_in_Practice`
  - apply 结果与样本快照暂时不一致
  - 不能再直接拿旧 `auto_visual_toc.json` 判断这本书的当前真实组织方式

### 当前下一步

1. 先追 `Biopolitics` 最新 run 里的 `footnote_orphan_note`，定位到具体 lecture 后就地修掉
2. `Biopolitics` 收口后，再继续这 4 本的单书 `test_fnm_batch + full audit`
3. 再确认：
   - `Biopolitics` 是否刷出包含 `RÉSUMÉ / SITUATION` 的最新 zip
   - `Neuropsychoanalysis_in_Practice` 的样本快照是否刷成新的 organization 结果

## 2026-04-12 手动目录组织方式重构继续推进（最新）

### 当前状态

- 已确认当前真正的卡点是“用户上传目录页后的组织方式还没稳定建模”，不是单纯章节边界：
  - `Biopolitics` 现在已经能识别出 `container + 12 lecture + 2 post_body + back_matter`
  - `Mad_Act` 暴露出另一类错法：`Part One / Part Two` 这类**无页码 container** 在第一轮目录项抽取里丢失，导致 16 个小章节被压成 7 个导出文件
  - `Neuropsychoanalysis_in_Practice` 和 `Napoleon` 当前快照仍明显带有旧的扁平目录结果，还需要按新逻辑重刷

### 这轮已完成

- `pipeline/visual_toc.py`
  - 扩展了目录角色启发式：
    - `Part One / Part Two / Première partie ...` 现在可直接识别为 `container`
    - `Bibliographies` 现在识别为 `back_matter`
  - 新增了 `roman numeral root + child depth` 的容器提升规则：
    - 如 `III. ... / IV. ... / V. ...` 这种上层标题，在其下存在更细层时会提升成 `container`
  - 新增了 `container` 下一层正文自动升为 `chapter` 的规则：
    - 仅在子项有页码或已定位到 `file_idx` 时触发，避免误把纯说明行升成正文
  - 新增了第二层手动目录组织方式判读：
    - `_extract_visual_toc_organization_nodes_from_images(...)`
    - `_merge_manual_toc_organization_nodes(...)`
    - 手动目录主链现在不再只做“逐页标题抽取”，还会对整份目录页再做一次组织方式判读，再把结构关系合并回第一轮已定位的页码项

- 新增并跑绿的守卫测试：
  - `tests.unit.test_visual_toc.VisualTocLogicTest.test_filter_visual_toc_items_keeps_part_one_container_without_page`
  - `tests.unit.test_visual_toc.VisualTocLogicTest.test_annotate_visual_toc_organization_promotes_container_children_and_roman_root`
  - `tests.unit.test_visual_toc.VisualTocLogicTest.test_merge_manual_toc_organization_nodes_preserves_missing_containers_and_page_matches`
  - `python3 -m unittest -q tests.unit.test_visual_toc`：`28 tests OK`

### 当前新发现的问题

- `Mad_Act`
  - 即使第一轮目录抽取已经带上 `Appendices` 和 `Bibliographies`，`Part One / Part Two` 仍没有出现在当前快照里
  - 说明现有第一轮“逐页目录项抽取”并不会稳定保留无页码 part 标题，第二层组织方式判读是必须的，不是优化项
- `Mad_Act` 当前快照仍表现为：
  - `container_titles = []`
  - `chapter = 7`
  - `post_body = 1`
  - `back_matter = 1`
  - 这仍然和真实目录“第 1 章 + Part One 下 2-9 + Part Two 下 10-16 + Bibliographies + Appendices”不一致
- `Neuropsychoanalysis_in_Practice`
  - 当前 `auto_visual_toc.json` 仍没有 `organization_summary`
  - 目录顺序也明显被旧结果污染，需要用新链重刷后再判断
- `Napoleon`
  - 当前结构问题不再只是章节边界，而是 `III / IV / V` 这类 roman-number 层没有稳定进入 `container`

### 最近实测

- `python3 -m unittest -q tests.unit.test_visual_toc.VisualTocLogicTest.test_filter_visual_toc_items_keeps_part_one_container_without_page tests.unit.test_visual_toc.VisualTocLogicTest.test_annotate_visual_toc_organization_promotes_container_children_and_roman_root`：先失败，后通过
- `python3 -m unittest -q tests.unit.test_visual_toc.VisualTocLogicTest.test_merge_manual_toc_organization_nodes_preserves_missing_containers_and_page_matches`：先因 helper 缺失失败，补实现后随整组通过
- `python3 -m unittest -q tests.unit.test_visual_toc`：`28 tests OK`
- `python3 scripts/generate_visual_toc_snapshots.py --slug Mad_Act`
  - 当前重刷仍显示 `Has Containers: No`
  - 说明仅靠第一轮 title extraction 不够，第二层组织方式判读需要继续验证真实效果

### 当前下一步

1. 等 `Mad_Act` 的手动目录重刷完成，直接检查第二层组织方式判读是否已经把 `Part One / Part Two` 合并进结果
2. 若 `Mad_Act` 仍无 `container_titles`，继续补更强的 manual TOC organization 规则，直到 16 个小章节能按最细正文层导出
3. `Mad_Act` 收口后，按同一条组织方式主线继续处理：
   - `Neuropsychoanalysis_in_Practice`
   - `Napoleon`

## 2026-04-12 FNM 最终收尾完成（最新）

### 当前状态

- FNM 最终收尾已经完成：
  - 最后一批 legacy 语义已继续清理
  - 8 本书已重新跑完 `FNM -> test 导出 -> full audit`
  - 各样本目录下的 `latest.fnm.obsidian.zip` 已被本轮结果覆盖
- 当前最终验证：
  - `python3 -m unittest discover -s tests/unit -p 'test_*.py'`：`334 tests OK`
  - `python3 -m unittest discover -s tests/integration -p 'test_*.py'`：`339 tests OK`
  - `python3 scripts/test_fnm_batch.py --all-docs`：`8 通过, 0 未通过`
- `output/fnm_book_audits/` 也已在本轮末尾重新刷新，和最新 zip 保持一致
- 当前批测结果文件已刷成最新且口径正确：
  - 顶层 `slug / example_folder / full_audit_report_path` 已恢复，不再是空字段

### 这轮最后完成的收口

- 修掉了 `--all-docs` 结果文件缺少 manifest 元数据的问题：
  - 根因是全量批测分支没有把 manifest 中的 `slug/folder` 回填进结果
  - 现在 `scripts/test_fnm_batch.py` 会在 `--all-docs` 下按 `doc_id` 补齐 manifest 元数据
  - 已新增回归测试：
    - `tests/unit/test_fnm_batch_report.py::test_select_documents_all_docs_still_enriches_manifest_slug_and_folder`
- 为避免结果互相覆盖，确认并执行了保守规则：
  - 同时发现两个残留的 `--all-docs` 批测进程时，只保留当前这次新的重跑
  - 旧残留进程已手动终止，避免继续改写 zip 和结果文件
- 8 本样本目录下的最新导出已确认覆盖：
  - `Biopolitics`
  - `Germany_Madness`
  - `post-revolutionary`
  - `Heidegger_en_France`
  - `Mad_Act`
  - `Napoleon`
  - `Neuropsychoanalysis_in_Practice`
  - `Neuropsychoanalysis_Introduction`

### 本轮章节抽查结论

- `Biopolitics`
  - 当前 12 个 lecture 导出稳定，尾注首条对齐恢复正常
  - 非阻塞问题：
    - 章节开头普遍存在 `## 标题` 后又重复一行原始标题
    - 注释区仍有少量 OCR/编码噪声
    - `RÉSUMÉ / SITUATION` 仍未作为 `post_body` 独立导出
- `Germany_Madness`
  - 主体章节基本稳定
  - 非阻塞问题：
    - `chapters/008-Epilogue.md` 仍卷入 `REFERENCE MATERIAL / PRIMARY SOURCES`
    - 开头仍有 OCR 错字 `Cpilogue`
- `Goldstein`
  - 抽查的 `Introduction / 中段 / Epilogue` 都比较干净
  - 当前没有新发现的真实质量问题
- `Heidegger_en_France`
  - 12 个主章节和脚注合同保持稳定
  - 非阻塞问题：
    - `chapters/001-Introduction.md` 仍有标题层级堆叠：先出现 `### De la mode à la méthode`，随后又重复 `Introduction`
- `Mad_Act`
  - 本轮脚注闭合问题已经收口
  - 非阻塞问题：
    - `chapters/001-Prologue.md` 开头仍残留孤立的 `10` 和 `Prologue to Part Two`
    - 末章脚注定义中仍能看到明显 OCR 噪声
- `Napoleon`
  - 当前主章节骨架较前几轮稳定
  - 抽查未见新的阻塞问题
- `Neuropsychoanalysis_in_Practice`
  - 主章节和尾注合同稳定
  - 非阻塞问题：
    - `chapters/001-Introduction.md` 仍混入封面/书名页元素、作者名和 `List of abbreviations`
- `Neuropsychoanalysis_Introduction`
  - 抽查确认首章结尾仍有真实问题：
    - `chapters/001-Introduction.md` 末尾停在半句 `Analogously on the temporal side, one can observe temporal`
    - 最新 full audit 已把这条记为 `major=1`，issue=`chapter_boundary_missing_tail`
  - 当前不阻塞本轮交付，但必须列入下一轮优化优先级

### 当前结论

- 这轮没有发现“本轮新引入的回归”
- 当前 8 本样本都已经达到：
  - batch 通过
  - full audit `blocking=0`
  - 最新 zip 已覆盖
- 还剩下的，是下一轮可以继续优化的**非阻塞质量问题**，主要集中在：
  - 标题重复/层级堆叠
  - 首章起点过宽
  - 个别章节误卷入后置材料
  - OCR/编码噪声清洗
  - 个别章节结尾截断（目前已确认 `Neuropsychoanalysis_Introduction/001-Introduction.md`）

### 当前下一步

- 若继续优化，优先顺序建议是：
  1. `Germany_Madness`：清掉 `Epilogue` 中的 `REFERENCE MATERIAL`
  2. `Neuropsychoanalysis_in_Practice`：收紧 `Introduction` 起点
  3. `Neuropsychoanalysis_Introduction`：修 `Introduction` 章节结尾截断
  4. `Mad_Act`：去掉 `Prologue` 页码/part 残片
  5. `Heidegger_en_France`：再压一轮标题投影去重
  6. `Biopolitics`：决定是否把 `RÉSUMÉ / SITUATION` 升成独立 `post_body` 文件

## 2026-04-11 FNM 主链清理继续推进（最新）

### 这轮新增完成

- 诊断层命名已经进一步收口到 `diagnostic` 语义：
  - `SQLiteRepository` 已统一使用：
    - `list_fnm_diagnostic_notes(...)`
    - `list_fnm_diagnostic_entries(...)`
    - `get_fnm_diagnostic_page(...)`
  - `fnm_page_translate.py` 已统一使用：
    - `rebuild_fnm_diagnostic_page_entries(...)`
    - `ensure_fnm_diagnostic_page_entries(...)`
    - `get_fnm_diagnostic_entry_for_page(...)`
  - `fnm_export.py / translate_worker_fnm.py / web/reading_view.py / web/translation_routes.py / scripts/test_fnm_batch.py / scripts/rebuild_doc_derivatives.py`
    都已切到新的诊断命名，不再继续暴露旧 `page_entries / notes` repo API 名称
- `/api/doc/<doc_id>/fnm/status` 当前也已改成：
  - `has_diagnostic_entries`
  - 不再继续使用 `has_page_entries`
- 全仓库进一步检索确认：
  - 已搜不到 `list_fnm_page_entries / list_fnm_notes / get_fnm_page_entry / rebuild_fnm_page_entries / ensure_fnm_page_entries / load_fnm_projected_entries / has_page_entries / include_page_entries`
  - 当前残留的旧名只存在于：
    - 历史验证记录
    - 显式标注为“历史草案”的旧规格文档
- `fnm_export.py` 内部也已把旧 `section_exports` 口径收成 `chapter_exports`
- `docs/superpowers/specs/2026-04-02-footnotemachine-integration-design.md` 顶部已补“历史草案”警示，避免旧设计继续被误读成当前主链

### 这轮刚完成的清理

- `build_fnm_structure()` 已不再返回：
  - `rendered_chapters`
  - `rendered_sections`
  - `legacy_structure`
- `build_fnm_v2_structure()` 也已不再返回 `rendered_sections`
- 对应守卫测试已经改成只检查结构真相层：
  - `note_links`
  - `note_items`
  - `body_anchors`
  - 以及“旧 legacy 返回字段不存在”
- 同时收掉了 9 个 `fnm_structure` 历史漂移点：
  - 3 个测试口径已对齐当前真实行为
  - 6 个脚注解析 / 重建逻辑点已修复
    - 图注 `FIG.` 不再被 OCR 模糊匹配成脚注定义
    - 纯正文内联上标不再被误当成页脚定义行
    - PDF 页文本可覆盖空白 inline 定义
    - 污染 marker（如 `4749`）不再回灌成重建脚注
    - 稳定连续推断 marker 群会优先于错误正文锚点
    - `Biopolitics` 的 `225` 页尾注区不再被误判成漂移异常

### 这轮立即验证到的结果

- 目标清理回归通过：
  - `python3 -m unittest tests.unit.test_fnm_structure.FnmStructureTest.test_biopolitics_structure_keeps_endnote_links_and_drops_legacy_rendered_outputs tests.unit.test_fnm_structure.FnmStructureTest.test_mad_act_matched_endnotes_must_have_body_anchor_and_no_legacy_rendered_outputs tests.unit.test_fnm_v2_structure.FnmV2StructureRegressionTest.test_biopolitics_v2_keeps_matched_endnote_links_without_rendered_sections -q`
  - `python3 scripts/test_fnm_batch.py --slug Biopolitics`
- 说明当前删除旧返回链后，真实 FNM 主链仍能正常跑通 `Biopolitics` 单书闭环
- 这轮补充验证：
  - `python3 -m unittest tests.unit.test_fnm_structure tests.unit.test_fnm_v2_structure -q`
  - 结果：`119 tests OK`
  - `python3 -m unittest tests.integration.test_fnm_worker tests.integration.test_sqlite_store tests.integration.test_sqlite_mainline -q`
  - 结果：`98 tests OK`
  - `python3 scripts/test_fnm_batch.py --slug Biopolitics`
  - 结果：通过，`state=ready, chapters=12`
- 本轮没有新增主链阻塞；当前新增清理主要是命名与接口诚实化，不涉及结构或导出合同回退

### 这轮新发现的后续清理目标

- 旧 `rendered_*` 返回链已经删掉，但仓库里仍残留一批 `page_entries / notes` 命名与诊断 wrapper：
  - `fnm_export.py`
  - `translate_worker_fnm.py`
  - `sqlite_repo_fnm.py`
  - `fnm_page_translate.py`
- 这些代码当前不再指向旧表，但名字和接口形状仍容易误导维护者
- 其中 repo 方法、page translate wrapper 和状态接口字段这一轮已经收掉；下一步继续清：
  - 剩余局部变量与日志里的旧 `section_id / note_id / page_entries` 语义
  - 诊断 helper 的文件内命名与注释
  - 历史规格文档的 archive 语义已补上，但仍会保留旧设计内容作为参考，不计入当前主链残留

### 当前下一步

- 继续把剩余低风险 legacy 命名和注释收口
- 优先处理 `translate_worker_fnm.py / fnm_export.py / web/reading_view.py` 内部局部变量与日志口径

## 2026-04-11 8 本逐书核查闭环完成（最新）

### 本轮结论

- 8 本样本书现在都已经完成“逐书 -> 逐文件 -> 重跑单书 pipeline -> 重审计”的固定闭环。
- 这轮最后补齐的两本是：
  - `Neuropsychoanalysis_in_Practice`
  - `Neuropsychoanalysis_Introduction`
- 当前 8 本都已经具备对应的逐书审计产物：
  - [output/fnm_book_audits/Biopolitics.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Biopolitics.md)
  - [output/fnm_book_audits/Germany_Madness.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Germany_Madness.md)
  - [output/fnm_book_audits/Goldstein.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Goldstein.md)
  - [output/fnm_book_audits/Heidegger_en_France.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Heidegger_en_France.md)
  - [output/fnm_book_audits/Mad_Act.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Mad_Act.md)
  - [output/fnm_book_audits/Napoleon.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Napoleon.md)
  - [output/fnm_book_audits/Neuropsychoanalysis_in_Practice.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Neuropsychoanalysis_in_Practice.md)
  - [output/fnm_book_audits/Neuropsychoanalysis_Introduction.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Neuropsychoanalysis_Introduction.md)
- 当前这 8 本逐书全量审计都已经清到：
  - `blocking=0`
  - `major=0`

### 这轮最后确认到的新结果

- `Neuropsychoanalysis_in_Practice`
  - 单书批测通过：`python3 scripts/test_fnm_batch.py --slug Neuropsychoanalysis_in_Practice`
  - 全量审计通过：`python3 scripts/audit_fnm_exports.py --slug Neuropsychoanalysis_in_Practice --full`
  - 当前 [output/fnm_book_audits/Neuropsychoanalysis_in_Practice.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Neuropsychoanalysis_in_Practice.md) 已与最新导出包一致。
- `Neuropsychoanalysis_Introduction`
  - 单书批测通过：`python3 scripts/test_fnm_batch.py --slug Neuropsychoanalysis_Introduction`
  - 全量审计通过：`python3 scripts/audit_fnm_exports.py --slug Neuropsychoanalysis_Introduction --full`
  - 当前 [output/fnm_book_audits/Neuropsychoanalysis_Introduction.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Neuropsychoanalysis_Introduction.md) 已与最新导出包一致。

### 当前判断

- 这轮“逐书逐文件核查 + 单书收口”主任务已经完成。
- 当前后续重点不再是继续补单书阻塞，而是：
  - 继续整理大重构后仍残留的文档和代码形状
  - 再做一次仓库级清理，把本轮为逐书修复临时留下的无用 helper、旧分支和重复记录清掉

### 下一步

- 继续完成仓库级清理与文档收口：
  - 压缩 `PROGRESS.md` 的重复分段
  - 统一 `Summary.md / DEV.md / TEST.md / verification.md` 的当前口径
  - 继续清掉 FNM 主链里剩余的 legacy 命名和只服务旧逻辑的 helper

## 2026-04-11 Mad_Act 逐书核查完成（最新）

### 本轮结论

- `Mad_Act` 这一本已经完成逐书核查：
  - `python3 scripts/test_fnm_batch.py --slug Mad_Act`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Mad_Act --full`：`can_ship=True, blocking=0, major=0`
- 当前 [output/fnm_book_audits/Mad_Act.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Mad_Act.md) 与最新批测结果已经一致：
  - 7 个章节文件全部通过全量审计
  - `latest.fnm.obsidian.zip` 已重新落盘

### 这轮确认到的情况

- `Mad_Act` 当前不再是导出阻塞样本
  - 第一轮全量审计即为 `blocking=0, major=0`
  - 单书重跑后结果保持不变
- 当前这本的结构角色分层、章节边界和导出合同都是稳定的：
  - `7` 个正式章节
  - `50` 个 `section_heads`
  - `link_summary` 中注释孤儿项全部为 `0`
- 因此这一本本轮**不需要新增代码修复**

### 当前验证

- `python3 scripts/test_fnm_batch.py --slug Mad_Act`：通过
- `python3 scripts/audit_fnm_exports.py --slug Mad_Act --full`：`can_ship=True, blocking=0, major=0`

### 下一步

- `Mad_Act` 已清到 `blocking=0, major=0`
- 按既定顺序继续进入：
  - `Napoleon`

## 2026-04-11 Heidegger_en_France 逐书核查完成（最新）

### 本轮结论

- `Heidegger_en_France` 这一本已经完成逐书核查：
  - `python3 scripts/test_fnm_batch.py --slug Heidegger_en_France`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Heidegger_en_France --full`：`can_ship=True, blocking=0, major=0`
- 当前 [output/fnm_book_audits/Heidegger_en_France.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Heidegger_en_France.md) 与最新批测结果已经一致：
  - 12 个章节文件全部通过全量审计
  - `latest.fnm.obsidian.zip` 已重新落盘

### 这轮确认到的情况

- `Heidegger_en_France` 当前不再是导出收口阻塞样本
  - 第一轮全量审计已经是 `blocking=0, major=0`
  - 单书重跑后结果保持不变
- 这本书当前主骨架、章内标题层和导出合同都是稳定的：
  - `12` 个主章节
  - `81` 个 `section_heads`
  - `link_summary` 中 `footnote_orphan_note / footnote_orphan_anchor / endnote_orphan_note / endnote_orphan_anchor` 全为 `0`
- 因此这一本本轮**不需要新增代码修复**
  - 后续若再优化，重点才会是结构质量细化，而不是当前导出阻塞

### 当前验证

- `python3 scripts/test_fnm_batch.py --slug Heidegger_en_France`：通过
- `python3 scripts/audit_fnm_exports.py --slug Heidegger_en_France --full`：`can_ship=True, blocking=0, major=0`

### 下一步

- `Heidegger_en_France` 已清到 `blocking=0, major=0`
- 按既定顺序继续进入：
  - `Mad_Act`

## 2026-04-11 Goldstein 逐书核查完成（最新）

### 本轮结论

- `Goldstein` 这一本已经完成逐书核查：
  - `python3 scripts/test_fnm_batch.py --slug Goldstein`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Goldstein --full`：`can_ship=True, blocking=0, major=0`
- 当前 [output/fnm_book_audits/Goldstein.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Goldstein.md) 与最新批测结果已经一致：
  - 9 个章节文件全部通过全量审计
  - `latest.fnm.obsidian.zip` 已重新落盘

### 这轮确认到的情况

- 第一轮全量审计最初报出 6 个 `raw_note_marker_leak`
  - 集中在 `001/002/003/004/005/008`
  - 复核后确认这些结果来自旧导出包，不是当前结构真相主链的新问题
- 单书重新跑完 pipeline、占位翻译和导出后：
  - 上述 6 个问题已全部消失
  - 最新 zip 审计恢复为 `blocking=0, major=0`
- 因此这一本本轮**不需要新增代码修复**
  - 当前更重要的是继续坚持“每本书先重跑单书，再做全量审计”的顺序

### 当前验证

- `python3 scripts/test_fnm_batch.py --slug Goldstein`：通过
- `python3 scripts/audit_fnm_exports.py --slug Goldstein --full`：`can_ship=True, blocking=0, major=0`

### 下一步

- `Goldstein` 已清到 `blocking=0, major=0`
- 按既定顺序继续进入：
  - `Heidegger_en_France`

## 2026-04-11 Germany_Madness 逐书核查完成（最新）

### 本轮结论

- `Germany_Madness` 这一本已经完成逐书核查：
  - `python3 scripts/test_fnm_batch.py --slug Germany_Madness`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Germany_Madness --full`：`can_ship=True, blocking=0, major=0`
- 当前 [output/fnm_book_audits/Germany_Madness.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Germany_Madness.md) 与最新批测结果已经一致：
  - 8 个章节文件全部通过全量审计
  - `latest.fnm.obsidian.zip` 已重新落盘

### 这轮确认到的情况

- 第一轮全量审计最初报出 6 个 `raw_note_marker_leak`
  - 集中在 `001/002/003/004/006/007`
  - 复核后确认这些结果来自旧导出包，不是当前结构真相主链的新增问题
- 单书重新跑完 pipeline、占位翻译和导出后：
  - 上述 6 个问题已全部消失
  - 最新 zip 中不再存在对应 `blocking`
- 因此这一本本轮**不需要新增代码修复**
  - 只需要把“先重跑该书，再做全量审计”这一步继续当成固定流程执行

### 当前验证

- `python3 scripts/test_fnm_batch.py --slug Germany_Madness`：通过
- `python3 scripts/audit_fnm_exports.py --slug Germany_Madness --full`：`can_ship=True, blocking=0, major=0`

### 下一步

- `Germany_Madness` 已清到 `blocking=0, major=0`
- 按既定顺序继续进入：
  - `Goldstein`

## 2026-04-11 Biopolitics 逐书收口完成（最新）

### 本轮结论

- `Biopolitics` 这一本已经完成逐书收口：
  - `python3 scripts/test_fnm_batch.py --slug Biopolitics`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Biopolitics --full`：`can_ship=True, blocking=0, major=0`
- 当前 [output/fnm_book_audits/Biopolitics.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Biopolitics.md) 与批测结果已经一致：
  - 12 个 lecture 章节文件全部通过全量审计
  - `latest.fnm.obsidian.zip` 已重新落盘
  - 此前卡住的 `footnote_orphan_note`、`21 mars` raw marker 泄漏、`28 mars` 缺尾问题已清零

### 这轮真正修到位的点

- 混合页不再重复补建 `footnote_band`
  - 当前 `_build_fallback_footnote_regions()` 会把已被 `chapter_endnotes / book_endnotes` 覆盖的页一并视作已覆盖
  - 不再对同一页重复补建 `footnote_band`
  - 这修掉了 `fn-0006 / fn-0007` 这类孤注，`footnote_orphan_note` 已清零
- `book_endnotes` 的混合起始页现在会保留 `NOTES` 之前的正文
  - `build_fnm_notes_and_units_from_structure()` 现在会把 `book_endnotes` 与 `chapter_endnotes` 一样视作正文尾页截断点
  - `LEÇON DU 28 MARS 1979` 不再把 `bookPage 302` 的正文尾巴丢掉
  - 这修掉了此前 `chapter_boundary_missing_tail` 的真实根因
- `21 mars` 的 continuation endnotes 现在会并入原有 `book_endnotes`
  - `281-282` 这类紧邻已有 `book_endnotes` 的续页，当前会补建为同 kind 的 continuation region 并合并
  - `LEÇON DU 21 MARS 1979` 的 note markers 现已恢复到 `1..37`
- 导出审计不再把尾注定义里的序数上标误判成 raw note marker
  - 例如 `I¹ª partie` 这类真实书目写法，不再触发 `raw_note_marker_leak`
  - 同时正文区对 raw `[n]` / superscript marker 的拦截保持不放松

### 这轮新增守卫测试

- [tests/unit/test_fnm_structure.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_structure.py)
  - `test_fallback_footnote_regions_skip_page_already_covered_by_chapter_endnotes`
  - `test_fallback_note_regions_extend_adjacent_book_endnotes_even_when_chapter_has_footnote_bands`
  - `test_biopolitics_21_mars_book_endnotes_keep_tail_markers_through_37`
- [tests/unit/test_fnm_pipeline.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_pipeline.py)
  - `test_book_endnote_start_page_keeps_body_prefix_in_structured_units`
- [tests/unit/test_fnm_export_audit.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_export_audit.py)
  - `test_audit_markdown_file_ignores_definition_ordinal_superscripts`

### 当前验证

- `python3 -m unittest tests.unit.test_fnm_structure.FnmStructureTest.test_fallback_note_regions_extend_adjacent_book_endnotes_even_when_chapter_has_footnote_bands tests.unit.test_fnm_structure.FnmStructureTest.test_biopolitics_21_mars_book_endnotes_keep_tail_markers_through_37 -q`：通过
- `python3 -m unittest tests.unit.test_fnm_pipeline.FnmPipelineTest.test_book_endnote_start_page_keeps_body_prefix_in_structured_units tests.unit.test_fnm_export_audit.FnmExportAuditTest.test_audit_markdown_file_ignores_definition_ordinal_superscripts -q`：通过
- `python3 -m unittest tests.unit.test_fnm_pipeline tests.unit.test_fnm_export_audit -q`：通过
- `python3 scripts/test_fnm_batch.py --slug Biopolitics`：通过
- `python3 scripts/audit_fnm_exports.py --slug Biopolitics --full`：`can_ship=True, blocking=0, major=0`

### 下一步

- `Biopolitics` 已清到 `blocking=0, major=0`
- 按既定顺序继续进入：
  - `Germany_Madness`

## 2026-04-11 Neuropsychoanalysis_Introduction 逐书收口完成（最新）

### 本轮结论

- `Neuropsychoanalysis_Introduction` 这一本已经完成逐书收口：
  - `python3 scripts/test_fnm_batch.py --slug Neuropsychoanalysis_Introduction`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Neuropsychoanalysis_Introduction --full`：`can_ship=True, blocking=0, major=0`
- 当前 [output/fnm_book_audits/Neuropsychoanalysis_Introduction.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Neuropsychoanalysis_Introduction.md) 与批测结果已经一致：
  - 9 个章节文件全部通过全量审计
  - `latest.fnm.obsidian.zip` 已重新落盘
  - 此前卡住的 bibliography tail / 假吞章误报已清零

### 这轮真正修到位的点

- 导出全量审计现在能识别“章节尾部 references 条目”，不会再把 bibliography entry 误判成 `chapter_boundary_missing_tail`
  - 这修掉了 `Introduction / Attachment and trauma / Unconscious and conscious / Conclusion` 4 章此前的同类误报
- `chapter_boundary_swallow_next` 的审计口径已经收紧为“只检查真正的 heading 行，且只比对紧邻下一章标题”
  - 不再把章内常见的 `Introduction / Conclusion` 小节或裸行标签误判成“吞入下一章”
  - 这修掉了 `Schizophrenia and depression` 章节里最后一个剩余 blocking 误报
- 当前审计脚本对这类教材/导论型书更稳：
  - 允许每章尾部保留真实的 references 列表
  - 同时仍保留对真正目录残片、front matter 泄漏、raw `[n]`、局部注释闭合错误的强拦截

### 这轮新增守卫测试

- [tests/unit/test_fnm_export_audit.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_export_audit.py)
  - `test_audit_markdown_file_does_not_flag_bibliography_entry_tail_as_missing_chapter_tail`
  - `test_audit_markdown_file_does_not_flag_book_reference_tail_without_trailing_period`
  - `test_audit_markdown_file_ignores_generic_inner_heading_that_matches_non_next_chapter`
  - `test_audit_markdown_file_ignores_plain_line_that_matches_next_chapter_title`

### 当前验证

- `python3 -m unittest tests.unit.test_fnm_export_audit -q`：通过
- `python3 scripts/audit_fnm_exports.py --slug Neuropsychoanalysis_Introduction --full`：`can_ship=True, blocking=0, major=0`
- `python3 scripts/test_fnm_batch.py --slug Neuropsychoanalysis_Introduction`：通过

### 下一步

- `Neuropsychoanalysis_Introduction` 已清到 `blocking=0, major=0`
- 当前 8 本里还没收净的，回到顺序最靠前的：
  - `Biopolitics`
  - 当前剩余 `3` 个 `major`，都属于 lecture 末尾正文尾巴被误判成 `chapter_boundary_missing_tail`

## 2026-04-11 Neuropsychoanalysis_in_Practice 逐书收口完成（最新）

### 本轮结论

- `Neuropsychoanalysis_in_Practice` 这一本已经完成逐书收口：
  - `python3 scripts/test_fnm_batch.py --slug Neuropsychoanalysis_in_Practice`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Neuropsychoanalysis_in_Practice --full`：`can_ship=True, blocking=0, major=0`
- 当前 [output/fnm_book_audits/Neuropsychoanalysis_in_Practice.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Neuropsychoanalysis_in_Practice.md) 与批测结果已经一致：
  - 14 个章节文件全部通过全量审计
  - `latest.fnm.obsidian.zip` 已重新落盘
  - 此前卡住的 `1 blocking + 2 major` 已全部清零

### 这轮真正修到位的点

- 结构层现在会把“脚注字段不完整、但 markdown 尾部还有脚注定义”的页面合并处理：
  - 不再只信 `footnotes` 或 `prunedResult.footnote`
  - 会继续从 markdown 尾部补入缺失的脚注定义行
  - 这修掉了第 2 章 `page 46` 里只抓到 `12`、漏掉 `11/13` 的问题
- 独立脚注定义行现在会按 marker 顺序归并：
  - 当同页候选链里同时出现 `11 / 12 / 13` 这类独立定义行时，会先排序再重建 note items
  - 不再因为“先遇到 12，再遇到 11”就把 `11` 错判成 `13`
- 正文页构建现在会剥离页尾脚注定义块：
  - `footnote_band` 或混合页里的页尾脚注定义，不再残留到正文导出
  - 第 2 章 `Arthur Schopenhauer ... [11]` 那种 raw marker 泄漏已清零
- 章节 gap 过渡页会回挂上一章正文前缀：
  - 当 `chapter_end + 1 .. next_start - 1` 之间出现 `front_matter` 过渡页，且 heading 前仍有上一章正文尾巴时，当前会把这段正文回挂上一章
  - 同时会剥掉图片/图题脚手架和 heading 之后的 `Acknowledgments`
  - 这修掉了第 8、12 章的 `chapter_boundary_missing_tail`

### 这轮新增守卫测试

- [tests/unit/test_fnm_structure.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_structure.py)
  - `test_footnote_candidate_lines_merge_markdown_tail_note_defs_when_footnotes_field_is_partial`
  - `test_footnote_candidate_lines_merge_markdown_tail_note_defs_even_with_pruned_footnote_block`
  - `test_footnote_candidate_lines_sort_standalone_definition_lines_by_marker`
- [tests/unit/test_fnm_pipeline.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_pipeline.py)
  - `test_body_page_strips_trailing_footnote_definition_block`
  - `test_gap_front_matter_page_keeps_body_prefix_before_acknowledgments_heading`

### 当前验证

- `python3 -m unittest tests.unit.test_fnm_structure.FnmStructureTest.test_footnote_candidate_lines_merge_markdown_tail_note_defs_when_footnotes_field_is_partial tests.unit.test_fnm_structure.FnmStructureTest.test_footnote_candidate_lines_merge_markdown_tail_note_defs_even_with_pruned_footnote_block tests.unit.test_fnm_structure.FnmStructureTest.test_footnote_candidate_lines_sort_standalone_definition_lines_by_marker -q`：通过
- `python3 -m unittest tests.unit.test_fnm_pipeline.FnmPipelineTest.test_body_page_strips_trailing_footnote_definition_block tests.unit.test_fnm_pipeline.FnmPipelineTest.test_gap_front_matter_page_keeps_body_prefix_before_acknowledgments_heading -q`：通过
- `python3 scripts/test_fnm_batch.py --slug Neuropsychoanalysis_in_Practice`：通过
- `python3 scripts/audit_fnm_exports.py --slug Neuropsychoanalysis_in_Practice --full`：`can_ship=True, blocking=0, major=0`

### 下一步

- `Neuropsychoanalysis_in_Practice` 已清到 `blocking=0`
- 按既定顺序继续进入：
  - `Neuropsychoanalysis_Introduction`

## 2026-04-11 Napoleon 逐书收口完成（最新）

### 本轮结论

- `Napoleon` 这一本已经完成逐书收口：
  - `python3 scripts/test_fnm_batch.py --slug Napoleon`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Napoleon --full`：`can_ship=True, blocking=0, major=0`
- 当前 [output/fnm_book_audits/Napoleon.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Napoleon.md) 与批测结果已经一致：
  - 6 个章节文件全部通过全量审计
  - `latest.fnm.obsidian.zip` 已重新落盘
  - `Préambule` 已稳定回锚到真实标题页，最后一章不再吞入尾部目录页和作者宣传页

### Napoleon 这轮真正修到位的点

- 页内脚注候选文本源已经补齐 `footer` 回退：
  - 当 `prunedResult.footnote` 和 `footnotes` 都不给力时，当前会从 `prunedResult.parsing_res_list` 的 `footer` blocks 里恢复真正脚注定义
  - 这修掉了 `page 286 / 338` 那类“脚注只存在于 footer、结构层却漏掉”的问题
- manual toc 的弱 resolved 项现在会优先回锚到真实标题页：
  - `Préambule` 不再因为同页 `visual_toc` 候选误判成“已有精确标题”
  - 当前能稳定回锚到 `page 7`
- 章节页内容切片改成 heading-aware：
  - 当前章首个页面如果页内有本章标题，会从标题行开始裁切
  - 下一章起始页上标题之前的正文尾巴，会回挂给前一章
  - 这直接修掉了 `1848 ...` 从半句话开头，以及 `1830 ...` 尾巴缺失的问题
- 尾部目录页、作者宣传页、稀疏垃圾页已从最后一章剥离：
  - `rear_toc_tail`
  - `rear_author_blurb`
  - `rear_sparse_other`
  都已进入 `other`，不再混入 `V. La raison insurgée`
- 导出侧新增了词首 OCR 污点修复：
  - `[1]es`
  - `[1]l'économie`
  这类 bracket noise 会在导出前按词首噪点清掉，不再误留在正文里

### 这轮新增守卫测试

- [tests/unit/test_fnm_structure.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_structure.py)
  - `test_footnote_candidate_lines_fallback_to_footer_blocks_when_no_footnote_payload`
  - `test_resolve_visual_toc_target_page_reanchors_to_exact_heading_when_current_page_lacks_match`
  - `test_apply_page_role_overrides_marks_rear_toc_tail_and_author_blurb_as_other`
- [tests/unit/test_fnm_pipeline.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_pipeline.py)
  - `test_start_page_is_trimmed_to_matching_heading_inside_page`
  - `test_previous_chapter_keeps_pre_heading_tail_from_next_chapter_start_page`
- [tests/unit/test_fnm_export.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_export.py)
  - `test_repair_word_initial_bracket_ocr_noise_recovers_common_french_article_forms`

### 当前验证

- `python3 -m unittest tests.unit.test_fnm_structure.FnmStructureTest.test_footnote_candidate_lines_fallback_to_footer_blocks_when_no_footnote_payload tests.unit.test_fnm_structure.FnmStructureTest.test_resolve_visual_toc_target_page_reanchors_to_exact_heading_when_current_page_lacks_match tests.unit.test_fnm_structure.FnmStructureTest.test_apply_page_role_overrides_marks_rear_toc_tail_and_author_blurb_as_other tests.unit.test_fnm_pipeline.FnmPipelineTest.test_start_page_is_trimmed_to_matching_heading_inside_page tests.unit.test_fnm_pipeline.FnmPipelineTest.test_previous_chapter_keeps_pre_heading_tail_from_next_chapter_start_page -q`：通过
- `python3 -m unittest tests.unit.test_fnm_export tests.unit.test_fnm_pipeline tests.unit.test_fnm_structure.FnmStructureTest.test_footnote_candidate_lines_fallback_to_footer_blocks_when_no_footnote_payload tests.unit.test_fnm_structure.FnmStructureTest.test_resolve_visual_toc_target_page_reanchors_to_exact_heading_when_current_page_lacks_match tests.unit.test_fnm_structure.FnmStructureTest.test_apply_page_role_overrides_marks_rear_toc_tail_and_author_blurb_as_other -q`：`43 tests OK`
- `python3 scripts/test_fnm_batch.py --slug Napoleon`：通过
- `python3 scripts/audit_fnm_exports.py --slug Napoleon --full`：`can_ship=True, blocking=0, major=0`

### 下一步

- `Napoleon` 已清到 `blocking=0`
- 按既定顺序继续进入：
  - `Neuropsychoanalysis_in_Practice`

## 2026-04-11 Mad_Act 逐书收口完成（最新）

### 本轮结论

- `Mad_Act` 这一本已经完成逐书收口：
  - `python3 scripts/test_fnm_batch.py --slug Mad_Act`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Mad_Act --full`：`can_ship=True, blocking=0, major=0`
- 当前 [output/fnm_book_audits/Mad_Act.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Mad_Act.md) 与批测结果已经一致：
  - 7 个章节文件全部通过全量审计
  - raw `[n]` 泄漏已清零
  - `latest.fnm.obsidian.zip` 已重新落盘

### Mad_Act 这轮真正修到位的点

- 页内脚注候选文本源已经收口：
  - 当 `prunedResult.footnote` 已存在时，不再继续混入 `footnotes` 字段里的 garbled OCR 文本
  - 这直接修掉了 `page 633` 那类被 `6 / 87 / 524 / 1862` 垃圾 marker 拖偏的问题
- 页首 continuation 行里中段才开始的新 marker 现在可以恢复：
  - 典型场景是 `page 447` 风格的 continuation 文本中间出现 `$ ^{22} $`
  - 当前 parser 会拆出真正的新 note，而不是把整行当上一条尾巴丢掉
- 远端 `book_endnotes` 不再反向污染已经是 `footnote_band` 的章节：
  - `Madness multiple` 不再被压成 `mixed_or_unclear`
  - 当前 7 章都回到 `footnote_primary`
  - `[4] / [5]` 这类正文锚点也不再被误判成 endnote

### 这轮新增守卫测试

- [tests/unit/test_fnm_structure.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_structure.py)
  - `test_parse_footnote_page_items_recovers_marker_that_starts_mid_continuation_line`
  - `test_footnote_candidate_lines_prefer_pruned_blocks_over_garbled_footnotes_field`
  - `test_mad_act_manual_toc_footnote_band_chapters_stay_footnote_primary`

### 当前最新结构画像

- `Mad_Act` 现状：
  - `chapters=7`
  - `chapter_note_modes`：
    - `footnote_primary=7`
    - `mixed_or_unclear=0`
- 最新单书批测结构摘要：
  - `note_items=544`
  - `anchors=639`
  - `matched=720`
  - `footnote_orphan_note=0`
  - `footnote_orphan_anchor=0`
  - `endnote_orphan_note=0`
  - `endnote_orphan_anchor=0`

### 当前验证

- `python3 -m unittest tests.unit.test_fnm_structure.FnmStructureTest.test_parse_footnote_page_items_recovers_marker_that_starts_mid_continuation_line tests.unit.test_fnm_structure.FnmStructureTest.test_footnote_candidate_lines_prefer_pruned_blocks_over_garbled_footnotes_field tests.unit.test_fnm_structure.FnmStructureTest.test_mad_act_manual_toc_footnote_band_chapters_stay_footnote_primary -q`：通过
- `python3 scripts/test_fnm_batch.py --slug Mad_Act`：通过
- `python3 scripts/audit_fnm_exports.py --slug Mad_Act --full`：`can_ship=True, blocking=0, major=0`

### 下一步

- `Mad_Act` 已清到 `blocking=0`
- 可以按既定顺序继续进入下一本

## 2026-04-11 Heidegger_en_France 逐书收口完成（最新）

### 本轮结论

- `Heidegger_en_France` 这一本已经完成逐书收口：
  - `python3 scripts/test_fnm_batch.py --slug Heidegger_en_France`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Heidegger_en_France --full`：`can_ship=True, blocking=0, major=0`
- 当前 [output/fnm_book_audits/Heidegger_en_France.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Heidegger_en_France.md) 与批测结果已经一致：
  - 12 个主章节保持不变
  - raw `[n]` / unicode superscript 泄漏已清零
  - `latest.fnm.obsidian.zip` 已重新落盘

### Heidegger 这轮真正修到位的点

- 结构层不再把**未被消费的 synthetic footnote anchors**计入 `footnote_orphan_anchor`：
  - 这 46 条原先的阻塞项本质上是结构层自动补出的噪声锚点
  - 现在只有真实显式锚点还会进入 orphan review
- 新增了 page-local 三位数 OCR 假高标记修复：
  - 典型场景是 `page 108` 的正文 `[122]`
  - 当前会按同页 footnote items 的最佳相似候选修回 `102`
  - 修复后对应显式 anchor 会重新接管 matched link
- 导出侧剩余的 `raw_note_marker_leak` 已随结构修复一起清掉：
  - 第 4 章 `3. Les fascinations de l'après-guerre` 不再残留 `[122]`
  - 全书目前仅保留正常的文本型 `<sup>th</sup>`，不会再被当成脚注泄漏

### 这轮新增守卫测试

- [tests/unit/test_fnm_structure.py](/Users/hao/OCRandTranslation/tests/unit/test_fnm_structure.py)
  - `test_append_orphan_anchor_links_ignores_unused_synthetic_footnote_anchors`
  - `test_repair_ocr_shortened_footnote_anchors_repairs_single_three_digit_outlier_by_similarity`
- 相关旧守卫测试也已重跑通过：
  - `test_germany_and_heidegger_keep_matched_footnotes_while_reducing_orphan_anchors`
  - `test_section_markdown_strips_trailing_image_only_block`

### 当前验证

- `python3 -m unittest tests.unit.test_fnm_structure.FnmStructureTest.test_append_orphan_anchor_links_ignores_unused_synthetic_footnote_anchors tests.unit.test_fnm_structure.FnmStructureTest.test_repair_ocr_shortened_footnote_anchors_repairs_single_three_digit_outlier_by_similarity tests.unit.test_fnm_structure.FnmStructureTest.test_germany_and_heidegger_keep_matched_footnotes_while_reducing_orphan_anchors -q`：通过
- `python3 -m unittest tests.unit.test_fnm_export.FnmObsidianFootnotePlacementTest.test_raw_bracket_replacement_accepts_original_anchor_source_marker_alias tests.unit.test_fnm_export.FnmObsidianFootnotePlacementTest.test_section_markdown_strips_trailing_image_only_block -q`：通过
- `python3 scripts/test_fnm_batch.py --slug Heidegger_en_France`：通过
- `python3 scripts/audit_fnm_exports.py --slug Heidegger_en_France --full`：`can_ship=True, blocking=0, major=0`

### 下一步

- 按既定顺序继续进入：
  - `Mad_Act`
- 继续坚持当前闭环：
  - 先全量审计该书 zip
  - 再补测试
  - 再修
  - `blocking=0` 后才进入下一本

## 2026-04-11 Goldstein 收口完成 + Heidegger 首轮全量审计（最新）

### Goldstein 当前结论

- `Goldstein` 这一本已经完成逐书收口：
  - `python3 scripts/test_fnm_batch.py --slug Goldstein`：通过
  - `python3 scripts/audit_fnm_exports.py --slug Goldstein --full`：`can_ship=True, blocking=0, major=0`
- 当前最新 [output/fnm_book_audits/Goldstein.md](/Users/hao/OCRandTranslation/output/fnm_book_audits/Goldstein.md) 已确认：
  - 9 个正文章节 + `index.md`
  - raw `[n]` 已清零
  - 本地 `[^n]` 与章末定义闭合
  - `Introduction / Epilogue` 与书末 `Notes` 的 chapter-local 绑定已稳定

### Goldstein 这轮真正修到位的点

- 书末 `Notes` 已按页内 chapter heading 切成多个 `book_endnotes` 子区，而不是继续当成 `Epilogue` 的单一尾注区。
- `book_endnotes` 的 fallback link 已按 chapter-local marker 起作用，重复编号不再跨章互相抢占。
- 当前 `Introduction` notes region 跨到 `351` 页是**预期行为**：
  - 同页 split 后会通过 `_page_text_overrides` 切片
  - 因此 region `pages` 会和相邻子区重叠一页
  - 对应测试已改成断言“前 3 页固定 + 包含 351”

### Heidegger_en_France 当前首轮审计结果

- `python3 scripts/audit_fnm_exports.py --slug Heidegger_en_France --full`：
  - `can_ship=False`
  - `blocking=12`
  - 当前尚未进入可交付状态
- 当前阻塞画像已经明确，不再是目录主层问题，而是导出正文质量问题：
  - `Introduction`：
    - `mid_sentence_opening`
    - `raw_note_marker_leak`
    - `chapter_boundary_missing_tail`
  - `002-011`：
    - 主要都是 `raw_note_marker_leak`
  - `012`：
    - `toc_residue`
    - `raw_note_marker_leak`
    - `chapter_boundary_missing_tail`

### Heidegger 已确认的根因

- `Introduction` 的起点被结构层裁到了 `body` 页：
  - 真实标题页在 `PDF 7`
  - 当前章节从 `PDF 10` 开始
  - 原因是 chapter span 当前优先使用 `body_span_pages`，把属于 `front_matter` 的引言首页切掉了
- 脚注原文里存在 OCR 断号/短号：
  - 例如 `1.30 / 1.31 / 13 5 / 13 6 / 13 9`
  - 结构层当前不能把这些形式稳定还原为 `130 / 131 / 135 / 136 / 139`
- 同页正文脚注锚点还存在 OCR 短号：
  - 例如正文锚点是 `2 / 3 / 4`
  - 对应脚注实际是 `12 / 13 / 14`
  - 当前主链没有把这种短号修复真正挂回 `build_fnm_structure()`
- 第 12 章结尾的 `mid_sentence_opening / chapter_boundary_missing_tail`
  - 根因不是目录，而是 chunk 组装时把 `consumed_by_prev=True` 的段落碎片带进了新的 body unit
- 第二轮继续确认后，`Heidegger` 的 raw marker 阻塞已经拆成 3 类明确根因：
  - `front_matter` 页（尤其 `Introduction` 的 `7/8/9`）虽然已经识别为 `body_with_page_footnotes`，但旧 fallback 只靠 visible body anchor 建 region/item，导致这些页的脚注区没有进入 `fnm_note_regions / fnm_note_items`
  - 页脚脚注正文里仍有 OCR 异形前缀没有被解析：
    - 例如 `.38. ...`
    - 例如 `118 Pour ...`
    - 例如 `, 103. ...`
  - 同页显式 footnote anchor 和 page-local note items 之间还存在顺序漂移：
    - 典型例子是 page `218` 的 `29 / 221 / 125 / 126`
    - 实际应重绑到 `123 / 124 / 125 / 126`
  - 这些问题会直接导致导出里残留 raw `[221] / [109] / [38] / [118]` 或 unicode superscript `¹ / ¹¹⁸`

### Heidegger 下一步主攻方向

- 先修导出层 raw marker 重写，目标是把 12 章里的 raw `[n]` 清零。
- 再修章节边界裁切：
  - `Introduction` 不能从半句话开头
  - `012` 不能再吞进书后目录/书单残片
- 章节主骨架暂时不动，继续保住现有 12 个主章与大部分 section heads。

## 2026-04-11 Germany_Madness 逐书审计收口（最新）

### 本轮结论

- 8 本逐书逐文件审计当前已完成：
  - `Biopolitics`
  - `Germany_Madness`
- `Germany_Madness` 当前已经收口完成：
  - standalone full audit：`blocking=0`
  - `python3 scripts/test_fnm_batch.py --slug Germany_Madness`：通过
- 这一步完成后，顺序执行可以继续进入下一本：
  - `Goldstein`

### Germany_Madness 这次真正修掉的问题

- 最后一条阻塞不是目录或章节骨架，而是 chapter 001 的脚注提取缺口：
  - page 63 的 `56. Ibid.` 在 OCR 里落进了 `paragraph_title`
  - 同页脚注首行的 `§7.` 实际是 OCR 误识别的 `57.`
- 结构层已修复：
  - `fnm_structure.py` 现在会在显式 `footnotes` 之外，补抓 note-like `paragraph_title`
  - `§` 现在会按 OCR 误识别修正规则转换为 `5`
- 导出层已修复：
  - 正文 `$^{56}$` / `<sup>56</sup>` 这类 raw superscript marker 现在会改写为本地 `[^n]`
  - 同 marker 的干净 note region 文本会覆盖脏 linked note 文本

### 这次顺手收口的批测 gate

- `test_fnm_batch.py` 的 `verify_export()` 之前存在一处 gate 漂移：
  - 预审诊断信号里的 `duplicate_paragraph_detected=True`
  - 会直接把导出判失败
  - 即使新的 full audit 已经确认 `can_ship=True`
- 当前已改成：
  - 机械合同仍由 batch 内部先校验
  - 语义是否可发，以 full audit 的 `blocking=0 / can_ship=True` 为最终裁决
  - 预审布尔信号继续保留在结果里，只作为诊断摘要，不再单独推翻 full audit

### 当前验证

- `python3 -m unittest tests.unit.test_fnm_batch_report -q`：通过
- `python3 scripts/test_fnm_batch.py --slug Germany_Madness`：通过
- 当前 [output/fnm_batch_test_result.json](/Users/hao/OCRandTranslation/output/fnm_batch_test_result.json) 中：
  - `Germany_Madness.all_ok = true`
  - `export.ok = true`
  - `full_audit_can_ship = true`
  - `full_audit_blocking_issue_count = 0`

### 下一步

- 按既定顺序继续进入：
  - `Goldstein`
- 仍然坚持当前闭环：
  - 先全量审计该书 zip
  - 再补测试
  - 再修
  - `blocking=0` 后才进入下一本

## 2026-04-11 代码结构收官重构（最新）

### 当前主线

- 标准主线：
  - 上传 / OCR / 普通翻译 / 阅读 / 导出
- FNM 主线：
  - 手动目录输入
  - 视觉目录解析
  - 结构真相建模
  - 顺序翻译
  - Obsidian 导出
  - 首页进度展示

### 本轮已完成

- 旧 FNM 持久化表已删除：
  - `fnm_notes`
  - `fnm_page_entries`
  - `fnm_page_revisions`
- SQLite schema 已升到 `19`
- FNM 正式导出已收口为只读结构真相层：
  - `fnm_chapters`
  - `fnm_section_heads`
  - `fnm_note_regions`
  - `fnm_note_items`
  - `fnm_note_links`
  - `fnm_translation_units`
- `fnm_translation_units` 已固定采用 `owner_kind / owner_id`，区分：
  - `chapter`
  - `note_region`
- FNM 诊断页已改成只读：
  - `reading?view=fnm` 保留
  - `GET/POST /api/page_editor?view=fnm` 与历史接口已下线
- FNM 首页默认入口保持 `fnm_progress`
- 手动目录已成为 FNM 正式主链前置条件：
  - 无手动目录时，`manual_toc_required=true`
  - 真实翻译与正式导出必须阻塞
- 新增 [docs/code-ownership.md](/Users/hao/OCRandTranslation/docs/code-ownership.md) 作为模块归属清单：
  - `mainline`
  - `diagnostic`
  - `legacy_to_remove`

### 当前验证状态

- unit 全量：已通过
- integration 全量：已通过
- 8 本批测：已重跑，当前结果 `8 通过, 0 未通过`
- 详细结果仍以 [output/fnm_batch_test_result.md](/Users/hao/OCRandTranslation/output/fnm_batch_test_result.md) 和 [output/fnm_batch_test_result.json](/Users/hao/OCRandTranslation/output/fnm_batch_test_result.json) 为准

### 当前仍需继续优化的方向

- 这轮“代码结构大扫除”已经完成，后续不再优先做旧链清理
- 后续重点改为：基于手动目录和 8 本样本反馈继续做结构质量优化
- 当前最值得持续盯的书：
  - `Biopolitics`
  - `Heidegger_en_France`

### 维护约定

- `PROGRESS.md` 以后只保留当前口径，不再累积历史阶段总结
- 历史验证数字统一放 [verification.md](/Users/hao/OCRandTranslation/verification.md)
- 稳定结构说明统一放 [DEV.md](/Users/hao/OCRandTranslation/DEV.md)
# 2026-04-12 手动目录组织方式重构推进（进行中）

- 已补第一批失败测试并转绿，覆盖：
  - `visual_toc` 保留 `container/post_body`
  - `generate_visual_toc_snapshots` 输出 `organization_summary`
  - `fnm_structure` 尊重显式 `container/post_body`
  - `fnm_export_audit` 对缺失 `post_body` 报阻塞
- 当前已落地第一版实现：
  - `pipeline/visual_toc.py` 新增目录组织方式标注，输出 `role_hint / parent_title / body_candidate / export_candidate / organization_summary / organization_nodes`
  - `scripts/generate_visual_toc_snapshots.py` 新增“组织方式”快照输出
  - `fnm/fnm_structure.py` 开始按显式角色消费目录项，`container` 不再直接导出，`post_body` 可进入导出候选
  - `fnm/fnm_export_audit.py` 新增 `missing_post_body_export / container_exported_as_chapter / export_depth_too_shallow / toc_organization_mismatch`
- 进行中的真实书验证新发现：
  - `Biopolitics` 手动目录重刷结果已经识别出：
    - `container_titles = ["COURS, ANNÉE 1978-1979"]`
    - `post_body_titles = ["RÉSUMÉ DU COURS", "SITUATION DES COURS"]`
    - `back_matter_titles = ["Index des notions", "Index des noms de personnes"]`
  - 但当前样本目录中的 `latest.fnm.obsidian.zip` 仍只有 12 个 lecture，没有 `RÉSUMÉ / SITUATION`
  - 这说明当前新的目录组织方式已经进入视觉目录结果，但还没有完整落进 FNM 结构/导出层
  - `python3 scripts/test_fnm_batch.py --slug Biopolitics` 最新实测：
    - 当前最新一轮已经变化为：`sections=13, notes=362, units=401`
    - `structure_state=review_required`
    - `blocking=["footnote_orphan_note", "boundary_review_required"]`
    - `toc_coverage / toc_alignment / toc_semantic` 当前整组掉成 `0`
    - 这说明新的目录组织方式已经开始影响 pipeline，但 visual TOC 对齐摘要链被打空了
    - 导出被 `structure_review_required` 阻塞，zip 未更新
- 当前优先级：
  1. 等 `Biopolitics` 本轮 FNM 重跑完成
  2. 直接核对 `documents.auto_toc_visual` / `fnm_chapters / toc_role_summary / export zip`
  3. 修正“组织方式进入视觉目录结果，但未进入结构/导出”的断点
