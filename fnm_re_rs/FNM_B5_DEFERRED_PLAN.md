# B5 遗留项详细执行规划（B5-7 + B5-2余 / B5-1余 / B5-6核心深拆）

> 编写日期：2026-05-30。**本文档只规划，不动手。** 全部结论基于源码实测（标 `file:line`）。
> 隶属 `FNM_B5_REMAINING_PLAN.md` 的「留待单独 PR」清单。
> 总验证主轴：行为不变（重构）→ `cargo test --workspace` 全绿 + clippy 0 + parity 不变。

---

## 0. 总览与执行顺序

| # | 项 | 风险 | 工作量 | 独立 PR | 守护 |
|---|---|---|---|---|---|
| 1 | **B5-7 records flatten** | 高（数据契约） | 中 | 是 | parity + 新增 JSON 快照 |
| 2a | **B5-2 余 重复收敛** | 低–中 | 小 | 可拆多个 | 各调用点 parity |
| 2b | **B5-1 余 弱类型** | 中 | 中 | 可拆多个 | 行为不变 |
| 2c | **B5-6 核心深拆** | **最高**（状态交织） | 大 | 是 | 严格快照 |

**建议顺序**：2a（最低风险、最快赢）→ 2b → 1（B5-7）→ 2c（最后，最难）。
**关键前置事实**（已实测）：
- parity 测试（`fnm-phaseN/tests/biopolitics_phaseN_parity.rs`）：**Phase2 主要用 typed struct 反序列化比对，Phase3/4 用 `.get(key)` Value 比对**——两种方式都**不依赖序列化字符串顺序** → 字段顺序变化不破坏契约（结论对 flatten 成立）。
- 6×Summary / 6×Structure 均 `#[derive(Debug, Clone, Default, Serialize, Deserialize)]`（`records.rs:183/250` 等）→ **flatten 技术可行**。
- 契约边界：`Phase6Structure` 等 → DB persist + fnm-py JSON 暴露给 Python；golden 固化在 `fixtures/biopolitics_phaseN_golden.json`。

---

## 1. B5-7　records.rs Summary/Structure 字段平铺去重〔最高风险，重点〕

### 1.1 现状（实测字段分层）

**6×Summary**（`records.rs` 行 184/386/588/831/1247/1453）呈**累积嵌套**，但有顺序错位：

| 层 | 字段（按出现顺序） | 出现于 |
|---|---|---|
| **L0-toc（前15，完全一致）** | page_partition_summary, heading_review_summary, heading_graph_summary, chapter_source_summary, visual_toc_conflict_count, toc_alignment_summary, toc_semantic_summary, toc_role_summary, container_titles, post_body_titles, back_matter_titles, chapter_title_alignment_ok, chapter_section_alignment_ok, toc_semantic_contract_ok, toc_semantic_blocking_reasons | **P1–P6** |
| **L1-note（5）** | note_region_summary, note_item_summary, chapter_note_mode_summary, chapter_endnote_region_alignment_ok, chapter_endnote_start_page_map | P2–P6 |
| **L2-anchor（3）** | body_anchor_summary, note_link_summary, review_seed_summary | P3–P6 |
| **L3-review（2）** | review_type_counts, override_summary | P4–P6 |
| **L4-unit（4）** | unit_planning_summary, ref_materialization_summary, diagnostic_page_summary, diagnostic_note_summary | P5–P6 |
| **散落** | `review_flags`（P2:21 / P3:24 / P4-6:26，位置不一；**P1 无此字段**）、`visual_toc_endnotes_summary`（**仅 P1/P2 Summary，P3-6 已移除**；records.rs:763 的同名字段属 `StructureStatusRecord`，与 PhaseNSummary 无关）、P3 的 paragraph_footnote/paragraph_endnote/chapter_anchor_alignment_summary、P6 的 export_*_summary | 各异 |

**6×Structure**（行 251/434/646/887/1311/1521）更规整，纯累积：
- **L0（4）**：pages, heading_candidates, chapters, section_heads（P1–P6）
- **L1（3）**：note_regions, note_items, chapter_note_modes（P2–P6）
- **L2（2）**：body_anchors, note_links（P3–P6）
- **L3**：effective_note_links, structure_reviews, status（P4–P6，P3 用 paragraph_*/chapter_anchor_alignments 替代）
- **L4**：translation_units, diagnostic_pages, diagnostic_notes（P5–P6）
- 每个末尾 `summary: PhaseNSummary`（类型不同，不可共用）。

