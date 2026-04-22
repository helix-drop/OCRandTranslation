# 阶段 3 详细计划：`note_linking` 正文锚点与注释链接

## 概要

已核对阶段 2 状态，当前可以进入下一阶段：

- `build_chapter_layers`、阶段 2 类型、对外导出、`test_fnm_re_module3_split.py` 都已落地。
- 文档口径与代码一致：`FNM_RE/OnWorking.md`、`FNM_RE/DEV_FNM.md`、`verification.md` 都已同步到 stage2。
- 本地复核通过：`python3 -m unittest tests.unit.test_fnm_re_module1_toc tests.unit.test_fnm_re_module2_book_type tests.unit.test_fnm_re_module3_split` 为 `12 tests OK`。

进入阶段 3 的原因也很明确：旧 `phase3` 在 Biopolitics 上当前仍有真实链接问题。实测基线为 `480` 个 anchors、`490` 个 links，其中 `matched=364`、`footnote_orphan_anchor=44`、`endnote_orphan_note=64`、`endnote_orphan_anchor=7`、`ambiguous=11`。下一阶段必须把“链接是否成立”收成单点模块和单点 gate。

## 接口与实现变更

新增模块入口：

```python
build_note_link_table(
    chapter_layers,
    pages,
    *,
    overrides=None,
) -> ModuleResult[NoteLinkTable]
```

这里明确修正模块合同：`note_linking` 不能只吃 `ChapterLayers`，还必须显式接收原始 `pages`。原因是 `4A anchor_collection` 需要继续扫描 markdown 段落和 OCR blocks；阶段 2 当前输出不保留足够的原始页面结构，不能靠隐式回查。

在 `FNM_RE/modules/types.py` 增加：

- `BodyAnchorLayer`：基本沿用旧 `BodyAnchorRecord` 字段，保留 `synthetic`、`ocr_repaired_from_marker`。
- `NoteLinkLayer`：基本沿用旧 `NoteLinkRecord` 字段。
- `ChapterLinkContract`：包含 `chapter_id`、`requires_endnote_contract`、`book_type`、`note_mode`、`first_marker_is_one`、`endnotes_all_matched`、`no_ambiguous_left`、`no_orphan_note`、`endnote_only_no_orphan_anchor`、`failure_link_ids`。
- `NoteLinkTable`：包含 `anchors`、`links`、`effective_links`、`chapter_link_contracts`、`anchor_summary`、`link_summary`。

实现固定拆成 4 个子流程：

- `4A anchor_collection`
  - 只扫描 `chapter_layers.chapters[].body_pages` 对应页。
  - 复用 `shared/anchors.py` 的 `page_body_paragraphs()`、`scan_anchor_markers()`、`looks_like_year_marker()`、`resolve_anchor_kind()`。
  - 复用 `body_anchors.py` 的页键去重逻辑。
  - `anchor_kind` 不重新猜书型，只读 `chapter.policy_applied["note_mode"]`；`footnote band` 页由 `chapter_layers.regions` 的 footnote region 判定。
  - 输出 `BodyAnchorLayer[]` 与 `anchor_summary`。

- `4B direct_match`
  - 先 endnote，再 footnote。
  - 先同章、同 marker、同 kind 直接匹配。
  - footnote 必须保留页距窗口约束。
  - book-scope endnote、fallback chapter、toc chapter 的跨章匹配规则，直接继承旧 `note_links.py` 现有行为。

- `4C repair_match`
  - 继续复用 `_marker_digits_are_ordered_subsequence`、`_nearest_unique_candidate`、`_make_synthetic_anchor`。
  - synthetic anchor 只允许出现在 footnote repair，且必须显式标记 `synthetic=True`，不能伪装成正常命中。
  - OCR 缩短 marker 修补后，原 marker 要写入 `ocr_repaired_from_marker`。

- `4D chapter_link_contract`
  - contract 适用条件固定为：该章存在 `endnote_items` 或 `endnote_regions`。不能只看 `note_mode`，因为 Biopolitics 当前数据里“章有 endnote item”与“章级 mode”并不完全一一对应。
  - `links` 保留原始结果；`effective_links` 才用于 gate 和后续 `ref_freeze`。
  - `overrides` 采用现有 grouped 结构，只支持 `link` scope：
    - `{"link": {"<link_id>": {"action": "ignore"}}}`
    - `{"link": {"<link_id>": {"action": "match", "note_item_id": "...", "anchor_id": "..."}}}`
  - `ignore` 只改 `effective_links`，不改原始 `links`。
  - `match` 只有在 `note_item_id`、`anchor_id` 都存在且 chapter/note_kind 一致时才生效；无效 override 记入 `invalid_override_count` 和 `review_flags`。

