# FNM Rust 代码库修复清单（综合两轮审计）

> 来源：本轮 10 份 `FNM_*_AUDIT2.md` + 总览 `FNM_AUDIT2_SUMMARY.md` + 现有 `audit/*.md`（旧审计 19 P0/45 P1/80 P2/59 P3）。
> 范围：**仅程序逻辑 / Rust 风格 / 死代码**，不含业务逻辑。
> 状态：**纯清单，未动任何代码**（交接他人执行）。每条含：位置 · 根因 · 修复 · 验证 · 来源。
> 来源标记：`[双]`=两轮一致，`[新]`=本轮独有，`[旧]`=旧审计独有（本轮已核实属实）。
> 日期：2026-05-29

---

## 0. 执行顺序总纲

| 批次 | 主题 | 件数 | 风险 | 前置 |
|---|---|---|---|---|
| **B1** | 数据正确性 / panic | 11 | 多为 1–5 行 | 先做，独立 |
| **B2** | 死代码清理（明确） | 8 类 | 删除，零行为变更 | 任意时 |
| **B3** | 未接入功能定性与去留 | 6 项 | 需产品决策 | 见 §3 |
| **B4** | 逻辑/契约不一致 | ~10 | 小重构 | B1 后 |
| **B5** | 质量：重复/弱类型/日志 | 跨 crate | 大重构 | 最后 |

**验证基线（每批后跑）**：`cargo test --workspace` + `cargo clippy --workspace --all-targets`（须保持 0 warning）+ 关键 crate 的 parity/contract 测试。

---

## 1. B1 — 数据正确性 / panic（立即）

### B1-1 `[新]` page_segments 恒空 → 按页翻译正文丢失（跨 4 crate，最高优先级）
- **位置**：根因 [phase4 ref_freeze/mod.rs:489](fnm-phase4/src/ref_freeze/mod.rs)；受害 [orchestrator page_translate/jobs.rs:9-25](fnm-orchestrator/src/page_translate/jobs.rs)、jobs_builder.rs:18、apply.rs:28、retry.rs:16。
- **根因**：phase4 把 chunk 算出的 `page_segments` 仅用于取 `page_nos`，`FrozenUnit{ page_segments: Vec::new() }`（注释「JSON → 暂不反序列化」）；下游 phase5 convert 透传空、DB 存 `"[]"`、orchestrator 翻译 job 构建只读 `page_segments.paragraphs` **无 source_text fallback**。经 fnm-py `build_fnm_body_unit_jobs_json`/`prepare_page_translate_jobs_json` 暴露给 Python，是真实按页翻译入口。pipeline 测试（phase1-6 不含翻译）覆盖盲区。
- **修复（二选一，建议都做）**：① phase4 把 chunk 的 page_segments 反序列化为 `Vec<UnitPageSegmentRecord>` 填入 `FrozenUnit.page_segments`；② orchestrator `frozen_body_text_for_page` 在 page_segments 空时 fallback 到 `unit.source_text`（与 phase5 `resolve_body_unit_text` 一致）。
- **验证**：跑一本书完整 pipeline → 断言 DB `fnm_translation_units.page_segments_json != "[]"`；新增 page-translate 端到端 fixture 测试，断言正文段 job 非空、`build_fnm_body_unit_jobs` 返回 `len>0`。

### B1-2 `[双]` DB 所有 `replace_*` 无事务
- **位置**：[fnm-core db/repository.rs](fnm-core/src/db/repository.rs) `write_phase1_tables`/`replace_fnm_phase2/3/5/6_products`/`replace_fnm_translation_units`/`replace_fnm_structure_reviews`。
- **根因**：DELETE 多表 + 循环 INSERT 无事务；中途失败 → 旧数据已删、新数据半写。仅 `batch_save_fnm_review_overrides_v2` 用了 `conn.transaction()`。
- **修复**：每个 `replace_*` 用 `let tx = conn.transaction()?; … tx.commit()?;` 包裹。
- **验证**：注入一个 INSERT 失败（如违反约束）的单测，断言 DELETE 被回滚（旧行仍在）。

