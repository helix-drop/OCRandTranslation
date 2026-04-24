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
- removed_count: `8`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Napoleon/llm_traces", "/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.Napoleon.test.zip", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.test.zip", "/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `1098`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=3, prompt=4119, completion=4619, total=8738
- llm_repair.cluster_request: request=12, prompt=25858, completion=2594, total=28452
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
- slug zip: `/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.Napoleon.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Napoleon/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `15`
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

## 阻塞定位明细
