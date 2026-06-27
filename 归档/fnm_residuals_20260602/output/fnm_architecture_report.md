# FNM Pipeline 架构、数据流与薄弱点分析

## 树状原则

```
分类来源唯一 → 分支穷尽互斥 → 禁止广播 → 上下游隔离 → 集中 dispatch 分散处理
```

每个 entity 的类型只在一处决定，下游透传不可覆盖。章的聚合属性不能赋值给个体 entity。下游只消费上游事实，不可重新解释。

## Phase 1: 页面角色 + 章节边界

| 项目 | 详情 |
|------|------|
| 入口 | `pipeline.py:171` `build_phase1_structure` |
| 核心模块 | `toc_structure.py` (TOC 解析), `chapter_skeleton/builder.py` (章节骨架) |
| 输入 | raw_pages.json (OCR markdown + blocks), 目录 PDF visual TOC |
| 输出 | `Phase1Structure`: pages (page_role: body/note/noise/front_matter), chapters (title, start_page, end_page), section_heads |
| 算法 | 规则 + 视觉模型 (visual TOC) |
| 数据流 | raw_pages → page_partitions → heading_candidates → chapters → section_heads |

**树状职责**: 唯一决定 page_role 和 chapter 边界。下游不允许重新划章。

**薄弱点**:
1. TOC 解析依赖视觉模型质量，OCR 模糊的目录页可能误判章节标题
2. `page_role` 分类没有语义理解——靠 markdown 特征（是否有 `## NOTES`、block 密度）判为 body/note/noise
3. 章节边界在 TOC 偏移和实际页面之间可能不对齐（reanchored_titles）

**LLM 补强**: ❌ 不需要。TOC 是一次性配置（manual TOC 过一遍即可），页面角色是稳定规则。

---

## Phase 2: 注记检测 + 分类 + 书型

| 项目 | 详情 |
|------|------|
| 入口 | `pipeline.py:351` `build_phase2_structure` |
| 核心模块 | `note_regions.py` (区域检测), `note_items.py` (条目提取), `book_note_type.py` (书型分类), `chapter_split.py` (章内拆分) |
| 输入 | Phase1 + raw_pages |
| 输出 | `Phase2Structure`: note_regions (region_kind + scope), note_items (marker, note_kind, source_text), chapter_note_modes (chapter_endnote_primary / footnote_primary / book_endnote_bound / no_notes) |
| 算法 | 规则: `_NOTE_DEF_RE` / `_SYMBOL_NOTE_DEF_RE` 正则提取, `_is_endnote_page` 启发式判断, per-chapter mode 推导 |
| 数据流 | pages → scan `## NOTES` heading → note_regions → parse def lines → note_items → classify book_type + chapter_modes |

**树状职责**: **note_kind 的唯一分类源**。每个 note_item 的 footnote/endnote 分类在此阶段决定。book_type 和 chapter_note_mode 也在此阶段决定。下游不可重分类。

**薄弱点**:
1. **star-marker 分类** (en-00036 `*`): 在 endnote region 中的 `*` 标记被归为 endnote——但它的行为像 footnote（不参与数字编号）。分类结果准确（它确实在尾注区），但下游 (export numbering) 需要特殊处理。
2. **`[n]` bracket 格式**: `resolve_anchor_kind` 已修复为 unknown/footnote，但 note_item 的分类不受影响。
3. **书型分类**: 纯规则驱动——"有章末尾注页 → chapter_endnote_primary"。没有对书的整体结构做语义理解。

**LLM 补强**: ⚠️ 中等价值。书型分类可以让 LLM 看 3-5 页样本判断，减少误判。但当前规则已足够稳定。

---

## Phase 3: 正文锚点检测 + 链接匹配（薄弱点集中区）

