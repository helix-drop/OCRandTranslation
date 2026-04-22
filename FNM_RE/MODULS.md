# MODULS（FNM_RE 模块化重构总纲）

本文件是 `FNM_RE/` 后续重构的唯一口径。

目标不是把 `phase1~phase6` 改名，而是把当前“阶段堆叠 + 到处补丁”的实现，收敛成：

1. 流程清楚：7 个业务模块按单向流水线串联。
2. 结构清楚：每个模块内部再拆成树状子节点，额外处理有明确归属。
3. 责任清楚：每个判断只在一个模块里发生，不跨层反复推断。
4. 校验清楚：每个模块都有自己的 `gate`，`status.py` 只汇总，不反向脑补。
5. 债务清楚：历史修补逻辑必须显式挂到某个子节点，不能“迁移时顺手丢掉”。

---

## 1. 总体原则

### 1.1 业务原则

1. 7 步业务流程 = 7 个业务模块。
2. 模块只做业务判断，不做 repo 读写，不依赖 `doc_id`。
3. 模块之间只传“真相对象”，不传松散 dict 拼装结果。
4. 一个判断只允许有一个归属模块；禁止在后续模块重新推翻前序真相。
5. 历史修补逻辑可以保留，但必须写明“归谁管、何时触发、改变什么”。

### 1.2 工程原则

1. 不保留长期双轨。
2. 允许迁移批次内存在临时适配层，但该批次结束前必须删除。
3. 先冻结边界合同，再做模块内重排。
4. 文档中的 gate 名称，就是 `status.py` 的正式字段前缀来源。

### 1.3 本次重构真正想解决的问题

当前问题不是“函数太长”这么简单，而是：

- 页面角色、目录角色、章节边界、注释区边界、导出兜底，散落在多个阶段重复判断。
- 同一类异常会在 `page_partition / note_regions / units / export / status` 多处被补。
- `status.py` 里同时承担了“汇总结果”和“反推业务事实”的职责。
- 运行时对象、持久化对象、导出对象彼此缠绕，导致一改就全链受影响。

所以本方案的核心，不是追求“小改”，而是把流程和职责一次理顺。

---

## 2. 总体边界

### 2.1 三层边界

#### A. 纯业务模块层

位置目标：`FNM_RE/modules/`

职责：

- 接收上游真相对象。
- 产出下游真相对象。
- 产出本模块 `gate_report`。
- 记录本模块使用的 override 和证据。

禁止：

- 读写 SQLite。
- 读取 `doc_id` 相关 repo 状态。
- 直接操作 `pipeline_state`。
- 修改上游对象本身。

#### B. 运行态投影层

位置目标：`FNM_RE/app/` 内的纯投影 helper，必要时可拆 `runtime_projection.py`

职责：

- 把业务对象投影成当前 worker / diagnostic / export 仍需使用的形状。
- 叠加 repo 里的历史翻译结果。
- 维持当前翻译 worker 所需的 `unit` 合同。

禁止：

- 新增业务判断。
- 用 repo 数据推翻纯业务模块已经产出的事实。

#### C. doc/repo 接线层

位置保持：`FNM_RE/app/mainline.py`

职责：

- 目录来源解析。
- manual 输入解析。
- repo 读写。
- run 状态写回。
- 调度 7 个模块。

禁止：

- 直接做章节、注释、链接、导出语义判断。

### 2.2 模块统一返回协议

每个模块必须返回：

```python
ModuleResult[
    data,              # 本模块真相对象
    gate_report,       # 本模块 gate 结果
    evidence,          # 本模块关键证据摘要
    overrides_used,    # 本模块实际使用的人工覆写
    diagnostics,       # 非阻塞调试信息
]
```

### 2.3 Gate 统一协议

每个模块的 `gate_report` 统一包含：

```python
GateReport(
    module="toc|book_type|split|link|freeze|merge|export",
    hard={},           # 必须通过；失败即阻塞
    soft={},           # 可提示；默认不阻塞
    reasons=[],        # 标准化原因码
    evidence={},       # 支撑 gate 的证据摘要
    overrides_used=[], # 具体用了哪些 override
)
```

规则：

1. `status.py` 只汇总 `GateReport`，不再自己逆向推断业务事实。
2. `blocking_reasons` 只来自各模块 `hard=false` 的原因码。
3. `soft` 结果进入 review/hints，不直接阻塞。
4. 所有 override 都必须写进 `overrides_used`，避免“静默放行”。

