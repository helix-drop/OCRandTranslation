# FNM 注释覆盖率与契约重建计划（已归档）

> 创建于 2026-04-26。归档于 2026-04-28（8 张工单全部完成）。基线测试输入：[`test_example/Biopolitics/`](../test_example/Biopolitics/)（Foucault《Naissance de la biopolitique》14 章，PDF 共 370 页）。
> 基线证据：[`fnm_real_test_result.json`](../test_example/Biopolitics/fnm_real_test_result.json)、[`fnm_real_test_modules.json`](../test_example/Biopolitics/fnm_real_test_modules.json)、[`golden_exports/golden_note_manifest.json`](../test_example/Biopolitics/golden_exports/golden_note_manifest.json)、[`golden_exports/real_golden_template/`](../test_example/Biopolitics/golden_exports/real_golden_template/)。

## 0. 整套工程完成总结（2026-04-28）

| 工单 | 状态 | 关键改动 |
|---|---|---|
| #1 anchor 形态扩展 | ✅ 2026-04-26 | 复用 `shared/anchors.scan_anchor_markers` + 加 `_FOOTNOTE_REF_RE` / `_BARE_DIGIT_RE` / 黑名单守卫；`chapter_split._scan_body_anchor_markers` 替换窄正则 |
| #3 契约 v2 | ✅ 2026-04-27 | `note_linking._chapter_contracts` 加 first_marker_is_one / marker_gap / def_anchor_mismatch 三阀；`ChapterLayers` / `ChapterLinkContract` 加新字段 |
| #4 链接质量阈值 | ✅ 2026-04-27 | 原计划"修计数 bug"被证伪；新增 `fallback_match_ratio` 指标 + 双阈值阻塞 + `link_resolver_counts` 语义 docstring |
| #5 page_role + 文本侧 NOTES | ✅ 2026-04-27 | `_build_page_roles` 保留 partition `note` 角色（不被 chapter mapping 覆盖）；`_legacy_page_role` 透传 note；移除 `note_regions` 的 footnote-band 短路；`book_note_type` 加 nearest-prior 兜底 |
| #2 区域合并 | ✅ 2026-04-27（最小集） | 主问题被 #5 副作用解决；本工单只做回归保险 + `region_first_note_item_marker` 回填 |
| #6 mode endnote 优先 | ✅ 2026-04-27 | `book_note_type` 改"页数比较"为"endnote 容器优先"决策 |
| #7 NOTES 块格式 | ✅ 2026-04-27 | 新增 `chapter_merge._apply_notes_block_format` helper：`### NOTES` 标题统一 + `[^N]: N. ...` 印刷前缀（幂等） |
| #8 长 note 截断 | ✅ 2026-04-27 | `_PAGE_CITATION_PREFIX_RE` 在 `document/note_detection.py` 与 `FNM_RE/shared/notes.py` 两处同步扩展 12 类引文缩写（vol / n° / cf / infra / éd / dir 等） |

**最终验收（Biopolitics fixture 真实端到端）**：

| 指标 | 基线（修前） | 完成后 | 变化 |
|---|---|---|---|
| 全书 endnote_items | 0 | ~498 | 0 → 488 (金板) +2% |
| `### NOTES` 标题章数 | 1（仅 ch.1） | 13 / 13 | 全覆盖 |
| `[^N]: N. ...` 印刷前缀 | 0 章 | 13 / 13 | 全覆盖 |
| `chapter_endnote_primary` 章 | 2 | 11 | +9 |
| `fallback_match_ratio` | 73% | 2% | -97% |
| `orphan_anchor_total` | 204 | 1 | -99% |
| `page_role_counts.note` | 0 | 65 | 0 → 65 |
| 长 note 截断章数 | 8（vol./n° 处切） | 0 | 全部恢复 |
| `tests/unit/` passed | 929 | 988 | +59 新测试 |
| `tests/unit/` failed | 44 baseline | 44 baseline | 0 新失败 |

## 1. 背景与口径声明

当前 Biopolitics 真实模式测试通过：`blocked = false`、`blocking_reasons = []`、`all_ok = true`。但与金板逐项对比后：

- **golden_note_manifest 期望全书 488 条尾注**，当前导出仅产出 **210 条** `[^N]:` 定义，**缺口 57%**；
- 第 14 章（编者撰写的「Situation des cours」）按 manifest `expected_endnote_count = 0`，当前却**凭空导出 10 条**；
- 多章「定义编号不从 1 开始」（章 1=3、章 7=6、章 9=18、章 11=30），编号体系断裂；
- 章节缺 `### NOTES` 标题（除章 1 外其余 13 章都缺）；定义行缺金板要求的 `[^N]: N. ...` 印刷编号前缀。

**结论**：测试绿灯只代表模块「内部自洽」（local def == ref），不代表与金板「对地一致」。本计划的目标是把这一对齐落到代码层。