### B1-3 `[新]` 连接池 foreign_keys 仅迁移连接生效
- **位置**：[fnm-core db/pool.rs:22](fnm-core/src/db/pool.rs)。
- **根因**：`PRAGMA foreign_keys=ON` 是 per-connection，只设在迁移用的首连接；池中其余连接默认 OFF → FK 约束实质失效（可插孤儿行）。fnm-py 每调用新建池放大暴露。
- **修复**：`SqliteConnectionManager::file(db_path).with_init(|c| c.execute_batch("PRAGMA foreign_keys=ON;"))`；WAL 可留在迁移连接设一次。
- **验证**：从池取第 2+ 个连接，`PRAGMA foreign_keys` 应返回 1；插孤儿行应被拒。

### B1-4 `[旧]` phase4 运算符优先级越界 panic
- **位置**：[phase4 text/markdown_parse.rs:911](fnm-phase4/src/text/markdown_parse.rs)（本轮初读漏此行，已核实）。
- **根因**：`!cond && A || result[0]` 中 `&&`/`||` 优先级使 `result` 空时仍求值 `result[0]` → 越界 panic。
- **修复**：显式括号 `(!cond && A) || (…)`，并在访问 `result[0]` 前判空。
- **验证**：构造触发该分支且 `result` 为空的输入单测，断言不 panic。

### B1-5 `[旧]` phase6 `chars().rev().take(120)` 产出倒序字符串
- **位置**：[phase6 export_audit/file_audit/mod.rs:320](fnm-phase6/src/export_audit/file_audit/mod.rs)。
- **根因**：取尾部 N 字符用 `chars().rev().take(120)` 后未再 `rev()`，结果字符倒序。
- **修复**：`let n=s.chars().count(); s.chars().skip(n.saturating_sub(120)).collect()`。
- **验证**：单测断言尾部截取保持正序。

### B1-6 `[双]` `page_index as u16` 截断
- **位置**：[fnm-core vision/pdfium.rs:37,73,103](fnm-core/src/vision/pdfium.rs)、[phase1 chapter_skeleton/pdf_font.rs:65](fnm-phase1/src/chapter_skeleton/pdf_font.rs)。
- **根因**：`i64 as u16` 负值/>65535 回绕 → 访问错误页。
- **修复**：`u16::try_from(page_index).map_err(…)?`。
- **验证**：传 `-1`/`70000` 应返回错误而非错页。

### B1-7 `[双]` phase1 字节切片多字节标题 panic
- **位置**：[phase1 toc_structure.rs:303](fnm-phase1/src/toc_structure.rs) `&tk[..tk.len().min(20)]`。
- **根因**：`chapter_title_match_key` 保留 `à-ÿ`（2 字节 UTF-8），第 20 字节可能切在字符中间 → panic。同 crate title_utils.rs:283 已正确用 `chars().take(24)`。
- **修复**：`tk.chars().take(20).collect::<String>()`。
- **验证**：法语标题 fixture 断言不 panic。

### B1-8 `[双]` phase1 pdf_font_band `partial_cmp().unwrap()` NaN panic
- **位置**：[phase1 chapter_skeleton/heading_candidates/pdf_font_band.rs:256,262](fnm-phase1/src/chapter_skeleton/heading_candidates/pdf_font_band.rs)。
- **根因**：`safe_float` 对 `"NaN"` 返回 `Some(NaN)`，排序 `partial_cmp().unwrap()` 遇 NaN→None→panic。
- **修复**：`.unwrap_or(std::cmp::Ordering::Equal)`。
- **验证**：含 NaN 坐标的 PDF item 排序不 panic。

