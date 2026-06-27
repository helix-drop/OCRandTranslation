# 批次 4 详细计划 — 逻辑 / 契约一致性

> 隶属 `FNM_REMEDIATION_PLAN_00_MASTER.md` 批次 B4。前置：批次 1（数据/panic）完成。
> 性质：小重构 + 契约统一，中等风险。分支 `fix/b4-logic`。
> 验证主轴：每条补行为级单测；`cargo test/clippy` 守门；涉及 DB 的与批次 1 的事务/FK 修复协同。

---

## B4-1　DB enum 读回容错策略不一致
**审计**：`FNM_CORE_AUDIT2.md` C-5。
**现状**：`fnm-core/src/db/repository.rs` 中 `note_kind`/`page_role`/`status`/`resolver`/`boundary_state` 用 `from_str(...).unwrap_or(默认)` **静默兜底**（有 `invalid_note_kind_reads_back_as_unknown` 等测试覆盖，是有意容错）；而 `region_scope`/`region_source` 用 `map_err(invalid_db_value)?` **fail-fast**。同一类「DB enum 读回非法值」两种策略，且无注释解释。
**改法**：二选一并全文统一 +注释：
- 推荐：与 `db/schema.rs`「缺列读回失败」哲学一致 → **全部 fail-fast**（非法 enum 返回 `invalid_db_value`），强制重生成而非掩盖脏数据；同时配合批次 1 的 FK/事务，减少脏数据来源。
- 或：全部容错 + 统一加 `tracing::warn!("invalid {enum} '{raw}' → 降级 {默认}")` 降级日志。
**注意**：若改 fail-fast，须同步更新 `invalid_note_kind_reads_back_as_unknown` 等测试的期望。
**验证**：构造 DB 中非法 enum 值，断言统一行为（全 Err 或全降级+日志）。

## B4-2　structure_reviews 的 review_id 合成碰撞
**审计**：`FNM_CORE_AUDIT2.md` C-3。
**现状**：`replace_fnm_structure_reviews` 写入丢弃 `review_id`；`list_fnm_structure_reviews`（repository.rs:1222）用 `format!("review-{type}-{chapter}-{page_start}-{page_end}-na")` 合成，**尾部写死 `"na"`** → 同 `(type,chapter,page_start,page_end)` 的多条 review 得到**相同 review_id**，下游按 id 去重会丢条目。
**改法**：二选一：
- 持久化 `review_id` 列（schema 加列 + INSERT/SELECT 带上）；
- 或合成键纳入区分字段（payload hash / ordinal），去掉占位 `"na"`。
**验证**：插入两条同坐标不同内容的 review，读回断言 `review_id` 不碰撞、`reviews.len()==2`。

## B4-3　orchestrator retry `visible_idx` 与类型化版不一致
**审计**：旧审计 P0（`FNM_AUDIT2_SUMMARY.md` §3.3）。
**现状**：`fnm-orchestrator/src/page_translate/retry.rs:27` `collect_unit_failed_locations_value`（Value 版）在 `consumed_by_prev` 分支 `continue` 前**仍 `visible_idx += 1`**；而类型化版 `collect_failed_locations`（116）在 `consumed_by_prev` 时 `continue` **不递增**（122-124）。两实现的 `para_idx` 语义错位。
**改法**：对齐两者——确认正确语义（visible 段落索引应**跳过** consumed_by_prev 还是计数），统一二者。结合 apply.rs `apply_single_paragraph_entry` 的 `visible_idx` 递增时机一并核对。
**验证**：构造含 `consumed_by_prev` 段的 unit，断言 Value 版与类型化版返回的 `para_idx` 一致。

## B4-4　orchestrator load `note_links` / `effective_note_links` 语义混淆
**审计**：旧审计 P0。
**现状**：`fnm-orchestrator/src/load.rs:125-126` 把 `note_links` 同时赋给 `note_links` 和 `effective_note_links`（`effective` 应是 override 生效后的链接）。
**改法**：确认 DB 是否区分两者（phase3 持久化的是 effective_links）；若 DB 只存一份，注释说明「load 阶段二者等同（override 已在 phase3 物化）」；若应区分，分别加载。
**验证**：对照 phase3 persist 的 note_links 语义，断言 load 回的 effective 与 phase3 出口一致。

