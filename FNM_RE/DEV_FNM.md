# DEV_FNM

这份文档只盘点当前仓库里 `FNM_RE/` 的真实代码状态，基于当前工作区代码，而不是基于旧计划文档的理想目标。

## 1. 当前状态结论

### 1.1 当前判断口径

当前如果要判断 `FNM_RE` 是否“已经收口”，必须优先看：

1. [PROGRESS.md](/Users/hao/OCRandTranslation/PROGRESS.md) 顶部最新记录
2. [verification.md](/Users/hao/OCRandTranslation/verification.md) 顶部“当前状态”
3. 当前代码里的 `FNM_RE/status.py` gate 逻辑

注意：

- `PROGRESS.md` 和 `verification.md` 下面保留了很多更早的“单书通过 / can_ship=True”历史记录。
- 这些历史记录有参考价值，但**不能当作当前结论**。
- 目前的当前口径，以 `2026-04-15 stage6(mainline + snapshot + gate summary) 收口后` 为准。

### 1.2 2026-04-15 最新状态（stage6 mainline-snapshot 收口后）

当前真实状态是“阶段 6 主线收口已完成，可用”，具体为：

1. `phase1 ~ phase7` 仍是当前运行主线，回归稳定。
2. 已新增模块化目录 `FNM_RE/modules/`，并落地：
   - `toc_structure`
   - `book_note_type`
   - `chapter_split`
   - `note_linking`
   - `ref_freeze`
   - `chapter_merge`
   - `book_assemble`
   - `ModuleResult / GateReport` 协议与阶段 1~7 业务对象。
3. 主线已切到 `pipeline snapshot`：`load_phase6_for_doc()` 通过 `_load_module_snapshot_for_doc()` 返回 `snapshot.phase6_shadow`。
4. `status.py` 的模块 gate 汇总已收口：`build_module_gate_status(...)` 统一消费模块 hard gate/reasons 并产出最终 `StructureStatusRecord`。
5. consumer 同步已完成：`web/pipeline/translation/scripts/persistence` 统一从 `FNM_RE` 公开入口取状态、导出、诊断与重建。
6. phase 专用 API 已从公开导出面移除，`FNM_RE`/`FNM_RE.app` 仅保留通用 doc 级 API 与模块 API。

按本轮阶段 6 的 Biopolitics 快照：

- `Biopolitics`
  - `toc_structure`：`toc.pages_classified / toc.has_exportable_chapters / toc.chapter_titles_aligned / toc.chapter_order_monotonic / toc.role_semantics_valid` 全部为真。
  - 导出章节计数：`chapter=12`，`post_body=2`（`RÉSUMÉ DU COURS`、`SITUATION DES COURS`）。
  - `book_note_type`：`book_type=mixed`，且 `book_type.resolved / book_type.chapter_modes_consistent / book_type.no_unapproved_review_required` 全部为真。
  - `chapter_split`：`split.regions_bound / split.items_extracted / split.body_note_disjoint / split.cross_page_continuity_ok / split.policy_applied / split.footnote_only_synthesized / split.mixed_marker_materialized` 全部为真。
  - `note_linking`：`link.first_marker_is_one / link.endnotes_all_matched / link.no_ambiguous_left / link.no_orphan_note / link.endnote_only_no_orphan_anchor` 全部为真（其中 `endnote_only_no_orphan_anchor` 在 `mixed` 下为 `not_applicable`）。
  - `ref_freeze`：`freeze.only_matched_frozen / freeze.no_duplicate_injection / freeze.accounting_closed / freeze.unit_contract_valid` 全部为真。
  - `chapter_merge`：`merge.chapter_files_emitted / merge.local_refs_closed / merge.no_frozen_ref_leak / merge.no_raw_marker_leak_in_body` 全部为真。
  - `book_assemble`：`export.order_follows_toc / export.semantic_contract_ok / export.audit_can_ship / export.no_cross_chapter_contamination / export.no_raw_marker_leak_book_level` 全部为真。
  - 当前软告警仍有：`link.footnote_orphan_anchor_warn`、`link.synthetic_anchor_warn`、`freeze.synthetic_skip_warn`（不阻塞当前阶段硬验收）。

`FNM_RE` 现在已经不是“纯实验目录”，而是实际接入了 FNM 主链的一套新实现。当前真实状态如下：

1. 分阶段构建链已经完整落到 `phase1 ~ phase6`，phase7 的 doc/repo-aware 接线层也已经存在。
2. 代码侧的主入口已经是 `FNM_RE/app/mainline.py`，而不是只靠 `app/pipeline.py` 做纯函数拼装。
3. 公开消费入口已经统一收口到 `FNM_RE`：`run_doc_pipeline/load_doc_structure/build_doc_status/build_export_bundle_for_doc/list_diagnostic_*`。
4. `FNM_RE` 仍有待继续收敛的实现债：
   - `FNM_RE/stages/chapter_skeleton.py` 仍直接依赖旧 `fnm.fnm_structure._build_visual_toc_chapters_and_section_heads`
   - `FNM_RE/app/mainline.py` 仍调用旧 `group_review_overrides()`、`resolve_manual_toc_state()`、`load_auto_visual_toc_from_disk()` 等 repo/接线辅助

一句话总结：`FNM_RE` 现在已经是“已切换并可用的实际主线”，当前问题主要是复杂度与后续重构，而不是 cutover 断点。

### 1.3 2026-04-16 运行异常收敛（视觉目录与首页状态）

围绕用户侧当前可感知问题，本轮新增了三条运行时口径：

1. 视觉目录请求若出现非可重试 `HTTP 400`，现在会立即失败并返回可读错误（含 stage/状态码），不再“吞异常继续重试”。
2. `needs_offset` 判定从“所有目录项都必须有页码”改为“仅可导航目录项必须可定位”，容器/前后附录不再误触发阻塞。
3. 首页 FNM 状态轮询对非 2xx 与非 JSON 响应会直接显示失败原因，不再长期停在“等待 FNM 状态…”占位。

