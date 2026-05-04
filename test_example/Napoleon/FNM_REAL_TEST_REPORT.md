# FNM Real Test Report — Napoleon

- doc_id: `5df1d3d7f9c1`
- 状态: `blocked`
- 导出可用: `False`
- 阻塞原因: `["freeze_matched_ref_not_injected", "export_audit_blocking", "export_cross_chapter_contamination", "structure_review_required"]`
- translation_mode: `placeholder`
- translation_api_called: `False`
- current_stage: `report_write`

## 输入资产
- pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Napoleon/把自己当成是拿破仑的人L'homme qui se prenait pour Napoléon_ Pour une histoire -- Laure Murat; Gallimard -- NRF (Series), Paris, ©2011 -- Gallimard.pdf` size=`381232917` sha256=`15be9fe00953d0dbdc7aec42f8155e0ed59f32e4414b846c8a4f20bcca1dab5b`
- raw_pages: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Napoleon/raw_pages.json` size=`7568675` sha256=`06c82dd1e495910c7c243eb470d170f24d6a59d9b92979e45ed8933bc06a5718`
- raw_pages.page_count: `396`
- raw_source_markdown: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Napoleon/raw_source_markdown.md` size=`599223` sha256=`d5b8c1815dd4b6203c1ee9ba670e16a3cfb381c395680b00911491ffe2f864bb`
- raw_source_markdown.usage_note: `本轮只作为输入资产校验与报告证据，不回灌数据库。`
- raw_source_markdown.preview: `# 把自己当成是拿破仑的人L'homme qui se prenait pour Napoléon_ Pour une histoire -- Laure Murat; Gallimard -- NRF (Series), Paris, ©2011 -- Gallimard.pdf ## PDF第1页 Laure Murat # L'HOMME QUI SE PRENAIT POUR NAPOLÉON Pour une histoir...`
- manual_toc_pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Napoleon/目录.pdf` size=`663298` sha256=`a885078f02b66c5cd98968b1e06ecf1a7805d63affd61afb332df7f628dd9c1e`

## 清理结果
- removed_count: `8`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces", "/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.Napoleon.blocked.test.zip", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.blocked.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `0`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=3, prompt=4914, completion=3768, total=8682
- llm_repair.cluster_request: request=44, prompt=74908, completion=5549, total=80457
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `18`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `0`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 20, "resolved_anchor_count": 20, "provisional_anchor_count": 0, "section_node_count": 27, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": ["Préambule", "« Une invention utile dans le genre funeste »", "Un médecin au chevet du corps de l'État", "Spectres de la guillotine", "Maisons de santé, maisons d'arrêt", "Dissidence ou démence ?", "« Cet homme n'est pas aliéné » : Sade à Charenton", "La monomanie orgueilleuse ou le mal du siècle"], "demoted_chapter_titles_preview": ["L'HOMME QUI SE PRENAIT POUR NAPOLÉON", "DU MÊME AUTEUR", "Préambule", "I", "Chagrins domestiques", "Amour", "Dévotion ou fanatisme", "Événements de la Révolution"], "optimized_anchor_count": 18, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 0}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 7, "endnotes": 0, "chapter": 19, "section": 0, "post_body": 1, "back_matter": 2, "front_matter": 3}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.Napoleon.blocked.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.blocked.test.zip`

