# FNM Real Test Report — Neuropsychoanalysis_Introduction

- doc_id: `a3c9e1f7b284`
- 状态: `ready`
- 导出可用: `True`
- 阻塞原因: `[]`
- translation_mode: `placeholder`
- translation_api_called: `False`
- current_stage: `report_write`

## 输入资产
- pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/Neuropsychoanalysis A Contemporary Introduction (Georg Northoff) (Z-Library).pdf` size=`2012321` sha256=`cb082473b24096b30e8d18895901275bfe53d508b10a6915fa15ad6fb96b4b92`
- raw_pages: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/raw_pages.json` size=`3577114` sha256=`38f0b4ed7b66927051e9280c6cfc264cd088e0243567e42e6d9f71b3deff03da`
- raw_pages.page_count: `168`
- raw_source_markdown: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/raw_source_markdown.md` size=`369464` sha256=`0d0f9b610d874eb5aa37ad6184401e2ff58d2ca7ee27bc358a14ba2849dc21d0`
- raw_source_markdown.usage_note: `本轮只作为输入资产校验与报告证据，不回灌数据库。`
- raw_source_markdown.preview: `# Neuropsychoanalysis A Contemporary Introduction (Georg Northoff) (Z-Library).pdf ## PDF第1页 ## NEUROPSYCHOANALYSIS A Contemporary Introduction <div style="text-align: center;"><img src="imgs/img_in_image_box_341_513_440...`
- manual_toc_pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/目录.pdf` size=`104631` sha256=`4e30e2d54d3247992166e207ae1629a8be75ddb4abb7fc8ca952ae9487368a1f`

## 清理结果
- removed_count: `9`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/llm_traces", "/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/latest.fnm.obsidian.Neuropsychoanalysis_Introduction.test.zip", "/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/latest.fnm.obsidian.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `0`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=2, prompt=2822, completion=1031, total=3853
- llm_repair.cluster_request: request=0, prompt=0, completion=0, total=0
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `3`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `107`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 9, "resolved_anchor_count": 9, "provisional_anchor_count": 0, "section_node_count": 213, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": ["Introduction", "Conclusion"], "demoted_chapter_titles_preview": ["NEUROPSYCHOANALYSIS A Contemporary Introduction", "Aner Govrin – Editor", "Mismatch between psyche and brain – different models in psychoanalysis and neuroscience", "Overview and main goal of the book", "“Common currency” of brain and psyche - topography and dynamic", "“Common currency” of brain and psyche –", "Psyche in psychoanalysis – dynamic, topographic, and spatio-temporal", "Psychoanalysis and neuroscience – contrasting views of psyche and brain"], "optimized_anchor_count": 3, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 107}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 0, "endnotes": 0, "chapter": 9, "section": 0, "post_body": 0, "back_matter": 1, "front_matter": 0}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/latest.fnm.obsidian.Neuropsychoanalysis_Introduction.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `2`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/Neuropsychoanalysis_Introduction/llm_traces/visual_toc.manual_input_extract.002.json`

## 模块过程取证
### 边界区分
- decision_basis: `["fnm_pages.page_role", "fnm_pages.role_reason", "fnm_pages.role_confidence", "fnm_pages.has_note_heading", "fnm_pages.section_hint"]`
- page_role_counts: `{"front_matter": 42, "body": 117, "other": 9}`
- first_body_page: `20`
- first_note_page: `None`
- page_role_samples: `[{"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 2, "target_pdf_page": 2, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 3, "target_pdf_page": 3, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 20, "target_pdf_page": 20, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 21, "target_pdf_page": 21, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 22, "target_pdf_page": 22, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 160, "target_pdf_page": 160, "page_role": "other", "role_reason": "bibliography", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 161, "target_pdf_page": 161, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 162, "target_pdf_page": 162, "page_role": "other", "role_reason": "rear_toc_tail", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}]`