对外导出：

- 新增 `FNM_RE/modules/note_linking.py`
- 更新 `FNM_RE/modules/__init__.py`
- 更新 `FNM_RE/__init__.py`

## Gate 与验收口径

模块 hard gate 固定为：

- `link.first_marker_is_one`
  - 仅对 `requires_endnote_contract=true` 的章节统计。
  - 该章 endnote item 的首个有效 numeric marker 必须为 `1`，除非显式 override 已把异常 link 处理掉。

- `link.endnotes_all_matched`
  - contract 章节内所有 endnote item 都必须在 `effective_links` 中为 `matched`。

- `link.no_ambiguous_left`
  - contract 章节内不得残留 `ambiguous`。

- `link.no_orphan_note`
  - contract 章节内不得残留 `orphan_note`。

- `link.endnote_only_no_orphan_anchor`
  - 仅在 `book_type == "endnote_only"` 时生效。
  - 对 Biopolitics 这类 `mixed` 书，hard 直接放行为 `true`，并在 evidence 记录 `not_applicable`。

soft gate 固定为：

- `link.footnote_orphan_anchor_warn`
  - 非 `endnote_only` 书允许存在，但必须计数并输出 `orphan_anchor_ids`。
- `link.synthetic_anchor_warn`
  - 只要用了 synthetic anchor 就提示，不阻塞。

Biopolitics 的阶段 3 硬验收固定为：

- `build_note_link_table()` 在 Biopolitics 上返回的 hard gate 全真。
- `link.endnotes_all_matched=true`
- `link.no_ambiguous_left=true`
- `link.no_orphan_note=true`
- `link.endnote_only_no_orphan_anchor=true` 且 evidence 标明 `not_applicable`
- `footnote_orphan_anchor` 允许只做 soft warn，不作为本阶段阻塞项。

## 测试计划

新增：

```text
tests/unit/test_fnm_re_module4_linking.py
```

必须覆盖的用例：

- Biopolitics 主路径：阶段 1+2 产物接入后，`build_note_link_table()` hard gate 全真。
- year-like marker 过滤：`[2020]` 不能当注释锚点。
- note definition line 过滤：脚注定义行、尾注定义行不能反向产出 body anchor。
- note/other 页不产出 body anchor：只扫 `body_pages`。
- synthetic footnote anchor：允许创建，但不能再额外产出对应 orphan anchor。
- 显式 anchor 优先于 synthetic：有真实 anchor 时要替换 synthetic 命中。
- OCR 缩短 marker repair：`12 -> 123` 这类修补要落到 repaired anchor 上。
- chapter-scope endnote 不得跨章误配。
- fallback/toc/book-scope endnote 可按旧规则跨章修补。
- ambiguous 候选保持 `ambiguous`，不能偷偷择一。
- unique nearest footnote 候选必须命中最近且唯一的 anchor。
- 未使用显式 anchor 生成 `orphan_anchor`。
- `ignore` override 只改 `effective_links`，原始 `links` 不变。
- `match` override 成功时，`effective_links` 变为 `matched`；失败时进入 `invalid_override_count`。
- chapter contract 的适用条件按 `endnote_items/endnote_regions` 判定，不按 `note_mode` 简化。

验收命令固定为：

```bash
python3 -m unittest \
  tests.unit.test_fnm_re_module1_toc \
  tests.unit.test_fnm_re_module2_book_type \
  tests.unit.test_fnm_re_module3_split \
  tests.unit.test_fnm_re_module4_linking
```

回归护栏固定为：

```bash
python3 -m unittest \
  tests.unit.test_fnm_re_phase3 \
  tests.unit.test_fnm_re_phase4 \
  tests.unit.test_fnm_re_module1_toc \
  tests.unit.test_fnm_re_module2_book_type \
  tests.unit.test_fnm_re_module3_split \
  tests.unit.test_fnm_re_module4_linking
```

## 文档与默认假设

文档同步范围固定为：

- `FNM_RE/OnWorking.md` 新增批次 `12（stage3-note-linking）`
- `FNM_RE/DEV_FNM.md` 更新“当前状态”为 stage3 执行后
- `verification.md` 记录本轮 unittest 结果与 Biopolitics gate 结果
- `TEST.md` 与 `FNM_RE/MODULS.md` 同步修正 `note_linking` 输入合同为 `ChapterLayers + pages`

默认假设固定为：

- 本阶段只做 `note_linking`，不并入 `ref_freeze`。
- 不改 mainline、不切主流程、不补兼容层。
- 后续 `ref_freeze` 只消费 `effective_links`，不会重新应用 override。
- Biopolitics 是唯一硬验收样本；其他样本本阶段只要求不破坏旧 phase3/phase4 护栏测试。