> 本计划不重写流水线，只在现有 [`FNM_RE/modules/`](../FNM_RE/modules/) 模块边界内补强检测、契约和导出后处理。

## 2. 模块对应关系

行号会随改动浮动，下表只给函数/常量名，请用编辑器跳转。带 ✅ 的位置已在工单 #1/#3/#4 中改动。

| 报告侧模块名 | 主代码文件 | 关键函数/常量 |
|---|---|---|
| M1 边界识别 | [`FNM_RE/modules/toc_structure.py`](../FNM_RE/modules/toc_structure.py) | `_build_page_roles` |
| M2 区域识别 | [`FNM_RE/modules/chapter_split.py`](../FNM_RE/modules/chapter_split.py) | `_to_layer_regions`、`_build_chapter_layers` |
| M3 anchor 形态 | [`FNM_RE/modules/chapter_split.py`](../FNM_RE/modules/chapter_split.py)、[`FNM_RE/shared/anchors.py`](../FNM_RE/shared/anchors.py) | ✅ `_scan_body_anchor_markers`（chapter_split）、✅ `scan_anchor_markers` / `_FOOTNOTE_REF_RE` / `_BARE_DIGIT_RE` / `_BARE_DIGIT_LEFT_WORD_BLACKLIST`（shared/anchors） |
| M3 mode 判定 | [`FNM_RE/modules/chapter_split.py`](../FNM_RE/modules/chapter_split.py) | `_note_capture_summary` |
| M4 freeze 契约 | [`FNM_RE/modules/ref_freeze.py`](../FNM_RE/modules/ref_freeze.py) | `_unit_contract_issues`（unit 结构校验）、`build_frozen_units` |
| M5 link 契约 | [`FNM_RE/modules/note_linking.py`](../FNM_RE/modules/note_linking.py) | ✅ `_chapter_contracts`（章级对地）、✅ `_summarize_links` / `_link_quality_gate`（链接质量） |
| M5 类型载体 | [`FNM_RE/modules/types.py`](../FNM_RE/modules/types.py) | ✅ `ChapterLayers.chapter_marker_counts`、✅ `ChapterLinkContract.has_marker_gap` / `def_anchor_mismatch` / `def_count` / `anchor_total` / `marker_sequence` |
| M5 阈值 | [`config.py`](../config.py) | ✅ `LINK_FALLBACK_MATCH_RATIO_THRESHOLD_DEFAULT`、`LINK_ORPHAN_ANCHOR_THRESHOLD_DEFAULT` |
| M6 导出 | [`FNM_RE/modules/chapter_merge.py`](../FNM_RE/modules/chapter_merge.py) | `build_chapter_markdown_set`、`_LOCAL_DEF_LINE_RE` |
| M6 导出审计 | [`scripts/test_fnm_batch.py`](../scripts/test_fnm_batch.py) | ✅ `_analyze_export_text.local_numbering_no_gap`（工单 #3 旁路） |
| M7 visual_toc/类型 | [`FNM_RE/modules/book_note_type.py`](../FNM_RE/modules/book_note_type.py) | `_NOTES_HEADING_RE`、`_is_endnote_page`、`build_book_note_profile` |
| 真实回归入口 | [`scripts/test_fnm_real_batch.py`](../scripts/test_fnm_real_batch.py)、[`tests/integration/test_fnm_real_mode.py`](../tests/integration/test_fnm_real_mode.py) | — |

## 3. 量化证据：每章期望 vs 实际

来源：`golden_note_manifest.json` 的 `expected_endnote_count` vs 当前 zip 各章 `[^N]:` 与 `[^N]` 的去重数。

| 章 | 期望 | 当前定义 | 当前唯一 ref | 缺口 | 当前 mode | 应为 mode |
|---|---|---|---|---|---|---|
| 1 | 18 | 4 | 4 | **−14** | footnote_primary | chapter_endnote_primary |
| 2 | 17 | 1 | 1 | **−16** | footnote_primary | chapter_endnote_primary |
| 3 | 32 | 2 | 2 | **−30** | footnote_primary | chapter_endnote_primary |
| 4 | 53 | 21 | 21 | −32 | chapter_endnote_primary ✓ | chapter_endnote_primary |
| 5 | 54 | 26 | 26 | −28 | footnote_primary | chapter_endnote_primary |
| 6 | 62 | 24 | 24 | −38 | chapter_endnote_primary ✓ | chapter_endnote_primary |
| 7 | 42 | 25 | 25 | −17 | footnote_primary | chapter_endnote_primary |
| 8 | 52 | 2 | 2 | **−50** | footnote_primary | chapter_endnote_primary |
| 9 | 42 | 38 | 38 | −4 | footnote_primary | chapter_endnote_primary |
| 10 | 37 | 2 | 2 | **−35** | footnote_primary | chapter_endnote_primary |
| 11 | 37 | 31 | 31 | −6 | footnote_primary | chapter_endnote_primary |
| 12 | 32 | 24 | 24 | −8 | footnote_primary | chapter_endnote_primary |
| 13 | 0 | 0 | 0 | 0 ✓ | no_notes ✓ | no_notes |
| 14 | 0 | 10 | 10 | **+10 假阳** | no_notes (但生成 region) | no_notes |
| **合计** | **488** | **210** | **210** | **−278 (−57%)** | | |

