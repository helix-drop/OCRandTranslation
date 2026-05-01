# FNM Real Test Report — Heidegger_en_France

- doc_id: `a5d9a08d6871`
- 状态: `blocked`
- 导出可用: `False`
- 阻塞原因: `["contract_marker_gap", "contract_def_anchor_mismatch", "link_quality_low", "structure_review_required"]`
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
- removed_count: `8`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.Heidegger_en_France.test.zip", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.test.zip", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `2732`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/fnm_real_test_modules.json`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=4, prompt=3864, completion=6632, total=10496
- llm_repair.cluster_request: request=0, prompt=0, completion=0, total=0
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `3`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `180`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 16, "resolved_anchor_count": 16, "provisional_anchor_count": 0, "section_node_count": 128, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": ["5. L'embellie des années 1950", "1 Des documents encombrants: le retour de la politique"], "demoted_chapter_titles_preview": ["HEIDEGGER EN FRANCE", "JANICAUD", "étrangères", "de ce genre de tâche. Non pour étouffer l'es­", "RENCONTRES, ÉTUDES ET TRADUCTIONS PIONNIÈRES", "Heidegger1", "LA CLÉ DE VOUTE : LA CONSCIENCE DE LA LIBERTÉ", "se retrouve"], "optimized_anchor_count": 3, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 180}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 0, "endnotes": 0, "chapter": 18, "section": 69, "post_body": 0, "back_matter": 5, "front_matter": 0}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.Heidegger_en_France.blocked.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.blocked.test.zip`

