# FNM 8本书全量测试报告 — MiMo V2.5 Token Plan

**测试日期**: 2026-05-03 04:19–05:22 CST  
**视觉模型**: MiMo V2.5 (mimo-v2.5) via Token Plan API (`mimo_token_plan` provider)  
**视觉模型 Base URL**: `https://token-plan-sgp.xiaomimimo.com/v1`  
**翻译模式**: placeholder (跳过翻译)  
**总耗时**: 约 63 分钟

---

## 1. 总体摘要

| 指标 | 数值 |
|------|------|
| 总书籍数 | 8 |
| 通过 (ready) | 1 (Neuropsychoanalysis_Introduction) |
| 阻塞 (blocked) | 7 |
| 总 API 请求数 | 313 |
| 总 Token 消耗 | **661,780** |
| Prompt Tokens | 592,025 |
| Completion Tokens | 69,755 |
| 使用模型 | **mimo-v2.5** (唯一) |
| visual_toc 请求 | 27 (87,691 tokens) |
| llm_repair 请求 | 286 (573,754 tokens) |

**Token 排名 (从高到低)**:

| 书籍 | Tokens | 请求数 | 状态 |
|------|--------|--------|------|
| Mad_Act | 182,400 | 100 | blocked |
| Germany_Madness | 136,323 | 45 | blocked |
| Biopolitics | 120,120 | 59 | blocked |
| Napoleon | 89,139 | 47 | blocked |
| Heidegger_en_France | 83,295 | 35 | blocked |
| Neuropsychoanalysis_in_Practice | 38,146 | 22 | blocked |
| Goldstein | 8,504 | 3 | blocked |
| Neuropsychoanalysis_Introduction | 3,853 | 2 | **ready** |

---

## 2. 各 Phase Token 消耗详情

### 2.1 visual_toc (视觉目录识别)

| 子阶段 | 请求数 | Prompt | Completion | Total |
|--------|--------|--------|------------|-------|
| visual_toc.preflight | 1 | 311 | 24 | 335 |
| visual_toc.manual_input_extract | 26 | 61,417 | 26,274 | 87,691 |

**每书 visual_toc 明细**:

| 书籍 | 请求数 | Tokens | 目录页数 |
|------|--------|--------|----------|
| Biopolitics | 7 | 14,793 | 6 |
| Germany_Madness | 2 | 19,281 | 2 |
| Goldstein | 2 | 5,522 | 2 |
| Heidegger_en_France | 4 | 9,950 | 4 |
| Mad_Act | 3 | 11,700 | 3 |
| Napoleon | 3 | 8,682 | 3 |
| Neuropsychoanalysis_in_Practice | 4 | 14,245 | 4 |
| Neuropsychoanalysis_Introduction | 2 | 3,853 | 2 |

### 2.2 llm_repair (LLM 修补)

| 子阶段 | 请求数 | Prompt | Completion | Total |
|--------|--------|--------|------------|-------|
| llm_repair.cluster_request | 286 | 530,297 | 43,457 | 573,754 |

**每书 llm_repair 明细**:

| 书籍 | 请求数 | Tokens | auto_applied | suggestions |
|------|--------|--------|--------------|-------------|
| Biopolitics | 52 | 105,327 | 54 | 113 |
| Germany_Madness | 43 | 117,042 | 31 | 124 |
| Goldstein | 1 | 2,982 | 0 | 1 |
| Heidegger_en_France | 31 | 73,345 | 38 | 111 |
| Mad_Act | 97 | 170,700 | 20 | 230 |
| Napoleon | 44 | 80,457 | 24 | 71 |
| Neuropsychoanalysis_in_Practice | 18 | 23,901 | 5 | 22 |
| Neuropsychoanalysis_Introduction | 0 | 0 | 0 | 0 |

### 2.3 sup_recovery (上标恢复，FNM Pipeline 内部)

