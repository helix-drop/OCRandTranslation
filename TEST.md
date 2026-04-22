# FNM_RE 重构测试说明

这份文档只服务于当前 `FNM_RE` 模块化重构。

旧测试方式已经不再作为本轮验收口径：

- 不再用默认 8 本样本批测作为硬门槛。
- 不再用旧 `phase1~phase6` 测试名称作为结构正确性的依据。
- 不再用“导出的 markdown 看起来差不多”反推流程正确。
- 不再把旧报告里的历史通过结论当作当前可用性证明。

本轮测试必须跟随重构阶段走：每完成一个阶段，就只测该阶段的模块、gate、投影和 Biopolitics 单书链路。

---

## 1. 当前唯一验收样本

本轮唯一硬验收样本是 `Biopolitics`。

| 项 | 路径 / 值 |
|---|---|
| 样本目录 | `test_example/Biopolitics/` |
| PDF 原文 | `test_example/Biopolitics/Foucault和Foucault - 2004 - Naissance de la biopolitique.pdf` |
| 手动目录 | `test_example/Biopolitics/目录.pdf` |
| JSON 布局 | `test_example/Biopolitics/raw_pages.json` |
| MD 文本 | `test_example/Biopolitics/raw_source_markdown.md` |
| doc_id | `0d285c0800db` |
| 期望页数 | `370` |

说明：

- 如果后续用户提供的 `example_text/Biopolitics` 是另一份目录，只替换本节输入路径。
- 本轮只要求 Biopolitics 跑通。
- 其他书的失败、回归、语义偏差，先记录为后续修补项，不阻塞本轮。

---

## 2. 总测试原则

### 2.1 每阶段单独验收

每个阶段必须有自己的测试，不允许只在最后跑总链路。

每阶段至少验证：

1. 本阶段模块能接收上游真相对象。
2. 本阶段模块能产出下游真相对象。
3. 本阶段 `GateReport.hard` 能正确通过。
4. 至少一个 hard gate 失败样例能被阻塞。
5. 至少一个 override 放行样例能记录到 `overrides_used`。
6. Biopolitics 在该阶段的关键事实稳定。

### 2.2 每模块只测自己的职责

模块测试禁止跨层兜底。

例如：

- `toc_structure` 测章节骨架，不测尾注链接。
- `chapter_split` 测正文/注释切分，不测 token 冻结。
- `note_linking` 测链接 contract，不测导出 markdown。
- `status.py` 只测 gate 汇总，不测业务推断。

### 2.3 旧脚本的使用方式

旧脚本只允许作为临时外层烟测，不作为模块通过依据。

可临时保留的命令：

```bash
python3 scripts/generate_visual_toc_snapshots.py --slug Biopolitics
python3 scripts/apply_manual_toc_to_examples.py --slug Biopolitics --skip-fnm
python3 scripts/test_fnm_batch.py --slug Biopolitics
```

使用限制：

- `test_fnm_batch.py --slug Biopolitics` 只作为最终单书烟测。
- 任何模块是否通过，必须看该模块自己的单测和 `GateReport`。
- 默认 8 本批测不再属于本轮验收。

---

## 3. 阶段测试办法

### 阶段 0：边界合同与测试夹具

目标：

- 固定 Biopolitics 单书输入。
- 固定 `ModuleResult / GateReport` 协议。
- 固定 worker/repo/diagnostic 投影合同。

必须测试：

- `raw_pages.json` 可解析为 370 页。
- 每页至少有 `bookPage` 和 `markdown`。
- `目录.pdf` 存在且可作为 manual toc 输入。
- `ModuleResult` 至少包含 `data / gate_report / evidence / overrides_used / diagnostics`。
- `GateReport` 至少包含 `module / hard / soft / reasons / evidence / overrides_used`。
- 当前 `TranslationUnit` 投影合同仍包含 `kind / owner_kind / owner_id / section_id / section_title / note_id / page_segments / target_ref`。

