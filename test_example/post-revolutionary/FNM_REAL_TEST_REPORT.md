# FNM Real Test Report — Goldstein

- doc_id: `7ba9bca783fd`
- 状态: `blocked`
- 导出可用: `False`
- 阻塞原因: `["toc_pages_unclassified", "split_items_sparse_note_capture", "contract_marker_gap", "contract_def_anchor_mismatch", "link_quality_low", "merge_frozen_ref_leak", "export_audit_blocking", "export_raw_marker_leak", "structure_review_required"]`
- translation_mode: `placeholder`
- translation_api_called: `False`
- current_stage: `report_write`

## 输入资产
- pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/post-revolutionary/Goldstein - 2005 - The post-revolutionary self politics and psyche i.pdf` size=`1319017` sha256=`d7c0294be9e87365e48e3bab9d0de4302061f9cb789322e0d0dae08a8f97e762`
- raw_pages: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/post-revolutionary/raw_pages.json` size=`9337867` sha256=`1f9905e5025a9d7776f43933f247dffaa4fcf82d2cce19477ed4c0d5ea07abaa`
- raw_pages.page_count: `431`
- raw_source_markdown: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/post-revolutionary/raw_source_markdown.md` size=`1055399` sha256=`4786dbcdb1f36f166450891c8882d3450a0efd16effa88ea1d15bef4323819c4`
- raw_source_markdown.usage_note: `本轮只作为输入资产校验与报告证据，不回灌数据库。`
- raw_source_markdown.preview: `# Goldstein - 2005 - The post-revolutionary self politics and psyche i.pdf ## PDF第1页 <div style="text-align: center;"><img src="imgs/img_in_image_box_234_10_893_941.jpg" alt="Image" width="73%" /></div> <div style="text-...`
- manual_toc_pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/post-revolutionary/目录.pdf` size=`22357` sha256=`d39c01f87f4d1976e373c25939cdc6c9f7a52b42167a915fb6d2a59c1c45622f`

## 清理结果
- removed_count: `8`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/post-revolutionary/llm_traces", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.Goldstein.blocked.test.zip", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.blocked.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `1771`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/post-revolutionary/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=2, prompt=2993, completion=2470, total=5463
- llm_repair.cluster_request: request=0, prompt=0, completion=0, total=0
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `2`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `148`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 9, "resolved_anchor_count": 9, "provisional_anchor_count": 0, "section_node_count": 181, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": ["Epilogue"], "demoted_chapter_titles_preview": ["the person would be thrown ominously off-kilter.", "List of Illustrations", "turn undergird—and create—a different kind of self.", "to the", "Imagination in Socioeconomic Discourse (1): The Trade Corporation", "The Worker's Imagination Further Scrutinized", "tices and", "Imagination in Socioeconomic Discourse (2): Credit"], "optimized_anchor_count": 2, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 148}`

## Endnotes Summary
- present: `True`
- container_title: `Notes`
- container_printed_page: `331`
- container_visual_order: `30`
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 2, "endnotes": 1, "chapter": 9, "section": 0, "post_body": 0, "back_matter": 2, "front_matter": 2}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.Goldstein.blocked.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.blocked.test.zip`

## LLM 交互摘要
- trace_count: `2`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/post-revolutionary/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/post-revolutionary/llm_traces/visual_toc.manual_input_extract.002.json`

## 模块过程取证
### 边界区分
- decision_basis: `["fnm_pages.page_role", "fnm_pages.role_reason", "fnm_pages.role_confidence", "fnm_pages.has_note_heading", "fnm_pages.section_hint"]`
- page_role_counts: `{"front_matter": 17, "body": 330, "note": 67, "other": 17}`
- first_body_page: `18`
- first_note_page: `348`
- page_role_samples: `[{"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 2, "target_pdf_page": 2, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 3, "target_pdf_page": 3, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 18, "target_pdf_page": 18, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 19, "target_pdf_page": 19, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 20, "target_pdf_page": 20, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 348, "target_pdf_page": 348, "page_role": "note", "role_reason": "endnotes_start_page_hint", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 349, "target_pdf_page": 349, "page_role": "note", "role_reason": "endnotes_start_page_hint", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 350, "target_pdf_page": 350, "page_role": "note", "role_reason": "endnotes_start_page_hint", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 415, "target_pdf_page": 415, "page_role": "other", "role_reason": "rear_sparse_other", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 416, "target_pdf_page": 416, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 417, "target_pdf_page": 417, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}]`

