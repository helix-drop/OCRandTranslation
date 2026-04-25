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
- removed_count: `5`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/FNM_REAL_TEST_REPORT.md"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `754`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=1, prompt=127, completion=24, total=151
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=6, prompt=10302, completion=3098, total=13400
- llm_repair.cluster_request: request=9, prompt=52938, completion=5080, total=58018
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `0`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `15`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 14, "resolved_anchor_count": 14, "provisional_anchor_count": 0, "section_node_count": 9, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": [], "demoted_chapter_titles_preview": ["MICHEL FOUCAULT", "Naissance de la biopolitique", "FRANÇOIS EWALD et ALESSANDRO FONTANA", "des physiocrates, de d’Argenson, d’Adam Smith, de Bentham, des utili-", "le marché, ou plutôt la concurrence pure, qui est l’essence même du", "cation, une discipline", "Indices", "liberté"], "optimized_anchor_count": 0, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 15}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 2, "endnotes": 0, "chapter": 12, "section": 0, "post_body": 2, "back_matter": 2, "front_matter": 1}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.Biopolitics.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `16`
- visual_toc.preflight: 确认当前视觉模型是否可用 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.preflight.001.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.002.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.003.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.004.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.005.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.006.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.001.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.003.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.004.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.005.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.006.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.007.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.008.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.009.json`

## 模块过程取证
### 边界区分
- decision_basis: `["fnm_pages.page_role", "fnm_pages.role_reason", "fnm_pages.role_confidence", "fnm_pages.has_note_heading", "fnm_pages.section_hint"]`
- page_role_counts: `{"front_matter": 51, "body": 298, "other": 21}`
- first_body_page: `17`
- first_note_page: `None`
- page_role_samples: `[{"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 2, "target_pdf_page": 2, "page_role": "front_matter", "role_reason": "blank_front_page", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 3, "target_pdf_page": 3, "page_role": "front_matter", "role_reason": "archive_noise", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 17, "target_pdf_page": 17, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 18, "target_pdf_page": 18, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 19, "target_pdf_page": 19, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 350, "target_pdf_page": 350, "page_role": "other", "role_reason": "index", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 351, "target_pdf_page": 351, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 352, "target_pdf_page": 352, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}]`

### 尾注区确定
- decision_basis: `["fnm_note_regions.region_kind/start_page/end_page/pages", "fnm_note_regions.bound_chapter_id", "fnm_note_regions.region_start_first_source_marker", "fnm_note_regions.region_first_note_item_marker", "structure.chapter_binding_summary", "structure.visual_toc_endnotes_summary"]`
- visual_toc_endnotes_summary: `{}`
- chapter_binding_summary: `{"region_count": 22, "book_scope_region_count": 0, "unbound_region_count": 0, "unbound_region_ids_preview": [], "unassigned_item_count": 0, "unassigned_item_ids_preview": []}`
- endnote_region_rows: `[]`

### 尾注数组建立
- decision_basis: `["fnm_note_items.region_id/chapter_id/page_no/marker", "按 region_id 聚合生成注释数组", "检查 numeric marker 连续性与首尾 marker"]`
- note_capture_summary: `{"expected_anchor_count": 35, "captured_note_count": 80, "capture_ratio": 2.2857, "sparse_capture_chapter_ids": [], "dense_anchor_zero_capture_pages": [], "chapters": [{"chapter_id": "toc-ch-001-leçondu10janvier1979", "note_mode": "footnote_primary", "expected_anchor_count": 2, "captured_note_count": 5, "capture_ratio": 2.5}, {"chapter_id": "toc-ch-002-leçondu17janvier1979", "note_mode": "footnote_primary", "expected_anchor_count": 0, "captured_note_count": 1, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-003-leçondu24janvier1979", "note_mode": "footnote_primary", "expected_anchor_count": 1, "captured_note_count": 2, "capture_ratio": 2.0}, {"chapter_id": "toc-ch-004-leçondu31janvier1979", "note_mode": "chapter_endnote_primary", "expected_anchor_count": 8, "captured_note_count": 24, "capture_ratio": 3.0}, {"chapter_id": "toc-ch-005-leçondu7février1979", "note_mode": "footnote_primary", "expected_anchor_count": 5, "captured_note_count": 0, "capture_ratio": 0.0}, {"chapter_id": "toc-ch-006-leçondu14février1979", "note_mode": "chapter_endnote_primary", "expected_anchor_count": 1, "captured_note_count": 28, "capture_ratio": 28.0}, {"chapter_id": "toc-ch-007-leçondu21février1979", "note_mode": "footnote_primary", "expected_anchor_count": 3, "captured_note_count": 0, "capture_ratio": 0.0}, {"chapter_id": "toc-ch-008-leçondu7mars1979", "note_mode": "footnote_primary", "expected_anchor_count": 11, "captured_note_count": 2, "capture_ratio": 0.1818}, {"chapter_id": "toc-ch-009-leçondu14mars1979", "note_mode": "footnote_primary", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-010-leçondu21mars1979", "note_mode": "footnote_primary", "expected_anchor_count": 1, "captured_note_count": 3, "capture_ratio": 3.0}, {"chapter_id": "toc-ch-011-leçondu28mars1979", "note_mode": "footnote_primary", "expected_anchor_count": 3, "captured_note_count": 0, "capture_ratio": 0.0}, {"chapter_id": "toc-ch-012-leçondu4avril1979", "note_mode": "footnote_primary", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-013-résuméducours", "note_mode": "no_notes", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-014-situationdescours", "note_mode": "no_notes", "expected_anchor_count": 0, "captured_note_count": 15, "capture_ratio": 1.0}]}`
- book_endnote_stream_summary: `{"chapter_count": 7, "chapters_with_endnote_stream": ["toc-ch-004-leçondu31janvier1979", "toc-ch-005-leçondu7février1979", "toc-ch-006-leçondu14février1979", "toc-ch-007-leçondu21février1979", "toc-ch-009-leçondu14mars1979", "toc-ch-011-leçondu28mars1979", "toc-ch-012-leçondu4avril1979"], "high_concentration_chapter_ids": [], "chapters": [{"chapter_id": "toc-ch-004-leçondu31janvier1979", "item_count": 24, "projection_mode_counts": {"native": 24}}, {"chapter_id": "toc-ch-005-leçondu7février1979", "item_count": 27, "projection_mode_counts": {"native": 27}}, {"chapter_id": "toc-ch-006-leçondu14février1979", "item_count": 28, "projection_mode_counts": {"native": 28}}, {"chapter_id": "toc-ch-007-leçondu21février1979", "item_count": 46, "projection_mode_counts": {"native": 46}}, {"chapter_id": "toc-ch-009-leçondu14mars1979", "item_count": 48, "projection_mode_counts": {"native": 48}}, {"chapter_id": "toc-ch-011-leçondu28mars1979", "item_count": 33, "projection_mode_counts": {"native": 33}}, {"chapter_id": "toc-ch-012-leçondu4avril1979", "item_count": 32, "projection_mode_counts": {"native": 32}}]}`
- endnote_array_rows: `[]`

### 尾注拼接
- decision_basis: `["fnm_translation_units.kind/owner_kind/section_id/target_ref", "导出 chapter markdown 中 local refs/local defs 的闭合情况", "structure.freeze_note_unit_summary"]`
- freeze_note_unit_summary: `{"chapter_view_note_unit_count": 268, "owner_fallback_note_unit_count": 0, "unresolved_note_item_count": 0, "unresolved_note_item_ids_preview": []}`
- note_unit_rows: `[{"section_id": "toc-ch-001-leçondu10janvier1979", "section_title": "Leçon du 10 janvier 1979", "note_unit_count": 5, "note_unit_kind_counts": {"footnote": 5}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [33, 37]}, {"section_id": "toc-ch-002-leçondu17janvier1979", "section_title": "Leçon du 17 janvier 1979", "note_unit_count": 1, "note_unit_kind_counts": {"footnote": 1}, "target_ref_preview": ["{{NOTE_REF:fn-00006}}"], "page_span": [62, 62]}, {"section_id": "toc-ch-003-leçondu24janvier1979", "section_title": "Leçon du 24 janvier 1979", "note_unit_count": 2, "note_unit_kind_counts": {"footnote": 2}, "target_ref_preview": ["{{NOTE_REF:fn-00007}}", "{{NOTE_REF:fn-00008}}"], "page_span": [71, 76]}, {"section_id": "toc-ch-004-leçondu31janvier1979", "section_title": "Leçon du 31 janvier 1979", "note_unit_count": 24, "note_unit_kind_counts": {"endnote": 24}, "target_ref_preview": ["{{NOTE_REF:en-00001}}", "{{NOTE_REF:en-00002}}", "{{NOTE_REF:en-00003}}", "{{NOTE_REF:en-00004}}", "{{NOTE_REF:en-00005}}"], "page_span": [111, 114]}, {"section_id": "toc-ch-005-leçondu7février1979", "section_title": "Leçon du 7 février 1979", "note_unit_count": 27, "note_unit_kind_counts": {"endnote": 27}, "target_ref_preview": ["{{NOTE_REF:en-00025}}", "{{NOTE_REF:en-00026}}", "{{NOTE_REF:en-00027}}", "{{NOTE_REF:en-00028}}", "{{NOTE_REF:en-00029}}"], "page_span": [139, 144]}, {"section_id": "toc-ch-006-leçondu14février1979", "section_title": "Leçon du 14 février 1979", "note_unit_count": 28, "note_unit_kind_counts": {"endnote": 28}, "target_ref_preview": ["{{NOTE_REF:en-00052}}", "{{NOTE_REF:en-00053}}", "{{NOTE_REF:en-00054}}", "{{NOTE_REF:en-00055}}", "{{NOTE_REF:en-00056}}"], "page_span": [170, 176]}, {"section_id": "toc-ch-007-leçondu21février1979", "section_title": "Leçon du 21 février 1979", "note_unit_count": 46, "note_unit_kind_counts": {"endnote": 46}, "target_ref_preview": ["{{NOTE_REF:en-00080}}", "{{NOTE_REF:en-00081}}", "{{NOTE_REF:en-00082}}", "{{NOTE_REF:en-00083}}", "{{NOTE_REF:en-00084}}"], "page_span": [197, 202]}, {"section_id": "toc-ch-008-leçondu7mars1979", "section_title": "Leçon du 7 mars 1979", "note_unit_count": 2, "note_unit_kind_counts": {"footnote": 2}, "target_ref_preview": ["{{NOTE_REF:fn-00009}}", "{{NOTE_REF:fn-00010}}"], "page_span": [220, 220]}]`
- export_merge_rows: `[{"title": "Leçon du 10 janvier 1979", "path": "chapters/001-Leçon du 10 janvier 1979.md", "note_unit_count": 5, "local_ref_total": 8, "local_def_total": 4, "first_local_def_marker": "3", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 17 janvier 1979", "path": "chapters/002-Leçon du 17 janvier 1979.md", "note_unit_count": 1, "local_ref_total": 2, "local_def_total": 1, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 24 janvier 1979", "path": "chapters/003-Leçon du 24 janvier 1979.md", "note_unit_count": 2, "local_ref_total": 3, "local_def_total": 2, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 31 janvier 1979", "path": "chapters/004-Leçon du 31 janvier 1979.md", "note_unit_count": 24, "local_ref_total": 27, "local_def_total": 21, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 7 février 1979", "path": "chapters/005-Leçon du 7 février 1979.md", "note_unit_count": 27, "local_ref_total": 53, "local_def_total": 26, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 14 février 1979", "path": "chapters/006-Leçon du 14 février 1979.md", "note_unit_count": 28, "local_ref_total": 40, "local_def_total": 24, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 21 février 1979", "path": "chapters/007-Leçon du 21 février 1979.md", "note_unit_count": 46, "local_ref_total": 25, "local_def_total": 25, "first_local_def_marker": "6", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Leçon du 7 mars 1979", "path": "chapters/008-Leçon du 7 mars 1979.md", "note_unit_count": 2, "local_ref_total": 3, "local_def_total": 2, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{"matched": 266, "footnote_orphan_note": 2, "footnote_orphan_anchor": 48, "endnote_orphan_note": 0, "endnote_orphan_anchor": 25, "ambiguous": 0, "ignored": 32, "fallback_count": 199, "repair_count": 43}`
- link_resolver_counts: `{"rule": 131, "repair": 43, "fallback": 199}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "toc-ch-001-leçondu10janvier1979", "page_no": 17, "paragraph_index": 1, "marker": "1", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "[Vous connaissez] la citation de Freud : « Acheronta movebo¹. » Eh bien, je voudrais placer le cours de cette année sous le signe d'une autr..."}, {"anchor_id": "anchor-00002", "chapter_id": "toc-ch-001-leçondu10janvier1979", "page_no": 17, "paragraph_index": 1, "marker": "2", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "[Vous connaissez] la citation de Freud : « Acheronta movebo¹. » Eh bien, je voudrais placer le cours de cette année sous le signe d'une autr..."}, {"anchor_id": "anchor-00003", "chapter_id": "toc-ch-001-leçondu10janvier1979", "page_no": 17, "paragraph_index": 1, "marker": "3", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "[Vous connaissez] la citation de Freud : « Acheronta movebo¹. » Eh bien, je voudrais placer le cours de cette année sous le signe d'une autr..."}, {"anchor_id": "anchor-00004", "chapter_id": "toc-ch-001-leçondu10janvier1979", "page_no": 19, "paragraph_index": 0, "marker": "4", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "grille d'intelligibilité obligatoire pour un certain nombre de pratiques concrètes, je voudrais partir de ces pratiques concrètes et passer..."}, {"anchor_id": "anchor-00005", "chapter_id": "toc-ch-001-leçondu10janvier1979", "page_no": 19, "paragraph_index": 0, "marker": "5", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "grille d'intelligibilité obligatoire pour un certain nombre de pratiques concrètes, je voudrais partir de ces pratiques concrètes et passer..."}, {"anchor_id": "anchor-00006", "chapter_id": "toc-ch-001-leçondu10janvier1979", "page_no": 19, "paragraph_index": 1, "marker": "6", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "L'an dernier, vous vous souvenez, j'avais essayé de faire l'étude de l'un de ces épisodes importants, je crois, dans l'histoire du gouvernem..."}, {"anchor_id": "anchor-00007", "chapter_id": "toc-ch-001-leçondu10janvier1979", "page_no": 24, "paragraph_index": 1, "marker": "8", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "Vous avez aussi la théorie du droit naturel et des droits naturels que l'on fait valoir comme droits imprescriptibles et qu'aucun souverain,..."}, {"anchor_id": "anchor-00008", "chapter_id": "toc-ch-001-leçondu10janvier1979", "page_no": 28, "paragraph_index": 0, "marker": "9", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "le peuvent pas, autrement dit, entre les choses à faire et les moyens à employer pour les faire d'une part, et les choses à ne pas faire. Le..."}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-004-leçondu31janvier1979", "note_item_id": "en-00001", "anchor_id": "anchor-00063", "status": "matched", "resolver": "rule", "marker": "1", "page_span": [111, 111]}, {"link_id": "link-00002", "chapter_id": "toc-ch-004-leçondu31janvier1979", "note_item_id": "en-00002", "anchor_id": "anchor-00064", "status": "matched", "resolver": "repair", "marker": "2", "page_span": [91, 91]}, {"link_id": "link-00003", "chapter_id": "toc-ch-004-leçondu31janvier1979", "note_item_id": "en-00003", "anchor_id": "anchor-00066", "status": "matched", "resolver": "rule", "marker": "3", "page_span": [111, 111]}, {"link_id": "link-00004", "chapter_id": "toc-ch-004-leçondu31janvier1979", "note_item_id": "en-00004", "anchor_id": "anchor-00181", "status": "matched", "resolver": "rule", "marker": "4", "page_span": [111, 111]}, {"link_id": "link-00005", "chapter_id": "toc-ch-004-leçondu31janvier1979", "note_item_id": "en-00005", "anchor_id": "anchor-00067", "status": "matched", "resolver": "rule", "marker": "5", "page_span": [111, 111]}, {"link_id": "link-00006", "chapter_id": "toc-ch-004-leçondu31janvier1979", "note_item_id": "en-00006", "anchor_id": "anchor-00080", "status": "matched", "resolver": "repair", "marker": "6", "page_span": [111, 111]}, {"link_id": "link-00007", "chapter_id": "toc-ch-004-leçondu31janvier1979", "note_item_id": "en-00007", "anchor_id": "anchor-00069", "status": "matched", "resolver": "rule", "marker": "7", "page_span": [111, 111]}, {"link_id": "link-00008", "chapter_id": "toc-ch-004-leçondu31janvier1979", "note_item_id": "en-00008", "anchor_id": "anchor-00070", "status": "matched", "resolver": "rule", "marker": "8", "page_span": [111, 111]}]`

## 阻塞定位明细