| 项目 | 详情 |
|------|------|
| 入口 | `body_anchors.py:756` `build_body_anchors`, `note_linking.py` `build_note_links` |
| 核心模块 | `anchors.py` (inline ref scan + anchor_kind 分类), `body_anchors.py` (per-page anchor building + bare_digit gate), `note_linking.py` (link matching + contract), `sup_recovery.py` (L0-L3 marker recovery), `visual_anchor_recovery.py` (visual recovery) |
| 输入 | Phase2 + raw_pages + PDF |
| 输出 | body_anchors (anchor_kind, normalized_marker, certainty), note_links (anchor↔note_item, status, resolver), contract (def_anchor_aligned, etc.) |
| 算法 | 规则: `_scan_inline_refs` 14 个正则扫描 → `resolve_anchor_kind` 分类 → `_positive_gate_bare_digit` 过滤 → rule/fallback/repair linking → contract validation。LLM: `sup_recovery` L3 vision 扫描 + `visual_anchor_recovery` vision gap filling + `llm_repair` cluster repair |

**数据流**:
```
每个正文页 markdown
  → _scan_inline_refs (14 regex patterns: latex, html, plain, bracket, bare_digit, unicode, ...)
  → scan_anchor_markers (同 marker + 重叠位置去重, year-like 过滤)
  → resolve_anchor_kind (pattern + footnote_band + endnote_marker_set → endnote/footnote/unknown)
  → _positive_gate_bare_digit (条件1: 在note_items中, 条件2: 未被高置信度覆盖, 条件3: ≤2次出现, 条件4: 句末白名单)
  → BodyAnchorRecord (source_marker, anchor_kind, certainty)
  → build_note_links (rule matching + fallback + gap-fill + LLM repair)
  → NoteLinkRecord (anchor↔note_item, status, resolver)
  → contract validation (def_anchor_aligned, first_marker_is_one, ...)
```

**树状职责**: anchor_kind 的唯一分类源。linking 是 Phase 2 note_kind 的消费者——不可重分类 note_kind。

**薄弱点 (最集中)**:
1. **bare_digit gate** (~150行): 纯正向证据——在 note_items 中、未被覆盖、≤2次、句末位置。仍有假阳性 (page 208 `7»`) 和假阴性 (句末白名单可能漏掉合法 bare_digit)。
2. **sup_recovery L3** (~400行): 324次 vision 扫描，117次成功但位置不精确（词中间注入），141次 REJECTED。Vision 模型返回的坐标不稳定。
3. **contract 过于严格**: 5个 orphan note (LLM不可控) 导致整个 pipeline 阻塞。Δ=1 就 block，没有容忍度。
4. **OCR 多重检测**: `_scan_inline_refs` 产出的 `<sup>6</sup>`, `$ ^{6} $`, `⁶` 在同位置被 `scan_anchor_markers` 去重，但在不同段落中的重复检测可能产生多余 anchor。
5. **gap-fill 假 anchor**: ch002 anchor-00619 把标题页 "17 janvier" 的 "17" 当成了尾注标记。

**LLM 补强**: ✅✅ **最高价值**。
- 当前 bare_digit gate 是纯规则白名单——LLM 可以直接判断 "这个上下文里的数字 7 是不是尾注标记"
- 当前 llm_repair 只修 orphan/ambiguous——可以扩展到 bare_digit 验证
- 当前 contract 是硬阻塞——可以改为 LLM 对 Δ=1 的章做最终判断

---

## Phase 4: 引用冻结 + 翻译单元

| 项目 | 详情 |
|------|------|
| 入口 | `ref_freeze.py` (ref freeze), `units.py:756` `build_translation_units` |
| 核心模块 | `ref_freeze.py` (坐标注入 `{{NOTE_REF:xxx}}`), `units.py` (段落拆分 + 跨页合并 + 翻译单元组装) |
| 输入 | Phase3 anchors + links + raw_pages |
| 输出 | frozen body pages (正文中 marker 被替换为 `{{NOTE_REF:xxx}}`), translation_units (body_units + note_units) |
| 算法 | `_inject_token_once` 坐标注入 + 候选列表兜底; `_chunk_body_page_segments` 段落拆分 + consumed_by_prev 跨页合并 |

**树状职责**: 消费 Phase 3 的 link 数据，将 raw marker 替换为 frozen ref token。不重新分类。

