# FNM Real Test Report — Biopolitics

- doc_id: `0d285c0800db`
- 状态: `ready`
- 导出可用: `True`
- 阻塞原因: `[]`
- translation_mode: `placeholder`
- translation_api_called: `False`
- current_stage: `report_write`

## 输入资产
- pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/Foucault和Foucault - 2004 - Naissance de la biopolitique.pdf` size=`23254145` sha256=`59617ad735f29120f416ab9f6c3ec396c2a96616895710bd15ba994cd87f440b`
- raw_pages: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/raw_pages.json` size=`8521865` sha256=`21f0e008c9942580bfb1dff1d603786d6916ecc41912b9f043605f782c8461a7`
- raw_pages.page_count: `370`
- raw_source_markdown: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/raw_source_markdown.md` size=`1038263` sha256=`d41aa823918142fe09408bdc00c08310cbb0d13112bbd03c34cb9ad6c7e6ab83`
- raw_source_markdown.usage_note: `本轮只作为输入资产校验与报告证据，不回灌数据库。`
- raw_source_markdown.preview: `# Foucault和Foucault - 2004 - Naissance de la biopolitique.pdf ## PDF第1页 ## MICHEL FOUCAULT NAISSANCE DE LA BIOPOLITIQUE Cours au Collège de France. 1978-1979 HAUTES ÉTUDES <div style="text-align: center;"><img src="imgs/...`
- manual_toc_pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/Bioplitics目录.pdf` size=`6981680` sha256=`47d65ce2923c8a5bb29b08f46c4fec9fbc8127623508cad91f9ff84ebe2de9de`

## 清理结果
- removed_count: `9`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.Biopolitics.test.zip", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `1179`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=0, prompt=0, completion=0, total=0
- llm_repair.cluster_request: request=0, prompt=0, completion=0, total=0
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `0`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `0`
- residual_provisional_titles_preview: `[]`
- `{}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.Biopolitics.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `0`

## 模块过程取证
### 边界区分
- decision_basis: `["fnm_pages.page_role", "fnm_pages.role_reason", "fnm_pages.role_confidence", "fnm_pages.has_note_heading", "fnm_pages.section_hint"]`
- page_role_counts: `{"front_matter": 16, "body": 270, "note": 62, "other": 22}`
- first_body_page: `17`
- first_note_page: `40`
- page_role_samples: `[{"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 2, "target_pdf_page": 2, "page_role": "front_matter", "role_reason": "blank_front_page", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 3, "target_pdf_page": 3, "page_role": "front_matter", "role_reason": "archive_noise", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 17, "target_pdf_page": 17, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 18, "target_pdf_page": 18, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 19, "target_pdf_page": 19, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 40, "target_pdf_page": 40, "page_role": "note", "role_reason": "note_scan_collection", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 41, "target_pdf_page": 41, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 42, "target_pdf_page": 42, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 349, "target_pdf_page": 349, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 350, "target_pdf_page": 350, "page_role": "other", "role_reason": "index", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 351, "target_pdf_page": 351, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}]`

### 尾注区确定
- decision_basis: `["fnm_note_regions.region_kind/start_page/end_page/pages", "fnm_note_regions.bound_chapter_id", "fnm_note_regions.region_start_first_source_marker", "fnm_note_regions.region_first_note_item_marker", "structure.chapter_binding_summary", "structure.visual_toc_endnotes_summary"]`
- visual_toc_endnotes_summary: `{}`
- chapter_binding_summary: `{}`
- endnote_region_rows: `[]`

### 尾注数组建立
- decision_basis: `["fnm_note_items.region_id/chapter_id/page_no/marker", "按 region_id 聚合生成注释数组", "检查 numeric marker 连续性与首尾 marker"]`
- note_capture_summary: `{}`
- book_endnote_stream_summary: `{}`
- endnote_array_rows: `[]`

