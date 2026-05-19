# FNM Real Test Report — Germany_Madness

- doc_id: `67356d1f7d9a`
- 状态: `ready`
- 导出可用: `True`
- 阻塞原因: `[]`
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
- removed_count: `9`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.Germany_Madness.test.zip", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `3011`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_modules.json`

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
- slug zip: `/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.Germany_Madness.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `0`

## 模块过程取证
### 边界区分
- decision_basis: `["fnm_pages.page_role", "fnm_pages.role_reason", "fnm_pages.role_confidence", "fnm_pages.has_note_heading", "fnm_pages.section_hint"]`
- page_role_counts: `{"front_matter": 44, "body": 363, "note": 3, "other": 54}`
- first_body_page: `45`
- first_note_page: `139`
- page_role_samples: `[{"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 2, "target_pdf_page": 2, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 3, "target_pdf_page": 3, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 45, "target_pdf_page": 45, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 46, "target_pdf_page": 46, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 47, "target_pdf_page": 47, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 139, "target_pdf_page": 139, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 280, "target_pdf_page": 280, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 281, "target_pdf_page": 281, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 411, "target_pdf_page": 411, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 412, "target_pdf_page": 412, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 413, "target_pdf_page": 413, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}]`

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
- note_unit_rows: `[{"section_id": "toc-ch-001-historicalproblemssinstv", "section_title": "Historical Problems: Sin, St. Vitus, and the Devil", "note_unit_count": 159, "note_unit_kind_counts": {"endnote": 159}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [46, 98]}, {"section_id": "toc-ch-002-tworeformersandaworldgon", "section_title": "Two Reformers and a World Gone Mad: Luther and Paracelsus", "note_unit_count": 264, "note_unit_kind_counts": {"endnote": 264}, "target_ref_preview": ["{{NOTE_REF:fn-00161}}", "{{NOTE_REF:fn-00162}}", "{{NOTE_REF:fn-00163}}", "{{NOTE_REF:fn-00164}}", "{{NOTE_REF:fn-00165}}"], "page_span": [100, 158]}, {"section_id": "toc-ch-003-academicpsychiatryandthe", "section_title": "Academic \"Psychiatry\" and the Rise of Galenic Observation", "note_unit_count": 118, "note_unit_kind_counts": {"endnote": 118}, "target_ref_preview": ["{{NOTE_REF:fn-00425}}", "{{NOTE_REF:fn-00426}}", "{{NOTE_REF:fn-00427}}", "{{NOTE_REF:fn-00428}}", "{{NOTE_REF:fn-00429}}"], "page_span": [160, 200]}, {"section_id": "toc-ch-004-witchcraftandthemelancho", "section_title": "Witchcraft and the Melancholy Interpretation of the Insanity Defense", "note_unit_count": 169, "note_unit_kind_counts": {"endnote": 169}, "target_ref_preview": ["{{NOTE_REF:fn-00543}}", "{{NOTE_REF:fn-00544}}", "{{NOTE_REF:fn-00545}}", "{{NOTE_REF:fn-00546}}", "{{NOTE_REF:fn-00547}}"], "page_span": [202, 246]}, {"section_id": "toc-ch-005-courtfoolsandtheirfollyi", "section_title": "Court Fools and Their Folly: Image and Social Reality", "note_unit_count": 76, "note_unit_kind_counts": {"endnote": 76}, "target_ref_preview": ["{{NOTE_REF:fn-00712}}", "{{NOTE_REF:fn-00713}}", "{{NOTE_REF:fn-00714}}", "{{NOTE_REF:fn-00715}}", "{{NOTE_REF:fn-00716}}"], "page_span": [248, 296]}, {"section_id": "toc-ch-006-pilgrimsinsearchoftheirr", "section_title": "Pilgrims in Search of Their Reason", "note_unit_count": 159, "note_unit_kind_counts": {"endnote": 159}, "target_ref_preview": ["{{NOTE_REF:fn-00788}}", "{{NOTE_REF:fn-00790}}", "{{NOTE_REF:fn-00791}}", "{{NOTE_REF:fn-00792}}", "{{NOTE_REF:fn-00793}}"], "page_span": [297, 340]}, {"section_id": "toc-ch-007-madnessashelplessnesstwo", "section_title": "Madness as Helplessness: Two Hospitals in the Age of the Reformations", "note_unit_count": 179, "note_unit_kind_counts": {"endnote": 179}, "target_ref_preview": ["{{NOTE_REF:fn-00948}}", "{{NOTE_REF:fn-00949}}", "{{NOTE_REF:fn-00950}}", "{{NOTE_REF:fn-00951}}", "{{NOTE_REF:fn-00952}}"], "page_span": [343, 403]}, {"section_id": "toc-ch-008-epilogue", "section_title": "Epilogue", "note_unit_count": 1, "note_unit_kind_counts": {"endnote": 1}, "target_ref_preview": ["{{NOTE_REF:fn-01128}}"], "page_span": [406, 406]}]`
- export_merge_rows: `[{"title": "Historical Problems: Sin, St. Vitus, and the Devil", "path": "chapters/001-Historical Problems Sin, St Vitus, and the Devil.md", "note_unit_count": 159, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Two Reformers and a World Gone Mad: Luther and Paracelsus", "path": "chapters/002-Two Reformers and a World Gone Mad Luther and Paracelsus.md", "note_unit_count": 264, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Academic \"Psychiatry\" and the Rise of Galenic Observation", "path": "chapters/003-Academic Psychiatry and the Rise of Galenic Observation.md", "note_unit_count": 118, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Witchcraft and the Melancholy Interpretation of the Insanity Defense", "path": "chapters/004-Witchcraft and the Melancholy Interpretation of the Insanity Defense.md", "note_unit_count": 169, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Court Fools and Their Folly: Image and Social Reality", "path": "chapters/005-Court Fools and Their Folly Image and Social Reality.md", "note_unit_count": 76, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Pilgrims in Search of Their Reason", "path": "chapters/006-Pilgrims in Search of Their Reason.md", "note_unit_count": 159, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Madness as Helplessness: Two Hospitals in the Age of the Reformations", "path": "chapters/007-Madness as Helplessness Two Hospitals in the Age of the Reformations.md", "note_unit_count": 179, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Epilogue", "path": "chapters/008-Epilogue.md", "note_unit_count": 1, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{}`
- link_resolver_counts: `{"rule": 1200}`
- anchor_samples: `[{"anchor_id": "anchor-00003", "chapter_id": "", "page_no": 21, "paragraph_index": 0, "marker": "1", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00005", "chapter_id": "", "page_no": 21, "paragraph_index": 0, "marker": "2", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00006", "chapter_id": "", "page_no": 21, "paragraph_index": 0, "marker": "3", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00007", "chapter_id": "", "page_no": 21, "paragraph_index": 0, "marker": "4", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00008", "chapter_id": "", "page_no": 23, "paragraph_index": 0, "marker": "5", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00009", "chapter_id": "", "page_no": 23, "paragraph_index": 0, "marker": "6", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00010", "chapter_id": "", "page_no": 23, "paragraph_index": 0, "marker": "7", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00011", "chapter_id": "", "page_no": 23, "paragraph_index": 0, "marker": "8", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00003", "status": "orphan_anchor", "resolver": "rule", "marker": "1", "page_span": [21, 21]}, {"link_id": "link-00002", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00005", "status": "orphan_anchor", "resolver": "rule", "marker": "2", "page_span": [21, 21]}, {"link_id": "link-00003", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00006", "status": "orphan_anchor", "resolver": "rule", "marker": "3", "page_span": [21, 21]}, {"link_id": "link-00004", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00007", "status": "orphan_anchor", "resolver": "rule", "marker": "4", "page_span": [21, 21]}, {"link_id": "link-00005", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00008", "status": "orphan_anchor", "resolver": "rule", "marker": "5", "page_span": [23, 23]}, {"link_id": "link-00006", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00009", "status": "orphan_anchor", "resolver": "rule", "marker": "6", "page_span": [23, 23]}, {"link_id": "link-00007", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00010", "status": "orphan_anchor", "resolver": "rule", "marker": "7", "page_span": [23, 23]}, {"link_id": "link-00008", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00011", "status": "orphan_anchor", "resolver": "rule", "marker": "8", "page_span": [23, 23]}]`

## 阻塞定位明细
