# FNM_RE

FNM（脚注/尾注机）的 Python thin wrapper。核心 pipeline 已用 Rust 重写（`fnm_re_rs/` 10 个 crate），此包仅通过 `fnm-re-rs` pyo3 wheel 暴露 surface API。

## 状态

- `FNM_RE/` 已归档到 `归档/FNM_RE/`（含 `app/`、`stages/`、`modules/`、`shared/`、`dev/`、`constants.py`、`models.py`）
- `tests/unit/` 的 parity 测试已归档到 `归档/tests/unit/`
- `tools/` 的 golden 生成器已归档到 `归档/tools/`

## Surface API（39 个）

### Pipeline 入口
- `run_doc_pipeline` / `build_module_pipeline_snapshot_rust`

### 结构加载
- `load_doc_structure` / `build_doc_status`

### 导出
- `build_export_bundle_for_doc` / `build_export_zip_for_doc`
- `audit_export_for_doc` / `run_post_translate_export_checks_for_doc`

### 诊断
- `list_diagnostic_entries_for_doc` / `list_diagnostic_notes_for_doc`
- `get_diagnostic_entry_for_page`

### 翻译辅助
- `prepare_page_translate_jobs` / `build_retry_summary` / `build_unit_progress`
- `run_llm_repair`

### page_translate helper（9 个）
- `build_fnm_body_unit_jobs` / `apply_body_unit_translations` / `apply_body_unit_entry_result`
- `list_fnm_units_with_indices` / `sync_fnm_retry_state` / `rebuild_fnm_diagnostic_page_entries`
- `collect_fnm_unit_failed_locations`

### 文本工具（4 个）
- `serialize_segments` / `deserialize_segments_to_dicts`
- `replace_frozen_refs` / `format_fnm_unit_label` / `format_fnm_unit_pages`

### 导出审计 helper（3 个）
- `body_paragraphs` / `definition_lines` / `split_body_and_definitions`

### sup_recovery
- `has_explicit_sup` / `recover_book`

### LLM 工具
- `dump_traces` / `write_summary_traces`
- `resolve_repair_model_args` / `render_repair_page_data_url`

### 阴影模式 / 工具
- `fnm_re_rs_version` / `run_with_shadow` / `summarize_pipeline_snapshot`

## 快速验证

```bash
.venv/bin/python -c "import FNM_RE; print(len(FNM_RE.__all__))"
# 期望输出: 39
```

## 历史计划

见 `归档/FNM_RE/plans/`（M1-M3 详细计划 + M1 会话记录）。
当前计划：`M4_DETAILED_PLAN.md`、`NEXT_PHASE_PLAN.md`。
