# 下一阶段计划：主线切换、状态收口与旧阶段退场

## 概要

当前完成状态已核对：

- 模块 1 到 7 都已落地，`chapter_merge` / `book_assemble` 的单测和 `phase6` 护栏回归通过。
- 通用主入口 `run_doc_pipeline / build_doc_status / build_export_bundle_for_doc` 已被脚本、路由和服务层使用，外部调用面基本已经收敛到通用 API。
- 但 Biopolitics 的模块链当前仍未达到 cutover 验收线：
  - `merge.no_raw_marker_leak_in_body=false`
  - `export.no_raw_marker_leak_book_level=false`

所以下一阶段不能直接“切主线”，而要按固定顺序做两件事：

1. 先把模块 6/7 在 Biopolitics 上的剩余 hard gate 收口到全真。
2. 再完成 `mainline/pipeline/status` 的模块化切换、旧 phase 公开入口下线、脚本和路由口径更新。

## 实施变更

### 1. 先收口模块 6/7 的剩余 hard gate

- 以 Biopolitics 为唯一硬验收样本，先把 `merge_raw_marker_leak` 和 `export_raw_marker_leak` 清零。
- 不允许带着 `merge.no_raw_marker_leak_in_body=false` 或 `export.no_raw_marker_leak_book_level=false` 进入主线切换；否则新 `status` 不可能达到 `blocking_reasons=[]`。
- 修复范围只限模块 6/7：
  - raw marker 白名单与本章局部 `[^n]` 编号的对应关系
  - body/definition 分区后 raw marker 扫描口径
  - 整书级 raw marker 检查与 `audit_report` 的一致性
- 修完后的前置完成条件：
  - Biopolitics 上模块 1 到 7 的 hard gate 全真
  - `merge_reasons == []`
  - `export_reasons == []`

### 2. 切换 `app/pipeline.py` 到 7 模块主线

新增内部组合入口，名称固定为：

```python
build_module_pipeline_snapshot(...)
```

返回一个仅供内部使用的 `ModulePipelineSnapshot`，至少包含：

- `toc_result`
- `book_type_result`
- `split_result`
- `link_result`
- `freeze_result`
- `merge_result`
- `export_result`
- `frozen_units_effective`
- `diagnostic_pages`
- `diagnostic_notes`

实现顺序固定为：

1. `build_toc_structure`
2. `build_book_note_profile`
3. `build_chapter_layers`
4. `build_note_link_table`
5. `build_frozen_units`
6. 叠加 repo 里的历史翻译到 `FrozenUnits`
7. 由叠加后的 `FrozenUnits` 生成 `diagnostic_pages / diagnostic_notes`
8. `build_chapter_markdown_set`
9. `build_export_bundle`

明确规则：

- repo overlay 只允许改 `FrozenUnits.body_units / note_units` 的 `translated_text / status / error_msg / page_segments`，不允许回写章节、region、link、export 真相对象。
- `mainline.py` 不再调用 `build_phase5_structure / build_phase6_structure` 作为业务主线。
- 如果还要复用旧 `build_diagnostic_projection`、repo serializer、`audit_phase6_export`，只能通过纯投影 shadow adapter，且这些 adapter 不允许新增业务判断。

### 3. 重写 `app/mainline.py` 为 doc/repo 接线层

`mainline.py` 保留并只保留这些职责：

- 读取 pages / TOC / manual TOC / review overrides / repo units
- 调用 `build_module_pipeline_snapshot`
- 把 snapshot 投影到 repo 持久化
- 产出 doc 级状态、导出 bundle、导出 zip、诊断页/诊断注释

通用公共 API 保持不变并改为新主线实现：

- `run_doc_pipeline`
- `load_doc_structure`
- `build_doc_status`
- `build_export_bundle_for_doc`
- `build_export_zip_for_doc`
- `audit_export_for_doc`
- `list_diagnostic_entries_for_doc`
- `get_diagnostic_entry_for_page`
- `list_diagnostic_notes_for_doc`

phase 专用公共 API 在本批次结束时下线：

- `build_phase1_structure` 到 `build_phase6_structure`
- `run_phase6_pipeline_for_doc`
- `load_phase6_for_doc`
- `build_phase6_status_for_doc`
- `build_phase6_export_bundle_for_doc`
- `build_phase6_export_zip_for_doc`
- `audit_phase6_export_for_doc`
- `list_phase6_*`

处理规则固定为：

- 先把所有脚本、路由、服务都保留在通用 API 上，不再直接引用 phase 名。
- 仅在所有新测试通过后，从 `FNM_RE.__all__` 和 `FNM_RE.app.__all__` 中移除 phase 专用导出。
- phase builder 如需短暂保留，只能变成 `_build_phase*_shadow` 形式的私有适配器，不能继续公开。

### 4. 重写 `status.py` 为 Gate 汇总层

新增内部入口，名称固定为：

```python
build_module_gate_status(snapshot, *, pipeline_state, manual_toc_ready, manual_toc_summary)
```

新 `status.py` 只做三件事：

- 汇总 7 个模块的 `GateReport`
- 投影成现有 `StructureStatusRecord` 字段
- 生成 `blocking_reasons / review_counts / progress summaries`

固定口径：

- `blocking_reasons` 只来自 module hard=false 的 `GateReport.reasons`
- reason code 不再改名，直接使用模块已有前缀：
  - `toc_*`
  - `book_type_*`
  - `split_*`
  - `link_*`
  - `freeze_*`
  - `merge_*`
  - `export_*`
