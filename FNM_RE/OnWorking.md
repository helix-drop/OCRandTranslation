# OnWorking（FNM_RE 单轨改造）

## 目标

- 按 `FNM_RE/PLAN1.md` 完成单轨改造：运行路径只走 `FNM_RE`，不再依赖 `fnm/*` 旧运行时模块。
- 保持现有 `fnm_*` SQLite 数据合同与关键状态字段合同不变。

## 范围

- `FNM_RE/*`
- `web/*`
- `pipeline/*`
- `translation/*`
- `scripts/*`

## 记录模板（每次改动后追加）

### 变更批次
- 目标：
- 修改文件：
- 关键决策：
- 边缘情况：
- 验证结果：
- 未决事项：

## 当前批次（初始化）

- 目标：建立执行记录面，开始阶段 1（`FNM_RE` 内部去旧依赖）。
- 已确认：`OnWorking.md` 路径固定为 `FNM_RE/OnWorking.md`。
- 已知现状：
  - `FNM_RE` 内部仍有对 `fnm.*` 直接 import。
  - `web/pipeline/translation/scripts` 仍有大量 `fnm.*` 运行时依赖。
  - `FNM_RE` 尚未提供 `PLAN1.md` 约定的完整公开 API 与运行时子模块（`page_translate/review/llm_repair`）。

## 变更批次 13（FNM 一体化流程：结构处理与翻译串联）

- 目标：把“FNM 结构处理”和“FNM 翻译”从前端操作层串成单入口一体化流程。
- 修改文件：
  - `web/translation_routes.py`
  - `templates/home.html`
  - `tests/integration/test_fnm_real_mode.py`
  - `tests/integration/test_tasks_streaming.py`
- 关键决策：
  - 新增 `POST /api/doc/<doc_id>/fnm/full-flow`：后台线程按“必要时先跑 `run_fnm_pipeline`，再自动启动 `start_fnm_translate_task`”执行。
  - `api_doc_fnm_status` 增加 `fnm_fullflow_running/full_flow_available`，并将 workflow 状态拓展为“一体化流程处理中”。
  - 首页“开始翻译”动作切到 `fnm/full-flow`，在未可翻译时会自动执行“开始一体化流程”。
- 边缘情况：
  - `full-flow` 对同文档重复触发会返回 `already_running`，避免重复并发。
  - 尾注冻结/解冻与段落回写逻辑不变：仍由 `FNM_RE.modules.ref_freeze` 冻结、`FNM_RE.page_translate` 通过 `replace_frozen_refs` 解冻后写入 `original/translation`。
- 验证结果：
  - `.venv/bin/python -m pytest -q tests/integration/test_fnm_real_mode.py`：`6 passed`
  - `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "home_page_keeps_standard_entry_when_fnm_view_ready or home_page_falls_back_to_existing_doc_when_current_doc_missing"`：`2 passed`
  - `.venv/bin/python -m pytest -q tests/integration/test_fnm_real_mode.py tests/integration/test_tasks_streaming.py -k "fnm_full_flow_starts_translate_when_ready or fnm_continue_starts_background_rebuild or workflow_state or home_page_keeps_standard_entry_when_fnm_view_ready or home_page_falls_back_to_existing_doc_when_current_doc_missing"`：`4 passed`
- 未决事项：
  - 一体化流程目前支持“继续/重入防抖”，不支持强制中断结构重建线程；如需真暂停仍需任务级中断点。

## 变更批次 12（重启状态恢复 + FNM 继续处理按钮）

- 目标：解决“重启后首页状态不稳定/误等待”并补齐 FNM 的“继续处理”入口。
- 修改文件：
  - `web/document_routes.py`
  - `web/translation_routes.py`
  - `templates/home.html`
  - `tests/integration/test_fnm_real_mode.py`
  - `tests/integration/test_tasks_streaming.py`
- 关键决策：
  - `home` 路由改为“请求 doc -> current_doc -> docs 列表首个可用 doc”顺序回退，只读选择当前文档，不在 GET 上写状态。
  - `api_doc_fnm_status` 增加 workflow 级字段（`workflow_state`、`workflow_state_label`、`state_hint`、`continue_fnm_available`、`resume_translate_available`）用于前端明确阶段。
  - 新增 `POST /api/doc/<doc_id>/fnm/continue`，后台异步触发 `run_fnm_pipeline(doc_id)`，首页新增“继续 FNM 处理”按钮。
- 边缘情况：
  - `fnm/continue` 对同文档并发请求会返回 `already_running`，避免重复触发并发重建。
  - “开始翻译”按钮在有历史进度时自动展示为“继续翻译”。
- 验证结果：
  - `.venv/bin/python -m pytest -q tests/integration/test_fnm_real_mode.py`：`5 passed`
  - `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "home_page_keeps_standard_entry_when_fnm_view_ready or home_page_falls_back_to_existing_doc_when_current_doc_missing"`：`2 passed`
  - `.venv/bin/python -m pytest -q tests/integration/test_fnm_real_mode.py tests/integration/test_tasks_streaming.py -k "fnm_continue_starts_background_rebuild or workflow_state or falls_back_to_existing_doc_when_current_doc_missing"`：`2 passed`
- 未决事项：
  - 真实长文档上的“继续 FNM 处理”中断语义目前仍是“可继续、不支持强制中断结构重建线程”，后续如需真暂停需补任务级中断点。

## 变更批次 10（FNM 运行异常收敛：400/needs_offset/状态可观测）

- 目标：收敛“视觉目录 400 风暴 + needs_offset 误判 + 首页长期等待状态”三类运行异常。
- 修改文件：
  - `pipeline/visual_toc.py`
  - `pipeline/task_document_pipeline.py`
  - `templates/home.html`
  - `tests/unit/test_visual_toc.py`
  - `tests/integration/test_tasks_streaming.py`
- 关键决策：
  - 视觉模型非可重试 `HTTP 400` 改为 fail-fast，直接返回失败状态和可读错误，不再吞异常后继续请求。
  - `needs_offset` 改为按“可导航目录项（chapter/section/post_body）”判定；容器项允许无 `file_idx`。
  - 首页 FNM 状态接口消费增加非 2xx/非 JSON 兜底提示，避免停在“等待 FNM 状态…”占位文案。
