# 剩余 5 本书导出阻塞交接文档

日期：2026-04-19  
分支：未提交  
前置修复已落地：`_definition_has_raw_note_marker` 改为只检测"行首裸标记"、`update_fnm_run`/`update_fnm_translation_unit` 加 `doc_id` 签名参数、`_resolve_chapter_id_for_page` 章节 fallback。

## 当前状态（test_example 批处理）

| 书 | state | zip 落盘 | blocking |
|---|---|---|---|
| Biopolitics | ready | ✅ | — |
| Neuropsychoanalysis_Introduction | ready | ✅ | — |
| Napoleon | ready | ✅ | — |
| **Goldstein** | review_required | ❌ | `link_first_marker_not_one`, `link_endnote_not_all_matched`, `link_orphan_note_remaining`, `freeze_unit_contract_invalid` |
| **Heidegger_en_France** | review_required | ❌ | `toc_chapter_order_non_monotonic` |
| **Mad_Act** | review_required | ❌ | `freeze_unit_contract_invalid` |
| **Germany_Madness** | review_required | ❌ | `freeze_unit_contract_invalid`, `export_semantic_contract_broken` |
| **Neuropsychoanalysis_in_Practice** | review_required | ❌ | `toc_chapter_order_non_monotonic`, `toc_role_semantics_invalid`, `split_footnote_only_synthesis_failed` |

---

## 1. Goldstein — `link_*` 系列（最复杂，需要新模块）

### doc_id：`7ba9bca783fd`  slug：`post-revolutionary`

### 数据特征

- 9 个正文章节，全部 `book_endnote_bound`（全书级尾注）
- 903 body anchors（marker `1..169`，按章节各自重置）
- 11 note regions、496 note items
- **关键异常：490 条 note 全部挂到最后一个章节 `epilogue`**（原因见下）

### 根因

1. `build_note_regions` / `_endnote_scope_for_page`（`FNM_RE/stages/note_regions.py`）把 `scope='book'` 的尾注统一挂到"最后一个章节"，Goldstein 书后 10 个 note region 都落在 epilogue 下。
2. OCR 在尾注区按空白页切分，产生 10 个物理 region，但这些 region 并不按书原本的"Notes to Chapter N"边界对齐：
   - 有些 region 是完整章节 note 块（e.g. 0004 = Ch4 的 142 条）
   - 有些是同章节的碎片（Ch5 被切成 0005+0006，Ch7 被切成 0009+0010）
   - 有些 region 的 marker 范围（10..19、6..16）和任何章节都对不齐，疑似 OCR 遗漏
3. link 阶段按章节内 marker 匹配：epilogue 下 490 条 note vs 30 条 anchor → 匹配 30 条，其余 466 条 orphan_note；另有 873 条 orphan_anchor（Intro/Ch1/Ch2/Ch3 没有 region）。

**完整的 region-marker 表**：见 `output/tier1a_runs/20260419_224233/Goldstein/*.md`（最近一次 LLM tier1a 运行），或重跑 `python3 scripts/run_fnm_llm_tier1a.py --slug Goldstein`。

### LLM tier1a 已跑结果

`repair_count=1, auto_applied=11（全部 ignore_ref）, synth=0`。LLM 收到孤立集合后主要判断"这些正文 marker 不是真的 note 引用"（11 条 ignore_ref）和"需要人工复核"（16 条 needs_review），只产出 1 条 synthesize_anchor 且置信度不过阈值。**单靠当前 LLM 修补策略无法解决 Goldstein**。

### 建议修法（LLM 辅助 + 算法兜底）

#### 方案 A：新增 `region → 正文章节再绑定` 阶段

1. 新建 `FNM_RE/modules/region_chapter_binder.py`：
   - 输入：正文章节（`chapter_id`、标题、page 范围、该章节内 anchor 的 marker 范围 `[min..max]`、唯一 marker 数）+ back-matter 的 note regions（`region_id`、page 范围、note 数、marker 范围、前 2 条 note 文本 preview）
   - 输出：`{region_id: chapter_id}` 映射（允许多 region → 1 chapter；也允许"未绑定"）

2. 两级兜底策略：
   - **先算法**：region 按 page 顺序扫，检测"marker reset"（新 region 第一个 marker < 前一 region 最后一个 marker）作为分组边界；把同组 region 合并，按 marker 范围与章节 anchor 范围做**Jaccard 相似度匹配**，取最大匹配。
   - **算法拿不准时再 LLM**：相似度 < 0.6 或多章节候选时，把章节摘要 + region 摘要 + 每条 note 前 80 字节送给 LLM 要结论。