### 1.4 2026-04-16 翻译报错收敛（致命错误快速终止 + 实时仪表）

本轮新增两条翻译运行口径：

1. 对翻译上游 `HTTP 400/401/403/404/422` 统一归类为不可重试错误（`NonRetryableProviderError`），worker 立即终止并写明错误，不再逐页刷错。
2. `api_doc_fnm_status` 现已对外提供实时翻译态字段（`translate_phase`、`translate_last_error`、`translate_log_relpath`、`draft_status`、`draft_para_done/total` 等），首页 FNM 卡片会直接显示“正在翻译哪一段、当前流状态、最近错误、日志路径”。

### 1.5 2026-04-16 重启状态与 FNM 继续入口收口

本轮新增三条用户侧口径：

1. 首页在 `current_doc_id` 丢失或失效时，会自动回退到已有文档，避免重启后落到空文档导致状态长期不可见。
2. `/api/doc/<doc_id>/fnm/status` 新增 `workflow_state/workflow_state_label/state_hint/continue_fnm_available/resume_translate_available`，可区分“继续处理中 / 可继续翻译 / 结构阻塞”等阶段。
3. 新增 `POST /api/doc/<doc_id>/fnm/continue` 异步入口；首页 FNM 卡片增加“继续 FNM 处理”按钮，且“开始翻译”会在可恢复场景自动切成“继续翻译”。

### 1.6 2026-04-16 FNM 一体化流程入口

本轮将用户操作口径进一步收敛成“单入口流程”：

1. 新增 `POST /api/doc/<doc_id>/fnm/full-flow`，后台按“必要时先结构重建，再自动进入 FNM 翻译”执行。
2. 首页开始按钮改为调用 `fnm/full-flow`，在未就绪时文案显示“开始一体化流程”，就绪后自动回到“开始/继续翻译”。
3. 冻结/解冻合同保持不变：`ref_freeze` 负责 `NOTE_REF` 冻结，翻译回写时由 `replace_frozen_refs(...)` 解冻并落库，最终条目维持 `original + translation + heading_level` 结构。

## 2. 代码规模

下面的行数统计只计算 `FNM_RE/**/*.py`，不包含 `PLAN*.md`、`README.md`、`__pycache__`、`.DS_Store`。

### 2.1 目录级行数

| 目录 | 行数 |
|---|---:|
| `FNM_RE/` 根目录 Python 文件 | 1207 |
| `FNM_RE/app/` | 1926 |
| `FNM_RE/shared/` | 845 |
| `FNM_RE/stages/` | 6094 |
| 合计 | 10072 |

### 2.2 复杂度最高的文件

| 文件 | 行数 |
|---|---:|
| `FNM_RE/stages/chapter_skeleton.py` | 1173 |
| `FNM_RE/app/mainline.py` | 992 |
| `FNM_RE/stages/export.py` | 914 |
| `FNM_RE/app/pipeline.py` | 901 |
| `FNM_RE/stages/units.py` | 764 |
| `FNM_RE/stages/export_audit.py` | 652 |
| `FNM_RE/stages/note_links.py` | 639 |
| `FNM_RE/models.py` | 579 |
| `FNM_RE/stages/note_regions.py` | 568 |
| `FNM_RE/status.py` | 516 |

`FNM_RE` 的主要复杂度已经明显集中在五块：

1. 章节骨架
2. doc/repo 接线
3. 导出拼装
4. 翻译单元规划
5. 导出审计与链接修补

## 3. 当前实际业务流程

### 3.1 纯阶段流水线

`FNM_RE/app/pipeline.py` 负责纯阶段函数的拼装，当前真实流程是：

```text
pages
  -> phase1: page_partition -> chapter_skeleton -> section_heads
  -> phase2: note_regions -> note_items -> chapter_note_modes
  -> phase3: body_anchors -> note_links
  -> phase4: overrides -> structure_reviews -> phase4 status
  -> phase5: translation_units -> diagnostic_pages/diagnostic_notes
  -> phase6: export_bundle -> export_audit -> phase6 status
```

对应入口函数：

- `build_phase1_structure()`
- `build_phase2_structure()`
- `build_phase3_structure()`
- `build_phase4_structure()`
- `build_phase5_structure()`
- `build_phase6_structure()`

这条链路的特点是：

1. 上游阶段产真相层，下游阶段只消费，不回写上游对象。
2. 真正带 repo/doc 概念的逻辑不写在这里，而是下沉到 `app/mainline.py`。
3. phase4 以后开始引入“effective”概念：
   - `effective_note_links`
   - phase6 status/export gate

### 3.1.1 这条 phase 流水线现在真正负责什么

按当前代码现实，这 6 个阶段大致分工如下：

1. `phase1`
   - 页面分区
   - 章节骨架
   - 章内标题
2. `phase2`
   - note region
   - note item
   - chapter note mode
3. `phase3`
   - 正文 anchor
   - anchor 与 note item 的匹配
4. `phase4`
   - review override
   - structure review
   - 结构 gate
5. `phase5`
   - frozen ref
   - translation unit
   - diagnostic 投影
6. `phase6`
   - 按章导出
   - export audit
   - 导出 gate

### 3.2 真实 doc 级主线

`FNM_RE/app/mainline.py` 才是当前最接近生产的实际业务流程。

真实运行路径如下：

