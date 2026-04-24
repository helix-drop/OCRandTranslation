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
- removed_count: `8`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.Germany_Madness.test.zip", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.test.zip", "/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `2267`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=2, prompt=6019, completion=2085, total=8104
- llm_repair.cluster_request: request=6, prompt=90117, completion=3261, total=93378
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `7`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `1`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 8, "resolved_anchor_count": 8, "provisional_anchor_count": 0, "section_node_count": 123, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": [], "demoted_chapter_titles_preview": ["History of Madness in Sixteenth-Century Germany", "Psychoanalytic and Feminist Approaches: The Problem of Hysteria", "The Contribution of Michel Foucault", "the invidious labeling of disproportionately more men or more women.", "Madness as Cerebral Disorder", "people from a new angle.", "the hallmark of this new social science, one of whose earliest discoveries", "Madness and Culture"], "optimized_anchor_count": 7, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 1}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 0, "endnotes": 0, "chapter": 7, "section": 0, "post_body": 1, "back_matter": 2, "front_matter": 3}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.Germany_Madness.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Germany_Madness/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `8`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/visual_toc.manual_input_extract.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.001.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.003.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.004.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.005.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Germany_Madness/llm_traces/llm_repair.cluster_request.006.json`

## 阻塞定位明细