## 4. 关键内容采样

### 4.1 章 1：18 个引用被压成 4 个（anchor 形态欠拟合）

正文中章 1 实际有 18 处尾注引用，OCR 后呈现 6 种不同形态。当前 `_BODY_NOTE_MARKER_RE = re.compile(r"\[\^?(\d{1,4})\]")` 只识别其中 1 种：

| 注号 | OCR 形态 | 当前是否识别 |
|---|---|---|
| 1, 2, 3, 4 | `[^N]` | ✅ |
| 5 | `ensuite⁵`（Unicode 上标） | ❌ |
| 6, 8, 12, 15-18 | 裸方括号 `[6]` `[8]` `[12]` `[15]` `[16]` `[17]` `[18]` | ❌ |
| 9 | `liste $ ^{9} $`（TeX 上标） | ❌ |
| 10 | `gouverner<sup>10</sup>`（HTML sup） | ❌ |
| 11 | `Encyclopédie 11`（裸数字） | ❌ |

`### NOTES` 区只剩孤儿一段（`(1800-1804), in Jeremy Bentham's Economic Writings...`，金板第 9 条注的中段），缺 `[^N]:` 头。

第 75 行同段中 OCR 的两个手稿星号脚注 `*` `**` 被错认为新 `[^3]` `[^4]` 引用，导致同章 `[^3]` `[^4]` 各出现 3 次。按金板 [`PROCESSING_NOTES.md`](../test_example/Biopolitics/golden_exports/real_golden_template/PROCESSING_NOTES.md) 第 8 条，这两个应转 `[footnote]` 块。

### 4.2 章 5：54 条注被截到 26 条（区域被切碎）

[`fnm_real_test_modules.json`](../test_example/Biopolitics/fnm_real_test_modules.json) 显示章 5 的 chapter_endnotes region 被拆成 3 段（p139-140 / p142 / p144）。同一章 NOTES 容器是连续的，应合并为一个区域；下游 `array_rows` 把它拆成 10+6+11 三个 array，编号体系连续性丢失。导出文件中 `[^1]:`-`[^26]:` 存在但 `[^27]:`-`[^54]:` 全部缺失，且**章末没有 `### NOTES` 标题**（仅章 1 有）。定义行缺 `N. ` 印刷前缀（金板 `[^1]: 1. Walter Eucken...` vs 当前 `[^1]: Walter Eucken...`）。

### 4.3 章 14：本应无注却凭空 10 条

`SITUATION DES COURS` 是编者导读，manifest 标 `note_pages: []`。当前模块在 p343 / p345-348 扫出 15 条 footnote-like item，导出 10 条 `[^N]:`。这是「无 NOTES 容器声明」时未启用「抑制」的反向案例。

## 5. 按模块倒推的设计问题

### M1 boundary_detection
- `first_note_page = None`、`page_role_counts.note` 字段从未填充。
- `role_reason` 全为 `default_body` / `archive_noise` / `blank_front_page`，缺「NOTES 容器」识别理由。
- 当 visual_toc `endnotes_summary = {}` 时无文本侧 fallback。

### M2 note_region_detection
- `region_start_first_source_marker` / `region_first_note_item_marker` 全为空串（首条注号信息没抓）。
- 章末连续 chapter_endnotes 区被按页切碎（章 5 拆 3 段、章 6 拆 3 段、章 4 拆 2 段）。
- 章 1/2/3/8/10 的真 NOTES 容器（书页 39-42 等）未被任何 region 覆盖；模块只抓到正文中 `*`/`**` 手稿脚注页（33/37）。
- `endnote_region_rows = []`：取证表与 `region_rows` 不一致。

### M3 endnote_array_building
- `_BODY_NOTE_MARKER_RE` 只识 `[^N]/[N]`，6 种形态漏 5。
- mode 判定用「capture/anchor 比值」启发式覆盖 region_kind 权威，形成「anchor 少→比值高→误判 footnote」死循环。
- `capture_ratio` 报警单边（仅 < 阈值），高 ratio（章 6 = 28、章 14 = 1.0 凭空 15）从不报警。
- `endnote_array_rows = []`：取证表缺。

### M4 endnote_merging（最关键，「绿灯但有问题」根因）
- `chapter_local_contract_ok` 只校验「def 数 = ref 数 / 无孤儿」，**不校验**：
  - 编号从 1 开始
  - 编号连续无断号
  - 章定义数与 anchor 全形态扫描期望一致
- 缓存兜底无遥测：`owner_fallback_note_unit_count = 0` 但实际定义文本来自缓存。

