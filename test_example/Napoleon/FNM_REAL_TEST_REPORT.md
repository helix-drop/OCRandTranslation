# FNM Real Test Report — Napoleon

- doc_id: `5df1d3d7f9c1`
- 状态: `blocked`
- 导出可用: `False`
- 阻塞原因: `["contract_first_marker_not_one", "contract_marker_gap", "contract_def_anchor_mismatch", "link_quality_low", "structure_review_required"]`
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
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces", "/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.Napoleon.test.zip", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.test.zip", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `1081`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=3, prompt=4119, completion=4608, total=8727
- llm_repair.cluster_request: request=0, prompt=0, completion=0, total=0
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `18`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `0`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 20, "resolved_anchor_count": 20, "provisional_anchor_count": 0, "section_node_count": 27, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": ["Préambule", "« Une invention utile dans le genre funeste »", "Un médecin au chevet du corps de l’État", "Spectres de la guillotine", "Maisons de santé, maisons d’arrêt", "Dissidence ou démence ?", "« Cet homme n’est pas aliéné » : Sade à Charenton", "La monomanie orgueilleuse ou le mal du siècle"], "demoted_chapter_titles_preview": ["L'HOMME QUI SE PRENAIT POUR NAPOLÉON", "DU MÊME AUTEUR", "Préambule", "I", "Chagrins domestiques", "Amour", "Dévotion ou fanatisme", "Événements de la Révolution"], "optimized_anchor_count": 18, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 0}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 6, "endnotes": 0, "chapter": 19, "section": 0, "post_body": 1, "back_matter": 5, "front_matter": 0}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.Napoleon.blocked.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.blocked.test.zip`