```text
run_phase6_pipeline_for_doc(doc_id)
  -> 读 repo 中 pages / toc / review overrides / manual toc state / latest run
  -> load_phase6_for_doc(doc_id)
      -> _load_phase5_for_doc()
          -> build_phase5_structure(...)
          -> 可选叠加 repo 里已有 translation units 结果
      -> build_export_bundle(...)
      -> audit_phase6_export(...)
      -> build_phase6_status(...)
  -> _persist_phase6_to_repo(...)
      -> replace_fnm_structure(...)
      -> replace_fnm_data(...)
      -> update_fnm_run(...)
```

同时，`mainline.py` 还承担了当前所有 doc 级只读接口：

- `build_phase6_status_for_doc()`
- `build_phase6_export_bundle_for_doc()`
- `build_phase6_export_zip_for_doc()`
- `audit_phase6_export_for_doc()`
- `list_phase6_diagnostic_notes_for_doc()`
- `list_phase6_diagnostic_entries_for_doc()`
- `get_phase6_diagnostic_entry_for_doc()`

### 3.3 当前消费者接线状态（stage6）

当前代码的消费接线已统一到 `FNM_RE` 主入口，不再依赖 `fnm_re_mainline` 条件切换：

1. **主线装配单轨**
   - `load_phase6_for_doc()` 固定走 `_load_module_snapshot_for_doc() -> build_module_pipeline_snapshot() -> snapshot.phase6_shadow`。

2. **公开 API 单轨**
   - `run_doc_pipeline()`、`build_doc_status()`、`build_export_bundle_for_doc()`、`build_export_zip_for_doc()`、`list_diagnostic_*()` 全部由 `FNM_RE/__init__.py` 统一导出。

3. **调用方同步完成**
   - `web/`、`pipeline/`、`translation/`、`scripts/`、`persistence/` 已统一从 `FNM_RE` 导入对应入口。
   - 代码检索 `rg -n "fnm_re_mainline" --glob "**/*.py"` 无命中。

### 3.4 按业务重整后的当前主流程

如果不按 phase 名称，而按“书真正是怎么被处理的”来理解，当前主流程更接近下面这 7 步：

1. 先确定目录来源和目录组织方式
   - `auto_visual_toc`
   - `manual_toc`
   - `document_toc`
   - 最终目标是得到 `container / chapter / post_body / back_matter`
2. 再按章判断注释模式，而不是先给整本书贴死“脚注书 / 尾注书”标签
   - `footnote_primary`
   - `chapter_endnote_primary`
   - `book_endnote_bound`
   - `review_required`
3. 以章节为单位拆正文区和注释区
   - 正文页
   - note start 页
   - gap page
   - 尾部定义块
4. 以章节为单位整理 note item，并做 anchor-link 对齐
   - 第一轮直接命中
   - 第二轮 repair/fallback
   - 必要时 synthetic anchor
5. 冻结已确认引用
   - 当前统一冻结为 `{{NOTE_REF:...}}`
   - 后续导出时再改写为本地 `[^n]`
6. 以章节为单位合并正文和本章注释，生成章节文件
7. 按目录顺序导出整本书，并通过 status/audit gate 决定是否放行

这条业务主流程和“严格先判整本书是脚注书还是尾注书，再走单一路径”的做法不同。

当前 `FNM_RE` 的现实是：

- 先按章判 note mode
- 再按章组织正文与注释
- 最后统一通过 gate 判定能不能导出

### 3.5 当前真正卡住的不是阶段数量，而是第 4 步

现在最关键的现实不是“还有没有 phase8”，而是：

1. 目录组织方式与章节骨架，已经能在大多数样本上跑通。
2. frozen ref、导出、audit、status 也都已经落地。
3. 当前真正没收口的是：
   - 以章节为单位，把正文 anchor 和 note item 全部稳定打通
   - 再把剩余的标题对齐问题收尾

也就是说，当前最核心的未完成工作，不是“再开新阶段”，而是：

1. `Mad_Act` 的 `footnote_orphan_anchor`
2. `Biopolitics` 的 `endnote_orphan_note / endnote_orphan_anchor / ambiguous`
3. `Goldstein / Germany / Heidegger` 一类的 `toc_chapter_title_mismatch`

### 3.6 按目标业务流程对照当前实现

下面按当前希望采用的 7 步业务流程，逐条对照 `FNM_RE` 现有实现。

#### 1. 根据用户上传的 PDF 目录，调用视觉模型确定目录结构和划分方式

目标流程里的角色集合是：

- `front_matter`
- `container`
- `chapter`
- `post_body`
- `back_matter`

当前实现情况：

1. 目录结构识别这一步**存在，但不在 `FNM_RE` 内直接实现**。
2. 真正做视觉目录识别的是上游 `pipeline/visual_toc.py`。
3. 当前目录视觉模型不是在 `FNM_RE` 里硬编码成 `qwen3.5-plus`，而是通过 `resolve_visual_model_spec()` 读取当前视觉模型配置。
4. `FNM_RE` 的职责是读取已经生成好的 `toc_items`，再把它们用于章节骨架构建。
5. `front_matter / container / chapter / post_body / back_matter` 这些目录语义，目前主要来自上游 visual TOC 的 `role_hint`。

当前与目标流程不一致的点：

1. 目标流程里写的是“调用 `qwen3.5-plus` 视觉模型”，但当前代码口径是“调用当前配置的视觉模型”，未锁死到 `qwen3.5-plus`。
2. 目标流程里希望去掉 `noise`，但当前 `FNM_RE` 页面分区仍保留 `noise`。
3. 当前“目录语义角色”和“页面角色”是两套口径：
   - 目录语义：`front_matter / container / chapter / post_body / back_matter`
   - 页面角色：`noise / front_matter / body / note / other`

这一段的职责交叉：

1. `pipeline/visual_toc.py`
   - 负责目录页视觉识别与 role hint
2. `FNM_RE/app/mainline.py`
   - 负责取用 `toc_items`
3. `FNM_RE/stages/chapter_skeleton.py`
   - 负责把目录结构落成章节骨架