### M5 anchor_resolution
- ~~`link_resolver_counts` 总和 373 ≠ `matched` 266，计数器有 bug~~ → **更正（工单 #4 调研后）**：`link_resolver_counts` 是按 resolver 维度对**所有 link** 全量计数（含 matched/orphan/ignored），sum 等于总 link 数（373），与 matched（266）不可直接比较。原判读为"bug"是误解，已在 [`note_linking._summarize_links`](../FNM_RE/modules/note_linking.py) docstring 钉死语义。
- fallback 占 75%、orphan_anchor 73 个，无任何阈值挂到 blocking_reasons。
- `chapter_link_contract_summary.failed_chapter_ids = []`：与 M4 同样宽。

### M6 export
- `### NOTES` 标题输出条件不一致：章 1 有、其余 13 章无。
- 定义行缺 `N. ` 印刷前缀（PROCESSING_NOTES 第 25 行明确要求）。
- `expected_endnote_count = 0` 章节未启用 NOTES 抑制（章 14 凭空）。

### M7 visual_toc / book_note_type
- `endnotes_summary = {}` 即「present=false」，下游就照「无 NOTES」行事。
- `_is_endnote_page` 已有但未被 `_build_page_roles` 调用 → 文本侧 fallback 路径断开。

### M8 翻译缓存（旁路）
- 缓存命中无 metadata 回写；缓存内容在合并阶段疑似按句号/换行截断（章 5 [^4] 被截到 `vol.`）。

## 6. 工单清单（8 张）

> 每张工单：**模块/文件 → 问题 → 修改方案 → 测试方案（先红后绿）→ 验收指标**。
> AGENTS.md 第 5 条要求「出 bug 先写能重现的测试，再修复」，所有工单都按此顺序。

---

### 工单 #1 — anchor 形态扩展为多 marker ✅ 完成（2026-04-26）

**模块**：M3

**问题**：单正则 `_BODY_NOTE_MARKER_RE = re.compile(r"\[\^?(\d{1,4})\]")` 只匹配 `[^N]/[N]`，章 1 实测 18 个引用只识 4 个。

**实际落地**（与原计划方案不同——见调研结论）：

调研发现 [`FNM_RE/shared/anchors.py`](../FNM_RE/shared/anchors.py) `scan_anchor_markers()` 已支持 5 形态识别（HTML / LaTeX / plain `^{}` / bracket / Unicode 上标），但 `chapter_split.py` 自己用一个独立窄正则做章级 marker 统计。两份代码并存导致上下游识别不一致。

最终方案：**复用 shared/anchors，不新建 `document/text_utils.normalize_body_note_markers`**。
1. [`FNM_RE/shared/anchors.py`](../FNM_RE/shared/anchors.py)：
   - 修复 `[^N]` 漏识 bug（原 `_BRACKET_REF_RE` 不含 `^`）：新增 `_FOOTNOTE_REF_RE`（优先级最高）。
   - 新增第 6 形态"紧跟法语词后的裸数字"`_BARE_DIGIT_RE`，配 `_BARE_DIGIT_LEFT_WORD_BLACKLIST`（p / pp / vol / cf / voir / Section / 法语介词等）守卫；左词长度 ≥ 4 + 严格右标点 lookahead 防假阳。
   - `_REF_PATTERN_PRIORITY` / `_REF_PATTERN_CERTAINTY` 加入新 pattern。
   - Roman ordinal `XVIIIe` 等被现有 `_HTML_SUP_RE` 严格 `\d{1,4}` 自然过滤；年份由 `looks_like_year_marker` 过滤。
2. [`FNM_RE/modules/chapter_split.py`](../FNM_RE/modules/chapter_split.py)：
   - 删 `_BODY_NOTE_MARKER_RE`；新增 `_scan_body_anchor_markers(text)` helper，逐行扫描 `scan_anchor_markers`，跳过 `[^N]:` 定义行（避免把 NOTES 区定义当 anchor 重复计数）。
   - `_chapter_body_marker_sets` 与 `_build_chapter_layers` 两处使用全部切换。

**测试方案**（实际）：
- 新建 [`tests/unit/test_body_note_marker_normalization.py`](../tests/unit/test_body_note_marker_normalization.py) 14 测试：
  - 5+1 形态各一个用例（`[^N]` / `[N]` / `<sup>N</sup>` / `$ ^{N} $` / Unicode 上标 / 裸数字）
  - Roman ordinal mask（`XVIII<sup>e</sup>` / `XIXe XXe` / `n° 21`）
  - `p. 200` 页码引用排除
  - `[1789]` 年份过滤
  - Biopolitics 章 1 真实段落（Unicode 上标）
  - 5 形态混合段
  - 裸数字守卫（"段内无明确 marker 时不识别"）
- 回归：[`tests/unit/test_chapter_anchor_alignment.py`](../tests/unit/test_chapter_anchor_alignment.py) 等无需改动即通过。