### 尾注拼接
- decision_basis: `["fnm_translation_units.kind/owner_kind/section_id/target_ref", "导出 chapter markdown 中 local refs/local defs 的闭合情况", "structure.freeze_note_unit_summary"]`
- freeze_note_unit_summary: `{}`
- note_unit_rows: `[{"section_id": "toc-ch-001-leçondu10janvier1979", "section_title": "Leçon du 10 janvier 1979", "note_unit_count": 28, "note_unit_kind_counts": {"endnote": 28}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [22, 42]}, {"section_id": "toc-ch-001-résuméducours", "section_title": "RÉSUMÉ DU COURS", "note_unit_count": 1, "note_unit_kind_counts": {"endnote": 1}, "target_ref_preview": ["{{NOTE_REF:fn-00094}}"], "page_span": [337, 337]}, {"section_id": "toc-ch-002-leçondu17janvier1979", "section_title": "Leçon du 17 janvier 1979", "note_unit_count": 24, "note_unit_kind_counts": {"endnote": 24}, "target_ref_preview": ["{{NOTE_REF:fn-00011}}", "{{NOTE_REF:fn-00012}}", "{{NOTE_REF:fn-00013}}", "{{NOTE_REF:fn-00014}}", "{{NOTE_REF:fn-00015}}"], "page_span": [44, 65]}, {"section_id": "toc-ch-002-situationdescours", "section_title": "SITUATION DES COURS", "note_unit_count": 14, "note_unit_kind_counts": {"endnote": 14}, "target_ref_preview": ["{{NOTE_REF:fn-00095}}", "{{NOTE_REF:fn-00096}}", "{{NOTE_REF:fn-00097}}", "{{NOTE_REF:fn-00098}}", "{{NOTE_REF:fn-00099}}"], "page_span": [343, 348]}, {"section_id": "toc-ch-003-leçondu24janvier1979", "section_title": "Leçon du 24 janvier 1979", "note_unit_count": 43, "note_unit_kind_counts": {"endnote": 43}, "target_ref_preview": ["{{NOTE_REF:fn-00018}}", "{{NOTE_REF:fn-00019}}", "{{NOTE_REF:fn-00020}}", "{{NOTE_REF:fn-00021}}", "{{NOTE_REF:fn-00022}}"], "page_span": [71, 89]}, {"section_id": "toc-ch-004-leçondu31janvier1979", "section_title": "Leçon du 31 janvier 1979", "note_unit_count": 56, "note_unit_kind_counts": {"endnote": 56}, "target_ref_preview": ["{{NOTE_REF:fn-00027}}", "{{NOTE_REF:fn-00028}}", "{{NOTE_REF:fn-00029}}", "{{NOTE_REF:en-00070}}", "{{NOTE_REF:en-00071}}"], "page_span": [99, 117]}, {"section_id": "toc-ch-005-leçondu7février1979", "section_title": "Leçon du 7 février 1979", "note_unit_count": 62, "note_unit_kind_counts": {"endnote": 62}, "target_ref_preview": ["{{NOTE_REF:fn-00030}}", "{{NOTE_REF:fn-00031}}", "{{NOTE_REF:fn-00032}}", "{{NOTE_REF:fn-00033}}", "{{NOTE_REF:fn-00034}}"], "page_span": [122, 147]}, {"section_id": "toc-ch-006-leçondu14février1979", "section_title": "Leçon du 14 février 1979", "note_unit_count": 72, "note_unit_kind_counts": {"endnote": 72}, "target_ref_preview": ["{{NOTE_REF:fn-00038}}", "{{NOTE_REF:fn-00039}}", "{{NOTE_REF:fn-00040}}", "{{NOTE_REF:fn-00041}}", "{{NOTE_REF:fn-00042}}"], "page_span": [150, 177]}]`
- export_merge_rows: `[{"title": "Leçon du 10 janvier 1979", "path": "chapters/001-Leçon du 10 janvier 1979.md", "note_unit_count": 28, "local_ref_total": 19, "local_def_total": 18, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 17 janvier 1979", "path": "chapters/002-Leçon du 17 janvier 1979.md", "note_unit_count": 24, "local_ref_total": 17, "local_def_total": 16, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 24 janvier 1979", "path": "chapters/003-Leçon du 24 janvier 1979.md", "note_unit_count": 43, "local_ref_total": 32, "local_def_total": 31, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 31 janvier 1979", "path": "chapters/004-Leçon du 31 janvier 1979.md", "note_unit_count": 56, "local_ref_total": 53, "local_def_total": 49, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 7 février 1979", "path": "chapters/005-Leçon du 7 février 1979.md", "note_unit_count": 62, "local_ref_total": 51, "local_def_total": 51, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 14 février 1979", "path": "chapters/006-Leçon du 14 février 1979.md", "note_unit_count": 72, "local_ref_total": 61, "local_def_total": 57, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 21 février 1979", "path": "chapters/007-Leçon du 21 février 1979.md", "note_unit_count": 48, "local_ref_total": 39, "local_def_total": 37, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": ["8"]}, {"title": "Leçon du 7 mars 1979", "path": "chapters/008-Leçon du 7 mars 1979.md", "note_unit_count": 59, "local_ref_total": 51, "local_def_total": 49, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{}`
- link_resolver_counts: `{"rule": 535}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "", "page_no": 8, "paragraph_index": 0, "marker": "1", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00002", "chapter_id": "", "page_no": 9, "paragraph_index": 0, "marker": "1", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00003", "chapter_id": "", "page_no": 9, "paragraph_index": 0, "marker": "2", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00004", "chapter_id": "", "page_no": 9, "paragraph_index": 0, "marker": "3", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00005", "chapter_id": "", "page_no": 9, "paragraph_index": 0, "marker": "4", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00006", "chapter_id": "", "page_no": 10, "paragraph_index": 0, "marker": "5", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00007", "chapter_id": "", "page_no": 11, "paragraph_index": 0, "marker": "8", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00008", "chapter_id": "toc-ch-001-leçondu10janvier1979", "page_no": 17, "paragraph_index": 0, "marker": "1", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00001", "status": "orphan_anchor", "resolver": "rule", "marker": "1", "page_span": [8, 8]}, {"link_id": "link-00002", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00002", "status": "orphan_anchor", "resolver": "rule", "marker": "1", "page_span": [9, 9]}, {"link_id": "link-00003", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00003", "status": "orphan_anchor", "resolver": "rule", "marker": "2", "page_span": [9, 9]}, {"link_id": "link-00004", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00004", "status": "orphan_anchor", "resolver": "rule", "marker": "3", "page_span": [9, 9]}, {"link_id": "link-00005", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00005", "status": "orphan_anchor", "resolver": "rule", "marker": "4", "page_span": [9, 9]}, {"link_id": "link-00006", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00006", "status": "orphan_anchor", "resolver": "rule", "marker": "5", "page_span": [10, 10]}, {"link_id": "link-00007", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00007", "status": "orphan_anchor", "resolver": "rule", "marker": "8", "page_span": [11, 11]}, {"link_id": "link-00008", "chapter_id": "toc-ch-001-leçondu10janvier1979", "note_item_id": "", "anchor_id": "anchor-00008", "status": "orphan_anchor", "resolver": "rule", "marker": "1", "page_span": [17, 17]}]`

## 阻塞定位明细