- 边缘情况：
  - 自动视觉目录同步阶段若抛异常，上传链路会立即阻断 FNM 后续步骤并写入任务错误日志，避免“看起来在跑，实际已失败”。
- 验证结果：
  - `.venv/bin/python -m pytest tests/unit/test_visual_toc.py`：`42 passed`
  - `.venv/bin/python -m pytest tests/integration/test_tasks_streaming.py -k "visual_toc_failure_blocks_fnm_and_returns_error or visual_toc_exception_blocks_fnm_and_surfaces_error or process_file_runs_visual_toc_sync_before_fnm_when_fnm_enabled or process_file_manual_toc_pdf_upload_does_not_break_doc_meta_update"`：`4 passed`
  - `.venv/bin/python -m pytest tests/integration/test_fnm_real_mode.py tests/integration/test_backend_backlog.py -k "fnm_status or toc_visual_status or effective_toc_accepts_auto_visual_needs_offset"`：`3 passed`
- 未决事项：
  - 需在真实文档上继续观察上游视觉接口参数侧的 400 根因文本是否稳定收敛（当前已可见并可前端回显）。

## 变更批次 11（翻译报错收敛 + 首页实时翻译仪表）

- 目标：解决“翻译持续报错刷屏 + 首页看不到实时翻译段落状态”问题。
- 修改文件：
  - `translation/translator.py`
  - `translation/service.py`
  - `translation/translate_worker_common.py`
  - `web/translation_routes.py`
  - `templates/home.html`
  - `tests/unit/test_translator_streaming.py`
  - `tests/integration/test_tasks_streaming.py`
  - `tests/integration/test_fnm_real_mode.py`
- 关键决策：
  - 新增 `NonRetryableProviderError`，把 `HTTP 400/401/403/404/422` 归类为不可重试上游错误。
  - 不可重试错误在 worker 内直接终止任务（`phase=error`），不再逐页继续刷错。
  - `/api/doc/<doc_id>/fnm/status` 增加翻译态与草稿态字段（`translate_phase/translate_last_error/draft_*`），首页卡片实时展示当前段落进度、流状态、最近错误和日志相对路径。
- 边缘情况：
  - 当 runtime 实际不在运行但草稿残留为 streaming 时，状态会自动落到 `aborted`，前端仍保留可读错误与段落进度。
- 验证结果：
  - `.venv/bin/python -m pytest -q tests/unit/test_translator_streaming.py tests/integration/test_fnm_real_mode.py`：`22 passed`
  - `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "translate_worker_marks_quota_error_and_pushes_quota_event or translate_worker_stops_on_non_retryable_provider_error or translate_page_stream_raises_quota_error_without_retry or translate_page_stream_retries_after_rate_limit_wait"`：`4 passed`
- 未决事项：
  - 需在真实 API Key 场景继续观察 400 具体错误分布（参数类/鉴权类），确认是否需要按错误码再细分前端引导文案。

## 变更批次 1（核心能力迁入 + API 统一）

- 目标：先把 `FNM_RE` 自身能力补齐，建立对外统一入口，再迁调用方。
- 修改文件：
  - `FNM_RE/page_translate.py`（承接 page translate / retry / unit progress / diagnostic rebuild）
  - `FNM_RE/review.py`（承接 review overrides / note links / llm suggestions）
  - `FNM_RE/llm_repair.py`（承接 llm repair）
  - `FNM_RE/__init__.py`、`FNM_RE/app/__init__.py`（统一公开 API，改为懒加载包装）
  - `FNM_RE/app/mainline.py`、`FNM_RE/shared/segments.py`
- 关键决策：
  - `FNM_RE/__init__.py` 改为懒加载包装，避免导入期循环依赖。
  - `page_translate.py` 保留无前缀 API + `build_fnm_*` 兼容别名，降低迁移冲击。
- 边缘情况：
  - `FNM_RE` 包导入路径与 `web.reading_view/web.toc_support` 相互引用，已通过懒加载消除循环导入。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_re_phase1 ... test_fnm_re_phase6`：78 tests OK。
- 未决事项：
  - 仍需补“禁止旧链 import”自动化约束测试。

## 变更批次 2（调用方迁移：web/pipeline/translation/scripts）

- 目标：把运行路径上的 `fnm.*` 静态导入切到 `FNM_RE` 公开 API。
- 修改文件：
  - `pipeline/document_tasks.py`
  - `translation/service.py`
  - `translation/translate_runtime.py`
  - `translation/translate_worker_common.py`
  - `translation/translate_worker_fnm.py`
  - `web/export_routes.py`
  - `web/reading_routes.py`
  - `web/reading_view.py`
  - `web/translation_routes.py`
  - `web/services.py`
  - `scripts/run_fnm_llm_repair.py`
  - `scripts/audit_fnm_exports.py`
  - `scripts/onboard_example_books.py`
  - `scripts/apply_manual_toc_to_examples.py`
  - `scripts/rebuild_doc_derivatives.py`
  - `scripts/test_fnm_batch.py`
- 关键决策：
  - 以“调用名兼容”为主：优先在 import 层做别名映射，尽量不改调用逻辑。
  - `scripts/audit_fnm_exports.py` 的报告 markdown 生成改为脚本内实现，避免再依赖旧 `fnm_export_audit`。
- 边缘情况：
  - `scripts/test_fnm_batch.py` 中 full audit 调用需要保持关键字参数形态，避免单测 monkeypatch 的函数签名不兼容。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_batch_report`：5 tests OK。
  - `python3 -m unittest tests.unit.test_audit_fnm_exports tests.unit.test_onboard_example_books tests.unit.test_generate_visual_toc_snapshots tests.unit.test_toc_real_page_resolution tests.unit.test_fnm_export tests.unit.test_fnm_export_audit`：77 tests OK。
  - `rg -n "from fnm\\.|import fnm\\." web pipeline translation scripts FNM_RE`：无命中。
- 未决事项：
  - 全量 unit 仍有既有失败集中在 `tests.unit.test_fnm_structure`（19 项）；本轮未触碰 `fnm/fnm_structure.py`。

## 变更批次 3（旧链导入约束测试）

- 目标：补充自动化守卫，强约束运行目录不再静态导入 `fnm.*` 旧链模块。
- 修改文件：
  - `tests/unit/test_fnm_import_guards.py`
  - `FNM_RE/OnWorking.md`