### 2.4 Override 统一协议

只允许三类 override：

1. `page_override`
   用于页面角色、页面归属修正。
2. `link_override`
   用于注释链接强制 `match` 或 `ignore`。
3. `gate_override`
   用于显式放行某个 hard gate。

要求：

- override 必须精确到对象 id。
- override 必须带原因。
- override 只能放行，不得隐藏原始证据。
- `status.py` 必须能显示“此结果由 override 放行”。

### 2.5 当前必须冻结的边界合同

在迁移完成前，下列合同先保持不变：

1. FNM 翻译 worker 仍吃当前 `TranslationUnit` 形状。
   关键字段：`kind / owner_kind / owner_id / section_id / section_title / note_id / page_segments / target_ref`
2. repo 持久化入口仍由 `replace_fnm_structure()` 与 `replace_fnm_data()` 写回。
3. 诊断层仍可由现有 `page_translate.py` 和 `diagnostics.py` 消费投影后的 unit。
4. SQLite 表第一轮不因模块重排而强改语义。

含义：

- 我们可以重写业务对象。
- 但迁移中间态必须提供“业务对象 -> 现有 worker/repo 形状”的投影层。
- 否则会把结构重构和运行链路重构绑死在一轮里，风险过高。

---

## 3. 统一词汇

### 3.1 对外页面/目录角色

| 角色 | 含义 |
|---|---|
| `front_matter` | 前述材料：封面、版权、前言、目录本身、课程列表等 |
| `container` | 上层结构壳子：Part / Book / Section 级目录节点，本身不作为翻译单章 |
| `chapter` | 真正的正文章节，翻译与导出的基本单位 |
| `post_body` | 正文后的正式章节化内容，如总结、后记、索引导言 |
| `back_matter` | 参考文献、索引、附录、作者简介、广告页等 |

说明：

- `noise` 只允许作为模块内部技术标签存在。
- `noise` 不允许出现在对外真相对象或对外状态字段中。

### 3.2 书型

| 书型 | 含义 |
|---|---|
| `mixed` | 脚注 + 尾注混合 |
| `endnote_only` | 仅尾注 |
| `footnote_only` | 仅脚注，需要导出为统一尾注区 |
| `no_notes` | 无注释 |

### 3.3 继续保留的底层枚举

保留现有：

- `NoteKind`
- `RegionScope`
- `RegionSource`
- `NoteMode`
- `AnchorKind`
- `LinkStatus`
- `LinkResolver`

新增：

- `BookNoteType`

下线：

- `PageRole` 对外暴露中的 `noise`

---

## 4. 七个模块

---

## 4.1 模块一：`toc_structure`

职责：把“页面角色 + 目录结构 + 章节骨架 + section heads”一次收口。

### 4.1.1 树状拆分

```text
toc_structure
├─ 1A page_role_tagging
│  ├─ 页面基础角色判定
│  ├─ front/back 连续段修正
│  ├─ 注释延续页修正
│  └─ manual page override
├─ 1B toc_role_projection
│  ├─ TOC 行归类为 container/chapter/post_body/back_matter
│  └─ non-body 项剔除与摘要
├─ 1C chapter_skeleton
│  ├─ visual_toc 主路
│  ├─ heading-only reanchor
│  ├─ chapter level 选择与错级兜底
│  └─ fallback skeleton
└─ 1D section_head_binding
   ├─ 多来源标题候选采集
   ├─ section head 绑定
   └─ 章内标题摘要
```

### 4.1.2 输入

- `pages`
- 统一形状的 `toc_items`
- 可选 `manual_page_overrides`

### 4.1.3 输出

`TocStructure`

- `pages`
  - `page_no`
  - `external_role`
  - `internal_tags`
  - `reason_codes`
- `toc_tree`
- `chapters`
- `section_heads`
- `role_summary`

### 4.1.4 关键判断

1. 页面必须先归“外部角色”，再保留内部技术标签。
2. 章节骨架以 `visual_toc` 为主证据，页内弱证据只能补边界，不能推翻主骨架。
3. `container` 与 `chapter` 必须分开建模，不能再混为一个“章节列表”。
4. `back_matter` 一旦开始，默认不再接受新的 `chapter`，除非 explicit override。

### 4.1.5 必须继承的历史修补

#### 归 `1A page_role_tagging`