**验收**（实际）：
| 章 | 期望 | 改前 | 改后 | 命中 |
|---|---|---|---|---|
| 1 | 18 | 4 | 16 | 89% ✓ ≥16 |
| 5 | 54 | 26 | 54 | 100% ✓ ≥50 |
| 8 | 52 | 2 | 50 | 96% ✓ ≥48 |
| 全书 | 488 | 210 | ~445 | 91% |

`tests/unit/` 通过数 929 → 943（+14 全是新测试），baseline 44 失败保持，无新失败。

**已知边缘**：章 10/11 各多识 1 条（裸数字假阳性），由工单 #3 的 marker_gap 校验兜底；章 14 多识 12 条（实为编者真实引用），由工单 #5/#7 处理 NOTES 容器声明 / 抑制开关。

---

### 工单 #2 — 章末连续 NOTES 区合并 ✅ 完成（2026-04-27 最小集）

**模块**：M2

**问题**：章 5 拆 3 段（p139-140/142/144）、章 6 拆 3 段（p170-171/174/176）、章 4 拆 2 段（p111-112/114）。

**实际落地**（与原计划不同）：

调研发现原 #2 主问题（chapter_endnotes region 被切碎）**已被工单 #5 副作用解决**——`_build_endnote_regions_raw` 自身按 contiguous page-no 自然成段，前提是不被 footnote-band 短路（#5 修了）。本工单只做两件小事：

1. **回归保险**：新增 [`tests/unit/test_chapter_endnote_region_consolidation.py`](../tests/unit/test_chapter_endnote_region_consolidation.py) 5 测试，钉死章 5/6/7 的 chapter_endnotes region 为单一连续段 + `region_first_note_item_marker` 必须非空。
2. **取证字段回填**：[`FNM_RE/modules/types.py`](../FNM_RE/modules/types.py) `LayerNoteRegion` 加 `region_first_note_item_marker` 字段；[`FNM_RE/modules/chapter_split.py`](../FNM_RE/modules/chapter_split.py) `build_chapter_layers` 在 `build_note_items` 后按 `region_id` 取首条 note 的 normalized_marker，回填到 `NoteRegionRecord.region_first_note_item_marker`（mutable dataclass）；`_to_layer_regions` 透传该字段。

**未做**：原计划"页号差 ≤ 2 的兜底合并"——边缘场景 + 无实测需求，跳过。

**验收**：5 新测试全绿；章 5/6/7 各 1 个连续段 ✓；所有 endnote region 的 `region_first_note_item_marker` 非空（多数为 "1"）。

---

### 工单 #3 — 契约 v2：章级「对地」校验 ✅ 完成（2026-04-27）

**模块**：M5（pipeline 内部）+ 旁路 M6 导出审计

**问题**：当前契约只校验自洽，多章 `first_local_def_marker` 不是 "1"（章 1=3、章 7=6、章 9=18、章 11=30）但全部通过。

**实际落地**（与原计划"改 `_unit_contract_issues`"不同——见调研结论）：

调研发现 `ref_freeze._unit_contract_issues` 是 **unit 结构校验**（unit_id / kind / owner / page_segments 形态等），不是章级 marker 校验的合适位置。`note_linking._chapter_contracts` 已有 `first_marker_is_one` 字段，但当 `requires_endnote_contract = False`（mode 错判为 footnote_primary）时被强制 True 短路。

最终方案：契约 v2 加在 `_chapter_contracts`，并扩数据载体。

1. [`FNM_RE/modules/types.py`](../FNM_RE/modules/types.py)：
   - `ChapterLayers` 加字段 `chapter_marker_counts: dict[str, int]`（承载 chapter_split 累积的 anchor 全形态扫描数）。
   - `ChapterLinkContract` 加 5 个字段：`has_marker_gap` / `def_anchor_mismatch` / `def_count` / `anchor_total` / `marker_sequence`。
2. [`FNM_RE/modules/chapter_split.py`](../FNM_RE/modules/chapter_split.py)：
   - `build_chapter_layers` 把 `chapter_marker_counts` 传给 `ChapterLayers`。
3. [`FNM_RE/modules/note_linking.py`](../FNM_RE/modules/note_linking.py)：
   - `_chapter_contracts` 不再被 `requires_endnote_contract = False` 短路 `first_marker_is_one`；改为基于 chapter 的 footnote_items + endnote_items 数字 marker 并集计算三类对地校验：
     - `first_marker_is_one`：def 数字 marker 排序后最小值 == 1
     - `has_marker_gap`：去重后是否等于 `list(range(1, max+1))`
     - `def_anchor_mismatch`：def_count 与 chapter_marker_counts[chapter_id] 严格不等（anchor_total = 0 时不判）
   - `build_note_link_table.gate_report.hard` 加 `link.contract_first_marker_is_one` / `link.no_marker_gap` / `link.def_anchor_aligned`，对应 reasons `contract_first_marker_not_one` / `contract_marker_gap` / `contract_def_anchor_mismatch`。
   - `evidence.chapter_link_contract_summary` 加 `contract_v2_failed_chapter_ids` / `contract_v2_first_marker_violation_count` / `contract_v2_marker_gap_violation_count` / `contract_v2_def_anchor_mismatch_count` 四个诊断字段。
