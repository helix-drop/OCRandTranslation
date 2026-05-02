# 仓库工作规则

这份文档只写当前仓库里最需要遵守的规则，尽量短，不和 [DEV.md](/Users/hao/OCRandTranslation/DEV.md) 混写。

1. 全部用中文回复。
2. 写代码或改文档前，先说明方案。
3. 需求不清楚时，先澄清再动手。
4. 不写兼容性代码，除非用户主动要求。
5. 出 bug 先写能重现的测试，再修复。
7. 写完后列出边缘情况，并先自行验证再交付。
8. 对用户汇报时，只说做了什么、结果怎样、能不能用，不堆术语。
9. 没确认完成前，不要提前收工。
10. 不要机械追求最小改动；当实现功能必须做较大改动或重构时，要明确提出并敢于推进相关决策。

## 文档分工

| 文档 | 作用 |
|---|---|
| [DEV.md](/Users/hao/OCRandTranslation/DEV.md) | 稳定说明、结构、运行方式、数据位置 |
| [PROGRESS.md](/Users/hao/OCRandTranslation/PROGRESS.md) | 当前进度、最近实测、下一步工作 |
| [CLAUDE.md](/Users/hao/OCRandTranslation/CLAUDE.md) | 给 Claude/同类代理看的简版约束 |
| [verification.md](/Users/hao/OCRandTranslation/verification.md) | 验证记录 |

## 维护原则

1. 新事实优先写进对应文档，不要所有内容都堆在一个文件里。
2. 路径、端口、目录名以代码为准，改代码后同步改文档。
3. 临时结论放 `PROGRESS.md`，稳定结论放 `DEV.md`。

## 设计原则：不写逐书修补的代码

修 bug 时不能"来一本书补一本书"——不能靠枚举特例、硬编码阈值、扩充黑名单来适配当前测试书。这类修补会让代码越来越脆，下一本新书必然再次崩在同一位置。

正确做法：

1. **用 pipeline 中已有的数据驱动判断，不引入外部假设。** 例如要知道某章的 endnote marker 范围，应该读 `fnm_note_items` 的实际数据，而不是猜一个 `max_marker=200` 的常量。
2. **正向验证优于黑名单排除。** "我只信在已确认范围内的 marker"比"我不信这些词后面的数字"更稳定——前者由每本书自己的数据结构保证，后者靠穷举一种语言/排版惯例。
3. **缺口填补用已知序列推断，不做文本猜测。** OCR 丢失了一个 superscript，应该用前后已检测 marker 的位置和 note_items 的预期序列来定位，而不是在 OCR 文本里搜"可能是 47 的东西"。
4. **改完后用另一本书回归。** Goldstein 修完跑 Biopolitics，Biopolitics 修完跑 Goldstein。两本书结构差异越大，回归越有价值。
5. **模块化修补，先上游再下游。** pipeline 阶段之间有明确的数据依赖，修 bug 时必须从最上游的断层开始，验证该层输出正确后再进入下一层。跳层修补会造成下游基于错误输入做正确决策的假象。具体数据流和 blocker 归属见下方"FNM Pipeline 数据流与 blocker 归因"。
## 设计原则：树枝状条件处理

这是贯穿整个代码库的**最高优先级**原则。违反它是一切"修不好的 bug"的根因。

### 核心思想

代码中的每个条件分支像一棵树：从根（数据源）到叶（最终决策），每一层分叉都必须**精确、排他、无遗漏**。分支之间不允许交叉感染，上层决策不允许被下层推翻。

### 五条铁律

**1. 分类源头唯一。** 每个 entity 的类型（如 footnote vs endnote）只能在**一个位置、一次性地**决定。这个位置是数据产生的地方（如 `chapter_layers` 构建时），不是数据消费的地方。下游代码只能读取这个分类，不能重新推断或覆盖。

> 反例：`_phase2_from_chapter_layers` 按 `chapter_mode` 把所有 item 的 `note_kind` 统一覆盖——这就是"下游重新推断"。note_kind 应该在 `chapter_layers` 构建时逐条确定，`_phase2_from_chapter_layers` 只是透传。

**2. 分支条件穷尽且互斥。** 每个 `if/elif/else` 必须覆盖所有可能情况，且分支之间不能有隐含重叠。`else` 只能用于"其它所有情况都处理不了"的兜底，不能悄悄吞掉未预期的输入。

> 反例：`if chapter_mode == "footnote_primary": note_kind = "footnote"` —— 这条分支把 `chapter_mode` 当作个体 entity 的类型，混淆了"章的聚合属性"和"entity 的个体属性"两个不同层次的概念。