### 尾注区确定
- decision_basis: `["fnm_note_regions.region_kind/start_page/end_page/pages", "fnm_note_regions.bound_chapter_id", "fnm_note_regions.region_start_first_source_marker", "fnm_note_regions.region_first_note_item_marker", "structure.chapter_binding_summary", "structure.visual_toc_endnotes_summary"]`
- visual_toc_endnotes_summary: `{}`
- chapter_binding_summary: `{"region_count": 0, "book_scope_region_count": 0, "unbound_region_count": 0, "unbound_region_ids_preview": [], "unassigned_item_count": 0, "unassigned_item_ids_preview": []}`
- endnote_region_rows: `[]`

### 尾注数组建立
- decision_basis: `["fnm_note_items.region_id/chapter_id/page_no/marker", "按 region_id 聚合生成注释数组", "检查 numeric marker 连续性与首尾 marker"]`
- note_capture_summary: `{"expected_anchor_count": 1, "captured_note_count": 0, "capture_ratio": 0.0, "sparse_capture_chapter_ids": [], "dense_anchor_zero_capture_pages": [], "chapters": [{"chapter_id": "toc-ch-001-introduction", "note_mode": "no_notes", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-002-selfandnarcissism", "note_mode": "no_notes", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-003-attachmentandtrauma", "note_mode": "no_notes", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-004-defensemechanismsanddiss", "note_mode": "no_notes", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-005-cathexisandfreeenergy", "note_mode": "no_notes", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-006-unconsciousandconscious", "note_mode": "no_notes", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-007-dreams", "note_mode": "no_notes", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-008-schizophreniaanddepressi", "note_mode": "no_notes", "expected_anchor_count": 1, "captured_note_count": 0, "capture_ratio": 0.0}, {"chapter_id": "toc-ch-009-conclusion", "note_mode": "no_notes", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}]}`
- book_endnote_stream_summary: `{"chapter_count": 0, "chapters_with_endnote_stream": [], "high_concentration_chapter_ids": [], "chapters": []}`
- endnote_array_rows: `[]`

### 尾注拼接
- decision_basis: `["fnm_translation_units.kind/owner_kind/section_id/target_ref", "导出 chapter markdown 中 local refs/local defs 的闭合情况", "structure.freeze_note_unit_summary"]`
- freeze_note_unit_summary: `{"chapter_view_note_unit_count": 0, "owner_fallback_note_unit_count": 0, "unresolved_note_item_count": 0, "unresolved_note_item_ids_preview": []}`
- note_unit_rows: `[]`
- export_merge_rows: `[{"title": "Introduction", "path": "chapters/001-Introduction.md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Self and narcissism", "path": "chapters/002-Self and narcissism.md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Attachment and trauma", "path": "chapters/003-Attachment and trauma.md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Defense mechanisms and dissociation", "path": "chapters/004-Defense mechanisms and dissociation.md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Cathexis and free energy", "path": "chapters/005-Cathexis and free energy.md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Unconscious and conscious", "path": "chapters/006-Unconscious and conscious.md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Dreams", "path": "chapters/007-Dreams.md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Schizophrenia and depression", "path": "chapters/008-Schizophrenia and depression.md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{"matched": 0, "footnote_orphan_note": 0, "footnote_orphan_anchor": 0, "endnote_orphan_note": 0, "endnote_orphan_anchor": 0, "ambiguous": 0, "ignored": 0, "fallback_count": 0, "repair_count": 0, "fallback_matched_count": 0, "fallback_match_ratio": 0.0}`
- link_resolver_counts: `{"rule": 1}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "toc-ch-008-schizophreniaanddepressi", "page_no": 149, "paragraph_index": 10, "marker": "2", "anchor_kind": "unknown", "certainty": 0.6, "source_text_preview": "Fuchs T, Van Duppen Z (2017) Time and events: On the phenomenology of temporal experience in schizophrenia (Ancillary article to EAWE domain..."}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-008-schizophreniaanddepressi", "note_item_id": "", "anchor_id": "anchor-00001", "status": "orphan_anchor", "resolver": "rule", "marker": "2", "page_span": [149, 149]}]`

## 阻塞定位明细
