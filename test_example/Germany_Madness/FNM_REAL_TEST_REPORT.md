# FNM Real Test Report — Germany_Madness

- doc_id: `67356d1f7d9a`
- 状态: `blocked`
- 导出可用: `False`
- 阻塞原因: `["link_endnote_not_all_matched", "link_orphan_note_remaining", "contract_def_anchor_mismatch", "freeze_matched_ref_not_injected", "merge_local_refs_unclosed", "export_audit_blocking", "structure_review_required"]`
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
- removed_count: `5`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/FNM_REAL_TEST_REPORT.md"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `0`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=2, prompt=17721, completion=1560, total=19281
- llm_repair.cluster_request: request=43, prompt=109708, completion=7334, total=117042
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `8`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `1`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 8, "resolved_anchor_count": 8, "provisional_anchor_count": 0, "section_node_count": 124, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": [], "demoted_chapter_titles_preview": ["History of Madness in Sixteenth-Century Germany", "Psychoanalytic and Feminist Approaches: The Problem of Hysteria", "The Contribution of Michel Foucault", "the invidious labeling of disproportionately more men or more women.", "Madness as Cerebral Disorder", "people from a new angle.", "the hallmark of this new social science, one of whose earliest discoveries", "Tables and Maps"], "optimized_anchor_count": 8, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 1}`

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
- trace_count: `88`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/visual_toc.manual_input_extract.002.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.001.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.001.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.002.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.003.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.003.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.004.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.004.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.005.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.005.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.006.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.006.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.007.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.007.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.008.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.008.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.009.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.009.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.010.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.010.json`
- llm_repair.cluster_request.started: 开始请求 LLM 修补 unresolved cluster -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.started.011.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.011.json`

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
- chapter_binding_summary: `{"region_count": 45, "book_scope_region_count": 0, "unbound_region_count": 0, "unbound_region_ids_preview": [], "unassigned_item_count": 0, "unassigned_item_ids_preview": []}`
- endnote_region_rows: `[]`

### 尾注数组建立
- decision_basis: `["fnm_note_items.region_id/chapter_id/page_no/marker", "按 region_id 聚合生成注释数组", "检查 numeric marker 连续性与首尾 marker"]`
- note_capture_summary: `{"expected_anchor_count": 880, "captured_note_count": 1123, "capture_ratio": 1.2761, "sparse_capture_chapter_ids": [], "dense_anchor_zero_capture_pages": [], "chapters": [{"chapter_id": "toc-ch-001-1historicalproblemssinst", "note_mode": "footnote_primary", "expected_anchor_count": 162, "captured_note_count": 159, "capture_ratio": 0.9815}, {"chapter_id": "toc-ch-002-2tworeformersandaworldgo", "note_mode": "footnote_primary", "expected_anchor_count": 132, "captured_note_count": 264, "capture_ratio": 2.0}, {"chapter_id": "toc-ch-003-3academicpsychiatryandth", "note_mode": "footnote_primary", "expected_anchor_count": 121, "captured_note_count": 117, "capture_ratio": 0.9669}, {"chapter_id": "toc-ch-004-4witchcraftandthemelanch", "note_mode": "footnote_primary", "expected_anchor_count": 167, "captured_note_count": 169, "capture_ratio": 1.012}, {"chapter_id": "toc-ch-005-5courtfoolsandtheirfolly", "note_mode": "footnote_primary", "expected_anchor_count": 87, "captured_note_count": 76, "capture_ratio": 0.8736}, {"chapter_id": "toc-ch-006-6pilgrimsinsearchoftheir", "note_mode": "footnote_primary", "expected_anchor_count": 48, "captured_note_count": 159, "capture_ratio": 3.3125}, {"chapter_id": "toc-ch-007-7madnessashelplessnesstw", "note_mode": "footnote_primary", "expected_anchor_count": 162, "captured_note_count": 178, "capture_ratio": 1.0988}, {"chapter_id": "toc-ch-008-epilogue", "note_mode": "footnote_primary", "expected_anchor_count": 1, "captured_note_count": 1, "capture_ratio": 1.0}]}`
- book_endnote_stream_summary: `{"chapter_count": 2, "chapters_with_endnote_stream": ["toc-ch-002-2tworeformersandaworldgo", "toc-ch-006-6pilgrimsinsearchoftheir"], "high_concentration_chapter_ids": [], "chapters": [{"chapter_id": "toc-ch-002-2tworeformersandaworldgo", "item_count": 2, "projection_mode_counts": {"native": 2}}, {"chapter_id": "toc-ch-006-6pilgrimsinsearchoftheir", "item_count": 9, "projection_mode_counts": {"native": 9}}]}`
- endnote_array_rows: `[]`