通过条件：

- Biopolitics 夹具加载稳定。
- 不需要访问网络或真实 LLM。
- 不改 SQLite 表语义也能构造测试输入。

建议测试名：

- `tests/unit/test_fnm_re_stage0_contract.py`

---

### 阶段 1：目录结构与书型

覆盖模块：

- `toc_structure`
- `book_note_type`

必须测试：

- Biopolitics 页面角色全部有外部角色，且对外不暴露 `noise`。
- TOC 能形成 `toc_tree`。
- exportable chapters 数量稳定。
- 目录顺序与章节页码单调一致。
- `container / chapter / post_body / back_matter` 不混用。
- Biopolitics 能产出明确 `book_type`，不允许 `unknown`。
- 章级 `note_mode` 与全书 `book_type` 不冲突。

通过条件：

- `toc.pages_classified=true`
- `toc.has_exportable_chapters=true`
- `toc.chapter_titles_aligned=true`
- `toc.chapter_order_monotonic=true`
- `toc.role_semantics_valid=true`
- `book_type.resolved=true`
- `book_type.chapter_modes_consistent=true`
- `book_type.no_unapproved_review_required=true`

建议测试名：

- `tests/unit/test_fnm_re_module1_toc.py`
- `tests/unit/test_fnm_re_module2_book_type.py`

---

### 阶段 2：章节正文与注释切分

覆盖模块：

- `chapter_split`

必须测试：

- Biopolitics 的 footnote band 能识别为脚注层。
- Biopolitics 的 chapter/book endnote regions 能绑定到正确章节或书级容器。
- note items 能从 structured scan / page text / pdf text 兜底链中稳定产出。
- 同页正文与注释切线明确，不靠导出层再猜。
- 跨页正文段落不出现明显截断。
- `mixed` 书脚注策略明确记录。
- 如出现 `footnote_only` 样例，脚注必须合成统一尾注区并从 1 连续编号。

通过条件：

- `split.regions_bound=true`
- `split.items_extracted=true`
- `split.body_note_disjoint=true`
- `split.cross_page_continuity_ok=true`
- `split.policy_applied=true`
- 对 Biopolitics：`split.mixed_marker_materialized=true` 或明确记录该章无正文内脚注 materialize 需求。

建议测试名：

- `tests/unit/test_fnm_re_module3_split.py`

---

### 阶段 3：注释链接与引用冻结

覆盖模块：

- `note_linking`
- `ref_freeze`

必须测试：

- anchor 能从 markdown 和 OCR block 双来源抽取。
- 年份等伪 marker 不会误当注释 anchor。
- Biopolitics 尾注 direct match 与 repair match 都能稳定记账。
- 需要章级尾注闭合的章节必须全部满足链接 contract。
- `ambiguous / orphan_note` 不允许静默通过。
- 只冻结 `matched` link。
- synthetic、ambiguous、orphan、ignored 都不得被冻结。
- token 注入失败必须有 skip reason。
- 输出 units 仍满足当前 worker 投影合同。

通过条件：

- `link.first_marker_is_one=true`
- `link.endnotes_all_matched=true`
- `link.no_ambiguous_left=true`
- `link.no_orphan_note=true`
- `freeze.only_matched_frozen=true`
- `freeze.no_duplicate_injection=true`
- `freeze.accounting_closed=true`
- `freeze.unit_contract_valid=true`

建议测试名：

- `tests/unit/test_fnm_re_module4_linking.py`
- `tests/unit/test_fnm_re_module5_freeze.py`

---

### 阶段 4：单章合并与整书导出

覆盖模块：

- `chapter_merge`
- `book_assemble`

必须测试：

- 译后 body unit 能合并为单章 markdown。
- `{{NOTE_REF:*}}` 能改写为本章局部 `[^n]`。
- raw marker fallback 只在本模块发生。
- 每个 `[^n]` 都有定义，每个定义都被正文引用。
- 每个 exportable chapter 恰好一个 `.md`。
- 整书顺序来自 `toc_tree`，不再按 `start_page` 重新排序。
- 整书 audit 能检查 raw marker 残留、跨章污染、重复段、语义合同。