- `page_partition.py`
  - `_rule_archive_noise`
  - `_rule_early_course_listing`
  - `_rule_copyright_front_matter`
  - `_rule_early_other_list`
  - `_rule_rear_toc_tail`
  - `_rule_rear_author_blurb`
  - `_rule_rear_sparse_other`
  - `_rule_title_page`
  - `_rule_title_family`
  - `_rule_blank_front_page`
  - `_apply_front_matter_continuation_fix`
  - `_apply_note_continuation_fix`
  - `_apply_manual_overrides`

#### 归 `1C chapter_skeleton`

- `chapter_skeleton.py`
  - `_looks_like_lecture_collection`
  - `_build_lecture_collection_chapter_rows`
  - `_is_misleveled_chapter_row`
  - `_choose_visual_toc_chapter_level`
  - `_resolve_visual_toc_page_by_heading_only`
  - `_infer_back_matter_start_page`
  - `_trim_chapter_rows`
  - `_trim_exportable_chapter_pages`
  - `_dedupe_visual_toc_rows`
  - `_classify_fallback_sections`
  - `_build_fallback_chapters_and_sections`

#### 归 `1D section_head_binding`

- `chapter_skeleton.py`
  - `_collect_toc_heading_candidates`
  - `_collect_pdf_font_band_candidates`
- `section_heads.py`
  - 现有全部 section head 生成与去伪逻辑

### 4.1.6 Gate

#### Hard

- `toc.pages_classified`
  每页必须有且仅有一个外部角色。
- `toc.has_exportable_chapters`
  `chapter` 数必须大于 0。
- `toc.chapter_titles_aligned`
  不残留当前意义上的 `toc_chapter_title_mismatch`。
- `toc.chapter_order_monotonic`
  目录顺序与章节 `start_page` 单调一致。
- `toc.role_semantics_valid`
  `front_matter -> container/chapter -> post_body/back_matter` 的相邻关系合法。

#### Soft

- `toc.section_alignment_warn`
  section heads 对齐不充分，但不阻塞。
- `toc.visual_toc_conflict_warn`
  visual toc 内部存在冲突或重锚。

### 4.1.7 非职责

- 不判定书型。
- 不切正文/注释。
- 不做链接。
- 不做导出顺序。

---

## 4.2 模块二：`book_note_type`

职责：把“全书书型”与“每章 note mode”单独收口。

### 4.2.1 树状拆分

```text
book_note_type
├─ 2A note_evidence_scan
│  ├─ TOC notes 词命中
│  ├─ 章末 notes heading 命中
│  └─ footnote band marker 命中
├─ 2B book_type_resolution
│  ├─ mixed
│  ├─ endnote_only
│  ├─ footnote_only
│  └─ no_notes
└─ 2C chapter_mode_projection
   ├─ 章级 primary mode
   ├─ conflict 检测
   └─ review_required 降级
```

### 4.2.2 输入

- `TocStructure`
- `pages`

### 4.2.3 输出

`BookNoteProfile`

- `book_type`
- `chapter_note_modes`
- `evidence_summary`

### 4.2.4 关键判断

1. 先出全书 `book_type`，再约束章级 `note_mode`。
2. `review_required` 是显式结果，不允许用“unknown”糊过去。
3. 证据不足时可以降级为 `review_required`，但不能默认放行。

### 4.2.5 必须继承的历史修补

#### 归 `2A note_evidence_scan`

- `shared/notes.py`
  - `is_notes_heading_line`
  - `normalize_note_marker`
  - `extract_pdf_text_by_page`
- `note_regions.py`
  - heading scan 信号采集
  - footnote band 信号采集

#### 归 `2C chapter_mode_projection`

- `app/pipeline.py`
  - `_build_chapter_note_modes`

### 4.2.6 Gate

#### Hard

- `book_type.resolved`
  `book_type` 必须属于 `{mixed, endnote_only, footnote_only, no_notes}`。
- `book_type.chapter_modes_consistent`
  章级 `note_mode` 汇总不得与全书书型冲突。
- `book_type.no_unapproved_review_required`
  所有 `review_required` 章节都必须由 explicit override 解释，否则阻塞。

#### Soft

- `book_type.low_confidence_warn`
  书型由弱证据决出。

### 4.2.7 非职责

- 不做注释区切分。
- 不抽 note items。
- 不改正文呈现策略。

---

## 4.3 模块三：`chapter_split`

职责：把“章内正文层”和“章内注释层”彻底拆清，并明确不同书型的处理策略。

