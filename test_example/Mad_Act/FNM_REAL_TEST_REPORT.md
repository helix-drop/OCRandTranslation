# FNM Real Test Report — Mad_Act

- doc_id: `bd05138cd773`
- 状态: `ready`
- 导出可用: `True`
- 阻塞原因: `[]`
- translation_mode: `placeholder`
- translation_api_called: `False`
- current_stage: `report_write`

## 输入资产
- pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Mad_Act/Mad_acts_mad_speech_and_mad_people_in_la.pdf` size=`11348163` sha256=`2a67a1ecfbfc57aa0e7affa5d28474d9fb39972be80afb18d255072f598358e1`
- raw_pages: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Mad_Act/raw_pages.json` size=`21456310` sha256=`ac187c3c859b7098b195531ad5f1c4304a151dbaf48d464f804018f24bd294cd`
- raw_pages.page_count: `824`
- raw_source_markdown: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Mad_Act/raw_source_markdown.md` size=`1559018` sha256=`889e5800d0d8a89c8516cca023af16ba52c6672c486eb3f81558257e9f3408d6`
- raw_source_markdown.usage_note: `本轮只作为输入资产校验与报告证据，不回灌数据库。`
- raw_source_markdown.preview: `# Mad_acts_mad_speech_and_mad_people_in_la.pdf ## PDF第1页 # MAD ACTS, MAD SPEECH, AND MAD PEOPLE IN LATE IMPERIAL CHINESE LAW AND MEDICINE Fabien Simonis A DISSERTATION PRESENTED TO THE FACULTY OF PRINCETON UNIVERSITY IN...`
- manual_toc_pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Mad_Act/目录.pdf` size=`71223` sha256=`54e8fe5fbc8bea8b98501f7c44d71e0fc027ea6fbda97b8b700a76ba57b72804`

## 清理结果
- removed_count: `9`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces", "/Users/hao/OCRandTranslation/test_example/Mad_Act/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Mad_Act/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Mad_Act/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/Mad_Act/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Mad_Act/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Mad_Act/latest.fnm.obsidian.Mad_Act.test.zip", "/Users/hao/OCRandTranslation/test_example/Mad_Act/latest.fnm.obsidian.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `2269`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Mad_Act/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=0, prompt=0, completion=0, total=0
- llm_repair.cluster_request: request=4, prompt=9119, completion=1493, total=10612
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
- slug zip: `/Users/hao/OCRandTranslation/test_example/Mad_Act/latest.fnm.obsidian.Mad_Act.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Mad_Act/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `0`

