# FNM 模式完整流程与检验点梳理

> 范围：自文件上传起，经 OCR、脚注结构化、翻译、直至 ZIP 导出。
> 生成日期：2026-04-16
> 代码库快照：`main` 分支（含 `FNM_RE/`、`pipeline/`、`web/` 重构后布局）

## 一、总览

FNM（FootNoteMachine）模式在普通 OCR 翻译流程之上，额外引入「脚注/尾注结构化 → 复核 → 按章导出」的多阶段管线。整个生命周期共划分为 **7 个主阶段**，跨越前端、Flask API、后台 Worker、SQLite 持久层。

```
[阶段0 上传] → [阶段1 OCR 预处理] → [阶段2 结构骨架] → [阶段3 链接冻结]
                                                            ↓
                                                    [阶段4 复核 Gate #1]
                                                            ↓
                                              [阶段5 单元规划 + 翻译]
                                                            ↓
                                              [阶段6 导出打包 Gate #2]
```

全流程共设置 **两道硬 Gate**（结构就绪、导出就绪），贯穿其中的 **检验点约 21 处**，分为「硬阻塞」「API 前置校验」「软告警」三类。

---

## 二、阶段详解

### 阶段 0 —— 上传与 FNM 开关判定

**入口**：`POST /api/document/upload_file`
**代码**：[web/document_routes.py:174](web/document_routes.py:174) `upload_file`

核心动作：
1. 校验 PaddleOCR 令牌已配置。
2. 接收 `file`、`fnm_mode` 标志、可选 TOC 上传、可选词典。
3. 根据 `fnm_mode` 调用 [`_task_options_for_fnm_mode`](web/document_routes.py:25) 设置 `clean_header_footer`、`auto_visual_toc` 两个开关。
4. 创建 `task_id`，后台线程调用 `process_file(task_id)`。

**FNM 与非 FNM 的区分点**：
- 表单字段 `fnm_mode=true` 即触发。
- 后续重解析入口 `api_doc_reparse_enhanced` [web/document_routes.py:271](web/document_routes.py:271) 强制以 FNM 模式（`_task_options_for_fnm_mode(True)`）重跑。
- 文档级持久化字段 `cleanup_headers_footers` 决定普通「重解析」按钮走 FNM 还是非 FNM。

#### 检验点
| # | 检验 | 位置 | 失败结果 |
|---|------|------|---------|
| C0-1 | 文件扩展名须为 `.pdf/.jpg/.jpeg/.png/.bmp/.tiff/.tif` | [web/document_routes.py:192-197](web/document_routes.py:192) | 返回 `{"error": "不支持的文件类型"}` |
| C0-2 | 手动 TOC 只允许 PDF 或截图其中一种 | [web/document_routes.py:183-185](web/document_routes.py:183) via `_collect_manual_toc_uploads` | 返回错误 |
| C0-3 | 词典文件只允许 `.csv/.xlsx` | [web/document_routes.py:59-71](web/document_routes.py:59) `_collect_glossary_upload` | 返回错误 |
| C0-4 | PaddleOCR Token 必须存在 | [web/document_routes.py:175-177](web/document_routes.py:175) | 返回错误 |

---

### 阶段 1 —— OCR 解析 + 视觉 TOC

**入口**：`process_file(task_id)`
**代码**：[pipeline/task_document_pipeline.py:382](pipeline/task_document_pipeline.py:382) `process_file`

子步骤（按 FNM 分支实际执行顺序）：
1. **OCR**：[_run_ocr_parse](pipeline/task_document_pipeline.py:22)，调用 PaddleOCR API，产出 `parsed["pages"]`。
2. **跳过文字层合并与页眉页脚清理**：FNM 模式下 `cleanup_enabled=True`，[task_document_pipeline.py:415](pipeline/task_document_pipeline.py:415) 的 `_merge_pdf_text_layers` 与 [task_document_pipeline.py:449](pipeline/task_document_pipeline.py:449) 的 `_cleanup_and_scan_pages` 均不执行；流水线直接打点 `"FNM 模式：已跳过文字层合并/页眉页脚清理/注释扫描…"`（[task_document_pipeline.py:440-447](pipeline/task_document_pipeline.py:440)），再调 `apply_cleanup_mode_to_pages(..., cleanup_enabled=False)` 原样透传页。
3. **自动视觉 TOC 提取（必需）**：[_run_required_visual_toc_before_fnm](pipeline/task_document_pipeline.py:500)。先读 PDF 书签，否则扫描前 30% 页面寻找目录链接；FNM 下此步**强制**，失败即终止任务。
4. **保存**：`save_pages_to_disk` 写入 `raw_pages.json` / `raw_pages.db`。
5. **触发 FNM 主线**：`run_fnm_pipeline_for_doc(task_id, doc_id)`（[task_document_pipeline.py:519](pipeline/task_document_pipeline.py:519)）。