### 4.3.1 树状拆分

```text
chapter_split
├─ 3A note_region_binding
│  ├─ footnote band regions
│  ├─ chapter endnote regions
│  ├─ book endnote regions
│  ├─ region merge/split/promote/rebind
│  └─ region id normalize
├─ 3B note_item_extraction
│  ├─ structured scan
│  ├─ page text fallback
│  ├─ pdf text fallback
│  └─ 去重与顺序规范化
├─ 3C body_page_split
│  ├─ chapter 起始页切线
│  ├─ note heading 切线
│  ├─ gap page 清理
│  ├─ trailing note block 剥离
│  └─ 跨页段落连续化
└─ 3D note_materialization_policy
   ├─ no_notes: 直通
   ├─ mixed: 脚注保留在正文尾部并打 [脚注]
   ├─ endnote_only: 保持章级/书级尾注层
   └─ footnote_only: 脚注抽出并合成统一尾注区
```

### 4.3.2 输入

- `TocStructure`
- `BookNoteProfile`
- `pages`

### 4.3.3 输出

`ChapterLayers`

- `chapters[]`
  - `chapter_id`
  - `headings`
  - `body_pages`
  - `body_segments`
  - `footnote_items`
  - `endnote_items`
  - `endnote_regions`
  - `policy_applied`
- `region_summary`
- `item_summary`

### 4.3.4 关键判断

1. “正文/注释切线”只允许在这里发生。
2. `mixed` 与 `footnote_only` 是不同策略，不允许靠导出层再兜。
3. `footnote_only` 的“脚注转尾注”是业务动作，不是导出小修补。
4. 同页正文与注释必须变成两个显式层，不能再靠后续模块猜。

### 4.3.5 必须继承的历史修补

#### 归 `3A note_region_binding`

- `note_regions.py`
  - `_build_footnote_band_regions`
  - `_promote_post_body_regions`
  - `_merge_adjacent_endnote_regions`
  - `_split_book_regions_by_heading`
  - `_rebind_book_regions`
  - `_normalize_region_ids`

#### 归 `3B note_item_extraction`

- `note_items.py`
  - structured scan / page text / pdf text 三级提取链
  - `_dedupe_region_items`

#### 归 `3C body_page_split`

- `units.py`
  - `_extract_note_heading_split`
  - `_split_page_text_by_chapter_heading`
  - `_split_page_text_at_first_heading`
  - `_trim_trailing_markdown_note_block`
  - `_sanitize_gap_page_prefix`
  - `_synthetic_markdown_pages`
  - `_build_structured_body_pages_for_chapter`
  - `_segment_paragraphs_from_body_pages`
  - `_chunk_body_page_segments`

#### 归 `3D note_materialization_policy`

- 新增，当前代码未完整实现：
  - `mixed` 书脚注追加 `[脚注]`
  - `footnote_only` 书脚注抽出为统一尾注区并从 `1` 重新编号

### 4.3.6 Gate

#### Hard

- `split.regions_bound`
  所有需要的注释区都已绑定到章节或书级容器。
- `split.items_extracted`
  每个非空 region 都必须产出 note items，除非 explicit override。
- `split.body_note_disjoint`
  同页正文层与注释层不得重叠。
- `split.cross_page_continuity_ok`
  跨页段落连续性无明显截断。
- `split.policy_applied`
  每章必须明确记录 `policy_applied`。
- `split.footnote_only_synthesized`
  `footnote_only` 书的统一尾注区编号必须从 `1` 连续。
- `split.mixed_marker_materialized`
  `mixed` 书保留在正文中的脚注必须显式带 `[脚注]`。

#### Soft

- `split.char_drop_warn`
  页面切分后字符量明显减少，需要人工抽查。

### 4.3.7 非职责

- 不做正文 anchor 匹配。
- 不决定哪些 link 可冻结。
- 不生成最终导出 markdown。

---

## 4.4 模块四：`note_linking`

职责：把正文 anchor 与注释条目链接起来，并对“本章尾注是否真的闭合”做硬判断。

### 4.4.1 树状拆分

```text
note_linking
├─ 4A anchor_collection
│  ├─ markdown 段落扫描
│  ├─ OCR block 扫描
│  └─ year-marker 过滤
├─ 4B direct_match
│  ├─ 同 marker 直连
│  └─ 同章范围约束
├─ 4C repair_match
│  ├─ OCR repair
│  ├─ ordered-subsequence
│  ├─ nearest unique candidate
│  └─ synthetic anchor
└─ 4D chapter_link_contract
   ├─ 章级 endnote contract
   ├─ orphan/ambiguous 汇总
   └─ override 放行记录
```

