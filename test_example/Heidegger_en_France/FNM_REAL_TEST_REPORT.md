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
- removed_count: `8`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.Heidegger_en_France.test.zip", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.test.zip", "/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `2737`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=4, prompt=3864, completion=6193, total=10057
- llm_repair.cluster_request: request=3, prompt=11262, completion=1784, total=13046
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
- slug zip: `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.Heidegger_en_France.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `7`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/visual_toc.manual_input_extract.002.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/visual_toc.manual_input_extract.003.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/visual_toc.manual_input_extract.004.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/llm_repair.cluster_request.001.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/llm_repair.cluster_request.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Heidegger_en_France/llm_traces/llm_repair.cluster_request.003.json`

## 阻塞定位明细