**重复量**：Summary 前15字段 ×6 = 90 行重复声明；Structure 前4 ×6 = 24。合计 16+ 公共字段在多 phase 重复（05 文档原话）。

### 1.2 关键发现（降低风险）

- **字段顺序无关契约**（见 §0）→ 散落字段（review_flags 等）可归入任一 Base，序列化位置变化不破坏 parity。
- **`#[serde(default)]` 普遍存在**：flatten 后 default 属性须随字段迁移到 Base struct 上。
- **HashMap 字段**（chapter_endnote_start_page_map、review_type_counts）可正常 flatten（serde 支持）。

### 1.3 方案（分层 Base flatten）

定义 5 个 Base struct（Summary）+ 4 个（Structure），逐层嵌套 flatten：

```rust
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SummaryTocBase { /* L0 前15字段，含各自 #[serde(default)] */ }

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SummaryNoteBase {
    #[serde(flatten)] pub toc: SummaryTocBase,
    /* L1 note 5字段 */
}
// SummaryAnchorBase flatten SummaryNoteBase + L2 …逐层
```

各 PhaseNSummary：
```rust
pub struct Phase3Summary {
    #[serde(flatten)] pub base: SummaryAnchorBase,   // L0+L1+L2
    /* P3 独有：review_seed/paragraph_*/chapter_anchor_alignment/review_flags */
}
```

**散落字段处理**：`review_flags`、`visual_toc_endnotes_summary` 不进 Base（位置/出现 phase 不规则），保留在各 PhaseNSummary 自身字段（顺序无关，不影响契约）。

Structure 同理抽 `StructureL0Base`（前4）→ `StructureNoteBase` → …

### 1.4 serde flatten 陷阱清单（实现时必须逐条验证）

1. **`#[serde(default)]` 迁移**：原字段的 default 属性移到 Base 字段上；Base 整体不需 default（flatten 总在）。
2. **flatten 与 `deny_unknown_fields` 不兼容**——确认这些 struct **未**用 `deny_unknown_fields`（实测目前没有，但实现时再 grep 确认）。
3. **flatten 嵌套层数**：serde 支持多层 flatten，但**反序列化**多层 flatten + default 有已知边界 case，需快照双向验证（serialize→deserialize→serialize 幂等）。
4. **字段名冲突**：Base 间字段名不能重复（实测无重复，安全）。
5. **`Value` 类型字段**：大量字段是 `serde_json::Value`，flatten 不影响。

### 1.5 守护策略（强制，按顺序）

1. **前置快照**（动手前）：为 6×Summary + 6×Structure 各写一个 `insta::assert_json_snapshot!`，用一个**字段全非空**的构造实例（不能用 `default()`，否则空值掩盖顺序问题）。`INSTA_UPDATE=always` 生成**改动前**基线 `.snap`。
2. **改动后**：重跑快照——因字段顺序可能变，**改用 `assert_json_snapshot!` 配合 `serde_json::Value` 解析后逐 key 比对**的自定义断言（而非裸字符串快照），确认 key 集合 + 值完全一致、仅顺序可能不同。
3. **parity 回归**：`cargo test -p fnm-phase{1..6} --test biopolitics_phaseN_parity` 全绿（真实数据 + 按 key 比对）。
4. **往返幂等**：`from_value(to_value(x)) == x` 测试（防 flatten 反序列化丢字段）。
5. 全量 `cargo test --workspace` + clippy 0。

### 1.6 执行步骤

- [ ] S0 写前置快照测试（6+6 个全非空实例）+ 往返幂等测试，生成基线。
- [ ] S1 抽 `SummaryTocBase`（L0），改 P1–P6 flatten，跑守护。
- [ ] S2 抽 `SummaryNoteBase`（L1）… 逐层，每层独立提交 + 跑守护。
- [ ] S3 Structure 各 Base 同理。
- [ ] S4 全量 + parity + clippy 最终验证。

### 1.7 风险 / 回滚 / 工作量

- **最大风险**：flatten 反序列化在多层 + default 下丢字段或改语义 → §1.5 的往返幂等 + parity 双重守护。任一不过即回退该层。
- **回滚**：每层 Base 独立提交，可单层回退。
- **工作量**：中（结构机械但守护测试要写扎实）。约 1–2 天。**收益仅去重**（90→15 行声明），无功能价值——**性价比中等，确认值得再做**。

---

## 2a. B5-2 余　重复 helper 收敛〔低–中风险，最快赢〕

### 2.1 已定位的重复对（**已逐处 diff 核对**，修正了 05 文档与初版规划的多处错误）