### 尾注区确定
- decision_basis: `["fnm_note_regions.region_kind/start_page/end_page/pages", "fnm_note_regions.bound_chapter_id", "fnm_note_regions.region_start_first_source_marker", "fnm_note_regions.region_first_note_item_marker", "structure.chapter_binding_summary", "structure.visual_toc_endnotes_summary"]`
- visual_toc_endnotes_summary: `{}`
- chapter_binding_summary: `{"region_count": 9, "book_scope_region_count": 9, "unbound_region_count": 0, "unbound_region_ids_preview": [], "unassigned_item_count": 0, "unassigned_item_ids_preview": []}`
- endnote_region_rows: `[]`

### 尾注数组建立
- decision_basis: `["fnm_note_items.region_id/chapter_id/page_no/marker", "按 region_id 聚合生成注释数组", "检查 numeric marker 连续性与首尾 marker"]`
- note_capture_summary: `{"expected_anchor_count": 915, "captured_note_count": 921, "capture_ratio": 1.0066, "sparse_capture_chapter_ids": [], "dense_anchor_zero_capture_pages": [{"chapter_id": "toc-ch-005-4anaprioriselfforthebour", "page_no": 160, "expected_anchor_count": 8, "captured_note_count": 0}, {"chapter_id": "toc-ch-008-7apalpableselfforthesoci", "page_no": 296, "expected_anchor_count": 8, "captured_note_count": 0}], "chapters": [{"chapter_id": "toc-ch-001-introductionpsychologica", "note_mode": "book_endnote_bound", "expected_anchor_count": 26, "captured_note_count": 26, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-002-1theperilsofimaginationa", "note_mode": "book_endnote_bound", "expected_anchor_count": 85, "captured_note_count": 86, "capture_ratio": 1.0118}, {"chapter_id": "toc-ch-003-2therevolutionaryschooli", "note_mode": "book_endnote_bound", "expected_anchor_count": 96, "captured_note_count": 96, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-004-3isthereaselfinthismenta", "note_mode": "book_endnote_bound", "expected_anchor_count": 108, "captured_note_count": 112, "capture_ratio": 1.037}, {"chapter_id": "toc-ch-005-4anaprioriselfforthebour", "note_mode": "book_endnote_bound", "expected_anchor_count": 136, "captured_note_count": 138, "capture_ratio": 1.0147}, {"chapter_id": "toc-ch-006-5cousinianhegemony", "note_mode": "book_endnote_bound", "expected_anchor_count": 171, "captured_note_count": 173, "capture_ratio": 1.0117}, {"chapter_id": "toc-ch-007-6religiousandsecularacce", "note_mode": "book_endnote_bound", "expected_anchor_count": 110, "captured_note_count": 109, "capture_ratio": 0.9909}, {"chapter_id": "toc-ch-008-7apalpableselfforthesoci", "note_mode": "book_endnote_bound", "expected_anchor_count": 153, "captured_note_count": 152, "capture_ratio": 0.9935}, {"chapter_id": "toc-ch-009-epilogue", "note_mode": "book_endnote_bound", "expected_anchor_count": 30, "captured_note_count": 29, "capture_ratio": 0.9667}]}`
- book_endnote_stream_summary: `{"chapter_count": 9, "chapters_with_endnote_stream": ["toc-ch-001-introductionpsychologica", "toc-ch-002-1theperilsofimaginationa", "toc-ch-003-2therevolutionaryschooli", "toc-ch-004-3isthereaselfinthismenta", "toc-ch-005-4anaprioriselfforthebour", "toc-ch-006-5cousinianhegemony", "toc-ch-007-6religiousandsecularacce", "toc-ch-008-7apalpableselfforthesoci", "toc-ch-009-epilogue"], "high_concentration_chapter_ids": ["toc-ch-004-3isthereaselfinthismenta", "toc-ch-005-4anaprioriselfforthebour", "toc-ch-006-5cousinianhegemony", "toc-ch-007-6religiousandsecularacce", "toc-ch-008-7apalpableselfforthesoci"], "chapters": [{"chapter_id": "toc-ch-001-introductionpsychologica", "item_count": 26, "projection_mode_counts": {"book_projected": 26}}, {"chapter_id": "toc-ch-002-1theperilsofimaginationa", "item_count": 86, "projection_mode_counts": {"book_projected": 84, "book_marker_projected": 2}}, {"chapter_id": "toc-ch-003-2therevolutionaryschooli", "item_count": 96, "projection_mode_counts": {"book_marker_projected": 3, "book_projected": 93}}, {"chapter_id": "toc-ch-004-3isthereaselfinthismenta", "item_count": 112, "projection_mode_counts": {"book_projected": 107, "book_marker_projected": 5}}, {"chapter_id": "toc-ch-005-4anaprioriselfforthebour", "item_count": 138, "projection_mode_counts": {"book_projected": 136, "book_marker_projected": 2}}, {"chapter_id": "toc-ch-006-5cousinianhegemony", "item_count": 173, "projection_mode_counts": {"book_marker_projected": 7, "book_projected": 166}}, {"chapter_id": "toc-ch-007-6religiousandsecularacce", "item_count": 109, "projection_mode_counts": {"book_projected": 109}}, {"chapter_id": "toc-ch-008-7apalpableselfforthesoci", "item_count": 152, "projection_mode_counts": {"book_marker_projected": 3, "book_projected": 149}}, {"chapter_id": "toc-ch-009-epilogue", "item_count": 29, "projection_mode_counts": {"book_projected": 29}}]}`
- endnote_array_rows: `[]`

