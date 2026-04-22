# example 八本书按模块顺序的修补待办清单

日期：2026-04-19

来源：

- `FNM_RE/MODULS.md`
- `FNM_RE/handoff/remaining_blocking_books.md`
- `test_example/example_manifest.json`
- `output/fnm_batch_test_result.json`
- `test_example/*/latest_export_status.json`

## 目标

这份清单不再按“哪本书先修”组织，而是按 `FNM_RE/MODULS.md` 的 7 个模块顺序组织。

执行规则只有一条：

**同一本书只有当前序模块通过后，才允许进入下一模块的修补。**

含义：

1. 下游模块即使已经出现阻塞码，也只作为“观测现象”记录。
2. 只要更早模块还没通过，下游模块一律不立项、不单修、不判完成。
3. 每次修完某模块后，都要对该书重跑全链，再决定是否进入下一模块。

## 状态口径

| 状态 | 含义 |
|---|---|
| `通过` | 当前模块已满足放行条件，可进入下一模块 |
| `未通过` | 当前模块就是这本书的修补入口，必须先修这里 |
| `阻塞` | 该模块暂不进入修补，因为更早模块还没通过 |

## 模块顺序与通过要求

| 顺序 | 模块 | 通过要求 |
|---|---|---|
| 1 | `toc_structure` | `toc.pages_classified`、`toc.has_exportable_chapters`、`toc.chapter_titles_aligned`、`toc.chapter_order_monotonic`、`toc.role_semantics_valid` 全部通过 |
| 2 | `book_note_type` | `book_type.resolved`、`book_type.chapter_modes_consistent`、`book_type.no_unapproved_review_required` 全部通过 |
| 3 | `chapter_split` | `split.regions_bound`、`split.items_extracted`、`split.body_note_disjoint`、`split.cross_page_continuity_ok`、`split.policy_applied` 通过；`footnote_only` 书还要过 `split.footnote_only_synthesized`；`mixed` 书还要过 `split.mixed_marker_materialized` |
| 4 | `note_linking` | 对需要章级尾注闭合的章节，`link.first_marker_is_one`、`link.endnotes_all_matched`、`link.no_ambiguous_left`、`link.no_orphan_note` 通过；若全书是 `endnote_only`，还要过 `link.endnote_only_no_orphan_anchor` |
| 5 | `ref_freeze` | `freeze.only_matched_frozen`、`freeze.no_duplicate_injection`、`freeze.accounting_closed`、`freeze.unit_contract_valid` 全部通过 |
| 6 | `chapter_merge` | `merge.chapter_files_emitted`、`merge.local_refs_closed`、`merge.no_frozen_ref_leak`、`merge.no_raw_marker_leak_in_body` 全部通过 |
| 7 | `book_assemble` | `export.order_follows_toc`、`export.semantic_contract_ok`、`export.audit_can_ship`、`export.no_cross_chapter_contamination`、`export.no_raw_marker_leak_book_level` 全部通过 |

## 按模块顺序的当前待办

### 1. `toc_structure`

当前直接待办书：

- `Heidegger_en_France`
- `Neuropsychoanalysis_in_Practice`

当前未通过原因：

- `Heidegger_en_France`：`toc_chapter_order_non_monotonic`
- `Neuropsychoanalysis_in_Practice`：`toc_chapter_order_non_monotonic`、`toc_role_semantics_invalid`

本模块完成判定：

- 上述两本书重跑后不再出现任何 `toc_*` blocking
- `Neuropsychoanalysis_in_Practice` 的 `toc_role_summary` 不再全空

注意：

- `Neuropsychoanalysis_in_Practice` 当前虽然还报 `split_footnote_only_synthesis_failed`，但在 `toc_structure` 通过前，不进入 `chapter_split` 修补。

### 2. `book_note_type`

当前直接待办书：

- 无

当前状态：

- 八本样本里，没有哪一本当前以 `book_note_type` 作为最早失败模块

本模块完成判定：

- 对每本书，`book_type` 明确落在 `{mixed, endnote_only, footnote_only, no_notes}` 之一
- 不存在未经 override 解释的 `review_required`

注意：

- `Heidegger_en_France`、`Neuropsychoanalysis_in_Practice` 必须在 `toc_structure` 修完并重跑后，才复核这里。

### 3. `chapter_split`

当前直接待办书：

- `Goldstein`
- `Mad_Act`

当前未通过原因：

- `Goldstein`：根因在 `book_endnote` 的 region 绑章错误，属于 `note_region_binding` 未收口；当前对外表现为下游 `link_*` 和 `freeze_*` 一起失败
- `Mad_Act`：根因在正文/脚注分区错误，导致大量脚注 marker 被当成正文 marker；当前对外表现为 `freeze_unit_contract_invalid`

本模块完成判定：

- `Goldstein`：endnote regions 能重新绑定到正确章节，不能再把大部分 note 全挂到最后一章
- `Mad_Act`：正文层和注释层重新切开，`body` 里不再吞入大段脚注定义
- 两本书重跑后，本模块不再留下 `split_*` 问题，且链接指标明显恢复

注意：