## LLM 交互摘要
- trace_count: `91`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/visual_toc.manual_input_extract.002.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/visual_toc.manual_input_extract.003.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.001.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.001.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.002.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.003.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.003.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.004.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.004.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.005.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.005.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.006.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.006.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.007.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.007.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.008.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.008.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.009.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.009.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.010.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.010.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.started.011.json`

## 模块过程取证
### 边界区分
- decision_basis: `["fnm_pages.page_role", "fnm_pages.role_reason", "fnm_pages.role_confidence", "fnm_pages.has_note_heading", "fnm_pages.section_hint"]`
- page_role_counts: `{"front_matter": 6, "body": 344, "other": 46}`
- first_body_page: `7`
- first_note_page: `None`
- page_role_samples: `[{"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 2, "target_pdf_page": 2, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 3, "target_pdf_page": 3, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 7, "target_pdf_page": 7, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 8, "target_pdf_page": 8, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 9, "target_pdf_page": 9, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 351, "target_pdf_page": 351, "page_role": "other", "role_reason": "appendix", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 352, "target_pdf_page": 352, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 353, "target_pdf_page": 353, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}]`

### 尾注区确定
- decision_basis: `["fnm_note_regions.region_kind/start_page/end_page/pages", "fnm_note_regions.bound_chapter_id", "fnm_note_regions.region_start_first_source_marker", "fnm_note_regions.region_first_note_item_marker", "structure.chapter_binding_summary", "structure.visual_toc_endnotes_summary"]`
- visual_toc_endnotes_summary: `{}`
- chapter_binding_summary: `{"region_count": 64, "book_scope_region_count": 0, "unbound_region_count": 0, "unbound_region_ids_preview": [], "unassigned_item_count": 0, "unassigned_item_ids_preview": []}`
- endnote_region_rows: `[]`

### 尾注数组建立
- decision_basis: `["fnm_note_items.region_id/chapter_id/page_no/marker", "按 region_id 聚合生成注释数组", "检查 numeric marker 连续性与首尾 marker"]`
- note_capture_summary: `{"expected_anchor_count": 460, "captured_note_count": 459, "capture_ratio": 0.9978, "sparse_capture_chapter_ids": [], "dense_anchor_zero_capture_pages": [], "chapters": [{"chapter_id": "toc-ch-001-préambule", "note_mode": "footnote_primary", "expected_anchor_count": 38, "captured_note_count": 44, "capture_ratio": 1.1579}, {"chapter_id": "toc-ch-002-uneinventionutiledansleg", "note_mode": "footnote_primary", "expected_anchor_count": 16, "captured_note_count": 16, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-003-unmédecinauchevetducorps", "note_mode": "footnote_primary", "expected_anchor_count": 29, "captured_note_count": 26, "capture_ratio": 0.8966}, {"chapter_id": "toc-ch-004-lesévénementsdelarévolut", "note_mode": "footnote_primary", "expected_anchor_count": 15, "captured_note_count": 16, "capture_ratio": 1.0667}, {"chapter_id": "toc-ch-005-spectresdelaguillotine", "note_mode": "footnote_primary", "expected_anchor_count": 24, "captured_note_count": 22, "capture_ratio": 0.9167}, {"chapter_id": "toc-ch-006-maisonsdesantémaisonsdar", "note_mode": "footnote_primary", "expected_anchor_count": 22, "captured_note_count": 23, "capture_ratio": 1.0455}, {"chapter_id": "toc-ch-007-dissidenceoudémence", "note_mode": "footnote_primary", "expected_anchor_count": 10, "captured_note_count": 11, "capture_ratio": 1.1}, {"chapter_id": "toc-ch-008-cethommenestpasaliénésad", "note_mode": "footnote_primary", "expected_anchor_count": 27, "captured_note_count": 29, "capture_ratio": 1.0741}, {"chapter_id": "toc-ch-009-lhommequiseprenaitpourna", "note_mode": "footnote_primary", "expected_anchor_count": 1, "captured_note_count": 1, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-010-lamonomanieorgueilleuseo", "note_mode": "footnote_primary", "expected_anchor_count": 25, "captured_note_count": 24, "capture_ratio": 0.96}, {"chapter_id": "toc-ch-011-lemairedelunivers", "note_mode": "footnote_primary", "expected_anchor_count": 29, "captured_note_count": 23, "capture_ratio": 0.7931}, {"chapter_id": "toc-ch-012-lusurpateur", "note_mode": "footnote_primary", "expected_anchor_count": 31, "captured_note_count": 31, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-013-théroignedeméricourtoula", "note_mode": "footnote_primary", "expected_anchor_count": 8, "captured_note_count": 8, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-014-1830oulamaladiedelacivil", "note_mode": "footnote_primary", "expected_anchor_count": 23, "captured_note_count": 22, "capture_ratio": 0.9565}, {"chapter_id": "toc-ch-015-1848oulapestedémocratiqu", "note_mode": "footnote_primary", "expected_anchor_count": 55, "captured_note_count": 52, "capture_ratio": 0.9455}, {"chapter_id": "toc-ch-016-lasiledelamisère", "note_mode": "footnote_primary", "expected_anchor_count": 39, "captured_note_count": 45, "capture_ratio": 1.1538}, {"chapter_id": "toc-ch-017-jeannedarcetlespanophobe", "note_mode": "footnote_primary", "expected_anchor_count": 15, "captured_note_count": 15, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-018-deschacalsdespiesdessing", "note_mode": "footnote_primary", "expected_anchor_count": 34, "captured_note_count": 32, "capture_ratio": 0.9412}, {"chapter_id": "toc-ch-019-lesbégaiementsdelhistoir", "note_mode": "footnote_primary", "expected_anchor_count": 15, "captured_note_count": 16, "capture_ratio": 1.0667}, {"chapter_id": "toc-ch-020-postambule", "note_mode": "no_notes", "expected_anchor_count": 4, "captured_note_count": 3, "capture_ratio": 0.75}]}`
- book_endnote_stream_summary: `{"chapter_count": 0, "chapters_with_endnote_stream": [], "high_concentration_chapter_ids": [], "chapters": []}`
- endnote_array_rows: `[]`

### 尾注拼接
- decision_basis: `["fnm_translation_units.kind/owner_kind/section_id/target_ref", "导出 chapter markdown 中 local refs/local defs 的闭合情况", "structure.freeze_note_unit_summary"]`
- freeze_note_unit_summary: `{"chapter_view_note_unit_count": 459, "owner_fallback_note_unit_count": 0, "unresolved_note_item_count": 0, "unresolved_note_item_ids_preview": []}`
- note_unit_rows: `[{"section_id": "toc-ch-001-préambule", "section_title": "Préambule", "note_unit_count": 44, "note_unit_kind_counts": {"footnote": 44}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [7, 40]}, {"section_id": "toc-ch-002-uneinventionutiledansleg", "section_title": "« Une invention utile dans le genre funeste »", "note_unit_count": 16, "note_unit_kind_counts": {"footnote": 16}, "target_ref_preview": ["{{NOTE_REF:fn-00045}}", "{{NOTE_REF:fn-00046}}", "{{NOTE_REF:fn-00047}}", "{{NOTE_REF:fn-00048}}", "{{NOTE_REF:fn-00049}}"], "page_span": [41, 49]}, {"section_id": "toc-ch-003-unmédecinauchevetducorps", "section_title": "Un médecin au chevet du corps de l'État", "note_unit_count": 26, "note_unit_kind_counts": {"footnote": 26}, "target_ref_preview": ["{{NOTE_REF:fn-00061}}", "{{NOTE_REF:fn-00062}}", "{{NOTE_REF:fn-00063}}", "{{NOTE_REF:fn-00064}}", "{{NOTE_REF:fn-00065}}"], "page_span": [50, 74]}, {"section_id": "toc-ch-004-lesévénementsdelarévolut", "section_title": "Les « événements de la Révolution »", "note_unit_count": 16, "note_unit_kind_counts": {"footnote": 16}, "target_ref_preview": ["{{NOTE_REF:fn-00087}}", "{{NOTE_REF:fn-00088}}", "{{NOTE_REF:fn-00089}}", "{{NOTE_REF:fn-00090}}", "{{NOTE_REF:fn-00091}}"], "page_span": [75, 86]}, {"section_id": "toc-ch-005-spectresdelaguillotine", "section_title": "Spectres de la guillotine", "note_unit_count": 22, "note_unit_kind_counts": {"footnote": 22}, "target_ref_preview": ["{{NOTE_REF:fn-00103}}", "{{NOTE_REF:fn-00104}}", "{{NOTE_REF:fn-00105}}", "{{NOTE_REF:fn-00106}}", "{{NOTE_REF:fn-00107}}"], "page_span": [87, 103]}, {"section_id": "toc-ch-006-maisonsdesantémaisonsdar", "section_title": "Maisons de santé, maisons d'arrêt", "note_unit_count": 23, "note_unit_kind_counts": {"footnote": 23}, "target_ref_preview": ["{{NOTE_REF:fn-00125}}", "{{NOTE_REF:fn-00126}}", "{{NOTE_REF:fn-00127}}", "{{NOTE_REF:fn-00128}}", "{{NOTE_REF:fn-00129}}"], "page_span": [106, 119]}, {"section_id": "toc-ch-007-dissidenceoudémence", "section_title": "Dissidence ou démence ?", "note_unit_count": 11, "note_unit_kind_counts": {"footnote": 11}, "target_ref_preview": ["{{NOTE_REF:fn-00148}}", "{{NOTE_REF:fn-00149}}", "{{NOTE_REF:fn-00150}}", "{{NOTE_REF:fn-00151}}", "{{NOTE_REF:fn-00152}}"], "page_span": [122, 136]}, {"section_id": "toc-ch-008-cethommenestpasaliénésad", "section_title": "« Cet homme n'est pas aliéné » : Sade à Charenton", "note_unit_count": 29, "note_unit_kind_counts": {"footnote": 29}, "target_ref_preview": ["{{NOTE_REF:fn-00159}}", "{{NOTE_REF:fn-00160}}", "{{NOTE_REF:fn-00161}}", "{{NOTE_REF:fn-00162}}", "{{NOTE_REF:fn-00163}}"], "page_span": [139, 162]}]`
- export_merge_rows: `[]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{"matched": 404, "footnote_orphan_note": 0, "footnote_orphan_anchor": 0, "endnote_orphan_note": 0, "endnote_orphan_anchor": 0, "ambiguous": 55, "ignored": 5, "fallback_count": 18, "repair_count": 33, "fallback_matched_count": 18, "fallback_match_ratio": 0.04455445544554455}`
- link_resolver_counts: `{"rule": 465, "repair": 55}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "toc-ch-001-préambule", "page_no": 7, "paragraph_index": 0, "marker": "1", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "Tout essai part d’une question qui le fonde, dont elle est à la fois le fanal et le fil rouge, le point de repère et l’axe directeur. Si abs..."}, {"anchor_id": "llm-anchor-fn-00039", "chapter_id": "toc-ch-001-préambule", "page_no": 7, "paragraph_index": 0, "marker": "40", "anchor_kind": "footnote", "certainty": 0.95, "source_text_preview": "comment délire-t-on l’Histoire¹"}, {"anchor_id": "anchor-00002", "chapter_id": "toc-ch-001-préambule", "page_no": 7, "paragraph_index": 1, "marker": "1", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "Tout essai part d’une question qui le fonde, dont elle est à la fois le fanal et le fil rouge, le point de repère et l’axe directeur. Si abs..."}, {"anchor_id": "anchor-00003", "chapter_id": "toc-ch-001-préambule", "page_no": 8, "paragraph_index": 2, "marker": "2", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "«L’influence de nos malheurs politiques a été si constante, écrivait le docteur Étienne Esquirol en 1816, que je pourrais donner l’histoire..."}, {"anchor_id": "anchor-00004", "chapter_id": "toc-ch-001-préambule", "page_no": 8, "paragraph_index": 2, "marker": "3", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "«L’influence de nos malheurs politiques a été si constante, écrivait le docteur Étienne Esquirol en 1816, que je pourrais donner l’histoire..."}, {"anchor_id": "anchor-00005", "chapter_id": "toc-ch-001-préambule", "page_no": 8, "paragraph_index": 3, "marker": "2", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "«L’influence de nos malheurs politiques a été si constante, écrivait le docteur Étienne Esquirol en 1816, que je pourrais donner l’histoire..."}, {"anchor_id": "anchor-00006", "chapter_id": "toc-ch-001-préambule", "page_no": 8, "paragraph_index": 3, "marker": "3", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "«L’influence de nos malheurs politiques a été si constante, écrivait le docteur Étienne Esquirol en 1816, que je pourrais donner l’histoire..."}, {"anchor_id": "anchor-00007", "chapter_id": "toc-ch-001-préambule", "page_no": 9, "paragraph_index": 1, "marker": "4", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "La folie n'a-t-elle pas au moins autant à nous apprendre que la vie onirique, dont elle est une secrète parente? Les analyses de Frantz Fano..."}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00001", "anchor_id": "", "status": "ambiguous", "resolver": "rule", "marker": "1", "page_span": [7, 7]}, {"link_id": "link-00002", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00002", "anchor_id": "", "status": "ambiguous", "resolver": "rule", "marker": "2", "page_span": [8, 8]}, {"link_id": "link-00003", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00003", "anchor_id": "", "status": "ambiguous", "resolver": "rule", "marker": "3", "page_span": [8, 8]}, {"link_id": "link-00004", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00004", "anchor_id": "anchor-00007", "status": "matched", "resolver": "rule", "marker": "4", "page_span": [9, 9]}, {"link_id": "link-00005", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00005", "anchor_id": "anchor-00008", "status": "matched", "resolver": "rule", "marker": "5", "page_span": [9, 9]}, {"link_id": "link-00006", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00006", "anchor_id": "anchor-00009", "status": "matched", "resolver": "rule", "marker": "6", "page_span": [9, 9]}, {"link_id": "link-00007", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00007", "anchor_id": "", "status": "ambiguous", "resolver": "rule", "marker": "7", "page_span": [10, 10]}, {"link_id": "link-00008", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00008", "anchor_id": "", "status": "ambiguous", "resolver": "rule", "marker": "8", "page_span": [10, 10]}]`

## 阻塞定位明细
- structure_verify / note_link_ambiguous: `原书 p.7 — Par Histoire, j'entends le déroulement des événements, en particulier politiques...` | `Par Histoire, j'entends le déroulement des événements, en particulier politiques, et non pas la discipline qui l'étudie et en fait le récit.`
- structure_verify / note_link_ambiguous: `原书 p.8 — Jean-Étienne-Dominique Esquirol, Des maladies mentales [1838], 2 vol., t. I, Fré...` | `Jean-Étienne-Dominique Esquirol, Des maladies mentales [1838], 2 vol., t. I, Frénésie éditions, coll. «Insania. Les introuvables de la psych...`
- structure_verify / note_link_ambiguous: `原书 p.8 — Charlotte Beradt, Réver sous le IIIe Reich, trad. de l'allemand par Pierre Saint...` | `Charlotte Beradt, Réver sous le IIIe Reich, trad. de l'allemand par Pierre Saint-Germain, Payot & Rivages, « Petite bibliothèque Payot », 20...`
- structure_verify / note_link_ambiguous: `原书 p.10 — Gilles Deleuze et Félix Guattari, L'Anti-Œdipe. Capitalisme et schizophrénie I,...` | `Gilles Deleuze et Félix Guattari, L'Anti-Œdipe. Capitalisme et schizophrénie I, Minuit, 1972/1973.`
- structure_verify / note_link_ambiguous: `原书 p.10 — La drapetomania, cette «manie de la fuite» bien connue des planteurs, était, sel...` | `La drapetomania, cette «manie de la fuite» bien connue des planteurs, était, selon le médecin, un trouble mental répandu mais facile à guéri...`
- structure_verify / note_link_orphan_note: `原书 p.11 — J.-E.-D. Esquirol, op. cit., t. I, p. 199; 1 $ ^{re} $ ed.: De la lypémanie ou m...` | `J.-E.-D. Esquirol, op. cit., t. I, p. 199; 1 $ ^{re} $ ed.: De la lypémanie ou mélancolie, 1820.`
- structure_verify / note_link_ambiguous: `原书 p.16 — L'intégralité du texte de la « loi sur les aliénés » de 1838 est disponible sur...` | `L'intégralité du texte de la « loi sur les aliénés » de 1838 est disponible sur : http://www.ch-charcot56.fr/textes/11838-7443.htm.`
- structure_verify / note_link_ambiguous: `原书 p.16 — J. Goldstein, Consoler et classifier, op. cit., p. 372.` | `J. Goldstein, Consoler et classifier, op. cit., p. 372.`
- structure_verify / note_link_ambiguous: `原书 p.17 — Esquirol, cité par J. Goldstein, Consoler et classifier, op. cit., p. 217.` | `Esquirol, cité par J. Goldstein, Consoler et classifier, op. cit., p. 217.`
- structure_verify / note_link_ambiguous: `原书 p.18 — «“Proust, Marcel, 46 ans, rentier”», La Revue littéraire, n° 14, Léo Scheer, mai...` | `«“Proust, Marcel, 46 ans, rentier”», La Revue littéraire, n° 14, Léo Scheer, mai 2005, p. 82-92.`
- structure_verify / note_link_orphan_note: `原书 p.18 — Cette appellation doit son origine à la loi de 1838 régissant les établissements...` | `Cette appellation doit son origine à la loi de 1838 régissant les établissements d'aliénés en France, qui imposait aux asiles de tenir et de...`
- structure_verify / note_link_ambiguous: `原书 p.19 — Histoires littéraires, revue trimestrielle consacrée à la littérature française...` | `Histoires littéraires, revue trimestrielle consacrée à la littérature française des XIXe et XXe siècles, Histoires littéraires (Paris) et Du...`
- structure_verify / note_link_ambiguous: `原书 p.20 — Cité par Pierre Nora, « Michelet, ou l’hystérie identitaire », L’Esprit créateur...` | `Cité par Pierre Nora, « Michelet, ou l’hystérie identitaire », L’Esprit créateur, vol. XLVI, n° 3, 2006, p. 6.`
- structure_verify / note_link_ambiguous: `原书 p.20 — Lucien Febvre, Combats pour l'histoire [1952], Librairie Armand Colin, 1992, p....` | `Lucien Febvre, Combats pour l'histoire [1952], Librairie Armand Colin, 1992, p. 12.`
- structure_verify / note_link_ambiguous: `原书 p.20 — Jules Michelet, «Préface de 1869», Histoire de France, in Œuvres complètes, éd....` | `Jules Michelet, «Préface de 1869», Histoire de France, in Œuvres complètes, éd. définitive, revue et corrigée, E. Flammarion, 1893-1898, p....`
- structure_verify / note_link_ambiguous: `原书 p.20 — Jean-Marc Mandosio, D'or et de sable, Ed. de l'Encyclopédie des nuisances, 2008,...` | `Jean-Marc Mandosio, D'or et de sable, Ed. de l'Encyclopédie des nuisances, 2008, p. 181.`
- structure_verify / note_link_ambiguous: `原书 p.20 — Charles-Augustin Sainte-Beuve, Portraits littéraires, t. III, Garnier frères, 18...` | `Charles-Augustin Sainte-Beuve, Portraits littéraires, t. III, Garnier frères, 1864, p. 222.`
- structure_verify / note_link_ambiguous: `原书 p.25 — Ibid., p. 58.` | `Ibid., p. 58.`
- structure_verify / note_link_ambiguous: `原书 p.26 — Jacques Derrida, «Cogito et Histoire de la folie», L'Écriture et la différence,...` | `Jacques Derrida, «Cogito et Histoire de la folie», L'Écriture et la différence, Seuil, «Points», 1967, p. 51-97. Ce texte est la version lég...`
- structure_verify / note_link_ambiguous: `原书 p.29 — Philippe Pinel, Traité médico-philosophique sur l'aliénation mentale ou la manie...` | `Philippe Pinel, Traité médico-philosophique sur l'aliénation mentale ou la manie, Richard, Caille et Ravier, an IX [1800], p. 231.`
- structure_verify / note_link_ambiguous: `原书 p.29 — Voir Trésor de la langue française : http://atilf.atilf.fr/tlf.htm. On pense éga...` | `Voir Trésor de la langue française : http://atilf.atilf.fr/tlf.htm. On pense également aux Historiétés de Tallemant des Réaux.`
- structure_verify / note_link_orphan_note: `原书 p.37 — Jules Michelet, Nos fils, cité par Paul Viallaneix dans sa préface à Jules Miche...` | `Jules Michelet, Nos fils, cité par Paul Viallaneix dans sa préface à Jules Michelet, Le Peuple, GF-Flammarion, 1974, p. 33.`
- structure_verify / note_link_ambiguous: `原书 p.42 — Louis Sébastien Mercier, Le Nouveau Paris, t. I, A Brunswick, chez les principau...` | `Louis Sébastien Mercier, Le Nouveau Paris, t. I, A Brunswick, chez les principaux libraires, 1800, p. 43.`
- structure_verify / note_link_ambiguous: `原书 p.43 — Camille Desmoulins, Le Vieux Cordelier, n° IV, 20 décembre 1793, reproduit in Œu...` | `Camille Desmoulins, Le Vieux Cordelier, n° IV, 20 décembre 1793, reproduit in Œuvres, t. II, Charpentier et Cie, 1874, p. 185.`
