# FNM_RE 模块化重构总计划（Biopolitics 单书验收版）

## 总结

本轮目标是把 `FNM_RE` 从旧 `phase1~phase6` 阶段拼装，重构为 7 个业务模块：`toc_structure -> book_note_type -> chapter_split -> note_linking -> ref_freeze -> chapter_merge -> book_assemble`。

验收范围只看 `Biopolitics` 单书。输入固定为 PDF 原文、`目录.pdf`、`raw_pages.json`、`raw_source_markdown.md`。旧的默认 8 本批测不再作为本轮通过条件，只在 Biopolitics 跑通后逐步恢复。

## 实施阶段

### 阶段 0：边界合同与测试夹具

目标是先冻结运行边界，避免重构过程中打断 worker、repo 和诊断投影。

- 新增 `ModuleResult` 与 `GateReport` 协议，所有模块统一返回 `data / gate_report / evidence / overrides_used / diagnostics`。
- 固定 Biopolitics 测试夹具，确认 `raw_pages.json` 为 370 页，且每页具备 `bookPage / markdown`。
- 保持当前 `TranslationUnit` 投影合同不变，字段包括 `kind / owner_kind / owner_id / section_id / section_title / note_id / page_segments / target_ref`。
- 第一轮不改 SQLite 表语义，只新增业务对象到现有 repo/worker 形状的投影层。
- 通过标准：阶段 0 单测通过，Biopolitics 夹具可无网络、无真实 LLM 加载。

### 阶段 1：目录结构与书型

目标是先把“这本书的结构”和“这本书的注释类型”稳定下来。

- 实现 `toc_structure`，负责页面外部角色、TOC 树、章节骨架、section heads。
- 实现 `book_note_type`，负责全书 `book_type` 与章级 `note_mode`。
- 对外页面角色不得暴露 `noise`，`container / chapter / post_body / back_matter` 必须分开。
- Biopolitics 必须得到稳定章节顺序、章节标题对齐结果和明确书型。
- 通过标准：`toc.pages_classified`、`toc.has_exportable_chapters`、`toc.chapter_titles_aligned`、`toc.chapter_order_monotonic`、`toc.role_semantics_valid`、`book_type.resolved`、`book_type.chapter_modes_consistent` 全部为真。

### 阶段 2：章节正文与注释切分

目标是把正文层、脚注层、尾注层一次切清，不再让后续模块补切线。

- 实现 `chapter_split`，内部按 `note_region_binding / note_item_extraction / body_page_split / note_materialization_policy` 树状拆分。
- Biopolitics 的 footnote band、chapter endnote、book endnote 都必须被绑定到明确层级。
- 正文/注释共页时，切线只在本模块产生。
- `mixed` 书策略在本模块记录，脚注 materialize 需求必须可审计。
- 通过标准：`split.regions_bound`、`split.items_extracted`、`split.body_note_disjoint`、`split.cross_page_continuity_ok`、`split.policy_applied` 全部为真。

### 阶段 3：注释链接与引用冻结

目标是把“链接是否可靠”和“哪些引用可安全进入翻译 token”分开。

- 实现 `note_linking`，负责 anchor 抽取、直接匹配、repair 匹配、章级链接 contract。
- 实现 `ref_freeze`，只冻结 `matched` link，synthetic、ambiguous、orphan、ignored 不得冻结。
- token 注入必须有完整记账，成功注入和 skip reason 必须闭合。
- 输出 units 必须继续兼容当前 FNM 翻译 worker。
- 通过标准：`link.endnotes_all_matched`、`link.no_ambiguous_left`、`link.no_orphan_note`、`freeze.only_matched_frozen`、`freeze.no_duplicate_injection`、`freeze.accounting_closed`、`freeze.unit_contract_valid` 全部为真。

### 阶段 4：单章合并与整书导出

目标是把单章 markdown 和整书 zip 分离验收。