4. [`scripts/test_fnm_batch.py`](../scripts/test_fnm_batch.py)：
   - `_analyze_export_text` 加 `local_numbering_no_gap`：`sorted(int defs) == list(range(1, max+1))`。
   - `chapter_local_contract_ok` 校验加上 `local_numbering_no_gap`。

**测试方案**（实际）：
- 新建 [`tests/unit/test_ref_freeze_contract_v2.py`](../tests/unit/test_ref_freeze_contract_v2.py) 10 测试：
  - first_marker：`[3,4,5]` 触发 / `[1,2,3,4]` 不触发 / footnote_primary 章 + chapter_marker_counts=18 时通过 def_anchor_mismatch 暴露
  - marker_gap：`[1,2,4]` 触发 / `[1,2,3,4]` 不触发
  - def_anchor_mismatch：`def=5 vs anchor=18` 触发 / 5+5 不触发
  - no_notes 章节不误伤
  - `_analyze_export_text.local_numbering_no_gap` 三场景（连续 / 断号 / 无 def）
- 改名 [`tests/unit/test_fnm_re_module4_linking.py`](../tests/unit/test_fnm_re_module4_linking.py) `test_biopolitics_main_path_hard_gates_true` → `..._endnote_link_hard_gates_true`（断言原 5 类 endnote-link 阀仍 True），新增 `test_biopolitics_contract_v2_blocks_due_to_def_anchor_mismatch` 反向断言"必须 blocked"。

**验收**（实际）：
```
hard gates:
  ✓ link.first_marker_is_one (5 类 endnote-link 旧阀)
  ✓ link.endnotes_all_matched
  ✓ link.no_ambiguous_left
  ✓ link.no_orphan_note
  ✓ link.endnote_only_no_orphan_anchor
  ✓ link.contract_first_marker_is_one (v2 新阀)
  ✓ link.no_marker_gap (v2 新阀)
  ✗ link.def_anchor_aligned (v2 新阀) ← 触发
reasons: ['contract_def_anchor_mismatch']
contract_v2_def_anchor_mismatch_count: 13
```

13 章全部 def_anchor_mismatch，把"绿灯但缺一半"翻成红灯。`tests/unit/` 通过数 943 → 954（+11），baseline 44 失败保持，无新失败。

**下一步预期**：完成工单 #2/#5/#6/#7 后 mismatch 数应大幅下降；`local_numbering_no_gap` 也将转绿。

---

### 工单 #4 — fallback / orphan 占比硬阈值 + resolver 计数 bug

**模块**：M5
**主文件**：
- [`FNM_RE/modules/note_linking.py:109`](../FNM_RE/modules/note_linking.py) `_summarize_links`
- [`FNM_RE/modules/note_linking.py:1346`](../FNM_RE/modules/note_linking.py) `_chapter_contracts`
- [`config.py`](../config.py) — 新增可配阈值

**问题**：
- `link_resolver_counts: rule=131, repair=43, fallback=199`，总和 373 ≠ `matched` 266（计数 bug）
- fallback 占 75%、orphan_anchor 73 个，全部不进 blocking

**修改方案**：
1. 修计数 bug：定位 `_summarize_links` 把同一 link 多 resolver 累加的逻辑。
2. 新增阈值（默认值放 [`config.py`](../config.py)）：
   - `LINK_FALLBACK_RATIO_THRESHOLD = 0.30`
   - `LINK_ORPHAN_ANCHOR_THRESHOLD = 10`
   - 任一超阈 → `blocking_reasons` 加 `link_quality_low`

**测试方案**：
- 新建 `tests/unit/test_note_linking_quality_gate.py`：
  1. 100 条 link 中 50 条 fallback → 断言 `link_quality_low` in blocking_reasons
  2. 10 条 link 全部 resolver=fallback → `sum(link_resolver_counts.values()) == 10`

**验收指标**：
- 重跑后 `link_resolver_counts` 总和 == `matched`
- Biopolitics 当前 fallback=75% → 触发 `link_quality_low` 阻塞

---

### 工单 #5 — page_role 增加 `note` 类 + 文本侧 NOTES 检测器

**模块**：M1 + M7（兜底）
**主文件**：
- [`FNM_RE/modules/toc_structure.py:149`](../FNM_RE/modules/toc_structure.py) `_build_page_roles`
- [`FNM_RE/modules/book_note_type.py:42`](../FNM_RE/modules/book_note_type.py) `_is_endnote_page`（已存在但未被调用）
- 新增 [`FNM_RE/modules/note_region_text_detector.py`](../FNM_RE/modules/note_region_text_detector.py) — visual_toc 失效时启用