3. 映射结果写成 `review_override(scope='region_chapter_bind')`，在 `note_linking` 读 region 的 chapter_id 前优先读 override。

4. 没有对应 region 的章节（Goldstein 的 Intro/Ch1/Ch2/Ch3）：让 orphan_anchor 自然存在，交由后续 `synthesize_anchor` / manual_required 流程处理。

#### 实现提纲

```
FNM_RE/modules/region_chapter_binder.py
├── build_binding_candidates(chapters, regions, anchors, notes) -> list[BindingCandidate]
├── bind_by_marker_overlap(candidate) -> dict[region_id, chapter_id]  # 算法
├── request_llm_region_binding(candidates) -> dict                     # LLM
├── run_region_chapter_binding(doc_id, repo=None, mode='auto') -> dict
│   ├── 先尝试算法绑定
│   ├── 低置信度项交给 LLM
│   └── 写入 review_override(scope='region_chapter_bind')
└── apply_region_bindings_to_notes(doc_id, repo) -> int  # 改写 note_items 的 chapter_id（内存层，不改原始数据）
```

在 `FNM_RE/app/pipeline.py` 的 phase5 之前插入调用：

```python
if mode == "book_endnote_bound" and endnote_match_rate < 0.2:
    run_region_chapter_binding(doc_id, repo=repo)
    # 再重跑 note_linking
```

#### 测试需要覆盖

- `tests/unit/test_region_chapter_binder_marker_overlap.py`：Jaccard 匹配的边界条件（完整 region、碎片 region、无 region 的章节）
- `tests/integration/test_goldstein_link_after_binding.py`：Goldstein 的真实数据跑完一整轮，断言 `endnote_orphan_note ≤ 50`（残留的那几条 OCR 漏检的可以留给 manual_required）

#### 估时

- 算法部分：~150 行 + 测试 ~100 行
- LLM 接入：~100 行（复用 `llm_repair.request_llm_repair_actions` 的 session/model_args 基建）
- 回归 + 整合：~100 行

**总计：预估 2 人日**。没碰 link 阶段核心代码，纯新增 + 一次 override 读取。

### 已完成的铺垫

- 章节 `chapter_id` fallback：`FNM_RE/llm_repair.py:_resolve_chapter_id_for_page`（synthesize_anchor 用，已落地）
- Tier1a 批处理脚本能按 slug 独立跑：`python3 scripts/run_fnm_llm_tier1a.py --slug Goldstein`

### 开始接手时跑什么

```bash
# 1. 观察当前状态
python3 scripts/reingest_fnm_from_snapshots.py
python3 -c "
from persistence.sqlite_store import SQLiteRepository
repo = SQLiteRepository()
for r in repo.list_fnm_note_regions('7ba9bca783fd'):
    print(r['region_id'], r.get('start_page'), r.get('end_page'), r.get('chapter_id'))
"

# 2. 起 TDD 循环
python3 -m unittest tests.unit.test_region_chapter_binder_marker_overlap -v

# 3. 最终验收
python3 scripts/test_fnm_batch.py --group all
```

---

## 2. Heidegger_en_France — `toc_chapter_order_non_monotonic`

### doc_id：`a5d9a08d6871`  slug：`Heidegger_en_France`

### 数据特征

- 12 个正文章节，但编号跳号：`1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12`（缺 `8.`）

```
p317-346 | '9. La lettre et l'esprit'   ← 此处应为第 8 章？
p347-390 | '10. Le retour du refoulé ?'
```

- 其他指标都很好：matched=1523（99%），fallback=988，repair=113，orphan_anchor=39

### 可能原因

1. OCR 把原书第 8 章的编号识别错（"8" → "9"）
2. PDF 源本身就缺第 8 章（版本差异）
3. 视觉 TOC 绑定的 `目录.pdf` 里就缺

### 验证步骤

```bash
# 对比 PDF 源的实际章节标题
ls text_example/Heidegger_en_France/
# 若有原 PDF，翻到 p317 前一页，看标题是 "8." 还是 "9."
```

### 建议修法

- 如果是 OCR 错：在 `视觉 TOC 绑定` 阶段加章节编号连续性校验，发现跳号时让 LLM 看章节首页文本修复 chapter_number 字段
- 如果是源书就缺：放宽 `toc_chapter_order_non_monotonic` 门槛，允许 "known gap" 配置（`manual_toc_config.allow_missing_chapter_numbers=[8]`）

### 估时

- 方案 A（LLM 修编号）：半人日
- 方案 B（配置放行）：1 小时

**优先方案 B**，因为这本的其他指标极好，极可能是书本身就跳号（法国学术书偶见）。

---

