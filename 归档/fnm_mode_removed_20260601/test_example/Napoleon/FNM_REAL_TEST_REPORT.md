# FNM Real Test Report — Napoleon

- doc_id: `5df1d3d7f9c1`
- 状态: `ready`
- 导出可用: `True`
- 阻塞原因: `[]`
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
- removed_count: `9`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces", "/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.Napoleon.test.zip", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `1719`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=0, prompt=0, completion=0, total=0
- llm_repair.cluster_request: request=1, prompt=1247, completion=67, total=1314
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
- slug zip: `/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.Napoleon.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `0`

## 模块过程取证
### 边界区分
- decision_basis: `["fnm_pages.page_role", "fnm_pages.role_reason", "fnm_pages.role_confidence", "fnm_pages.has_note_heading", "fnm_pages.section_hint"]`
- page_role_counts: `{"front_matter": 40, "body": 312, "other": 44}`
- first_body_page: `41`
- first_note_page: `None`
- page_role_samples: `[{"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 2, "target_pdf_page": 2, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 3, "target_pdf_page": 3, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 41, "target_pdf_page": 41, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 42, "target_pdf_page": 42, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 43, "target_pdf_page": 43, "page_role": "body", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 353, "target_pdf_page": 353, "page_role": "other", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 354, "target_pdf_page": 354, "page_role": "other", "role_reason": "bibliography", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}, {"page_no": 355, "target_pdf_page": 355, "page_role": "other", "role_reason": "bibliography", "role_confidence": 1.0, "has_note_heading": false, "section_hint": ""}]`

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
- note_unit_rows: `[{"section_id": "toc-ch-001-postambule", "section_title": "Postambule", "note_unit_count": 3, "note_unit_kind_counts": {"endnote": 3}, "target_ref_preview": ["{{NOTE_REF:fn-00413}}", "{{NOTE_REF:fn-00414}}", "{{NOTE_REF:fn-00415}}"], "page_span": [344, 347]}, {"section_id": "toc-ch-001-uneinventionutiledansleg", "section_title": "« Une invention utile dans le genre funeste »", "note_unit_count": 16, "note_unit_kind_counts": {"endnote": 16}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [41, 49]}, {"section_id": "toc-ch-002-unmédecinauchevetducorps", "section_title": "Un médecin au chevet du corps de l'État", "note_unit_count": 26, "note_unit_kind_counts": {"endnote": 26}, "target_ref_preview": ["{{NOTE_REF:fn-00017}}", "{{NOTE_REF:fn-00018}}", "{{NOTE_REF:fn-00019}}", "{{NOTE_REF:fn-00020}}", "{{NOTE_REF:fn-00021}}"], "page_span": [50, 74]}, {"section_id": "toc-ch-003-lesévènementsdelarévolut", "section_title": "Les « évènements de la Révolution »", "note_unit_count": 16, "note_unit_kind_counts": {"endnote": 16}, "target_ref_preview": ["{{NOTE_REF:fn-00043}}", "{{NOTE_REF:fn-00044}}", "{{NOTE_REF:fn-00045}}", "{{NOTE_REF:fn-00046}}", "{{NOTE_REF:fn-00047}}"], "page_span": [75, 86]}, {"section_id": "toc-ch-004-spectresdelaguillotine", "section_title": "Spectres de la guillotine", "note_unit_count": 23, "note_unit_kind_counts": {"endnote": 23}, "target_ref_preview": ["{{NOTE_REF:fn-00059}}", "{{NOTE_REF:fn-00060}}", "{{NOTE_REF:fn-00061}}", "{{NOTE_REF:fn-00062}}", "{{NOTE_REF:fn-00063}}"], "page_span": [87, 103]}, {"section_id": "toc-ch-005-maisonsdesantémaisonsdar", "section_title": "Maisons de santé, maisons d'arrêt", "note_unit_count": 23, "note_unit_kind_counts": {"endnote": 23}, "target_ref_preview": ["{{NOTE_REF:fn-00081}}", "{{NOTE_REF:fn-00082}}", "{{NOTE_REF:fn-00083}}", "{{NOTE_REF:fn-00084}}", "{{NOTE_REF:fn-00085}}"], "page_span": [106, 119]}, {"section_id": "toc-ch-006-dissidenceoudémence", "section_title": "Dissidence ou démence ?", "note_unit_count": 11, "note_unit_kind_counts": {"endnote": 11}, "target_ref_preview": ["{{NOTE_REF:fn-00104}}", "{{NOTE_REF:fn-00105}}", "{{NOTE_REF:fn-00106}}", "{{NOTE_REF:fn-00107}}", "{{NOTE_REF:fn-00108}}"], "page_span": [122, 136]}, {"section_id": "toc-ch-006-listedesillustration", "section_title": "Liste des illustrations", "note_unit_count": 12, "note_unit_kind_counts": {"endnote": 12}, "target_ref_preview": ["{{NOTE_REF:en-00001}}", "{{NOTE_REF:en-00002}}", "{{NOTE_REF:en-00003}}", "{{NOTE_REF:en-00004}}", "{{NOTE_REF:en-00005}}"], "page_span": [389, 389]}]`
- export_merge_rows: `[{"title": "« Une invention utile dans le genre funeste »", "path": "chapters/001-« Une invention utile dans le genre funeste ».md", "note_unit_count": 16, "local_ref_total": 14, "local_def_total": 14, "first_local_def_marker": "4", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Un médecin au chevet du corps de l'État", "path": "chapters/002-Un médecin au chevet du corps de l'État.md", "note_unit_count": 26, "local_ref_total": 26, "local_def_total": 25, "first_local_def_marker": "22", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Les « évènements de la Révolution »", "path": "chapters/003-Les « évènements de la Révolution ».md", "note_unit_count": 16, "local_ref_total": 14, "local_def_total": 14, "first_local_def_marker": "51", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Spectres de la guillotine", "path": "chapters/004-Spectres de la guillotine.md", "note_unit_count": 23, "local_ref_total": 21, "local_def_total": 19, "first_local_def_marker": "68", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Maisons de santé, maisons d'arrêt", "path": "chapters/005-Maisons de santé, maisons d'arrêt.md", "note_unit_count": 23, "local_ref_total": 22, "local_def_total": 21, "first_local_def_marker": "2", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Dissidence ou démence ?", "path": "chapters/006-Dissidence ou démence.md", "note_unit_count": 11, "local_ref_total": 10, "local_def_total": 10, "first_local_def_marker": "26", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "« Cet homme n'est pas aliéné » : Sade à Charenton", "path": "chapters/007-« Cet homme n'est pas aliéné » Sade à Charenton.md", "note_unit_count": 29, "local_ref_total": 28, "local_def_total": 26, "first_local_def_marker": "39", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "III. L'homme qui se prenait pour Napoléon", "path": "chapters/008-III L'homme qui se prenait pour Napoléon.md", "note_unit_count": 1, "local_ref_total": 2, "local_def_total": 1, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{}`
- link_resolver_counts: `{"rule": 470}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "", "page_no": 7, "paragraph_index": 0, "marker": "1", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00002", "chapter_id": "", "page_no": 8, "paragraph_index": 0, "marker": "2", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00003", "chapter_id": "", "page_no": 8, "paragraph_index": 0, "marker": "3", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00004", "chapter_id": "", "page_no": 10, "paragraph_index": 0, "marker": "7", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00005", "chapter_id": "", "page_no": 10, "paragraph_index": 0, "marker": "8", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00007", "chapter_id": "", "page_no": 14, "paragraph_index": 0, "marker": "11", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00008", "chapter_id": "", "page_no": 15, "paragraph_index": 0, "marker": "12", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00009", "chapter_id": "", "page_no": 16, "paragraph_index": 0, "marker": "13", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00001", "status": "orphan_anchor", "resolver": "rule", "marker": "1", "page_span": [7, 7]}, {"link_id": "link-00002", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00002", "status": "orphan_anchor", "resolver": "rule", "marker": "2", "page_span": [8, 8]}, {"link_id": "link-00003", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00003", "status": "orphan_anchor", "resolver": "rule", "marker": "3", "page_span": [8, 8]}, {"link_id": "link-00004", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00004", "status": "orphan_anchor", "resolver": "rule", "marker": "7", "page_span": [10, 10]}, {"link_id": "link-00005", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00005", "status": "orphan_anchor", "resolver": "rule", "marker": "8", "page_span": [10, 10]}, {"link_id": "link-00006", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00007", "status": "orphan_anchor", "resolver": "rule", "marker": "11", "page_span": [14, 14]}, {"link_id": "link-00007", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00008", "status": "orphan_anchor", "resolver": "rule", "marker": "12", "page_span": [15, 15]}, {"link_id": "link-00008", "chapter_id": "", "note_item_id": "", "anchor_id": "anchor-00009", "status": "orphan_anchor", "resolver": "rule", "marker": "13", "page_span": [16, 16]}]`

## 阻塞定位明细
