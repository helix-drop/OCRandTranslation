# Phase 2 LLM 改造：代码走查 + 四书送检 + 方案汇总

## 一、Phase 1→Phase 2 实际数据流（代码走查）

### 1.1 完整调用链

```
Phase 1 (page_partition.py)
  │
  ├─ _resolve_page_role()     13条规则级联，逐页判断 body/note/noise/front_matter
  │   ├─ _rule_note_scan      page_kind=="endnote_collection" → role="note" (0.95)
  │   ├─ _rule_notes_heading  首行为 ## NOTES → role="note" (0.88)
  │   └─ _rule_default_body   兜底 → role="body" (0.62)
  │
  ├─ build_page_partitions()  组装 PagePartitionRecord（含 page_role, reason）
  │
  ▼
toc_structure.py
  │
  ├─ _build_page_roles()      最终 page_role 赋值，5级优先级：
  │   1. source_role=="note" → role="note"（最高优先，不被章节映射覆盖）
  │   2. page 在 chapter 映射内 → 继承 chapter.role
  │   3. page >= back_matter_start → role="back_matter"
  │   4. source_role=="other" → role="front_matter"
  │   5. else → role="front_matter"
  │
  ├─ _resolve_endnotes_start_page()  提取 TOC 中 "Notes" 条目的 book_page
  │
  ▼
book_note_type.py  ← 本书型判断的核心
  │
  ├─ build_book_note_profile()
  │   │
  │   ├─ [1] toc_has_endnotes_entry  TOC 根节点中是否有 role=="endnotes"
  │   │
  │   ├─ [2] 第一遍扫描：找 chapters_with_heading
  │   │     条件：_has_notes_heading() 或 page_kind=="endnote_collection"
  │   │     作用：无 TOC endnotes 条目时，弱信号页面的锚点守卫
  │   │
  │   ├─ [3] 第二遍扫描：逐页分类
  │   │     has_footnote: page.footnotes 字段非空
  │   │     has_endnote:
  │   │       强信号: _has_notes_heading (## NOTES 标题)
  │   │       弱信号: _is_endnote_page (≥4编号定义 或 连续序列)
  │   │       重分类: _reclassify_post_body_fnblocks_as_endnote
  │   │       ⚠️ 同页有 footnote+endnote → endnote 被抑制
  │   │       ⚠️ 弱信号 + 无TOC + 章节无锚点 → endnote 被丢弃（防止 Germany_Madness 误判）
  │   │
  │   ├─ [4] 补检：_chapter_has_consecutive_endnote_sequence
  │   │     对章末8页做从1开始的连续序列检测（最强物理信号）
  │   │     不依赖 ## NOTES 标题
  │   │
  │   ├─ [5] 逐章 mode 判定
  │   │     chapter_endnote_pages 非空 → chapter_endnote_primary（endnote优先）
  │   │     chapter_footnote_pages 非空 → footnote_primary
  │   │     book_endnote_pages 非空 → book_endnote_bound
  │   │     else → no_notes
  │   │
  │   └─ [6] book_type 判定
  │        has_footnote && has_endnote → mixed
  │        has_endnote → endnote_only
  │        has_footnote → footnote_only
  │
  ▼
Phase 2 (note_regions.py)
  │
  ├─ _build_endnote_regions_raw()
  │   ├─ _is_endnote_candidate_page:
  │   │   page_role=="note" → YES; 有notes_heading → YES; 有endnote scan items → YES
  │   │   ⚠️ fnBlocks 页面（有页底脚注）→ 跳过（除非被重分类）
  │   ├─ _endnote_scope_for_page:
  │   │   page > last_chapter_end → book scope; else chapter scope
  │   └─ 相邻同scope页面合并为 region
  │
  ├─ _build_footnote_band_regions()
  │   扫描每章中有 footnote scan items 的页面 → 合并为 footnote region
  │
  ▼
pipeline.py
  │
  └─ _build_chapter_note_modes()  从 region 证据最终确认
       footnote regions → footnote_primary
       chapter_endnote regions → chapter_endnote_primary
       book_endnote regions → book_endnote_bound
       冲突 → review_required
```

### 1.2 关键代码决策点与 LLM 发现对应