sup_recovery 是 Phase 3 (body_anchors) 内部的视觉模型调用，**不在此批次的 token_summary 中**（token 统计走 pipeline 内部路径）。每轮 pipeline 重建都会重新执行 sup_recovery。

**Biopolitics sup_recovery 统计** (3轮):
- layer3_vision: 38 次/轮 (共114次)
- unrecovered: 39 markers/轮
- pages_enriched: 38 pages
- layer0_unicode: 70 (第一阶段Unicode检测)
- 详细: 13 chapters 中有 superscript markers，每章3-5个缺失marker需视觉恢复

**Germany_Madness sup_recovery 统计** (3轮):
- layer3_vision: ~18-19 次/轮
- unrecovered: ~60 markers/轮
- pages_enriched: 19-20 pages
- layer1_pymupdf: 1 (PyMuPDF检测到1个)

**Mad_Act sup_recovery 统计** (3轮):
- layer3_vision: ~44-47 次/轮 (最多!)
- unrecovered: ~1031-1034 markers/轮 (极大)
- pages_enriched: 137 pages
- layer1_pymupdf: 82-85

**Goldstein sup_recovery 统计** (3轮):
- layer3_vision: ~6-7 次/轮
- unrecovered: ~17-18 markers/轮

**Napoleon sup_recovery 统计** (3轮):
- layer3_vision: ~33-34 次/轮
- unrecovered: ~26-27 markers/轮
- pages_enriched: 38-39 pages

**Neuropsychoanalysis_in_Practice sup_recovery 统计** (2轮):
- layer3_vision: ~2 次/轮
- unrecovered: 0
- pages_enriched: 2

---

## 3. 各书详细分析

### 3.1 Biopolitics (370页, 法语)

| 指标 | 数值 |
|------|------|
| 状态 | **blocked** |
| Pipeline OK | True |
| note_items | 592 (footnote:112, endnote:480) |
| matched links | 586 |
| footnote_orphan_anchor | 57 |
| endnote_orphan_note | 13 |
| fallback_count | 42 |
| repair_count | 146 |
| llm_repair auto_applied | 54 |
| structure_state | review_required |

**阻塞原因**:
1. `freeze_matched_ref_not_injected` — 匹配的引用未能注入到翻译单元
2. `merge_local_refs_unclosed` — 章节内局部引用未闭合
3. `export_audit_blocking` — 导出审计阻塞
4. `structure_review_required` — 需要结构审查

**阻塞定位详情** (关键页面):
- p.40: 2个 orphan endnote (Robert Walpole, Foucault précision)
- p.64-65: 2个 orphan endnote (Foucault引用, "Il faut défendre la société")
- p.112-113: 4个 orphan endnote (European Recovery Program, Grundtexte)
- p.174: 1个 orphan endnote (F. Bilger引用)
- p.199: 1个 orphan endnote (Klaus Croissant)
- heading_graph: 14个TOC body items全部resolved, 但有1个demoted chapter title ("MICHEL FOUCAULT")
- heading_graph boundary conflicts: 无
- page_partition: 370页 → body:282, note:65, noise:3, front_matter:5, other:15

**章节级 footnote/endnote 分布**:
- 12 chapters 使用 chapter_endnotes 模式
- 2 chapters 使用 body_only 模式 (RÉSUMÉ, SITUATION DES COURS)
- 无 book_endnotes 模式
- 尾注共计480条，跨12章分布

### 3.2 Germany_Madness (464页, 英语/德语)

| 指标 | 数值 |
|------|------|
| 状态 | **blocked** |
| Pipeline OK | True |
| note_items | 1,134 (footnote:1,123, endnote:11) |
| matched links | 1,077 |
| endnote_orphan_note | 6 |
| fallback_count | 396 |
| repair_count | 37 |
| llm_repair auto_applied | 31 |
| structure_state | review_required |