通过条件：

- `merge.chapter_files_emitted=true`
- `merge.local_refs_closed=true`
- `merge.no_frozen_ref_leak=true`
- `merge.no_raw_marker_leak_in_body=true`
- `export.order_follows_toc=true`
- `export.semantic_contract_ok=true`
- `export.audit_can_ship=true`
- `export.no_cross_chapter_contamination=true`
- `export.no_raw_marker_leak_book_level=true`

建议测试名：

- `tests/unit/test_fnm_re_module6_merge.py`
- `tests/unit/test_fnm_re_module7_export.py`

---

### 阶段 5：主线切换与状态收口

覆盖范围：

- `app/pipeline.py`
- `app/mainline.py`
- `status.py`
- repo/runtime 投影层

必须测试：

- 主线按 7 个模块顺序执行。
- `mainline.py` 只做 doc/repo 接线，不新增业务判断。
- repo overlay 只叠加历史翻译，不推翻业务真相对象。
- `status.py` 只汇总 7 个模块的 `GateReport`。
- `blocking_reasons` 全部来自模块 hard gate。
- 旧 `phase1~phase6` 公开入口下线。

通过条件：

- Biopolitics 单书主线 `structure_state=ready`。
- `blocking_reasons=[]`。
- `export_ready_test=true`。
- `chapter_local_endnote_contract_ok=true`。
- 导出 zip 落盘到 `test_example/Biopolitics/latest.fnm.obsidian.zip`。

建议测试名：

- `tests/integration/test_fnm_re_mainline_biopolitics.py`
- `tests/unit/test_fnm_re_status_gate_summary.py`

---

## 4. 模块通过条件速查

| 模块 | 通过条件 |
|---|---|
| `toc_structure` | 页面角色完整、TOC 树稳定、章节顺序合法、无标题错配 |
| `book_note_type` | 全书书型明确、章级 mode 与书型一致、无未批准 `review_required` |
| `chapter_split` | region/item/body 三层切清、正文/注释不重叠、策略明确 |
| `note_linking` | 尾注 contract 闭合、无 orphan note、无 ambiguous |
| `ref_freeze` | 只冻结 matched、注入不重复、unit 合同有效 |
| `chapter_merge` | 单章 markdown 闭合、无 token/raw marker 泄漏 |
| `book_assemble` | 顺序跟随 TOC、整书 audit 可 ship、无跨章污染 |
| `status.py` | 只汇总 gate，不反推业务事实 |

---

## 5. Biopolitics 最终硬验收

最终只认 Biopolitics 本轮结果。

必须满足：

- `structure_state == "ready"`
- `blocking_reasons == []`
- `export_ready_test == true`
- `chapter_title_alignment_ok == true`
- `chapter_local_endnote_contract_ok == true`
- `endnote_orphan_note == 0`
- `endnote_orphan_anchor == 0`
- `ambiguous == 0`
- 导出文件中无 `{{NOTE_REF:*}}`
- 导出正文中无未处理 raw note marker
- `test_example/Biopolitics/latest.fnm.obsidian.zip` 存在且来自本轮生成

最终烟测命令：

```bash
python3 scripts/test_fnm_batch.py --slug Biopolitics
```

注意：

- 这条命令只是最终烟测。
- 如果它失败，必须回到对应模块 gate 定位。
- 不允许靠导出结果手工修补绕过模块 gate。

---

## 6. 失败定位办法

### TOC 或章节错

先看：

- `toc.pages_classified`
- `toc.chapter_titles_aligned`
- `toc.chapter_order_monotonic`
- `toc.role_semantics_valid`

处理方向：

- 只修 `toc_structure`。
- 不允许在导出层调整章节顺序。

### 书型或 chapter mode 错

先看：