也就是说，“目录结构识别”当前被拆成了**上游视觉识别 + 新链章节落地**两段，而不是单一模块。

#### 2. 检查目录和章节结尾是否包含注释区，从而确定书型和链接方式

目标流程希望先区分：

1. 尾注+脚注混合型
2. 尾注型
3. 脚注型
4. 无注释

当前实现情况：

1. 当前代码**没有单独的“整本书型”对象**。
2. 目前真正存在的是 `chapter_note_modes`，按章判断：
   - `footnote_primary`
   - `chapter_endnote_primary`
   - `book_endnote_bound`
   - `no_notes`
   - `review_required`
3. 判断依据已经覆盖了目标流程里提到的几个信号：
   - notes heading
   - 章末 note region
   - 页底 footnote band
   - 数字 marker
4. 但这些信号最终是按章消化，不会先产出一个“整本书是脚注书 / 尾注书”的总分类。

当前与目标流程不一致的点：

1. 目标流程强调“先搞清楚整本书型和链接方式”，当前代码更像“先按章判 mode，再从各章 mode 汇总整本书表现”。
2. 当前没有显式产出：
   - `mixed`
   - `endnote_only`
   - `footnote_only`
   - `no_notes`
   这样的全书枚举。

这一段的职责交叉：

1. `note_regions.py`
   - 判断哪里是注释区
2. `note_items.py`
   - 判断这些区域里有什么条目
3. `app/pipeline.py:_build_chapter_note_modes()`
   - 负责把 region/item 投影成章节 note mode
4. `shared/anchors.py` 与 `note_links.py`
   - 又会根据章节 note mode 反向影响 anchor/link 解析方式

也就是说，“书型判断”和“链接策略选择”现在是**相互影响的两层逻辑**，还不是一个单独、集中、稳定的步骤。

#### 3. 尾注与脚注的拆分

目标流程希望做到：

1. 章内识别大标题、小标题、正文、脚注、尾注
2. 正文和尾注共页时，能切出分界
3. 正文跨页连续
4. 混合书型里脚注作为正文特殊区域处理，并打 `[脚注]`
5. 脚注书则把脚注提取成统一尾注区

当前实现情况：

1. 大标题/小标题/正文识别：
   - 已有
   - `chapter_skeleton.py` 负责章节骨架
   - `section_heads.py` 负责章内标题
   - `shared/title.py`、`shared/text.py`、`shared/segments.py` 负责标题和段落辅助
2. 正文/尾注共页切分：
   - 已有
   - `units.py` 里的 `_extract_note_heading_split()`、`_build_structured_body_pages_for_chapter()` 会把 note start 页切开
3. 正文跨页连续：
   - 已有
   - `parse_page_markdown()` + `cross_page / consumed_by_prev`
   - `segments.py` 与 `units.py` 负责保持连续段落
4. 注释区拆分：
   - 已有
   - `note_regions.py` 区分 `footnote_band / chapter endnote / book endnote`
5. note item 提取：
   - 已有
   - `note_items.py`

当前与目标流程不一致的点：

1. 当前没有统一的“章节内部内容分层对象”来同时容纳：
   - 大标题
   - 小标题
   - 正文
   - 脚注区
   - 尾注区
   这些层次，而是散落在多个阶段对象里。
2. 目标流程要求混合书型里的脚注在正文末尾打出 `[脚注]` 标记，当前没有这个显式标记。
3. 目标流程要求“脚注书把所有脚注提取出来形成尾注区”，当前也没有独立的“脚注转尾注区”阶段。
4. 当前脚注最终是通过 link 和 export 层本地定义落到章末，而不是先在结构层形成统一“尾注区”。

这一段的职责交叉最明显：

1. `chapter_skeleton.py`
   - 负责章节和标题层
2. `note_regions.py`
   - 负责注释区域层
3. `units.py`
   - 又重新裁一次正文页，实际再次决定正文和注释的边界
4. `export.py`
   - 最终又决定注释定义如何出现在章节文件里

也就是说，“正文与注释的拆分”现在并没有完全收敛在一个阶段，存在**结构层、unit 层、导出层三次参与**的问题。

#### 4. 以章节为单位整理尾注区域、计数、首轮直连、再做 OCR 修补，并以“尾注全部命中正文”为通过条件

当前实现情况：

1. “以章节为单位”：
   - 已成立
   - note region、note item、note link 都带 `chapter_id`
2. 条目计数：
   - 已有
   - `note_item_summary`、`note_region_summary`、`note_link_summary`
3. 第一遍直连：
   - 已有
   - `note_links.py` 先做直接匹配
4. 第二遍修补：
   - 已有
   - `repair / fallback / synthetic anchor / OCR shortened marker repair`
5. 通过条件：
   - 当前确实会因为 `orphan_note / orphan_anchor / ambiguous` 被 gate 挡住

当前与目标流程不一致的点：

1. 当前通过条件不是“唯有尾注条目全部在正文命中才通过”这一条单一规则。
2. 当前 gate 是更宽的一组条件：
   - `orphan_note`
   - `orphan_anchor`
   - `ambiguous`
   - `boundary_review_required`
   - `toc_alignment_review_required`
   - `toc_semantic_review_required`
   - `export_semantic_contract_broken`
   - `export_audit_blocking`
3. 当前没有看到“尾注必须以 1 开头”的硬校验。
4. 当前并不是先只看尾注 item，再去判断正文是否全命中；而是 anchor、note item、章节 mode、导出合同一起参与最终 gate。

这一段的职责交叉：

1. `note_items.py`
   - 定义项提取
2. `body_anchors.py`
   - 正文 marker 抽取
3. `note_links.py`
   - 匹配与修补
4. `reviews.py`
   - 把残留问题变成 review
5. `status.py`
   - 再把 review 投成 gate