## LLM 交互摘要
- trace_count: `17`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/visual_toc.manual_input_extract.002.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/visual_toc.manual_input_extract.003.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.001.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.003.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.004.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.005.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.006.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.007.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.008.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.009.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.010.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.011.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.012.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.013.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces/llm_repair.cluster_request.014.json`

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
- note_capture_summary: `{"expected_anchor_count": 476, "captured_note_count": 460, "capture_ratio": 0.9664, "sparse_capture_chapter_ids": [], "dense_anchor_zero_capture_pages": [], "chapters": [{"chapter_id": "toc-ch-001-préambule", "note_mode": "footnote_primary", "expected_anchor_count": 41, "captured_note_count": 44, "capture_ratio": 1.0732}, {"chapter_id": "toc-ch-002-uneinventionutiledansleg", "note_mode": "footnote_primary", "expected_anchor_count": 16, "captured_note_count": 16, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-003-unmédecinauchevetducorps", "note_mode": "footnote_primary", "expected_anchor_count": 29, "captured_note_count": 26, "capture_ratio": 0.8966}, {"chapter_id": "toc-ch-004-lesévénementsdelarévolut", "note_mode": "footnote_primary", "expected_anchor_count": 18, "captured_note_count": 16, "capture_ratio": 0.8889}, {"chapter_id": "toc-ch-005-spectresdelaguillotine", "note_mode": "footnote_primary", "expected_anchor_count": 22, "captured_note_count": 22, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-006-lasileprisonpolitique", "note_mode": "book_endnote_bound", "expected_anchor_count": 2, "captured_note_count": 0, "capture_ratio": 0.0}, {"chapter_id": "toc-ch-007-maisonsdesantémaisonsdar", "note_mode": "footnote_primary", "expected_anchor_count": 22, "captured_note_count": 23, "capture_ratio": 1.0455}, {"chapter_id": "toc-ch-008-dissidenceoudémence", "note_mode": "footnote_primary", "expected_anchor_count": 10, "captured_note_count": 11, "capture_ratio": 1.1}, {"chapter_id": "toc-ch-009-cethommenestpasaliénésad", "note_mode": "footnote_primary", "expected_anchor_count": 28, "captured_note_count": 30, "capture_ratio": 1.0714}, {"chapter_id": "toc-ch-010-lamonomanieorgueilleuseo", "note_mode": "footnote_primary", "expected_anchor_count": 26, "captured_note_count": 24, "capture_ratio": 0.9231}, {"chapter_id": "toc-ch-011-lemaîtredelunivers", "note_mode": "footnote_primary", "expected_anchor_count": 29, "captured_note_count": 23, "capture_ratio": 0.7931}, {"chapter_id": "toc-ch-012-lusurpateur", "note_mode": "footnote_primary", "expected_anchor_count": 32, "captured_note_count": 31, "capture_ratio": 0.9688}, {"chapter_id": "toc-ch-013-théroignedeméricourtoula", "note_mode": "footnote_primary", "expected_anchor_count": 8, "captured_note_count": 8, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-014-1830oulamaladiedelacivil", "note_mode": "footnote_primary", "expected_anchor_count": 26, "captured_note_count": 22, "capture_ratio": 0.8462}, {"chapter_id": "toc-ch-015-1848oulapestedémocratiqu", "note_mode": "footnote_primary", "expected_anchor_count": 55, "captured_note_count": 52, "capture_ratio": 0.9455}, {"chapter_id": "toc-ch-016-lasiledelamisère", "note_mode": "footnote_primary", "expected_anchor_count": 39, "captured_note_count": 45, "capture_ratio": 1.1538}, {"chapter_id": "toc-ch-017-jeannedarcetlespanophobe", "note_mode": "footnote_primary", "expected_anchor_count": 16, "captured_note_count": 15, "capture_ratio": 0.9375}, {"chapter_id": "toc-ch-018-deschacalsdespiesdessing", "note_mode": "footnote_primary", "expected_anchor_count": 38, "captured_note_count": 33, "capture_ratio": 0.8684}, {"chapter_id": "toc-ch-019-lesbégaiementsdelhistoir", "note_mode": "footnote_primary", "expected_anchor_count": 15, "captured_note_count": 16, "capture_ratio": 1.0667}, {"chapter_id": "toc-ch-020-postambule", "note_mode": "no_notes", "expected_anchor_count": 4, "captured_note_count": 3, "capture_ratio": 0.75}]}`
- book_endnote_stream_summary: `{"chapter_count": 0, "chapters_with_endnote_stream": [], "high_concentration_chapter_ids": [], "chapters": []}`
- endnote_array_rows: `[]`

### 尾注拼接
- decision_basis: `["fnm_translation_units.kind/owner_kind/section_id/target_ref", "导出 chapter markdown 中 local refs/local defs 的闭合情况", "structure.freeze_note_unit_summary"]`
- freeze_note_unit_summary: `{"chapter_view_note_unit_count": 460, "owner_fallback_note_unit_count": 0, "unresolved_note_item_count": 0, "unresolved_note_item_ids_preview": []}`
- note_unit_rows: `[{"section_id": "toc-ch-001-préambule", "section_title": "Préambule", "note_unit_count": 44, "note_unit_kind_counts": {"footnote": 44}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [7, 40]}, {"section_id": "toc-ch-002-uneinventionutiledansleg", "section_title": "« Une invention utile dans le genre funeste »", "note_unit_count": 16, "note_unit_kind_counts": {"footnote": 16}, "target_ref_preview": ["{{NOTE_REF:fn-00045}}", "{{NOTE_REF:fn-00046}}", "{{NOTE_REF:fn-00047}}", "{{NOTE_REF:fn-00048}}", "{{NOTE_REF:fn-00049}}"], "page_span": [41, 49]}, {"section_id": "toc-ch-003-unmédecinauchevetducorps", "section_title": "Un médecin au chevet du corps de l’État", "note_unit_count": 26, "note_unit_kind_counts": {"footnote": 26}, "target_ref_preview": ["{{NOTE_REF:fn-00061}}", "{{NOTE_REF:fn-00062}}", "{{NOTE_REF:fn-00063}}", "{{NOTE_REF:fn-00064}}", "{{NOTE_REF:fn-00065}}"], "page_span": [50, 74]}, {"section_id": "toc-ch-004-lesévénementsdelarévolut", "section_title": "Les « événements de la Révolution »", "note_unit_count": 16, "note_unit_kind_counts": {"footnote": 16}, "target_ref_preview": ["{{NOTE_REF:fn-00087}}", "{{NOTE_REF:fn-00088}}", "{{NOTE_REF:fn-00089}}", "{{NOTE_REF:fn-00090}}", "{{NOTE_REF:fn-00091}}"], "page_span": [75, 86]}, {"section_id": "toc-ch-005-spectresdelaguillotine", "section_title": "Spectres de la guillotine", "note_unit_count": 22, "note_unit_kind_counts": {"footnote": 22}, "target_ref_preview": ["{{NOTE_REF:fn-00103}}", "{{NOTE_REF:fn-00104}}", "{{NOTE_REF:fn-00105}}", "{{NOTE_REF:fn-00106}}", "{{NOTE_REF:fn-00107}}"], "page_span": [87, 103]}, {"section_id": "toc-ch-007-maisonsdesantémaisonsdar", "section_title": "Maisons de santé, maisons d’arrêt", "note_unit_count": 23, "note_unit_kind_counts": {"footnote": 23}, "target_ref_preview": ["{{NOTE_REF:fn-00125}}", "{{NOTE_REF:fn-00126}}", "{{NOTE_REF:fn-00127}}", "{{NOTE_REF:fn-00128}}", "{{NOTE_REF:fn-00129}}"], "page_span": [106, 119]}, {"section_id": "toc-ch-008-dissidenceoudémence", "section_title": "Dissidence ou démence ?", "note_unit_count": 11, "note_unit_kind_counts": {"footnote": 11}, "target_ref_preview": ["{{NOTE_REF:fn-00148}}", "{{NOTE_REF:fn-00149}}", "{{NOTE_REF:fn-00150}}", "{{NOTE_REF:fn-00151}}", "{{NOTE_REF:fn-00152}}"], "page_span": [122, 136]}, {"section_id": "toc-ch-009-cethommenestpasaliénésad", "section_title": "« Cet homme n’est pas aliéné » : Sade à Charenton", "note_unit_count": 30, "note_unit_kind_counts": {"footnote": 30}, "target_ref_preview": ["{{NOTE_REF:fn-00159}}", "{{NOTE_REF:fn-00160}}", "{{NOTE_REF:fn-00161}}", "{{NOTE_REF:fn-00162}}", "{{NOTE_REF:fn-00163}}"], "page_span": [139, 165]}]`
- export_merge_rows: `[]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{"matched": 460, "footnote_orphan_note": 0, "footnote_orphan_anchor": 17, "endnote_orphan_note": 0, "endnote_orphan_anchor": 1, "ambiguous": 0, "ignored": 12, "fallback_count": 41, "repair_count": 18, "fallback_matched_count": 41, "fallback_match_ratio": 0.0891304347826087}`
- link_resolver_counts: `{"rule": 431, "fallback": 41, "repair": 18}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "toc-ch-001-préambule", "page_no": 7, "paragraph_index": 0, "marker": "1", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "Tout essai part d’une question qui le fonde, dont elle est à la fois le fanal et le fil rouge, le point de repère et l’axe directeur. Si abs..."}, {"anchor_id": "anchor-00002", "chapter_id": "toc-ch-001-préambule", "page_no": 8, "paragraph_index": 2, "marker": "2", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "«L’influence de nos malheurs politiques a été si constante, écrivait le docteur Étienne Esquirol en 1816, que je pourrais donner l’histoire..."}, {"anchor_id": "anchor-00003", "chapter_id": "toc-ch-001-préambule", "page_no": 8, "paragraph_index": 2, "marker": "3", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "«L’influence de nos malheurs politiques a été si constante, écrivait le docteur Étienne Esquirol en 1816, que je pourrais donner l’histoire..."}, {"anchor_id": "synthetic-footnote-00001", "chapter_id": "toc-ch-001-préambule", "page_no": 9, "paragraph_index": 999, "marker": "4", "anchor_kind": "footnote", "certainty": 0.4, "source_text_preview": "Frantz Fanon, Les Damnés de la terre [1961], La Découverte, 2002. Voir en particulier le dernier chapitre, « Guerre coloniale et troubles me..."}, {"anchor_id": "synthetic-footnote-00002", "chapter_id": "toc-ch-001-préambule", "page_no": 9, "paragraph_index": 999, "marker": "5", "anchor_kind": "footnote", "certainty": 0.4, "source_text_preview": "Françoise Davoine et Jean-Max Gaudillère, Histoire et trauma. La folie des guerres, Stock, «L'autre pensée», 2006."}, {"anchor_id": "synthetic-footnote-00003", "chapter_id": "toc-ch-001-préambule", "page_no": 9, "paragraph_index": 999, "marker": "6", "anchor_kind": "footnote", "certainty": 0.4, "source_text_preview": "Cathy Caruth (éd.), Trauma : Explorations in Memory, Baltimore, The Johns Hopkins University Press, 1995; Cathy Caruth, Unclaimed Experience..."}, {"anchor_id": "anchor-00004", "chapter_id": "toc-ch-001-préambule", "page_no": 10, "paragraph_index": 0, "marker": "7", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "continents, les cultures⁷. » Délire dont on peut dire, mieux que du bon sens, qu'il est sans doute la chose au monde la plus partagée. Qu'es..."}, {"anchor_id": "anchor-00005", "chapter_id": "toc-ch-001-préambule", "page_no": 10, "paragraph_index": 0, "marker": "8", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "continents, les cultures⁷. » Délire dont on peut dire, mieux que du bon sens, qu'il est sans doute la chose au monde la plus partagée. Qu'es..."}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00001", "anchor_id": "anchor-00001", "status": "matched", "resolver": "rule", "marker": "1", "page_span": [7, 7]}, {"link_id": "link-00002", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00002", "anchor_id": "anchor-00002", "status": "matched", "resolver": "rule", "marker": "2", "page_span": [8, 8]}, {"link_id": "link-00003", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00003", "anchor_id": "anchor-00003", "status": "matched", "resolver": "rule", "marker": "3", "page_span": [8, 8]}, {"link_id": "link-00004", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00004", "anchor_id": "synthetic-footnote-00001", "status": "matched", "resolver": "fallback", "marker": "4", "page_span": [9, 9]}, {"link_id": "link-00005", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00005", "anchor_id": "synthetic-footnote-00002", "status": "matched", "resolver": "fallback", "marker": "5", "page_span": [9, 9]}, {"link_id": "link-00006", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00006", "anchor_id": "synthetic-footnote-00003", "status": "matched", "resolver": "fallback", "marker": "6", "page_span": [9, 9]}, {"link_id": "link-00007", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00007", "anchor_id": "anchor-00004", "status": "matched", "resolver": "rule", "marker": "7", "page_span": [10, 10]}, {"link_id": "link-00008", "chapter_id": "toc-ch-001-préambule", "note_item_id": "fn-00008", "anchor_id": "anchor-00005", "status": "matched", "resolver": "rule", "marker": "8", "page_span": [10, 10]}]`

## 阻塞定位明细
- structure_verify / note_link_orphan_anchor: `原书 p.34 ¶0 — souffrance, dans tous les sens du terme. Car ces registres sont lacunaires à plu...` | `souffrance, dans tous les sens du terme. Car ces registres sont lacunaires à plus d'un titre. Le premier volume d'observations médicales de...`
- structure_verify / note_link_orphan_anchor: `原书 p.46 ¶1 — La France n'a pas inventé ce mode d'exécution, elle en a changé l'échelle de pro...` | `La France n'a pas inventé ce mode d'exécution, elle en a changé l'échelle de production, en faisant entrer la mort dans l'ère technique et s...`
- structure_verify / note_link_orphan_anchor: `原书 p.47 ¶0 — de l’Intérieur lui refusera le brevet qu’il réclame : « Il répu- gne à l’humanit...` | `de l’Intérieur lui refusera le brevet qu’il réclame : « Il répu- gne à l’humanité d’accorder un brevet d’invention pour une découverte de ce...`
- structure_verify / note_link_orphan_anchor: `原书 p.58 ¶0 — La première consiste dans une certaine extase de prospérité publique, & un amour...` | `La première consiste dans une certaine extase de prospérité publique, & un amour de la patrie porté jusqu'au délire, comme les visions de ce...`
- structure_verify / note_link_orphan_anchor: `原书 p.66 ¶0 — ne prévois qu'anarchie, que factions, que guerres désastreuses, même pour les va...` | `ne prévois qu'anarchie, que factions, que guerres désastreuses, même pour les vainqueurs, et certainement je connais bien maintenant ce pays...`
- structure_verify / note_link_orphan_anchor: `原书 p.71 ¶1 — Il existe un autre texte de Pinel à cette époque, intitulé « Observations sur l’...` | `Il existe un autre texte de Pinel à cette époque, intitulé « Observations sur l’hospice des insensés de Bicêtre ». Il est, pour ainsi dire,...`
- structure_verify / note_link_orphan_anchor: `原书 p.92 ¶1 — Mais le choc salutaire escompté a été de courte durée, puisque, avant même d'app...` | `Mais le choc salutaire escompté a été de courte durée, puisque, avant même d'apprendre qu'il avait été trompé, l'aliéné est retombé dans son...`
- structure_verify / note_link_orphan_anchor: `原书 p.105 ¶0 — Le 6 août 1793, jour de la nomination officielle de Pinel à Bicêtre, la maison B...` | `Le 6 août 1793, jour de la nomination officielle de Pinel à Bicêtre, la maison Belhomme, où il exerçait à titre de médecin consultant depuis...`
- structure_verify / note_link_orphan_anchor: `原书 p.155 ¶0 — temps en calculs, comptes et décomptes, énumération des jours de détention, mais...` | `temps en calculs, comptes et décomptes, énumération des jours de détention, mais aussi à une réverie superlative autour de dates et de nombr...`
- structure_verify / note_link_orphan_anchor: `原书 p.178 ¶1 — Sand qu’elles [ont] lus sans les comprendre $ ^{21} $ ».` | `Sand qu’elles [ont] lus sans les comprendre $ ^{21} $ ».`
- structure_verify / note_link_orphan_anchor: `原书 p.182 ¶0 — incarnation de « la transition régnante $ ^{25} $ ». Or on ne s'identifie pas à...` | `incarnation de « la transition régnante $ ^{25} $ ». Or on ne s'identifie pas à une transition. Trop humain, trop simple, trop bourgeois, ce...`
- structure_verify / note_link_orphan_anchor: `原书 p.186 ¶0 — mort au Temple en 1795 à l'âge de dix ans, mais prétendument enlevé ou évadé, a...` | `mort au Temple en 1795 à l'âge de dix ans, mais prétendument enlevé ou évadé, a suscité une centaine de vocations à travers l'Europe, dont c...`
- structure_verify / note_link_orphan_anchor: `原书 p.220 ¶0 — négligée. Elle n'aura pas échappé en revanche à Jacques Lacan qui, abordant l'in...` | `négligée. Elle n'aura pas échappé en revanche à Jacques Lacan qui, abordant l'infatuation du sujet, remarque : « [S]i un homme qui se croit...`
- structure_verify / note_link_orphan_anchor: `原书 p.239 ¶0 — d'Indépendance aux États-Unis, la Révolution française, avivant les passions et...` | `d'Indépendance aux États-Unis, la Révolution française, avivant les passions et déplaçant les hommes, sont autant de troubles pris en exempl...`
- structure_verify / note_link_orphan_anchor: `原书 p.275 ¶0 — Tandis que Victor Hugo observe la scène, Alexis de Tocqueville est abordé dans l...` | `Tandis que Victor Hugo observe la scène, Alexis de Tocqueville est abordé dans la cohue par le docteur Ulysse Trélat, député du Puy-de-Dôme....`
- structure_verify / note_link_orphan_anchor: `原书 p.279 ¶0 — tuant la figure de l'homme « hors de lui », dont l'Autoportrait de Courbet, dit...` | `tuant la figure de l'homme « hors de lui », dont l'Autoportrait de Courbet, dit Le Désespéré (1843), a popularisé l'image. Gestes, cris, reg...`
- structure_verify / note_link_orphan_anchor: `原书 p.318 ¶1 — On s'en tiendra donc aux résultats globaux donnés, en pourcentage, par Boucherea...` | `On s'en tiendra donc aux résultats globaux donnés, en pourcentage, par Bouchereau et Magnan pour l'année 1871 $ ^{19} $:`
- structure_verify / note_link_orphan_anchor: `原书 p.338 ¶1 — En cela, les aliénistes confortent l'opinion bourgeoise, prompte à assimiler la...` | `En cela, les aliénistes confortent l'opinion bourgeoise, prompte à assimiler la Commune à un pur acte de démence. L'évidence est en particul...`
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