| 代码决策点 | 文件:行号 | 作用 | LLM 发现 |
|-----------|----------|------|---------|
| `toc_has_endnotes_entry` | `book_note_type.py:173` | TOC 是否有 Notes 条目 | Goldstein: TOC有，但页码偏移17页 |
| `_resolve_endnotes_start_page` | `toc_structure.py:17` | 读取 TOC 中 Notes 的 book_page | 返回值331不可信，实际Notes起始348 |
| `chapters_with_heading` 守卫 | `book_note_type.py:188-203` | 无TOC时，弱信号需章节锚点 | Germany_Madness: 正确丢弃了弱信号 |
| `_is_endnote_page` (弱信号) | `book_note_type.py:58-68` | ≥4编号定义 或 连续序列 | Germany_Madness p.129脚注136-137 匹配了编号定义模式 |
| `_chapter_has_consecutive_endnote_sequence` | `book_note_type.py:104-136` | 章末8页连续序列检测 | Biopolitics: 正确检测了无标题的章末尾注 |
| `has_footnote` 抑制 `has_endnote` | `book_note_type.py:229-230` | 同页有脚注时抑制尾注信号 | 正确行为 |
| 弱信号+无TOC守卫 | `book_note_type.py:231-238` | TOC无endnotes条目时丢弃弱信号 | Germany_Madness 和 Mad_Act 在此被正确拦截 |
| `_is_endnote_candidate_page` | `note_regions.py:130-151` | Phase2 尾注候选页判断 | note_detection scan 的误判会漏过来 |
| fnBlocks 页面守卫 | `note_regions.py:246-280` | 有页底脚注的页面不作为尾注候选 | 重要防线 |

---

## 二、四书在代码路径中的实际行为

### 2.1 Biopolitics（正确路径 ✅）

```
Phase 1:
  _rule_note_scan: 部分页 page_kind="endnote_collection" → role="note"
  _rule_notes_heading: 少量页有 ## NOTES 标题 → role="note"
  toc_has_endnotes_entry: False（TOC无Notes条目）
  chapters_with_heading: Ch1-Ch12 中的某些章有 endnote_collection 或 ## NOTES
  逐页扫描: 
    - 正文页: has_footnote=True（星号脚注在 raw markdown 中）
    - 章末尾注页: is_weak_endnote=True, 因章节在 chapters_with_heading 中 → has_endnote=True
    - 同页有 footnote+endnote → endnote 被抑制（正确，避免正文页被判为endnote）
  _chapter_has_consecutive_endnote_sequence: Ch1-Ch12 的章末8页检测到1..N连续序列
  per-chapter mode: 12章 chapter_endnote_primary, 2章 footnote_primary
  book_type: mixed ✅

Phase 2:
  note_regions: 章末尾注页 → chapter scope regions（marker 从1重新开始）
  footnote_band_regions: 每章正文页 → footnote regions

LLM 验证: mixed, chapter_end, confidence=high ✅ 与代码一致
```

### 2.2 Goldstein（正确 + TOC偏移问题 ⚠️）

```
Phase 1:
  toc_has_endnotes_entry: True（TOC 有 "Notes" at book_page=331）
  _resolve_endnotes_start_page: 返回 331
  chapters_with_heading: 不触发（toc_has_endnotes_entry=True，跳过第一遍扫描）
  逐页扫描:
    - 正文页: has_footnote=False（无脚注），has_endnote=False
    - p.348+: is_weak_endnote=True, toc_has_endnotes_entry=True → 保留
    - has_footnote=False → 不触发抑制
  per-chapter mode: 9章 book_endnote_bound
  book_type: endnote_only ✅

Phase 2:
  note_regions: p.348+ → book scope regions
  逐章 projection: 每个 chapter 的 endnote items 映射到各自 chapter

LLM 验证: endnote_only ✅
  ⚠️ 但 TOC 的 "Notes at p.331" 错误——LLM 看到 p.331 是正文（上标150-151）
  ⚠️ 真实 Notes 起始: p.348（偏移17页）
  ⚠️ LLM 误判 endnote_style 为 "book_end_continuous"（实际是 book_end_per_chapter，每章marker从1重新开始）
```

### 2.3 Germany_Madness（正确拦截 ✅）