这 5 层现在形成了一条链，但“通过条件”分散在 `note_links -> reviews -> status` 三层，不是一个单点规则。

#### 5. 冻结所有确定的尾注标记，翻译后替换为 `[^n]`

当前实现情况：

1. 这一步已经落地。
2. 当前统一冻结为 `{{NOTE_REF:<note_id>}}`。
3. `build_translation_units()` 会先把可确认的 link 物化成 frozen ref。
4. `export.py` 再把 frozen ref 和原始 raw marker 改写为本章本地 `[^n]`。

当前与目标流程不一致的点：

1. 不是“所有尾注标记都冻结”，而是“只有已确认稳定匹配的引用才冻结”。
2. `ignored / orphan / ambiguous / synthetic` 这几类不会按正常引用那样直接冻结。
3. 当前冻结对象不只尾注，也包括脚注，只是内部统一用 `NOTE_REF`。

这一段职责相对集中，但仍有两层：

1. `units.py`
   - 冻结
2. `export.py`
   - 解冻并改写成本地编号

#### 6. 以章节为单位，将章节主体和尾注区合并为一个文件

当前实现情况：

1. 这一步已经成立。
2. `export.py` 现在按章节生成 markdown 文件。
3. 每个导出章节文件里会包含：
   - 本章正文
   - 本章 section heads
   - 本章本地注释定义

当前与目标流程不一致的点：

1. 当前导出文件里是“本章正文 + 本章本地注释定义”，不是一个先独立成型的“尾注区对象”再合并。
2. 目标流程里说的是“章节主体和尾注区合并”，当前更准确地说是“正文和已本地化的注释定义一起导出”。

这一段职责交叉较少，主责任基本在：

1. `units.py`
   - 准备正文 unit 和 note unit
2. `export.py`
   - 合并成章节 markdown

#### 7. 按解析后的章节和目录顺序，进行文件合并并导出

当前实现情况：

1. 这一步已经存在。
2. `build_export_bundle()` 会生成：
   - `index.md`
   - `chapters/*.md`
3. 导出顺序当前主要按解析后的章节 `start_page` 排序。
4. 实际上它已经接近“按解析后的章节顺序导出”，通常与目录顺序一致。

当前与目标流程不一致的点：

1. 当前并不是单独维护一份“最终目录顺序表”驱动导出，而是更依赖章节骨架结果本身的顺序。
2. 如果目录语义和章节骨架仍有轻微漂移，导出顺序仍可能表现为“更偏 start_page 驱动”。

这一段的职责交叉：

1. `chapter_skeleton.py`
   - 决定章节顺序基础
2. `export.py`
   - 按章节顺序落文件
3. `export_audit.py`
   - 最后再检查导出顺序和语义是否出现漂移

### 3.7 当前最明显的职责交叉

如果按上面的目标流程看，当前代码里职责交叉最明显的是 5 处：

1. **目录语义识别**
   - 上游 `pipeline/visual_toc.py` 判 role
   - `chapter_skeleton.py` 再消费并重解释
   - `status.py` / `export_audit.py` 继续消费同一批语义摘要
2. **书型/链接方式判断**
   - `note_regions.py`、`note_items.py`、`_build_chapter_note_modes()`、`shared/anchors.py`、`note_links.py` 共同参与
   - 目前还没有单独“整本书型判定层”
3. **正文与注释区切分**
   - `page_partition.py` 先切页面角色
   - `note_regions.py` 再切注释区
   - `units.py` 又在 note start 页和 gap page 上重切一次正文
4. **链接通过条件**
   - `note_links.py` 判断命中
   - `reviews.py` 转 review
   - `status.py` 再决定是否阻塞
   - 当前通过条件不是单点，而是三级投影
5. **注释最终呈现**
   - `note_items.py` 负责定义项
   - `units.py` 负责 frozen ref
   - `export.py` 负责本地 `[^n]`
   - “注释如何在最终章节文件里出现”并没有完全收在一个阶段

### 3.8 按目标流程看，当前最需要收束的地方

如果后续要继续按这条业务主流程收口，最值得优先收束的是：

1. 统一目录角色口径
   - 明确 `front_matter / container / chapter / post_body / back_matter`
   - 决定 `noise` 是否只保留为低层页面技术标签
2. 显式增加“整本书型”投影
   - `mixed / endnote_only / footnote_only / no_notes`
3. 把“正文与注释区边界”尽量收敛到结构层或 unit 层
   - 避免导出层继续补切分
4. 把“通过条件”尽量收成一套更接近业务定义的规则
   - 例如是否引入“尾注必须从 1 开始”
   - 是否显式检查“该章尾注条目全部命中正文”

## 4. 当前分支处理方式

这一节只写现在代码里真正存在的分支，不写计划里的理想状态。

### 4.1 输入与入口层分支

主要在 `app/mainline.py`：

1. TOC 读取顺序分支：
   - `auto_visual`
   - `auto_pdf`
   - `document_toc`
   - `load_auto_visual_toc_from_disk()` 兜底
2. `pipeline_state` 分支：
   - `idle`
   - `running`
   - `error`
   - `done`
3. `manual_toc_ready` / `manual_toc_summary` 分支：
   - phase4/phase6 status 会把它作为 gate 条件
4. repo unit 覆盖分支：
   - `_overlay_repo_translation_units()` 可把 repo 中现有翻译结果叠回 phase5 结果
5. 目录模型来源分支：
   - `FNM_RE` 自己并不在代码里写死 `qwen3.5-plus`
   - 当前目录视觉模型来自上游 `resolve_visual_model_spec()`
   - 因此“目录识别是否由 qwen3.5-plus 执行”取决于当前视觉模型配置，而不是 `FNM_RE` 硬编码

### 4.2 结构层分支

主要在 `page_partition.py` 与 `chapter_skeleton.py`：