## 3. Mad_Act — `freeze_unit_contract_invalid`

### doc_id：`bd05138cd773`  slug：`Mad_Act`

### 数据特征

- 16 个正文章节全部 `footnote_primary`（章末脚注）
- `matched=172, footnote_orphan_anchor=1555, endnote_orphan_note=92, ambiguous=8`
- 正文里有 **1555 个原始脚注 marker 没有落位**，这本书实际上 link 阶段已经严重失败，只是没触发 `link_*` 硬门槛（因为 `footnote_orphan_note=0`，意味着所有脚注 body 都能配到位置，但 body 里的 marker 找不到对应 note）

### 根因假设（需验证）

1555 个 orphan_anchor 极可能是 OCR 把每一页页底的完整脚注段误识为正文段落，导致 body_anchor 扫描把定义文本里的 `(1)`、`²` 等也统计成 body marker。和 Goldstein 一样需要章节级重绑定，但方向相反（这里 note 太少，body marker 太多）。

### 验证步骤

```python
from persistence.sqlite_store import SQLiteRepository
repo = SQLiteRepository()
# 看 orphan anchor 集中在哪几页
anchors = repo.list_fnm_body_anchors('bd05138cd773')
links = repo.list_fnm_note_links('bd05138cd773')
matched_anchor_ids = {l['anchor_id'] for l in links if l.get('status') == 'matched'}
from collections import Counter
by_page = Counter(a['page_no'] for a in anchors if a['anchor_id'] not in matched_anchor_ids)
print(by_page.most_common(20))
```

如果集中在少数页 → 这些页可能是脚注集中区，正文/脚注分区错了；`partition_heading_conflict_count` 在 pipeline 报告里应当同步看。

### 建议修法

- 先用上面脚本定位 orphan 最密集的页，抽 3~5 页人工核对
- 若确认是正文/脚注分区问题：在 `FNM_RE/stages/page_partition.py` 加 LLM 分页兜底（对 "body 文本里出现 >10 个 marker 但没有对应 note body" 的页面重新判定分区）

### 估时：1~1.5 人日（诊断 + 分区重判）

---

## 4. Germany_Madness — `freeze_unit_contract_invalid` + `export_semantic_contract_broken`

### doc_id：`67356d1f7d9a`  slug：`Germany_Madness`

### 数据特征

- 8 个章节全部 `footnote_primary`
- `matched=1051, footnote_orphan_anchor=74, endnote_orphan_note=22, ambiguous=17`（链路比较好）
- export 语义契约破了（mid_paragraph_heading / toc_residue / front_matter_leak / duplicate_paragraph 其中之一）

### 验证步骤

```python
# 看 semantic contract 具体是哪一项破的
import json
with open('output/fnm_batch_test_result.json') as f:
    data = json.load(f)
for item in data:
    if item['slug'] == 'Germany_Madness':
        exp = item.get('steps', {}).get('export', {})
        print('mid_paragraph_heading:', exp.get('mid_paragraph_heading_detected'))
        print('toc_residue:', exp.get('toc_residue_detected'))
        print('front_matter_leak:', exp.get('front_matter_leak_detected'))
        print('duplicate_paragraph:', exp.get('duplicate_paragraph_detected'))
        print('audit preview:', exp.get('full_audit_summary'))
```

### 根因候选

1. `freeze_unit_contract_invalid`：说明 freeze 阶段（`FNM_RE/stages/units.py`）对某些 unit 生成失败——可能是 cross-page 段落或 chapter boundary 附近的边界条件。
2. `export_semantic_contract_broken`：通常是章节 markdown 里混了 TOC 残渣 / front-matter 或重复段落，最常见是 OCR 把版权页、TOC 部分误分到第一章。

### 建议修法

- freeze_unit：跑 `python3 scripts/run_fnm_llm_tier1a.py --slug Germany_Madness --stage freeze` 诊断（如果这个 stage 参数不存在，直接读 `repo.list_fnm_translation_units('67356d1f7d9a')` 看有没有字段为空的 unit）
- semantic_contract：打开导出的 markdown（`test_example/Germany_Madness/` 下无 zip，需要强制导出一次），grep `^#{1,3} ` 看是否有异常标题

### 估时：1 人日（主要是 freeze 契约排错）

---

## 5. Neuropsychoanalysis_in_Practice — TOC 三连

### doc_id：`e7f8a1b6c2d3`  slug：`Neuropsychoanalysis_in_Practice`

### 数据特征

- 14 个章节，但其中有问题：

```
p281-298 | '11 Psychosis I: Psychodynamics and Phenomenology'
p300-335 | 'Psychosis II: Neuropsychodynamic Hypotheses'   ← 无章节编号
p342-352 | 'Epilogue: ...'
```

