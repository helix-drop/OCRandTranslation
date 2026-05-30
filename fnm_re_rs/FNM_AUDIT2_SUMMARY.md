# FNM Rust 代码库审计总览（独立第二轮）+ 与现有审计对照

> 审计范围：10 个 crate 的 `src/` 源码（约 268 个 `.rs` 文件 / 63.8k 行）。
> 维度：程序逻辑、Rust 风格、过度防御/偷懒/AI 常见病。**不含业务逻辑**。
> 方法：逐文件精读核心 + `cargo clippy --all-targets`（强制 touch 后 **0 warning**）+ 反模式 grep + **跨 crate 数据流追踪** + 调用关系核实。
> 审计期间不读现有 `audit/`，全部 10 份 `FNM_*_AUDIT2.md` 完成后才对照。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

各 crate 详见：[CORE](FNM_CORE_AUDIT2.md) · [PHASE1](FNM_PHASE1_AUDIT2.md) · [PHASE2](FNM_PHASE2_AUDIT2.md) · [PHASE3](FNM_PHASE3_AUDIT2.md) · [PHASE4](FNM_PHASE4_AUDIT2.md) · [PHASE5](FNM_PHASE5_AUDIT2.md) · [PHASE6](FNM_PHASE6_AUDIT2.md) · [LLM-REPAIR](FNM_LLM_REPAIR_AUDIT2.md) · [ORCHESTRATOR](FNM_ORCHESTRATOR_AUDIT2.md) · [PY](FNM_PY_AUDIT2.md)

---

## 1. 质量分层（核心结论）

代码质量呈**明显两档**，与重构时序吻合：

| 档位 | crate | 特征 |
|---|---|---|
| **A（高质量，后期重构）** | phase3 / phase4 / phase5 / phase6 / llm-repair | 严格遵守铁律（注释引用 §1/§3/§4/§12）、数据驱动去广播、性能意识（marker_cache 避免 hot-loop regex）、Unicode 仔细、unwrap 几乎都有守卫、ZIP-slip 防护、错误分类完整 |
| **B（问题集中，早期移植 + 基础设施）** | core / phase1 / phase2 | DB 事务/外键缺陷、字节切片 panic、死代码堆积（「构建后丢弃」≥4 处）、大量未接入子系统、`serde_json::to_value(RawPage)` 浪费、AI 推导草稿注释 |

orchestrator/py 是薄编排/绑定层，骨架质量高，但**承接了 B 档的数据契约缺陷**（见 H-1）。

---

## 2. 跨 crate 高优先级主题（按影响排序）

### H-1　`page_segments` 恒空 → 按页翻译正文丢失（跨 4 crate，本轮独有发现）
phase4 [ref_freeze/mod.rs:489](fnm-phase4/src/ref_freeze/mod.rs) `FrozenUnit.page_segments = Vec::new()`（算了 chunk segments 仅取 page_nos，未持久化）→ phase5 convert 透传空 → DB `page_segments_json="[]"` → orchestrator [jobs.rs](fnm-orchestrator/src/page_translate/jobs.rs) `frozen_body_text_for_page` 只读 page_segments、**无 source_text fallback** → 经 fnm-py `prepare_page_translate_jobs_json` 暴露的**按页翻译入口正文 job 全跳过**。章合并模式（phase5）有 source_text fallback 不受影响，故该 bug 在 page-translate 路径潜伏。**建议**：phase4 持久化 page_segments，或 jobs.rs 加 source_text fallback。

### H-2　DB 写入无事务（影响 Phase1-6 全部 replace）
fnm-core [db/repository.rs](fnm-core/src/db/repository.rs) 所有 `replace_*` 均 DELETE+循环 INSERT 无事务（仅 `batch_save_review_overrides_v2` 用了事务）。中途失败 → 旧数据已删、新数据半写的不一致态。**建议**：`conn.transaction()` 包裹。

### H-3　连接池 `foreign_keys` 仅迁移连接生效（本轮独有发现）
fnm-core [db/pool.rs:22](fnm-core/src/db/pool.rs) `PRAGMA foreign_keys=ON` 是 per-connection，只设在迁移用的首个连接；池中其余连接默认 OFF → 外键约束实质失效（可写孤儿行）。fnm-py 每调用新建池（[PY-1](FNM_PY_AUDIT2.md)）放大暴露面。**建议**：`SqliteConnectionManager::file(p).with_init(|c| c.execute_batch("PRAGMA foreign_keys=ON;"))`。

### H-4　字节/字符混用 panic（多处）
phase1 toc_structure:303 字节切片多字节标题 panic（已修建议用 chars().take）；orchestrator jobs.rs trim/tail_context `len()`(字节) 比较 + `chars().take`(字符) 截断不一致（CJK 偏差）；phase3 endnote_links unicode byte_end 边界。**根因**：`str.len()` 字节 vs Python `len()` 字符的移植语义差。

### H-5　`page_index as i64→u16` 截断
fnm-core vision/pdfium.rs + phase1 pdf_font.rs：负值/>65535 回绕访问错误页。**建议** `u16::try_from`。

### H-6　运算符优先级越界 panic
phase4 markdown_parse.rs:911 `!empty && A || result[0]` —— result 空时 `||` 右侧仍 `result[0]` 越界 panic（**本轮核实确认，旧审计已标，我初轮 grep+抽样漏读此行**）。fnm-py lib.rs:787 同类（当前靠短路侥幸正确）。