```
Phase 1:
  toc_has_endnotes_entry: False（TOC不可用）
  chapters_with_heading: 空集（无 ## NOTES 标题页）
  逐页扫描:
    - 正文页: has_footnote=True（页底脚注数字）
    - p.129, 309等: _is_endnote_page 返回 True（高编号脚注136-137匹配 ≥4 编号定义模式）
    - 但 is_weak_endnote=True AND toc_has_endnotes_entry=False AND chapter不在chapters_with_heading中
    - → has_endnote=False ✅ 被守卫正确拦截！
  per-chapter mode: 全部 footnote_primary（因为章节未正确建立，走 heading graph）
  book_type: footnote_only ✅

Phase 2:
  但 note_detection scan 上游仍将部分页面标记为 endnote items
  → note_regions._is_endnote_candidate_page 返回 True（有 endnote scan items）
  → 少量 endnote region 被创建（p.129, 309, 321 共11条）

LLM 验证: footnote_only, confidence=high ✅
  关键发现: p.129有脚注136-137，p.309有脚注50-53——全部是页底脚注，非尾注
  11个"endnote" items 是 note_detection scan 的假阳性
```

### 2.4 Mad_Act（正确拦截 ✅）

```
Phase 1:
  toc_has_endnotes_entry: False
  chapters_with_heading: 空集
  逐页扫描:
    - 正文页: has_footnote=True
    - p.785-787: _is_endnote_page 返回 True（附录编号条目匹配模式）
    - 但守卫拦截 → has_endnote=False ✅
  book_type: footnote_only ✅

Phase 2:
  p.785-787 被 note_detection scan 标记为 endnote items
  → 1个 book_endnote region（10条items）

LLM 验证: footnote_only ✅
  p.785是 "Appendix 7"，法律条文翻译（292.16, 292.17），非学术尾注
  10个"endnote" items 是附录被误判
```

---

## 三、LLM 送检的实际价值——不是"替代规则"而是"交叉验证"

### 3.1 四书分类全部正确

经过实际送检，四本书的 Phase 1 规则判定（book_type）**全部正确**。LLM 在此起的是**验证**作用，不是纠正作用。

但 LLM 发现了三个规则系统**检测不到**的问题：

| # | 发现 | 规则能检测吗？ | 严重性 |
|---|------|--------------|--------|
| 1 | Goldstein TOC 页码偏移 17 页 | ❌ `_resolve_endnotes_start_page` 盲信 TOC，无交叉验证 | 中——如果下游用此页码定位 Notes 会错 |
| 2 | Germany_Madness 11条 "endnote" 是脚注假阳性 | ❌ 被 Phase 1 守卫正确拦截，但 Phase 2 仍从 scan 创建了 items | 低——book_type 正确，仅浪费少量计算 |
| 3 | Mad_Act 10条 "endnote" 是附录条文 | ❌ 同上，Phase 1 拦截但 Phase 2 未拦截 | 低——同上 |

### 3.2 真正需要 LLM 的场景

从四书数据看，LLM 在以下场景有不可替代的价值：

1. **TOC 页码验证**：当 TOC 说 "Notes at p.X"，LLM 看 p.X ± 偏移窗口确认。规则无法做这个判断——它没有视觉能力确认"这个页面是不是 Notes 区"。

2. **phase2 endnote items 假阳性清理**：Phase 1 的守卫（`toc_has_endnotes_entry` + `chapters_with_heading`）已经正确拦截了 Germany_Madness 和 Mad_Act，但 Phase 2 的 `note_regions` 仍从 note_detection scan 创建了假的 endnote items。LLM 可以在此做二次验证。

3. **极低比例的灰区书**：当 `footnote_items` 和 `endnote_items` 的比值在灰区（如 1:3 到 3:1），且无 TOC 锚定时，规则可能出错。但四书中未出现此情况。

---

## 四、LLM 必经验证方案

### 4.1 介入位置

```
Phase 1 (book_note_type.py) 运行完毕
  │
  ├─ book_type 已确定
  ├─ chapter_modes 已确定
  │
  ▼
  ┌──────────────────────────────────────────┐
  │ LLM 交叉验证层（必经，每本书都走）          │
  │                                          │
  │ 固定送检 7-11 页，不依赖触发条件            │
  │ 验证：book_type / TOC偏移 / 假阳性endnote  │
  │                                          │
  │ 产出: evidence 写入 gate_report           │
  │ 不一致 → soft flag 触发人工审核            │
  └──────────────────────────────────────────┘
  │
  ▼
Phase 2 (note_regions.py) 使用修正后的 TOC 偏移
```

### 4.2 结构驱动的送检规则

