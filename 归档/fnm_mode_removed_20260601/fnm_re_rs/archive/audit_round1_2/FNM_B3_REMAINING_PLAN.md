# 批次 3 剩余工作执行计划 — S2/S3 接入 + 占位清理 + 红线守卫测试

> 隶属 `FNM_REMEDIATION_PLAN_03_llm_integration.md`。S1/S4 已完成并接入主流程，本文档**只覆盖 B3 剩余部分**。
> 编写日期：2026-05-30。**全部结论基于源码实际验证**（标注 `file:line`），非凭符号名猜测（CLAUDE.md §9）。
> 红线总纲：LLM 不得成为 `note_kind` 第二决策源（CLAUDE.md §8 / §12）。

---

## 0. 现状快照（已逐项验证）

| 子系统 | 状态 | 证据（file:line） |
|---|---|---|
| S1 phase1 书型校验 | ✅ 已接入 | `verify_book_type_with_llm` 在 `fnm-phase1/src/toc_structure.rs:418` 有生产调用 |
| S4 phase3 bare_digit anchor | ✅ 已接入 | `body_anchors/mod.rs:200-230` `block_on(verify_bare_digit_anchors_with_llm)` |
| **S2 visual_anchor_recovery** | ⚠️ 函数就绪，未接入 | `run_visual_anchor_recovery`（`visual_anchor_recovery/mod.rs:134`）仅被 `#[test]` 调用 |
| **S3 bare_digit verify** | ⚠️ 函数就绪，未接入 | `verify_bare_digit_candidates`（`llm_bare_digit_verify/mod.rs:19`）仅被 `#[test]` 调用 |
| ready 占位标志 | ⚠️ 未清理 | `fnm-phase2/src/lib.rs:135-136`：`llm_bare_digit_verify_ready` / `visual_anchor_recovery_ready` |

**剩余四件事**：① S2 接入　② S3 决策落地　③ ready 占位清理　④ 红线守卫测试。

---

## 1. 架构地基（S2 回流链路已坐实，非臆想）

写本计划前已验证回流通道真实存在：

1. **override → 重建 phase3 机制已存在**：`mainline.rs:140-168`。
   LLM repair 把 override 写进 DB（`fnm_review_overrides`）→ 若 `auto_applied_count > 0` 则 `list_fnm_review_overrides_v2` → 塞入 `config.review_overrides` → 重跑 `run_phase3` → 重新持久化。**S2 照搬此模式。**
2. **override 通道支持「新增 anchor」**：`note_linking/anchor_overrides.rs:284` 有 `"action": "create"`，:243 读 `synthetic` 字段。visual recovery 产出的正是 synthetic/recovered anchor。
3. **phase3 消费 override 入口**：`note_linking/mod.rs:100-104` `group_review_overrides` → anchor 组交 `anchor_overrides.rs` 处理；新 anchor 进入后 note_links 在重建时自动重链（`note_linking/mod.rs:152` `build_body_anchors` → `enhanced_anchors` → note_links）。

→ **S2 回流路径**：`run_visual_anchor_recovery` → `Vec<BodyAnchorRecord>` → 转 anchor `create` override → 写 DB → 重建 phase3 → 自动重链。

---

## 2. S2 接入 — orchestrator post-phase3 视觉锚点恢复

### 2.1 新增 gap 构建（核心工程量）

`run_visual_anchor_recovery` 要的是 `ChapterAnchorGap`（`materialize.rs:23`）：
```rust
pub struct ChapterAnchorGap {
    pub chapter_id: String,
    pub missing_markers: HashSet<i64>,
    pub body_page_range: (i64, i64),
}
```
现成的 `detect_chapter_marker_gaps`（`gap_detection.rs:17`）产的是逐 marker 的 `GapCandidate`（`marker: String`），**粒度不符**。需新增聚合函数（建议放 `fnm-phase2/src/visual_anchor_recovery/gap_detection.rs`）：