### B1-9 `[旧]` phase3 Unicode 上标 byte_end 越界
- **位置**：[phase3 endnote_links.rs:434-436](fnm-phase3/src/endnote_links.rs) `byte_start + unicode_pat.len()`。
- **根因**：byte_end 由 `byte_start + pat.len()` 推算，与实际匹配字节边界不一定一致，切片可能越界/非边界。
- **修复**：用匹配的实际 char 边界换算 byte_end，或 `get(..).is_some()` 守卫后再切。
- **验证**：多位上标 marker fixture 断言不 panic、偏移正确。

### B1-10 `[旧]` phase4 `(-char_a).cmp(...)` i64::MIN 溢出
- **位置**：[phase4 ref_freeze/mod.rs:121](fnm-phase4/src/ref_freeze/mod.rs) 排序键 `(-char_a)`。
- **根因**：`char_start = i64::MIN` 时 `-char_a` 溢出（debug panic / release 回绕）。char_start 理论非负，属防御缺口。
- **修复**：用 `std::cmp::Reverse(char_a)` 替代 `-char_a`。
- **验证**：clippy `neg_overflow` 类 + 极值单测。

### B1-11 `[旧]` phase2 哨兵值 / 空数组守卫 / 静默 Null
- [phase2 endnote_project.rs:89](fnm-phase2/src/chapter_split/endnote_project.rs) 哨兵 `1000000` 代替 `Option`（**注意**：该文件 0 引用，见 §3-B5，修 bug 前先定去留）；
- [phase2 endnote_chapter_explorer/boundary_fallback.rs:407](fnm-phase2/src/endnote_chapter_explorer/boundary_fallback.rs) 空数组无守卫 → `first().unwrap()` 风险；
- [phase2 chapter_split/mod.rs:216](fnm-phase2/src/chapter_split/mod.rs) `serde_json::to_value(p).unwrap_or_default()` 序列化失败静默 Null（+ 同处 RawPage→Value 浪费）。
- **修复**：哨兵→Option；空数组前置守卫；序列化失败记日志或传错误。
- **验证**：对应边界单测。

---

## 2. B2 — 死代码清理（明确，零行为变更）

> 以下均经调用关系核实为**无效计算 / 无引用**，可直接删除（删除后须 `cargo build` + clippy 通过）。

| ID | 位置 | 内容 | 来源 |
|---|---|---|---|
| B2-1 | [phase1 page_partition/mod.rs:153](fnm-phase1/src/page_partition/mod.rs) | `let _synthetic = build_synthetic_page_by_no(...)` —— 含整个 `build_synthetic_page_by_no` 函数（~40 行白算后丢弃） | 双 |
| B2-2 | [phase1 section_heads.rs:75](fnm-phase1/src/section_heads.rs) | `let _chapter_title_key_map = chapter_title_keys(...)` 丢弃 | 双 |
| B2-3 | [phase1 toc_semantics/mod.rs:171,480](fnm-phase1/src/chapter_skeleton/toc_semantics/mod.rs) | `_missing` / `_page_row_by_no` 丢弃 | 双 |
| B2-4 | [phase1 title_utils.rs:102,149](fnm-phase1/src/chapter_skeleton/toc_semantics/title_utils.rs)、[heading_graph/title_key.rs:11](fnm-phase1/src/heading_graph/title_key.rs) | 死 regex `_CHAPTER_KEYWORD_RE`/`_YEAR_RANGE_RE`/`_TRAILING_NOTE_MARKER_RE` | 双 |
| B2-5 | [phase1 fallback.rs:85,222,665](fnm-phase1/src/chapter_skeleton/fallback.rs) | 3× `#[allow(dead_code)]`：`SectionRow`/`ClassifiedSection` 未读字段 + `merge_section_heads` 无调用者 | 双 |
| B2-6 | [phase3 paragraph_footnotes.rs:195](fnm-phase3/src/paragraph_footnotes.rs) | `let _anchor_matched_count = ...` 丢弃 | 双 |
| B2-7 | [orchestrator apply.rs:17](fnm-orchestrator/src/page_translate/apply.rs) | `let _section_title = ...` 丢弃 | 双 |
| B2-8 | [orchestrator post_translate.rs:155-160](fnm-orchestrator/src/post_translate.rs) | 空操作 `if { if let Some(last){ let _ = last; } }` 什么都不做 | 新 |