1. 页面角色分支：
   - `noise`
   - `front_matter`
   - `body`
   - `note`
   - `other`
2. 页面角色判定方式：
   - 首轮规则链
   - 前书连续段修正
   - note continuation 修正
   - 最后再应用 manual page override
3. 章节来源分支：
   - `visual_toc`
   - `fallback`
4. 当前章节骨架的关键现实：
   - fallback 候选收集和分类已经在新链里
   - visual TOC 章节构建仍直接借旧 `_build_visual_toc_chapters_and_section_heads()`

### 4.3 注释区与定义项分支

主要在 `note_regions.py`、`note_items.py`：

1. 注释区类型分支：
   - `footnote_band`
   - `chapter-scope endnote`
   - `book-scope endnote`
2. 注释区后处理分支：
   - merge adjacent endnote regions
   - promote post-body regions
   - split book regions by heading
   - rebind book regions
3. region source 分支：
   - `heading_scan`
   - `footnote_band`
   - `continuation_merge`
   - `manual_rebind`
4. note item 提取分支：
   - 优先结构化 scan
   - 再用 page text
   - 再用 pdf text fallback

### 4.4 anchor/link 分支

主要在 `body_anchors.py`、`note_links.py`：

1. anchor kind 分支：
   - `footnote`
   - `endnote`
   - `unknown`
2. anchor 来源分支：
   - markdown paragraph
   - OCR block paragraph
3. link status 分支：
   - `matched`
   - `orphan_note`
   - `orphan_anchor`
   - `ambiguous`
   - `ignored`
4. resolver 分支：
   - `rule`
   - `fallback`
   - `repair`
5. synthetic anchor 分支：
   - 只在 footnote 场景下按需生成
   - 生成后允许被同页显式 anchor 回绑替换

### 4.5 override 分支

主要在 `app/pipeline.py` phase4：

1. 支持的 override scope：
   - `page`
   - `link`
2. `page` override：
   - 只改 `page_role`
   - 通过重跑上游生效
3. `link` override：
   - `ignore`
   - `match`
4. 当前不支持但会被记录为 unsupported 的 scope：
   - `chapter`
   - `region`
   - `llm_suggestion`

### 4.6 导出与状态分支

主要在 `export.py`、`export_audit.py`、`status.py`：

1. 导出正文选择分支：
   - 人工译文
   - 机器译文
   - `[待翻译]`
2. 导出正文引用修正分支：
   - frozen ref 替换
   - raw bracket marker 替换
   - raw superscript marker 替换
   - unicode superscript 替换
3. 导出 include 选项：
   - `include_diagnostic_entries=False/True`
4. 导出 gate 分支：
   - `chapter_local_endnote_contract_ok`
   - `export_semantic_contract_ok`
   - `export_audit.can_ship`
   - 最终投影成 `export_ready_test/export_ready_real`

### 4.7 样本特判的现实状态

当前 `FNM_RE` Python 代码里**基本看不到按书名硬编码的分支**。搜索结果里没有 `Biopolitics`、`Mad_Act`、`Goldstein`、`Heidegger`、`Napoleon` 这类书名 if-else。

当前样本差异主要通过下面三种方式进入新链：

1. `manual_toc`
2. `review_overrides`
3. 通用 fallback / rebind / repair 规则

这说明 `FNM_RE` 当前在“去样本硬编码”上做得比旧链干净，但也意味着：一旦规则泛化不够，问题会集中爆成 `orphan_* / ambiguous / toc mismatch / export audit blocking`，而不是体现在样本特判分支里。

## 5. 主要文件、主函数与职责

下面只写代码文件，不写计划文档。

### 5.1 根目录核心文件

| 文件 | 行数 | 主要函数/对象 | 作用 |
|---|---:|---|---|
| `FNM_RE/__init__.py` | 33 | 导出 `build_phase*` 和 `mainline` 入口 | 包级对外导出 |
| `FNM_RE/constants.py` | 79 | `is_valid_*()` | 统一字面量类型与校验 |
| `FNM_RE/models.py` | 579 | `PagePartitionRecord` 到 `Phase6Structure` 全量 dataclass | 新链统一数据模型 |
| `FNM_RE/status.py` | 516 | `build_phase4_status()`、`build_phase6_status()` | 结构状态、导出 gate、owner progress 投影 |

### 5.2 `app/`

| 文件 | 行数 | 主要函数 | 作用 |
|---|---:|---|---|
| `FNM_RE/app/__init__.py` | 33 | 导出 pipeline/mainline 入口 | `app` 子包导出 |
| `FNM_RE/app/pipeline.py` | 901 | `build_phase1_structure()` ~ `build_phase6_structure()`、`_group_review_overrides()`、`_apply_link_overrides()` | 纯阶段拼装入口，不直接读 repo |
| `FNM_RE/app/mainline.py` | 992 | `load_phase6_for_doc()`、`build_phase6_status_for_doc()`、`build_phase6_export_bundle_for_doc()`、`build_phase6_export_zip_for_doc()`、`audit_phase6_export_for_doc()`、`run_phase6_pipeline_for_doc()`、`list_phase6_diagnostic_*()` | doc/repo-aware 主接线层，也是当前最接近生产的实际入口 |

### 5.3 `shared/`