| helper | 实测（逐处核对）| 处理决策 |
|---|---|---|
| `safe_int` | **3 处**：phase3/chapter_contracts.rs:10（`.trim()`）、phase5/render/section_render.rs:52（`.trim()`）、**phase5/convert.rs:188（无 `.trim()`）** | ⚠️ **trim 行为有差异**——合并前先决策：convert 版省 trim 是 bug 还是「入参已 trim」的有意省略；统一后提 `fnm-core` |
| `build_chapter_by_page` | **2 处**：book_note_type/mod.rs:40（入参 `&[ChapterRecord]`）、selection.rs:56 `chapter_by_page`（入参 `&Phase1Structure`）——**diff 确认函数体逻辑逐行相同** | ✅ **真重复**：统一入参为 `&[ChapterRecord]`，selection 调用传 `&structure.chapters`，合并到一处 |
| `looks_like_*` | **4 个函数各 2 版本**：`copyright_front_matter_page` / `course_listing_page` / `title_page` / `prose_after_heading`，均 page_resolve.rs（简化版）vs front_matter.rs（完整版） | ⚠️ 大概率**有意不同**（简化版用于 toc 上下文）→ diff 后交叉注释，**不合并** |
| `compute_body_bounds` | **仅 1 处**（endnote_regions_raw.rs:129）——实测无第 2 处 | ❌ **非重复**，从清单删除（05 文档此项有误）|
| `WHITESPACE_RE` | 7 处 `r"\s+"` | ❌ 过于简单→**跳过**（合并反增跨 crate 耦合）|
| `extract_context` / `extract_json_block` / `candidate_source_score` | — | ✅ 本次已处理 |

> **勘误说明**：① 05 文档说 `compute_body_bounds` phase2×2、`build_chapter_by_page` phase1×3，实测分别为 1 处（非重复）和 2 处。② `safe_int` 实为 3 处且 convert 版无 `.trim()`（合并障碍）。③ `looks_like_*` 四个函数（非仅 title_page）各有 2 版本。

### 2.2 执行步骤（缩减后：实际只剩 `safe_int` 合并 + `build_chapter_by_page` 合并 + `looks_like_*` 注释）

- [ ] **第一步（强制）**：对每对 `diff` 函数体——一致 → 合并；不一致 → 注释差异（参照 `candidate_source_score`）。
- [ ] `safe_int`：**先决策 trim 差异**（convert.rs:188 无 trim）。若判定 3 处应统一行为 → 提 `fnm-core::safe_int`（phase3/phase5 都依赖 core）；若 convert 版有意无 trim → 保留并注释。
- [ ] `build_chapter_by_page`：统一入参后合并（两处逻辑已确认相同）。注意 selection 版是 `pub`、book_note_type 版是私有——合并落点需 `pub`。
- [ ] `looks_like_*`（4 函数）：diff page_resolve 简化版 vs front_matter 完整版，**有意不同则交叉注释、不合并**。
- [ ] `compute_body_bounds`：**删除**（非重复）。
- [ ] `WHITESPACE_RE`：**跳过**。

### 2.3 守护
各调用点的现有单元/parity 测试；合并后跑相关 crate `cargo test`。低风险。

---

## 2b. B5-1 余　弱类型定型〔中风险〕

### 2.1 热点清单（实测 `.get("...")` 密度）

| 热点 | 位置 | `.get` 数 | 适配方式 |
|---|---|---|---|
| prompt 构建 | `fnm-llm-repair/prompt_builder.rs` | 58 | 多为读 cluster/page 字段 → typed view |
| page context | `fnm-llm-repair/page_context.rs` | 29 | typed view |
| override 物化 | `fnm-llm-repair/override_materializer.rs` | 19 | typed view |
| page_translate apply | `fnm-orchestrator/page_translate/apply.rs` | 22 | 中间结果 typed struct |
| （已完成代表）jobs_builder `paragraph_rows` | — | — | ✅ 本次已做 |

### 2.2 方案（两选一，按热点性质）

- **纯内部中间结构**（如已完成的 `paragraph_rows`）→ 直接换 typed struct（零签名影响，最优先）。
- **跨函数/签名传递的 Value**（cluster/action/page）→ 定义 `XxxView<'a>(&'a Value)` accessor wrapper + typed getter 方法（**保持 `.get().unwrap_or()` 的容错语义**，避免 `from_value` 失败改变行为）。**不轻易改函数签名**（波及调用点）。
- ⚠️ **本仓库目前无 accessor wrapper 先例**（`rg "struct \w+View|Accessor"` 为 0）→ 首次引入须先做 1 个最小示例验证模式（编译通过 + getter 默认值逐项对齐原 `.get`），再推广到其他热点。