另：phase2 `note_kind_resolver` 的 `explicit_markers` 死字段、phase2 matching.rs 3× `#[allow(dead_code)]` 未读字段、phase1 多个 `pub` 无项目内调用者函数（`alignment::align_toc_to_chapters`/`container_detection::*`/`monotonic::reorder_chapters_monotonic`）—— 确认无外部消费后清理。

---

## 3. B3 — 未接入功能：逐个定性与去留（核心，需决策）

> 用户问：「该接没接，还是死代码？」结论基于 orchestrator/py 实际调用关系（已 grep 核实）。

### 已接入（澄清，非死代码，**保留**）
- **fnm-llm-repair 整 crate** ✅：`run_llm_repair` 被 [mainline.rs:134](fnm-orchestrator/src/mainline.rs)（phase3.5）+ [post_translate.rs:117](fnm-orchestrator/src/post_translate.rs) + [fnm-py lib.rs:1121](fnm-py/src/lib.rs) 调用。`run_pipeline` 纯内存版不含它是**设计**（DB-driven + caller 显式调用）。

### 待产品决策（Python 有、Rust 有意推迟的「LLM 验证增强层」——非普通死代码，有明确接入意图 G5）
这一层共 ~3000 行，主入口对 `skip_llm_verify=false` 一律 `bail!`（从任何入口都无法启用）：

| 模块 | 行数 | 现状 | 依据 |
|---|---|---|---|
| **B3-1** phase1 `llm_book_type_verify` + `book_note_type` | ~1660 | 主入口 `skip_llm_verify=true` 跳过；`=false` → [toc_structure.rs:101](fnm-phase1/src/toc_structure.rs) `bail!` | 注释标「保留给 LLM book-type verify 用作 prior（G5 待办）」 |
| **B3-2** phase2 `visual_anchor_recovery` | ~1360 | lib 仅设 `visual_anchor_recovery_ready` 标志，0 主流程调用 | 完整 port Python 但未接 |
| **B3-3** phase2 `llm_bare_digit_verify` | ~355 | lib 仅设 `*_ready` 标志，0 调用 | 同上 |
| **B3-4** phase3 bare_digit verifier | — | `context_guard::positive_gate_bare_digit` 的 `llm_candidates` 收集后**丢弃**（无 verifier 注入），`skip_llm_verify` 硬编码 true | [note_linking/mod.rs:150](fnm-phase3/src/note_linking/mod.rs) `_pdf_path` 占位 |

**定性结论**：**既非已接入，也非普通死代码**——是有明确路线图意图（G5）的「功能占位」。**去留是产品决策，不能由审计擅自定**：
- **若决定启用 LLM 验证**（提升书型/锚点/bare_digit 准确率）→ **必须接入**：为各 phase 主入口接 vision client（参照 llm-repair 的 `ResolvedModelSpec` + `HTTP_CLIENT` + async/`block_on` 模式），把 `bail!` 改为实际调用，并把 phase3 `llm_candidates` 接到 verifier。**工作量大（重大功能开发）**。
- **若决定 Rust 端不做 LLM 验证**（依赖现有 rule-based + 弱信号守卫已足够，或 LLM 验证留在 Python 端）→ **删除这 ~3000 行 + 相关 `*_ready` 标志 + bail 分支**，消除「pub 规避 clippy 的伪活代码」。
- **交接建议**：先与项目 owner 确认 G5 路线图状态，再二选一。无论哪种，当前「port 了但永久 bail」的中间态应终结。