**阻塞原因** (最多!):
1. `link_endnote_not_all_matched` — 尾注链接未完全匹配
2. `link_orphan_note_remaining` — 残留孤儿注释
3. `contract_def_anchor_mismatch` — 契约定义锚点不匹配
4. `freeze_matched_ref_not_injected` — 匹配引用未注入
5. `merge_local_refs_unclosed` — 局部引用未闭合
6. `export_audit_blocking` — 导出审计阻塞
7. `structure_review_required` — 需要结构审查

**阻塞定位详情** (关键页面):
- p.129: 多个 orphan note (Paracelsus文献引用)
- p.321: 4个 orphan note (Bauer, Altötting 文献)
- p.49: 2个 ambiguous link (Panofsky, McCloy引用)
- heading_graph: 8个TOC body items optimized, 无 unresolved/conflicts

### 3.3 Goldstein / post-revolutionary (431页, 英语)

| 指标 | 数值 |
|------|------|
| 状态 | **blocked** |
| Pipeline OK | True |
| note_items | 926 (全部 endnote) |
| matched links | 893 |
| endnote_orphan_note | 0 |
| footnote_orphan_anchor | 0 |
| fallback_count | 0 |
| repair_count | 127 |
| llm_repair auto_applied | 0 |
| structure_state | review_required |

**阻塞原因**:
1. `link_first_marker_not_one` — 首标记不是1
2. `contract_first_marker_not_one` — 契约首标记不是1
3. `freeze_matched_ref_not_injected` — 匹配引用未注入
4. `merge_local_refs_unclosed` — 局部引用未闭合
5. `export_audit_blocking` — 导出审计阻塞
6. `structure_review_required` — 需要结构审查

**阻塞定位详情** (关键页面):
- p.388: orphan_note (尾注引用)
- p.21: orphan_anchor (American tribes引用)
- p.41: orphan_anchor (conversation引用)
- p.60: 2个 orphan_anchor (laissez-faire引用)
- p.65: orphan_anchor (crowd引用, 含 `<sup>60</sup>` HTML残留)
- p.71, 75, 100, 110: 多个 orphan_anchor
- heading_graph: 2个TOC body items optimized

**重要发现**: p.65 仍有 `<sup>60</sup>` HTML标签残留，说明 sup_recovery 或 OCR 阶段未完全处理上标格式。

### 3.4 Heidegger_en_France (608页, 法语) — 最大书籍

| 指标 | 数值 |
|------|------|
| 状态 | **blocked** |
| Pipeline OK | True |
| note_items | 1,645 (全部 footnote) |
| matched links | 1,587 |
| footnote_orphan_anchor | 5 |
| fallback_count | 953 (最多!) |
| repair_count | 126 |
| llm_repair auto_applied | 38 |
| structure_state | review_required |

**阻塞原因**:
1. `freeze_matched_ref_not_injected` — 匹配引用未注入
2. `structure_review_required` — 需要结构审查

**阻塞定位详情** (关键页面):
- p.7-9: 多个 ambiguous/orphan note (Rockmore, Löwith, Adorno, Gadamer引用)
- heading_graph: 3个TOC body items optimized

**特点**: fallback_count=953 (极高), 占比 953/1587=60%。说明大量链接使用fallback resolver而非精确匹配。Footnote-only书籍(无endnote)。

### 3.5 Mad_Act (824页, 英语/中文) — Token消耗最多

| 指标 | 数值 |
|------|------|
| 状态 | **blocked** |
| Pipeline OK | True |
| note_items | 378 (footnote:368, endnote:10) |
| matched links | 368 |
| endnote_orphan_note | 10 |
| fallback_count | 324 |
| repair_count | 29 |
| llm_repair auto_applied | 20 |
| structure_state | review_required |