## LLM 交互摘要
- trace_count: `7`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/visual_toc.manual_input_extract.002.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/visual_toc.manual_input_extract.003.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/visual_toc.manual_input_extract.004.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/llm_repair.cluster_request.001.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/llm_repair.cluster_request.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/llm_repair.cluster_request.003.json`

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
- chapter_binding_summary: `{"region_count": 24, "book_scope_region_count": 0, "unbound_region_count": 0, "unbound_region_ids_preview": [], "unassigned_item_count": 0, "unassigned_item_ids_preview": []}`
- endnote_region_rows: `[]`

### 尾注数组建立
- decision_basis: `["fnm_note_items.region_id/chapter_id/page_no/marker", "按 region_id 聚合生成注释数组", "检查 numeric marker 连续性与首尾 marker"]`
- note_capture_summary: `{"expected_anchor_count": 797, "captured_note_count": 1657, "capture_ratio": 2.079, "sparse_capture_chapter_ids": [], "dense_anchor_zero_capture_pages": [], "chapters": [{"chapter_id": "toc-ch-001-introduction", "note_mode": "footnote_primary", "expected_anchor_count": 11, "captured_note_count": 22, "capture_ratio": 2.0}, {"chapter_id": "toc-ch-002-premierspassagesdurhin", "note_mode": "footnote_primary", "expected_anchor_count": 54, "captured_note_count": 100, "capture_ratio": 1.8519}, {"chapter_id": "toc-ch-003-labombesartre", "note_mode": "footnote_primary", "expected_anchor_count": 25, "captured_note_count": 70, "capture_ratio": 2.8}, {"chapter_id": "toc-ch-004-lesfascinationsdelaprèsg", "note_mode": "footnote_primary", "expected_anchor_count": 28, "captured_note_count": 109, "capture_ratio": 3.8929}, {"chapter_id": "toc-ch-005-lhumanismedanslesturbule", "note_mode": "footnote_primary", "expected_anchor_count": 30, "captured_note_count": 65, "capture_ratio": 2.1667}, {"chapter_id": "toc-ch-006-lembelliedesannées1950", "note_mode": "footnote_primary", "expected_anchor_count": 91, "captured_note_count": 179, "capture_ratio": 1.967}, {"chapter_id": "toc-ch-007-polémiquesrenouveléesdép", "note_mode": "footnote_primary", "expected_anchor_count": 2, "captured_note_count": 10, "capture_ratio": 5.0}, {"chapter_id": "toc-ch-008-1desdocumentsencombrants", "note_mode": "footnote_primary", "expected_anchor_count": 63, "captured_note_count": 133, "capture_ratio": 2.1111}, {"chapter_id": "toc-ch-009-epilogueii", "note_mode": "book_endnote_bound", "expected_anchor_count": 0, "captured_note_count": 0, "capture_ratio": 1.0}, {"chapter_id": "toc-ch-010-disséminationourecomposi", "note_mode": "footnote_primary", "expected_anchor_count": 65, "captured_note_count": 131, "capture_ratio": 2.0154}, {"chapter_id": "toc-ch-011-mortettransfiguration", "note_mode": "footnote_primary", "expected_anchor_count": 73, "captured_note_count": 142, "capture_ratio": 1.9452}, {"chapter_id": "toc-ch-012-lalettreetlesprit", "note_mode": "footnote_primary", "expected_anchor_count": 51, "captured_note_count": 102, "capture_ratio": 2.0}, {"chapter_id": "toc-ch-013-leretourdurefoulé", "note_mode": "footnote_primary", "expected_anchor_count": 54, "captured_note_count": 126, "capture_ratio": 2.3333}, {"chapter_id": "toc-ch-014-entreéruditionettechnosc", "note_mode": "footnote_primary", "expected_anchor_count": 89, "captured_note_count": 174, "capture_ratio": 1.9551}, {"chapter_id": "toc-ch-015-lacroiséedeschemins", "note_mode": "footnote_primary", "expected_anchor_count": 107, "captured_note_count": 185, "capture_ratio": 1.729}, {"chapter_id": "toc-ch-016-conclusion", "note_mode": "footnote_primary", "expected_anchor_count": 54, "captured_note_count": 109, "capture_ratio": 2.0185}]}`
- book_endnote_stream_summary: `{"chapter_count": 0, "chapters_with_endnote_stream": [], "high_concentration_chapter_ids": [], "chapters": []}`
- endnote_array_rows: `[]`

### 尾注拼接
- decision_basis: `["fnm_translation_units.kind/owner_kind/section_id/target_ref", "导出 chapter markdown 中 local refs/local defs 的闭合情况", "structure.freeze_note_unit_summary"]`
- freeze_note_unit_summary: `{"chapter_view_note_unit_count": 1657, "owner_fallback_note_unit_count": 0, "unresolved_note_item_count": 0, "unresolved_note_item_ids_preview": []}`
- note_unit_rows: `[{"section_id": "toc-ch-001-introduction", "section_title": "Introduction", "note_unit_count": 22, "note_unit_kind_counts": {"footnote": 22}, "target_ref_preview": ["{{NOTE_REF:fn-00001}}", "{{NOTE_REF:fn-00002}}", "{{NOTE_REF:fn-00003}}", "{{NOTE_REF:fn-00004}}", "{{NOTE_REF:fn-00005}}"], "page_span": [7, 21]}, {"section_id": "toc-ch-002-premierspassagesdurhin", "section_title": "1. Premiers passages du Rhin", "note_unit_count": 100, "note_unit_kind_counts": {"footnote": 100}, "target_ref_preview": ["{{NOTE_REF:fn-00023}}", "{{NOTE_REF:fn-00024}}", "{{NOTE_REF:fn-00025}}", "{{NOTE_REF:fn-00026}}", "{{NOTE_REF:fn-00027}}"], "page_span": [25, 53]}, {"section_id": "toc-ch-003-labombesartre", "section_title": "2. La bombe Sartre", "note_unit_count": 70, "note_unit_kind_counts": {"footnote": 70}, "target_ref_preview": ["{{NOTE_REF:fn-00123}}", "{{NOTE_REF:fn-00124}}", "{{NOTE_REF:fn-00125}}", "{{NOTE_REF:fn-00126}}", "{{NOTE_REF:fn-00127}}"], "page_span": [55, 79]}, {"section_id": "toc-ch-004-lesfascinationsdelaprèsg", "section_title": "3. Les fascinations de l'après-guerre", "note_unit_count": 109, "note_unit_kind_counts": {"footnote": 109}, "target_ref_preview": ["{{NOTE_REF:fn-00193}}", "{{NOTE_REF:fn-00194}}", "{{NOTE_REF:fn-00195}}", "{{NOTE_REF:fn-00196}}", "{{NOTE_REF:fn-00197}}"], "page_span": [81, 111]}, {"section_id": "toc-ch-005-lhumanismedanslesturbule", "section_title": "4. L'humanisme dans les turbulences", "note_unit_count": 65, "note_unit_kind_counts": {"footnote": 65}, "target_ref_preview": ["{{NOTE_REF:fn-00302}}", "{{NOTE_REF:fn-00303}}", "{{NOTE_REF:fn-00304}}", "{{NOTE_REF:fn-00305}}", "{{NOTE_REF:fn-00306}}"], "page_span": [113, 134]}, {"section_id": "toc-ch-006-lembelliedesannées1950", "section_title": "5. L'embellie des années 1950", "note_unit_count": 179, "note_unit_kind_counts": {"footnote": 179}, "target_ref_preview": ["{{NOTE_REF:fn-00367}}", "{{NOTE_REF:fn-00368}}", "{{NOTE_REF:fn-00369}}", "{{NOTE_REF:fn-00370}}", "{{NOTE_REF:fn-00371}}"], "page_span": [136, 178]}, {"section_id": "toc-ch-007-polémiquesrenouveléesdép", "section_title": "6. Polémiques renouvelées, déplacements inédits", "note_unit_count": 10, "note_unit_kind_counts": {"footnote": 10}, "target_ref_preview": ["{{NOTE_REF:fn-00546}}", "{{NOTE_REF:fn-00547}}", "{{NOTE_REF:fn-00548}}", "{{NOTE_REF:fn-00549}}", "{{NOTE_REF:fn-00550}}"], "page_span": [185, 187]}, {"section_id": "toc-ch-008-1desdocumentsencombrants", "section_title": "1 Des documents encombrants: le retour de la politique", "note_unit_count": 133, "note_unit_kind_counts": {"footnote": 133}, "target_ref_preview": ["{{NOTE_REF:fn-00556}}", "{{NOTE_REF:fn-00557}}", "{{NOTE_REF:fn-00558}}", "{{NOTE_REF:fn-00559}}", "{{NOTE_REF:fn-00560}}"], "page_span": [188, 223]}]`
- export_merge_rows: `[]`

### 锚点寻找与链接
- decision_basis: `["fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker", "fnm_note_links.status/resolver/confidence", "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）"]`
- link_summary: `{"matched": 1657, "footnote_orphan_note": 0, "footnote_orphan_anchor": 1, "endnote_orphan_note": 0, "endnote_orphan_anchor": 0, "ambiguous": 0, "ignored": 11, "fallback_count": 1040, "repair_count": 146, "fallback_matched_count": 1040, "fallback_match_ratio": 0.627640313820157}`
- link_resolver_counts: `{"rule": 483, "fallback": 1040, "repair": 146}`
- anchor_samples: `[{"anchor_id": "anchor-00001", "chapter_id": "toc-ch-001-introduction", "page_no": 7, "paragraph_index": 1, "marker": "1", "anchor_kind": "footnote", "certainty": 1.0, "source_text_preview": "Il était une fois un enfant pauvre de Souabe — né dans un petit bourg à l'est de la Forêt-Noire. Par la seule force de sa pensée et l'acharn..."}, {"anchor_id": "synthetic-footnote-00001", "chapter_id": "toc-ch-001-introduction", "page_no": 8, "paragraph_index": 999, "marker": "2", "anchor_kind": "footnote", "certainty": 0.4, "source_text_preview": "Karl LŒWITH, «Les implications politiques de la philosophie de l'existence chez Heidegger>>, Les Temps modernes, novembre 1946/p. 343."}, {"anchor_id": "synthetic-footnote-00002", "chapter_id": "toc-ch-001-introduction", "page_no": 8, "paragraph_index": 999, "marker": "3", "anchor_kind": "footnote", "certainty": 0.4, "source_text_preview": "C'est d'ailleurs cette expression qu'un pamphlétaire communiste a utilisée comme titre ironique pour brocarder la vogue française de Heidegg..."}, {"anchor_id": "synthetic-footnote-00003", "chapter_id": "toc-ch-001-introduction", "page_no": 8, "paragraph_index": 999, "marker": "4", "anchor_kind": "footnote", "certainty": 0.4, "source_text_preview": "Frankfurter Allgemeine Zeitung, 19 mai 1999, p. 49: <<Die Trivialisierung des Martin Heidegger. Schund, Sex und Sühne: Di~ neuen Abenteuer d..."}, {"anchor_id": "synthetic-footnote-00004", "chapter_id": "toc-ch-001-introduction", "page_no": 8, "paragraph_index": 999, "marker": "5", "anchor_kind": "footnote", "certainty": 0.4, "source_text_preview": "ll serait «un Heidegger en quelque sorte aci::Iimaté et assimilé, métamorphosé, qni aurait trouvé en France une dimension inconnue de sa pro..."}, {"anchor_id": "synthetic-footnote-00005", "chapter_id": "toc-ch-001-introduction", "page_no": 9, "paragraph_index": 999, "marker": "6", "anchor_kind": "footnote", "certainty": 0.4, "source_text_preview": "Theodor W. ADoRNO, ]argon der Eigentlichkeit, Francfort, Suhrkamp, 1964; Jargon de l'authenticité, trad. É. Escoubas, Paris, Payot, 1989."}, {"anchor_id": "synthetic-footnote-00006", "chapter_id": "toc-ch-001-introduction", "page_no": 9, "paragraph_index": 999, "marker": "7", "anchor_kind": "footnote", "certainty": 0.4, "source_text_preview": "Voir, par exemple, Hans-Georg GADAMER, Philosophische Lehrjahre, Francfort, Klostermann, 1995, pp. 175-176."}, {"anchor_id": "synthetic-footnote-00007", "chapter_id": "toc-ch-001-introduction", "page_no": 9, "paragraph_index": 999, "marker": "8", "anchor_kind": "footnote", "certainty": 0.4, "source_text_preview": "<<Un tel travail présenterait saos conteste un intérêt certain» (François FÉDIER, <<Heidegger vu de France», Regarder voir, Paris, Les Belle..."}]`
- link_samples: `[{"link_id": "link-00001", "chapter_id": "toc-ch-001-introduction", "note_item_id": "fn-00001", "anchor_id": "anchor-00001", "status": "matched", "resolver": "rule", "marker": "1", "page_span": [7, 7]}, {"link_id": "link-00002", "chapter_id": "toc-ch-001-introduction", "note_item_id": "fn-00002", "anchor_id": "synthetic-footnote-00001", "status": "matched", "resolver": "fallback", "marker": "2", "page_span": [8, 8]}, {"link_id": "link-00003", "chapter_id": "toc-ch-001-introduction", "note_item_id": "fn-00003", "anchor_id": "synthetic-footnote-00002", "status": "matched", "resolver": "fallback", "marker": "3", "page_span": [8, 8]}, {"link_id": "link-00004", "chapter_id": "toc-ch-001-introduction", "note_item_id": "fn-00004", "anchor_id": "synthetic-footnote-00003", "status": "matched", "resolver": "fallback", "marker": "4", "page_span": [8, 8]}, {"link_id": "link-00005", "chapter_id": "toc-ch-001-introduction", "note_item_id": "fn-00005", "anchor_id": "synthetic-footnote-00004", "status": "matched", "resolver": "fallback", "marker": "5", "page_span": [8, 8]}, {"link_id": "link-00006", "chapter_id": "toc-ch-001-introduction", "note_item_id": "fn-00006", "anchor_id": "synthetic-footnote-00005", "status": "matched", "resolver": "fallback", "marker": "6", "page_span": [9, 9]}, {"link_id": "link-00007", "chapter_id": "toc-ch-001-introduction", "note_item_id": "fn-00007", "anchor_id": "synthetic-footnote-00006", "status": "matched", "resolver": "fallback", "marker": "7", "page_span": [9, 9]}, {"link_id": "link-00008", "chapter_id": "toc-ch-001-introduction", "note_item_id": "fn-00008", "anchor_id": "synthetic-footnote-00007", "status": "matched", "resolver": "fallback", "marker": "8", "page_span": [9, 9]}]`

## 阻塞定位明细
- structure_verify / note_link_orphan_anchor: `原书 p.436 ¶0 — rejets un forme emphatique qui leur ôte une grande partie de leur intérêt $ ^{67...` | `rejets un forme emphatique qui leur ôte une grande partie de leur intérêt $ ^{67} $, Citant une confidence de Queneau à Michel Leiris («Il n...`
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- structure_verify / chapter_issue: `` | ``
- export_verify / structure_review_required: `` | `["contract_marker_gap", "contract_def_anchor_mismatch", "link_quality_low"]`