- `book_type.resolved`
- `book_type.chapter_modes_consistent`
- `book_type.no_unapproved_review_required`

处理方向：

- 只修 `book_note_type` 的证据采集和 mode 规则。
- 不允许在 `chapter_split` 中重新判书型。

### 正文/注释混乱

先看：

- `split.regions_bound`
- `split.items_extracted`
- `split.body_note_disjoint`
- `split.cross_page_continuity_ok`
- `split.policy_applied`

处理方向：

- 只修 `chapter_split`。
- 不允许让 `note_linking` 或 `chapter_merge` 重新切正文。

### orphan 或 ambiguous

先看：

- `link.endnotes_all_matched`
- `link.no_ambiguous_left`
- `link.no_orphan_note`

处理方向：

- 只修 `note_linking`。
- explicit override 必须写入 `overrides_used`。

### token 或导出引用错

先看：

- `freeze.accounting_closed`
- `merge.local_refs_closed`
- `merge.no_frozen_ref_leak`
- `merge.no_raw_marker_leak_in_body`

处理方向：

- token 注入问题修 `ref_freeze`。
- 解冻、本地编号和 raw marker fallback 修 `chapter_merge`。

### 整书 zip 或审计错

先看：

- `export.order_follows_toc`
- `export.semantic_contract_ok`
- `export.audit_can_ship`
- `export.no_cross_chapter_contamination`

处理方向：

- 只修 `book_assemble` 或 `export_audit`。
- 不回头改写单章 markdown 内容。

---

## 7. 后续扩展测试

Biopolitics 跑通后，再逐步恢复其他书。

恢复顺序建议：

1. 先选一本脚注为主的书。
2. 再选一本书尾尾注为主的书。
3. 再选一本目录层级复杂的书。
4. 最后恢复默认多书批测。

恢复默认多书批测前，必须满足：

- 7 个模块都有独立测试。
- Biopolitics 单书集成测试稳定通过。
- `status.py` 已经完全改成 gate 汇总。
- 旧 `phase1~phase6` 测试不再作为通过依据。

---

## 8. 记录要求

每完成一个阶段，更新：

- `FNM_RE/OnWorking.md`
- `verification.md`

记录内容只写三类：

1. 做了什么阶段。
2. Biopolitics 当前通过到哪一步。
3. 剩余阻塞 gate 是什么。

不要再写“默认 8 本通过所以本阶段可用”这类旧结论。

---

## 9. LLM Tier 1a 修补链路测试（脚注 + 尾注）

这一节用于验证 `FNM_RE.llm_repair`（DashScope Qwen 调用）在 orphan cluster 上的 **合成锚点 → 物化成 `BodyAnchorRecord` → `note_linking` 重建为 matched link** 全链路。

适用样本：`test_example/example_manifest.json` 中除 Biopolitics 之外的 7 本（Germany_Madness / Goldstein / Heidegger_en_France / Mad_Act / Napoleon / Neuropsychoanalysis_in_Practice / Neuropsychoanalysis_Introduction）。

### 9.1 前置条件

1. 环境变量：`DASHSCOPE_API_KEY` 已导出，账户有可用额度。
2. 代码版本必须包含：
   - `FNM_RE/modules/note_linking.py::_materialize_anchor_overrides`（消费 scope="anchor" override）
   - `FNM_RE/app/pipeline.py::_group_review_overrides` 的 `known_scopes` 包含 `"anchor"`
   - `FNM_RE/llm_repair.py::build_unresolved_clusters` 不过滤 footnote
   - `FNM_RE/llm_repair.py` 的 synthesize_anchor auto-apply 分支中 `"anchor_kind": note_system`（动态，而非硬编码 `"endnote"`）
3. 所有 399 条 `tests/unit` + `tests/integration` 单测通过：
   ```bash
   python3 -m unittest discover -s tests/unit -v
   ```

#### 9.1.1 七本样本映射（准备阶段）