**阻塞原因** (9个 - 最多):
1. `link_first_marker_not_one` — 首标记不是1
2. `link_endnote_not_all_matched` — 尾注链接未完全匹配
3. `link_orphan_note_remaining` — 残留孤儿注释
4. `contract_first_marker_not_one` — 契约首标记不是1
5. `contract_marker_gap` — 标记缺口
6. `freeze_matched_ref_not_injected`
7. `merge_local_refs_unclosed`
8. `export_audit_blocking`
9. `structure_review_required`

**阻塞定位详情** (关键页面):
- p.785-787: 密集 orphan note (清代法律条文引用)
- heading_graph: 14个TOC body items optimized (最多)

**特点**: 824页大书，中英双语，清代法律引文复杂。sup_recovery unrecovered=1031 (极高，可能因中文注释格式特殊)。fallback_count=324/368=88%。

### 3.6 Napoleon (396页, 法语)

| 指标 | 数值 |
|------|------|
| 状态 | **blocked** |
| Pipeline OK | True |
| note_items | 459 (全部 footnote) |
| matched links | 404 |
| fallback_count | 18 |
| repair_count | 33 |
| llm_repair auto_applied | 24 |
| structure_state | review_required |

**阻塞原因**:
1. `freeze_matched_ref_not_injected`
2. `export_audit_blocking`
3. `export_cross_chapter_contamination` — **跨章污染** (独特!)
4. `structure_review_required`

**阻塞定位详情** (关键页面):
- p.7-16: 多个 ambiguous link (学术引用: Esquirol, Deleuze, Goldstein等)
- heading_graph: 18个TOC body items optimized
- sup_recovery: 34 layer3_vision calls, 26 unrecovered

**独特问题**: `export_cross_chapter_contamination` — 章节间引用交叉污染，仅此本书有此问题。

### 3.7 Neuropsychoanalysis_in_Practice (386页, 英语)

| 指标 | 数值 |
|------|------|
| 状态 | **blocked** |
| Pipeline OK | True |
| note_items | 90 (全部 footnote) |
| matched links | 90 |
| fallback_count | 17 |
| repair_count | 6 |
| llm_repair auto_applied | 5 |
| structure_state | review_required |

**阻塞原因**:
1. `freeze_matched_ref_not_injected`
2. `structure_review_required`

**阻塞定位详情** (关键页面):
- p.46, 61, 67, 71, 90, 172, 249, 281: orphan note (学术自引: Northoff, Metzinger)

**特点**: 简单的footnote-only书籍。90个note item全部是footnote。阻塞程度较轻。

### 3.8 Neuropsychoanalysis_Introduction (168页, 英语) — **唯一通过**

| 指标 | 数值 |
|------|------|
| 状态 | **ready** |
| Pipeline OK | True |
| note_items | 0 |
| matched links | 0 |
| llm_repair auto_applied | 0 |
| structure_state | ready |

**特点**: 唯一完全通过的书籍。168页小书，无任何注释(no footnotes, no endnotes)。结构简单，无需任何LLM修复。**仅消耗3,853 tokens** 用于 visual_toc (2页目录)。

---

## 4. 金版对比分析

### 4.1 Biopolitics 金版对比

| 指标 | 数值 |
|------|------|
| 对比章数 | 14 |
| 完全通过章 | 1/14 (RÉSUMÉ DU COURS) |
| 总问题数 | 27 |
| 总正文引用差异 | 导出 472 vs 金版 484 (-12) |
| 总尾注定义差异 | 导出 480 vs 金版 491 (-11) |

**金版对比——逐章详情**:

| 章节 | 相似度 | 导出refs | 金版refs | 导出defs | 金版defs | 状态 |
|------|--------|----------|----------|----------|----------|------|
| 001-Leçon du 10 janvier | 65.8% | 17 | 18 | 18 | 18 | 缺refs [17,18], 多refs [1] |
| 002-Leçon du 17 janvier | **0.2%** | 15 | 16 | 17 | 17 | 严重不匹配! |
| 003-Leçon du 24 janvier | 70.6% | 32 | 29 | 34 | 32 | 多refs [6,22,33,34], 多defs [33,34] |
| 004-Leçon du 31 janvier | 96.7% | 54 | 53 | 53 | 53 | 缺refs [50-53], 多refs [3,7,15,20,21] |
| 005-Leçon du 7 février | 93.9% | 55 | 54 | 54 | 54 | 多refs [4] |
| 006-Leçon du 14 février | 78.8% | 64 | 62 | 61 | 62 | 缺refs [61,62], 缺defs [62], 重复refs [32,33] |
| 007-Leçon du 21 février | 90.9% | 35 | 42 | 42 | 42 | 大量缺refs [35-42] |
| 008-Leçon du 7 mars | 63.6% | 52 | 52 | 52 | 52 | 缺refs [51,52], 多refs [9,14] |
| 009-Leçon du 14 mars | 96.9% | 41 | 41 | 42 | 42 | 缺refs [41,42], 多refs [1,39] |
| 010-Leçon du 21 mars | 90.0% | 33 | 36 | 37 | 37 | 缺refs [34-37], 多refs [3] |
| 011-Leçon du 28 mars | 86.2% | 42 | 36 | 37 | 37 | 多refs [2,9,9,10,10,17] |
| 012-Leçon du 4 avril | 84.5% | 32 | 32 | 33 | 32 | 缺refs [32], 多refs [11], 多defs [33] |
| 013-RÉSUMÉ DU COURS | 91.7% | 0 | 0 | 0 | 0 | **✅ 通过** |
| 014-SITUATION DES COURS | **4.5%** | 0 | 13 | 0 | 13 | **严重不匹配!** 全缺 |

**关键发现**:
- **002章** (相似度仅 0.2%) 和 **014章** (4.5%) 极其异常——可能是章节分割或标题匹配失败
- Biopolitics 的 sup_recovery 修复了38个上标标记，但仍有39个无法恢复（见上文）
- 尾部章节 (012, 013, 014) 的尾注处理有系统性差异
- 章节内 ref 重复 (如 ch006 的 [32,32,33], ch011 的 [9,9,10,10]) 是 OCR/匹配问题

### 4.2 Goldstein 金版对比

| 指标 | 数值 |
|------|------|
| 对比章数 | 9 |
| 完全通过章 | 0/9 |
| 总问题数 | 25 |
| 总正文引用差异 | 导出 1,057 vs 金版 921 (+136!) |
| 总尾注定义差异 | 导出 926 vs 金版 921 (+5) |

**关键差异**: Goldstein 导出的正文引用比金版多 **136个**！这是极其重大的差异。

**金版对比——逐章详情**:

| 章节 | 相似度 | 导出refs | 金版refs | 导出defs | 金版defs | 状态 |
|------|--------|----------|----------|----------|----------|------|
| 001-Introduction | 88.6% | 28 | 26 | 27 | 26 | 多refs [8,13], 多defs [27] |
| 002-Perils of Imagination | 82.0% | 101 | 86 | 85 | 86 | 多refs(大量), 缺defs [86] |
| 003-Revolutionary Schooling | 66.1% | 108 | 95 | 96 | 95 | 多refs, 多defs [96] |
| 004-Mental Apparatus | 79.4% | 114 | 108 | 112 | 108 | 多refs(7个), 多defs(4个) |
| 005-A Priori Self | 72.7% | 151 | 142 | 138 | 142 | 大量缺refs [136-142], 多refs |
| 006-Cousinian Hegemony | 53.9% | 195 | 169 | 183 | 169 | 大量多refs+多defs(extreme) |
| 007-Vie Intérieure | 70.9% | 121 | 112 | 104 | 112 | 大量缺refs [105-112], 多refs |
| 008-Phrenological Alternative | **31.3%** | 199 | 152 | 152 | 152 | 严重不匹配! 多refs(extreme) |
| 009-Epilogue | 21.7% | 40 | 31 | 29 | 31 | 多refs |