**3. 禁止广播。** 永远不能把容器（章/书）的聚合属性赋值给容器内的个体 entity。章的 `note_mode` 描述的是"这章的主注释类型是什么"，不能用来覆盖章内每个 item 的 `note_kind`。同一章内可以同时存在 footnote 和 endnote，它们的分类必须独立于章的聚合属性。

**4. 上下游隔离。** 每个 phase 产出的数据结构是**不可变事实**。下游 phase 只能消费这些事实，不能因为自己的需求不同而重新解释上游的决策。如果下游发现上游数据"不对"，修上游，不要在下游打补丁。

> 反例：Phase 3 的 `_repair_endnote_links_for_contract` 用 `chapter_mode` 跳过整章——这是 Phase 3 在推翻 Phase 2 的 region 数据。如果 region 说这里有 endnote，Phase 3 就应该处理，不管 chapter_mode 怎么说。

**5. 集中 dispatch，分散处理。** 当一个函数需要处理多种类型（如同时处理 footnote 和 endnote 的 link），结构和处理必须分离：一个 dispatch 层按类型分流，每种类型有独立的处理函数。不允许在同一个循环里用 `if kind == X` 交叉处理不同逻辑。

> 正例：`build_note_links` 的 endnote_resolver 和 footnote_resolver 是分开的循环。反例：一个循环里混写 footnote 和 endnote 的匹配、修复、dedup 逻辑。

## FNM Pipeline 数据流与 phase 职责边界

Pipeline 共 6 个 phase，严格串行。**每个 phase 只做一种决策**——这是树状原则在架构层的体现。决策权不重复、不下放、不旁路。

```
Phase 1 → Phase 2 → Phase 3 → Phase 3.5 → Phase 4 → Phase 5 → Phase 6
```

### Phase 1：TOC 结构与页面分区

| 项 | 内容 |
|---|---|
| **决策权** | ① 每页的 `page_role`（body/note/front_matter/back_matter）② 章节骨架与边界 |
| **输入** | OCR 页面 + 目录数据（自动/手动 visual TOC） |
| **产出** | `PagePartition`（page_role）+ `ChapterRecord`（start_page/end_page） |
| **禁止** | 不关心注释内容、不判断 footnote/endnote 类型 |
| **代码** | `toc_structure.py`、`stages/page_partition.py` |

| blocker | 触发条件 |
|---|---|
| `toc_pages_unclassified` | 存在页面未被分配合法 role |
| `toc_no_exportable_chapter` | 没有 role=chapter 的章节 |
| `toc_chapter_title_mismatch` | 章节标题未对齐 |

### Phase 2：注释捕获与分类

| 项 | 内容 |
|---|---|
| **决策权** | ① **每个 note item 的 `note_kind`（footnote vs endnote）**——这是全书唯一的分类来源 ② 每章的 `note_mode`（聚合属性，仅用于 contract gate，不能广播）③ `chapter_mode` 是章的摘要信号，不是个体 entity 的标签 |
| **输入** | Phase 1 的章节边界 + 页面分区 |
| **产出** | `NoteRegion`（含 note_kind）+ `NoteItem`（含 note_kind, marker）+ `ChapterNoteMode`（含 note_mode） |
| **禁止** | 不匹配 link、不猜测 body anchor、**不允许下游覆盖 note_kind** |
| **代码** | `chapter_split.py`、`stages/note_regions.py`、`stages/note_items.py` |

| blocker | 触发条件 |
|---|---|
| `split_items_sparse_note_capture` | 注释捕获验证失败 |

**书型问题必须在 Phase 2 内解决**：如果某章的 footnote/endnote 分类不对，加强 Phase 2 的识别能力（如 note_region 检测、`## NOTES` 标题匹配），不要把分类问题推给 Phase 3/4 用 chapter_mode 门禁绕过。

### Phase 3：锚点检测与链接匹配

| 项 | 内容 |
|---|---|
| **决策权** | ① body anchor 检测（正文上标 marker 扫描）② anchor 与 note_item 的一对一匹配 ③ unmatched link 修复 |
| **输入** | Phase 2 的 NoteItem（含 note_kind）+ NoteRegion + Phase 1 的页面数据 |
| **产出** | `BodyAnchor`（含 anchor_kind, marker）+ `NoteLink`（含 status: matched/orphan_note/orphan_anchor） |
| **禁止** | **不能重新分类 note_kind**——Phase 2 已经决定了，Phase 3 只消费。**不能用 chapter_mode 跳过整章的 link 修复**——修复判断标准是 link 自身的 note_kind 和 status。**不能把 anchor_kind 按章广播**——anchor_kind 只能由逐页 evidence（如 fnBlock）决定 |
| **代码** | `stages/body_anchors.py`、`stages/note_links.py`、`modules/note_linking.py` |