### 2.3 执行步骤
- [ ] 逐热点：先读该函数全貌，分清「内部中间结构」vs「签名传递 Value」。
- [ ] 内部结构 → typed struct（参照 `ParagraphRow`）。
- [ ] 签名 Value → accessor wrapper（getter 封装 `.get`，容错语义不变）。
- [ ] **不必全量**（05 原则）；优先 llm-repair prompt_builder（密度最高）。

### 2.4 守护
行为不变；逐热点跑所在 crate `cargo test`（含 parity）。注意：accessor 必须逐字段复刻原 `.get(...).and_then(...).unwrap_or(default)` 的默认值，**diff 核对**。

---

## 2c. B5-6 核心阶段深拆〔最高风险，最后做〕

### 2.1 现状（本次已做轻量拆分，核心留待）

- `toc_semantics/mod.rs::build_toc_semantics`：已抽 step 11/12/15；**step 1-10（约 410 行）留待**。
- `ref_freeze/mod.rs::build_frozen_units`：已抽 Phase 2；**Phase 1/3/5/6 留待**。

### 2.2 难点（实测，为何高风险）

- **toc_semantics step 1-10**（实测约 **413 行**，占函数 477 行总长的大部分；其中约 330 行仍 inline）：`rows`（可变贯穿）+ step 7 派生 `body_rows`(借用 rows)、`chapter_level_rows`、`chapter_style`、`force_export_rows`、`misleveled_rows`、`corrected_chapter_rows`、`explicit_chapter_rows`、`page_role_by_no`、`lecture_collection_override` 等——**实测共 28 个中间变量，step 7 独占 15 个（含 8 个 `Vec<&TocRow>` 借用）**，被 step 8-10 网状消费。
- **ref_freeze Phase 1/3**：Phase 1 产 `chapter_by_id`/`anchor_by_id`/`region_by_id` 等**借用型** HashMap（`HashMap<String, &X>` 绑定入参生命周期）+ `matched_links`(`Vec<&NoteLinkRecord>`)，Phase 3 inject loop 用 `get_mut` 修改。实测 **3 个借用型 HashMap + 5 个 owned**；`build_frozen_units` 718 行，已抽 4 个子模块（chapter_index/inject/hash/contract）+ 本次 Phase 2，剩余 inline 部分重构成本高。

### 2.3 方案（状态 struct 承载）

唯一可行路径是定义**状态 struct** 把中间量集中：
```rust
struct TocSemanticsState<'a> {
    rows: Vec<TocRow>,
    chapter_level: i64,
    body_rows_idx: Vec<usize>,   // 用索引替代 &TocRow 借用，规避生命周期
    // …
}
```
**关键设计决策**：用**索引**（`Vec<usize>`）替代借用引用（`Vec<&TocRow>`），否则状态 struct 自借用无法成立。这是主要重构成本。

ref_freeze 同理：Phase 1 索引改为 `HashMap<String, usize>`（存 Vec 下标）而非 `HashMap<String, &X>`。

### 2.4 守护策略（最严格）

1. **前置端到端快照**：用 biopolitics 真实数据（已有 fixtures）跑 build_toc_semantics / build_frozen_units，`insta` 快照完整输出。
2. 每抽一个子阶段，重跑快照 + parity，**逐字节一致**才继续。
3. 借用→索引改写**逐处 diff**，确认语义等价（索引解引用 == 原借用）。

### 2.5 风险 / 工作量

- **最大风险**：借用→索引改写引入下标错位（off-by-one / 排序后索引失效）。缓解：快照守护 + 小步提交。
- **工作量**：大（toc 1-2 天，ref_freeze 1-2 天）。**纯可读性收益**——除非该文件后续要频繁改动，否则**性价比低，可长期搁置**。
- 建议：仅在「需要再动这两个函数的功能」时，**顺带**做对应阶段的深拆，不为深拆而深拆。

---

## 3. 总 DoD

- [ ] 每项独立 PR，commit 粒度细（便于回退）。
- [ ] 行为不变：全量 `cargo test --workspace` + 6 个 parity + clippy 0。
- [ ] B5-7 / B5-6 额外有快照 + 往返幂等守护。
- [ ] 重复收敛「分值/阈值不同的不合并」（§12）。