### 疑似死代码（需对照 Python 主流程确认，**倾向清理**）
- **B3-5** phase2 `chapter_split/{endnote_project, overrides_apply, synth_markers}`：`compute_endnote_projections`/`compute_fallback_assignments`/`apply_note_item_overrides`/`compute_synthetic_markers` **0 非测试引用**，且**不属 LLM 层**。
  - **判断**：需对照 Python `chapter_split` 主流程是否调用等价逻辑：
    - 若 Python 在 phase2 做 endnote 投影 / note-item override 应用 / 合成 marker，而 Rust `build_chapter_layers` 未接 → **功能缺口（该接）**；
    - 若 Python 也不在 phase2 做（如 override 应用实际在 phase3 `note_item_overrides`、合成 marker 在别处）→ **死代码（删）**。
  - **交接建议**：grep Python `FNM_RE` 对应函数的调用点确认。**在确认前不要修 B1-11 的 endnote_project 哨兵 bug**（死代码里的 bug 不必修）。

---

## 4. B4 — 逻辑/契约不一致（短期）

- **B4-1** `[双]` DB enum 读回容错不一致：[repository.rs](fnm-core/src/db/repository.rs) note_kind/page_role/status 等 `unwrap_or(默认)` 静默兜底（有测试覆盖），而 region_scope/source `map_err` fail-fast。**修复**：统一策略 + 注释；建议与 B1-2/B1-3 一起走 fail-fast + 降级日志。
- **B4-2** `[双]` `structure_reviews` review_id 不持久化、读回用 `type+chapter+page` 合成且尾部写死 `"na"` → 同坐标多条碰撞。[repository.rs:1222](fnm-core/src/db/repository.rs)。**修复**：持久化 review_id 列，或合成键纳入区分字段。
- **B4-3** `[旧]` orchestrator [retry.rs:27](fnm-orchestrator/src/page_translate/retry.rs) `visible_idx` 在 `consumed_by_prev` 分支 `continue` 前未递增，与类型化版 `collect_failed_locations`（121）行为不一致 → para_idx 错位。**修复**：对齐两实现的 `visible_idx` 递增时机。
- **B4-4** `[旧]` orchestrator [load.rs:125-126](fnm-orchestrator/src/load.rs) `note_links` 与 `effective_note_links` 都赋同一份 `note_links`（effective 应是 override 后的）→ 语义混淆。**修复**：确认 DB 是否区分两者，effective 取 phase3 effective。
- **B4-5** `[双]` phase4 `local_endnote_ref_number` while 循环不可达死分支（max+1 后恒不冲突）；[fnm-core ref_rewriter.rs:176](fnm-core/src/ref_rewriter.rs)。**修复**：删 while。
- **B4-6** `[双]` ref-rewriter `find`+`captures` 重复匹配、`pattern.as_str().contains("\\[\\^")` 用正则源码做控制流（refs.rs:226）；改 `captures_iter` + 结构化标志。
- **B4-7** `[双]` phase1 `is_sentence_like_heading` 两实现阈值不一致（normalize.rs 8 词 vs fallback `is_sentence_like_heading` 6 词）；统一或注释差异。
- **B4-8** `[新]` 注释/实现不符：phase1 heading_candidates/mod.rs:374 称 pdf_font_band「stub」实为完整实现；monotonic.rs 注释「严格递增」实现 `<=`；records.rs 头注「1361 行」实 1657 行。**修复**：更新注释。

---

## 5. B5 — 质量：重复 / 弱类型 / 日志 / 性能（中长期）