## 模块过程取证
### 边界区分
- decision_basis: `["fnm_pages.page_role", "fnm_pages.role_reason", "fnm_pages.role_confidence", "fnm_pages.has_note_heading", "fnm_pages.section_hint"]`
- page_role_counts: `{"front_matter": 138, "body": 549, "other": 133, "note": 4}`
- first_body_page: `91`
- first_note_page: `770`
- page_role_samples: `[{"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 2, "target_pdf_page": 2, "page_role": "front_matter", "role_reason": "copyright_front_matter", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 3, "target_pdf_page": 3, "page_role": "front_matter", "role_reason": "title_family", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 91, "target_pdf_page": 91, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 92, "target_pdf_page": 92, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 93, "target_pdf_page": 93, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 688, "target_pdf_page": 688, "page_role": "other", "role_reason": "bibliography", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 689, "target_pdf_page": 689, "page_role": "other", "role_reason": "bibliography_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 690, "target_pdf_page": 690, "page_role": "other", "role_reason": "bibliography_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 770, "target_pdf_page": 770, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 785, "target_pdf_page": 785, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 786, "target_pdf_page": 786, "page_role": "note", "role_reason": "note_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}]`

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
- note_unit_rows: `[{"section_id": "toc-ch-001-fromwindtomucusandfire", "section_title": "From Wind to mucus and Fire", "note_unit_count": 145, "note_unit_kind_counts": {"endnote": 145}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [93, 340]}, {"section_id": "toc-ch-002-ghostsormucus", "section_title": "Ghosts or mucus?", "note_unit_count": 135, "note_unit_kind_counts": {"endnote": 135}, "target_ref_preview": ["{{NOTE_REF:fn-00144}}", "{{NOTE_REF:fn-00145}}", "{{NOTE_REF:fn-00146}}", "{{NOTE_REF:fn-00147}}", "{{NOTE_REF:fn-00148}}"], "page_span": [345, 524]}, {"section_id": "toc-ch-003-lifetrials", "section_title": "13. Life trials", "note_unit_count": 39, "note_unit_kind_counts": {"endnote": 39}, "target_ref_preview": ["{{NOTE_REF:fn-00278}}", "{{NOTE_REF:fn-00279}}", "{{NOTE_REF:fn-00280}}", "{{NOTE_REF:llm-note-anchor-01404-8}}", "{{NOTE_REF:fn-00281}}"], "page_span": [529, 559]}, {"section_id": "toc-ch-004-distressandpower", "section_title": "14. Distress and power", "note_unit_count": 13, "note_unit_kind_counts": {"endnote": 13}, "target_ref_preview": ["{{NOTE_REF:fn-00314}}", "{{NOTE_REF:fn-00315}}", "{{NOTE_REF:llm-note-anchor-01491-5}}", "{{NOTE_REF:llm-note-anchor-01493-7}}", "{{NOTE_REF:llm-note-anchor-01494-8}}"], "page_span": [562, 584]}, {"section_id": "toc-ch-005-figuresandtables", "section_title": "Figures and tables", "note_unit_count": 82, "note_unit_kind_counts": {"endnote": 82}, "target_ref_preview": ["{{NOTE_REF:en-00001}}", "{{NOTE_REF:en-00002}}", "{{NOTE_REF:en-00003}}", "{{NOTE_REF:en-00004}}", "{{NOTE_REF:en-00005}}"], "page_span": [7, 9]}, {"section_id": "toc-ch-005-madmentalking", "section_title": "15. Madmen talking?", "note_unit_count": 36, "note_unit_kind_counts": {"endnote": 36}, "target_ref_preview": ["{{NOTE_REF:fn-00324}}", "{{NOTE_REF:fn-00325}}", "{{NOTE_REF:fn-00326}}", "{{NOTE_REF:llm-note-anchor-01567-7}}", "{{NOTE_REF:fn-00327}}"], "page_span": [592, 787]}]`
- export_merge_rows: `[{"title": "From Wind to mucus and Fire", "path": "chapters/006-From Wind to mucus and Fire.md", "note_unit_count": 145, "local_ref_total": 279, "local_def_total": 79, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": ["11", "12"]}, {"title": "Ghosts or mucus?", "path": "chapters/007-Ghosts or mucus.md", "note_unit_count": 135, "local_ref_total": 338, "local_def_total": 96, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": ["14", "15"]}, {"title": "13. Life trials", "path": "chapters/008-13 Life trials.md", "note_unit_count": 39, "local_ref_total": 46, "local_def_total": 34, "first_local_def_marker": "2", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": ["7", "8", "13"]}, {"title": "14. Distress and power", "path": "chapters/009-14 Distress and power.md", "note_unit_count": 13, "local_ref_total": 9, "local_def_total": 5, "first_local_def_marker": "2", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": ["4", "7", "8"]}, {"title": "15. Madmen talking?", "path": "chapters/010-15 Madmen talking.md", "note_unit_count": 36, "local_ref_total": 10, "local_def_total": 1, "first_local_def_marker": "318", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": ["287", "292", "299", "315", "316", "319"]}, {"title": "Bibliographies", "path": "chapters/001-Bibliographies.md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Contents", "path": "chapters/002-Contents.md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Contents (detailed)", "path": "chapters/003-Contents (detailed).md", "note_unit_count": 0, "local_ref_total": 0, "local_def_total": 0, "first_local_def_marker": "", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{}`
- link_resolver_counts: `{"rule": 1845, "repair": 3}`
- anchor_samples: `[{"anchor_id": "anchor-00011", "chapter_id": "toc-ch-005-figuresandtables", "page_no": 19, "paragraph_index": 0, "marker": "1", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00012", "chapter_id": "toc-ch-005-figuresandtables", "page_no": 19, "paragraph_index": 0, "marker": "2", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00013", "chapter_id": "toc-ch-005-figuresandtables", "page_no": 20, "paragraph_index": 0, "marker": "3", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00014", "chapter_id": "toc-ch-005-figuresandtables", "page_no": 21, "paragraph_index": 0, "marker": "4", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00015", "chapter_id": "toc-ch-005-figuresandtables", "page_no": 21, "paragraph_index": 0, "marker": "5", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00016", "chapter_id": "toc-ch-005-figuresandtables", "page_no": 22, "paragraph_index": 0, "marker": "6", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00017", "chapter_id": "toc-ch-005-figuresandtables", "page_no": 22, "paragraph_index": 0, "marker": "7", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00018", "chapter_id": "toc-ch-005-figuresandtables", "page_no": 23, "paragraph_index": 0, "marker": "8", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-005-figuresandtables", "note_item_id": "", "anchor_id": "anchor-00011", "status": "orphan_anchor", "resolver": "rule", "marker": "1", "page_span": [19, 19]}, {"link_id": "link-00002", "chapter_id": "toc-ch-005-figuresandtables", "note_item_id": "", "anchor_id": "anchor-00012", "status": "orphan_anchor", "resolver": "rule", "marker": "2", "page_span": [19, 19]}, {"link_id": "link-00003", "chapter_id": "toc-ch-005-figuresandtables", "note_item_id": "", "anchor_id": "anchor-00013", "status": "orphan_anchor", "resolver": "rule", "marker": "3", "page_span": [20, 20]}, {"link_id": "link-00004", "chapter_id": "toc-ch-005-figuresandtables", "note_item_id": "", "anchor_id": "anchor-00014", "status": "orphan_anchor", "resolver": "rule", "marker": "4", "page_span": [21, 21]}, {"link_id": "link-00005", "chapter_id": "toc-ch-005-figuresandtables", "note_item_id": "", "anchor_id": "anchor-00015", "status": "orphan_anchor", "resolver": "rule", "marker": "5", "page_span": [21, 21]}, {"link_id": "link-00006", "chapter_id": "toc-ch-005-figuresandtables", "note_item_id": "", "anchor_id": "anchor-00016", "status": "orphan_anchor", "resolver": "rule", "marker": "6", "page_span": [22, 22]}, {"link_id": "link-00007", "chapter_id": "toc-ch-005-figuresandtables", "note_item_id": "", "anchor_id": "anchor-00017", "status": "orphan_anchor", "resolver": "rule", "marker": "7", "page_span": [22, 22]}, {"link_id": "link-00008", "chapter_id": "toc-ch-005-figuresandtables", "note_item_id": "", "anchor_id": "anchor-00018", "status": "orphan_anchor", "resolver": "rule", "marker": "8", "page_span": [23, 23]}]`

## 阻塞定位明细