### 尾注拼接
- decision_basis: `["fnm_translation_units.kind/owner_kind/section_id/target_ref", "导出 chapter markdown 中 local refs/local defs 的闭合情况", "structure.freeze_note_unit_summary"]`
- freeze_note_unit_summary: `{"chapter_view_note_unit_count": 1137, "owner_fallback_note_unit_count": 0, "unresolved_note_item_count": 0, "unresolved_note_item_ids_preview": []}`
- note_unit_rows: `[{"section_id": "toc-ch-001-1historicalproblemssinst", "section_title": "1 Historical Problems: Sin, St. Vitus, and the Devil", "note_unit_count": 159, "note_unit_kind_counts": {"footnote": 159}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [46, 98]}, {"section_id": "toc-ch-002-2tworeformersandaworldgo", "section_title": "2 Two Reformers and a World Gone Mad: Luther and Paracelsus", "note_unit_count": 266, "note_unit_kind_counts": {"footnote": 264, "endnote": 2}, "target_ref_preview": ["{{NOTE_REF:fn-00161}}", "{{NOTE_REF:fn-00162}}", "{{NOTE_REF:fn-00163}}", "{{NOTE_REF:fn-00164}}", "{{NOTE_REF:fn-00165}}"], "page_span": [100, 158]}, {"section_id": "toc-ch-003-3academicpsychiatryandth", "section_title": "3 Academic \"Psychiatry\" and the Rise of Galenic Observation", "note_unit_count": 118, "note_unit_kind_counts": {"footnote": 118}, "target_ref_preview": ["{{NOTE_REF:fn-00425}}", "{{NOTE_REF:fn-00426}}", "{{NOTE_REF:fn-00427}}", "{{NOTE_REF:fn-00428}}", "{{NOTE_REF:fn-00429}}"], "page_span": [160, 200]}, {"section_id": "toc-ch-004-4witchcraftandthemelanch", "section_title": "4 Witchcraft and the Melancholy Interpretation of the Insanity Defense", "note_unit_count": 169, "note_unit_kind_counts": {"footnote": 169}, "target_ref_preview": ["{{NOTE_REF:fn-00543}}", "{{NOTE_REF:fn-00544}}", "{{NOTE_REF:fn-00545}}", "{{NOTE_REF:fn-00546}}", "{{NOTE_REF:fn-00547}}"], "page_span": [202, 246]}, {"section_id": "toc-ch-005-5courtfoolsandtheirfolly", "section_title": "5 Court Fools and Their Folly: Image and Social Reality", "note_unit_count": 76, "note_unit_kind_counts": {"footnote": 76}, "target_ref_preview": ["{{NOTE_REF:fn-00712}}", "{{NOTE_REF:fn-00713}}", "{{NOTE_REF:fn-00714}}", "{{NOTE_REF:fn-00715}}", "{{NOTE_REF:fn-00716}}"], "page_span": [248, 296]}, {"section_id": "toc-ch-006-6pilgrimsinsearchoftheir", "section_title": "6 Pilgrims in Search of Their Reason", "note_unit_count": 168, "note_unit_kind_counts": {"footnote": 159, "endnote": 9}, "target_ref_preview": ["{{NOTE_REF:fn-00788}}", "{{NOTE_REF:fn-00790}}", "{{NOTE_REF:fn-00791}}", "{{NOTE_REF:fn-00792}}", "{{NOTE_REF:fn-00793}}"], "page_span": [297, 340]}, {"section_id": "toc-ch-007-7madnessashelplessnesstw", "section_title": "7 Madness as Helplessness: Two Hospitals in the Age of the Reformations", "note_unit_count": 180, "note_unit_kind_counts": {"footnote": 180}, "target_ref_preview": ["{{NOTE_REF:fn-00948}}", "{{NOTE_REF:fn-00949}}", "{{NOTE_REF:fn-00950}}", "{{NOTE_REF:fn-00951}}", "{{NOTE_REF:fn-00952}}"], "page_span": [343, 403]}, {"section_id": "toc-ch-008-epilogue", "section_title": "Epilogue", "note_unit_count": 1, "note_unit_kind_counts": {"footnote": 1}, "target_ref_preview": ["{{NOTE_REF:fn-01128}}"], "page_span": [406, 406]}]`
- export_merge_rows: `[]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{"matched": 1077, "footnote_orphan_note": 0, "footnote_orphan_anchor": 0, "endnote_orphan_note": 6, "endnote_orphan_anchor": 0, "ambiguous": 54, "ignored": 1, "fallback_count": 396, "repair_count": 37, "fallback_matched_count": 396, "fallback_match_ratio": 0.36768802228412256}`
- link_resolver_counts: `{"rule": 727, "repair": 434, "orphan_recovery": 1}`
- anchor_samples: `[{"anchor_id": "llm-anchor-fn-00061", "chapter_id": "toc-ch-001-1historicalproblemssinst", "page_no": 45, "paragraph_index": 0, "marker": "61", "anchor_kind": "footnote", "certainty": 0.9, "source_text_preview": "Hugo van der Goes. A second basic problem is the possibility"}, {"anchor_id": "llm-anchor-fn-00062", "chapter_id": "toc-ch-001-1historicalproblemssinst", "page_no": 45, "paragraph_index": 0, "marker": "62", "anchor_kind": "footnote", "certainty": 0.9, "source_text_preview": "the dancing mania, we encounter strange diseases that do not fit"}, {"anchor_id": "llm-anchor-fn-00063", "chapter_id": "toc-ch-001-1historicalproblemssinst", "page_no": 45, "paragraph_index": 0, "marker": "63", "anchor_kind": "footnote", "certainty": 0.9, "source_text_preview": "the devil could obsess and possess a person, body and mind"}, {"anchor_id": "llm-anchor-fn-00065", "chapter_id": "toc-ch-001-1historicalproblemssinst", "page_no": 45, "paragraph_index": 0, "marker": "65", "anchor_kind": "footnote", "certainty": 0.9, "source_text_preview": "Here was a religious madness that was of purely"}, {"anchor_id": "llm-anchor-fn-00074", "chapter_id": "toc-ch-001-1historicalproblemssinst", "page_no": 45, "paragraph_index": 0, "marker": "74", "anchor_kind": "footnote", "certainty": 0.9, "source_text_preview": "the devil could obsess and possess a person, body and mind, mimicking the worst forms of madness"}, {"anchor_id": "llm-anchor-fn-00146", "chapter_id": "toc-ch-001-1historicalproblemssinst", "page_no": 45, "paragraph_index": 0, "marker": "145", "anchor_kind": "footnote", "certainty": 0.95, "source_text_preview": "the troubled late medieval painter Hugo van der Goes"}, {"anchor_id": "llm-anchor-fn-00147", "chapter_id": "toc-ch-001-1historicalproblemssinst", "page_no": 45, "paragraph_index": 0, "marker": "146", "anchor_kind": "footnote", "certainty": 0.9, "source_text_preview": "dancing mania, we encounter strange diseases"}, {"anchor_id": "llm-anchor-fn-00148", "chapter_id": "toc-ch-001-1historicalproblemssinst", "page_no": 45, "paragraph_index": 0, "marker": "147", "anchor_kind": "footnote", "certainty": 0.9, "source_text_preview": "tempting them to suicide. Here was a religious madness"}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-002-2tworeformersandaworldgo", "note_item_id": "en-00001", "anchor_id": "", "status": "orphan_note", "resolver": "rule", "marker": "136", "page_span": [129, 129]}, {"link_id": "link-00002", "chapter_id": "toc-ch-002-2tworeformersandaworldgo", "note_item_id": "en-00002", "anchor_id": "", "status": "orphan_note", "resolver": "rule", "marker": "137", "page_span": [129, 129]}, {"link_id": "link-00003", "chapter_id": "toc-ch-006-6pilgrimsinsearchoftheir", "note_item_id": "en-00003", "anchor_id": "llm-anchor-en-00003", "status": "matched", "resolver": "repair", "marker": "50", "page_span": [297, 297]}, {"link_id": "link-00004", "chapter_id": "toc-ch-006-6pilgrimsinsearchoftheir", "note_item_id": "en-00004", "anchor_id": "llm-anchor-en-00004", "status": "matched", "resolver": "repair", "marker": "51", "page_span": [297, 297]}, {"link_id": "link-00005", "chapter_id": "toc-ch-006-6pilgrimsinsearchoftheir", "note_item_id": "en-00005", "anchor_id": "llm-anchor-en-00005", "status": "matched", "resolver": "repair", "marker": "52", "page_span": [297, 297]}, {"link_id": "link-00006", "chapter_id": "toc-ch-006-6pilgrimsinsearchoftheir", "note_item_id": "en-00006", "anchor_id": "llm-anchor-en-00006", "status": "matched", "resolver": "repair", "marker": "53", "page_span": [297, 297]}, {"link_id": "link-00007", "chapter_id": "toc-ch-006-6pilgrimsinsearchoftheir", "note_item_id": "en-00007", "anchor_id": "", "status": "orphan_note", "resolver": "rule", "marker": "96", "page_span": [321, 321]}, {"link_id": "link-00008", "chapter_id": "toc-ch-006-6pilgrimsinsearchoftheir", "note_item_id": "en-00008", "anchor_id": "", "status": "orphan_note", "resolver": "rule", "marker": "97", "page_span": [321, 321]}]`

