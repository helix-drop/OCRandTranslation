# 下一部分详细计划：`chapter_merge` 与 `book_assemble`

## 概要

当前 `ref_freeze` 已完成并通过 Biopolitics 验收，下一部分按 [FNM_RE/MODULS.md](/Users/hao/OCRandTranslation/FNM_RE/MODULS.md) 和 [FNM_RE/Overview.md](/Users/hao/OCRandTranslation/FNM_RE/Overview.md) 固定为两个模块一起落地：

- `chapter_merge`：把译后正文和本章注释定义合成单章 Markdown。
- `book_assemble`：按模块一的目录顺序组装整书导出物并执行整书审计。

本部分的阶段边界必须保持清楚：

- `ref_freeze` 只负责 token 冻结和 unit 规划，不解冻。
- `chapter_merge` 是唯一允许做 `NOTE_REF -> [^n]`、raw marker fallback、本章局部编号的地方。
- `book_assemble` 只负责顺序装配、打包、审计，不回头改写章节内容。

## 关键变更

### 模块六：`chapter_merge`

新增入口：

```python
build_chapter_markdown_set(
    frozen_units,
    note_link_table,
    chapter_layers,
    *,
    diagnostic_machine_by_page=None,
    include_diagnostic_entries=False,
) -> ModuleResult[ChapterMarkdownSet]
```

新增类型：

- `ChapterMarkdownEntry`
  - `order`、`chapter_id`、`title`、`path`、`markdown_text`、`start_page`、`end_page`、`pages`
- `ChapterMarkdownSet`
  - `chapters`
  - `chapter_contract_summary`
  - `merge_summary`

实现固定拆成 5 个子流程：

- `6A translated_body_resolve`
  - 正文文本回退链固定为：`translated_text -> diagnostic_machine_by_page -> source_text -> [待翻译]`
  - 保留旧行为：若正文仍含冻结 token 且本章没有可用注释定义，输出 `[待翻译]`，不能把半成品正文继续往后传。
- `6B frozen_ref_thaw`
  - 只在这里做 `{{NOTE_REF:*}} -> [^n]`
  - 编号是“本章局部编号”，按正文中首次出现顺序确定，不按 note item 原顺序编号
- `6C raw_marker_fallback_rewrite`
  - 只在这里重写 raw marker
  - 覆盖方括号、HTML/LaTeX 上标、Unicode 上标、OCR alias
  - fallback 的 note 归属只允许来自本章 matched link 序列
- `6D note_definition_assembly`
  - 只导出“正文实际引用到”的 notes
  - 注释文本优先 `translated_text`，否则 `source_text`
  - 继续复用旧清洗规则，去掉定义前缀 marker 和正文残留 markup
- `6E chapter_markdown_emit`
  - 每个 exportable chapter 恰好产出一个 `.md`
  - 文件名继续走旧标题清洗和命名规则
  - section heads 继续按旧过滤规则排除伪标题
  - 尾部图片块清洗保留

hard gate 固定为：

- `merge.chapter_files_emitted`
- `merge.local_refs_closed`
- `merge.no_frozen_ref_leak`
- `merge.no_raw_marker_leak_in_body`

soft gate 固定为：

- `merge.image_tail_warn`
- `merge.section_heading_warn`

### 模块七：`book_assemble`

新增入口：

```python
build_export_bundle(
    chapter_markdown_set,
    toc_structure,
    *,
    slug="",
    doc_id="",
) -> ModuleResult[ExportBundle]
```

新增类型：

- `ExportAuditFile`
- `ExportAuditReport`
- `ExportBundle`
  - `index_markdown`
  - `chapters`
  - `chapter_files`
  - `files`
  - `zip_bytes`
  - `audit_report`
  - `semantic_summary`

实现固定拆成 4 个子流程：

- `7A chapter_ordering`
  - 导出顺序只信任 `toc_structure.chapters` 的顺序投影
  - 禁止再按 `start_page` 排序
- `7B book_file_assembly`
  - 生成 `index.md`
  - 生成 `chapters/*.md`
  - `files` 作为最终 bundle 真相
- `7C zip_bundle`
  - 由 `files` 直接打出 zip bytes
- `7D export_audit`
  - 继续复用旧 `export.py` 语义合同和 `export_audit.py` 规则
  - 只检查整书问题：顺序、跨章污染、重复段、raw marker、容器误导出、post_body 缺失、导出深度不足
  - 不得在这里回写章节内容

hard gate 固定为：

- `export.order_follows_toc`
- `export.semantic_contract_ok`
- `export.audit_can_ship`
- `export.no_cross_chapter_contamination`
- `export.no_raw_marker_leak_book_level`

## 测试计划

新增：

- `tests/unit/test_fnm_re_module6_merge.py`
- `tests/unit/test_fnm_re_module7_export.py`

`test_fnm_re_module6_merge.py` 必测：

- 译文优先级：手动译文 > 诊断页机器译文 > source > `[待翻译]`
- `{{NOTE_REF:*}}` 会改写为本章局部 `[^n]`
- raw bracket / sup / unicode marker 会改写为本地引用
- 只有被正文引用的 notes 才生成定义
- 每个 `[^n]` 都有定义，且没有 orphan definition
- 伪 section head 被过滤
- 尾部 image-only block 被移除
- 章节文件中不残留 `{{NOTE_REF:*}}`
- 正文区不残留 raw marker

`test_fnm_re_module7_export.py` 必测：

- 章节顺序与 `toc_structure.chapters` 一致
- `index.md` 链接顺序与章节顺序一致
- `missing_post_body_export` 会阻断
- `container_exported_as_chapter` 会阻断
- `export_depth_too_shallow` 会阻断
- 跨章污染会阻断
- 整书级 raw marker 残留会阻断
- `audit_report.can_ship` 与 gate 一致

验收命令固定为：

```bash
python3 -m unittest \
  tests.unit.test_fnm_re_module1_toc \
  tests.unit.test_fnm_re_module2_book_type \
  tests.unit.test_fnm_re_module3_split \
  tests.unit.test_fnm_re_module4_linking \
  tests.unit.test_fnm_re_module5_freeze \
  tests.unit.test_fnm_re_module6_merge \
  tests.unit.test_fnm_re_module7_export
```

回归护栏固定为：

```bash
python3 -m unittest tests.unit.test_fnm_re_phase6
```

## 文档与默认假设

文档同步固定为：

- `FNM_RE/OnWorking.md` 新增本批次记录
- `FNM_RE/DEV_FNM.md` 更新为 `chapter_merge/book_assemble` 执行后口径
- `verification.md` 记录模块 1 到 7 与 `phase6` 回归结果
- `TEST.md` 只同步阶段 4 完成状态，不改前序模块口径

默认假设固定为：

- 本计划按 `Overview` 的“下一部分”执行，两个模块一起规划，但实现顺序固定为 `chapter_merge` 在前、`book_assemble` 在后。
- `chapter_merge` 的输入是“已回填译文结果”的 `FrozenUnits`；不会再回头读取旧 `phase5` 结构。
- `diagnostic_machine_by_page` 作为可选输入保留，只为兼容旧导出回退链，不引入新的模块真相对象。
- 本部分不改 `app/pipeline.py`、`app/mainline.py`、`status.py`，主线切换留到下一阶段。