- 实现 `chapter_merge`，负责译后正文合并、`NOTE_REF` 解冻、本章局部 `[^n]` 编号、raw marker fallback。
- 实现 `book_assemble`，负责按 TOC 顺序组装 `index.md / chapters/*.md / zip` 并执行整书审计。
- 导出顺序必须来自 `toc_tree`，不再由 `start_page` 反推。
- 整书审计只检查整书问题，不回头改写单章内容。
- 通过标准：`merge.local_refs_closed`、`merge.no_frozen_ref_leak`、`merge.no_raw_marker_leak_in_body`、`export.order_follows_toc`、`export.semantic_contract_ok`、`export.audit_can_ship` 全部为真。

### 阶段 5：主线切换与旧入口删除

目标是让新 7 模块成为正式主线，并下线旧阶段口径。

- `app/pipeline.py` 切成 7 模块组合入口。
- `app/mainline.py` 只保留 doc/repo 接线、manual 输入解析、repo overlay 和持久化映射。
- `status.py` 改为只汇总 7 个模块的 `GateReport`，不再反推业务事实。
- `blocking_reasons` 统一改为模块前缀：`toc_* / book_type_* / split_* / link_* / freeze_* / merge_* / export_*`。
- 删除旧 `phase1~phase6` 公开入口和旧阶段测试口径。
- 通过标准：Biopolitics 单书主线 `structure_state=ready`、`blocking_reasons=[]`、`export_ready_test=true`，并生成本轮 `latest.fnm.obsidian.zip`。

## 接口与类型变化

- 新增真相对象：`TocStructure`、`BookNoteProfile`、`ChapterLayers`、`NoteLinkTable`、`FrozenUnits`、`ChapterMarkdownSet`、`ExportBundle`。
- 新增统一返回协议：`ModuleResult`。
- 新增统一 gate 协议：`GateReport`。
- `status.py` 对外状态仍保留主字段，但来源改为模块 gate 汇总。
- 第一轮不改 SQLite 表结构，业务对象通过投影层写回现有 `replace_fnm_structure()` 与 `replace_fnm_data()`。
- 第一轮不改 FNM 翻译 worker 的 unit 消费合同。

## 测试计划

- 阶段 0：新增 `tests/unit/test_fnm_re_stage0_contract.py`，验证 Biopolitics 夹具、协议和 unit 投影合同。
- 阶段 1：新增 `test_fnm_re_module1_toc.py` 与 `test_fnm_re_module2_book_type.py`，验证 TOC、章节、书型 gate。
- 阶段 2：新增 `test_fnm_re_module3_split.py`，验证 region、item、正文/注释切分和策略 gate。
- 阶段 3：新增 `test_fnm_re_module4_link.py` 与 `test_fnm_re_module5_freeze.py`，验证链接 contract、冻结规则和 unit 合同。
- 阶段 4：新增 `test_fnm_re_module6_merge.py` 与 `test_fnm_re_module7_export.py`，验证单章闭合、整书顺序和 audit。
- 阶段 5：新增 `tests/integration/test_fnm_re_mainline_biopolitics.py` 与 `tests/unit/test_fnm_re_status_gate_summary.py`，验证新主线和状态收口。
- 最终烟测只跑：`python3 scripts/test_fnm_batch.py --slug Biopolitics`。

## 最终验收标准

- Biopolitics 本轮运行结果 `structure_state == "ready"`。
- `blocking_reasons == []`。
- `export_ready_test == true`。
- `chapter_title_alignment_ok == true`。
- `chapter_local_endnote_contract_ok == true`。
- `endnote_orphan_note == 0`。
- `endnote_orphan_anchor == 0`。
- `ambiguous == 0`。
- 导出文件无 `{{NOTE_REF:*}}` 残留。
- 导出正文无未处理 raw note marker。
- `test_example/Biopolitics/latest.fnm.obsidian.zip` 存在且来自本轮生成。

## 默认假设

- 本轮只以 `test_example/Biopolitics` 作为硬验收样本。
- 如果实际输入目录改为 `example_text/Biopolitics`，只替换夹具路径，不改变重构路线。
- 其他样本的失败不阻塞本轮，只记录为后续修补项。
- 每完成一个阶段，都更新 `FNM_RE/OnWorking.md` 和 `verification.md`，只记录阶段、Biopolitics 当前进度和剩余阻塞 gate。
