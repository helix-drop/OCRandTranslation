# 第一阶段详细计划：目录结构与书型

## 总结

本阶段只实现并验证两个新业务模块：`toc_structure` 和 `book_note_type`。目标是让 Biopolitics 在“页面角色、TOC 树、章节骨架、section heads、全书书型、章级 note mode”这一步稳定通过，不做正文/注释切分、不做链接、不做冻结、不做导出。

前置假设：阶段 0 的 `ModuleResult / GateReport` 协议和 Biopolitics fixture 已可用；如果尚未落地，先补最小协议与 fixture helper，但不切主线。

## 实现改动

- 新增 `FNM_RE/modules/toc_structure.py`，对外提供 `build_toc_structure(pages, toc_items, manual_page_overrides=None, pdf_path="") -> ModuleResult[TocStructure]`。
- 新增 `FNM_RE/modules/book_note_type.py`，对外提供 `build_book_note_profile(toc_structure, pages, pdf_path="", page_text_map=None, overrides=None) -> ModuleResult[BookNoteProfile]`。
- 新增或扩展真相对象：`TocStructure`、`TocPageRole`、`TocNode`、`BookNoteProfile`、`BookNoteTypeEvidence`；旧 `Phase1Structure / Phase2Structure` 本阶段不删除。
- 本阶段不改 SQLite schema，不改正式 `app/mainline.py` 主线，不删除旧 `phase1~phase6`，只新增模块与单测。
- 所有新模块必须返回 `ModuleResult`，并把 hard/soft gate 写入 `GateReport`。

## `toc_structure` 具体要求

- 内部按 4 个子流程组织：`page_role_tagging -> toc_role_projection -> chapter_skeleton -> section_head_binding`。
- `page_role_tagging` 复用 `build_page_partitions()`，但输出对外角色时不得暴露 `noise`；旧 `noise/body/note/other` 只进入 `internal_tags` 或 `reason_codes`。
- `toc_role_projection` 读取统一 `toc_items`，生成 `toc_tree`，每个节点必须有 `role in front_matter/container/chapter/post_body/back_matter`。
- `chapter_skeleton` 复用 `build_chapter_skeleton()`，视觉目录为主证据，fallback 只在无可用视觉目录时启用。
- `section_head_binding` 复用 `build_section_heads()`，只产出章内 section heads，不参与章节边界推翻。
- Biopolitics 期望：`page_count=370`、`chapter_count=12`、章节来源优先为 `visual_toc`、章节标题对齐通过。

## `toc_structure` Gate

- `toc.pages_classified=true`：每页都有且仅有一个外部角色。
- `toc.has_exportable_chapters=true`：至少一个 exportable chapter；Biopolitics 期望为 12 个。
- `toc.chapter_titles_aligned=true`：不残留 `toc_chapter_title_mismatch`。
- `toc.chapter_order_monotonic=true`：TOC 顺序与章节 `start_page` 单调一致。
- `toc.role_semantics_valid=true`：`back_matter` 之后不得再出现普通 `chapter`，除非 override。
- soft gate 保留 `toc.section_alignment_warn` 与 `toc.visual_toc_conflict_warn`，但不阻塞本阶段。

## `book_note_type` 具体要求

- 内部按 3 个子流程组织：`note_evidence_scan -> book_type_resolution -> chapter_mode_projection`。
- `note_evidence_scan` 只采集证据，不生成正式 note regions；可复用 `shared/notes.py` 与 `note_regions.py` 中 heading scan / footnote band 的纯 helper。
- 若现有 helper 与 `build_note_regions()` 绑定过深，先抽出无副作用证据函数，不把模块三职责提前搬进来。
- `book_type_resolution` 输出 `book_type in mixed/endnote_only/footnote_only/no_notes`，不允许 `unknown`。
- `chapter_mode_projection` 可以复用 `_build_chapter_note_modes()` 的 mode 规则，但本阶段 `region_ids` 可为空或只记录 evidence id；正式 region id 由模块三负责。
- Biopolitics 期望：识别为 `mixed`，章级 mode 不与 `mixed` 冲突，不能出现未解释的 `review_required`。

## `book_note_type` Gate

- `book_type.resolved=true`：全书书型明确。
- `book_type.chapter_modes_consistent=true`：章级 note mode 与全书书型一致。
- `book_type.no_unapproved_review_required=true`：若出现 `review_required`，必须有 explicit override，否则阻塞。
- soft gate `book_type.low_confidence_warn` 允许存在，但必须记录证据来源和原因。

## 测试计划

- 新增 `tests/unit/test_fnm_re_module1_toc.py`。
- 新增 `tests/unit/test_fnm_re_module2_book_type.py`。
- 测试 fixture 读取 `test_example/Biopolitics/raw_pages.json` 和 `test_example/Biopolitics/auto_visual_toc.json`，不调用视觉模型、不访问网络。
- `toc_structure` 单测覆盖：Biopolitics 主路径、页面 role 不暴露 `noise`、章节数 12、章节顺序单调、制造乱序 TOC 时 `toc.chapter_order_monotonic=false`。
- `book_note_type` 单测覆盖：Biopolitics 判为 `mixed`、章级 mode 一致、制造冲突证据时 `book_type.chapter_modes_consistent=false`、制造 `review_required` 且无 override 时阻塞。
- 两个模块都必须覆盖一次 override 记录，验证 `overrides_used` 不为空且原始 evidence 不被隐藏。

## 验收命令

- 阶段内最小命令：`python3 -m unittest tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type`
- 可选烟测：`python3 scripts/test_fnm_batch.py --slug Biopolitics`
- 烟测失败不直接判定阶段失败；先看本阶段两个模块的 `GateReport` 是否通过。

## 不做的事

- 不做 `chapter_split`。
- 不生成正式 note regions / note items。
- 不做 body anchor、note link、ref freeze。
- 不改导出顺序。
- 不删除旧 `phase1~phase6`。
- 不用 8 本样本批测作为本阶段验收。

## 交付物

- 两个新模块文件。
- 新真相对象或 dataclass。
- 两个模块单测文件。
- Biopolitics fixture helper。
- `FNM_RE/OnWorking.md` 记录本阶段结果。
- `verification.md` 记录命令、结果、剩余未覆盖 gate。