| blocker | 触发条件 |
|---|---|
| `link_endnote_not_all_matched` | 存在未匹配的尾注 |
| `contract_marker_gap` | marker 序列有断裂 |
| `contract_def_anchor_mismatch` | 章内 def 数与 anchor 数不一致 |
| `link_quality_low` | fallback 占比或 orphan_anchor 数超阈值 |

### Phase 3.5：LLM 修补

| 项 | 内容 |
|---|---|
| **决策权** | LLM 辅助合成 anchor、建议 link 匹配 |
| **输入** | Phase 3 的 orphan links |
| **产出** | 合成 anchor + link override（写入 `fnm_review_overrides_v2`） |
| **禁止** | 不能绕过 Phase 2 的 note_kind 分类 |

### Phase 4：引用冻结与翻译单元生成

| 项 | 内容 |
|---|---|
| **决策权** | 将 matched link 注入正文（用 anchor 坐标替换原文标记）、生成翻译单元 |
| **输入** | Phase 3 的 matched links + Phase 3.5 的合成 anchors |
| **产出** | 注入后的 body text + `TranslationUnit` 列表 |
| **禁止** | 不修改 link 匹配结果。如果 anchor 无法注入（synthetic/坐标缺失），报 blocker 而不是静默跳过 |

| blocker | 触发条件 |
|---|---|
| `freeze_matched_ref_not_injected` | 存在 matched link 无法注入正文 |

### Phase 5：章节 Markdown 合并

| 项 | 内容 |
|---|---|
| **决策权** | 章内 body text + footnote 定义 + endnote 定义 → 单章 markdown |
| **输入** | Phase 4 的注入后 body text + note 定义 |
| **产出** | 单章 markdown 文本 |
| **禁止** | 不修改 link、不重新匹配 |

| blocker | 触发条件 |
|---|---|
| `merge_local_refs_unclosed` | 注释定义无对应正文引用 |
| `merge_frozen_ref_leak` | frozen ref token 泄漏 |

### Phase 6：导出审计

| 项 | 内容 |
|---|---|
| **决策权** | 整书组装、最终质量检查 |
| **输入** | Phase 5 的各章 markdown |
| **产出** | Obsidian ZIP 导出包 |
| **禁止** | 不修改任何上游数据 |

| blocker | 触发条件 |
|---|---|
| `export_audit_blocking` | 导出审计 can_ship=false |

## FNM 测试脚本分层

三种测试脚本，数据源和产物不同，禁止混用：

### 1. 增量测试 `scripts/test_fnm_incremental.py`

**用途**：冻结已确认成果，层层推进修复。已通过的 phase 不再重跑，每次只对剩余问题逐层处理。支持 `--repair` 调 LLM 修补残余 orphan。

**数据源**：
- `Module Phase 2/3`：来自 `build_module_pipeline_snapshot()` 的模块管道输出（`split_result.data` / `link_result.data.link_summary`）。这是 Phase 3 gate 的权威来源。
- `Persisted Phase 2/3`：来自 `SQLiteRepository` 的落库读回（`fnm_note_items` / `fnm_body_anchors` / `fnm_note_links`）。这是 Phase 4-6 持久化后的数据。

**关键约定**：Module 和 Persisted 是同一次 pipeline run 的两个视角，但数值可能不同——Phase 4 会把未注入的 matched link 重新打开成 orphan_note。当两者分叉时，**以 Module Phase 3 作为 Phase 3 gate 的判断来源**，Persisted 的分叉由 Phase 4 blocker 解释。

**产物**：只输出到终端，不写文件。

### 2. 实批 `scripts/test_fnm_real_batch.py`

**用途**：真实视觉 TOC + 真实 LLM repair 的完整集成测试。

**数据源**：同批测，但额外调用视觉模型和 LLM repair API。

**产物**：
- `test_example/<书名>/FNM_REAL_TEST_REPORT.md`（注意：可能过期）
- `test_example/<书名>/fnm_real_test_modules.json`
- `test_example/<书名>/fnm_real_test_progress.json`
- `test_example/<书名>/fnm_real_test_result.json`
- `test_example/<书名>/llm_traces/`

### 时间戳约定