**送检量不由常数决定，而由书的结构参数决定。** 一本书有 14 章 + 12 个 endnote region，和另一本书只有 1 章 + 0 个 endnote region，送检量不可能相同。

#### 结构参数提取

送检前先从 Phase 1 产出中提取以下结构参数：

```python
@dataclass
class BookStructureProfile:
    """从 Phase 1 产出提取的结构参数，决定送检量。"""
    total_pages: int                    # 总页数
    
    # 章节
    chapter_count: int                  # 章总数
    chapter_modes: dict[str, str]       # {chapter_id: note_mode}
    
    # Endnote region（Phase 1 已检测）
    endnote_region_count: int           # endnote region 总数
    endnote_regions: list[EndnoteRegionInfo]  # 每个 region 的详情
    chapter_endnote_count: int          # scope=chapter 的 region 数
    book_endnote_count: int             # scope=book 的 region 数
    
    # Item 统计
    endnote_item_count: int             # endnote item 总数
    footnote_item_count: int            # footnote item 总数
    
    # TOC
    toc_has_notes_entry: bool           # TOC 中是否有 Notes/Endnotes 条目
    toc_notes_printed_page: int | None  # TOC 声称的 Notes 所在印刷页码
    
    # 模式分布
    mode_types: set[str]                # 出现了哪些 chapter_mode 类型
    # e.g. {"chapter_endnote_primary", "footnote_primary", "book_endnote_bound"}


@dataclass
class EndnoteRegionInfo:
    chapter_id: str
    scope: str              # "chapter" | "book"
    start_page: int         # region 第一页 (PDF页码)
    end_page: int           # region 最后一页
    page_count: int         # region 页数
    chapter_start_page: int # 所属章的起始页
    chapter_end_page: int   # 所属章的结束页
```

#### 送检规则（五条，由结构参数驱动）

```python
def select_verification_pages(profile: BookStructureProfile) -> list[int]:
    """由书的结构参数决定送检页面。"""
    pages: list[int] = []
    
    # ═══ 规则1: TOC 页（1页，每本书必有）═══
    pages.append(_toc_page(profile))
    
    # ═══ 规则2: 正文基线 ═══
    # 每出现一种 chapter_mode 类型，取 1 页代表正文。
    # 最少 2 页，分散在书的前、中、后部。
    pages.extend(_body_baseline_pages(profile))
    
    # ═══ 规则3: 章末边界（由 endnote region 数决定） ═══
    # 这是送检量的主要变量。
    # 对 scope=chapter 的 region，取 transition（末页正文 + 第一条注释）
    # 抽样率：ceil(region数 × 0.3)，最少 3 个 region，最多 15 个
    pages.extend(_chapter_end_boundary_pages(profile))
    
    # ═══ 规则4: 全书 Notes 区（book scope region 专用）═══
    # 对 scope=book 的 region，不存在"章末边界"
    # 改为验证 Notes 区的起始和内部
    pages.extend(_book_notes_region_pages(profile))
    
    # ═══ 规则5: TOC Notes 偏移验证 ═══
    # 仅当 TOC 声称有 Notes 条目时触发
    pages.extend(_toc_offset_verification_pages(profile))
    
    # ═══ 规则6: 假阳性嫌疑页验证 ═══
    # 仅当 endnote item 极少（< 50）且存在时触发
    pages.extend(_false_positive_check_pages(profile))
    
    # 去重排序，总量上限 = min(10% × total_pages, 40页)
    cap = min(int(profile.total_pages * 0.10), 40)
    return sorted(set(pages))[:cap]
```

#### 各规则的详细逻辑

**规则2：正文基线**

```python
def _body_baseline_pages(p: BookStructureProfile) -> list[int]:
    modes = p.mode_types  # 出现了哪些 chapter_mode
    pages = []
    # 每种 mode 取 1 个代表章的中页
    for mode in modes:
        ch = _pick_representative_chapter(p, mode)
        pages.append(_mid_body_page(ch))
    # 最少 2 页
    while len(pages) < 2:
        # 从还没取过的章补
        ...
    return pages[:max(2, len(modes))]
```

**规则3：章末边界（送检量的主要变量）**