### 尾注拼接
- decision_basis: `["fnm_translation_units.kind/owner_kind/section_id/target_ref", "导出 chapter markdown 中 local refs/local defs 的闭合情况", "structure.freeze_note_unit_summary"]`
- freeze_note_unit_summary: `{"chapter_view_note_unit_count": 921, "owner_fallback_note_unit_count": 0, "unresolved_note_item_count": 0, "unresolved_note_item_ids_preview": []}`
- note_unit_rows: `[{"section_id": "toc-ch-001-introductionpsychologica", "section_title": "Introduction: Psychological Interiority versus Self-Talk", "note_unit_count": 26, "note_unit_kind_counts": {"endnote": 26}, "target_ref_preview": ["{{NOTE_REF:en-00001}}", "{{NOTE_REF:en-00002}}", "{{NOTE_REF:en-00003}}", "{{NOTE_REF:en-00004}}", "{{NOTE_REF:en-00005}}"], "page_span": [348, 351]}, {"section_id": "toc-ch-002-1theperilsofimaginationa", "section_title": "1 The Perils of Imagination at the End of the Old Regime", "note_unit_count": 86, "note_unit_kind_counts": {"endnote": 86}, "target_ref_preview": ["{{NOTE_REF:en-00027}}", "{{NOTE_REF:en-00028}}", "{{NOTE_REF:en-00029}}", "{{NOTE_REF:en-00030}}", "{{NOTE_REF:en-00031}}"], "page_span": [351, 362]}, {"section_id": "toc-ch-003-2therevolutionaryschooli", "section_title": "2 The Revolutionary Schooling of Imagination", "note_unit_count": 96, "note_unit_kind_counts": {"endnote": 96}, "target_ref_preview": ["{{NOTE_REF:en-00073}}", "{{NOTE_REF:en-00086}}", "{{NOTE_REF:en-00113}}", "{{NOTE_REF:en-00114}}", "{{NOTE_REF:en-00115}}"], "page_span": [355, 368]}, {"section_id": "toc-ch-004-3isthereaselfinthismenta", "section_title": "3 Is There a Self in This Mental Apparatus?", "note_unit_count": 112, "note_unit_kind_counts": {"endnote": 112}, "target_ref_preview": ["{{NOTE_REF:en-00208}}", "{{NOTE_REF:en-00209}}", "{{NOTE_REF:en-00210}}", "{{NOTE_REF:en-00211}}", "{{NOTE_REF:en-00212}}"], "page_span": [365, 378]}, {"section_id": "toc-ch-005-4anaprioriselfforthebour", "section_title": "4 An A Priori Self for the Bourgeois Male: Victor Cousin’s Project", "note_unit_count": 138, "note_unit_kind_counts": {"endnote": 138}, "target_ref_preview": ["{{NOTE_REF:en-00316}}", "{{NOTE_REF:en-00317}}", "{{NOTE_REF:en-00318}}", "{{NOTE_REF:en-00319}}", "{{NOTE_REF:en-00320}}"], "page_span": [373, 391]}, {"section_id": "toc-ch-006-5cousinianhegemony", "section_title": "5 Cousinian Hegemony", "note_unit_count": 173, "note_unit_kind_counts": {"endnote": 173}, "target_ref_preview": ["{{NOTE_REF:en-00429}}", "{{NOTE_REF:en-00458}}", "{{NOTE_REF:en-00459}}", "{{NOTE_REF:en-00460}}", "{{NOTE_REF:en-00461}}"], "page_span": [380, 411]}, {"section_id": "toc-ch-007-6religiousandsecularacce", "section_title": "6 Religious and Secular Access to the Vie Intérieure: Renan at the Crossroads", "note_unit_count": 109, "note_unit_kind_counts": {"endnote": 109}, "target_ref_preview": ["{{NOTE_REF:en-00627}}", "{{NOTE_REF:en-00628}}", "{{NOTE_REF:en-00629}}", "{{NOTE_REF:en-00630}}", "{{NOTE_REF:en-00631}}"], "page_span": [393, 401]}, {"section_id": "toc-ch-008-7apalpableselfforthesoci", "section_title": "7 A Palpable Self for the Socially Marginal: The Phrenological Alternative", "note_unit_count": 152, "note_unit_kind_counts": {"endnote": 152}, "target_ref_preview": ["{{NOTE_REF:en-00609}}", "{{NOTE_REF:en-00739}}", "{{NOTE_REF:en-00740}}", "{{NOTE_REF:en-00741}}", "{{NOTE_REF:en-00742}}"], "page_span": [392, 413]}]`
- export_merge_rows: `[]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{"matched": 921, "footnote_orphan_note": 0, "footnote_orphan_anchor": 0, "endnote_orphan_note": 0, "endnote_orphan_anchor": 0, "ambiguous": 0, "ignored": 0, "fallback_count": 908, "repair_count": 13, "fallback_matched_count": 908, "fallback_match_ratio": 0.9858849077090119}`
- link_resolver_counts: `{"fallback": 908, "repair": 13}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 0, "marker": "1", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "of the Renaissance in Italy (1860) and divided among several disciplines, has located so many putative births of the Western self—for exampl..."}, {"anchor_id": "anchor-00002", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 0, "marker": "2", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "of the Renaissance in Italy (1860) and divided among several disciplines, has located so many putative births of the Western self—for exampl..."}, {"anchor_id": "anchor-00003", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 0, "marker": "3", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "of the Renaissance in Italy (1860) and divided among several disciplines, has located so many putative births of the Western self—for exampl..."}, {"anchor_id": "anchor-00004", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 0, "marker": "4", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "of the Renaissance in Italy (1860) and divided among several disciplines, has located so many putative births of the Western self—for exampl..."}, {"anchor_id": "anchor-00005", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 1, "marker": "5", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "Rather than attempting to illuminate this muddle through a grand theoretical intervention, I have in this book adopted a minimalist position..."}, {"anchor_id": "anchor-00006", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 1, "marker": "6", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "Rather than attempting to illuminate this muddle through a grand theoretical intervention, I have in this book adopted a minimalist position..."}, {"anchor_id": "anchor-00007", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 20, "paragraph_index": 0, "marker": "7", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "three different types of fragmentation have provided cause for worry. The type with which we are most familiar today was well evoked by Jean..."}, {"anchor_id": "anchor-00008", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 21, "paragraph_index": 0, "marker": "8", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "ican tribes, to be the persona, role, or mask, a concept referring to its possessor's social function. According to Mauss, an important evol..."}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "en-00001", "anchor_id": "anchor-00001", "status": "matched", "resolver": "fallback", "marker": "1", "page_span": [348, 348]}, {"link_id": "link-00002", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "en-00002", "anchor_id": "anchor-00002", "status": "matched", "resolver": "fallback", "marker": "2", "page_span": [348, 348]}, {"link_id": "link-00003", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "en-00003", "anchor_id": "anchor-00003", "status": "matched", "resolver": "fallback", "marker": "3", "page_span": [349, 349]}, {"link_id": "link-00004", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "en-00004", "anchor_id": "anchor-00004", "status": "matched", "resolver": "fallback", "marker": "4", "page_span": [349, 349]}, {"link_id": "link-00005", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "en-00005", "anchor_id": "anchor-00005", "status": "matched", "resolver": "fallback", "marker": "5", "page_span": [349, 349]}, {"link_id": "link-00006", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "en-00006", "anchor_id": "anchor-00006", "status": "matched", "resolver": "fallback", "marker": "6", "page_span": [349, 349]}, {"link_id": "link-00007", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "en-00007", "anchor_id": "anchor-00007", "status": "matched", "resolver": "fallback", "marker": "7", "page_span": [349, 349]}, {"link_id": "link-00008", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "en-00008", "anchor_id": "anchor-00008", "status": "matched", "resolver": "fallback", "marker": "8", "page_span": [349, 349]}]`

## 阻塞定位明细
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- export_verify / structure_review_required: `` | `["toc_pages_unclassified", "split_items_sparse_note_capture", "contract_marker_gap", "contract_def_anchor_mismatch", "link_quality_low", "merge_frozen_ref_leak", "export_audit_blocking", "export_raw_marker_leak"]`