- 每次 pipeline run 都会在 SQLite `fnm_runs` 表中创建一条记录，包含 `created_at`。
- 增量脚本输出的 `Module Phase 2/3` 数据来自当次 snapshot 构建，不是历史 DB 数据。
- 实批报告 `FNM_REAL_TEST_REPORT.md` 的 `generated_at` 字段记录了报告生成时间；如果该时间早于最近一次 pipeline run，报告数据视为过期。
- **判断任何 blocker 前，先确认数据来源的时间戳**：增量看终端输出时间，批测看 `latest_export_status.json` 的 `timestamp`，实批看报告 `generated_at`。

## FNM 调试方法论

### 基本原则

修 bug 不能靠猜。每个 blocker 都要追溯到**具体的页面**，查看：
1. **PDF 原页**——用 `scripts/inspect_page.py` 调用视觉模型看排版
2. **raw_pages.json**——看 markdown、blocks、fnBlocks、footnotes 字段
3. **fnm_real_test_modules.json**——看各 module 的中间输出（region、item、link、contract）
4. **SQLite DB**——`list_fnm_note_items` / `list_fnm_body_anchors` / `list_fnm_note_links` 查实际数据

### 视觉辅助脚本

```bash
# 检查单页（渲染 PDF + 调视觉模型分析）
.venv/bin/python scripts/inspect_page.py --slug Biopolitics --page 104

# 连续多页
.venv/bin/python scripts/inspect_page.py --slug Goldstein --page 160 --range 3

# 对比正文页和注释页
.venv/bin/python scripts/inspect_page.py --slug Biopolitics --page 104 --compare 111

# 只导出数据不调模型
.venv/bin/python scripts/inspect_page.py --slug Biopolitics --page 104 --no-vision
```

输出保存到 `/tmp/fnm_inspect/`：渲染的 JPG + 模型分析 JSON。

### 常见断层模式与修复策略

#### 1. 章模式误判（Phase 1 → Phase 2 边界）

**症状**：纯脚注书的某章被标为 `chapter_endnote_primary`，捕获率为 0。
**追查路径**：
1. 查 `fnm_real_test_modules.json` → `endnote_array_building.note_capture_summary` 看哪些章 mode 不对
2. 查 `book_note_type.py` 的 `_is_endnote_page` 判断——页首是否有 `## NOTES` 标题
3. 区分**强信号**（显式 `## NOTES`/`## Endnotes` 标题）和**弱信号**（`endnote_collection` 或无标题的 ≥4 编号定义）
4. 强信号始终保留，弱信号在 TOC 无 endnotes 条目时降级
**修复位置**：`FNM_RE/modules/book_note_type.py` 的 `build_book_note_profile()`

#### 2. bare_digit 假阳性（Phase 3）

**症状**：`contract_def_anchor_mismatch` 每章多 1-4 个 anchor；`link_quality_low`。
**追查路径**：
1. SQLite 查每章的 anchor 去重计数 vs note_item 计数：`Counter(marker for anchor in chapter_anchors)`
2. 找重复/孤儿 marker，检查 `source_text` 上下文
3. 假阳性特征：日期（"August 4, 1789"）、列表（"4, 5 or 6"）、千分位（"2,000"）、文档编号（"Mémoire 10"）、课程编号（"Lesson 1"）
4. 用 `inspect_page.py` 看 PDF 确认
**修复位置**：`FNM_RE/shared/anchors.py` 的 `_is_bare_digit_marker_context()`
**注意**：bare_digit 是优先级最低的模式（priority=6），只在 `<sup>`、`$^{N}$`、`[N]`、unicode 上标都未命中时才触发。修复时应优先考虑**加新识别模式**（如 `apostrophe_sup`），再考虑收紧 bare_digit 守卫。

#### 3. dense_anchor_zero_capture 假阳性（Phase 2）

**症状**：`split_items_sparse_note_capture`，但 note capture 整体正常。
**追查路径**：
1. 查 `_note_capture_summary` 的 `captured_pages` 收集逻辑——只收了 `footnote_items` 没收 `endnote_items`
2. `book_endnote_bound` 书的尾注条目在全书尾注区（不在正文页），逐页比对无意义
**修复位置**：`FNM_RE/modules/chapter_split.py` 的 `_note_capture_summary()`

#### 4. LLM repair 无法合成锚点（Phase 3.5）

**症状**：cluster 全部 `needs_review`，auto_applied=0。
**追查路径**：
1. 查 `request_metrics` 的 `request_mode`——`note_only` 说明没有 `chapter_body_text`
2. 追 `_build_chapter_body_text` → `repo.load_pages` → page markdown 是否为空
3. 检查 `has_body_text` 的 fallback 是否生效
**修复位置**：`FNM_RE/llm_repair.py` 的 `_build_chapter_body_text()` 和 `request_llm_repair_actions()`