**问题**：`first_note_page = None`，没有 `note` 角色被打；visual_toc `endnotes_summary` 空时下游照「无 NOTES」行事；金板每章末尾确有 NOTES 容器页。

**修改方案**：
1. `_build_page_roles` 在 body 区遍历时调用 `_is_endnote_page(markdown)`，命中改 `page_role = "note"`、`role_reason = "text_side_endnote_detector"`。
2. 检测增强：连续 ≥ 3 行匹配 `_NOTE_DEF_RE`（`^N. ` 形态）即判 NOTES 页。
3. 把 `note` 页 role 透传到 `_to_layer_regions`，让其优先生成 `chapter_endnotes` 区而不是 `footnote` 区。

**测试方案**：
- 新建 `tests/unit/test_text_side_notes_detector.py`：用 [`test_example/Biopolitics/raw_pages.json`](../test_example/Biopolitics/raw_pages.json) 第 39-42、139-148、170-178 页文本作 fixture，断言判 `note`。
- 反例：第 17、100 页正文 → `body`。

**验收指标**：
- 章 1 NOTES region 从 33,37 改为含 39-42
- `page_role_counts.note` ≥ 30（manifest 共 30+ 章末注页）

---

### 工单 #6 — note_mode 判定以 region_kind 为权威

**模块**：M3
**主文件**：[`FNM_RE/modules/chapter_split.py:551`](../FNM_RE/modules/chapter_split.py) `_note_capture_summary`

**问题**：region 已标 `chapter_endnotes` 的章（5/7/9/10/11/12）mode 仍被覆盖为 `footnote_primary`，因为覆盖逻辑用 `captured_count vs expected_anchor_count` 比值，而 anchor 在工单 #1 之前严重欠拟合 → 形成负循环。

**修改方案**：
1. mode 决策改为 region_kind 多数投票优先：≥ 1 个 `chapter_endnotes` region 且页跨 ≥ 2 → `chapter_endnote_primary`，无 chapter_endnotes 才考虑 footnote。
2. `capture_ratio` 双向报警：`< 0.5` 或 `> 1.5` 都进 `abnormal_capture_chapter_ids`（原 `sparse_capture_chapter_ids` 改名）。

**测试方案**：
- 新建 `tests/unit/test_chapter_split_mode_decision.py`：
  1. region=[chapter_endnotes(p139-144)] + anchor=5 + captured=27 → mode=chapter_endnote_primary
  2. region=[footnote(p33), footnote(p37)] + captured=5 → mode=footnote_primary
  3. anchor=1 + captured=28 → ratio=28 → 进 abnormal 列表
- 回归 [`tests/unit/test_chapter_anchor_alignment.py`](../tests/unit/test_chapter_anchor_alignment.py)。

**验收指标**：
- Biopolitics 章 5/7/9/10/11/12 mode 全部为 `chapter_endnote_primary`
- 章 6 ratio=28、章 14 ratio=1.0 凭空 15 条 → 双侧报警

---

### 工单 #7 — 导出模板：`### NOTES` 统一 + `[^N]: N. ...` 印刷前缀 + 抑制开关

**模块**：M6
**主文件**：
- [`FNM_RE/modules/chapter_merge.py:641`](../FNM_RE/modules/chapter_merge.py) `build_chapter_markdown_set`
- [`FNM_RE/modules/chapter_merge.py:327`](../FNM_RE/modules/chapter_merge.py) `_LOCAL_DEF_LINE_RE` — 增 `N. ` 解析
- [`FNM_RE/modules/book_assemble.py:38`](../FNM_RE/modules/book_assemble.py) — 输出落格

**问题**：除章 1 外其余 13 章缺 `### NOTES` 标题；所有定义缺 `N. ` 印刷前缀；章 14 凭空导出 10 条。

**修改方案**：
1. `### NOTES` 标题统一条件：只要 chapter 有 ≥ 1 条 `chapter_local_def`，必输出标题。
2. 定义行渲染：`[^N]: N. <text>`；若 text 已以 `N.` 开头则不重复。
3. 增 `book_note_profile.suppress_chapter_ids` 配置：当上游声明 `expected_endnote_count == 0` 时跳过该章 NOTES 块。

**测试方案**：
- 新建 `tests/unit/test_chapter_merge_notes_block.py`：
  1. def_total ≥ 1 → 输出含 `### NOTES` 与 `[^1]: 1. ...`
  2. 缓存 `Walter Eucken (1891-1950)...` → 渲染 `[^1]: 1. Walter Eucken...`
  3. 缓存已有 `1. Walter Eucken...` → 不重复，仍 `[^1]: 1. Walter Eucken...`
  4. 章 manifest=0 + 抑制开关 → 输出无 `### NOTES`
