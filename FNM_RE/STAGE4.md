# 阶段 3 下半段详细计划：`ref_freeze` 引用冻结与 Unit 规划

## 概要

当前状态已经满足进入下一部分：`note_linking` 已落地，Biopolitics 的链接 hard gate 为真，模块 1 到 4 和旧 `phase5` 护栏测试也都可用。下一部分按 [FNM_RE/MODULS.md](/Users/hao/OCRandTranslation/FNM_RE/MODULS.md) 与 [FNM_RE/Overview.md](/Users/hao/OCRandTranslation/FNM_RE/Overview.md) 固定为模块五 `ref_freeze`，职责只做 4 件事：筛选可冻结 link、注入 `NOTE_REF`、产出翻译 unit、闭合冻结记账。

本阶段不改 `note_linking` 规则，不做解冻，不生成章节 markdown，不接 mainline。`ref_freeze` 只消费 `ChapterLayers` 和 `NoteLinkTable.effective_links`，不再回头重新切正文或重算链接。

## 关键实现

### 对外接口与类型

新增入口：

```python
build_frozen_units(
    chapter_layers,
    note_link_table,
    *,
    max_body_chars=6000,
) -> ModuleResult[FrozenUnits]
```

在 `FNM_RE/modules/types.py` 新增：

- `FrozenRefEntry`
  - `link_id`、`chapter_id`、`anchor_id`、`note_item_id`、`target_ref`
  - `decision`：`"injected"` 或 `"skipped"`
  - `reason`：固定为 `synthetic_anchor / conflict_anchor / duplicate_anchor / missing_anchor / missing_body_page / token_not_found`
  - `page_no`
- `FrozenUnit`
  - 字段与现有 `TranslationUnitRecord` 对齐：`unit_id / kind / owner_kind / owner_id / section_id / section_title / section_start_page / section_end_page / note_id / page_start / page_end / char_count / source_text / translated_text / status / error_msg / target_ref / page_segments`
- `FrozenUnits`
  - `body_units`
  - `note_units`
  - `ref_map`
  - `freeze_summary`

对外导出同步更新：

- `FNM_RE/modules/ref_freeze.py`
- `FNM_RE/modules/__init__.py`
- `FNM_RE/__init__.py`

### 5A `freezable_link_selection`

- 只读取 `note_link_table.effective_links` 中 `status == "matched"` 的 link。
- 对每条 matched link 建立 `FrozenRefEntry`，不能静默丢失。
- 只允许显式非 synthetic anchor 进入注入候选；以下情况必须转为 `skipped`：
  - anchor 是 synthetic
  - anchor 命中 conflict（同一 anchor 对应多个 note_id）
  - anchor 缺失
  - anchor 已被本章前序 link 使用过
  - anchor 对应页不在当前章 `body_pages`
  - 注入时找不到 marker 文本
- `ref_map` 的排序固定为旧 `_link_sort_key` 口径：`page_no ASC, char_start DESC, link_id ASC`。

### 5B `token_injection`

- 只在 `chapter_layers.chapters[].body_pages` 的克隆副本上工作，不修改输入对象。
- 注入 token 统一使用 `frozen_note_ref(note_item_id)`，格式固定为 `{{NOTE_REF:<note_id>}}`。
- 注入规则固定继承旧 `units.py`：
  - 先尝试 `anchor.source_marker`
  - 再尝试 `[marker]`
  - 再尝试正则 bracket fallback
  - 每个 anchor 最多注入一次
- 不重新做正文/注释切线；正文来源只信任阶段 2 的 `body_pages`。

### 5C `translation_unit_planning`

- body unit 生成流程固定为：
  - 使用注入后的 `body_pages` 作为 `frozen_body_pages`
  - 使用 `replace_frozen_refs()` 后的可读文本作为 `obsidian_body_pages`
  - 调用 `_segment_paragraphs_from_body_pages`
  - 调用 `_chunk_body_page_segments(max_body_chars)`
  - 为每个 chunk 生成一个 `FrozenUnit(kind="body")`