以下 `slug/doc_id` 来自 `test_example/example_manifest.json` 当前版本，开跑前若有变动以 manifest 实际值为准：

| slug | doc_id | manifest.folder |
|---|---|---|
| Germany_Madness | `67356d1f7d9a` | `Germany_Madness` |
| Goldstein | `7ba9bca783fd` | `post-revolutionary` |
| Heidegger_en_France | `a5d9a08d6871` | `Heidegger_en_France` |
| Mad_Act | `bd05138cd773` | `Mad_Act` |
| Napoleon | `5df1d3d7f9c1` | `Napoleon` |
| Neuropsychoanalysis_in_Practice | `e7f8a1b6c2d3` | `Neuropsychoanalysis_in_Practice` |
| Neuropsychoanalysis_Introduction | `a3c9e1f7b284` | `Neuropsychoanalysis_Introduction` |

#### 9.1.2 开跑前快检（准备阶段）

```bash
# 1) 关键环境变量
test -n "$DASHSCOPE_API_KEY" && echo "DASHSCOPE_API_KEY=ok" || echo "DASHSCOPE_API_KEY=missing"

# 2) 关键脚本存在
ls scripts/onboard_example_books.py scripts/run_fnm_llm_repair.py scripts/test_fnm_batch.py

# 3) manifest 中 7 本 slug 是否齐全
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("test_example/example_manifest.json")
data = json.loads(p.read_text(encoding="utf-8"))
slugs = {b.get("slug") for b in data.get("books", [])}
target = {
    "Germany_Madness",
    "Goldstein",
    "Heidegger_en_France",
    "Mad_Act",
    "Napoleon",
    "Neuropsychoanalysis_in_Practice",
    "Neuropsychoanalysis_Introduction",
}
missing = sorted(target - slugs)
print("manifest_ok" if not missing else f"manifest_missing={missing}")
PY
```

### 9.2 标准测试流程（对每一本书执行）

本节就是 7 步标准链路：`onboard → baseline → dry-run → auto-apply → DB 验证 → 收敛对比 → 下游烟测`。
本节一律以 `SLUG` 作为占位符，实际跑时替换为 `Germany_Madness` 等。每一步都必须把输出截图/贴进报告。

#### 9.2.1 入库并跑结构化管线

```bash
python3 scripts/onboard_example_books.py --slug SLUG
python3 scripts/test_fnm_batch.py --slug SLUG
```

跑完后用 `test_example/example_manifest.json` 查到对应 `doc_id`（或从 `local_data/user_data/data/documents/` 找出新目录），后续 `DOC_ID` 均指该值。

#### 9.2.2 记录基线 orphan 状态（LLM 前）

```bash
sqlite3 local_data/user_data/data/documents/DOC_ID/doc.db \
  "SELECT chapter_id, note_kind, status, COUNT(*) \
   FROM fnm_note_links GROUP BY chapter_id, note_kind, status \
   HAVING status IN ('orphan_note','orphan_anchor','ambiguous') \
   ORDER BY chapter_id, note_kind;"
```

把结果全量复制进报告的 **基线表**。重点统计：
- `footnote|orphan_note` 的章节和条数
- `endnote|orphan_note` 的章节和条数
- `footnote|orphan_anchor` / `endnote|orphan_anchor` 的章节和条数

若某一本的 orphan_note 总数为 0：报告里标注 "无可测样本"，直接结束该书。

#### 9.2.3 Step A：dry run（不写库）

先用 dry run 看 LLM 对 top 若干 cluster 的建议：

```bash
python3 scripts/run_fnm_llm_repair.py DOC_ID \
  --cluster-limit 3 --no-auto-apply --skip-rebuild
```

在输出 JSON 里记录：
- `cluster_count`（总 unresolved cluster 数量）
- 每个处理过的 cluster 的 `cluster_id`、`note_system`、`request_mode`、LLM 给出的 `actions` 数量和各 action 的 `action_type` / `confidence` / `fuzzy_score`

