# FNM 树状模式：Phase 职责边界与条件分支

## 总体拓扑

```
Phase 0 (book_note_type)
  └─ 全书书型分类：endnote_only / footnote_only / mixed / no_notes

Phase 1 (chapter_split)
  └─ 页面角色 + 章节边界

Phase 2 (note_regions + note_items)
  └─ note_kind 分类(全书唯一来源) + note_mode 聚合(章级)

Phase 3 (body_anchors + note_linking)
  └─ body anchor 检测 + link 匹配
     (不能重分类 note_kind，不能用 chapter_mode 跳过修复)

Phase 4 (ref_freeze)
  └─ 引用注入 + FrozenUnit 构建

Phase 5 (translation_units + export)
  └─ TranslationUnit 构建 + 章 markdown 合并 + contract 检查

Phase 6 (audit)
  └─ 导出审计 + 最终 contract
```

## 树状原则

```
1. 分类源头唯一：每个 entity 的类型只在一处决定，下游透传不可覆盖
2. 分支条件穷尽互斥：禁止 else 吞掉边界情况
3. 禁止广播：章的聚合属性不能赋值给个体 entity
4. 上下游隔离：下游只消费上游事实，不可重新解释
5. 集中 dispatch 分散处理：按类型分流后独立处理
6. 不写逐书修补：用 pipeline 已有数据驱动，做正向验证而非黑名单排除
7. 模块化修补，先上游再下游
```

---

## Phase 0: 全书书型分类

**入口**: `modules/book_note_type.py:build_book_note_profile`

**唯一决策**: 全书属于哪种书型

```
逐页扫描 _note_scan.page_kind
  ├─ 强信号: 页首有 ## NOTES / ## Endnotes 标题 → is_heading_endnote
  ├─ 弱信号: page_kind=endnote_collection 或 ≥4 条编号定义 → is_weak_endnote
  └─ 额外守卫: TOC 无 endnotes 条目时，弱信号需同章有强信号锚点才保留

每章统计:
  ├─ 有 footnote 页 → chapter_has_footnote
  └─ 有 endnote 页 → chapter_has_endnote

全书聚合:
  has_footnote = any(chapter_has_footnote)
  has_endnote  = any(chapter_has_endnote)

  ├─ has_footnote ∧ has_endnote → "mixed"
  ├─ has_endnote                 → "endnote_only"
  ├─ has_footnote                → "footnote_only"
  └─ 否则                        → "no_notes"
```

**关键分支**:

```
book_type
├─ endnote_only  → 全书尾注，endnote orphan 有特殊处理
├─ footnote_only → 全书脚注
├─ mixed         → 章级混合，每章独立 note_mode
└─ no_notes      → 跳过注释处理
```

---

## Phase 1: 页面角色 + 章节边界

**入口**: `app/pipeline.py:build_phase1_structure`
**核心模块**: `modules/chapter_split.py:build_chapter_layers`

**唯一决策**: 每页的角色和每章的边界

```
page_role 分类:
  ├─ body          → 正文页
  ├─ front_matter  → 前页(目录/前言)
  ├─ note          → 注释页
  └─ back_matter   → 后页(索引/参考文献)

章节边界:
  ├─ 从 TOC 获取 chapter start_page/end_page
  ├─ 从 heading detection 获取标题位置
  └─ 从 visual TOC 获取额外线索
```

**输出**: `ChapterLayer` 列表，每章含:
- `body_pages`: 正文页列表(含 page.text)
- `footnote_items`: 脚注条目
- `endnote_items`: 尾注条目
- `note_regions`: 注释区域

---

## Phase 2: note_kind 分类(全书唯一来源) + note_mode 聚合

**入口**: `app/pipeline.py:build_phase2_structure`
**核心模块**: `note_regions.py` + `note_items.py`

**唯一决策(实体级)**: 每个 note_item 的 `note_kind` 是 `footnote` 还是 `endnote`