- note unit 生成流程固定为：
  - `chapter_layers.note_items` 中每个 note item 生成一个 `FrozenUnit`
  - `kind` 为 `footnote` 或 `endnote`
  - `target_ref` 固定等于 `{{NOTE_REF:<note_id>}}`
  - `owner_kind="note_region"`，`owner_id=region_id`
- 输出顺序固定为 chapter order；后续如需投影给现有 worker，合并顺序固定为同章 `body` 在前、`note` 在后，排序键为 `(chapter_order, kind_rank, page_start, unit_id)`。

### 5D `freeze_audit`

`freeze_summary` 必须至少包含：

- `matched_link_count`
- `injected_count`
- `skipped_count`
- `skip_reason_counts`
- `synthetic_skipped_count`
- `conflict_anchor_count`
- `body_unit_count`
- `note_unit_count`
- `chapter_unit_counts`
- `empty_body_chapter_count`
- `max_body_chars`

hard gate 固定为：

- `freeze.only_matched_frozen`
- `freeze.no_duplicate_injection`
- `freeze.accounting_closed`
- `freeze.unit_contract_valid`

soft gate 固定为：

- `freeze.synthetic_skip_warn`
- `freeze.conflict_skip_warn`

判定口径固定为：

- `freeze.only_matched_frozen=true`：所有 `decision=="injected"` 的 `FrozenRefEntry` 都来自 `effective_links.matched`
- `freeze.no_duplicate_injection=true`：同一 anchor 不出现两次注入
- `freeze.accounting_closed=true`：每条 matched link 在 `ref_map` 中恰好有一条记录，且 `decision` 为 `injected` 或 `skipped`
- `freeze.unit_contract_valid=true`：所有 `FrozenUnit` 必填字段齐全；note unit 的 `target_ref` 非空；body unit 的 `target_ref` 为空；`page_segments` 类型合法

## 测试计划

新增：

- `tests/unit/test_fnm_re_module5_freeze.py`

必须覆盖：

- Biopolitics 主路径：模块 1 到 5 串跑时，`freeze.*` hard gate 全真。
- matched 显式 anchor 会注入 `{{NOTE_REF:*}}`。
- `ignored / ambiguous / orphan` link 不会注入 token。
- synthetic anchor 会被跳过，并进入 `synthetic_skipped_count`。
- conflict anchor 会被跳过，并进入 `conflict_anchor_count`。
- `token_not_found` 会形成 `skipped(reason="token_not_found")`，且 `freeze.accounting_closed=true`。
- 每个 note item 都生成 note unit，且 `target_ref` 正确。
- body unit 的 `source_text` 保留冻结 token；可读层通过 `replace_frozen_refs()` 进入 `page_segments` 的 display 视图。
- 构建过程不允许修改输入的 `chapter_layers` 和 `note_link_table`。

验收命令固定为：

```bash
python3 -m unittest \
  tests.unit.test_fnm_re_module1_toc \
  tests.unit.test_fnm_re_module2_book_type \
  tests.unit.test_fnm_re_module3_split \
  tests.unit.test_fnm_re_module4_linking \
  tests.unit.test_fnm_re_module5_freeze
```

回归护栏固定为：

```bash
python3 -m unittest tests.unit.test_fnm_re_phase5
```

## 文档与默认假设

文档同步固定为：

- `FNM_RE/OnWorking.md` 新增批次 `13（stage3-ref-freeze）`
- `FNM_RE/DEV_FNM.md` 更新为 `stage3(ref_freeze) 执行后`
- `verification.md` 记录模块 1 到 5 回归结果
- `TEST.md` 只同步阶段 3 已完成状态，不改阶段边界
- `MODULS.md` 和 `Overview.md` 仅在接口签名与当前文档不一致时才更新；本计划默认它们的阶段边界不变

默认假设固定为：

- `ref_freeze` 不接受 override；所有 override 只在 `note_linking` 中完成并体现在 `effective_links`。
- `chapter_layers.body_pages` 是正文唯一真相，本阶段不回查原始 `pages`。
- 本阶段不改 SQLite、不改 `status.py`、不切换主线、不删除旧 phase。
- 本阶段不做 `NOTE_REF` 解冻、不做本章 `[^n]` 编号、不生成章节 markdown；这些都留给下一部分 `chapter_merge`。