## 阻塞定位明细
- structure_verify / note_link_orphan_note: `原书 p.129 — Paracelsus: Sämtliche Werke nach der 10-bändigen Huserschen Gesamtausgabe (1589–...` | `Paracelsus: Sämtliche Werke nach der 10-bändigen Huserschen Gesamtausgabe (1589–91), zum erstenmal in neuzetliches Deutsch übersetzt, ed. an...`
- structure_verify / note_link_orphan_note: `原书 p.129 — Kurt Goldammer, Paracelsus: Natur und Offenbarung (Hannover, 1953); Heinrich Sch...` | `Kurt Goldammer, Paracelsus: Natur und Offenbarung (Hannover, 1953); Heinrich Schipperges, Paracelsus: Der Mensch in der Licht der Natur (Stu...`
- structure_verify / note_link_orphan_note: `原书 p.321 — Bauer, "Das älteste gedruckte Mirakelbüchlein von Altötting," p. 150, nos. 4, 6,...` | `Bauer, "Das älteste gedruckte Mirakelbüchlein von Altötting," p. 150, nos. 4, 6, 16, 24.`
- structure_verify / note_link_orphan_note: `原书 p.321 — Bauer, "Das Büchlein der Zuflucht zu Maria," p. 235, nos. 1, 2, 4b, 5, 6, 11, 24...` | `Bauer, "Das Büchlein der Zuflucht zu Maria," p. 235, nos. 1, 2, 4b, 5, 6, 11, 24, 40, 43, 48, 64, 65, 66, 75. of the twenty-five miracles li...`
- structure_verify / note_link_orphan_note: `原书 p.321 — Hans Strauss, Altötting.` | `Hans Strauss, Altötting.`
- structure_verify / note_link_orphan_note: `原书 p.321 — <div style="text-align: center;"><img src="imgs/img_in_image_box_742_1569_3662_5...` | `<div style="text-align: center;"><img src="imgs/img_in_image_box_742_1569_3662_5661.jpg" alt="Image" width="73%" /></div>`
- structure_verify / note_link_ambiguous: `原书 p.49 — Erwin Panofsky, Early Netherlandish Painting: Its Origins and Character (Cambrid...` | `Erwin Panofsky, Early Netherlandish Painting: Its Origins and Character (Cambridge, Mass., 1958), 1: 331.`
- structure_verify / note_link_ambiguous: `原书 p.49 — McCloy, Ofhuys Chronicle, pp. 31—32: “ ... aliquando ex cibis melancholicis aliq...` | `McCloy, Ofhuys Chronicle, pp. 31—32: “ ... aliquando ex cibis melancholicis aliquando ex potatione fortis vini exurentis et incinerantis hum...`
- structure_verify / note_link_orphan_note: `原书 p.53 — Richard Beitl, Worterbuch der deutschen Volkskunde (Stuttgart, 1955), p. 376.` | `Richard Beitl, Worterbuch der deutschen Volkskunde (Stuttgart, 1955), p. 376.`
- structure_verify / note_link_ambiguous: `原书 p.54 — Fragments des anciennes chroniques d"Alsace, ed. L. Dacheux, vol. 4 (Strasbourg,...` | `Fragments des anciennes chroniques d"Alsace, ed. L. Dacheux, vol. 4 (Strasbourg, 1901), p- 252, quoting from the so-called “Annals of Sebast...`
- structure_verify / note_link_ambiguous: `原书 p.55 — Martin, “Geschichte der Tanzkrankheit,” p. 119; L. Dacheux, ed., Les chroniques...` | `Martin, “Geschichte der Tanzkrankheit,” p. 119; L. Dacheux, ed., Les chroniques strasbourgeoises de Jacques Trausch et de Jean Wencker. Les...`
- structure_verify / note_link_ambiguous: `原书 p.55 — Archive municipale, Strasbourg, R3, fol. 72 recto; my thanks to Thomas and Kathy...` | `Archive municipale, Strasbourg, R3, fol. 72 recto; my thanks to Thomas and Kathy Brady for transcribing this entry.`
- structure_verify / note_link_ambiguous: `原书 p.56 — Ibid., p. 117, and appendices 1 and 2, pp. 122—24.` | `Ibid., p. 117, and appendices 1 and 2, pp. 122—24.`
- structure_verify / note_link_ambiguous: `原书 p.56 — Ibid., p. 121; Dacheux, ed., Les chroniques, p. 148.` | `Ibid., p. 121; Dacheux, ed., Les chroniques, p. 148.`
- structure_verify / note_link_ambiguous: `原书 p.56 — Beitl, Worterbuch der deutschen Volkskunde, p. 647; see Handwarterbuch des deuts...` | `Beitl, Worterbuch der deutschen Volkskunde, p. 647; see Handwarterbuch des deutschen Aberglaubens (Berlin and Leipzig, 1927—42, ed. E. Hoffm...`
- structure_verify / note_link_orphan_note: `原书 p.65 — J. F. C. Hecker, Die grossen Volkskrankheiten des Mittelalters: Historisch-patho...` | `J. F. C. Hecker, Die grossen Volkskrankheiten des Mittelalters: Historisch-pathologische Untersuchungen, ed. August Hirsch (Berlin, 1865), p...`
- structure_verify / note_link_ambiguous: `原书 p.65 — Rosen, Madness in Society, p. 202; Backman, Religious Dances, pp. 244-47.` | `Rosen, Madness in Society, p. 202; Backman, Religious Dances, pp. 244-47.`
- structure_verify / note_link_ambiguous: `原书 p.67 — Ibid., p. 165.` | `Ibid., p. 165.`
- structure_verify / note_link_ambiguous: `原书 p.67 — Rodney Needham, “Percussion and Transition,” Man 2 (1967): 606—14; Andrew Neher,...` | `Rodney Needham, “Percussion and Transition,” Man 2 (1967): 606—14; Andrew Neher, “A Physiological Explanation of Unusual Behavior in Ceremon...`
- structure_verify / note_link_ambiguous: `原书 p.67 — Marius Schneider, “Tarantella,” in Musik in Geschichte und Gegenwart, vol. 13 (K...` | `Marius Schneider, “Tarantella,” in Musik in Geschichte und Gegenwart, vol. 13 (Kassel, 1966), cols. 117-109.`
- structure_verify / note_link_orphan_note: `原书 p.69 — S. Kemp and K. Williams, “Demonic Possession and Mental Disorder in Medieval and...` | `S. Kemp and K. Williams, “Demonic Possession and Mental Disorder in Medieval and Early Modern Europe,” Psychological Medicine 17 (1987): 21-...`
- structure_verify / note_link_orphan_note: `原书 p.69 — For an unconvincing effort to assimilate demoniacs and witches to the history of...` | `For an unconvincing effort to assimilate demoniacs and witches to the history of hysteria, see G. S. Rousseau, “’A Strange Pathology”: Hyste...`
- structure_verify / note_link_orphan_note: `原书 p.70 — My account depends on Andreas Angelus, Wider Natur und Wunderbuch: Darin so wol...` | `My account depends on Andreas Angelus, Wider Natur und Wunderbuch: Darin so wol in gemein von Wunderwercken dess Himmels, Luffts, Wassers un...`
- structure_verify / note_link_orphan_note: `原书 p.71 — Ibid., p. 208: “Hetten sie auch gerne hinweg getragen, wenns nicht einer im Gelb...` | `Ibid., p. 208: “Hetten sie auch gerne hinweg getragen, wenns nicht einer im Gelben Kleide widerrahten. Doch hetten sie sie hart gedruckt, un...`