> 说明：`_task_options_for_fnm_mode` 虽把 `clean_header_footer` 设为 True，但该字段在 `process_file` 中作为 **FNM 分支判据**使用——值为 True 反而触发"跳过清理"分支。文字层合并与页眉页脚清理只在非 FNM（快速）流程下生效。

#### 检验点
| # | 检验 | 位置 | 失败结果 |
|---|------|------|---------|
| C1-1 | OCR 结果页数 > 0 | `_run_ocr_parse` 返回空时在 `process_file` 内被视为失败 | 任务进入 `error` 状态 |
| C1-2 | 视觉 TOC 必须成功（FNM 下为硬性） | [pipeline/task_document_pipeline.py:511-517](pipeline/task_document_pipeline.py:511) | 失败即 `error_msg`，不进入 FNM 主线 |

---

### 阶段 2 —— 页面分区、章节骨架、脚注/尾注区域

**入口**：`build_phase1_structure` + `build_phase2_structure`
**代码**：[FNM_RE/app/pipeline.py:75](FNM_RE/app/pipeline.py:75)、[FNM_RE/app/pipeline.py:222](FNM_RE/app/pipeline.py:222)

Phase 1（结构骨架）：
- `build_page_partitions`：每页分区（正文 / 注释带 / 页眉页脚剔除区）。
- `build_chapter_skeleton`（[FNM_RE/stages/chapter_skeleton.py](FNM_RE/stages/chapter_skeleton.py)）：依据 TOC + 标题 + 章间分页做章节切分。
- `build_section_heads`：小节级标题提取。

Phase 2（脚注/尾注区域）：
- `build_note_regions`（[FNM_RE/stages/note_regions.py](FNM_RE/stages/note_regions.py)）：判定 `note_kind ∈ {footnote, endnote}` 及 `scope ∈ {chapter, book}`。
- `build_note_items`（[FNM_RE/stages/note_items.py](FNM_RE/stages/note_items.py)）：切分单条注释，绑定 marker。
- `_build_chapter_note_modes`（[FNM_RE/app/pipeline.py:125](FNM_RE/app/pipeline.py:125)）：推断章内注释模式 `footnote_primary / chapter_endnote_primary / book_endnote_bound / no_notes / review_required`。

#### 检验点
| # | 检验 | 位置 | 分支 |
|---|------|------|------|
| C2-1 | 脚注区域 marker 是否与 anchor 对齐 | `region_marker_alignment_ok` 计算于 note_regions | 未对齐 → 产生 `boundary_review_required` |
| C2-2 | 章内是否同时存在 footnote + endnote 冲突 | [FNM_RE/app/pipeline.py:172-174](FNM_RE/app/pipeline.py:172) | 冲突 → mode 设为 `review_required` |
| C2-3 | 每条 note_item 是否具备合法 marker 与非空正文 | note_items 构建过程 | 不合法 → 进入 orphan 分类 |

---

### 阶段 3 —— Anchor 匹配与引用冻结

**入口**：`build_phase3_structure`
**代码**：[FNM_RE/app/pipeline.py:279](FNM_RE/app/pipeline.py:279)

子步骤：
1. **Body Anchor 提取**：[FNM_RE/stages/body_anchors.py](FNM_RE/stages/body_anchors.py)，从正文扫描 `[1]/(1)/¹` 等 marker。
2. **三级链接匹配**：[FNM_RE/stages/note_links.py](FNM_RE/stages/note_links.py)
   - L1 直接匹配 → `matched`
   - L2 修复 / 回退匹配 → `matched`（标记非直接）
   - L3 合成 anchor → `synthetic_anchor`
   - 失败分类：`orphan_note` / `orphan_anchor` / `ambiguous` / `ignored`
