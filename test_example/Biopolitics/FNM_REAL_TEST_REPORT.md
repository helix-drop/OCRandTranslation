# FNM Real Test Report — Biopolitics

- doc_id: `0d285c0800db`
- 状态: `blocked`
- 导出可用: `False`
- 阻塞原因: `["toc_pages_unclassified", "contract_marker_gap", "contract_def_anchor_mismatch"]`
- translation_mode: `placeholder`
- translation_api_called: `False`
- current_stage: `structure_verify`

## 输入资产
- pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/Foucault和Foucault - 2004 - Naissance de la biopolitique.pdf` size=`23254145` sha256=`59617ad735f29120f416ab9f6c3ec396c2a96616895710bd15ba994cd87f440b`
- raw_pages: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/raw_pages.json` size=`8521865` sha256=`21f0e008c9942580bfb1dff1d603786d6916ecc41912b9f043605f782c8461a7`
- raw_pages.page_count: `370`
- raw_source_markdown: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/raw_source_markdown.md` size=`1038263` sha256=`d41aa823918142fe09408bdc00c08310cbb0d13112bbd03c34cb9ad6c7e6ab83`
- raw_source_markdown.usage_note: `本轮只作为输入资产校验与报告证据，不回灌数据库。`
- raw_source_markdown.preview: `# Foucault和Foucault - 2004 - Naissance de la biopolitique.pdf ## PDF第1页 ## MICHEL FOUCAULT NAISSANCE DE LA BIOPOLITIQUE Cours au Collège de France. 1978-1979 HAUTES ÉTUDES <div style="text-align: center;"><img src="imgs/...`
- manual_toc_pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Biopolitics/Bioplitics目录.pdf` size=`6981680` sha256=`47d65ce2923c8a5bb29b08f46c4fec9fbc8127623508cad91f9ff84ebe2de9de`

## 清理结果
- removed_count: `8`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_modules.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.Biopolitics.blocked.test.zip", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.blocked.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `0`

## 模块过程取证文件
- path: `/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_modules.json`

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
- composite_heading_count: `15`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 14, "resolved_anchor_count": 14, "provisional_anchor_count": 0, "section_node_count": 9, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": [], "demoted_chapter_titles_preview": ["MICHEL FOUCAULT", "Naissance de la biopolitique", "FRANÇOIS EWALD et ALESSANDRO FONTANA", "des physiocrates, de d’Argenson, d’Adam Smith, de Bentham, des utili-", "le marché, ou plutôt la concurrence pure, qui est l’essence même du", "cation, une discipline", "Indices", "liberté"], "optimized_anchor_count": 0, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 0, "composite_heading_count": 15}`

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
- slug zip: ``
- alias zip: ``

## LLM 交互摘要
- trace_count: `29`
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
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.010.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.011.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.012.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.013.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.014.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.015.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.016.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces/llm_repair.cluster_request.017.json`

## 阻塞定位明细