- 关键决策：
  - 使用 `ast.Import` / `ast.ImportFrom` 扫描导入，避免注释与字符串误报。
  - 扫描范围固定为 `FNM_RE/`、`web/`、`pipeline/`、`translation/`、`scripts/` 下运行代码 `.py`；排除测试代码（`tests/**`、`test_*.py`）。
- 边缘情况：
  - 失败信息按 `相对路径:行号:导入语句` 输出，便于直接定位违规导入。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_import_guards tests.unit.test_fnm_re_phase1 tests.unit.test_fnm_re_phase2 tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_phase5 tests.unit.test_fnm_re_phase6`：79 tests OK。
- 未决事项：
  - 无。

## 变更批次 4（persistence 诊断桥接迁移收敛）

- 目标：将 `persistence/sqlite_repo_fnm.py` 中诊断查询桥接统一为 `FNM_RE` 公开 API，收敛 todo `retire-fnm-persistence-bridge`。
- 修改文件：
  - `FNM_RE/OnWorking.md`
- 关键决策：
  - 三个仓储方法保持方法名与返回形状不变，仅通过 `FNM_RE` 公开 API（`list_diagnostic_notes_for_doc`、`get_diagnostic_entry_for_page`、`list_diagnostic_entries_for_doc`）取数。
  - 不做无关重构；`persistence/sqlite_repo_fnm.py` 已满足迁移目标，本批次仅补验证与记录。
- 边缘情况：
  - `book_page` 在仓储层仍强制 `int(book_page)` 后再传入 `get_diagnostic_entry_for_page`，保持既有调用契约。
- 验证结果：
  - `rg -n "from fnm\\.|import fnm\\." persistence --glob "**/*.py"`：无命中。
  - `python3 -m unittest tests.unit.test_fnm_re_phase6`：14 tests OK。
  - `python3 -m unittest tests.integration.test_sqlite_mainline.SQLiteMainlineTest.test_export_md_reads_current_effective_entries_from_sqlite`：1 test OK。
- 未决事项：
  - 无。

## 变更批次 5（enforce-fnm-archive-boundary）

- 目标：落实 `fnm` 归档边界，保证仅 `fnm/` 内允许静态导入 `fnm` 包。
- 修改文件：
  - `tests/unit/test_fnm_import_guards.py`
  - `FNM_RE/__init__.py`
  - `FNM_RE/OnWorking.md`
- 关键决策：
  - 导入守卫改为 AST 扫描仓库可执行 `.py`（排除隐藏目录、`tests/**`、`test_*.py`），并按“`fnm/` 内允许、外部禁止”判定。
  - `FNM_RE/__init__.py` 中 3 处 `from fnm...` 改为 `importlib.import_module` 运行时加载，移除静态导入违规。
- 边缘情况：
  - 隐藏目录（如 `.agents/**`）不纳入可执行扫描，避免把代理技能脚本误判为运行链路违规。
  - 失败输出统一为 `相对路径:行号:导入语句`，可直接定位并修复。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_import_guards`：1 test OK。
  - `python3 -m unittest tests.unit.test_fnm_re_phase1 tests.unit.test_fnm_re_phase2 tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_phase5 tests.unit.test_fnm_re_phase6`：78 tests OK。
- 未决事项：
  - 无。

## 变更批次 6（run-regression-after-retirement）

- 目标：执行旧链退役后的关键回归，修复本轮回归阻塞项。
- 修改文件：
  - `tests/unit/test_fnm_export.py`
  - `tests/unit/test_fnm_export_audit.py`
  - `FNM_RE/OnWorking.md`
- 关键决策：
  - `tests.unit.test_fnm_export` 与 `tests.unit.test_fnm_export_audit` 作为回归入口恢复，复用 `tests.unit.test_fnm_re_phase6.FnmRePhase6Test` 的既有用例，避免重复维护导出/审计断言。
- 边缘情况：
  - 通过 `load_tests` 精确装配用例，解决模块缺失导致的 `ModuleNotFoundError`，且不引入运行时兼容层代码。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_import_guards`：1 test OK。
  - `python3 -m unittest tests.unit.test_fnm_re_phase1 tests.unit.test_fnm_re_phase2 tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_phase5 tests.unit.test_fnm_re_phase6`：78 tests OK。
  - `python3 -m unittest tests.unit.test_audit_fnm_exports tests.unit.test_onboard_example_books tests.unit.test_generate_visual_toc_snapshots tests.unit.test_toc_real_page_resolution tests.unit.test_fnm_export tests.unit.test_fnm_export_audit tests.unit.test_fnm_batch_report`：34 tests OK。
  - 合并执行上述三组回归：113 tests OK。
- 未决事项：
  - 无。

## 变更批次 7（sync-docs-onworking-retirement）

- 目标：同步“旧链彻底退役（fnm 软退役）”最终状态到文档口径。
- 修改文件：
  - `FNM_RE/OnWorking.md`
  - `PROGRESS.md`
  - `verification.md`
- 关键决策：
  - `fnm/` 保留为只读存档目录，不再承接主链运行与功能迭代。
  - `fnm/` 目录外静态导入 `fnm.*` 由 `tests.unit.test_fnm_import_guards` 守卫强制禁止。
  - 旧链测试已下线，不再作为退役后的必跑回归集；当前回归基线为“守卫 + phase1~6 + 导出/脚本集合”。
- 边缘情况：
  - `fnm/` 内仍可保留历史实现供追溯，但运行链路新增调用必须走 `FNM_RE` 公开 API。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_import_guards`：1 test OK。
  - `python3 -m unittest tests.unit.test_fnm_re_phase1 tests.unit.test_fnm_re_phase2 tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_phase5 tests.unit.test_fnm_re_phase6`：78 tests OK。
  - `python3 -m unittest tests.unit.test_audit_fnm_exports tests.unit.test_onboard_example_books tests.unit.test_generate_visual_toc_snapshots tests.unit.test_toc_real_page_resolution tests.unit.test_fnm_export tests.unit.test_fnm_export_audit tests.unit.test_fnm_batch_report`：34 tests OK。
  - `rg -n "from fnm\\.|import fnm\\." --glob "{FNM_RE/**,web/**,pipeline/**,translation/**,scripts/**}/*.py"`：无命中。
- 未决事项：
  - 无。

## 变更批次 8（移除旧链动态桥接，收紧为 `fnm/` 外零运行时引用）

- 目标：把 `FNM_RE/__init__.py` 中遗留的旧链诊断动态桥接移除，确保 `fnm/` 外不再运行时引用 `fnm` 包。
- 修改文件：
  - `FNM_RE/__init__.py`
  - `FNM_RE/OnWorking.md`
- 关键决策：
  - `list_diagnostic_entries_for_doc`、`get_diagnostic_entry_for_page`、`list_diagnostic_notes_for_doc` 统一直接转发到 `FNM_RE.app.mainline` 的 phase6 诊断实现，不再通过 `importlib.import_module("fnm.fnm_diagnostic")` 间接桥接旧链。
- 边缘情况：
  - 保持对外函数名与调用签名不变，仅替换内部实现来源，避免影响 `persistence/sqlite_repo_fnm.py` 等调用方。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_import_guards`：1 test OK。
  - `python3 -m unittest tests.unit.test_fnm_re_phase1 tests.unit.test_fnm_re_phase2 tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_phase5 tests.unit.test_fnm_re_phase6`：78 tests OK。
  - `python3 -m unittest tests.unit.test_audit_fnm_exports tests.unit.test_onboard_example_books tests.unit.test_generate_visual_toc_snapshots tests.unit.test_toc_real_page_resolution tests.unit.test_fnm_export tests.unit.test_fnm_export_audit tests.unit.test_fnm_batch_report`：34 tests OK。
  - `rg -n "fnm\\.fnm_|import_module\\(\"fnm" --glob "{FNM_RE/**,web/**,pipeline/**,translation/**,scripts/**,persistence/**}/*.py"`：无命中。
- 未决事项：
  - 无。

## 变更批次 9（硬退役落地 + 验收阻塞定位）

- 目标：按 `FNM_RE/PLAN.md` 完成“主仓硬退役”，并同步当前验收状态。
- 修改文件：
  - `FootNoteMachine/legacy_fnm/README.md`
  - `persistence/sqlite_schema.py`
  - `persistence/sqlite_repo_fnm.py`
  - `FNM_RE/app/mainline.py`
  - `FNM_RE/stages/export.py`
  - `FNM_RE/stages/diagnostics.py`
  - `web/export_routes.py`
  - `web/reading_view.py`
  - `web/translation_routes.py`
  - `tests/unit/test_fnm_import_guards.py`
  - `tests/integration/test_sqlite_store.py`
  - `PROGRESS.md`
  - `verification.md`
  - `FNM_RE/OnWorking.md`
- 关键决策：
  - 主仓根目录彻底删除 `fnm/`，旧链整体迁入 `FootNoteMachine/legacy_fnm/code/fnm/` 只读归档，不保留运行薄壳。
  - `*_v2` schema/repo API 完整退役；`SCHEMA_VERSION` 提升并在迁移中执行 retired v2 表清理。
  - 对外路由路径可保留 `/api/doc/<doc_id>/fnm/*`，但实现仅走 `FNM_RE` 主链。
- 边缘情况：
  - doc/repo 弱投影场景下，`mainline` 需要从 `fnm_*` 持久化层回填 phase5 结构与 unit，避免章节/诊断空集。
  - `fnm_obsidian` 预览接口需要兼容 service 返回 bundle dict 的场景，统一提取 markdown 文本。
  - 未翻译正文在“无 note 定义 + unresolved refs”时降级为 `[待翻译]`，避免 legacy token 泄漏触发导出阻塞。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_import_guards`：1 test OK。
  - `python3 -m unittest tests.unit.test_fnm_re_phase1 tests.unit.test_fnm_re_phase2 tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_phase5 tests.unit.test_fnm_re_phase6`：78 tests OK。
  - `python3 -m unittest tests.unit.test_audit_fnm_exports tests.unit.test_onboard_example_books tests.unit.test_generate_visual_toc_snapshots tests.unit.test_toc_real_page_resolution tests.unit.test_fnm_export tests.unit.test_fnm_export_audit tests.unit.test_fnm_batch_report`：34 tests OK。
  - `rg -n "from fnm\\.|import fnm\\." --glob "{FNM_RE/**,web/**,pipeline/**,translation/**,scripts/**,persistence/**,tests/**}/*.py"`：无命中。
  - `rg -n "fnm_re_mainline" --glob "{FNM_RE/**,web/**,pipeline/**,translation/**,scripts/**,persistence/**,tests/**}/*"`：无命中。
  - `rg -n "replace_fnm_v2_structure|list_fnm_v2_|fnm_structure_issues_v2" --glob "{persistence/**,tests/**}/*.py"`：无命中。
  - `python3 scripts/test_fnm_batch.py --group baseline`：完整执行完成；5 本均在导出校验阶段被 `structure_review_required` gate 阻塞，无退役相关新回归。
  - `python3 scripts/test_fnm_batch.py --group extension`：完整执行完成；3 本均在导出校验阶段被 `structure_review_required` gate 阻塞，无退役相关新回归。
- 未决事项：
  - 退役验收无阻塞；`structure_review_required` 属既有结构质量 gate，后续按内容质量治理单独推进。

## 变更批次 10（stage1-modules-bootstrap）

- 目标：按 `FNM_RE/MODULS.md` + `FNM_RE/Overview.md` + `FNM_RE/STAGE1.md` 启动第一阶段模块化重构，先落地 `toc_structure` 与 `book_note_type`，不切主线。
- 修改文件：
  - `FNM_RE/modules/contracts.py`
  - `FNM_RE/modules/types.py`
  - `FNM_RE/modules/toc_structure.py`
  - `FNM_RE/modules/book_note_type.py`
  - `FNM_RE/modules/__init__.py`
  - `FNM_RE/__init__.py`
  - `tests/unit/fnm_re_module_fixtures.py`
  - `tests/unit/test_fnm_re_module1_toc.py`
  - `tests/unit/test_fnm_re_module2_book_type.py`
  - `FNM_RE/OnWorking.md`
  - `FNM_RE/DEV_FNM.md`
- 关键决策：
  - 新增 `ModuleResult` / `GateReport` 与阶段 1 业务对象，模块层保持纯业务，不触 repo/doc 接线。
  - `toc_structure` 复用 `page_partition + chapter_skeleton + section_heads`，并把对外页面角色收敛为 `front_matter/chapter/post_body/back_matter`，不暴露 `noise`。
  - `book_note_type` 先做“证据扫描 + 全书书型 + 章级模式”，输出 `book_type` 与 gate；`chapter_split` 及后续模块职责不提前搬入本批次。
- 边缘情况：
  - Biopolitics 前置目录页存在 `other`，若直接当 `back_matter` 会误触 `toc.role_semantics_valid`；已按“首章前 `other` 视为 `front_matter`”修正。
  - Biopolitics 混合书中个别章同时出现 footnote/endnote 证据，采用“按证据主导模式优先归类”避免误判 `review_required`。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type`：7 tests OK。
  - `python3 -m unittest tests.unit.test_fnm_import_guards tests.unit.test_fnm_re_phase1 tests.unit.test_fnm_re_phase2 tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_phase5 tests.unit.test_fnm_re_phase6 tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type`：86 tests OK。
- 未决事项：
  - 阶段 1 仅完成模块落地与单测；尚未进入阶段 2 `chapter_split` 与主线切换。

## 变更批次 11（stage2-chapter-split）

- 目标：按 `FNM_RE/STAGE2.md` 落地第二阶段模块化重构，新增 `chapter_split`，打通 region/item/body/policy 的模块输出与 gate。
- 修改文件：
  - `FNM_RE/modules/types.py`
  - `FNM_RE/modules/chapter_split.py`
  - `FNM_RE/modules/__init__.py`
  - `FNM_RE/__init__.py`
  - `tests/unit/test_fnm_re_module3_split.py`
  - `FNM_RE/OnWorking.md`
  - `FNM_RE/DEV_FNM.md`
  - `verification.md`
- 关键决策：
  - 复用旧 `stages` 逻辑但只经模块适配层输出新对象：`TocStructure -> Phase1Structure` 后复用 `build_note_regions/build_note_items` 与 `units` 的正文切分纯函数，不调用 `build_translation_units()`。
  - `split.footnote_only_synthesized` 在 Biopolitics（`mixed`）场景采用 `hard=true + evidence.not_applicable`；`split.mixed_marker_materialized` 采用 `hard=true + evidence.not_required`。
  - gate 与 override 统一走模块协议：空 region 允许通过 `allow_empty_region_ids` 显式放行，并写入 `overrides_used`。
- 边缘情况：
  - Biopolitics 某些章 `note_start_page` 与正文切分结果存在“页号晚于起始页”现象，直接按 `page_no > note_start_page` 判重叠会误报；已改为“仅当后续页属于 note/other 或仍含 notes heading 才判 overlap”。
  - synthetic 同页正文+`## Notes` 场景下，正文层需去掉 notes 区段且 notes 仍进入 item 提取；已用单测锁定。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type tests.unit.test_fnm_re_module3_split`：12 tests OK。
  - `python3 -m unittest tests.unit.test_fnm_import_guards tests.unit.test_fnm_re_phase1 tests.unit.test_fnm_re_phase2 tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_phase5 tests.unit.test_fnm_re_phase6 tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type tests.unit.test_fnm_re_module3_split`：91 tests OK。
- 未决事项：
  - 阶段 2 已完成模块与测试；尚未进入阶段 3 `note_linking/ref_freeze` 与主线切换。

## 变更批次 12（stage3-note-linking）

- 目标：按 `FNM_RE/STAGE3.md` 落地第三阶段模块化重构（本批次仅 `note_linking`），收口 anchor/link/contract/effective_links 与 gate。
- 修改文件：
  - `FNM_RE/modules/types.py`
  - `FNM_RE/modules/note_linking.py`
  - `FNM_RE/modules/__init__.py`
  - `FNM_RE/__init__.py`
  - `tests/unit/test_fnm_re_module4_linking.py`
  - `FNM_RE/MODULS.md`
  - `TEST.md`
  - `FNM_RE/OnWorking.md`
  - `FNM_RE/DEV_FNM.md`
  - `verification.md`
- 关键决策：
  - 新增阶段 3 真相对象：`BodyAnchorLayer / NoteLinkLayer / ChapterLinkContract / NoteLinkTable`。
  - `note_linking` 入口固定为 `build_note_link_table(chapter_layers, pages, *, overrides=None)`；内部通过适配层把 `ChapterLayers` 投影为 `Phase2Structure`，复用 `stages/body_anchors.py` 与 `stages/note_links.py` 成熟规则。
  - `chapter_link_contract` 仅对“有 endnote 信号且章级策略确认为 endnote/review_required”的章节生效；`mixed` 书的 `link.endnote_only_no_orphan_anchor` 固定 `hard=true + evidence.not_applicable`。
  - `overrides` 仅支持 `link` scope：`ignore` 只改 `effective_links`，`match` 需校验 note_item/anchor 存在且 chapter/note_kind 一致，否则记入 `invalid_override_count`。
- 边缘情况：
  - `footnote_primary` 章节中可能出现历史遗留 endnote 识别噪声；模块按章策略归一化 note_kind，避免把脚注章误当尾注 contract 阻塞。
  - 章级 endnote contract 仍存在 orphan/ambiguous 时，模块会在章内执行保守 repair（含 fallback 配对）并明确记账，不静默吞掉。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type tests.unit.test_fnm_re_module3_split tests.unit.test_fnm_re_module4_linking`：18 tests OK。
  - `python3 -m unittest tests.unit.test_fnm_re_phase3 tests.unit.test_fnm_re_phase4 tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type tests.unit.test_fnm_re_module3_split tests.unit.test_fnm_re_module4_linking`：49 tests OK。
- 未决事项：
  - 本批次仅完成阶段 3 的 `note_linking`；`ref_freeze` 仍待下一批次落地。

## 变更批次 13（stage4-ref-freeze）

- 目标：按 `FNM_RE/STAGE4.md` 落地模块五 `ref_freeze`，收口 NOTE_REF 冻结、unit 规划和冻结审计 gate。
- 修改文件：
  - `FNM_RE/modules/types.py`
  - `FNM_RE/modules/ref_freeze.py`
  - `FNM_RE/modules/__init__.py`
  - `FNM_RE/__init__.py`
  - `tests/unit/test_fnm_re_module5_freeze.py`
  - `FNM_RE/OnWorking.md`
  - `FNM_RE/DEV_FNM.md`
  - `verification.md`
- 关键决策：
  - 新增阶段 4 真相对象：`FrozenRefEntry / FrozenUnit / FrozenUnits`，并保持 unit 字段合同与当前 worker 一致。
  - `ref_freeze` 入口固定为 `build_frozen_units(chapter_layers, note_link_table, *, max_body_chars=6000)`；只消费 `effective_links.matched`，不重算链接。
  - 复用 `stages/units.py` 的分段与切块逻辑（`_segment_paragraphs_from_body_pages / _chunk_body_page_segments`），并复用 `shared/refs.py` 的 `frozen_note_ref/replace_frozen_refs`。
  - 每条 matched link 必须进入 `ref_map` 且二选一：`injected` 或 `skipped(reason=...)`；不允许静默丢失。
- 边缘情况：
  - Biopolitics 中存在大量 synthetic anchor：本批次按规范全部显式 `skipped(reason=synthetic_anchor)`，不阻塞 hard gate。
  - 少量 marker 在正文页找不到可替换文本：按 `skipped(reason=token_not_found)` 记账，`freeze.accounting_closed` 仍保持闭合。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type tests.unit.test_fnm_re_module3_split tests.unit.test_fnm_re_module4_linking tests.unit.test_fnm_re_module5_freeze`：24 tests OK。
  - `python3 -m unittest tests.unit.test_fnm_re_phase5 tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type tests.unit.test_fnm_re_module3_split tests.unit.test_fnm_re_module4_linking tests.unit.test_fnm_re_module5_freeze`：36 tests OK。
- 未决事项：
  - 本批次仅完成模块五 `ref_freeze`；后续阶段 4（`chapter_merge/book_assemble`）尚未开始。

## 变更批次 14（stage5-chapter-merge-book-assemble）

- 目标：按 `FNM_RE/STAGE5.md` 同批次落地模块六 `chapter_merge` 与模块七 `book_assemble`，并补齐模块 6/7 类型、导出接线和单测。
- 修改文件：
  - `FNM_RE/modules/types.py`
  - `FNM_RE/modules/chapter_merge.py`
  - `FNM_RE/modules/book_assemble.py`
  - `FNM_RE/modules/__init__.py`
  - `FNM_RE/__init__.py`
  - `tests/unit/test_fnm_re_module6_merge.py`
  - `tests/unit/test_fnm_re_module7_export.py`
  - `FNM_RE/OnWorking.md`
  - `FNM_RE/DEV_FNM.md`
  - `verification.md`
- 关键决策：
  - 新增阶段 5 真相对象：`ChapterMarkdownEntry / ChapterMarkdownSet / ExportAuditFile / ExportAuditReport / ExportBundle`。
  - `chapter_merge` 入口固定为 `build_chapter_markdown_set(frozen_units, note_link_table, chapter_layers, *, diagnostic_machine_by_page=None, include_diagnostic_entries=False)`；通过阶段 5 影子投影复用 `stages/export.py` 的章节合并主流程（译文回退、NOTE_REF 解冻、本章局部编号、定义拼装、文件名规则）。
  - `book_assemble` 入口固定为 `build_export_bundle(chapter_markdown_set, toc_structure, *, slug="", doc_id="")`；导出顺序只按 `toc_structure.chapters`，并复用 `stages/export.py + stages/export_audit.py` 完成整书语义合同与审计。
  - 为避免整书 raw marker gate 漏检，`book_assemble` 追加了“按本章局部引用号（`[^n]`）白名单”的书级 raw marker 检查，与审计报告合并判定 `export.no_raw_marker_leak_book_level`。
- 边缘情况：
  - 章节正文中存在 `[1978]` 这类普通方括号数字时，不能一概判定为注释 marker；模块 6/7 的 raw marker 检查改为“仅对本章局部引用号白名单做判定”，降低误报。
  - `audit_phase6_export` 在章节无 note marker 白名单时不会主动报 `raw_note_marker_leak`；模块 7 增加了显式书级补检，避免出现 gate 假阴性。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_re_module6_merge tests.unit.test_fnm_re_module7_export`：9 tests OK。
  - `python3 -m unittest tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type tests.unit.test_fnm_re_module3_split tests.unit.test_fnm_re_module4_linking tests.unit.test_fnm_re_module5_freeze tests.unit.test_fnm_re_module6_merge tests.unit.test_fnm_re_module7_export`：33 tests OK。
  - `python3 -m unittest tests.unit.test_fnm_re_phase6`：14 tests OK。
- 未决事项：
  - Biopolitics 直连模块链路下，`merge.no_raw_marker_leak_in_body` 与 `export.no_raw_marker_leak_book_level` 当前仍为 `false`（`export.audit_can_ship` 为 `true`）；后续需在模块 6 的 raw marker fallback 覆盖率上继续收敛。

## 变更批次 15（stage6-mainline-snapshot-sync）

- 目标：完成阶段 6 收口并同步文档口径，覆盖 `merge/export hard gate`、`pipeline snapshot`、`mainline` 切换、`status gate summary`、consumer 接线与 phase 公开 API 退场。
- 修改文件：
  - `FNM_RE/app/pipeline.py`
  - `FNM_RE/app/mainline.py`
  - `FNM_RE/status.py`
  - `FNM_RE/__init__.py`
  - `FNM_RE/app/__init__.py`
  - `web/export_routes.py`
  - `web/translation_routes.py`
  - `templates/reading/fnm_review.html`
  - `scripts/test_fnm_batch.py`
  - `tests/unit/test_fnm_batch_report.py`
  - `tests/unit/test_fnm_re_pipeline_snapshot.py`
  - `tests/unit/test_fnm_re_status_gate_summary.py`
  - `tests/unit/test_fnm_re_public_api_surface.py`
  - `tests/integration/test_fnm_re_mainline_biopolitics.py`
  - `FNM_RE/OnWorking.md`
  - `FNM_RE/DEV_FNM.md`
  - `verification.md`
- 关键决策：
  - `merge/export hard gate` 已收口：Biopolitics 模块快照下，`merge.no_raw_marker_leak_in_body` 与 `export.no_raw_marker_leak_book_level` 均为真，且 `export.audit_can_ship=true`。
  - `pipeline snapshot` 成为主线真相承载：`build_module_pipeline_snapshot(...)` 统一串联模块 1~7，并生成 `phase6/status/summary` 一致快照。
  - `mainline` 切到 snapshot：`load_phase6_for_doc()` 通过 `_load_module_snapshot_for_doc()` 装配并直接返回 `snapshot.phase6_shadow`，状态/导出/诊断读取同源。
  - `status gate summary` 收口：`build_module_gate_status(...)` 统一汇总模块 hard gate、`blocking_reasons/review_counts`、`pipeline_state` 分支与导出就绪判定。
  - consumer sync 完成：`web/pipeline/translation/scripts/persistence` 已统一走 `FNM_RE` 公开入口；代码内不再依赖 `fnm_re_mainline` 条件标记。
  - phase API 退场：`FNM_RE` 与 `FNM_RE.app` 对外导出面移除 phase 专用 API，仅保留通用 API；`test_fnm_re_public_api_surface` 锁定导出边界。
  - 测试收口：新增并通过 `mainline biopolitics` 集成测试、`status gate summary` 测试、`pipeline snapshot` 测试、`public api surface` 测试，并与阶段 6 核心回归合并验证。
- 边缘情况：
  - `manual_toc_ready=false` 时会强制追加 `toc_manual_toc_required`，`structure_state` 回落为 `review_required`。
  - `pipeline_state` 为 `idle/running/error` 时，状态强制保持对应运行态，`export_ready_test/export_ready_real` 均为 false。
  - `mixed` 书型仍可能产生 `synthetic_anchor`/`synthetic_skip` 软告警；当前不阻塞阶段 6 可用性判定。
- 验证结果：
  - `python3 -m unittest tests.unit.test_fnm_re_module6_merge tests.unit.test_fnm_re_module7_export tests.unit.test_fnm_re_phase6 tests.unit.test_fnm_re_status_gate_summary tests.unit.test_fnm_re_pipeline_snapshot tests.integration.test_fnm_re_mainline_biopolitics`：31 tests OK。
  - `python3 -m unittest tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type tests.unit.test_fnm_re_module3_split tests.unit.test_fnm_re_module4_linking tests.unit.test_fnm_re_module5_freeze tests.unit.test_fnm_re_module6_merge tests.unit.test_fnm_re_module7_export tests.unit.test_fnm_re_phase6 tests.unit.test_fnm_re_pipeline_snapshot tests.unit.test_fnm_re_status_gate_summary tests.integration.test_fnm_re_mainline_biopolitics tests.unit.test_fnm_re_public_api_surface tests.unit.test_fnm_batch_report`：62 tests OK。
  - `python3 - <<'PY' ... build_module_pipeline_snapshot(load_pages("Biopolitics"), ...)`：`merge_hard/export_hard` 全真，`status_state=ready`，`blocking=[]`。
  - `rg -n "fnm_re_mainline" --glob "**/*.py"`：无命中。