3. **Ref Freeze**：[FNM_RE/modules/ref_freeze.py](FNM_RE/modules/ref_freeze.py)，仅对 `matched` 注入 `{{NOTE_REF:chapter_id:note_id}}` 占位符。

#### 检验点
| # | 检验 | 位置 | 类型 |
|---|------|------|------|
| C3-1 | `footnote_orphan_note` 计数 | [FNM_RE/status.py:110](FNM_RE/status.py:110) | 硬阻塞 |
| C3-2 | `footnote_orphan_anchor` 计数 | 同上 | 硬阻塞 |
| C3-3 | `endnote_orphan_note` 计数 | [FNM_RE/status.py:113](FNM_RE/status.py:113) | 硬阻塞 |
| C3-4 | `endnote_orphan_anchor` 计数 | [FNM_RE/status.py:115](FNM_RE/status.py:115) | 硬阻塞 |
| C3-5 | `ambiguous` 计数 | [FNM_RE/status.py:119](FNM_RE/status.py:119) | 硬阻塞 |
| C3-6 | `freeze.only_matched_frozen` | ref_freeze 内部断言 | 硬阻塞 |
| C3-7 | `freeze.no_duplicate_injection` / `freeze.accounting_closed` | ref_freeze 内部断言 | 硬阻塞 |
| C3-8 | `synthetic_anchor_warn` / `footnote_orphan_anchor_warn` | status 内 soft warn 集合 | 软告警（不阻塞） |

---

### 阶段 4 —— 结构复核 & 第一道 Gate

**入口**：`build_phase4_structure` + `build_phase4_status`
**代码**：[FNM_RE/app/pipeline.py:328](FNM_RE/app/pipeline.py:328)、[FNM_RE/status.py:188](FNM_RE/status.py:188)

动作：
1. 从 SQLite `fnm_review_overrides` 加载用户手动复核记录，覆盖自动判决。
2. 对 orphan / ambiguous 项生成 `structure_review` 记录（前端可视化）。
3. 推断 `structure_state ∈ {idle, running, error, review_required, ready}`。
4. 聚合 `blocking_reasons` 列表，作为 **Gate #1**。

**前端 / API 入口**：
- `GET /api/doc/<doc_id>/fnm/status` → [web/translation_routes.py:878](web/translation_routes.py:878) 返回 state、counts、blocking。
- `POST /api/doc/<doc_id>/fnm/continue` → [web/translation_routes.py:747](web/translation_routes.py:747) 用户复核完重跑管线。

#### 检验点（Gate #1，任一项非零即阻塞翻译）
| # | 字段 | 位置 |
|---|------|------|
| C4-1 | `manual_toc_required` | [FNM_RE/status.py:195,219-220](FNM_RE/status.py:195) |
| C4-2 | `chapter_title_alignment_ok` | [FNM_RE/status.py:221-222](FNM_RE/status.py:221) |
| C4-3 | `chapter_endnote_region_alignment_ok` | [FNM_RE/status.py:223-224](FNM_RE/status.py:223) |
| C4-4 | `toc_semantic_contract_ok` | [FNM_RE/status.py:225-231](FNM_RE/status.py:225) |
| C4-5 | `BLOCKING_REVIEW_KEYS` 聚合（涵盖 C3-1~C3-5 + `boundary_review_required`） | [FNM_RE/status.py:199-232](FNM_RE/status.py:199) |

**通过条件**：`pipeline_state == done` 且 `blocking_reasons == []` → `structure_state = ready`。

---

### 阶段 5 —— 翻译单元规划 + 翻译执行

#### 5A. Phase 5 单元规划
**入口**：`build_phase5_structure`
**代码**：[FNM_RE/app/pipeline.py:394](FNM_RE/app/pipeline.py:394)

- `build_translation_units`（[FNM_RE/stages/units.py](FNM_RE/stages/units.py)）：按章节与注释区域切分 `body` / `note` 两种 `kind` 的 Unit；绑定 `owner_kind / owner_id` 与冻结后的 `target_ref`。
- `build_diagnostic_projection`（[FNM_RE/stages/diagnostics.py](FNM_RE/stages/diagnostics.py)）：供前端展示页面级与注释级问题。