## B4-5　ref_rewriter `local_endnote_ref_number` while 死循环分支
**审计**：`FNM_CORE_AUDIT2.md` C-4。
**位置**：`fnm-core/src/ref_rewriter.rs:176-179`。
```rust
// before:
// let mut next_num = local_ref_numbers.values().max().copied().unwrap_or(0) + 1;
// while local_ref_numbers.values().any(|&v| v == next_num) { next_num += 1; }  // 恒不进入
// after:
let next_num = local_ref_numbers.values().max().copied().unwrap_or(0) + 1;
```
**验证**：现有 ref_rewriter 测试不变（行为等价）。

## B4-6　ref-rewriter `find`+`captures` 重复匹配 + 正则源码控制流
**审计**：`FNM_CORE_AUDIT2.md` C-12。
**位置**：`fnm-core/src/refs.rs`：`cleanup_nested_note_refs`（59-69，SPLIT 分支 find 后又 captures×2）；`extract_note_refs`（226-250，`find_iter` 后再 `captures(m.as_str())`，并用 `pattern.as_str().contains("\\[\\^")` 判断模式）。
**改法**：改 `captures_iter` 一次拿 match+groups；用结构化标志（如给每个 pattern 附 `kind` 字段的 struct）替代「正则源码字符串包含」判断。
**验证**：现有 refs 测试不变；新增一个 `[^en-...]` vs `[^fn-...]` 区分用例。

## B4-7　phase1 `is_sentence_like_heading` 两实现阈值不一致
**审计**：旧审计（`FNM_AUDIT2_SUMMARY.md` §3.3）。
**现状**：`fnm-phase1/src/chapter_skeleton/heading_candidates/normalize.rs` 的 `is_sentence_like_heading` 用 `words.len() < 8`；`fallback.rs` 的 `is_sentence_like_heading` 用 `words.len() >= 6`（+逗号/冒号）。两套阈值。
**改法**：确认应否统一——若是同一语义，抽到一处共享；若有意不同，注释说明差异理由。
**验证**：边界词数（6/7/8 词）用例断言符合预期。

## B4-8　注释 / 实现不符订正
**审计**：`FNM_PHASE1_AUDIT2.md` 等。
- `fnm-phase1/src/chapter_skeleton/heading_candidates/mod.rs:374` 注释称 pdf_font_band「当前 stub」实为完整实现 → 删/改注释。
- `fnm-phase1/src/chapter_skeleton/toc_semantics/monotonic.rs:5` 注释「严格递增」实现是 `<=`（非严格）→ 对齐注释或改 `<`。
- `fnm-core/src/records.rs:25-26` 头注「1361 行」实 1657 行 → 更新或删行数。
- `fnm-orchestrator/src/page_translate/jobs.rs` `trim_context`/`tail_context` 的 `len()`(字节) vs `chars()`(字符) 混用（批次1 H-4 未单列处，此处随手统一为 char 计数）。
**验证**：纯注释/局部，build+clippy 通过即可。

---

## 完成标准（DoD）
- [ ] 每条有行为级单测或明确的「等价/对齐」论证。
- [ ] enum 策略（B4-1）全 crate 统一并注释；review_id（B4-2）不碰撞。
- [ ] `cargo test/clippy`（0 warning）通过；多书实批回归无契约回归。

## 风险与回滚
- B4-1/B4-2 涉及 DB 行为与既有测试期望，改 fail-fast 需同步更新测试，注意不要把「有意容错」误判为 bug——以 `db/schema.rs` 哲学为准绳。
- B4-3/B4-4 是 orchestrator 翻译进度/失败定位语义，改前确认正确语义（对照 Python），避免引入新错位。
- 逐条独立提交，可单独回退。