如果 `cluster_limit=3` 跑完完全没有 `synthesize_anchor` 建议，加大到 5 或 10 再试一次；如果还是没有，证明该书在 Tier 1a 这层无可合成样本，标记 "no synthesizable clusters" 结束。

#### 9.2.4 Step B：自动应用 + 重建

```bash
python3 scripts/run_fnm_llm_repair.py DOC_ID --cluster-limit 3
```

（默认 auto-apply 开启；重建在 `auto_applied_count > 0` 时自动触发。）

在输出 JSON 里记录：
- `auto_applied_count`
- `auto_applied_breakdown`（按 action_type 分组）
- `rebuild.ok` 是否为 true

> ⚠️ **LLM 有随机性**。若本轮 0 auto-apply 而上一轮 dry run 看到过合成建议，**重跑最多 3 次**再判定失败。

#### 9.2.5 Step C：DB 验证

```bash
sqlite3 local_data/user_data/data/documents/DOC_ID/doc.db \
  "SELECT scope, COUNT(*) FROM fnm_review_overrides_v2 GROUP BY scope;"

sqlite3 local_data/user_data/data/documents/DOC_ID/doc.db \
  "SELECT anchor_id, chapter_id, page_no, char_start, char_end, anchor_kind, source \
   FROM fnm_body_anchors WHERE anchor_id LIKE 'llm-synth-%';"
```

若当前库表 `fnm_body_anchors` 没有 `source` 列（会报 `no such column: source`），改用：

```bash
sqlite3 local_data/user_data/data/documents/DOC_ID/doc.db \
  "SELECT anchor_id, chapter_id, page_no, char_start, char_end, anchor_kind \
   FROM fnm_body_anchors WHERE anchor_id LIKE 'llm-synth-%';"
```

硬性通过条件：
- `fnm_review_overrides_v2` 中 `scope='anchor'` 行数 > 0
- `fnm_body_anchors WHERE anchor_id LIKE 'llm-synth-%'` **非空**
- 每个 llm-synth 锚点都有配对的 `scope='link'` `action='match'` override
- `anchor_kind` 必须和它所属 cluster 的 `note_system` 一致（footnote cluster → `footnote`；endnote cluster → `endnote`）

#### 9.2.6 Step D：对比 orphan 收敛

重跑 9.2.2 的 SQL，写入报告 **收敛表**。目标：
- 合成锚点所在章节的 `orphan_note` 条数应该严格下降 `≥ auto_applied_synthesize_count`
- **不允许**任何其他章节的 orphan 数量变大
- **不允许**出现新的 `ambiguous` 条目

#### 9.2.7 Step E：下游烟测

```bash
python3 scripts/test_fnm_batch.py --slug SLUG
```

检查：
- `structure_state` 是否从 `error/idle` 变成 `ready` 或维持原状（不允许回退）
- 导出 zip 文件是否能生成：`test_example/SLUG/latest.fnm.obsidian.zip`
- zip 里对应章节的 markdown 中合成 anchor 是否转成了 `[^n]` 引用；定义条目是否仍在章节末尾

### 9.3 Footnote vs Endnote 的专项检查

同一本书通常同时存在两种 note_system，必须分别覆盖：

| 维度 | Footnote 场景 | Endnote 场景 |
|---|---|---|
| orphan 形态 | 正文找不到 marker → `footnote\|orphan_note` | 章末找不到对应 anchor → `endnote\|orphan_anchor` 或 `endnote\|orphan_note` |
| request_mode | `note_only_with_body`（带章节正文给 LLM 定位） | `paired` 或 `paired_with_body` |
| 期望 action | 主要是 `synthesize_anchor`（LLM 在正文中 locate 锚点短语） | 可能是 `match_pair`、`mark_ignore`，`synthesize_anchor` 仅在章末锚点丢失时出现 |
| 合成 anchor.anchor_kind | 必须是 `"footnote"` | 必须是 `"endnote"` |
| 回归风险 | 若 `anchor_kind` 回退到硬编码 `"endnote"`，`note_linking._infer_note_kind_from_anchor` 会判 `same_kind=False` → `invalid_link_override` | 正常 |