```python
def _chapter_end_boundary_pages(p: BookStructureProfile) -> list[int]:
    """抽样率 30%，最少 3 个 region，最多 15 个。"""
    chapter_regions = [r for r in p.endnote_regions if r.scope == "chapter"]
    if not chapter_regions:
        return []  # 此书没有章末尾注区
    
    # 抽样：ceil(N × 0.3)，最少 3，最多 15
    n = len(chapter_regions)
    sample_n = max(3, min(15, int(math.ceil(n * 0.3))))
    
    # 分散取样：在 region 列表中等间距选取
    sampled = _distributed_sample(chapter_regions, sample_n)
    
    pages = []
    for region in sampled:
        # 末页正文（region 开始前 1 页）
        last_body = region.start_page - 1
        if last_body >= region.chapter_start_page:
            pages.append(last_body)
        # 第一条注释（region 第一页）
        pages.append(region.start_page)
        # region ≥ 3 页时，加一页中间注释
        if region.page_count >= 3:
            pages.append(region.start_page + region.page_count // 2)
    
    return pages
```

**规则4：全书 Notes 区**

```python
def _book_notes_region_pages(p: BookStructureProfile) -> list[int]:
    """book scope 的 region：验证 Notes 起始 + 中间。"""
    book_regions = [r for r in p.endnote_regions if r.scope == "book"]
    if not book_regions:
        return []
    
    pages = []
    for region in book_regions:
        # Notes 起始前 1 页（看过渡）
        pages.append(max(1, region.start_page - 1))
        # Notes 第一页
        pages.append(region.start_page)
        # Notes 中间页
        if region.page_count >= 5:
            pages.append(region.start_page + region.page_count // 2)
    
    return pages
```

**规则5：TOC Notes 偏移验证**

```python
def _toc_offset_verification_pages(p: BookStructureProfile) -> list[int]:
    if not p.toc_has_notes_entry or not p.toc_notes_printed_page:
        return []
    
    toc_claimed = p.toc_notes_printed_page  # TOC 声称的印刷页码
    # pipeline 检测到的第一条 endnote 所在 PDF 页码
    pipeline_first = _first_endnote_page(p)
    
    if not pipeline_first:
        return [toc_claimed]  # 只送 TOC 声称页
    
    offset = pipeline_first - toc_claimed  # 偏移量
    
    return [
        toc_claimed,               # 不加偏移（对照：TOC盲信）
        pipeline_first - 2,        # 偏移-2（过渡检查）
        pipeline_first,            # 加偏移（pipeline检测）
        pipeline_first + 5,        # 偏移+5（确认在Notes区内）
    ]
```

**规则6：假阳性嫌疑**

```python
def _false_positive_check_pages(p: BookStructureProfile) -> list[int]:
    """endnote items < 50 且 > 0 → 可能是误判（高编号脚注、附录条文）。"""
    if not (0 < p.endnote_item_count < 50):
        return []
    
    # 取所有 endnote item 所在页面（去重，最多 5 页）
    endnote_pages = _pages_with_endnote_items(p)
    return sorted(set(endnote_pages))[:5]
```


#### 四书按结构驱动的送检量

**Biopolitics**（370页，14章，12个 scope=chapter 的 endnote region）

| 规则 | 计算过程 | 送检页 | 说明 |
|------|---------|--------|------|
| 规则1 TOC | 固定 | 1 | TOC页 |
| 规则2 正文基线 | 2种mode (chapter_endnote_primary, footnote_primary) | 2 | Ch3中页 + Ch13中页 |
| 规则3 章末边界 | ceil(12 × 0.3) = 4个region抽样 | 8 | Ch1/Ch4/Ch8/Ch12，每区末页正文+首页注释 |
| 规则4 全书Notes | 0个book scope region | 0 | — |
| 规则5 TOC偏移 | TOC无Notes条目 | 0 | — |
| 规则6 假阳性 | 480 endnote items，不触发 | 0 | — |
| **合计** | | **11** | **3.0%** |

**Goldstein**（431页，9章，0个 scope=chapter 的 region，9个 scope=book 的 region）

| 规则 | 计算过程 | 送检页 | 说明 |
|------|---------|--------|------|
| 规则1 TOC | 固定 | 1 | TOC页 |
| 规则2 正文基线 | 1种mode (book_endnote_bound) → 最少2页 | 2 | Ch4中页 + Ch7中页 |
| 规则3 章末边界 | 0个chapter scope region | 0 | — |
| 规则4 全书Notes | 9个book scope region → 合并为1个连续Notes区 | 3 | Notes前1页 + 首页(p.348) + 中间(p.380) |
| 规则5 TOC偏移 | TOC Notes at p.331, pipeline_at p.348, offset=17 | 4 | p.331, p.346, p.348, p.353 |
| 规则6 假阳性 | 921 endnote items，不触发 | 0 | — |
| **合计** | | **10** | **2.3%** |