- 三个 blocking：
  - `toc_chapter_order_non_monotonic`：Psychosis II 无编号 → 排序断裂
  - `toc_role_semantics_invalid`：`toc_role_summary` 全 0，TOC role 分类阶段没产出
  - `split_footnote_only_synthesis_failed`：LLM 章节合成步骤失败

- link 指标：matched=63, footnote_orphan_anchor=45, fallback=3, repair=0（单次 LLM 都没跑起来）

### 根因

三个问题根源在**视觉 TOC 绑定的原始数据**：
1. 第 12 章标题"Psychosis II"在 `目录.pdf` / OCR 文本里丢失了前缀编号"12"
2. `toc_role` 阶段依赖章节编号推断角色（body/chapter/post_body），编号缺失 → 全 role 空
3. `split_footnote_only_synthesis_failed` 是下游：章节合成要 role，role 空 → 合成失败

### 建议修法

**首选：LLM 修标题**  
在 `FNM_RE/modules/toc_role_classifier.py`（或视觉 TOC 绑定阶段）里加一个 LLM 检查：  
把"章节标题列表 + 正文第一页截图/文字"送 LLM 问"这一章应该是第几章？"  
回填 `chapter_number` 字段后，其他两个 blocking 会自动消失。

### 估时：半人日 + 1 小时回归

---

## 总体交接清单

| 书 | 估时 | 关键改动文件 | 优先级 |
|---|---|---|---|
| Heidegger_en_France | 1 小时（放行配置） | `manual_toc_config.py` | 高（投入产出比最好） |
| Neuropsychoanalysis_in_Practice | 0.5 人日 | `modules/toc_role_classifier.py` | 高 |
| Mad_Act | 1.5 人日 | `stages/page_partition.py` | 中 |
| Germany_Madness | 1 人日 | `stages/units.py` + 导出语义审计 | 中 |
| Goldstein | 2 人日（见本文 §1） | 新模块 `modules/region_chapter_binder.py` | 低（复杂度最高） |

## 接手前先做的事

1. 读 `FNM_RE/MODULS.md`、`FNM_RE/STAGE1.md`..`STAGE6.md` 了解 pipeline 各阶段
2. 跑一次 `python3 scripts/test_fnm_batch.py --group all` 复现基线
3. 跑 `python3 -m unittest discover tests/unit -v` 和 `python3 -m unittest discover tests/integration -v`，确认所有现有测试绿
4. 用 AI 协作时强制先写能重现的失败测试（见 `CLAUDE.md` 第 5 条）

## 相关工具和文件索引

- 批处理脚本：`scripts/test_fnm_batch.py`、`scripts/reingest_fnm_from_snapshots.py`、`scripts/run_fnm_llm_tier1a.py`
- LLM 修补入口：`FNM_RE/llm_repair.py:run_llm_repair`
- 状态判定：`FNM_RE/status.py`、`FNM_RE/dev/gates.py`
- 视觉 TOC 绑定：`pipeline/document_tasks.py:run_auto_visual_toc_for_doc`
- 输出报告：`output/fnm_batch_test_result.{json,md}`、`output/tier1a_runs/<timestamp>/`
- 样本数据：`test_example/<slug>/` 下各种诊断文件

## 已完成的上游修复（本轮）

- `FNM_RE/stages/export_audit.py:_definition_has_raw_note_marker`：改为只检查行首裸标记，定义正文的档案号/叶码/嵌套上标不再误报。覆盖 Napoleon、Mad_Act、Heidegger 的 `export_raw_marker_leak`。
- `persistence/sqlite_repo_fnm.py:update_fnm_run/update_fnm_translation_unit`：签名改为 `(doc_id, run_id/unit_id, **fields)`，从 `_DOC_CONTEXT_METHODS` 移除。修复批脚本 UPDATE 漏写到 catalog 库的问题。
- `FNM_RE/llm_repair.py:_resolve_chapter_id_for_page`：synthesize_anchor 动作在 chapter_id 为空时按 page_no 回落到最近章节。覆盖 Goldstein 早期的 `invalid_coords` 误判。
- `scripts/run_fnm_llm_tier1a.py:_decide_verdict`：0 orphan 的书不再跑 LLM，直接 SKIP。

覆盖以上回归的单测：

- `tests/unit/test_definition_raw_marker_scope.py`
- `tests/unit/test_update_fnm_run_routes_to_doc_db.py`
- `tests/unit/test_llm_repair_chapter_fallback.py`
- `tests/unit/test_tier1a_verdict_skip_no_orphans.py`
