# FNM Real Test Report — Germany_Madness

- doc_id: `67356d1f7d9a`
- 状态: `blocked`
- 导出可用: `False`
- 阻塞原因: `["toc_pages_unclassified", "link_endnote_not_all_matched", "contract_marker_gap", "contract_def_anchor_mismatch", "link_quality_low", "structure_review_required"]`
- translation_mode: `placeholder`
- translation_api_called: `False`
- current_stage: `report_write`

## 输入资产
- pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Germany_Madness/Bell - 2000 - A History of Madness in Sixteenth-Century Germa.pdf` size=`289324824` sha256=`bdb08eff20acab636f5075a9f6089cf8eaee65276e167e334966ac1c1715d0e0`
- raw_pages: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Germany_Madness/raw_pages.json` size=`14072242` sha256=`aa03f21ba43089e944e975ade2a2f41106ed00749502b0b9085095c28fb63c59`
- raw_pages.page_count: `464`
- raw_source_markdown: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Germany_Madness/raw_source_markdown.md` size=`1145062` sha256=`df65bc2dfce74089195c100ed3c6ad2692a908df724dc889aa08e0d6b6dc3170`
- raw_source_markdown.usage_note: `本轮只作为输入资产校验与报告证据，不回灌数据库。`
- raw_source_markdown.preview: `# Bell - 2000 - A History of Madness in Sixteenth-Century Germa.pdf ## PDF第1页 <div style="text-align: center;"><img src="imgs/img_in_image_box_0_83_1777_5037.jpg" alt="Image" width="40%" /></div> <div style="text-align:...`
- manual_toc_pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Germany_Madness/目录.pdf` size=`245869` sha256=`361b1a722efe7ddb7be2909748605c2b703871fb61277fcbe9a673da590c860e`

## 清理结果
- removed_count: `8`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.Germany_Madness.test.zip", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.test.zip", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `1965`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=2, prompt=6019, completion=2084, total=8103
- llm_repair.cluster_request: request=0, prompt=0, completion=0, total=0
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `8`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `1`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 8, "resolved_anchor_count": 8, "provisional_anchor_count": 0, "section_node_count": 123, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": [], "demoted_chapter_titles_preview": ["History of Madness in Sixteenth-Century Germany", "Psychoanalytic and Feminist Approaches: The Problem of Hysteria", "The Contribution of Michel Foucault", "the invidious labeling of disproportionately more men or more women.", "Madness as Cerebral Disorder", "people from a new angle.", "the hallmark of this new social science, one of whose earliest discoveries", "Madness and Culture"], "optimized_anchor_count": 8, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 1}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 0, "endnotes": 0, "chapter": 8, "section": 0, "post_body": 0, "back_matter": 2, "front_matter": 3}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.Germany_Madness.blocked.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.blocked.test.zip`