```rust
pub fn build_chapter_anchor_gaps(
    chapters: &[ChapterRecord],
    note_items: &[NoteItemRecord],
    body_anchors: &[BodyAnchorRecord],
) -> Vec<ChapterAnchorGap>
```
- **expected**：复用 `chapter_marker_sets::build_chapter_note_items_set(note_items)`，得每章 expected marker 数字集。
- **found**：`body_anchors` 按 `chapter_id` 分组，`normalized_marker` 解析为 `i64`。
- **missing** = expected − found（i64 集合）。
- **body_page_range** = `(ChapterRecord.start_page, end_page)`（`records.rs:164-165`）。
- 只保留 `missing` 非空的章。

### 2.2 接入点（两条路径）

**DB 路径（`mainline.rs`，主路径）**：紧接 Phase 3.5 LLM repair（:130-138）之后插入 S2 步骤，并与既有重建分支（:142-168）合并触发：
```text
if !config.skip_llm_verify && pdf_path 非空:
    gaps = build_chapter_anchor_gaps(&phase1.chapters, &phase2.note_items, &phase3.body_anchors)
    page_by_no = raw_pages 按 book_page 建索引
    for gap in gaps:
        (anchors, diag) = block_on(run_visual_anchor_recovery(&gap, &page_by_no, pdf_path))
        for a in anchors:
            写 anchor create override 到 DB（action="create", synthetic=true, 带 chapter_id/page_no/marker/char 区间）
    若本步产生 override → 纳入「重建 phase3」触发条件（复用 :142-168 逻辑）
```

**in-memory 路径（`pipeline.rs`）**：在 `run_phase3`（:57）后加同逻辑；无 DB，override 直接塞 `config.review_overrides` 后重跑 `run_phase3`。

### 2.3 async 桥接
`mainline` 已是 `block_on` 模式（`run_llm_repair_sync`）。S2 用 `tokio` current-thread runtime `block_on`，与 S4 / llm-repair 一致。

### 2.4 红线（D2）
`run_visual_anchor_recovery` 产物只有 `BodyAnchorRecord`，**天然不碰 `note_kind`**。落点为 anchor `create` override，符合 §8/§12。

---

## 3. S3 决策 — 推荐「不单独接入」（决策点 1，需拍板）

### 3.1 冗余分析
- **S4（已接入）**：phase3 内 `build_body_anchors` 时，对 `positive_gate_bare_digit`（`context_guard.rs`）产出的**低置信候选**做 LLM gate，通过才进 anchors。**bare_digit 的 LLM 裁决已在此唯一发生。**
- **S3（`verify_bare_digit_candidates`）**：对**已成为 anchor 的 `source=="bare_digit"`** 做复核。

进入最终 anchors 的 bare_digit = positive_gate 直接通过（高置信） + S4 验证通过。S3 再验一遍 = ① 重复烧 vision API；② 制造 bare_digit 的**第二 LLM 决策源**，违反 §12「分类源头唯一」。

### 3.2 推荐：方案 A（不接入）
- 不接主流程；保留 `verify_bare_digit_candidates` 为库函数 + 现有单测（与 S4 共享 `llm_client`，有复用价值）。
- 清理 `llm_bare_digit_verify_ready` 占位标志（见 §4）。
- 在 `llm_bare_digit_verify/mod.rs` 顶注释标明「bare_digit LLM 裁决唯一发生在 phase3（S4）；本模块为备用库函数，未接主流程」。

### 3.3 备选：方案 B（接入为抽检，不推荐）
若确需对高置信 bare_digit 也抽检：post-phase3 调 `verify_bare_digit_candidates`，但须只对 S4 未覆盖者（`source=="markdown:bare_digit"` 且 positive_gate 直通）抽检以避免重复；rejected 经 anchor override（`action=ignore`）回流。工作量≈S2，收益存疑。

> **决策点 1**：S3 取方案 A（推荐）还是 B？

---

## 4. ready 占位标志清理