- manual TOC 阻塞统一写为 `toc_manual_toc_required`
- `pipeline_state != done` 时只显示 `idle/running/error`
- `pipeline_state == done` 且所有 hard gate 全真时才允许 `structure_state=ready`
- 任一 hard gate 失败都进入 `review_required`
- soft gate 只进入提示，不阻塞

兼容字段的投影规则固定为：

- `review_counts`
  - 保留字段名，但 key 改为模块 reason code
  - value 为该 reason 的出现次数
- `link_summary`
  - 直接取 `note_link_table.link_summary`
- `page_partition_summary`
  - 直接取 `toc_result.evidence.page_partition_summary`
- `chapter_mode_summary`
  - 继续投影成现有 5 档：`footnote_primary / chapter_endnotes / book_endnotes / body_only / mixed_or_unclear`
- `chapter_local_endnote_contract_ok`
  - 直接等于 `merge.local_refs_closed`
- `export_semantic_contract_ok`
  - 直接等于 `export.semantic_contract_ok`
- `export_ready_test / export_ready_real`
  - 只有 `pipeline_state == done` 且全部 hard gate 为真时才为 `true`
- `manual_toc_required / manual_toc_ready / manual_toc_summary`
  - 保留顶层布尔和摘要字段，供路由/UI 使用
- `toc_export_coverage_summary`
  - 由 `toc_structure` 的 exportable chapter/post_body 数与 `chapter_markdown_set / export_bundle` 的实际导出数直接计算
- `export_drift_summary`
  - 基于 `chapter_markdown_set` / `export_bundle.chapter_files` 扫 legacy note token、legacy raw marker、orphan local refs/defs，不能再依赖旧 `phase6` 反推

### 5. 同步更新脚本、路由与测试口径

必须同步改的消费方：

- `web/export_routes.py`
  - 不再从 `blocking_reasons` 中查旧的 `manual_toc_required`
  - 改为先看 `manual_toc_required` 布尔，再回退到新的模块 reason
- `web/translation_routes.py`
  - `review_counts` 改为展示模块 reason counts，不再假定有 `footnote_orphan_note / ambiguous`
- `scripts/test_fnm_batch.py`
  - 批测报告改为按模块 reason 汇总，不再输出 legacy orphan/ambiguous 统计行
  - `manual_toc_required` 继续读顶层布尔
- `tests/unit/test_fnm_batch_report.py`
  - 更新为新 blocking reason / review_counts 文案

旧 phase 测试口径处理顺序固定为：

1. 实现期间允许保留 `tests/unit/test_fnm_re_phase1..6.py` 作为影子回归。
2. 新的 `mainline` 和 `status` 测试全部通过后，删除旧 phase 测试文件，或至少从默认回归命令中移除。
3. 批次结束时，默认验收套件只保留模块测试、mainline 集成测试、status 汇总测试和批测脚本。

## 测试计划

新增并作为本批次主验收的测试：

- `tests/integration/test_fnm_re_mainline_biopolitics.py`
  - 直接走 `run_doc_pipeline` / `build_doc_status` / `build_export_bundle_for_doc`
  - 断言 Biopolitics：
    - `structure_state == "ready"`
    - `blocking_reasons == []`
    - `export_ready_test == true`
    - `chapter_local_endnote_contract_ok == true`
- `tests/unit/test_fnm_re_status_gate_summary.py`
  - 用 synthetic module results 验证：
    - hard fail 才进入 `blocking_reasons`
    - `pipeline_state` 的 `idle/running/error/done` 分支
    - `manual_toc_required` 与 `toc_manual_toc_required` 的兼容投影
    - `review_counts` 按模块 reason code 计数
- `tests/unit/test_fnm_re_public_api_surface.py`
  - 断言通用 API 仍在
  - phase 专用 API 已不再公开导出

保留并继续通过的回归：

```bash
python3 -m unittest \
  tests.unit.test_fnm_re_module1_toc \
  tests.unit.test_fnm_re_module2_book_type \
  tests.unit.test_fnm_re_module3_split \
  tests.unit.test_fnm_re_module4_linking \
  tests.unit.test_fnm_re_module5_freeze \
  tests.unit.test_fnm_re_module6_merge \
  tests.unit.test_fnm_re_module7_export \
  tests.integration.test_fnm_re_mainline_biopolitics \
  tests.unit.test_fnm_re_status_gate_summary \
  tests.unit.test_fnm_batch_report
```

最终烟测固定为：

```bash
python3 scripts/test_fnm_batch.py --slug Biopolitics
python3 scripts/test_fnm_batch.py --group baseline
python3 scripts/test_fnm_batch.py --group extension
```

Biopolitics 完成标准固定为：

- 模块 1 到 7 所有 hard gate 为真
- `structure_state == "ready"`
- `blocking_reasons == []`
- `export_ready_test == true`
- `chapter_local_endnote_contract_ok == true`
- 由现有批测脚本将 zip 落盘到 `test_example/Biopolitics/latest.fnm.obsidian.zip`

## 默认假设

- 仓库当前没有 `FNM_RE/STAGE5.md`，本批次以 `MODULS.md / Overview.md / TEST.md / OnWorking.md` 为准。
- `latest.fnm.obsidian.zip` 的落盘继续由现有测试/批处理脚本负责，主线 API 仍只返回 export bundle / zip bytes，不主动写测试目录文件。
- 允许在 `mainline.py` 内保留极薄的 shadow projection，用于复用旧诊断/审计/持久化函数；但这些 shadow 不能承载任何业务判断。
- 如果模块 6/7 的 raw marker gate 未先收口，本批次不得宣告 cutover 完成。