**每本书在报告里至少要分别给出 footnote / endnote 各一个 cluster 的前后对比**（若该 note_system 在该书中确实存在 orphan）。

### 9.4 标准报告格式（每本书一个 .md）

文件位置：`test_example/SLUG/FNM_LLM_TIER1A_REPORT.md`。

```markdown
# FNM Tier 1a LLM 修补测试报告 — SLUG

- doc_id: ...
- 测试日期: YYYY-MM-DD
- 代码版本 / commit: <git rev-parse HEAD>
- DashScope 模型: qwen-plus（或当次实际使用的）

## 1. 前置检查
- 单测全量通过: yes / no
- 环境变量存在: yes / no
- 入库 + 结构化管线跑通: yes / no，`structure_state` = ...

## 2. 基线 orphan 统计（LLM 前）
| chapter_id | note_kind | status | count |
|---|---|---|---|
| ... | ... | ... | ... |

- footnote orphan_note 总数: N1
- endnote orphan_note 总数: N2
- footnote orphan_anchor 总数: N3
- endnote orphan_anchor 总数: N4

## 3. Step A dry-run 结果
- cluster_count: ...
- 按 note_system 分布: footnote=..., endnote=...
- 被处理的 cluster 列表：
  | cluster_id | note_system | request_mode | actions 数 | synthesize 数 | match_pair 数 | ignore 数 | 最高 confidence |

## 4. Step B 自动应用结果
- auto_applied_count: ...
- breakdown: synthesize=..., match_pair=..., ignore=...
- rebuild.ok: ...
- LLM 重试次数（若有）: ...

## 5. Step C DB 验证
- fnm_review_overrides_v2 按 scope 计数: anchor=..., link=..., llm_suggestion=...
- 合成 anchor 列表：
  | anchor_id | chapter_id | page_no | char_range | anchor_kind | note_system 一致? |
- 配对 match link 列表：
  | link_id | note_item_id | anchor_id | 一致? |

## 6. Step D orphan 收敛
| chapter_id | note_kind | before | after | delta |

- 受影响章节：...
- 未受影响章节是否稳定：yes / no
- 是否出现新 ambiguous：yes / no

## 7. Step E 下游烟测
- `structure_state` after: ...
- zip 是否落盘: yes / no (path)
- 抽样检查的章节号: ...
- 该章节 md 中 `[^n]` 引用是否闭合: yes / no
- 是否有 `{{NOTE_REF:*}}` 残留: yes / no
- 是否有 raw marker 残留: yes / no

## 8. Footnote vs Endnote 专项
### 8.1 Footnote cluster 样本
- cluster_id: ...
- 前: ... orphan_note
- 后: ... orphan_note
- 合成 anchor.anchor_kind: ...（必须 footnote）

### 8.2 Endnote cluster 样本
- cluster_id: ...
- 前: ...
- 后: ...
- 合成 anchor.anchor_kind: ...（必须 endnote）

（若该书不存在某一类别，写 "N/A — 该书无此类 orphan"）

## 9. 异常与待跟进
- 本次测试发现的反常现象
- 建议的 follow-up（比如：某 cluster LLM 三次都没返回 synthesize_anchor）
- 是否触发过已知 bug（例如 `invalid_link_override` consistency 拒绝）

## 10. 结论
- [ ] Tier 1a 链路对本书可用
- [ ] orphan 收敛数量 >= 预期
- [ ] 下游导出无回归
- [ ] 脚注和尾注的 anchor_kind 均正确

**总体判定：PASS / PASS_WITH_NOTES / FAIL**
```

### 9.5 汇总报告格式（7 本合一）

文件位置：`test_example/FNM_LLM_TIER1A_BATCH_REPORT.md`。