- 回归 [`tests/unit/test_fnm_export.py`](../tests/unit/test_fnm_export.py)、[`tests/unit/test_definition_raw_marker_scope.py`](../tests/unit/test_definition_raw_marker_scope.py)。

**验收指标**：
- 重跑后 zip 章 2-12 全部含 `### NOTES`
- 章 5 `[^1]:` 起的行带 `1. ` 前缀
- 章 14 没有 `[^N]:` 块

---

### 工单 #8 — note 翻译缓存命中遥测 + 截断修复

**模块**：M8
**主文件**：
- [`persistence/storage_endnotes.py`](../persistence/storage_endnotes.py)
- [`FNM_RE/modules/chapter_merge.py:330`](../FNM_RE/modules/chapter_merge.py) `_chapter_note_text_by_id`、`_book_note_text_by_id`

**问题**：`owner_fallback_note_unit_count = 0` 但定义文本明显来自缓存；章 5 [^4] 在缓存里完整，导出时被截到 `vol.`。

**修改方案**：
1. 缓存命中时回写 `note_unit.source = "translation_cache"`，让 `owner_fallback_note_unit_count` 真实反映。
2. 定位截断点：grep `_chapter_note_text_by_id` / `_book_note_text_by_id`，检查是否对 cache 内容做 split/strip；测试对照原 cache 与导出文本。

**测试方案**：
- 新建 `tests/unit/test_note_translation_cache_merge.py`：
  1. cache `"Wilhelm Lautenbach (1891-1948); cf. notamment son article: ..."` → 导出后字符串完全一致
  2. cache 命中 → `owner_fallback_note_unit_count` ≥ 1
- 集成回归：跑 Biopolitics 真实模式，断言导出 ch.5 [^4] 字符长度 > 200。

**验收指标**：
- 章 5 [^4] 不再截到 `vol.`
- `owner_fallback_note_unit_count` 反映真实命中数

## 7. 落地顺序与依赖图

```
#1 (anchor 形态)  ──┐
#2 (region 合并) ──┤──→ #3 (契约 v2)  ──→ #6 (mode 判定)
#5 (page_role)   ──┘
                                          ↘
#4 (link 阈值) ─────────────────────────────→ #7 (导出格式)
                                          ↗
#8 (cache 截断 + 遥测) ──────────────────────┘
```

| 阶段 | 工单 | 目标 |
|---|---|---|
| 第一周 | #1 + #3 + #4 | 把「绿灯但缺一半」暴露成红灯（必须先红） |
| 第二周 | #2 + #5 + #6 | 区域识别和 mode 判定根因修复 |
| 第三周 | #7 + #8 | 导出层格式 + cache 兜底遥测 |

每张工单独立分支 / PR，pytest 在 `tests/unit/` 与 `tests/integration/`，通过后跑 [`scripts/test_fnm_real_batch.py`](../scripts/test_fnm_real_batch.py) 做 Biopolitics 回归。

## 8. 验证与交付检查清单

每个工单 PR 合并前必须满足：

- [ ] 该工单的「测试方案」中所有新增 `tests/unit/test_*.py` 都先红后绿
- [ ] 受影响的现有 `tests/unit/` 与 `tests/integration/` 全部通过
- [ ] [`scripts/test_fnm_real_batch.py`](../scripts/test_fnm_real_batch.py) 在 Biopolitics 上跑通，输出 [`fnm_real_test_result.json`](../test_example/Biopolitics/fnm_real_test_result.json) 的关键字段（`blocked` / `blocking_reasons` / `link_summary` / 各章 `note_capture_summary`）符合工单的「验收指标」
- [ ] 该 PR 引入的新参数 / 阈值在 [`config.py`](../config.py) 或对应模块文档中说明默认值与覆盖路径

全部 8 张工单完成后，验收口径：

- [ ] Biopolitics 全书 `[^N]:` 定义总数 ≥ **460**（金板 488 ± 6%）
- [ ] 章 14 凭空尾注归零
- [ ] 所有章 `first_local_def_marker == "1"`、编号连续
- [ ] 所有章含 `### NOTES` 标题（除 manifest 声明 0 注的章）
- [ ] 所有 `[^N]:` 行带 `N. ` 印刷前缀
- [ ] `link_resolver_counts` 总和 == `matched`
- [ ] fallback 占比 < 30%、orphan_anchor < 10（或 blocked）

## 9. 回滚与边界

- 任一工单回滚以 git revert 单 PR 为单位，不存在跨工单的破坏性 schema 变更。
- 对应文档同步：每个工单合并时同步修改 [`PROGRESS.md`](../PROGRESS.md) 的「最近实测」段；本计划文档（本文件）只在工单全部完成后归档到 [`DEV.md`](../DEV.md) 并删除。
- 不动 [`legacy/`](../legacy/) 与 [`归档/`](../归档/)（按 `chore(repo)` 仓库清洁约定）。
