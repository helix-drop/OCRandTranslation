# 阶段 2 详细计划：`chapter_split` 章节正文与注释切分

## 概要

阶段 2 承接阶段 1 已完成的 `TocStructure` 与 `BookNoteProfile`，新增模块 `chapter_split`，目标是把每章拆成清晰的树状层级：正文页、正文段落、脚注项、尾注区域、尾注项、策略记录，并为每个子流程建立 hard gate。

本阶段只解决“正文和注释如何被切开、归属、提取、记录策略”。不做正文 anchor 匹配、不冻结引用、不生成最终 Markdown、不切换主流程。

## 实施内容

新增对外入口：

```python
build_chapter_layers(
    toc_structure,
    book_note_profile,
    pages,
    pdf_path="",
    page_text_map=None,
    overrides=None,
    max_body_chars=6000,
) -> ModuleResult[ChapterLayers]
```

在 `FNM_RE/modules/types.py` 增加阶段 2 真相对象：

- `LayerNoteRegion`：记录 `region_id`、`chapter_id`、`page_start`、`page_end`、`pages`、`note_kind`、`scope`、`source`、`heading_text`、`review_required`。
- `LayerNoteItem`：记录 `note_item_id`、`region_id`、`chapter_id`、`page_no`、`marker`、`marker_type`、`text`、`source`、`is_reconstructed`、`review_required`。
- `BodyPageLayer`：记录 `page_no`、`text`、`split_reason`、`source_role`。
- `BodySegmentLayer`：记录 `page_no`、`paragraph_count`、`source_text`、`display_text`、`paragraphs`。
- `ChapterLayer`：记录 `chapter_id`、`title`、`body_pages`、`body_segments`、`footnote_items`、`endnote_items`、`endnote_regions`、`policy_applied`。
- `ChapterLayers`：记录 `chapters`、`regions`、`note_items`、`region_summary`、`item_summary`。

新增模块文件：

- `FNM_RE/modules/chapter_split.py`
- 在 `FNM_RE/modules/__init__.py` 和 `FNM_RE/__init__.py` 暴露 `build_chapter_layers`

## 模块树

`chapter_split`

- `3A note_region_binding`
  - 输入：`TocStructure`、`BookNoteProfile`、`pages`
  - 处理：复用旧 `FNM_RE/stages/note_regions.py` 的区域识别逻辑。
  - 输出：`LayerNoteRegion[]`
  - 验收：所有注释区域必须归属到 chapter 或 book scope，Biopolitics 不允许 orphan region。

- `3B note_item_extraction`
  - 输入：`LayerNoteRegion[]`、`pages`、`page_text_map`、`pdf_path`
  - 处理：复用旧 `FNM_RE/stages/note_items.py` 的 structured scan / markdown text / pdf text 兜底链。
  - 输出：`LayerNoteItem[]`
  - 验收：非空注释区域必须能产出 note item；空区域必须进入 evidence 或通过 override 放行。

- `3C body_page_split`
  - 输入：`TocStructure.chapters`、`pages`、注释区域 start page
  - 处理：复用旧 `FNM_RE/stages/units.py` 中正文页和段落切分的纯函数，但不能调用 `build_translation_units()`。
  - 输出：`BodyPageLayer[]`、`BodySegmentLayer[]`
  - 验收：正文层和注释层不能混在一起；章节正文不能明显截断；跨页段落统计必须进入 evidence。

- `3D note_materialization_policy`
  - 输入：`BookNoteProfile.book_type`、章级 note mode
  - 处理：为每章记录策略，不在本阶段提前写入最终导出文本。
  - 输出：`policy_applied`
  - 验收：Biopolitics 是 `mixed`，必须记录 mixed 策略；如果不把脚注 marker 写回正文，必须在 diagnostics/evidence 中明确记录 `mixed_marker_materialized=not_required` 或同等原因。

## 适配策略

阶段 2 可以复用旧阶段代码，但对外只能暴露新模块对象。

新增内部 helper：

```python
_phase1_from_toc_structure(toc_structure) -> Phase1Structure-like object
```

映射规则：

- `TocPageRole.role == "chapter"` 或 `"post_body"` 映射为旧 `body`。
- `TocPageRole.role == "front_matter"` 映射为旧 `front_matter`。
- `TocPageRole.role == "back_matter"` 映射为旧 `other`。
- `TocChapter` 转旧 `ChapterRecord`。
- `TocSectionHead` 如旧逻辑需要则转换，否则保持空列表。
- 不在此 helper 中重新判断书型，书型只信任 `BookNoteProfile`。

正文切分时：