### 4.4.2 输入

- `ChapterLayers`
- `pages`（原始页 payload，用于 anchor 扫描）

### 4.4.3 输出

`NoteLinkTable`

- `anchors`
- `links`
- `chapter_link_contracts`
- `link_summary`

### 4.4.4 关键判断

1. 先做直接匹配，再做修补匹配，最后才允许 synthetic anchor。
2. synthetic anchor 只能作为显式修补结果存在，不能伪装成正常命中。
3. 本模块只判断“链接是否成立”，不再承担 TOC 或导出语义审计。
4. 章级 contract 只对“需要形成本章尾注闭合”的章节生效。

### 4.4.5 必须继承的历史修补

#### 归 `4A anchor_collection`

- `shared/anchors.py`
  - `looks_like_year_marker`
  - `resolve_anchor_kind`
  - `page_body_paragraphs`
  - `scan_anchor_markers`
- `body_anchors.py`
  - `footnote band` 页键去重

#### 归 `4C repair_match`

- `note_links.py`
  - `_marker_digits_are_ordered_subsequence`
  - `_within_footnote_window`
  - `_nearest_unique_candidate`
  - `_make_synthetic_anchor`
  - resolver 三级链：`rule / fallback / repair`
  - `_infer_note_kind_from_anchor`
  - `_is_fallback_chapter_id`
  - `_is_toc_chapter_id`

### 4.4.6 Gate

#### Hard

对“需要形成章级尾注闭合”的章节，以下必须全部为真：

- `link.first_marker_is_one`
  首条 marker 必须为 `1`，除非 explicit override。
- `link.endnotes_all_matched`
  该章尾注条目全部命中正文 anchor。
- `link.no_ambiguous_left`
  不得残留 `ambiguous`，除非 `link_override=match`。
- `link.no_orphan_note`
  不得残留 `orphan_note`。
- `link.endnote_only_no_orphan_anchor`
  若全书为 `endnote_only`，则 `orphan_anchor` 也必须为 `0`。

#### Soft

- `link.footnote_orphan_anchor_warn`
  对非 `endnote_only` 书，少量 `orphan_anchor` 只提示。
- `link.synthetic_anchor_warn`
  存在 synthetic anchor，需要抽查。

### 4.4.7 非职责

- 不冻结引用。
- 不重写正文文本。
- 不做导出本地脚注编号。

---

## 4.5 模块五：`ref_freeze`

职责：只冻结可以安全冻结的正文引用，并同时产出翻译 worker 继续使用的 unit 规划。

### 4.5.1 树状拆分

```text
ref_freeze
├─ 5A freezable_link_selection
│  ├─ 仅选 matched
│  ├─ 跳过 ambiguous/orphan/ignored
│  └─ 跳过 synthetic/conflict anchors
├─ 5B token_injection
│  ├─ NOTE_REF 注入
│  ├─ 同位置防二次注入
│  └─ 同页排序确定化
├─ 5C translation_unit_planning
│  ├─ body units
│  ├─ note units
│  └─ 兼容当前 worker 的 unit 合同
└─ 5D freeze_audit
   ├─ 注入记账
   ├─ skip reason 记账
   └─ token 稳定性检查
```

### 4.5.2 输入

- `ChapterLayers`
- `NoteLinkTable`

### 4.5.3 输出

`FrozenUnits`

- `body_units`
- `note_units`
- `ref_map`
- `freeze_summary`

说明：

- 本模块输出的 unit 仍需兼容当前 worker。
- 即：当前 `kind / owner_kind / owner_id / section_id / section_title / note_id / page_segments / target_ref` 合同继续保留。

### 4.5.4 关键判断

1. 只冻结 `matched`。
2. 不确定项必须保留 raw marker，不能“先冻了再说”。
3. “注入失败”不能静默吞掉，必须有显式 skip reason。
4. unit 规划是本模块职责，不再散落在其他阶段。

### 4.5.5 必须继承的历史修补

#### 归 `5B token_injection`

- `units.py`
  - `_ref_materialization_context`
  - `_inject_token_once`
  - `_materialize_refs_for_chapter`
  - `_link_sort_key`