```
note_region 检测:
  ├─ 显式 ## NOTES 标题 → endnote region
  ├─ fnBlocks 中有连续编号的 footnote → 重分类为 endnote
  └─ 页脚 footnote 文本 → footnote region

note_item 提取:
  └─ 从 region 的 markdown/fnBlocks 中逐条提取，继承 region 的 note_kind
```

**聚合(章级——不能广播给实体)**:

```python
# pipeline.py:288-310 — _build_chapter_note_modes
for chapter in phase1.chapters:
    if footnote_regions:
        note_mode = "footnote_primary"
    elif chapter_endnote_regions:
        note_mode = "chapter_endnote_primary"
    elif book_endnote_regions:
        note_mode = "book_endnote_bound"
    else:
        note_mode = "no_notes"

    # 冲突: 同时有 footnote + endnote region → 标记 review_required
    if footnote_regions and (chapter_endnote_regions or book_endnote_regions):
        note_mode = "review_required"
```

**note_mode 是章的聚合标签，不能用于判断个体 entity 的种类。(树状原则 #3)**

---

## Phase 3: body anchor 检测 + link 匹配

**入口**: `app/pipeline.py:build_phase3_structure`
**核心模块**: `stages/body_anchors.py` + `stages/note_links.py`

**唯一决策**: 每个 anchor 的位置（`page_no`, `char_start`, `char_end`）和每个 link 的匹配状态

### 3a: body anchor 检测

```
scan_anchor_markers(paragraph_text)
  ├─ LaTeX sup:  $^{96}$   → source_marker="$ ^{96} $", normalized="96", certainty=1.0
  ├─ HTML sup:   <sup>96</sup> → source_marker="<sup>96</sup>", certainty=1.0
  ├─ Bracket:    [96]       → source_marker="[96]", certainty=1.0
  ├─ Unicode sup: ⁹⁶        → source_marker="⁹⁶", certainty=1.0
  ├─ Footnote ref: [^96]    → source_marker="[^96]", certainty=1.0
  ├─ Bare digit: 96         → source_marker="96", certainty=0.6 (需左侧词守卫)
  ├─ Apostrophe sup: '96    → source_marker="'96", certainty=0.55 (OCR 乱码修复)
  └─ Trailing symbol: ]*    → source_marker="]*", certainty=0.9

filter: _marker_in_expected_range
  ├─ 高置信度格式(latex/html/unicode/footnote_ref): 始终保留
  ├─ 有 footnote band 的页: 始终保留
  └─ 低置信度格式(bare_digit/bracket): 只在 chapter_marker_range [min, max+tolerance] 内保留
```

### 3b: link 匹配 (endnote_resolver)

```
for note_item in phase2.note_items (sorted by page_no):
    if note_kind != "endnote": continue

    marker = normalize_note_marker(note_item.marker)   ← 来自 note_item(定义页)

    候选 anchor 搜索:
      1. 同章 + 非 synthetic + 同 marker + endnote/unknown kind
      2. 同章 + synthetic(include) + endnote kind
      3. 跨章 + 非 synthetic + 同 marker

    ├─ 1 个候选   → matched (resolver=rule)
    ├─ 多个候选   → 按阅读顺序选最早未用的 → matched (resolver=repair)
    └─ 0 个候选   → orphan_note (resolver=rule)

orphan repair (_repair_endnote_links_for_contract):
  ├─ OCR variant repair: 同章 + 同 marker exact match
  ├─ Ordered subsequence: 同章 + marker digits 是 ordered subsequence
  └─ Fallback: orphan_note ↔ orphan_anchor 互换匹配

orphan_recovery (_build_orphan_recovery_anchors):
  └─ 对剩余 orphan_note endnote，逐页搜索 body text 中的 marker 原文
     (7 种格式逐一尝试: [N], $^{N}$, <sup>N</sup>, ^{N}, $^{N}$, ^N, unicode sup)
```

### 3c: link 匹配 (footnote_resolver)

```
for note_item in phase2.note_items:
    if note_kind != "footnote": continue

    星号脚注(*): 同页 + 同 marker + 按 paragraph_index 顺序配对

    候选搜索:
      1. 同章 + 非 synthetic + footnote kind + footnote_window(±1页)
      2. 多个候选 → nearest_unique_candidate
      3. 0 个候选 → OCR repair (ordered subsequence, ±1页窗口)
      4. 仍无 → _make_synthetic_anchor:
           anchor_kind="footnote", synthetic=True,
           source_marker=marker, page_no=note_item.page_no

    synthetic 替换: 同页有显式 anchor 则替换
```

### 3d: 并行辅助流程

```
paragraph_footnotes: layout-based 脚注分配
paragraph_endnotes:  layout-based 尾注分配
chapter_anchor_alignment: DP 序列对齐(尾注 marker 序列 vs anchor 序列)
```

---

## Phase 4: 引用注入 + FrozenUnit 构建

**入口**: `app/pipeline.py:build_phase4_structure`
**核心模块**: `modules/ref_freeze.py:build_frozen_units`
**同时使用**: `modules/note_linking.py:build_note_link_table`(模块版)

**唯一决策**: 每个 link 的 `decision`(injected/skipped) 和 body_units 的 `source_text`

### 4a: 模块版 link 表构建(chapter_merge → note_linking)

```
build_note_link_table(chapter_layers, pages)
  ├─ _materialize_note_item_overrides  → LLM 合成 note_item
  ├─ build_body_anchors               → anchor 检测(Phase 2 内)
  ├─ build_note_links                 → link 匹配(Phase 3 内)
  ├─ _repair_endnote_links_for_contract → endnote link 修复
  ├─ _repair_explicit_footnote_anchor_ocr_variants → footnote OCR 修复
  ├─ _materialize_anchor_overrides    → LLM 合成 anchor
  └─ _apply_link_overrides            → link override
```

### 4b: 引用注入(build_frozen_units)

```
for link in matched_links:
    anchor = anchor_by_id[link.anchor_id]

    ┌─ missing_anchor           → skip
    ├─ synthetic anchor:
    │   ├─ source_marker=""     → skipped (无数据来源，不可注入)
    │   └─ sm == nm(bare digit) → skipped (太宽泛，容易误匹配)
    ├─ conflict_anchor          → skipped (error_skip)
    ├─ duplicate_anchor         → skipped (policy_skip)
    └─ injection:
        _inject_token_once(payload["text"], anchor, marker, note_id)
        ├─ 尝试 anchor.source_marker → 找到? 替换 → injected
        ├─ 尝试 [marker]             → 找到? 替换 → injected
        ├─ 尝试 source_text(LLM)     → 找到? 追加 → injected
        ├─ 尝试 regex [^?marker]     → 找到? 替换 → injected
        └─ 都不匹配 → token_not_found → skip

skip 类别:
  ├─ ceiling_skip: missing_anchor, synthetic_anchor(bare digit), token_not_found
  │   └─ 清理 body text 中的 raw marker
  ├─ error_skip: conflict_anchor, missing_body_page
  │   └─ 不清理 marker(异常情况需保留现场)
  └─ policy_skip: duplicate_anchor
      └─ 清理 body text 中的 raw marker

清理后的 body text + 注入的 token → _segment_paragraphs_from_body_pages
  → _chunk_body_page_segments → body_units(FrozenUnit)
```

### 4c: note_unit 构建

```
note_items 按 chapter + region 分组 → note_units(FrozenUnit)
  ├─ chapter view: 从 chapter.footnote_items / chapter.endnote_items 取
  └─ owner fallback: 从 chapter_layers.note_items 兜底补录
```

**source_marker 守卫(Phase 4)**:

```python
# ref_freeze.py:291-299
if bool(anchor.synthetic):
    sm = str(anchor.source_marker or "").strip()
    if not sm:          # 空 → 无原文可匹配
        skip("synthetic_anchor")
    if sm == nm:        # bare digit → 太宽泛
        skip("synthetic_anchor")
```

---

## Phase 5: TranslationUnit + 导出

**入口**: `app/pipeline.py:build_phase5_structure`
**核心模块**: `stages/units.py:build_translation_units` + `stages/export.py`

### 5a: 引用物化(build_translation_units)

```
build_translation_units(phase4, pages):
  _build_structured_body_pages_for_chapter  → body_pages
    ├─ note_start_page: 拆分 body/note 文本
    ├─ chapter_start_page: 拆分前缀/章文本
    ├─ _trim_trailing_markdown_note_block: 修剪尾部 note 定义
    ├─ post_note_body detection: note_start 后的页可能有 body
    └─ gap page filling: 章之间的页补入

  _materialize_refs_for_chapter(Phase 5 版注入):
    与 Phase 4 相同的 synthetic anchor 守卫:
    ├─ source_marker=""  → synthetic_skipped
    └─ sm == nm          → synthetic_skipped

  _segment_paragraphs_from_body_pages:
    source_by_page(frozen_body_pages, 含 token)
    display_by_page(obsidian_body_pages, replace_frozen_refs 后)

    parse_page_markdown → 跨页段落合并
    └─ consumed_by_prev: 跨页延续段被标记，合并到上一页

  _chunk_body_page_segments(max_body_chars=6000):
    按字数切块，每块 → TranslationUnitRecord
```

### 5b: 导出

```
_build_section_markdown(chapter, body_units, note_units):

  ┌─ book_type=="mixed" ∧ note_mode=="footnote_primary"
  │   → export_footnote._build_inline_footnote_section_markdown
  │      ├─ 显式 anchor → 附到具体段落
  │      └─ synthetic anchor → 降级为页末整页脚注(page_fallback)
  │
  └─ 否则(标准路径):
      _rewrite_body_text_with_local_refs:
        Step 1: _replace_note_refs_with_local_labels
                └─ {{NOTE_REF:en-00411}} → [^138]
        Step 2-4: raw bracket/superscript/unicode ref 替换
        Step 5: replace_frozen_refs
                └─ 残存 {{NOTE_REF:...}} → [^en-00411]
        Step 6: 残存 {{NOTE_REF:...}} → [^N]

      _emit_definitions: [^138]: note text

      contract check:
        refs = body 中的 [^N] 集合
        defs = NOTES 中的 [^N]: 集合
        orphan_definition = defs - refs  → 报 orphan
```

---

## 关键条件分支全景

```
pipeline 入口
├─ book_type=no_notes → 跳过所有注释 phase
├─ book_type=endnote_only → 全尾注路径
│   ├─ endnote_resolver + orphan_recovery
│   └─ export: 标准路径(非 inline footnote)
├─ book_type=footnote_only → 全脚注路径
│   ├─ footnote_resolver + synthetic footnote
│   └─ export: footnote_primary 内联渲染
└─ book_type=mixed → 章级混合
    └─ 每章按 note_mode 分支:
        ├─ footnote_primary → inline footnote export
        ├─ chapter_endnote_primary → endnote 标准路径
        ├─ book_endnote_bound → 全书尾注池，按 marker 分配到章
        └─ review_required → 阻塞，需人工审核
```

## anchor 数据来源(尾注)

```
尾注 anchor 只允许三个来源(均有页面原文作为数据出处):

1. OCR 检测 (body_anchors.py:286)
   synthetic=False, source_marker="页面匹配到的原文", source="markdown:{pattern}"

2. orphan_recovery (note_links.py:266)
   synthetic=True, source_marker="页面匹配到的原文", source="orphan_recovery"
   └─ _find_marker_in_body 逐页搜索 7 种 marker 格式

3. LLM repair (note_linking.py:302)
   synthetic=False, source_marker=override["normalized_marker"], source="llm"
   └─ MIMO 视觉模型确认

已删除: gap_fill(算术补全)
```

## source_marker 守卫(Phase 4 & Phase 5)

```
所有 synthetic anchor 需通过两道检查才能注入:

1. source_marker 非空    → 有数据来源
2. sm != nm              → 非 bare digit(有格式包装，能精确匹配)

不满足 → skipped(不注入)
满足   → 尝试注入(用 source_marker 在页面文本中匹配)
```