#### 5B. 翻译执行
**入口**：`POST /api/doc/<doc_id>/fnm/translate` 或 `POST /api/doc/<doc_id>/fnm/full-flow`
**代码**：[web/translation_routes.py:668](web/translation_routes.py:668)、[web/translation_routes.py:771](web/translation_routes.py:771)

- FNM Worker 按 Unit 顺序请求翻译 API，支持：
  - 断点续译（记录 `start_unit_idx`）
  - 失败重试（HTTP 400/401/403/404/422 视为不可重试，立即停止；其他可重试）
  - 运行态字段 `translating / continuing / full_flow_running` 通过 `_resolve_fnm_workflow_state`（[web/translation_routes.py:174-200](web/translation_routes.py:174)）映射到 UI。

#### 检验点（API 前置，阶段 5 进入翻译之前）
| # | 检验 | 位置 | 失败状态码 |
|---|------|------|----------|
| C5-1 | FNM run 存在且 `status == done` | [web/translation_routes.py:686-714](web/translation_routes.py:686) | 409 `fnm_unavailable` |
| C5-2 | `translation_units` 非空 | 同上 | 404 `fnm_empty` |
| C5-3 | `manual_toc_required == False`（real 模式） | [web/translation_routes.py:715-724](web/translation_routes.py:715) | 409 |
| C5-4 | `structure_state == ready`（real 模式） | [web/translation_routes.py:725-731](web/translation_routes.py:725) | 409 |
| C5-5 | 翻译 API Key 存在（real 模式） | [web/translation_routes.py:732-734](web/translation_routes.py:732) | 400 |
| C5-6 | 单元翻译错误码分级（是否可重试） | FNM Worker 内部策略 | 不可重试时 worker 终止 |

---

### 阶段 6 —— 导出打包 & 第二道 Gate

**入口**：`build_phase6_structure` → `build_export_bundle` → `audit_phase6_export`
**代码**：[FNM_RE/app/pipeline.py:465](FNM_RE/app/pipeline.py:465)、[FNM_RE/stages/export.py](FNM_RE/stages/export.py)、[FNM_RE/stages/export_audit.py](FNM_RE/stages/export_audit.py)

**API**：`web/export_routes.py:79` 调用 `build_fnm_obsidian_export_zip(doc_id)`（注册于 [web/services.py:447](web/services.py:447)）。

动作：
1. 按 TOC 顺序（非页序）合并每章正文译文与脚注，生成 Obsidian 兼容 markdown（`[^n]` 脚注语法）。
2. 审计：
   - `toc_export_coverage`：章节是否完整覆盖 TOC
   - `semantic_contract`：文件内容是否满足语义约定
   - 残留扫描：是否还有 raw marker 或未解冻的 `{{NOTE_REF:*}}`
3. 产出两个布尔量：`export_ready_test` / `export_ready_real`（[FNM_RE/models.py:302-303](FNM_RE/models.py:302)）。

#### 检验点（Gate #2）
| # | 检验 | 位置 |
|---|------|------|
| C6-1 | `NOTE_REF` 占位符全部解冻 | export_audit 残留扫描 |
| C6-2 | raw marker（`[脚注]` 原文）不残留 | export_audit 残留扫描 |
| C6-3 | 章节顺序与 TOC 一致 | export 构建过程 |
| C6-4 | `can_ship = len(blocking_files) == 0` | [FNM_RE/stages/export_audit.py:637](FNM_RE/stages/export_audit.py:637) |
| C6-5 | `export_ready_real` 取决于 C6-4 + 翻译完成度 | [FNM_RE/models.py:302](FNM_RE/models.py:302) |

---

## 三、检验点汇总表

按「性质」分类：

### A. 硬阻塞（Gate）—— 共 11 大类
| 编号 | 所属 Gate | 事项 |
|------|----------|------|
| C0-1~C0-4 | Pre-Gate | 上传期输入校验 |
| C1-1 | Pre-Gate | OCR 空结果 |
| C3-1~C3-5 | Gate #1 | 四种 orphan / ambiguous 链接 |
| C3-6~C3-7 | Gate #1 | Ref Freeze 自检 |
| C4-1 | Gate #1 | manual_toc_required |
| C4-2 | Gate #1 | 章节标题对齐 |
| C4-3 | Gate #1 | 章级尾注区域对齐 |
| C4-4 | Gate #1 | TOC 语义契约 |
| C4-5 | Gate #1 | boundary_review_required |
| C6-1~C6-4 | Gate #2 | 导出审计 |