#### 归 `5C translation_unit_planning`

- `units.py`
  - `build_translation_units` 中的 unit 规划主干

#### 继续复用

- `shared/refs.py`
  - `frozen_note_ref`
  - `replace_frozen_refs`
  - `extract_note_refs`
- `translation/translate_worker_common.py`
  - 现有占位符保护通道

### 4.5.6 Gate

#### Hard

- `freeze.only_matched_frozen`
  冻结对象只能来自 `matched` link。
- `freeze.no_duplicate_injection`
  同一位置不得出现重复 token。
- `freeze.accounting_closed`
  每个可冻结 link 必须落入二选一：
  - 成功注入
  - 显式 skip 并附 reason
- `freeze.unit_contract_valid`
  输出 unit 必须满足当前 worker 合同。

#### Soft

- `freeze.synthetic_skip_warn`
  因 synthetic anchor 而跳过的数量偏多。
- `freeze.conflict_skip_warn`
  conflict anchor 数量偏多。

### 4.5.7 非职责

- 不把 token 解冻为 `[^n]`。
- 不生成章节 markdown。

---

## 4.6 模块六：`chapter_merge`

职责：把“译后的正文 + 本章注释定义”合成单章 markdown，并完成 token 解冻与 raw marker 兜底。

### 4.6.1 树状拆分

```text
chapter_merge
├─ 6A translated_body_resolve
│  ├─ 优先取 translated_text
│  ├─ 诊断模式回退
│  └─ body unit 文本规整
├─ 6B frozen_ref_thaw
│  ├─ NOTE_REF -> [^n]
│  ├─ 本章局部编号
│  └─ 编号顺序确定化
├─ 6C raw_marker_fallback_rewrite
│  ├─ 方括号 marker
│  ├─ HTML/sup marker
│  ├─ Unicode 上标 marker
│  └─ OCR alias 收敛
├─ 6D note_definition_assembly
│  ├─ note text 选择
│  ├─ definition 文本清洗
│  └─ 章尾定义块生成
└─ 6E chapter_markdown_emit
   ├─ 标题与 section heads
   ├─ 文件名
   └─ 单章 markdown 输出
```

### 4.6.2 输入

- `FrozenUnits` 的译后结果
- `NoteLinkTable`
- `ChapterLayers`

### 4.6.3 输出

`ChapterMarkdownSet`

- `chapters[]`
  - `chapter_id`
  - `title`
  - `path`
  - `markdown_text`
- `chapter_contract_summary`

### 4.6.4 关键判断

1. token 解冻只在这里发生。
2. raw marker 兜底也只在这里发生。
3. 单章文件是最终用户可交付对象，不能再把未解冻 token 留给整书阶段处理。

### 4.6.5 必须继承的历史修补

#### 归 `6B frozen_ref_thaw`

- `export.py`
  - `_marker_key`
  - `_marker_aliases`
  - `_normalize_endnote_note_id`
  - `_resolve_note_id`
  - `_local_ref_number`
  - `_replace_note_refs_with_local_labels`

#### 归 `6C raw_marker_fallback_rewrite`

- `export.py`
  - `_replace_raw_bracket_refs_with_local_labels`
  - `_replace_raw_superscript_refs_with_local_labels`
  - `_replace_raw_unicode_superscript_refs_with_local_labels`

#### 归 `6D note_definition_assembly`

- `export.py`
  - `_should_replace_definition_text`
  - `_sanitize_note_text`
  - `_build_note_text_by_id_for_chapter`

#### 归 `6E chapter_markdown_emit`

- `export.py`
  - `_sanitize_obsidian_chapter_title`
  - `_build_chapter_filename`
  - `_normalize_markdown_content`
  - `_strip_trailing_image_only_block`
  - `_looks_like_sentence_section_heading`
  - `_is_exportable_section_head`
  - `_resolve_body_unit_text`
  - `_rewrite_body_text_with_local_refs`
  - `_chapter_page_numbers`
  - `_build_section_heads_by_page`
  - `_build_raw_marker_note_sequences`
  - `_build_section_markdown`

### 4.6.6 Gate

#### Hard

- `merge.chapter_files_emitted`
  每个 exportable chapter 恰好产出一个 `.md`。
- `merge.local_refs_closed`
  每个 `[^n]` 都有对应定义，且无悬空定义。
- `merge.no_frozen_ref_leak`
  章节文件中不得残留 `{{NOTE_REF:*}}`。