- **B5-1** `serde_json::Value` 弱类型高频路径定型（llm-repair cluster / orchestrator page_translate job / phase3-4 中间结构）：为最常用字段加 typed accessor 或 struct。`[双]`
- **B5-2** 重复 helper 收敛到 fnm-core：`extract_json_block`(×3)、`WHITESPACE_RE`、`extract_context`(×2)、`safe_int`、`compute_body_bounds`(×2)、`candidate_source_score`(分值不同的两套)、`build_chapter_by_page`(×3)、page_numbers 提取(×3)、role_heuristics vs page_resolve 的 `looks_like_*` 重复。`[双]`
- **B5-3** `serde_json::to_value(RawPage)` 在循环内反复序列化：phase1 book_note_type/page_resolve/page_rows、phase2 chapter_split/mod.rs:216。改直接取 `RawPage` 字段。`[双]`
- **B5-4** `eprintln!`→`tracing`（≥6 处）：fnm-core config 静默吞错 + repository load_raw_pages、mainline.rs:623（含 TODO）、llm-repair run.rs:523、token_counter `_error` 字段。`[双]`
- **B5-5** fnm-py 每个 DB pyfunction `open_pool`（建池 + 跑 migrations）×21；高频按页/进度调用开销大 + 放大 B1-3。**改**：进程级池缓存（按 db_path）。`[新]`
- **B5-6** 超长函数拆分：phase1 `build_toc_semantics`(580)、phase4 `build_frozen_units`(740)、phase1 `build_phase1_structure`。`[双]`
- **B5-7** core `PhaseNSummary`/`PhaseNStructure` 6 份字段平铺重复 → `#[serde(flatten)] common`。`[双]`
- **B5-8** AI 推导草稿注释：phase2 [sequence_repair.rs:230-272](fnm-phase2/src/note_items/sequence_repair.rs) 测试内 ~40 行「Let me think… Wait… 公式好像错了」流水账，删。`[双]`
- **B5-9** 测试隔离：core `USAGE_RECORDS` 全局 Mutex 致并行测试污染（用弹性 `>=` 断言绕过）；types.rs `BookType` 漏入 roundtrip；config `default_pool_has_4_slots` 测试名不副实。`[双]`
- **B5-10** `rules::all_rules()` 每页重建 `Vec<fn>`；continuation/* 每页 `.cloned()` 整页文本；可借用/`const`。`[双]`

---

## 6. 验证修复成功的总策略

1. **回归基线**：修前先跑 `cargo test --workspace` 记录通过集；每条修复后重跑，不得新增失败。
2. **clippy 守门**：`cargo clippy --workspace --all-targets`，删死代码后须仍 **0 warning**（B2/B3 删除若触发新 dead_code 说明还有连带未清）。
3. **panic 类（B1-4/5/7/8/9/10）**：每条补一个触发该路径的 fixture 单测，先红后绿。
4. **数据正确性（B1-1/2/3, B4-2）**：
   - B1-1：page-translate 端到端 fixture，断言正文段 job 非空 + DB page_segments 非 `"[]"`；
   - B1-2：故意失败的 INSERT 单测断言回滚；
   - B1-3：池第 2+ 连接 `PRAGMA foreign_keys`=1 + 孤儿行被拒；
   - B4-2：两条同坐标 review 断言 review_id 不碰撞。
5. **B3 去留**：接入则 parity 测试对齐 Python LLM 验证输出；删除则 `cargo build` + clippy 0 warning + 全测试通过证明无活引用。
6. **实批回归（CLAUDE.md §13）**：B1/B3/B4 改完用「另一本书」做多书完整回归 + 导出审计，确认无 phase 间契约回归。

---

## 7. 与旧审计的关系（交接说明）
- 本清单的 **B1-1 / B1-3 / B5-5** 为本轮跨 crate 数据流追踪独有；**B1-4/5/9/10、B4-3/4** 来自旧审计逐行覆盖（本轮已逐条 Read 核实属实）。
- 旧审计 `audit/*.md` 的量化分级（19 P0 等）与逐行清单可作为本清单的**逐条对账表**；两份在核心问题上高度一致（DB 事务、as-u16、字节切片、死代码、未接入子系统、弱类型、eprintln 等），可信度高。
- **建议**：以本文件为执行主清单，旧审计 `audit/` 为逐行查漏补遗副本，二者合并即覆盖完全。