**关键发现**:
- **系统性冗余引用**: 几乎所有章节都多余了正文引用，总计多出 136 个 refs
- **008章** (31.3%) 和 **009章** (21.7%) 相似度极低，导出引用了远超金版的 refs
- **006章** (53.9%) 导出 195 refs vs 金版 169 refs (+26!) 和 183 defs vs 169 defs (+14!)
- Goldstein 的 sup_recovery 只有 2-7 次 layer3_vision 调用，说明视觉模型上标恢复极少
- Goldstein 花费了极少的 token (8,504)，但结果差异巨大——说明模型没能解决尾注冗余问题

---

## 5. 阻塞模式分析

### 5.1 阻塞原因频率统计

| 阻塞原因 | 出现次数 | 影响书籍 |
|----------|----------|----------|
| `structure_review_required` | 7 | 所有阻塞书籍 |
| `freeze_matched_ref_not_injected` | 7 | 所有阻塞书籍 |
| `merge_local_refs_unclosed` | 4 | Biopolitics, Germany_Madness, Goldstein, Mad_Act |
| `export_audit_blocking` | 5 | Biopolitics, Germany_Madness, Goldstein, Mad_Act, Napoleon |
| `link_endnote_not_all_matched` | 2 | Germany_Madness, Mad_Act |
| `link_first_marker_not_one` | 2 | Goldstein, Mad_Act |
| `link_orphan_note_remaining` | 2 | Germany_Madness, Mad_Act |
| `contract_first_marker_not_one` | 2 | Goldstein, Mad_Act |
| `contract_marker_gap` | 1 | Mad_Act |
| `contract_def_anchor_mismatch` | 1 | Germany_Madness |
| `export_cross_chapter_contamination` | 1 | Napoleon (唯一) |

### 5.2 阻塞严重度分级

**极度阻塞** (5+原因):
- **Mad_Act** (9原因): 824页中英双语，清代法律文献注释极复杂
- **Germany_Madness** (7原因): 464页学术著作，德语/英语混合

**重度阻塞** (4原因):
- **Biopolitics**: 370页法语学术著作
- **Goldstein**: 431页英语，尾注冗余(+136 refs vs golden)
- **Napoleon**: 396页法语，独有跨章污染问题

**中度阻塞** (2原因):
- **Heidegger_en_France**: 608页最大书，但阻塞原因最少
- **Neuropsychoanalysis_in_Practice**: 386页，小规模注释

### 5.3 根本阻塞原因分析

1. **`freeze_matched_ref_not_injected`** (7/8书) — 最普遍的阻塞。即使 llm_repair 匹配了引用，也无法注入到翻译单元中。这是 Phase 4 (引用注入) 的系统性问题。

2. **`structure_review_required`** (7/8书) — 几乎每本书都需要人工结构审查。说明自动结构检测仍有显著改进空间。

3. **`merge_local_refs_unclosed`** (4/8书) — 章节内局部引用无法闭合。Phase 5 (章节 markdown 合并) 的问题。

4. **`export_audit_blocking`** (5/8书) — 导出审计阶段发现严重问题。Phase 6 的校验过于严格。

---

## 6. sup_recovery (上标恢复) 统计

sup_recovery 在 Phase 3 body_anchors 中运行，每次 pipeline 重建都会重新执行。

| 书籍 | L3 Vision 调用/轮 | 总Vision调用(3轮) | Unrecovered | Pages Enriched |
|------|-------------------|-------------------|-------------|----------------|
| Biopolitics | 38 | 114 | 39 | 38 |
| Germany_Madness | 18-19 | ~55 | 60 | 19-20 |
| Goldstein | 6-7 | ~19 | 17-18 | 7 |
| Mad_Act | 44-47 | ~136 | 1031 | 137 |
| Napoleon | 33-34 | ~101 | 26-27 | 38-39 |
| Neuropsychoanalysis_Practice | 2 | ~6 | 0 | 2 |
| Heidegger_en_France | N/A (混合策略) | N/A | N/A | N/A |
| Neuropsychoanalysis_Introduction | N/A | N/A | N/A | N/A |