- 每章 `note_start_page` 来自该章 endnote region 的起始页。
- 如果没有章级 endnote region，则正文范围按 `TocChapter.start_page/end_page`。
- 不注入 `NOTE_REF`。
- 不生成 `TranslationUnit`。
- 不做 link/freeze/export 决策。

## Gate 规则

`ModuleResult.gate_report.hard` 必须包含：

- `split.regions_bound`
- `split.items_extracted`
- `split.body_note_disjoint`
- `split.cross_page_continuity_ok`
- `split.policy_applied`
- `split.footnote_only_synthesized`
- `split.mixed_marker_materialized`

判定口径：

- `split.regions_bound=true`：所有 region 都有 `chapter_id` 或 `scope="book"`；Biopolitics 不允许 orphan region。
- `split.items_extracted=true`：所有非空 region 都有 note item；失败时列出 `empty_region_ids`。
- `split.body_note_disjoint=true`：正文页不包含 endnote region 起始后的注释内容；同页正文/注释必须有明确切线。
- `split.cross_page_continuity_ok=true`：每章有正文段落，跨页拼接异常进入 evidence；不能只用“没有跨页”为通过依据。
- `split.policy_applied=true`：每个 `ChapterLayer` 都有明确 `policy_applied`。
- `split.footnote_only_synthesized=true`：Biopolitics 为 mixed，本 gate 以 `not_applicable` 证据放行；如果 synthetic footnote-only 测试启用，则要求脚注合成为统一尾注区且编号从 1 连续。
- `split.mixed_marker_materialized=true`：Biopolitics 可为实际 materialized，也可为 `not_required` 放行，但必须在 evidence 中说明原因。

Soft gate：

- `split.char_drop_warn`：正文切分前后字符量明显异常时触发 warning，不直接阻断阶段 2。

## 测试计划

新增测试文件：

```text
tests/unit/test_fnm_re_module3_split.py
```

测试统一使用 Biopolitics fixture：

```python
pages = load_pages("Biopolitics")
toc = build_toc_structure(pages, load_auto_visual_toc("Biopolitics")).data
profile = build_book_note_profile(toc, pages).data
layers = build_chapter_layers(toc, profile, pages)
```

必须覆盖：

- Biopolitics 主路径：所有 hard gate 为 true；`regions` 非空；`note_items` 非空；正文 chapter 数量与阶段 1 输出一致；每章都有 `policy_applied`。
- 注释归属：footnote band 能进入 `footnote_items`，chapter/book endnote region 能绑定到正确章节或 book scope。
- 正文/注释切线：构造一个同页含正文和 `# Notes` 的 synthetic case，断言正文不吞掉 notes，notes 仍进入 note items。
- 空注释区域：构造有 note heading 但无 note item 的 case，断言 `split.items_extracted=false`，并在 reasons/evidence 中列出空 region。
- override：对空 region 使用 override 放行时，`overrides_used` 必须记录，原始 empty evidence 不能被隐藏。
- mixed 策略：Biopolitics 必须记录 mixed policy；如果不实际写入脚注 marker，则 evidence 必须说明 `not_required`。
- footnote-only：Biopolitics 不作为 hard case；如实现合成策略，用 synthetic fixture 验证脚注编号从 1 连续。

验收命令：

```bash
python3 -m unittest \
  tests.unit.test_fnm_re_module1_toc \
  tests.unit.test_fnm_re_module2_book_type \
  tests.unit.test_fnm_re_module3_split
```

可选烟测，不作为阶段 2 硬验收：

```bash
python3 scripts/test_fnm_batch.py --slug Biopolitics
```

## 明确不做

- 不做正文 anchor 匹配。
- 不做 note link 生成。
- 不做 ref freeze。
- 不生成最终导出 Markdown。
- 不调用 `build_translation_units()`。
- 不切换 mainline pipeline。
- 不改 SQLite 状态流。
- 不删除旧阶段实现。

## 交付物

- 新增 `FNM_RE/modules/chapter_split.py`
- 更新 `FNM_RE/modules/types.py`
- 更新 `FNM_RE/modules/__init__.py`
- 更新 `FNM_RE/__init__.py`
- 新增 `tests/unit/test_fnm_re_module3_split.py`
- 更新 `FNM_RE/OnWorking.md`，记录 stage2 批次、测试结果、Biopolitics 结论。
- 更新 `verification.md`，记录实际执行的 unittest 命令与结果。

## 默认假设

- 阶段 1 当前工作区内容可用，阶段 2 直接基于这些未提交文件继续。
- Biopolitics 是本阶段唯一硬验收样本。
- Biopolitics 的书型为 `mixed`，`footnote_only` 只作为 synthetic 测试或后续扩展，不作为本阶段硬验收。
- 旧 `note_regions`、`note_items`、`units` 可以作为内部复用实现，但不能泄漏旧阶段对象到新的对外接口。