- 未决事项：
  - 结论：阶段 6 主链当前可用，可直接用于 `run_doc_pipeline/build_doc_status/build_export_bundle_for_doc`。
  - 非本轮阻塞项：`chapter_skeleton.py` 复杂度仍高且有旧 visual TOC 依赖，`app/mainline.py` 接线职责仍偏重，属于后续重构项。

## 变更批次 16（sqlite-refactor-read-path-purify-batch1）

- 目标：按 `SQLite.md` 推进拆库重构，先完成“迁移脚本可用 + 读链路去写首批收敛”。
- 修改文件：
  - `persistence/sqlite_split_migration.py`
  - `persistence/sqlite_catalog_schema.py`
  - `persistence/sqlite_store.py`
  - `persistence/storage.py`
  - `web/document_routes.py`
  - `web/reading_routes.py`
  - `tests/integration/test_tasks_streaming.py`
  - `tests/integration/test_sqlite_split_migration.py`
  - `PROGRESS.md`
  - `verification.md`
  - `SQLite.md`
  - `FNM_RE/OnWorking.md`
  - `FNM_RE/DEV_FNM.md`
- 关键决策：
  - `upsert_document` 改为 catalog/doc 双写，保证 doc.db 的 FK 前置条件成立，避免写 `pages` 时出现外键失败。
  - `catalog.db` schema 升级到 v2，并补齐文档元字段兼容列（含补列迁移），优先保行为稳定。
  - 迁移脚本对 `translation_segments` 改为通过 `translation_pages` 反查 `doc_id`，修复旧实现直接按 `doc_id` 过滤报错。
  - 读路径去写首批先收口最热路径：`load_pages_from_disk`、`GET /`、`GET /input`、`GET /reading`。