- `Goldstein` 当前虽然报 `link_first_marker_not_one`、`link_endnote_not_all_matched`、`link_orphan_note_remaining`，但在 `chapter_split` 通过前，不进入 `note_linking` 单独修补。
- `Mad_Act` 当前虽然只显式报 `freeze_unit_contract_invalid`，但按交接根因，应视为 `chapter_split` 先不过。

### 4. `note_linking`

当前直接待办书：

- 无

当前状态：

- `Goldstein` 已出现明确 `link_*` 阻塞，但其上游 `chapter_split` 还没过，所以暂不进入本模块修补

本模块完成判定：

- `Goldstein` 在 `chapter_split` 修完并重跑后，再检查是否仍残留 `link_first_marker_not_one`、`link_endnote_not_all_matched`、`link_orphan_note_remaining`

注意：

- 现阶段不单修 `note_linking`，否则容易把上游 region 绑章错误硬补成下游链接特判。

### 5. `ref_freeze`

当前直接待办书：

- `Germany_Madness`

当前未通过原因：

- `Germany_Madness`：`freeze_unit_contract_invalid`

暂不直接进入的书：

- `Goldstein`
- `Mad_Act`

原因：

- 这两本虽然也报 `freeze_unit_contract_invalid`，但更早模块还没通过，当前不能把 `ref_freeze` 当作真正修补入口

本模块完成判定：

- `Germany_Madness` 重跑后不再报 `freeze_unit_contract_invalid`
- 输出 unit 满足当前 worker 合同，且冻结记账闭合

### 6. `chapter_merge`

当前直接待办书：

- 无

当前状态：

- 八本样本没有哪一本当前以 `chapter_merge` 作为最早失败模块

本模块完成判定：

- 当前所有上游阻塞清完后，再确认是否出现 `merge.*` 失败

### 7. `book_assemble`

当前直接待办书：

- 无

当前状态：

- `Germany_Madness` 当前有 `export_semantic_contract_broken`
- 但它的 `ref_freeze` 还没通过，所以暂不进入 `book_assemble` 单独修补

本模块完成判定：

- `Germany_Madness` 在 `ref_freeze` 通过后重跑
- 只有那时仍残留 `export_semantic_contract_broken`，才正式进入本模块修补

## 八本书逐书模块状态

| 书 | 1 `toc_structure` | 2 `book_note_type` | 3 `chapter_split` | 4 `note_linking` | 5 `ref_freeze` | 6 `chapter_merge` | 7 `book_assemble` | 当前修补入口 |
|---|---|---|---|---|---|---|---|---|
| `Biopolitics` | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 | 无 |
| `Germany_Madness` | 通过 | 通过 | 通过 | 通过 | 未通过（`freeze_unit_contract_invalid`） | 阻塞 | 阻塞（当前虽报 `export_semantic_contract_broken`，但先不修） | `ref_freeze` |
| `Goldstein` | 通过 | 通过 | 未通过（book endnote region 绑章错误） | 阻塞（当前已报 `link_*`，但先不修） | 阻塞（当前已报 `freeze_*`，但先不修） | 阻塞 | 阻塞 | `chapter_split` |
| `Heidegger_en_France` | 未通过（`toc_chapter_order_non_monotonic`） | 阻塞 | 阻塞 | 阻塞 | 阻塞 | 阻塞 | 阻塞 | `toc_structure` |
| `Mad_Act` | 通过 | 通过 | 未通过（正文/脚注分区错，导致 marker 污染正文） | 阻塞（先等重切后重跑） | 阻塞（当前已报 `freeze_*`，但先不修） | 阻塞 | 阻塞 | `chapter_split` |
| `Napoleon` | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 | 无 |
| `Neuropsychoanalysis_Introduction` | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 | 无 |
| `Neuropsychoanalysis_in_Practice` | 未通过（`toc_chapter_order_non_monotonic`、`toc_role_semantics_invalid`） | 阻塞 | 阻塞（当前虽报 `split_footnote_only_synthesis_failed`，但先不修） | 阻塞 | 阻塞 | 阻塞 | 阻塞 | `toc_structure` |

## 当前执行顺序

按模块顺序、且只进入“当前修补入口”的做法，当前实际执行顺序应当是：

1. 先清 `toc_structure`
   - `Heidegger_en_France`
   - `Neuropsychoanalysis_in_Practice`
2. 再清 `chapter_split`
   - `Goldstein`
   - `Mad_Act`
3. 再清 `ref_freeze`
   - `Germany_Madness`
4. `note_linking`、`chapter_merge`、`book_assemble` 暂不单独立项
   - 只有对应上游模块通过并重跑后仍失败，才进入这些模块

## 禁止事项

下面这些事当前都不应该做：

- 在 `Goldstein` 上直接改 `note_linking` 特判
- 在 `Mad_Act` 上直接改 `freeze` 而不先处理正文/脚注切分
- 在 `Germany_Madness` 上先修导出语义，而不先修 `freeze`
- 在 `Neuropsychoanalysis_in_Practice` 上先修 `split`，而不先修 TOC 编号和 role
- 在 `Heidegger_en_France` 上跳过 TOC 顺序问题去碰后续模块