| 文件 | 行数 | 主要函数 | 作用 |
|---|---:|---|---|
| `FNM_RE/shared/__init__.py` | 2 | 无 | 占位 |
| `FNM_RE/shared/text.py` | 87 | `page_markdown_text()`、`extract_page_headings()`、`note_scan_summary()` | 页面文本、heading、note scan 的轻量抽取 |
| `FNM_RE/shared/title.py` | 33 | `normalize_title()`、`normalized_title_key()`、`chapter_title_match_key()`、`guess_title_family()` | 标题标准化与标题家族猜测 |
| `FNM_RE/shared/notes.py` | 198 | `normalize_note_marker()`、`is_notes_heading_line()`、`scan_items_by_kind()`、`parse_note_items_from_text()`、`extract_pdf_text_by_page()` | 注释 marker、notes heading、页文本与 PDF 文本 fallback |
| `FNM_RE/shared/anchors.py` | 240 | `looks_like_year_marker()`、`resolve_anchor_kind()`、`page_body_paragraphs()`、`scan_anchor_markers()` | 正文 anchor 扫描与 anchor kind 解析 |
| `FNM_RE/shared/refs.py` | 93 | `frozen_note_ref()`、`replace_frozen_refs()`、`extract_note_refs()` | `{{NOTE_REF:...}}` 的生成、显示替换、逆向抽取 |
| `FNM_RE/shared/segments.py` | 192 | `split_fnm_paragraphs()`、`build_fallback_unit_paragraphs()`、`normalize_unit_page_segment()` | unit paragraph/page segment 的构建与标准化 |

### 5.4 `stages/`

| 文件 | 行数 | 主要函数 | 作用 |
|---|---:|---|---|
| `FNM_RE/stages/__init__.py` | 1 | 无 | 占位 |
| `FNM_RE/stages/page_partition.py` | 317 | `build_page_partitions()`、`summarize_page_partitions()` | 页面角色识别、二轮修正、manual override |
| `FNM_RE/stages/chapter_skeleton.py` | 1173 | `build_chapter_skeleton()`、`_collect_*_heading_candidates()`、`_classify_fallback_sections()`、`_build_fallback_chapters_and_sections()` | 章节骨架、heading candidate、visual/fallback 双路；当前最大复杂度文件 |
| `FNM_RE/stages/section_heads.py` | 148 | `build_section_heads()` | 章内标题归属与过滤 |
| `FNM_RE/stages/note_regions.py` | 568 | `build_note_regions()`、`_build_footnote_band_regions()`、`_build_endnote_regions_raw()`、`_merge_adjacent_endnote_regions()`、`_split_book_regions_by_heading()`、`_rebind_book_regions()` | 注释区识别、合并、拆分、rebind |
| `FNM_RE/stages/note_items.py` | 249 | `build_note_items()` | 注释定义项提取、去重、PDF fallback |
| `FNM_RE/stages/body_anchors.py` | 152 | `build_body_anchors()` | 正文锚点抽取与统计 |
| `FNM_RE/stages/note_links.py` | 639 | `build_note_links()`、`_make_synthetic_anchor()`、`_candidate_anchors()` | 锚点-定义项链接、synthetic anchor、repair/fallback/ambiguous 处理 |
| `FNM_RE/stages/reviews.py` | 210 | `build_structure_reviews()` | 把 orphan/ambiguous/boundary/toc 问题投成 review rows |
| `FNM_RE/stages/units.py` | 764 | `build_translation_units()`、`_segment_paragraphs_from_body_pages()`、`_chunk_body_page_segments()`、`_build_structured_body_pages_for_chapter()`、`_materialize_refs_for_chapter()` | body/note unit 规划、正文裁切、分段、frozen ref 物化 |
| `FNM_RE/stages/diagnostics.py` | 307 | `build_diagnostic_projection()`、`_build_diagnostic_entry()` | 从 unit 和 note item 现算 diagnostic page/note |
| `FNM_RE/stages/export.py` | 914 | `build_export_bundle()`、`build_export_zip()`、`_build_section_markdown()`、`_rewrite_body_text_with_local_refs()`、`_compute_export_semantic_contract()` | 章节 markdown、bundle、zip、本地引用和导出语义合同 |
| `FNM_RE/stages/export_audit.py` | 652 | `audit_markdown_file()`、`audit_phase6_export()` | 单文件与整书导出审计、issue code 汇总 |

## 6. 真实主函数索引

如果只看“当前最应该读的函数”，建议按下面顺序读：

1. `FNM_RE/app/mainline.py:run_phase6_pipeline_for_doc()`
   - 真实跑一本文档时的主入口
2. `FNM_RE/app/mainline.py:load_phase6_for_doc()`
   - 真实 doc 级装配入口
3. `FNM_RE/app/pipeline.py:build_phase6_structure()`
   - 纯阶段总拼装
4. `FNM_RE/stages/chapter_skeleton.py:build_chapter_skeleton()`
   - 章节侧核心复杂度入口
5. `FNM_RE/stages/note_regions.py:build_note_regions()`
   - 注释区识别主入口
6. `FNM_RE/stages/note_links.py:build_note_links()`
   - 锚点与定义项匹配主入口
7. `FNM_RE/stages/units.py:build_translation_units()`
   - 翻译 unit 主入口
8. `FNM_RE/stages/export.py:build_export_bundle()`
   - 导出拼装主入口
9. `FNM_RE/stages/export_audit.py:audit_phase6_export()`
   - 导出审计主入口
10. `FNM_RE/status.py:build_phase6_status()`
    - 最终状态与 export gate 主入口

## 7. 当前代码结构的优点与问题

### 7.1 当前优点

1. 阶段边界已经明确，整体比旧 `fnm_structure.py` 单体总函数清晰很多。
2. 主数据模型集中在 `models.py`，真相层和投影层已经分开。
3. 样本级硬编码显著减少，主要依靠 override / manual TOC / generic fallback。
4. `mainline.py` 已经把“纯阶段逻辑”和“repo/doc 接线逻辑”分离开。

### 7.2 当前问题

1. `chapter_skeleton.py` 仍是单点复杂度最高文件，而且还残留对旧 visual TOC 构建函数的直接依赖。
2. `app/mainline.py` 接线职责很多，已经接近第二个“总控文件”。
3. `note_links.py` 和 `export.py` 的规则密度很高，是当前最容易继续膨胀的地方。
4. 主线已切到 snapshot 单轨，但 `mainline.py` 接线职责仍偏重，后续仍需继续瘦身。
5. 代码上已经能跑，但样本 gate 还没清零，因此不能把“能跑通”误认为“已经收口”。