**关键发现**:
- sup_recovery 的 layer3_vision 调用**不计入** batch token summary（只有 visual_toc 和 llm_repair 的 token 被统计）
- 实际 MiMo 视觉模型调用量远超报告的 313 次——sup_recovery 额外增加了约 **430+ 次**视觉调用
- 真实总 MiMo API 调用量估计: 313 + 430 = **~743 次**

---

## 7. 模型使用汇总

| 阶段 | 使用模型 | 请求数 | Tokens |
|------|----------|--------|--------|
| visual_toc.preflight | mimo-v2.5 (token_plan) | 1 | 335 |
| visual_toc.manual_input_extract | mimo-v2.5 (token_plan) | 26 | 87,691 |
| llm_repair.cluster_request | mimo-v2.5 (token_plan) | 286 | 573,754 |
| **小计 (已统计)** | | **313** | **661,780** |
| sup_recovery L3 vision (估算) | mimo-v2.5 (token_plan) | ~430 | ~未统计~ |
| **总计 (估算)** | | **~743** | **~未统计~** |

**注意**: sup_recovery 的 token 消耗未被本批次的 token_summary 统计，因为 sup_recovery 走 pipeline 内部路径而非显式 trace callback。实际 token 消耗远高于报告的 661,780。

---

## 8. 关键发现与建议

### 8.1 通过率分析

- 唯一通过的书籍 **Neuropsychoanalysis_Introduction** (168页) 没有任何注释 (0 note_items)
- 所有含注释的书籍都阻塞 (7/7)
- 注释类型不重要 —— footnote-only 和 endnote-only 书籍都阻塞

### 8.2 Token 效率

- **Mad_Act** 消耗最多 token (182,400) 但 auto_applied 只有 20 (效率 9,120 tok/fix)
- **Heidegger_en_France** 效率较高 (83,295 tok, 38 fixes = 2,192 tok/fix)
- **Goldstein** 消耗最少 (8,504 tok) 但 auto_applied=0 —— 几乎没做修复
- **Biopolitics** 中等效率 (120,120 tok, 54 fixes = 2,224 tok/fix)

### 8.3 金版对照关键差异

- **Biopolitics**: 缺少 12 个正文引用和 11 个尾注定义 vs 金版
- **Goldstein**: 多出 136 个正文引用 vs 金版 —— 系统性过度引用
- Goldstein 相似度总体低于 Biopolitics (大部分章 60-80% vs 85-97%)
- 两个金版对照书籍的尾部章节都严重偏离金版

### 8.4 阻塞根因优先级

1. **Phase 4 引用注入** (`freeze_matched_ref_not_injected`): 7/8书，最高优先级
2. **Phase 5 章节合并** (`merge_local_refs_unclosed`): 4/8书
3. **Phase 3 链接匹配** (link_* 系列): 4/8书
4. **Phase 6 导出审计**: 5/8书

---

## 9. 补充说明

- 本次测试使用 **MiMo V2.5 Token Plan** 模型作为唯一的视觉模型
- 所有 visual_toc 和 llm_repair 视觉调用均通过 `mimo_token_plan` provider
- sup_recovery 的 MiMo 调用不计入本报告 token 统计 (走 pipeline 内部路径)
- 翻译步骤已跳过 (`--skip-translation`), 使用 placeholder 翻译
- 测试完成时间: 2026-05-03 05:22 CST
- 测试输出目录: `/Users/hao/OCRandTranslation/output/fnm_real_batch/full8_mimo25_20260503_041914/`

---

*报告由 Claude Code 自动生成，基于 FNM Pipeline 8本书全量测试结果。*  
*视觉模型: MiMo V2.5 (mimo-v2.5) via Token Plan API*