- `merge.no_raw_marker_leak_in_body`
  正文区不得残留未改写 raw marker。

#### Soft

- `merge.image_tail_warn`
  尾部出现图片块清洗。
- `merge.section_heading_warn`
  section head 有被过滤或疑似伪标题情况。

### 4.6.7 非职责

- 不决定章节顺序。
- 不做整书级审计。

---

## 4.7 模块七：`book_assemble`

职责：按目录顺序组装整本导出物，并做最终书级审计。

### 4.7.1 树状拆分

```text
book_assemble
├─ 7A chapter_ordering
│  ├─ 目录顺序装配
│  └─ 非 start_page 驱动
├─ 7B book_file_assembly
│  ├─ index.md
│  ├─ chapters/*.md
│  └─ files map
├─ 7C zip_bundle
│  └─ zip bytes 生成
└─ 7D export_audit
   ├─ 语义合同
   ├─ 重复段/重复标题
   ├─ 跨章污染
   └─ raw marker 残留
```

### 4.7.2 输入

- `ChapterMarkdownSet`
- `TocStructure`

### 4.7.3 输出

`ExportBundle`

- `index.md`
- `chapters/*`
- `files`
- `zip_bytes`
- `audit_report`

### 4.7.4 关键判断

1. 整书顺序由模块一的目录顺序决定，不再由 `start_page` 反推。
2. 书级审计只检查整书问题，不再回头改写章节内容。
3. 书级 audit 是最后一道闸，不替代前面模块的局部 gate。

### 4.7.5 必须继承的历史修补

#### 归 `7B book_file_assembly`

- `export.py`
  - `_build_index_markdown`
  - `_build_export_chapters`
  - `build_export_bundle`
  - `build_export_zip`

#### 归 `7D export_audit`

- `export.py`
  - `_compute_export_semantic_contract`
  - `_normalized_paragraph_key`
  - `_is_semantic_duplicate_candidate`
  - `_looks_like_bibliography_entry`
- `export_audit.py`
  - `split_body_and_definitions`
  - `_looks_like_mid_sentence_opening`
  - `_looks_like_missing_tail`
  - `_detect_mid_paragraph_heading`
  - `_duplicate_heading_count`
  - `_duplicate_paragraph_count`
  - `_contains_other_chapter_heading`
  - `_iter_raw_note_marker_hits`
  - `_iter_raw_superscript_note_marker_hits`
  - `_definition_has_raw_note_marker`

### 4.7.6 Gate

#### Hard

- `export.order_follows_toc`
  导出顺序必须等于模块一的目录顺序。
- `export.semantic_contract_ok`
  沿用 `_compute_export_semantic_contract` 的正式合同。
- `export.audit_can_ship`
  `audit_report.can_ship` 必须为真。
- `export.no_cross_chapter_contamination`
  不得命中跨章污染。
- `export.no_raw_marker_leak_book_level`
  整书级 raw marker 残留为 `0`。

#### Soft

- `export.duplicate_warn`
  存在轻度重复或可疑段落。

### 4.7.7 非职责

- 不再回写章节边界。
- 不再重跑链接。

---

## 5. `status.py` 的新职责

`status.py` 只做三件事：

1. 汇总 7 个模块的 `GateReport`
2. 映射成统一对外状态字段
3. 输出 `blocking_reasons / review_hints / progress summaries`

### 5.1 必须移除的旧行为

- 不再根据导出结果反向推测章节/注释业务事实。
- 不再把 TOC、boundary、link、export 多条线混成一条模糊 review 线。
- 不再使用 `phase4_* / phase6_*` 这种阶段绑定命名。

### 5.2 新命名约定

`blocking_reasons` 统一按模块前缀归类：

- `toc_*`
- `book_type_*`
- `split_*`
- `link_*`
- `freeze_*`
- `merge_*`
- `export_*`

### 5.3 放行规则

- `pipeline_state != done` 时，状态可显示 `idle/running/error`。
- `pipeline_state == done` 且所有 hard gate 为真时，结构状态才可为 `ready`。
- 任一 hard gate 失败则进入 `review_required`。
- `soft` 结果只进入提示，不直接阻塞。

---

## 6. 共享层约束

### 6.1 `shared/`

继续保留：

- `text.py`
- `title.py`
- `notes.py`
- `anchors.py`
- `refs.py`
- `segments.py`

原则：