## LLM 交互摘要
- trace_count: `21`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/visual_toc.manual_input_extract.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.001.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.003.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.004.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.005.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.006.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.007.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.008.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.009.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.010.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.011.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.012.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.013.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.014.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.015.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.016.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.017.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.018.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.019.json`

## 模块过程取证
### 边界区分
- decision_basis: `["fnm_pages.page_role", "fnm_pages.role_reason", "fnm_pages.role_confidence", "fnm_pages.has_note_heading", "fnm_pages.section_hint"]`
- page_role_counts: `{"front_matter": 44, "body": 360, "note": 6, "other": 54}`
- first_body_page: `45`
- first_note_page: `129`
- page_role_samples: `[{"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 2, "target_pdf_page": 2, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 3, "target_pdf_page": 3, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 45, "target_pdf_page": 45, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 46, "target_pdf_page": 46, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 47, "target_pdf_page": 47, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 129, "target_pdf_page": 129, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 139, "target_pdf_page": 139, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 280, "target_pdf_page": 280, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 411, "target_pdf_page": 411, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 412, "target_pdf_page": 412, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 413, "target_pdf_page": 413, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}]`

### 尾注区确定
- decision_basis: `["fnm_note_regions.region_kind/start_page/end_page/pages", "fnm_note_regions.bound_chapter_id", "fnm_note_regions.region_start_first_source_marker", "fnm_note_regions.region_first_note_item_marker", "structure.chapter_binding_summary", "structure.visual_toc_endnotes_summary"]`
- visual_toc_endnotes_summary: `{}`
- chapter_binding_summary: `{"region_count": 47, "book_scope_region_count": 0, "unbound_region_count": 0, "unbound_region_ids_preview": [], "unassigned_item_count": 0, "unassigned_item_ids_preview": []}`
- endnote_region_rows: `[]`

### 尾注数组建立
- decision_basis: `["fnm_note_items.region_id/chapter_id/page_no/marker", "按 region_id 聚合生成注释数组", "检查 numeric marker 连续性与首尾 marker"]`
- note_capture_summary: `{"expected_anchor_count": 978, "captured_note_count": 816, "capture_ratio": 0.8344, "sparse_capture_chapter_ids": [], "dense_anchor_zero_capture_pages": [], "chapters": [{"chapter_id": "toc-ch-001-historicalproblemssinstv", "note_mode": "chapter_endnote_primary", "expected_anchor_count": 174, "captured_note_count": 0, "capture_ratio": 0.0}, {"chapter_id": "toc-ch-002-tworeformersandaworldgon", "note_mode": "footnote_primary", "expected_anchor_count": 135, "captured_note_count": 264, "capture_ratio": 1.9556}, {"chapter_id": "toc-ch-003-academicpsychiatryandthe", "note_mode": "footnote_primary", "expected_anchor_count": 147, "captured_note_count": 117, "capture_ratio": 0.7959}, {"chapter_id": "toc-ch-004-witchcraftandthemelancho", "note_mode": "footnote_primary", "expected_anchor_count": 172, "captured_note_count": 171, "capture_ratio": 0.9942}, {"chapter_id": "toc-ch-005-courtfoolsandtheirfollyi", "note_mode": "footnote_primary", "expected_anchor_count": 49, "captured_note_count": 76, "capture_ratio": 1.551}, {"chapter_id": "toc-ch-006-pilgrimsinsearchoftheirr", "note_mode": "chapter_endnote_primary", "expected_anchor_count": 55, "captured_note_count": 9, "capture_ratio": 0.1636}, {"chapter_id": "toc-ch-007-madnessashelplessnesstwo", "note_mode": "footnote_primary", "expected_anchor_count": 245, "captured_note_count": 178, "capture_ratio": 0.7265}, {"chapter_id": "toc-ch-008-epilogue", "note_mode": "footnote_primary", "expected_anchor_count": 1, "captured_note_count": 1, "capture_ratio": 1.0}]}`
- book_endnote_stream_summary: `{"chapter_count": 3, "chapters_with_endnote_stream": ["toc-ch-002-tworeformersandaworldgon", "toc-ch-005-courtfoolsandtheirfollyi", "toc-ch-006-pilgrimsinsearchoftheirr"], "high_concentration_chapter_ids": [], "chapters": [{"chapter_id": "toc-ch-002-tworeformersandaworldgon", "item_count": 8, "projection_mode_counts": {"native": 8}}, {"chapter_id": "toc-ch-005-courtfoolsandtheirfollyi", "item_count": 12, "projection_mode_counts": {"native": 12}}, {"chapter_id": "toc-ch-006-pilgrimsinsearchoftheirr", "item_count": 9, "projection_mode_counts": {"native": 9}}]}`
- endnote_array_rows: `[]`

### 尾注拼接
- decision_basis: `["fnm_translation_units.kind/owner_kind/section_id/target_ref", "导出 chapter markdown 中 local refs/local defs 的闭合情况", "structure.freeze_note_unit_summary"]`
- freeze_note_unit_summary: `{"chapter_view_note_unit_count": 1155, "owner_fallback_note_unit_count": 0, "unresolved_note_item_count": 0, "unresolved_note_item_ids_preview": []}`
- note_unit_rows: `[{"section_id": "toc-ch-001-historicalproblemssinstv", "section_title": "Historical Problems: Sin, St. Vitus, and the Devil", "note_unit_count": 159, "note_unit_kind_counts": {"footnote": 159}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [46, 98]}, {"section_id": "toc-ch-002-tworeformersandaworldgon", "section_title": "Two Reformers and a World Gone Mad: Luther and Paracelsus", "note_unit_count": 272, "note_unit_kind_counts": {"footnote": 264, "endnote": 8}, "target_ref_preview": ["{{NOTE_REF:fn-00161}}", "{{NOTE_REF:fn-00162}}", "{{NOTE_REF:fn-00163}}", "{{NOTE_REF:fn-00164}}", "{{NOTE_REF:fn-00165}}"], "page_span": [100, 158]}, {"section_id": "toc-ch-003-academicpsychiatryandthe", "section_title": "Academic “Psychiatry” and the Rise of Galenic Observation", "note_unit_count": 117, "note_unit_kind_counts": {"footnote": 117}, "target_ref_preview": ["{{NOTE_REF:fn-00425}}", "{{NOTE_REF:fn-00426}}", "{{NOTE_REF:fn-00427}}", "{{NOTE_REF:fn-00428}}", "{{NOTE_REF:fn-00429}}"], "page_span": [160, 200]}, {"section_id": "toc-ch-004-witchcraftandthemelancho", "section_title": "Witchcraft and the Melancholy Interpretation of the Insanity Defense", "note_unit_count": 171, "note_unit_kind_counts": {"footnote": 171}, "target_ref_preview": ["{{NOTE_REF:fn-00543}}", "{{NOTE_REF:fn-00544}}", "{{NOTE_REF:fn-00545}}", "{{NOTE_REF:fn-00546}}", "{{NOTE_REF:fn-00547}}"], "page_span": [202, 246]}, {"section_id": "toc-ch-005-courtfoolsandtheirfollyi", "section_title": "Court Fools and Their Folly: Image and Social Reality", "note_unit_count": 88, "note_unit_kind_counts": {"footnote": 76, "endnote": 12}, "target_ref_preview": ["{{NOTE_REF:fn-00714}}", "{{NOTE_REF:fn-00715}}", "{{NOTE_REF:fn-00716}}", "{{NOTE_REF:fn-00717}}", "{{NOTE_REF:fn-00718}}"], "page_span": [248, 296]}, {"section_id": "toc-ch-006-pilgrimsinsearchoftheirr", "section_title": "Pilgrims in Search of Their Reason", "note_unit_count": 169, "note_unit_kind_counts": {"footnote": 160, "endnote": 9}, "target_ref_preview": ["{{NOTE_REF:fn-00790}}", "{{NOTE_REF:fn-00792}}", "{{NOTE_REF:fn-00793}}", "{{NOTE_REF:fn-00794}}", "{{NOTE_REF:fn-00795}}"], "page_span": [297, 340]}, {"section_id": "toc-ch-007-madnessashelplessnesstwo", "section_title": "Madness as Helplessness: Two Hospitals in the Age of the Reformations", "note_unit_count": 178, "note_unit_kind_counts": {"footnote": 178}, "target_ref_preview": ["{{NOTE_REF:fn-00951}}", "{{NOTE_REF:fn-00952}}", "{{NOTE_REF:fn-00953}}", "{{NOTE_REF:fn-00954}}", "{{NOTE_REF:fn-00955}}"], "page_span": [343, 403]}, {"section_id": "toc-ch-008-epilogue", "section_title": "Epilogue", "note_unit_count": 1, "note_unit_kind_counts": {"footnote": 1}, "target_ref_preview": ["{{NOTE_REF:fn-01131}}"], "page_span": [406, 406]}]`
- export_merge_rows: `[]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{"matched": 887, "footnote_orphan_note": 0, "footnote_orphan_anchor": 11, "endnote_orphan_note": 261, "endnote_orphan_anchor": 1, "ambiguous": 0, "ignored": 20, "fallback_count": 39, "repair_count": 83, "fallback_matched_count": 32, "fallback_match_ratio": 0.036076662908680945}`
- link_resolver_counts: `{"repair": 83, "rule": 1051, "fallback": 39, "orphan_recovery": 7}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "toc-ch-001-historicalproblemssinstv", "page_no": 46, "paragraph_index": 1, "marker": "1", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "In 1475, or more likely 1477–78, the renowned Flemish painter Hugo van der Goes (1440?–1482) retreated from the world to become a converso,..."}, {"anchor_id": "anchor-00002", "chapter_id": "toc-ch-001-historicalproblemssinstv", "page_no": 46, "paragraph_index": 2, "marker": "2", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "As his brother Nicolaes [a donatus, or lay brother in the same monastery] told me at the time, our brother Hugo, during one night on his jou..."}, {"anchor_id": "anchor-00003", "chapter_id": "toc-ch-001-historicalproblemssinstv", "page_no": 47, "paragraph_index": 2, "marker": "3", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "Van der Goes may well have been experiencing a much more specific humiliation than what Ofhuys described in general terms. When Nuremberg hu..."}, {"anchor_id": "anchor-00004", "chapter_id": "toc-ch-001-historicalproblemssinstv", "page_no": 48, "paragraph_index": 0, "marker": "4", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "ted together with Ofhuys's firsthand report on Hugo's fears that he was damned. $ ^{4} $ We may not be far wrong in guessing that for Hugo a..."}, {"anchor_id": "anchor-00005", "chapter_id": "toc-ch-001-historicalproblemssinstv", "page_no": 48, "paragraph_index": 2, "marker": "5", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "There are many different opinions about the illness of this converso. Some said that it was a kind of frenesis magna; others asserted that h..."}, {"anchor_id": "anchor-01007", "chapter_id": "toc-ch-001-historicalproblemssinstv", "page_no": 48, "paragraph_index": 2, "marker": "6", "anchor_kind": "endnote", "certainty": 0.55, "source_text_preview": "There are many different opinions about the illness of this converso. Some said that it was a kind of frenesis magna; others asserted that h..."}, {"anchor_id": "anchor-00006", "chapter_id": "toc-ch-001-historicalproblemssinstv", "page_no": 49, "paragraph_index": 0, "marker": "7", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "count of his guests. $ ^{7} $ In the course of time, Ofhuys thought, van der Goes may in this way have laid the physical or natural basis fo..."}, {"anchor_id": "anchor-00007", "chapter_id": "toc-ch-001-historicalproblemssinstv", "page_no": 49, "paragraph_index": 1, "marker": "8", "anchor_kind": "endnote", "certainty": 1.0, "source_text_preview": "This detailed description has seemed so clear in its particulars, so clinically detached, so natural, that historians have stumbled over one..."}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-001-historicalproblemssinstv", "note_item_id": "fn-00001", "anchor_id": "anchor-00002", "status": "matched", "resolver": "repair", "marker": "2", "page_span": [46, 46]}, {"link_id": "link-00002", "chapter_id": "toc-ch-001-historicalproblemssinstv", "note_item_id": "fn-00002", "anchor_id": "anchor-00003", "status": "matched", "resolver": "repair", "marker": "3", "page_span": [47, 47]}, {"link_id": "link-00003", "chapter_id": "toc-ch-001-historicalproblemssinstv", "note_item_id": "fn-00003", "anchor_id": "anchor-00004", "status": "matched", "resolver": "rule", "marker": "4", "page_span": [48, 48]}, {"link_id": "link-00004", "chapter_id": "toc-ch-001-historicalproblemssinstv", "note_item_id": "fn-00004", "anchor_id": "anchor-00005", "status": "matched", "resolver": "repair", "marker": "5", "page_span": [48, 48]}, {"link_id": "link-00005", "chapter_id": "toc-ch-001-historicalproblemssinstv", "note_item_id": "fn-00005", "anchor_id": "anchor-01007", "status": "matched", "resolver": "rule", "marker": "6", "page_span": [48, 48]}, {"link_id": "link-00006", "chapter_id": "toc-ch-001-historicalproblemssinstv", "note_item_id": "fn-00006", "anchor_id": "anchor-00006", "status": "matched", "resolver": "rule", "marker": "7", "page_span": [49, 49]}, {"link_id": "link-00007", "chapter_id": "toc-ch-001-historicalproblemssinstv", "note_item_id": "fn-00007", "anchor_id": "anchor-00007", "status": "matched", "resolver": "rule", "marker": "8", "page_span": [49, 49]}, {"link_id": "link-00008", "chapter_id": "toc-ch-001-historicalproblemssinstv", "note_item_id": "fn-00008", "anchor_id": "anchor-00008", "status": "matched", "resolver": "rule", "marker": "9", "page_span": [49, 49]}]`

## 阻塞定位明细
- structure_verify / note_link_orphan_note: `原书 p.129 — Paracelsus: Sämtliche Werke nach der 10-bändigen Huserschen Gesamtausgabe (1589–...` | `Paracelsus: Sämtliche Werke nach der 10-bändigen Huserschen Gesamtausgabe (1589–91), zum erstenmal in neuzetliches Deutsch übersetzt, ed. an...`
- structure_verify / note_link_orphan_note: `原书 p.129 — Kurt Goldammer, Paracelsus: Natur und Offenbarung (Hannover, 1953); Heinrich Sch...` | `Kurt Goldammer, Paracelsus: Natur und Offenbarung (Hannover, 1953); Heinrich Schipperges, Paracelsus: Der Mensch in der Licht der Natur (Stu...`
- structure_verify / note_link_orphan_note: `原书 p.130 — See Charles Nauert, Agrippa and the Crisis of Renaissance Thought (Urbana, IIL.,...` | `See Charles Nauert, Agrippa and the Crisis of Renaissance Thought (Urbana, IIL., 1965); Hiram Hayden, The Counter Renaissance (New York, 195...`
- structure_verify / note_link_orphan_note: `原书 p.130 — See Kammerer, Das Leib-Seele-Geist-Problem bei Paracelsus. It is worth emphasizi...` | `See Kammerer, Das Leib-Seele-Geist-Problem bei Paracelsus. It is worth emphasizing that, for Paracelsus, the highest part of man was one’s G...`
- structure_verify / note_link_orphan_note: `原书 p.130 — SW, pt.` | `SW, pt.`
- structure_verify / note_link_orphan_note: `原书 p.130 — Astronomia magna,in SW, pt.` | `Astronomia magna,in SW, pt.`
- structure_verify / note_link_orphan_note: `原书 p.130 — SW. pt.` | `SW. pt.`
- structure_verify / note_link_orphan_note: `原书 p.131 — Walter Pagel’s magisterial study of Paracelsus seems to exaggerate the gnostic a...` | `Walter Pagel’s magisterial study of Paracelsus seems to exaggerate the gnostic and Neoplatonic desire of Paracelsus to transcend mere flesh...`
- structure_verify / note_link_orphan_note: `原书 p.131 — De causis morborum invisibilium, in SW, pt.` | `De causis morborum invisibilium, in SW, pt.`
- structure_verify / note_link_orphan_note: `原书 p.131 — Pagel, Paracelsus, pp. 208, 227.` | `Pagel, Paracelsus, pp. 208, 227.`
- structure_verify / note_link_orphan_note: `原书 p.131 — Astronomia magna, in SW, pt.` | `Astronomia magna, in SW, pt.`
- structure_verify / note_link_orphan_note: `原书 p.131 — Ibid., pp. 37—38.` | `Ibid., pp. 37—38.`
- structure_verify / note_link_orphan_note: `原书 p.132 — In fact, late in his short life, he came to question the value of alchemy as a r...` | `In fact, late in his short life, he came to question the value of alchemy as a road to`
- structure_verify / note_link_orphan_note: `原书 p.133 — Pagel, Paracelsus, pp. 105, 113.` | `Pagel, Paracelsus, pp. 105, 113.`
- structure_verify / note_link_orphan_note: `原书 p.133 — Astronomia magna,in SW, pt.` | `Astronomia magna,in SW, pt.`
- structure_verify / note_link_orphan_note: `原书 p.133 — Beider Arzneien referred to a term used at the University of Ferrara, modeled on...` | `Beider Arzneien referred to a term used at the University of Ferrara, modeled on the legal degree in canon and civil law, “utriusque juris.”`
- structure_verify / note_link_orphan_note: `原书 p.134 — Owsei Temkin, “The Elusiveness of Paracelsus,” Bulletin of the History of Medici...` | `Owsei Temkin, “The Elusiveness of Paracelsus,” Bulletin of the History of Medicine 26 (1952): 201-17; lago Galdston, “The Psychiatry of Para...`
- structure_verify / note_link_orphan_note: `原书 p.134 — Pagel, Paracelsus, pp. 150—52; Walter Pagel, Das medizinische Weltbild des Parac...` | `Pagel, Paracelsus, pp. 150—52; Walter Pagel, Das medizinische Weltbild des Paracelsus: Seine Zusammenhinge mit Neuplatonismus und Gnosis (Wi...`
- structure_verify / note_link_orphan_note: `原书 p.134 — Kammerer, Das Leib-Seele-Geist-Problem, p- 61; E. Ackerknecht, Kurze Geschichte...` | `Kammerer, Das Leib-Seele-Geist-Problem, p- 61; E. Ackerknecht, Kurze Geschichte der Psychiatrie (2d ed. Stuttgart, 1967), p. 26.`
- structure_verify / note_link_orphan_note: `原书 p.134 — Werner Leibbrand and Annemarie Wettley, Der Wahnsinn: Geschichte der abendlindis...` | `Werner Leibbrand and Annemarie Wettley, Der Wahnsinn: Geschichte der abendlindischen Psycopathologie (Freiburg im Breisgau, 1961), pp. 201-2...`
- structure_verify / note_link_orphan_note: `原书 p.134 — See Liber prologi in vitam beatam, in Theophrastus Paracelsus: Werke, ed. Peucke...` | `See Liber prologi in vitam beatam, in Theophrastus Paracelsus: Werke, ed. Peuckert, 4: 131-48, esp. pp. 141-44; and (MP) L2 (89), fol. 430a.`
- structure_verify / note_link_orphan_note: `原书 p.136 — Ibid., p. 65.` | `Ibid., p. 65.`
- structure_verify / note_link_orphan_note: `原书 p.136 — Ibid., p. 300.` | `Ibid., p. 300.`
- structure_verify / note_link_orphan_note: `原书 p.136 — Von den Krankheiten die der Vernunft berauben, in SW, pt.` | `Von den Krankheiten die der Vernunft berauben, in SW, pt.`