### 7.3 当前最容易误判的点

当前最容易被误判的地方有 3 个：

1. **历史验证记录很多**
   - 文档里有大量“某本书曾经通过”的记录
   - 但当前最新状态必须看文档顶部最新记录
2. **phase 已齐全，不等于主流程已收口**
   - `phase1 ~ phase7` 都在，不代表 cutover 已完成
   - 当前最大问题仍在链接债和标题对齐
3. **能导出 zip，不等于可发版**
   - 当前真实 gate 看的是：
     - `structure_state`
     - `blocking_reasons`
     - `chapter_local_endnote_contract_ok`
     - `export_semantic_contract_ok`
     - `export_audit.can_ship`

## 8. 当前最值得继续盯的代码点

如果后面继续盘点或收口，我建议优先看这几处：

1. `FNM_RE/stages/chapter_skeleton.py`
   - 继续拆 visual TOC 与 fallback 混杂复杂度
2. `FNM_RE/stages/note_links.py`
   - 重点看 orphan/ambiguous 的来源是否可前移处理
3. `FNM_RE/stages/export.py`
   - 重点看 raw marker leak 与本地定义闭合
4. `FNM_RE/app/mainline.py`
   - 重点看 repo overlay、状态投影、持久化映射是否还可以再瘦身
5. `FNM_RE/status.py`
   - 重点看结构 blocker 和 export blocker 的分层是否继续清晰
6. `PROGRESS.md` 与 `verification.md` 顶部最新记录
   - 这是判断当前代码是否真的“收口”的外部事实基线

## 9. Python 源文件完整行数表

| 文件 | 行数 |
|---|---:|
| `FNM_RE/stages/__init__.py` | 1 |
| `FNM_RE/shared/__init__.py` | 2 |
| `FNM_RE/__init__.py` | 33 |
| `FNM_RE/app/__init__.py` | 33 |
| `FNM_RE/shared/title.py` | 33 |
| `FNM_RE/constants.py` | 79 |
| `FNM_RE/shared/text.py` | 87 |
| `FNM_RE/shared/refs.py` | 93 |
| `FNM_RE/stages/section_heads.py` | 148 |
| `FNM_RE/stages/body_anchors.py` | 152 |
| `FNM_RE/shared/segments.py` | 192 |
| `FNM_RE/shared/notes.py` | 198 |
| `FNM_RE/stages/reviews.py` | 210 |
| `FNM_RE/shared/anchors.py` | 240 |
| `FNM_RE/stages/note_items.py` | 249 |
| `FNM_RE/stages/diagnostics.py` | 307 |
| `FNM_RE/stages/page_partition.py` | 317 |
| `FNM_RE/status.py` | 516 |
| `FNM_RE/stages/note_regions.py` | 568 |
| `FNM_RE/models.py` | 579 |
| `FNM_RE/stages/note_links.py` | 639 |
| `FNM_RE/stages/export_audit.py` | 652 |
| `FNM_RE/stages/units.py` | 764 |
| `FNM_RE/app/pipeline.py` | 901 |
| `FNM_RE/stages/export.py` | 914 |
| `FNM_RE/app/mainline.py` | 992 |
| `FNM_RE/stages/chapter_skeleton.py` | 1173 |
| 合计 | 10072 |

## 10. 结论

现在的 `FNM_RE` 已经不是“一个还没接线的新目录”，而是：

1. 有完整 phase1~6 真相链和 phase7 接线层
2. `mainline + snapshot + status gate summary` 已形成单轨主线，并已同步到主要 consumer
3. 阶段 6 hard gate 已收口，当前可用

所以后续如果要继续盘点或推进，最重要的不是再补阶段名，而是盯住这四件事：

1. 章节骨架剩余旧依赖
2. 章节级 anchor-link 对齐为什么还会留下 `orphan / ambiguous`
3. 标题对齐和目录组织方式的尾债何时清零
4. `mainline.py / chapter_skeleton.py` 的复杂度如何继续拆解

## 11. SQLite 拆库改造联动状态（2026-04-16）

- 当前主线新增了 catalog/doc 拆库运行边界，`SQLiteRepository` 已具备文档元数据双写（catalog + doc.db）与迁移脚本可用能力。
- 与 FNM_RE 直接相关的变化是“读链路去写首批”已落地：`load_pages_from_disk` 不再修复回写，`GET /reading` 不再写 `save_entry_cursor`，`GET /`/`GET /input`/`GET /reading` 不再写 `current_doc_id`。
- 主链切库收口已完成：运行时初始化默认不再初始化 legacy `app.db`；`update_fnm_run/update_fnm_translation_unit` 已按 doc context 路由到 `doc.db`。
- 删除链路已与拆库对齐：删除文档时会清理 doc-scoped `app_state`，且不会再因路径获取副作用回建文档目录。
- 这批变更目标是压低并发写冲突风险且不改变 FNM_RE 阶段主线业务口径；目前结果满足该目标，可继续在此基线上做后续质量加固。
- 追加热修：已修复手动目录上传路径的依赖注入缺口（`update_doc_meta`/`parse_glossary_file`/`set_glossary`），避免 `process_file` 在“附带 PDF 目录”场景抛 `KeyError` 并中断解析。
- 新增状态与日志联动：`/api/doc/<doc_id>/fnm/status` 已提供运行/通过 gate 聚合字段；首页 FNM 卡片会实时显示通过数与失败项；FNM 解析日志会落 `run_id/structure_state/blocking_reasons`，并维持“翻译正文不入日志、仅错误信息入日志”的策略。