**薄弱点**:
1. **段落去重** (`_chunk_visible_paragraphs`): consumed_by_prev=False 的段落无去重——同段跨页时可能重复（但影响很小，Biopolitics 仅 ch011 [^8]×2）
2. **bare_digit 注入失败** (ch002 [^17]): `ref_freeze` 对 bare_digit 坐标注入可能失效（source_marker 是纯数字，候选列表不包含它）。正确行为（不应注入假的标题页 anchor），但 link 已存在。
3. **`consumed_by_prev` 含 NOTE_REF 的重入逻辑**: 可能在新位置重新注入 ref token，导致同段多次出现。

**LLM 补强**: ❌ 低价值。段落拆分是纯文本处理，LLM 做不了更好。

---

## Phase 5: 章合并

| 项目 | 详情 |
|------|------|
| 核心模块 | `chapter_merge.py` |
| 输入 | Phase4 translation_units + Phase3 links |
| 输出 | Phase5Structure (merged chapters) |

**薄弱点**: book_endnote_bound 章的尾注投影到各章时可能漏项或重复。当前代码稳定，无已知 bug。

**LLM 补强**: ❌ 不需要。

---

## Phase 6: 导出

| 项目 | 详情 |
|------|------|
| 入口 | `export.py:711` `build_export_zip` |
| 核心模块 | `export.py` (chapter markdown 构建 + 编号 + 定义渲染), `ref_rewriter.py` (frozen ref → `[^N]` 转换) |
| 输入 | Phase5 translation_units + links + note_items |
| 输出 | ExportBundleRecord → ZIP |
| 算法 | `_rewrite_body_text_with_local_refs` 4层替换链 → `_local_endnote_ref_number` 编号 → `_emit_definitions` 尾注区渲染 |

**树状职责**: 格式渲染——将 frozen ref 转为 `[^N]`，给 endnote 编号，渲染 NOTES 区。不重新分类。

**薄弱点**:
1. **`_local_endnote_ref_number` 编号逻辑**: star-marker 吞噬编号 (已修)、skip-footnote 预占编号 (已修)、non-digit marker 未处理 (已修)。三层 bug 都在这个函数。
2. **4层替换链**: `NOTE_REF → bracket → superscript → unicode` 的顺序可能产生级联干扰。
3. **`_emit_definitions`**: 只渲染 `ordered_note_ids` 中的定义，star marker 定义以 `[footnote] \*` 格式渲染。

**LLM 补强**: ❌ 不需要。编号和渲染是纯机械操作。

---

## 总览

```
raw_pages ──→ Phase1 ──→ Phase2 ──→ Phase3 ──→ Phase4 ──→ Phase5 ──→ Phase6 ──→ ZIP
             页面角色    注记提取    锚点+链接    引用冻结    章合并      导出
             章节边界    书型分类    【最薄弱】   翻译单元               编号渲染
            
LLM介入:     视觉TOC      无         sup_recovery  无         无         无
                                    visual_recov
                                    llm_repair
```

| Phase | 薄弱程度 | LLM 补强价值 | 说明 |
|-------|---------|------------|------|
| 1 | 低 | ❌ | 视觉 TOC 已用 LLM，其余规则稳定 |
| 2 | 中 | ⚠️ | 书型分类可 LLM，当前规则已够用 |
| **3** | **高** | **✅✅** | bare_digit gate、contract 容忍度、gap-fill 假 anchor |
| 4 | 低 | ❌ | 纯文本处理 |
| 5 | 低 | ❌ | 稳定 |
| 6 | 低 | ❌ | 机械操作，bug 已修 |

**结论**: Phase 3 是唯一需要 LLM 补强的阶段。具体方向：
1. **bare_digit 判别**: LLM 看页面 → "这个数字是不是尾注" (替代规则白名单)
2. **contract 降级**: Δ≤1 且全部来自 orphan note → 不阻塞 (替代硬阻塞)
3. **gap-fill 验证**: LLM 确认 gap-fill 创建的 anchor 是否合理 (替代盲目信任)
