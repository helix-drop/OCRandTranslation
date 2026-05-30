# FNM-PHASE3 审计报告（独立第二轮）

> 审计范围：`fnm-phase3` crate 全部 39 个 `.rs` 文件（约 8,443 行）。
> 维度：程序逻辑、Rust 风格、过度防御/偷懒/AI 常见病。业务规则不评判。
> 方法：逐文件精读核心 + 反模式 grep 全覆盖 + 调用关系/红线核实。审计期间未参考现有 `audit/`。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

---

## 0. 总体印象：质量标杆 crate

phase3（body anchor 检测 + note link 匹配）是目前审计的 5 个 crate 中**质量最高**的，几乎无需修复。突出优点：

- **严格遵守 CLAUDE.md 铁律**，且注释逐处引用：
  - §1 只消费上游事实（lib.rs:134 透传 phase2 chapter_note_modes 不重建）；
  - §3 禁止广播（[chapter_contracts.rs:290,322](fnm-phase3/src/note_linking/chapter_contracts.rs) footnote/endnote `def_count` 分离，脚注定义不混入尾注）；
  - §4 不重构上游事实（lib.rs:85 paragraph 数据源从 raw markdown 改为 phase2 NoteItem）；
  - §12 分类源头唯一（note_kind 不在 phase3 重分类——`note_kind_inference` 只推断 **anchor 自身** kind 用于匹配兼容性，**不修改 note item 的 note_kind**，已 grep `.note_kind =` 确认无赋值）。
- **弱信号守卫完整**（§10/§11）：bare_digit 三层 context guard + 4 条件正向门（[context_guard.rs](fnm-phase3/src/body_anchors/context_guard.rs)）。
- **性能意识好**：[endnote_links.rs](fnm-phase3/src/endnote_links.rs) 用 caller-owned `marker_cache` 预构建 marker 正则，避免 hot-loop `Regex::new`（AGENTS.md §2），且不用静态 `Mutex<HashMap>`（§10）。
- **Unicode 处理仔细**：Rust regex 无 lookaround，手动实现上标负前瞻/后顾（endnote_links.rs:407-444）。
- `book_type` 已从 endnote_repair/suppress 签名删除，改**数据驱动**判断（避免广播依赖）。
- clippy clean；全 crate **无** `Runtime::new`/`as u16` 窄化/`to_value(RawPage)` 浪费/死代码丢弃。

无 phase1/2 的「构建后丢弃」死代码、未接入大子系统、AI 草稿注释、serde 浪费等问题。

---

## 1. 🟡 低优先级（phase3 无高/中级真 bug）

### P3-1　LLM bare_digit verifier 未接入 → 部分候选被静默丢弃
- **位置**：[body_anchors/context_guard.rs:175-193](fnm-phase3/src/body_anchors/context_guard.rs) `positive_gate_bare_digit` 返回 `llm_candidates`（count>2 或 false-positive 上下文的 bare_digit），但 [note_linking/mod.rs:150](fnm-phase3/src/note_linking/mod.rs) `let _pdf_path = pdf_path;` 表明 LLM 验证未接入，`build_body_anchors` 只把 `llm_candidates` 用于 `llm_candidate_count` 统计——这些候选**既不接受也不送 LLM，被丢弃**。
- **评价**：是已知功能缺口（待 fnm-llm-repair crate），有 `llm_candidate_count` 统计 + 诚实注释。非 bug，但功能不完整——需在 Phase 3.5 接入 verifier 后这些候选才能被验证回收。

### P3-2　防御性 `expect("regex boundary")`（多处）
- **位置**：[pattern_scan.rs](fnm-phase3/src/body_anchors/pattern_scan.rs)、[endnote_links.rs:289-333](fnm-phase3/src/endnote_links.rs)、[gap_recovery.rs:287-378](fnm-phase3/src/body_anchors/gap_recovery.rs) 的 `byte_index_to_char_index(text, m.start()).expect("regex boundary")`。
- **评价**：regex `Match` 的 start/end 必落在 char boundary，`expect` 实际不会触发——但仍是 panic 点。可改 `?`/`unwrap_or` 让异常路径返回 None 而非 panic。低优先级（防御冗余）。

### P3-3　未用参数 / 丢弃变量
- [note_linking/mod.rs:150](fnm-phase3/src/note_linking/mod.rs) `_pdf_path`（LLM 未接入，注释充分）。
- [note_links.rs:238](fnm-phase3/src/note_links.rs) `build_summary` 的 `_note_items` 未用。
- [paragraph_footnotes.rs:195](fnm-phase3/src/paragraph_footnotes.rs) `let _anchor_matched_count = ...`（计算后丢弃，单点死变量，类似 phase1 模式但仅一处）。

### P3-4　其他 nit
- link 匹配大量 `NoteLinkRecord`/`BodyAnchorRecord` `.clone()`（endnote_links/footnote_links/contract_repair）——link 匹配算法常态，正确性无虞，若性能敏感可考虑就地修改/索引；当前可接受。
- `endnote_repair/contract_repair.rs:62,182` 的 2 处 `#[allow(clippy::needless_range_loop)]` —— **正当**：注释说明需 index 修改 `repaired_links[index]`（与 Python enumerate-then-mutate 一致），clippy 误报，非偷懒掩盖。

---

## 2. 正面实践细节
- `pattern_scan` 11+ 模式各有 `certainty`/`priority` 表，重叠去重按优先级 + span 选优。
- `chapter_contracts` endnote contract 的 first_marker/gap/def_anchor_mismatch 全部只用 endnote marker 序列，注释强调「§1 分类源头唯一；§3 禁止广播」。
- `gap_recovery` 用 `within_sequence_page_window` 约束恢复页范围、不跨章（铁律 §4）。
- endnote orphan 正文恢复分 per-page（certainty 0.7）/ combined（0.5）两级，标 `synthetic + OrphanRecovery`。
- `renumber_link_ids` 在 phase3 出口统一重排 link_id，解决「caller 各自从 1 计数致跨章 ID 重叠」（注释明确）。

---

## 3. 文件覆盖确认（39/39）
lib｜input｜output｜link_utils｜note_links｜endnote_links｜footnote_links｜paragraph_endnotes｜paragraph_footnotes｜body_anchors/{mod,chapter_marker_sets,context_guard,gap_recovery,pattern_scan}｜chapter_anchor_alignment/{mod,dp_alignment}｜endnote_repair/{mod,contract_repair,tests}｜note_linking/{mod,anchor_overrides,anchor_summary,chapter_body_text,chapter_contracts,chapter_meta,evidence_assemble,for_chapter,gate_compute,layer_conversion,link_overrides,link_summary,note_item_overrides,note_kind_inference,phase2_rebuild}｜note_linking/ocr_repair/{mod,loop1_orphan_rebind,loop2_ambiguous_followup,loop3_cross_chapter,tests}

> 逐字精读入口 + body_anchors + note_linking 编排 + link 匹配三核心 + chapter_contracts + context_guard + gap_recovery 等 ~10 个核心文件；其余经反模式 grep（全 crate clean）+ 去注释 cat + 调用/红线核实覆盖。

**核心结论**：phase3 是重构成果的体现——遵守全部铁律、性能与 Unicode 处理到位、无死代码堆积。唯一实质缺口是 **P3-1（LLM bare_digit verifier 未接入致部分候选丢弃）**，属 Phase 3.5 待办；其余均为可选清理（防御性 expect、未用参数）。