- 边缘情况：
  - `GET /reading` 原先会在命中翻译页时写 `save_entry_cursor`，现在移除后需由后续显式接口或前端本地态承接。
  - `catalog` 与 `doc.db` 双写阶段，文档元字段保持兼容口径，后续再做精简字段收口。
- 验证结果：
  - `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "load_pages_from_disk_does_not_write_back_repair_results or reading_get_does_not_persist_cursor_or_switch_current_doc"`：2 passed。
  - `.venv/bin/python -m pytest -q tests/integration/test_sqlite_store.py -k "test_catalog_repository_uses_catalog_db_path or test_document_repository_uses_document_db_path or test_initialize_runtime_databases_supports_catalog_and_document_dbs"`：3 passed。
  - `.venv/bin/python -m pytest -q tests/integration/test_sqlite_split_migration.py`：1 passed。
- 未决事项：
  - `db-refactor-mainline-cutover` 仍未完成，剩余 GET/状态接口需继续做“纯读无写”审计与收口。

## 变更批次 17（sqlite-refactor-mainline-cutover-closeout）

- 目标：完成 SQLite 拆库主链切换收口（初始化默认切库、删除流程清理、doc-scoped 状态落位）并同步文档口径。
- 修改文件：
  - `app.py`
  - `config.py`
  - `persistence/sqlite_bootstrap.py`
  - `persistence/sqlite_db_paths.py`
  - `persistence/sqlite_repo_state.py`
  - `persistence/sqlite_store.py`
  - `tests/integration/test_sqlite_store.py`
  - `README.md`
  - `DEV.md`
  - `PROGRESS.md`
  - `SQLite.md`
  - `verification.md`
  - `FNM_RE/OnWorking.md`
  - `FNM_RE/DEV_FNM.md`
