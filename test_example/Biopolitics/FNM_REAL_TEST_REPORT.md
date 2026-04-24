# FNM Real Test Report — Biopolitics

- doc_id: `0d285c0800db`
- 状态: `ready`
- 导出可用: `True`
- 阻塞原因: `[]`
- translation_mode: `placeholder`
- translation_api_called: `False`
- current_stage: `report_write`

## 输入资产
- pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/Foucault和Foucault - 2004 - Naissance de la biopolitique.pdf` size=`23254145` sha256=`59617ad735f29120f416ab9f6c3ec396c2a96616895710bd15ba994cd87f440b`
- raw_pages: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/raw_pages.json` size=`8471423` sha256=`3ddbd8d1ea8566e4b98534f14ee9d2b150d3773fd7470f3f29a7fce61bb5e658`
- raw_pages.page_count: `370`
- raw_source_markdown: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/raw_source_markdown.md` size=`1035819` sha256=`86c0cab29fb050ee4806ccb3359dac15e9efbb976ddb136f6f44b794d33e01ec`
- raw_source_markdown.usage_note: `本轮只作为输入资产校验与报告证据，不回灌数据库。`
- raw_source_markdown.preview: `# Foucault和Foucault - 2004 - Naissance de la biopolitique.pdf ## PDF第1页 ## MICHEL FOUCAULT NAISSANCE DE LA BIOPOLITIQUE Cours au Collège de France. 1978-1979 HAUTES ÉTUDES <div style="text-align: center;"><img src="imgs/...`
- manual_toc_pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/Bioplitics目录.pdf` size=`6981680` sha256=`47d65ce2923c8a5bb29b08f46c4fec9fbc8127623508cad91f9ff84ebe2de9de`

## 清理结果
- removed_count: `8`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.Biopolitics.test.zip", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.test.zip", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `750`

## Token by Stage
- visual_toc.preflight: request=1, prompt=127, completion=24, total=151
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=6, prompt=10296, completion=3094, total=13390
- llm_repair.cluster_request: request=9, prompt=52896, completion=8886, total=61782
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `0`
- residual_provisional_count: `0`
- expanded_window_hit_count: `0`
- composite_heading_count: `14`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 14, "resolved_anchor_count": 14, "provisional_anchor_count": 0, "section_node_count": 9, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": [], "demoted_chapter_titles_preview": ["MICHEL FOUCAULT", "Naissance de la biopolitique", "FRANÇOIS EWALD et ALESSANDRO FONTANA", "des physiocrates, de d’Argenson, d’Adam Smith, de Bentham, des utili-", "le marché, ou plutôt la concurrence pure, qui est l’essence même du", "cation, une discipline", "Indices", "liberté"], "optimized_anchor_count": 0, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 14}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 2, "endnotes": 0, "chapter": 12, "section": 0, "post_body": 2, "back_matter": 2, "front_matter": 1}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.Biopolitics.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `16`
- visual_toc.preflight: 确认当前视觉模型是否可用 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.preflight.001.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.002.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.003.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.004.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.005.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/visual_toc.manual_input_extract.006.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.001.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.003.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.004.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.005.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.006.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.007.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.008.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.009.json`

## 阻塞定位明细
