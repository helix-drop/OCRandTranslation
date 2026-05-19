# FNM Real Test Report — Heidegger_en_France

- doc_id: `a5d9a08d6871`
- 状态: `ready`
- 导出可用: `True`
- 阻塞原因: `[]`
- translation_mode: `placeholder`
- translation_api_called: `False`
- current_stage: `report_write`

## 输入资产
- pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/Heidegger en France (Dominique Janicaud) (Z-Library).pdf` size=`33093250` sha256=`c4e1e9a45f3fc4a5aab01c313be2b89ed7d24e157f89c9d20d2600a76fbfc777`
- raw_pages: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/raw_pages.json` size=`15846901` sha256=`9522993e420f2d2afcae5ac301a8a3e4833e01101c97be1449208cb10dc1f631`
- raw_pages.page_count: `608`
- raw_source_markdown: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/raw_source_markdown.md` size=`1205993` sha256=`ff56a63e13b8fd61079a3f0c8594a9fc341384eefe45b8f590d9c07a9cd119fb`
- raw_source_markdown.usage_note: `本轮只作为输入资产校验与报告证据，不回灌数据库。`
- raw_source_markdown.preview: `# Heidegger en France (Dominique Janicaud) (Z-Library).pdf ## PDF第1页 \ ## PDF第2页 '. ## PDF第3页 HEIDEGGER EN FRANCE ## PDF第4页 Aristote aux Champs-Élysées. Promenade et libres essais, Encre marine, 2003. L'homme va-t-il dép...`
- manual_toc_pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/目录.pdf` size=`300363` sha256=`4f3c6bcc1194dae90f51963841064d191d103186576aa4bd1e6a2970ccf6e599`

## 清理结果
- removed_count: `9`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.Heidegger_en_France.test.zip", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `3549`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=0, prompt=0, completion=0, total=0
- llm_repair.cluster_request: request=2, prompt=2772, completion=522, total=3294
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
- slug zip: `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.Heidegger_en_France.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `0`