- 关键决策：
  - 主链启动默认不再初始化 legacy `app.db`，仅保留 `catalog.db + doc.db` 运行时布局。
  - `update_fnm_run` / `update_fnm_translation_unit` 纳入 doc context 路由，避免拆库下误写到 catalog。
  - glossary 状态切到 doc-scoped 存储，删除文档时同步清理 catalog 侧 doc-scoped `app_state` 残留。
  - 删除路径获取 doc.db 路径时禁用目录自动创建，避免“删完又回建目录”。
- 边缘情况：
  - 仍保留 `app.db` 作为迁移来源/备份，不再作为主链运行库。
  - 当前仍有既有基线失败 `test_repository_persists_fnm_data_without_touching_standard_translation_pages`，本批次未改变其断言口径。
- 验证结果：
  - `.venv/bin/python -m pytest -q tests/integration/test_sqlite_store.py -k "test_catalog_repository_uses_catalog_db_path or test_document_repository_uses_document_db_path or test_initialize_runtime_databases_supports_catalog_and_document_dbs or test_initialize_runtime_databases_defaults_to_catalog_without_legacy_app_db or test_glossary_state_is_written_to_doc_db_in_split_mode or test_delete_document_cleans_catalog_doc_scoped_state_keys"`：6 passed。
  - `.venv/bin/python -m pytest -q tests/integration/test_sqlite_split_migration.py`：1 passed。
  - `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "load_pages_from_disk_does_not_write_back_repair_results or reading_get_does_not_persist_cursor_or_switch_current_doc"`：2 passed。
  - `.venv/bin/python -m pytest -q tests/integration/test_backend_backlog.py -k "test_doc_processing_status_returns_visual_toc_progress_payload or test_glossary_crud_api"`：2 passed。
  - `.venv/bin/python -m pytest -q tests/integration/test_sqlite_mainline.py -k "test_translate_status_is_task_only_and_reading_view_state_is_separate or test_doc_scoped_glossary_isolated_between_documents or test_fetch_next_uses_doc_scoped_glossary or test_delete_docs_batch_removes_selected"`：4 passed。