1. 无 repo 依赖。
2. 无 `doc_id` 语义。
3. 无阶段命名。
4. 只提供底层可复用工具，不承载业务 gate。

### 6.2 `app/mainline.py`

继续保留为 doc/repo 接线层，负责：

- TOC 来源选择与 fallback
- manual 输入状态
- repo 读写
- 运行态 overlay
- 调 7 个模块

禁止：

- 手写章节/注释/链接/导出语义判断

### 6.3 `app/pipeline.py`

目标：

- 下线公开的 `phase1~phase6` 入口
- 改成 7 步模块组合入口

要求：

- 可以在迁移批次内存在临时适配函数
- 但批次结束前必须删掉

---

## 7. 与现状相比，必须发生的行为变化

| 主题 | 现状 | 重构后 |
|---|---|---|
| 页面角色 | 对外仍含 `noise/body/note/other` 等技术混合角色 | 对外只保留业务角色；`noise` 只作为内部标签 |
| 目录角色 | 与页面角色混用 | 单独的 `toc_tree` 与目录节点角色 |
| 书型 | 只有章级 `note_mode` | 显式全书 `book_type` |
| 正文/注释切分 | 多层重复发生 | 只在模块三发生 |
| 链接 gate | 与 boundary/toc/export 混判 | 模块四只守链接 contract |
| ref 冻结 | 单位规划与正文切分混在一起 | 模块五单独负责 |
| 解冻与 raw marker 兜底 | 导出大函数里混做 | 模块六单独负责 |
| 导出顺序 | `start_page` 驱动 | `toc_tree` 驱动 |
| 状态汇总 | `status.py` 兼做业务推断 | `status.py` 只汇总 gate |

---

## 8. 迁移批次

本次迁移不按“先改名再整体替换”的方式做，改为 6 个批次。

### 批次 0：冻结边界合同

目标：

- 新建真相对象定义
- 新建 `ModuleResult / GateReport` 协议
- 冻结现有 worker / repo / diagnostic 所需投影合同

完成条件：

- 文档与代码中明确“业务对象”和“投影对象”的边界
- 不改 SQLite 语义

### 批次 1：模块一、二

目标：

- 先把目录结构和书型判定拆干净

完成条件：

- `toc_structure`
- `book_note_type`
- 对应 gate 单测

### 批次 2：模块三

目标：

- 收敛正文/注释切分

完成条件：

- 正文切线只在模块三存在
- `mixed` / `footnote_only` 策略有明确对象输出

### 批次 3：模块四、五

目标：

- 收敛链接与冻结逻辑

完成条件：

- 链接 contract 独立
- unit 规划从正文切分中剥离

### 批次 4：模块六、七

目标：

- 收敛章节导出与整书导出

完成条件：

- 单章与整书 gate 分离
- 目录顺序正式取代 `start_page` 顺序

### 批次 5：接线切换与旧入口删除

目标：

- `mainline.py` 切到 7 模块主线
- 删除 `phase1~phase6`
- 重写 `status.py`

完成条件：

- 无旧阶段公开入口
- `blocking_reasons` 全部改为模块前缀

---

## 9. 测试要求

每个模块必须至少覆盖：

1. 主路径
2. 至少一个历史修补点
3. 至少一个 hard gate 失败样例
4. 至少一个 override 放行样例

全量回归最低要求：

- `tests/unit/test_fnm_import_guards.py`
- 7 个模块单测
- `mainline` 集成测试
- `scripts/test_fnm_batch.py --group baseline`
- `scripts/test_fnm_batch.py --group extension`

命名目标：

- `test_fnm_re_module1_toc.py`
- `test_fnm_re_module2_book_type.py`
- `test_fnm_re_module3_split.py`
- `test_fnm_re_module4_link.py`
- `test_fnm_re_module5_freeze.py`
- `test_fnm_re_module6_merge.py`
- `test_fnm_re_module7_export.py`

---

## 10. 本文件的执行口径

后续如果代码实现与本文冲突，以本文为准，并按下面顺序处理：

1. 先修业务模块边界
2. 再修 gate 定义
3. 最后才修 repo / status / 诊断投影

禁止再出现的做法：

- 在导出层重新切正文/注释
- 在状态层反推业务事实
- 在接线层临时补判断绕过模块
- 在迁移时默默删除旧修补逻辑

本文件的目标，就是把 FNM_RE 从“阶段拼装”改成“职责树 + gate 树”的稳定结构。
