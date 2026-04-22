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
- removed_count: `8`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/post-revolutionary/llm_traces", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.Goldstein.test.zip", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.test.zip", "/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `859`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=2, prompt=2969, completion=2443, total=5412
- llm_repair.cluster_request: request=1, prompt=7549, completion=592, total=8141
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `2`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `143`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 9, "resolved_anchor_count": 9, "provisional_anchor_count": 0, "section_node_count": 177, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": ["Epilogue"], "demoted_chapter_titles_preview": ["to the", "Imagination in Socioeconomic Discourse (1): The Trade Corporation", "The Worker's Imagination Further Scrutinized", "tices and", "Imagination in Socioeconomic Discourse (2): Credit", "Self-Contained Persons: The Odd Trio", "anxiety for which the discourse on imagination typically served as", "restraints."], "optimized_anchor_count": 2, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 143}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 2, "endnotes": 0, "chapter": 8, "section": 0, "post_body": 1, "back_matter": 3, "front_matter": 2}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.Goldstein.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/post-revolutionary/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `3`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/post-revolutionary/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/post-revolutionary/llm_traces/visual_toc.manual_input_extract.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/post-revolutionary/llm_traces/llm_repair.cluster_request.001.json`

## 阻塞定位明细