```markdown
# Tier 1a LLM 修补 — 7 本批量报告

## 总览表
| slug | doc_id | orphan before (fn/en) | orphan after (fn/en) | auto_applied | 链路判定 |
|---|---|---|---|---|---|
| Germany_Madness | ... | a/b | c/d | ... | PASS |
| Goldstein | ... | ... | ... | ... | ... |
| Heidegger_en_France | ... | ... | ... | ... | ... |
| Mad_Act | ... | ... | ... | ... | ... |
| Napoleon | ... | ... | ... | ... | ... |
| Neuropsychoanalysis_in_Practice | ... | ... | ... | ... | ... |
| Neuropsychoanalysis_Introduction | ... | ... | ... | ... | ... |

## 跨书发现
- 共性问题
- 个别书的非共性问题

## 是否阻塞 Tier 1b 开工
PASS 本数 / 7；若 < 5 建议先修 bug 再上 Tier 1b。

## 链接到各书详细报告
- [Germany_Madness](Germany_Madness/FNM_LLM_TIER1A_REPORT.md)
- ...
```

### 9.6 常见失败模式速查

| 症状 | 可能原因 | 定位入口 |
|---|---|---|
| `fnm_body_anchors` 无 `llm-synth-%` 行，但 `fnm_review_overrides_v2` 有 scope=anchor | pipeline `_group_review_overrides` 丢了 anchor scope | `FNM_RE/app/pipeline.py::_group_review_overrides` 的 `known_scopes` |
| scope="link" match override 被判 `invalid_link_override:consistency` | 合成锚点的 `anchor_kind` 与 note_item `note_kind` 不一致 | `FNM_RE/llm_repair.py` 里 synthesize_anchor auto-apply 的 anchor_payload 里 `anchor_kind` 必须 `= note_system` |
| Step B 0 auto-applied，但 Step A 看过 synthesize 建议 | LLM 随机性 / confidence 未到阈值 / fuzzy_score < 88 / chapter_unmatched_count < 3 | `FNM_RE/llm_repair.py::select_auto_applicable_actions` 的阈值 |
| 所有 cluster 都是 footnote 但被 build_unresolved_clusters 过滤 | 旧版本的硬过滤 `note_system != "endnote"` | `FNM_RE/llm_repair.py::build_unresolved_clusters` |
| 合成 anchor 出现但 ref_freeze 没把它编入 `[^n]` | `source="llm"` 但 `synthetic=True` → ref_freeze 跳过 | `_materialize_anchor_overrides` 里 `synthetic=False` |
| rebuild 后 `structure_state=error` | contract 未闭合（新 match 影响了其他 gate） | `verification.md` 最近一次 `blocking_reasons` |

### 9.7 测试纪律

- 任何手工改数据库行为都必须在报告 §9 "异常与待跟进" 记录，不允许静默修改。
- 不允许 "看起来对就过"。必须满足 9.2.5 ~ 9.2.7 的所有硬性通过条件才能在总表里标 PASS。
- LLM 额度消耗超过预估时停手并告知，不要为了跑完所有 cluster 无限增大 `--cluster-limit`。

### 9.8 串行执行顺序与断点续跑（准备阶段）

推荐串行顺序（固定 7 本）：

1. `Germany_Madness`
2. `Goldstein`
3. `Heidegger_en_France`
4. `Mad_Act`
5. `Napoleon`
6. `Neuropsychoanalysis_in_Practice`
7. `Neuropsychoanalysis_Introduction`

断点续跑规则：

- 单书内：若中断在 Step A/B，先复跑 Step A 再继续；若中断在 Step C/D/E，先重跑 Step B（触发重建）再继续。
- 跨书：只要当前书未产出 `test_example/SLUG/FNM_LLM_TIER1A_REPORT.md` 的最终判定，就不要切下一本。
- 汇总：每完成一本就更新 `test_example/FNM_LLM_TIER1A_BATCH_REPORT.md` 对应行，避免最后一次性补录。
