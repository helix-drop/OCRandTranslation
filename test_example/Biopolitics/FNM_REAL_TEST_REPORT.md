# FNM Real Test Report — Biopolitics

- doc_id: `0d285c0800db`
- 状态: `blocked`
- 导出可用: `False`
- 阻塞原因: `["link_first_marker_not_one", "export_audit_blocking", "structure_review_required"]`
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
- removed_preview: `["/Users/hao/OCRandTranslation/test_example/Biopolitics/llm_traces", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_progress.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/fnm_real_test_result.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/FNM_REAL_TEST_REPORT.md", "/Users/hao/OCRandTranslation/test_example/Biopolitics/auto_visual_toc.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest_export_status.json", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.Biopolitics.blocked.test.zip", "/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.blocked.test.zip"]`

## 占位翻译
- translation_mode: `placeholder`
- translation_api_called: `False`
- translated_paras: `755`

## Token by Stage
- visual_toc.preflight: request=1, prompt=127, completion=24, total=151
- visual_toc.classify_candidates: request=0, prompt=0, completion=0, total=0
- visual_toc.extract_page_items: request=0, prompt=0, completion=0, total=0
- visual_toc.manual_input_extract: request=6, prompt=10302, completion=3094, total=13396
- llm_repair.cluster_request: request=9, prompt=52576, completion=3499, total=56075
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
- slug zip: `/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.Biopolitics.blocked.test.zip`
- alias zip: `/Users/hao/OCRandTranslation/test_example/Biopolitics/latest.fnm.obsidian.blocked.test.zip`

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
- structure_verify / note_link_orphan_note: `原书 p.343 — 600-1800. Théorie du droit public et science de la police, de M. Stolleis (Paris...` | `600-1800. Théorie du droit public et science de la police, de M. Stolleis (Paris, PUF, 1998).`
- structure_verify / note_link_orphan_note: `原书 p.347 — La bibliographie française sur le sujet étant extrêmement réduite, hormis la thè...` | `La bibliographie française sur le sujet étant extrêmement réduite, hormis la thèse de F. Bilger (La Pensée économique libérale de l'Allemagn...`
- structure_verify / note_link_orphan_anchor: `原书 p.19 ¶0 — grille d'intelligibilité obligatoire pour un certain nombre de pratiques concrèt...` | `grille d'intelligibilité obligatoire pour un certain nombre de pratiques concrètes, je voudrais partir de ces pratiques concrètes et passer...`
- structure_verify / note_link_orphan_anchor: `原书 p.19 ¶1 — L'an dernier, vous vous souvenez, j'avais essayé de faire l'étude de l'un de ces...` | `L'an dernier, vous vous souvenez, j'avais essayé de faire l'étude de l'un de ces épisodes importants, je crois, dans l'histoire du gouvernem...`
- structure_verify / note_link_orphan_anchor: `原书 p.24 ¶1 — Vous avez aussi la théorie du droit naturel et des droits naturels que l'on fait...` | `Vous avez aussi la théorie du droit naturel et des droits naturels que l'on fait valoir comme droits imprescriptibles et qu'aucun souverain,...`
- structure_verify / note_link_orphan_anchor: `原书 p.28 ¶0 — le peuvent pas, autrement dit, entre les choses à faire et les moyens à employer...` | `le peuvent pas, autrement dit, entre les choses à faire et les moyens à employer pour les faire d'une part, et les choses à ne pas faire. Le...`
- structure_verify / note_link_orphan_anchor: `原书 p.29 ¶0 — XVII<sup>e</sup> et au XVII<sup>e</sup> siècle quand il disait : si le souverain...` | `XVII<sup>e</sup> et au XVII<sup>e</sup> siècle quand il disait : si le souverain franchit cette loi, alors il doit être puni par une sanctio...`
- structure_verify / note_link_orphan_anchor: `原书 p.30 ¶1 — Deuxièmement, l'économie politique ne se propose pas du tout comme une objection...` | `Deuxièmement, l'économie politique ne se propose pas du tout comme une objection externe à la raison d'État et à son autonomie politique pui...`
- structure_verify / note_link_orphan_anchor: `原书 p.36 ¶3 — Eh bien, ce moment dont j'ai essayé d'indiquer le principal composant, c'est don...` | `Eh bien, ce moment dont j'ai essayé d'indiquer le principal composant, c'est donc ce moment qui se situe entre Walpole dont je vous parlais...`
- structure_verify / note_link_orphan_anchor: `原书 p.39 ¶0 — Alors, pardonnez-moi, pendant un certain nombre de séances dont je ne peux pas v...` | `Alors, pardonnez-moi, pendant un certain nombre de séances dont je ne peux pas vous fixer le nombre à l'avance, je vous parlerai du libérali...`
- structure_verify / note_link_orphan_anchor: `原书 p.104 ¶0 — la fin du XIX<sup>e</sup> siècle. Au congrès de Hanovre<sup>35</sup>, au congrès...` | `la fin du XIX<sup>e</sup> siècle. Au congrès de Hanovre<sup>35</sup>, au congrès de Bad Dürkheim encore en 1949, le Parti socialiste alleman...`
- structure_verify / note_link_orphan_anchor: `原书 p.106 ¶0 — Godesberg, ce fameux congrès de la renonciation absolue aux thèmes les plus trad...` | `Godesberg, ce fameux congrès de la renonciation absolue aux thèmes les plus traditionnels de la social-démocratie, c'était bien sûr la ruptu...`
- structure_verify / note_link_orphan_anchor: `原书 p.121 ¶0 — Husserl², qu'il s'était frotté de phénoménologie, qu'il avait connu un certain n...` | `Husserl², qu'il s'était frotté de phénoménologie, qu'il avait connu un certain nombre de ces juristes qui ont été finalement si importants d...`
- structure_verify / note_link_orphan_anchor: `原书 p.121 ¶0 — Husserl², qu'il s'était frotté de phénoménologie, qu'il avait connu un certain n...` | `Husserl², qu'il s'était frotté de phénoménologie, qu'il avait connu un certain nombre de ces juristes qui ont été finalement si importants d...`
- structure_verify / note_link_orphan_anchor: `原书 p.122 ¶0 — Il faudrait citer en fait, derrière eux, un certain nombre d'autres gens qui, eu...` | `Il faudrait citer en fait, derrière eux, un certain nombre d'autres gens qui, eux aussi, ont [joué un rôle important dans]* cette nouvelle d...`
- structure_verify / note_link_orphan_anchor: `原书 p.122 ¶0 — Il faudrait citer en fait, derrière eux, un certain nombre d'autres gens qui, eu...` | `Il faudrait citer en fait, derrière eux, un certain nombre d'autres gens qui, eux aussi, ont [joué un rôle important dans]* cette nouvelle d...`
- structure_verify / note_link_orphan_anchor: `原书 p.122 ¶0 — Il faudrait citer en fait, derrière eux, un certain nombre d'autres gens qui, eu...` | `Il faudrait citer en fait, derrière eux, un certain nombre d'autres gens qui, eux aussi, ont [joué un rôle important dans]* cette nouvelle d...`
- structure_verify / note_link_orphan_anchor: `原书 p.126 ¶2 — Enfin quatrième obstacle, lui, arrivé le plus récemment sur la scène historique...` | `Enfin quatrième obstacle, lui, arrivé le plus récemment sur la scène historique de l'Allemagne, ça a été le dirigisme de type keynésien. Dep...`
- structure_verify / note_link_orphan_anchor: `原书 p.127 ¶0 — de réseau continu. On est allé tout naturellement de l'économie protégée à l'éco...` | `de réseau continu. On est allé tout naturellement de l'économie protégée à l'économie d'assistance. La planification type Rathenau, par exem...`
- structure_verify / note_link_orphan_anchor: `原书 p.127 ¶0 — de réseau continu. On est allé tout naturellement de l'économie protégée à l'éco...` | `de réseau continu. On est allé tout naturellement de l'économie protégée à l'économie d'assistance. La planification type Rathenau, par exem...`
- structure_verify / note_link_orphan_anchor: `原书 p.127 ¶0 — de réseau continu. On est allé tout naturellement de l'économie protégée à l'éco...` | `de réseau continu. On est allé tout naturellement de l'économie protégée à l'économie d'assistance. La planification type Rathenau, par exem...`
- structure_verify / note_link_orphan_anchor: `原书 p.128 ¶1 — Et reprenant ce schéma et ce principe, ils étudient successivement différents ty...` | `Et reprenant ce schéma et ce principe, ils étudient successivement différents types d'économie, la planification soviétique par exemple. Ceu...`
- structure_verify / note_link_orphan_anchor: `原书 p.128 ¶1 — Et reprenant ce schéma et ce principe, ils étudient successivement différents ty...` | `Et reprenant ce schéma et ce principe, ils étudient successivement différents types d'économie, la planification soviétique par exemple. Ceu...`
- structure_verify / note_link_orphan_anchor: `原书 p.129 ¶1 — Deuxième leçon qu'ils ont tirée du nazisme, c'est celle-ci. Le nazisme, ont-ils...` | `Deuxième leçon qu'ils ont tirée du nazisme, c'est celle-ci. Le nazisme, ont-ils dit, qu'est-ce c'est ? C'est essentiellement, et avant tout,...`