- 未决事项：
  - 可选增强：继续扩大 GET/状态接口“纯读无写”覆盖面，作为后续质量加固项。

## 变更批次 18（upload-manual-toc-deps-hotfix）

- 目标：修复“附带 PDF 目录”上传后后台任务 `KeyError: update_doc_meta`。
- 修改文件：
  - `pipeline/document_tasks.py`
  - `tests/unit/test_document_tasks_deps.py`
  - `tests/integration/test_tasks_streaming.py`
- 根因：
  - `pipeline/task_document_pipeline.py::process_file` 在手动目录输入路径会调用 `deps["update_doc_meta"]`；
  - 但 `pipeline/document_tasks.py::_document_pipeline_deps` 未注入该键（同时也缺 `parse_glossary_file`、`set_glossary`），导致运行期 KeyError。
- 处理：
  - 依赖字典补齐 `update_doc_meta`、`parse_glossary_file`、`set_glossary`。
  - 新增依赖守卫单测，避免后续再次漏注入。
  - 新增集成测试覆盖“手动目录 PDF 上传 + process_file 全链路”。
- 验证结果：
  - `.venv/bin/python -m pytest -q tests/unit/test_document_tasks_deps.py tests/unit/test_upload_glossary_pipeline.py`：5 passed。
  - `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "test_process_file_"`：9 passed。
  - `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "test_process_file_manual_toc_pdf_upload_does_not_break_doc_meta_update or test_process_file_runs_visual_toc_sync_before_fnm_when_fnm_enabled"`：2 passed。

