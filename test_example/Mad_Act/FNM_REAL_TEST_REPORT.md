# FNM Real Test Report — Mad_Act

- doc_id: `bd05138cd773`
- 状态: `ready`
- 导出可用: `True`
- 阻塞原因: `[]`
- translation_mode: `placeholder`
- translation_api_called: `False`
- current_stage: `report_write`

## 输入资产
- pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Mad_Act/Mad_acts_mad_speech_and_mad_people_in_la.pdf` size=`11348163` sha256=`2a67a1ecfbfc57aa0e7affa5d28474d9fb39972be80afb18d255072f598358e1`
- raw_pages: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Mad_Act/raw_pages.json` size=`21456310` sha256=`ac187c3c859b7098b195531ad5f1c4304a151dbaf48d464f804018f24bd294cd`
- raw_pages.page_count: `824`
- raw_source_markdown: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Mad_Act/raw_source_markdown.md` size=`1559018` sha256=`889e5800d0d8a89c8516cca023af16ba52c6672c486eb3f81558257e9f3408d6`
- raw_source_markdown.usage_note: `本轮只作为输入资产校验与报告证据，不回灌数据库。`
- raw_source_markdown.preview: `# Mad_acts_mad_speech_and_mad_people_in_la.pdf ## PDF第1页 # MAD ACTS, MAD SPEECH, AND MAD PEOPLE IN LATE IMPERIAL CHINESE LAW AND MEDICINE Fabien Simonis A DISSERTATION PRESENTED TO THE FACULTY OF PRINCETON UNIVERSITY IN...`
- manual_toc_pdf: exists=`True` path=`/Users/hao/OCRandTranslation/test_example/Mad_Act/目录.pdf` size=`71223` sha256=`54e8fe5fbc8bea8b98501f7c44d71e0fc027ea6fbda97b8b700a76ba57b72804`

## 清理结果
- removed_count: `6`
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces", "/Users/hao/OCRandTranslation/test_example/Mad_Act/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Mad_Act/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Mad_Act/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Mad_Act/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Mad_Act/latest.fnm.obsidian.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `2269`

## Token by Stage
- visual_toc.preflight: request=0, prompt=0, completion=0, total=0
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=3, prompt=7744, completion=3835, total=11579
- llm_repair.cluster_request: request=16, prompt=187332, completion=15114, total=202446
- translation_test: request=0, prompt=0, completion=0, total=0

## Heading Graph
- optimized_anchor_count: `14`
- residual_provisional_count: `0`
- expanded_window_hit_count: `1`
- composite_heading_count: `50`
- residual_provisional_titles_preview: `[]`
- `{"toc_body_item_count": 17, "resolved_anchor_count": 17, "provisional_anchor_count": 0, "section_node_count": 263, "unresolved_titles_preview": [], "boundary_conflict_titles_preview": [], "promoted_section_titles_preview": ["From Wind to mucus and Fire", "Ghosts or mucus?", "13. Life trials", "14. Distress and power", "16. Madness multiple", "Psycho-behavioral pathology in Chinese medicine"], "demoted_chapter_titles_preview": ["MAD ACTS, MAD SPEECH, AND MAD PEOPLE IN LATE IMPERIAL CHINESE LAW AND MEDICINE", "Abstract", "Acknowledgments", "Mad acts, mad words, and mad people in Chinese medicine and law", "1.1 Historiography: insights and oversights", "1.2 Michel Foucault and madness", "@B?4E354\u0001D85=\u0007\u0001 9;5\u0001!5CC>5B\u0005\u0001C851<C?@<1354 =?B5\u00015=@81C9C\u0001?>\u00013<1CC96931D9?>\u00011>4 4?3DB9>5", "1.3 Substances and their referents: “what is madness?” and what is “madness”?"], "optimized_anchor_count": 14, "residual_provisional_count": 0, "residual_provisional_titles_preview": [], "expanded_window_hit_count": 1, "composite_heading_count": 50}`

## Endnotes Summary
- present: `False`
- container_title: ``
- container_printed_page: ``
- container_visual_order: ``
- has_chapter_keyed_subentries_in_toc: `False`
- subentry_pattern: ``

## TOC Role Summary
- `{"container": 4, "endnotes": 0, "chapter": 22, "section": 6, "post_body": 1, "back_matter": 2, "front_matter": 6}`

## Export
- slug zip: `/Users/hao/OCRandTranslation/test_example/Mad_Act/latest.fnm.obsidian.Mad_Act.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Mad_Act/latest.fnm.obsidian.test.zip`

## LLM 交互摘要
- trace_count: `19`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/visual_toc.manual_input_extract.001.json`
- visual_toc.manual_input_extract: 从目录页截图中抽取单页原子目录项 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/visual_toc.manual_input_extract.002.json`
- visual_toc.manual_input_extract: 根据整份目录页重建目录树，并识别尾注容器与子项 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/visual_toc.manual_input_extract.003.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.001.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.002.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.003.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.004.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.005.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.006.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.007.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.008.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.009.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.010.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.011.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.012.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.013.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.014.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.015.json`
- llm_repair.cluster_request: 根据 unresolved cluster 请求 LLM 给出注释链接修补建议 -> `/Users/hao/OCRandTranslation/test_example/Mad_Act/llm_traces/llm_repair.cluster_request.016.json`

## 阻塞定位明细