**Germany_Madness**（464页，章节结构不可用，0个 endnote region）

| 规则 | 计算过程 | 送检页 | 说明 |
|------|---------|--------|------|
| 规则1 TOC | TOC不可用→取卷首页 | 1 | p.2 |
| 规则2 正文基线 | 1种mode (footnote_primary) → 最少2页 | 3 | p.100, p.250, p.400（早中晚） |
| 规则3 章末边界 | 0个endnote region | 0 | — |
| 规则4 全书Notes | 0个book scope region | 0 | — |
| 规则5 TOC偏移 | TOC不可用 | 0 | — |
| 规则6 假阳性 | 11 endnote items (< 50) | 3 | p.129, p.309, p.321 |
| **合计** | | **7** | **1.5%** |

**Mad_Act**（824页，1章，0个 chapter scope，1个 book scope region）

| 规则 | 计算过程 | 送检页 | 说明 |
|------|---------|--------|------|
| 规则1 TOC | 固定 | 1 | TOC页 |
| 规则2 正文基线 | 1种mode (footnote_primary) → 最少2页 | 2 | p.200, p.500 |
| 规则3 章末边界 | 0个chapter scope region | 0 | — |
| 规则4 全书Notes | 1个book scope region (p.785-787) | 3 | p.784, p.785, p.787 |
| 规则5 TOC偏移 | TOC无Notes条目 | 0 | — |
| 规则6 假阳性 | 10 endnote items (< 50) | 3 | p.785, p.786, p.787（与规则4部分重叠） |
| **去重后合计** | | **7** | **0.8%** |

#### 送检量对比：结构驱动 vs 固定公式

| 书 | 结构参数 | 固定公式 | **结构驱动** | 差异原因 |
|----|---------|---------|------------|---------|
| Biopolitics | 14章/12 region | 9 | **11** | region 多→章末边界送检增加 |
| Goldstein | 9章/book scope | 11 | **10** | book scope 不需逐章边界，改为 Notes 区验证 |
| Germany_Madness | 0章/0 region | 7 | **7** | 结构简单，两者接近 |
| Mad_Act | 1章/1 region | 7 | **7** | 结构简单，两者接近 |

结构驱动的关键差异在于：**Biopolitics 因 12 个 chapter scope region 而增加章末边界送检，Goldstein 因全是 book scope 而改用 Notes 区验证替代逐章边界。** 这反映了两种完全不同的尾注组织方式，固定公式无法区分。

### 4.3 内容审核拒绝的换页策略

Biopolitics 第一次送检被拒绝（"high risk"），第二次用英文 prompt 通过。

```python
def verify_with_retry(images, prompt, pdf_path, page_list):
    """送检 + 审核拒绝时换页重试。"""
    # 尝试1: 英文中性 prompt
    result = call_vision_llm(images, prompt=ENGLISH_PROMPT)
    if not result.rejected:
        return result
    
    # 尝试2: 换掉可能触发审核的页面（前后 ±2 页）
    alt_pages = [p + offset for p in page_list for offset in (-2, 2)]
    result = call_vision_llm(render_pages(pdf_path, alt_pages), prompt=ENGLISH_PROMPT)
    if not result.rejected:
        return result
    
    # 尝试3: 再换一批（±1, ±3 页）
    alt_pages_2 = [p + offset for p in page_list for offset in (-1, 3)]
    result = call_vision_llm(render_pages(pdf_path, alt_pages_2), prompt=ENGLISH_PROMPT)
    if not result.rejected:
        return result
    
    # 三次都不行：信任规则判定，记录告警
    return {"error": "content_filter_rejected_3_attempts", "fallback": "trust_rules"}
```

审核拒绝率预估：8 本书仅 Biopolitics 第一次被拒（1/8），第二次通过。预计 < 5% 的页面需要换页。

### 4.4 总成本估算