## 模块过程取证
### 边界区分
- decision_basis: `["fnm_pages.page_role", "fnm_pages.role_reason", "fnm_pages.role_confidence", "fnm_pages.has_note_heading", "fnm_pages.section_hint"]`
- page_role_counts: `{"front_matter": 6, "body": 536, "other": 66}`
- first_body_page: `7`
- first_note_page: `None`
- page_role_samples: `[{"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 2, "target_pdf_page": 2, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 3, "target_pdf_page": 3, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 7, "target_pdf_page": 7, "page_role": "body", "role_reason": "title_family", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 8, "target_pdf_page": 8, "page_role": "body", "role_reason": "front_matter_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 9, "target_pdf_page": 9, "page_role": "body", "role_reason": "front_matter_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 543, "target_pdf_page": 543, "page_role": "other", "role_reason": "bibliography", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 544, "target_pdf_page": 544, "page_role": "other", "role_reason": "bibliography_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 545, "target_pdf_page": 545, "page_role": "other", "role_reason": "bibliography_continuation", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}]`

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
- note_unit_rows: `[{"section_id": "toc-ch-001-bibliographie", "section_title": "Bibliographie", "note_unit_count": 10, "note_unit_kind_counts": {"endnote": 10}, "target_ref_preview": ["{{NOTE_REF:en-00001}}", "{{NOTE_REF:en-00002}}", "{{NOTE_REF:en-00003}}", "{{NOTE_REF:en-00004}}", "{{NOTE_REF:en-00005}}"], "page_span": [554, 555]}, {"section_id": "toc-ch-001-introduction", "section_title": "Introduction", "note_unit_count": 22, "note_unit_kind_counts": {"endnote": 22}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [7, 21]}, {"section_id": "toc-ch-002-premierspassagesdurhin", "section_title": "1. Premiers passages du Rhin", "note_unit_count": 100, "note_unit_kind_counts": {"endnote": 100}, "target_ref_preview": ["{{NOTE_REF:fn-00023}}", "{{NOTE_REF:fn-00024}}", "{{NOTE_REF:fn-00025}}", "{{NOTE_REF:fn-00026}}", "{{NOTE_REF:fn-00027}}"], "page_span": [25, 53]}, {"section_id": "toc-ch-003-labombesartre", "section_title": "2. La bombe Sartre", "note_unit_count": 70, "note_unit_kind_counts": {"endnote": 70}, "target_ref_preview": ["{{NOTE_REF:fn-00123}}", "{{NOTE_REF:fn-00124}}", "{{NOTE_REF:fn-00125}}", "{{NOTE_REF:fn-00126}}", "{{NOTE_REF:fn-00127}}"], "page_span": [55, 79]}, {"section_id": "toc-ch-004-lesfascinationsdelaprèsg", "section_title": "3. Les fascinations de l'après-guerre", "note_unit_count": 109, "note_unit_kind_counts": {"endnote": 109}, "target_ref_preview": ["{{NOTE_REF:fn-00193}}", "{{NOTE_REF:fn-00194}}", "{{NOTE_REF:fn-00195}}", "{{NOTE_REF:fn-00196}}", "{{NOTE_REF:fn-00197}}"], "page_span": [81, 111]}, {"section_id": "toc-ch-005-lhumanismedanslesturbule", "section_title": "4. L'humanisme dans les turbulences", "note_unit_count": 66, "note_unit_kind_counts": {"endnote": 66}, "target_ref_preview": ["{{NOTE_REF:fn-00302}}", "{{NOTE_REF:fn-00303}}", "{{NOTE_REF:fn-00304}}", "{{NOTE_REF:fn-00305}}", "{{NOTE_REF:fn-00306}}"], "page_span": [113, 134]}, {"section_id": "toc-ch-006-lembelliedesannées1950", "section_title": "5. L'embellie des années 1950", "note_unit_count": 179, "note_unit_kind_counts": {"endnote": 179}, "target_ref_preview": ["{{NOTE_REF:fn-00367}}", "{{NOTE_REF:fn-00368}}", "{{NOTE_REF:fn-00369}}", "{{NOTE_REF:fn-00370}}", "{{NOTE_REF:fn-00371}}"], "page_span": [136, 178]}, {"section_id": "toc-ch-007-polémiquesrenouveléesdép", "section_title": "6. Polémiques renouvelées, déplacements inédits", "note_unit_count": 10, "note_unit_kind_counts": {"endnote": 10}, "target_ref_preview": ["{{NOTE_REF:fn-00546}}", "{{NOTE_REF:fn-00547}}", "{{NOTE_REF:fn-00548}}", "{{NOTE_REF:fn-00549}}", "{{NOTE_REF:fn-00550}}"], "page_span": [185, 187]}]`
- export_merge_rows: `[{"title": "Introduction", "path": "chapters/002-Introduction.md", "note_unit_count": 22, "local_ref_total": 17, "local_def_total": 11, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "1. Premiers passages du Rhin", "path": "chapters/003-1 Premiers passages du Rhin.md", "note_unit_count": 100, "local_ref_total": 55, "local_def_total": 48, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "2. La bombe Sartre", "path": "chapters/004-2 La bombe Sartre.md", "note_unit_count": 70, "local_ref_total": 43, "local_def_total": 36, "first_local_def_marker": "2", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "3. Les fascinations de l'après-guerre", "path": "chapters/005-3 Les fascinations de l'après-guerre.md", "note_unit_count": 109, "local_ref_total": 29, "local_def_total": 25, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "4. L'humanisme dans les turbulences", "path": "chapters/006-4 L'humanisme dans les turbulences.md", "note_unit_count": 66, "local_ref_total": 39, "local_def_total": 29, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": ["33"]}, {"title": "5. L'embellie des années 1950", "path": "chapters/007-5 L'embellie des années 1950.md", "note_unit_count": 179, "local_ref_total": 105, "local_def_total": 77, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "6. Polémiques renouvelées, déplacements inédits", "path": "chapters/008-6 Polémiques renouvelées, déplacements inédits.md", "note_unit_count": 10, "local_ref_total": 3, "local_def_total": 3, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "1 Des documents encombrants: le retour de la politique", "path": "chapters/009-1 Des documents encombrants le retour de la politique.md", "note_unit_count": 133, "local_ref_total": 70, "local_def_total": 52, "first_local_def_marker": "11", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{}`
- link_resolver_counts: `{"rule": 798}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "toc-ch-001-introduction", "page_no": 7, "paragraph_index": 0, "marker": "1", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00002", "chapter_id": "toc-ch-001-introduction", "page_no": 13, "paragraph_index": 0, "marker": "11", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00003", "chapter_id": "toc-ch-001-introduction", "page_no": 14, "paragraph_index": 0, "marker": "2", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00004", "chapter_id": "toc-ch-001-introduction", "page_no": 14, "paragraph_index": 0, "marker": "3", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00005", "chapter_id": "toc-ch-001-introduction", "page_no": 14, "paragraph_index": 0, "marker": "4", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00006", "chapter_id": "toc-ch-001-introduction", "page_no": 15, "paragraph_index": 0, "marker": "15", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00007", "chapter_id": "toc-ch-001-introduction", "page_no": 15, "paragraph_index": 0, "marker": "16", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00008", "chapter_id": "toc-ch-001-introduction", "page_no": 18, "paragraph_index": 0, "marker": "18", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-001-introduction", "note_item_id": "", "anchor_id": "anchor-00001", "status": "orphan_anchor", "resolver": "rule", "marker": "1", "page_span": [7, 7]}, {"link_id": "link-00002", "chapter_id": "toc-ch-001-introduction", "note_item_id": "", "anchor_id": "anchor-00002", "status": "orphan_anchor", "resolver": "rule", "marker": "11", "page_span": [13, 13]}, {"link_id": "link-00003", "chapter_id": "toc-ch-001-introduction", "note_item_id": "", "anchor_id": "anchor-00003", "status": "orphan_anchor", "resolver": "rule", "marker": "2", "page_span": [14, 14]}, {"link_id": "link-00004", "chapter_id": "toc-ch-001-introduction", "note_item_id": "", "anchor_id": "anchor-00004", "status": "orphan_anchor", "resolver": "rule", "marker": "3", "page_span": [14, 14]}, {"link_id": "link-00005", "chapter_id": "toc-ch-001-introduction", "note_item_id": "", "anchor_id": "anchor-00005", "status": "orphan_anchor", "resolver": "rule", "marker": "4", "page_span": [14, 14]}, {"link_id": "link-00006", "chapter_id": "toc-ch-001-introduction", "note_item_id": "", "anchor_id": "anchor-00006", "status": "orphan_anchor", "resolver": "rule", "marker": "15", "page_span": [15, 15]}, {"link_id": "link-00007", "chapter_id": "toc-ch-001-introduction", "note_item_id": "", "anchor_id": "anchor-00007", "status": "orphan_anchor", "resolver": "rule", "marker": "16", "page_span": [15, 15]}, {"link_id": "link-00008", "chapter_id": "toc-ch-001-introduction", "note_item_id": "", "anchor_id": "anchor-00008", "status": "orphan_anchor", "resolver": "rule", "marker": "18", "page_span": [18, 18]}]`

## 阻塞定位明细