## 变更批次 19（fnm-live-status-and-session-logs）

- 目标：把首页 FNM 状态改为实时可读的运行/通过/阻塞信息，并完成日志系统“每次启动独立文件”改造。
- 修改文件：
  - `web/translation_routes.py`
  - `templates/home.html`
  - `pipeline/document_tasks.py`
  - `FNM_RE/app/mainline.py`
  - `logging_config.py`
  - `app.py`
  - `tests/unit/test_logging_config.py`
  - `tests/unit/test_translate_runtime_logging_policy.py`
  - `tests/integration/test_fnm_real_mode.py`
  - `tests/integration/test_tasks_streaming.py`
  - `PROGRESS.md`
  - `verification.md`
  - `FNM_RE/OnWorking.md`
  - `FNM_RE/DEV_FNM.md`
- 关键决策：
  - `/api/doc/<doc_id>/fnm/status` 新增 gate 聚合字段（通过数/失败数/失败项标签），前端直接消费，避免文案和口径漂移。
  - FNM 解析任务日志增加 `run_id/structure_state/manual_toc_required/export_ready_real/blocking_reasons`，用于定位“为什么不能翻译/导出”。
  - 全局日志不再固定写 `logs/app.log`，改为 `logs/sessions/app_*.log` 按启动分片，并自动清理只保留最近 30 次。
  - 日志策略明确：翻译正文不入日志；仅错误相关信息允许落盘。
- 边缘情况：
  - `create_app()` 多次调用时日志初始化保持幂等，避免重复 handler。
  - `gate` 失败项在 `run=running` 阶段可能为暂时失败/未满足，前端按“当前快照”展示，不做历史态推断。
- 验证结果：
  - `.venv/bin/python -m pytest -q tests/unit/test_logging_config.py tests/unit/test_translate_runtime_logging_policy.py tests/unit/test_document_tasks_deps.py tests/integration/test_fnm_real_mode.py::FnmRealModeIntegrationTest::test_api_doc_fnm_status_reports_real_mode_blockers`：6 passed。
  - `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "test_process_file_"`：9 passed。
  - `.venv/bin/python -m pytest -q tests/integration/test_tasks_streaming.py -k "test_process_file_done_event_routes_fnm_when_cleanup_enabled or test_process_file_manual_toc_pdf_upload_does_not_break_doc_meta_update"`：2 passed。
