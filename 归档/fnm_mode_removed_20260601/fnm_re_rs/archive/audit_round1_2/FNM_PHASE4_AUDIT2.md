# FNM-PHASE4 审计报告（独立第二轮）

> 审计范围：`fnm-phase4` crate 全部 17 个 `.rs` 文件（约 5,246 行）。
> 维度：程序逻辑、Rust 风格、过度防御/偷懒/AI 常见病。业务规则不评判。
> 方法：逐文件精读核心 + 反模式 grep 全覆盖 + unwrap 守卫核实。审计期间未参考现有 `audit/`。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

---

## 0. 总体印象：高质量（与 phase3 同档）

phase4（引用冻结 + 翻译单元 + 结构复核）质量高：
- crate 级 **`#![deny(unused_must_use)]`**（lib.rs:15）——主动收紧。
- `ref_freeze::build_frozen_units` 7 个 phase 严格按 Python 行号实现，skip 分类（ceiling/error/policy）清晰，book-scope endnote 注入归属 **anchor 所在章**（mod.rs:294 注释明确，不拿全书尾注章查正文）。
- `reviews` 的 `build_structure_reviews` / `build_structure_reviews_without_upstream_gate_reviews` **都委托给 `build_structure_reviews_with_policy`**（参数化，**非重复**）。
- `ref_freeze::inject::shift_coords_out_of_note_ref_token` 处理 NOTE_REF token 重叠避免坐标插入 token 内部——细节到位。
- 全 crate **无** `#[allow]`/`Runtime::new`/`as` 窄化/死代码丢弃。
- **所有 unwrap 已核实有前置守卫**（见下），无真 panic。
- clippy clean。

---

## 1. 🟡 低优先级（phase4 无高/中级真 bug）

### P4-1　`page_segments` 计算后未持久化到 unit（潜在数据流缺口）
- **位置**：[ref_freeze/mod.rs:449-489](fnm-phase4/src/ref_freeze/mod.rs)
- **分析**：chunking 产出的 `chunk["page_segments"]`（JSON）在 mod.rs:449 被提取为 `segs`，但**仅用于导出 `page_nos`**（454-467），随后 `FrozenUnit { ... page_segments: Vec::new() }`（489、558 行注释「JSON → 暂不反序列化」）。`units/mod.rs::frozen_unit_to_translation_unit` 再 `page_segments: fu.page_segments.clone()` → 故 `TranslationUnitRecord.page_segments` **恒为空**。
- **影响**：若 phase5/6 渲染需要段落级 `page_segments`，此处缺失（需从 source_text 重新解析）；若不需要，则为冗余字段 + 白算的 segs。**需在 phase5 审计时交叉确认**——这是 phase4→5 的数据契约疑点。

### P4-2　`build_frozen_units` ~740 行单函数 + 多参数闭包
- [ref_freeze/mod.rs:26-764](fnm-phase4/src/ref_freeze/mod.rs)：单函数 7 phase。虽按 Python 行号注释分段清晰、是线性数据流水线（比 phase1 `build_toc_semantics` 可读性好），但仍偏长。
- `record_skipped`（8 参数）、`append_note_unit`（7 参数）闭包是 borrow-checker workaround，可重构为持 `&mut` 状态的 struct + 方法。低优先级。

### P4-3　防御性 unwrap（已核实安全，可选改 `?`）
所有非 regex unwrap 均有前置守卫：
- [text/re_utils.rs:172,184,216](fnm-phase4/src/text/re_utils.rs) `chars().next().unwrap()` —— 前面均有 `is_empty()`/`len()<3` 守卫。
- [text/markdown_parse.rs:745-796](fnm-phase4/src/text/markdown_parse.rs) `merged.last().unwrap()` —— 均在 `!merged.is_empty()` 内。
- [ref_freeze/mod.rs](fnm-phase4/src/ref_freeze/mod.rs) `body_page.unwrap()`/`.as_object_mut().unwrap()` —— 前置 `is_none()` 检查 / json! 构造保证。
属正确但风格上可用 `if let`/`?` 表达守卫，消除 panic 面。

### P4-4　nit
- [segments/chunking.rs:95](fnm-phase4/src/segments/chunking.rs) `to_value(page_segments)`（合理序列化，非 RawPage 浪费）。
- markdown_parse 1112 行单文件（~25 helper），是 `text_processing.py` 整体移植，按职责其实可拆 parse/merge/heading 三组；当前以单文件 + 注释索引维持，可接受。

---

## 2. 正面实践
- ref_freeze contract/caution 双层门（freeze.only_matched_frozen / no_duplicate_injection / closed_without_error / unit_contract_valid）。
- skip 分类语义清晰：policy_skip 清除正文重复标记，ceiling/error_skip 保留原 marker 作失败证据。
- units 一对一 frozen→translation 映射，section_order 稳定排序。
- 引用 token 注入用 `char_index_to_byte_index` 做 char/byte 转换（不裸切片）。

---

## 3. 文件覆盖确认（17/17）
lib｜input｜output｜ref_freeze/{mod,chapter_index,contract,hash,inject}｜reviews｜segments/{mod,chunking}｜text/{mod,markdown_parse,re_utils}｜units/{mod,endnote_lookup,page_split}

> 逐字精读 lib + ref_freeze/mod + units/mod + markdown_parse 头部 + inject 核心 + reviews 结构 + 全部 unwrap 守卫；其余经反模式 grep（clean）+ 去注释 cat 覆盖。

**核心结论**：phase4 质量与 phase3 同档，无真 bug。唯一需跟进的是 **P4-1（page_segments 未持久化）**——留待 phase5 审计验证是否为真实数据契约缺口。其余为可选清理（长函数、防御 unwrap）。