### 跨 crate 共性（中优先级）
- **大量未接入 pub 代码**：phase1 book_note_type + llm_book_type_verify（~1660 行）、phase2 visual_anchor_recovery + llm_bare_digit + chapter_split/{endnote_project,overrides_apply,synth_markers}（0 引用）。靠 `pub`/`_`/`#[allow]` 规避 clippy dead_code。
- **「构建后丢弃」死代码**：phase1 `_synthetic`/`_chapter_title_key_map`/`_missing`/`_page_row_by_no`、phase3 `_anchor_matched_count`、orchestrator `_section_title`。
- **`serde_json::Value` 弱类型**：贯穿 llm-repair/orchestrator/phase3-6/core，字段名拼写无编译期保护。
- **代码重复**：`extract_json_block`(×3)、`WHITESPACE_RE`/`extract_context`/`safe_int`/`compute_body_bounds`/page_numbers 提取等多份。
- **`eprintln!` 代替 `tracing`**（≥6 处）；**PhaseNSummary/Structure 字段平铺重复**（core records）。

---

## 3. 与现有 `audit/`（旧审计）对照

### 3.1 高度一致（互相印证，可信度高）
两轮**独立**审计在以下核心问题上完全重合：DB 事务缺失、`as u16` 截断（×2）、toc_structure:303 字节切片 panic、phase1 pdf_font_band NaN partial_cmp、`_synthetic` 等死值、fallback.rs 3× `#[allow(dead_code)]`、死 regex、phase2 sup_recovery 循环建 Runtime、note_kind_resolver `explicit_markers` 死字段、PhaseNSummary 重复、segment_codec/Value 弱类型、token_counter 测试污染、ref_rewriter 重复、未接入子系统、`eprintln!`、review_id 重建、超长函数（toc_semantics 580 / build_frozen_units 760）等。→ **核心问题清单可信。**

### 3.2 本轮独有（旧审计未覆盖）
- **H-1 `page_segments` 跨 4-crate 链路致按页翻译正文丢失**：旧审计逐 crate 看，phase4 只标了运算符 panic、orchestrator P0 是 jobs byte/char + retry + load，**均未把 page_segments 恒空串成正文丢失的端到端链**。这是跨 crate 数据流追踪的独有价值。
- **H-3 `foreign_keys` 仅迁移连接生效**：旧审计 core 标了 DB 事务（P0）与「池大小硬编码」（P3），但**未发现 foreign_keys 的 per-connection 语义致约束失效**。

### 3.3 旧审计更全 / 本轮漏掉（已核实，诚实记录）
本轮用「核心精读 + grep 反模式 + 抽样」未逐行读完所有大文件，漏掉旧审计找到的若干**单行 bug**（已抽样核实属实）：
- **phase4 markdown_parse:911 运算符优先级越界 panic**（已 Read 确认）；
- **phase6 file_audit:320 `chars().rev().take(120)` 产出倒序字符串**（已 Read 确认）；
- phase2 endnote_project 哨兵值 1000000、boundary_fallback:407 空数组守卫、book_regions 死分支；
- phase3 endnote_links unicode byte_end 越界、gap_recovery 死分支、anchor_overrides ~12 处 unwrap；
- phase1 `is_sentence_like_heading` 两实现阈值不一致（6 词 vs 8 词）；
- orchestrator retry.rs:27 `visible_idx` 与类型化版不一致、load.rs:126 note_links/effective 语义混淆、post_translate 重复合并 blocker；
- phase4 ref_freeze:121 `(-char_a).cmp` i64::MIN 溢出；fnm-py GIL allow_threads 重入隐患、lib.rs:850 字段源错配。
> 旧审计的量化分级（19 P0 / 45 P1 / 80 P2 / 59 P3）与逐行覆盖更适合做「逐条修复清单」。

### 3.4 视角差异（同一代码，结论不同）
- phase2 `endnote_project`：旧审计标其内部「哨兵值 P0 bug」；本轮 grep 确认 `compute_endnote_projections` **0 非测试引用 = 整文件未接入**——死代码里的 bug 不影响运行，去留决策优先于修 bug。
- 文件/行数差异：旧审计计 `src+tests`（如 core 37 文件/11355 行），本轮计 `src`（30 文件/10170 行）——本轮聚焦源码 + `#[cfg(test)]` 内联测试，未单独审 `tests/` 集成测试文件。

---

## 4. 综合修复优先级建议

1. **立即（数据正确性）**：H-1（page_segments 正文丢失）、H-2（DB 事务）、H-3（foreign_keys）、H-6 + file_audit:320（panic / 倒序）、H-4/H-5（byte-char / as-u16）。多为 1-5 行或一处契约修正。
2. **短期（逻辑/契约）**：去留未接入子系统（明确 roadmap 或删除）；统一 enum 读回容错策略（C-5）；review_id 持久化（H-2 关联）；旧审计 3.3 的单行 bug 清单逐条修。
3. **中期（质量）**：消除「构建后丢弃」死代码 + `#[allow(dead_code)]` 掩盖项；收敛重复 helper 到 fnm-core；弱类型 `Value` 高频路径定型；`eprintln!`→`tracing`。
4. **长期**：PhaseNSummary `#[serde(flatten)]` 复用；fnm-py 池缓存 + 修 H-3；超长函数拆分。

---

## 5. 正面结论
- **clippy clean**（强制全量重编 0 warning）、源码**无 `unsafe`**（「2190」系 grep 误匹配）、几乎无 `todo!/unimplemented!`。
- A 档 crate（phase3-6/llm-repair）质量达到生产标准：铁律合规、错误处理/并发/超时/容错到位、Unicode 与性能意识好。
- Python 行号对照注释、铁律引用注释、gate_report 程序合同、parity/spec/contract 三类测试覆盖，是该代码库突出优点。
- 与旧审计**两轮独立、核心高度一致**：既互相印证了主问题清单，又各自补足（本轮补 page_segments / foreign_keys 跨 crate 链，旧审计补单行 bug 全覆盖）。建议两份合并为最终修复清单。