| 书 | 送检页 | 占比 | 预估 token | 备注 |
|----|--------|------|-----------|------|
| Biopolitics | 11 | 3.0% | ~6,000 | 12 region × 30% = 4 章边界 |
| Goldstein | 10 | 2.3% | ~7,000 | book scope → Notes 区验证 + TOC 偏移 |
| Germany_Madness | 7 | 1.5% | ~15,000 | 大页面降分辨率后 |
| Mad_Act | 7 | 0.8% | ~6,000 | 假阳性 + 附录验证 |

单书：6,000-15,000 tokens（大页面降分辨率后）
8 书批次：约 50,000-70,000 tokens，为当前 llm_repair（190K）的 25-35%

---

## 五、与当前 pipeline 的集成方式

### 5.1 插入位置

不修改 Phase 1/Phase 2 核心逻辑，在中间插入一个必经验证模块：

```python
# pipeline.py 中新增（Phase 1 完成后、Phase 2 开始前）
book_type_result = build_book_note_profile(...)

# === 新增：LLM 交叉验证（必经步骤）===
llm_report = verify_book_type_with_llm(
    book_type=book_type_result.data,
    toc_structure=toc_structure,
    pages=pages,
    pdf_path=pdf_path,
    sample_pages=select_verification_pages(...),  # 结构驱动选页
)
book_type_result.gate_report.evidence["llm_verification"] = llm_report
# =================================
```

### 5.2 LLM 产出的使用方式

保持树状原则——LLM 不直接修改任何上游决策：

1. **一致时**：`confidence: high` → 记录到 evidence，增强 gate 置信度
2. **不一致时**：写入 `gate_report.soft["llm_disagreement"]`，触发人工审核，但 Phase 2 仍按规则结果继续
3. **TOC 偏移修正**：写入 `evidence["toc_offset_corrected"]`，下游 `_resolve_endnotes_start_page` 读取修正值
4. **假阳性标记**：写入 `evidence["suspected_false_positive_pages"]`，Phase 2 的 `note_regions` 可以据此过滤掉假 endnote 候选页

### 5.3 LLM 调用的技术参数

基于实际送检踩坑经验：

- **max_tokens**: ≥ 4000（mimo-v2.5 消耗约 80% 为 reasoning_tokens，1000 只够推理无输出）
- **页面数上限**: 12 页/次（当前 7-11 页方案在此范围内）
- **渲染分辨率**: 默认；大页面书（2MB+/页）降为 50% 分辨率
- **Prompt**: 英语、中性描述、三层结构（全书体系 / 尾注组织 / 逐页证据）、要求 JSON 输出
- **审核拒绝**: 英文 prompt → 换页 ±2 → 换页 ±3 → 放弃（信任规则）

---

## 六、总结

### 核心结论

1. **Phase 1 规则系统在四本书上全部正确**。但"全部正确"是基于四本已知书的统计——下一本新书是否会暴露新盲区，无法预知。因此 **LLM 验证必须是必经步骤**。

2. **规则盲区有三个**：
   - TOC 页码偏移（Goldstein：17 页偏差）
   - Phase 2 假阳性 endnote items（Germany_Madness: 11 条高编号脚注，Mad_Act: 10 条附录条文）
   - 灰区比值时的分类不确定性（Biopolitics: 480 vs 112）

3. **LLM 送检为必经步骤，送检量由书的结构参数决定**：章节数、endnote region 数和 scope、TOC Notes 条目、endnote item 数量。简单书（Mad_Act，1章，0 chapter region）送 7 页，复杂书（Biopolitics，14章，12 chapter region）送 11 页。8 书批次约 50-70 页，8 次 LLM 调用，约 50K-70K tokens。

4. **树状原则不受影响**：LLM 验证在 Phase 1 和 Phase 2 之间插入，产出写入 `gate_report.evidence`，不修改上游 book_type，不一致时触发人工审核而非自动覆盖。

5. **审核拒绝有换页策略**：英文 prompt → ±2 页 → ±3 页 → 放弃信任规则。预计 < 5% 触发换页。

### 数据处理经验

- **mimo-v2.5 模型的 reasoning_tokens 占 max_tokens 的 80%**，需设 max_tokens ≥ 4000
- **大页面（2MB+）消耗 40K image tokens**，需控制渲染分辨率
- **内容审核可能拒绝政治哲学类文本**，需准备中性 prompt 作为备选
- **LLM 对 endnote_style 的细粒度判断不够精确**（将 book_end_per_chapter 误判为 continuous），此字段不应作为 pipeline 输入，仅供参考
