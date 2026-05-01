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

## FNM Pipeline 数据流与 blocker 归因

Pipeline 共 6 个 phase，严格串行，每个 phase 的输出是下一个 phase 的输入。排查 blocker 时先找到最上游的断层 phase，修复并验证该层输出后再看下游。

```
Phase 1 → Phase 2 → Phase 3 → Phase 3.5 → Phase 4 → Phase 5 → Phase 6
```

### Phase 1：TOC 结构（`build_toc_structure()`）

包含 visual_toc 提取、page_partition（页面分区）、chapter_skeleton（章节骨架）。

| blocker | 触发条件 |
|---|---|
| `toc_pages_unclassified` | 存在页面未被分配合法 role |
| `toc_no_exportable_chapter` | 没有 role=chapter 的章节 |
| `toc_chapter_title_mismatch` | 章节标题未对齐 |
| `toc_chapter_order_non_monotonic` | 章节顺序非单调递增 |

### Phase 2：章节拆分与注释捕获（`build_chapter_layers()`）

包含 note_region_detection（注释区检测）、endnote_array_building（注释条目捕获）。

| blocker | 触发条件 |
|---|---|
| `split_items_sparse_note_capture` | 注释捕获验证失败（密集锚点页零捕获等） |

**上游依赖**：Phase 1 的章节边界和页面分区。如果 Phase 1 章节边界错了，Phase 2 的 note region 与 chapter 绑定会错位，导致注释分配到错误章节。

### Phase 3：锚点检测与链接（`build_note_link_table()`）

包含 body_anchor 提取（正文上标 marker 检测）和 note_link 匹配。

| blocker | 触发条件 |
|---|---|
| `link_endnote_not_all_matched` | 存在未匹配的尾注 |
| `contract_first_marker_not_one` | 章节首 marker ≠ 1 |
| `contract_marker_gap` | marker 序列有断裂 |
| `contract_def_anchor_mismatch` | 注释定义数 ≠ 正文锚点数 |
| `link_quality_low` | fallback_match_ratio 或 orphan anchor 数超过阈值 |

**上游依赖**：Phase 2 的注释条目数组。如果 Phase 2 注释没分对章，Phase 3 的合约校验（marker 序列、定义数对齐）必然大面积失败——这是"假阳性 blocker"，根因在 Phase 2。区分方法：看 Phase 2 的 `note_capture_summary`，如果 capture_ratio 严重偏离 1.0，则 Phase 3 的 blocker 是上游污染。

### Phase 3.5：LLM 修补（llm_repair）

不直接产出 blocker，但影响 Phase 4 输入。对 Phase 3 产生的 unresolved link 尝试 LLM 修补。

**已知问题模式**：
- `chapter_body_excerpt` 未传入（`book_endnote_bound` 模式书）→ LLM 完全无法工作
- 缺"一位置一 note"去重约束 → 多个 note 被绑到同一正文位置，downstream 触发 `token_not_found`

### Phase 4：引用冻结（`build_frozen_units()`）

| blocker | 触发条件 |
|---|---|
| `freeze_matched_ref_not_injected` | 存在 matched link 未真正注入正文（missing_body_page / synthetic_anchor / token_not_found） |

**性质**：正确的兜底拦截，不是 Phase 4 自身 bug。根因来自 Phase 1（页面分区）、Phase 3（锚点检测）、Phase 3.5（合成锚点）。

### Phase 5：章节合并（`build_chapter_markdown_set()`）

| blocker | 触发条件 |
|---|---|
| `merge_local_refs_unclosed` | 注释定义写进 NOTES 区但正文无对应引用 |
| `merge_frozen_ref_leak` | frozen ref token 泄漏到导出 markdown |

**性质**：下游症状层。

### Phase 6：导出审计（`build_export_bundle()`）

| blocker | 触发条件 |
|---|---|
| `export_audit_blocking` | 导出审计报告 can_ship=false |
| `export_raw_marker_leak` | 原始 marker 泄漏到最终导出文件 |

**性质**：最下游症状层。

### 兜底 fallback

| blocker | 来源 |
|---|---|
| `structure_review_required` | `web/export_routes.py`，只要有任何其他 blocker 就出现，无独立含义 |

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