### B. API 前置校验 —— 共 5 项（翻译入口）
`C5-1` ~ `C5-5`：见阶段 5 表格。

### C. 软告警（不阻塞，仅提示）
- `footnote_orphan_anchor_warn`
- `synthetic_anchor_warn`
- `freeze.synthetic_skip_warn`

合计：**硬阻塞 16 项（按细项）+ API 前置 5 项 + 软告警 3 项 ≈ 24 处检验**，其中上文按「大类」精简为 21 处。

---

## 四、状态机与 workflow_state

前端状态由 [`_resolve_fnm_workflow_state`](web/translation_routes.py:174) 按以下优先级推导：

```
full_flow_running  → full_flow_running
continue_running   → continuing
translate_running  → translating
run_status=error   → failed
run_status=running → processing
run_status=done
  ├ can_translate  → ready_translate
  ├ export_ready_real → ready_export
  └ 其他           → blocked
其余                → idle
```

对应 structure_state（[FNM_RE/status.py:188](FNM_RE/status.py:188)）：
`idle / running / error / review_required / ready`。

---

## 五、关键代码索引

- 文档级主线：[FNM_RE/app/mainline.py](FNM_RE/app/mainline.py)
- Phase 1~6 管线：[FNM_RE/app/pipeline.py](FNM_RE/app/pipeline.py)
- 状态/Gate 推断：[FNM_RE/status.py](FNM_RE/status.py)
- 章节骨架：[FNM_RE/stages/chapter_skeleton.py](FNM_RE/stages/chapter_skeleton.py)
- 脚注区域：[FNM_RE/stages/note_regions.py](FNM_RE/stages/note_regions.py)
- 链接匹配：[FNM_RE/stages/note_links.py](FNM_RE/stages/note_links.py)
- 引用冻结：[FNM_RE/modules/ref_freeze.py](FNM_RE/modules/ref_freeze.py)
- 翻译单元：[FNM_RE/stages/units.py](FNM_RE/stages/units.py)
- 导出：[FNM_RE/stages/export.py](FNM_RE/stages/export.py)
- 导出审计：[FNM_RE/stages/export_audit.py](FNM_RE/stages/export_audit.py)
- 上传/重解析 API：[web/document_routes.py](web/document_routes.py)
- FNM 翻译 API：[web/translation_routes.py](web/translation_routes.py)
- 导出 API：[web/export_routes.py](web/export_routes.py)
- OCR 管道：[pipeline/task_document_pipeline.py](pipeline/task_document_pipeline.py)

---

## 六、已知疑点（供后续工作参考）

1. **旧依赖遗留**：`chapter_skeleton.py` 仍引用旧 `fnm.fnm_structure._build_visual_toc_chapters_and_section_heads`；`mainline.py` 仍调用 `group_review_overrides()` 等旧接口（见 `FNM_RE/DEV_FNM.md`）。
2. **Phase 6 与翻译完成度耦合**：`export_ready_real` 同时依赖审计 `can_ship` 与翻译进度，需保证 Unit 翻译全部完成后再调用导出 API。
3. **软告警是否升级为阻塞**：`synthetic_anchor_warn` 目前不阻塞，但大量出现时质量堪忧，是否纳入 Gate #1 值得讨论。
4. **重解析入口语义差异**：`reparse` 走当前文档的 fnm_mode 旗标；`api_doc_reparse_enhanced` 永远强制 FNM 模式，两者界面入口不同但用户易混淆。

---

## 七、边缘情况

- FNM 模式下文字层合并与页眉页脚清理**不会运行**（仅非 FNM 快速模式生效）；若需利用 PDF 文字层或去页眉页脚，需走非 FNM 重解析。
- 视觉 TOC 缺失 → `manual_toc_required=True`，需要用户上传 TOC PDF/截图后才能过 Gate #1。
- 同章 footnote + endnote 混存 → note_mode=`review_required`，阻塞。
- LLM API 返回不可重试错误码（400/401/403/404/422）→ FNM Worker 立刻终止当前 Unit，全局状态转 `failed`。
- 用户在「review_required」状态下尝试 `POST /fnm/translate` → 409 返回。
- `execution_mode=test` 可绕过 C5-3/C5-4/C5-5，仅用于离线/测试。