`fnm-phase2/src/lib.rs:134-136`：
```rust
"llm_vision_configured": llm_ready,          // 保留：纯配置探测，无误导
"llm_bare_digit_verify_ready": llm_ready,    // S3：方案 A → 删除
"visual_anchor_recovery_ready": llm_ready,   // S2：接入后 → 改为真实 diag
```
- **S2**：`visual_anchor_recovery_ready` 删除，替换为真实诊断（恢复 anchor 数 / skipped 原因，由 `run_visual_anchor_recovery` 第二返回值 `Value` 提供）。
- **S3 方案 A**：`llm_bare_digit_verify_ready` 删除。
- 一并核查 S2/S3 相关 `_pdf_path`、`_ready` 等占位是否还有残留（`rg "_ready\b|_pdf_path" fnm-phase2 fnm-phase3`）。

---

## 5. 红线守卫测试（B3 必做项）

构造「LLM 与 rule-based 冲突」场景，断言决策源唯一。mock 用 stub HTTP（避免真实 API）：

1. **S1 守卫**：mock LLM 返回与 rule 相反的 `book_type` → 断言 `structure.chapters/book_type` 不变，仅 `diagnostics` 记录分歧。
2. **S2 守卫**：mock visual recovery 返回 anchor → 断言只新增 synthetic anchor、**不改任何 `note_item.note_kind`**。
3. **S4 守卫**：mock LLM accept/reject bare_digit → 断言只影响 anchor 去留/置信度、`note_kind` 不变。
4. **graceful skip**：`skip=false` 但无 API key → pipeline 正常完成、diag 标 `skipped`、产物与 `skip=true` **逐字节一致**。

---

## 6. 执行顺序 / DoD / 风险

**顺序**：S2 gap 构建 → S2 in-memory(`pipeline.rs`) 接入 → S2 DB(`mainline.rs`) 接入 → S3 决策落地 → ready 清理 → 守卫测试。

**DoD**：
- [ ] S2：`skip=false` + 有 key + 有 PDF → 恢复 anchor 经 override 注入、note_links 重链；`skip=true` 零变化。
- [ ] S3 按决策落地（方案 A：清理 + 注释；方案 B：接入 + 抽检守卫）。
- [ ] 所有 `*_ready` 占位删除或落地为真实 diag。
- [ ] 4 类守卫测试通过。
- [ ] `cargo clippy` 0 warning；多书实批回归（含导出）无差异。

**风险**：
- **重建幂等性**：S2 override 注入后重跑 phase3，须保证恢复的 anchor 不被再次判为 gap（避免死循环）。缓解：`build_chapter_anchor_gaps` 把 override 注入的 anchor 计入 `found`。
- **两路径一致性**：`pipeline.rs`(in-memory) 与 `mainline.rs`(DB) 都要测。
- **vision API 成本**：仅 `skip=false` 且存在 gap 时触发，默认（`skip=true`）关闭。
- 回滚：每个改动独立提交，可单独回退。

> **决策点 2**：S2 是否两条路径都接（in-memory + DB），还是只接 DB 主路径？（in-memory 多用于测试/单文档）

---

## 执行结果（2026-05-30，commit 5c8aa20）

| 项 | 状态 | 实现 |
|---|---|---|
| S2 视觉锚点恢复 | ✅ 接入 | 新建 `visual_recovery.rs`（`build_chapter_anchor_gaps` + `run_post_phase3_visual_recovery` + anchor `create` override 回流）；`mainline.rs` Phase 3.6 步骤 + 扁平化重建条件（DB 主路径）|
| S3 bare_digit verify | ✅ 不接入（决策点 1 = 方案 A）| `llm_bare_digit_verify/mod.rs` 加「未接入」注释；保留库函数 + 单测 |
| ready 占位清理 | ✅ | 删除 `llm_bare_digit_verify_ready` / `visual_anchor_recovery_ready`（确认无下游消费）|
| 红线守卫测试 | ✅ | +6 测试（含 `redline_override_never_touches_note_kind`）|

**决策点 2 落地**：仅接 DB 主路径（mainline）。in-memory `pipeline.rs` 是 MVP 纯内存模式（无 LLM repair 回环），S2 不接，与现状一致。

**验证**：B3 三 crate 213 passed / 0 failed；clippy 0 warning；mainline 集成测试向后兼容。
