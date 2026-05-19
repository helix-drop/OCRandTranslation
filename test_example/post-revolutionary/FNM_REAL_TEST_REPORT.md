# FNM Real Test Report — Goldstein

- doc_id: `7ba9bca783fd`
- 状态: `ready`
- 导出可用: `True`
- 阻塞原因: `[]`
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
- removed_count: `9`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/post-revolutionary/llm_traces", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.Goldstein.test.zip", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `1782`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/post-revolutionary/fnm_real_test_modules.json`

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
- slug zip: `/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.Goldstein.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `0`

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
- note_unit_rows: `[{"section_id": "toc-ch-001-introductionpsychologica", "section_title": "Introduction: Psychological Interiority versus Self-Talk", "note_unit_count": 26, "note_unit_kind_counts": {"endnote": 26}, "target_ref_preview": ["{{NOTE_REF:en-00001}}", "{{NOTE_REF:en-00002}}", "{{NOTE_REF:en-00003}}", "{{NOTE_REF:en-00004}}", "{{NOTE_REF:en-00005}}"], "page_span": [348, 351]}, {"section_id": "toc-ch-002-theperilsofimaginationat", "section_title": "The Perils of Imagination at the End of the Old Regime", "note_unit_count": 86, "note_unit_kind_counts": {"endnote": 86}, "target_ref_preview": ["{{NOTE_REF:en-00027}}", "{{NOTE_REF:en-00028}}", "{{NOTE_REF:en-00029}}", "{{NOTE_REF:en-00030}}", "{{NOTE_REF:en-00031}}"], "page_span": [351, 359]}, {"section_id": "toc-ch-003-therevolutionaryschoolin", "section_title": "The Revolutionary Schooling of Imagination", "note_unit_count": 95, "note_unit_kind_counts": {"endnote": 95}, "target_ref_preview": ["{{NOTE_REF:en-00113}}", "{{NOTE_REF:en-00114}}", "{{NOTE_REF:en-00115}}", "{{NOTE_REF:en-00116}}", "{{NOTE_REF:en-00117}}"], "page_span": [359, 365]}, {"section_id": "toc-ch-004-isthereaselfinthismental", "section_title": "Is There a Self in This Mental Apparatus?", "note_unit_count": 108, "note_unit_kind_counts": {"endnote": 108}, "target_ref_preview": ["{{NOTE_REF:en-00208}}", "{{NOTE_REF:en-00209}}", "{{NOTE_REF:en-00210}}", "{{NOTE_REF:en-00211}}", "{{NOTE_REF:en-00212}}"], "page_span": [365, 373]}, {"section_id": "toc-ch-005-anaprioriselfforthebourg", "section_title": "An A Priori Self for the Bourgeois Male: Victor Cousin's Project", "note_unit_count": 142, "note_unit_kind_counts": {"endnote": 142}, "target_ref_preview": ["{{NOTE_REF:en-00316}}", "{{NOTE_REF:en-00317}}", "{{NOTE_REF:en-00318}}", "{{NOTE_REF:en-00319}}", "{{NOTE_REF:en-00320}}"], "page_span": [373, 382]}, {"section_id": "toc-ch-006-cousinianhegemony", "section_title": "Cousinian Hegemony", "note_unit_count": 169, "note_unit_kind_counts": {"endnote": 169}, "target_ref_preview": ["{{NOTE_REF:en-00458}}", "{{NOTE_REF:en-00459}}", "{{NOTE_REF:en-00460}}", "{{NOTE_REF:en-00461}}", "{{NOTE_REF:en-00462}}"], "page_span": [382, 393]}, {"section_id": "toc-ch-007-religiousandsecularacces", "section_title": "Religious and Secular Access to the Vie Intérieure: Renan at the Crossroads", "note_unit_count": 112, "note_unit_kind_counts": {"endnote": 112}, "target_ref_preview": ["{{NOTE_REF:en-00627}}", "{{NOTE_REF:en-00628}}", "{{NOTE_REF:en-00629}}", "{{NOTE_REF:en-00630}}", "{{NOTE_REF:en-00631}}"], "page_span": [393, 401]}, {"section_id": "toc-ch-008-apalpableselfforthesocia", "section_title": "A Palpable Self for the Socially Marginal: The Phrenological Alternative", "note_unit_count": 152, "note_unit_kind_counts": {"endnote": 152}, "target_ref_preview": ["{{NOTE_REF:en-00739}}", "{{NOTE_REF:en-00740}}", "{{NOTE_REF:en-00741}}", "{{NOTE_REF:en-00742}}", "{{NOTE_REF:en-00743}}"], "page_span": [401, 411]}]`
- export_merge_rows: `[{"title": "Introduction: Psychological Interiority versus Self-Talk", "path": "chapters/001-Introduction Psychological Interiority versus Self-Talk.md", "note_unit_count": 26, "local_ref_total": 28, "local_def_total": 26, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "The Perils of Imagination at the End of the Old Regime", "path": "chapters/002-The Perils of Imagination at the End of the Old Regime.md", "note_unit_count": 86, "local_ref_total": 100, "local_def_total": 85, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": ["7"]}, {"title": "The Revolutionary Schooling of Imagination", "path": "chapters/003-The Revolutionary Schooling of Imagination.md", "note_unit_count": 95, "local_ref_total": 111, "local_def_total": 94, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Is There a Self in This Mental Apparatus?", "path": "chapters/004-Is There a Self in This Mental Apparatus.md", "note_unit_count": 108, "local_ref_total": 114, "local_def_total": 108, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "An A Priori Self for the Bourgeois Male: Victor Cousin's Project", "path": "chapters/005-An A Priori Self for the Bourgeois Male Victor Cousin's Project.md", "note_unit_count": 142, "local_ref_total": 157, "local_def_total": 141, "first_local_def_marker": "1", "chapter_local_contract_ok": false, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Cousinian Hegemony", "path": "chapters/006-Cousinian Hegemony.md", "note_unit_count": 169, "local_ref_total": 198, "local_def_total": 169, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "Religious and Secular Access to the Vie Intérieure: Renan at the Crossroads", "path": "chapters/007-Religious and Secular Access to the Vie Intérieure Renan at the Crossroads.md", "note_unit_count": 112, "local_ref_total": 120, "local_def_total": 112, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}, {"title": "A Palpable Self for the Socially Marginal: The Phrenological Alternative", "path": "chapters/008-A Palpable Self for the Socially Marginal The Phrenological Alternative.md", "note_unit_count": 152, "local_ref_total": 200, "local_def_total": 152, "first_local_def_marker": "1", "chapter_local_contract_ok": true, "orphan_local_definitions": [], "orphan_local_refs": []}]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{}`
- link_resolver_counts: `{"rule": 902}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 0, "marker": "1", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00002", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 0, "marker": "2", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00003", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 0, "marker": "3", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00004", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 0, "marker": "4", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00005", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 0, "marker": "5", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00006", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 19, "paragraph_index": 0, "marker": "6", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00007", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 20, "paragraph_index": 0, "marker": "7", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}, {"anchor_id": "anchor-00008", "chapter_id": "toc-ch-001-introductionpsychologica", "page_no": 21, "paragraph_index": 0, "marker": "8", "anchor_kind": "unknown", "certainty": 1.0, "source_text_preview": ""}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "", "anchor_id": "anchor-00001", "status": "orphan_anchor", "resolver": "rule", "marker": "1", "page_span": [19, 19]}, {"link_id": "link-00002", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "", "anchor_id": "anchor-00002", "status": "orphan_anchor", "resolver": "rule", "marker": "2", "page_span": [19, 19]}, {"link_id": "link-00003", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "", "anchor_id": "anchor-00003", "status": "orphan_anchor", "resolver": "rule", "marker": "3", "page_span": [19, 19]}, {"link_id": "link-00004", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "", "anchor_id": "anchor-00004", "status": "orphan_anchor", "resolver": "rule", "marker": "4", "page_span": [19, 19]}, {"link_id": "link-00005", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "", "anchor_id": "anchor-00005", "status": "orphan_anchor", "resolver": "rule", "marker": "5", "page_span": [19, 19]}, {"link_id": "link-00006", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "", "anchor_id": "anchor-00006", "status": "orphan_anchor", "resolver": "rule", "marker": "6", "page_span": [19, 19]}, {"link_id": "link-00007", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "", "anchor_id": "anchor-00007", "status": "orphan_anchor", "resolver": "rule", "marker": "7", "page_span": [20, 20]}, {"link_id": "link-00008", "chapter_id": "toc-ch-001-introductionpsychologica", "note_item_id": "", "anchor_id": "anchor-00008", "status": "orphan_anchor", "resolver": "rule", "marker": "8", "page_span": [21, 21]}]`

## 阻塞定位明细
