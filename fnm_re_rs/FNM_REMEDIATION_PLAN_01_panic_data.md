# 批次 1 详细计划 — 数据正确性 / panic 修复

> 隶属 `FNM_REMEDIATION_PLAN_00_MASTER.md` 批次 B1。**执行起点，先做。**
> 性质：点状修复（多为 1–5 行），低风险高收益，彼此独立可并行。
> 前置：无。建议独立分支 `fix/b1-panic-data`。
> 全程：改前记录 `cargo test --workspace` 基线；每条「先写复现测试→红→修→绿」；clippy 保持 0 warning。

---

## 执行顺序（批次内）
先做纯 panic 单行（B1-4/5/6/7/8/9/10，互不依赖）→ 再做 DB 契约（B1-2/3，需 schema 理解）→ 最后 B1-1（跨 crate，最大）+ B1-11（phase2 多点）。

---

## B1-1　page_segments 恒空 → 按页翻译正文丢失【最高优先级 / 跨 4 crate】
**审计依据**：`FNM_PHASE4_AUDIT2.md` P4-1、`FNM_ORCHESTRATOR_AUDIT2.md` O-1、`FNM_AUDIT2_SUMMARY.md` H-1。
**根因**：phase4 算出 chunk 的 `page_segments`（JSON）只用于取 `page_nos`，把 `FrozenUnit.page_segments` 设成空；下游 phase5/DB/orchestrator/py 的按页翻译全靠它取正文段，链路断裂。pipeline 测试不含翻译，覆盖盲区。

**修复 A（根治，推荐）— phase4 持久化 page_segments**
位置：`fnm-phase4/src/ref_freeze/mod.rs` body_unit 构建处（约 449–494）。
```rust
// before（约 489）：
// page_segments: Vec::new(), // JSON → 暂不反序列化
// after：把 chunk["page_segments"]（serde_json::Value 数组）反序列化为 Vec<UnitPageSegmentRecord>
let page_segments: Vec<fnm_core::records::UnitPageSegmentRecord> =
    serde_json::from_value(segs.clone()).unwrap_or_default(); // segs 即 chunk.get("page_segments")
// ...
FrozenUnit { page_segments, /* 其余不变 */ }
```
注意：`segs` 当前（约 449）已取出仅用于 page_nos，复用它；确认 `UnitPageSegmentRecord` 的 serde 字段与 chunk JSON 键一致（chunk 由 `segments::segment_paragraphs_from_body_pages`+`chunking` 产出，字段应同构）。

**修复 B（兜底，建议叠加）— orchestrator 加 source_text fallback**
位置：`fnm-orchestrator/src/page_translate/jobs.rs:9-25` `frozen_body_text_for_page`，及 `jobs_builder.rs:18`。
```rust
// frozen_body_text_for_page：page_segments 为空时退回 unit.source_text
if parts.is_empty() {
    let st = unit.source_text.trim();      // TranslationUnitRecord.source_text 始终有值
    if !st.is_empty() { return st.to_string(); }
}
```
（与 phase5 `render/body_render.rs:resolve_body_unit_text` 的三级 fallback 保持一致。）

**验证**：
1. 新增 `fnm-phase4` 单测：构造含正文 body unit → `build_frozen_units` → 断言 `frozen.body_units[0].page_segments` 非空、paragraph 数与输入一致。
2. 新增 orchestrator/py 端到端 fixture：跑一本书 pipeline persist → 读 DB `fnm_translation_units.page_segments_json != "[]"` → 调 `build_fnm_body_unit_jobs` 断言返回 `len()>0` 且含正文段。
3. 回归：纯正文（无 note）章节翻译 job 非空。

---

## B1-2　DB 所有 `replace_*` 无事务
**审计依据**：`FNM_CORE_AUDIT2.md` C-2；旧审计 P0。
位置：`fnm-core/src/db/repository.rs`：`write_phase1_tables`、`replace_fnm_phase2_products`、`replace_fnm_phase3_products`、`replace_fnm_translation_units`、`replace_fnm_structure_reviews`、`replace_fnm_phase5_products`、`replace_fnm_phase6_products`。
```rust
// before：let conn = self.get_conn()?; conn.execute("DELETE ...")?; for ... { stmt.execute(...)?; }
// after：
let mut conn = self.get_conn()?;
let tx = conn.transaction()?;
tx.execute("DELETE FROM ... WHERE doc_id=?1", [doc_id])?;
{ let mut stmt = tx.prepare("INSERT ...")?; for row in rows { stmt.execute(params![...])?; } }
tx.commit()?;
```
注意：`prepare` 借用 `tx`，用内层 `{}` 作用域释放后再 `commit`；`get_conn` 返回需 `mut`。
**验证**：单测注入一个会失败的 INSERT（如违反 NOT NULL），断言事务回滚后旧行仍在（DELETE 未生效）。同时性能应提升（单事务批量提交）。

---

## B1-3　连接池 foreign_keys 仅迁移连接生效
**审计依据**：`FNM_CORE_AUDIT2.md` C-1、`FNM_AUDIT2_SUMMARY.md` H-3。
位置：`fnm-core/src/db/pool.rs:12-27`。
```rust
// after：用 with_init 让每个新连接都开 FK
let manager = SqliteConnectionManager::file(db_path)
    .with_init(|c| c.execute_batch("PRAGMA foreign_keys=ON;"));
let pool = Pool::builder().max_size(4).build(manager).context("...")?;
{ let conn = pool.get()?; conn.execute_batch("PRAGMA journal_mode=WAL;")?; schema::run_migrations(&conn)?; }
```
**验证**：从池连续 `get()` 第 2、3 个连接，`PRAGMA foreign_keys` 应返回 1；插入 `doc_id` 不存在于 `documents` 的 fnm_* 行应被拒（修前不被拒）。
**关联**：批次5 B5-5（fnm-py 池缓存）会放大此修复收益。

---

## B1-4　phase4 markdown_parse 运算符优先级越界 panic
**审计依据**：旧审计 P0（本轮初读漏、`FNM_AUDIT2_SUMMARY.md` §3.3 已核实）。
位置：`fnm-phase4/src/text/markdown_parse.rs:911` 附近 `!cond && A || result[0]...`。
```rust
// 先加括号厘清意图，再对 result[0] 加判空：
let should = (!cond && a_flag) || (/* 原 || 右侧 */);
// 凡访问 result[0]/merged.last() 处，前置 !result.is_empty() / if let Some(last)=...
```
**验证**：构造触发该分支且 `result`/`merged` 为空的输入单测，先复现 panic 再修绿。

---

## B1-5　phase6 file_audit `chars().rev().take(N)` 倒序串
**审计依据**：旧审计 P0（本轮 §3.3 核实）。
位置：`fnm-phase6/src/export_audit/file_audit/mod.rs:320`。
```rust
// before: s.chars().rev().take(120).collect::<String>()  // 倒序！
// after:
let n = s.chars().count();
let tail: String = s.chars().skip(n.saturating_sub(120)).collect();
```
**验证**：单测断言尾部截取保持正序（如 `"abcdef"` 取尾 3 = `"def"` 而非 `"fed"`）。

---

## B1-6　`page_index as u16` 截断
**审计依据**：`FNM_CORE_AUDIT2.md` C-6、`FNM_PHASE1_AUDIT2.md` P1-4。
位置：`fnm-core/src/vision/pdfium.rs:37,73,103`、`fnm-phase1/src/chapter_skeleton/pdf_font.rs:65`。
```rust
// before: pages.get(page_index as u16)
// after:
let idx = u16::try_from(page_index)
    .map_err(|_| anyhow::anyhow!("page_index {} 超出 u16 范围", page_index))?;
pages.get(idx)
```
**验证**：传 `-1` / `70000` 返回 Err 而非访问错误页。

---

## B1-7　phase1 toc_structure 字节切片多字节标题 panic
**审计依据**：`FNM_PHASE1_AUDIT2.md` P1-1（高）。
位置：`fnm-phase1/src/toc_structure.rs:303`。
```rust
// before: &tk[..tk.len().min(20)]
// after:  &tk.chars().take(20).collect::<String>()
```
（同 crate `title_utils.rs:283` 已是正确写法，可对照。）
**验证**：用法语标题（key 含 `é/à`）fixture 让第 20 字节落在多字节字符中，先复现 panic 再修绿。

---

## B1-8　phase1 pdf_font_band `partial_cmp().unwrap()` NaN panic
**审计依据**：`FNM_PHASE1_AUDIT2.md` P1-3；旧审计 P0。
位置：`fnm-phase1/src/chapter_skeleton/heading_candidates/pdf_font_band.rs:256,262`。
```rust
// before: rank_item(a, true).partial_cmp(&rank_item(b, true)).unwrap()
// after:  ...partial_cmp(...).unwrap_or(std::cmp::Ordering::Equal)
```
**验证**：含 `"NaN"` 字符串坐标的 item（`safe_float` 会得 NaN）排序不 panic。

---

## B1-9　phase3 Unicode 上标 byte_end 越界
**审计依据**：旧审计 P0（`FNM_AUDIT2_SUMMARY.md` §3.3）。
位置：`fnm-phase3/src/endnote_links.rs:434-436`。
```rust
// 用实际匹配的 char 边界换算 byte_end，而非 byte_start + pat.len()
let byte_end = body_text.char_indices()
    .nth(end_idx).map(|(i,_)| i).unwrap_or(body_text.len());
// 切片前确认 body_text.is_char_boundary(byte_end)
```
**验证**：多位上标 marker（如 `¹²`）fixture 断言偏移正确、不 panic。

---

## B1-10　phase4 `(-char_a).cmp(...)` i64::MIN 溢出
**审计依据**：旧审计（`FNM_AUDIT2_SUMMARY.md` §3.3）。
位置：`fnm-phase4/src/ref_freeze/mod.rs:121` 排序键。
```rust
// before: .then_with(|| (-char_a).cmp(&(-char_b)))
// after:  .then_with(|| std::cmp::Reverse(char_a).cmp(&std::cmp::Reverse(char_b)))
```
**验证**：clippy 不报 `arithmetic_overflow`；极值单测。

---

## B1-11　phase2 哨兵值 / 空数组守卫 / 静默 Null
**审计依据**：旧审计 P0；`FNM_PHASE2_AUDIT2.md`。
1. `fnm-phase2/src/chapter_split/endnote_project.rs:89` 哨兵 `1000000` 代替 Option。
   **⚠ 先看批次2 §B3-5**：该文件 `compute_endnote_projections` 0 引用，**若判定为死代码则不修此 bug，直接删文件**；若判定该接入，再把哨兵改 `Option<usize>`。
2. `fnm-phase2/src/endnote_chapter_explorer/boundary_fallback.rs:407` `pages.first().unwrap()`/`last().unwrap()` 空数组守卫：前置 `if pages.is_empty() { continue; }`。
3. `fnm-phase2/src/chapter_split/mod.rs:216` `serde_json::to_value(p).unwrap_or_default()` 序列化失败静默 Null：改 `?` 传错误或 `tracing::warn`；并随 B5-3 消除 RawPage→Value 浪费。
**验证**：各对应边界单测（空 pages、序列化失败路径）。

---

## 完成标准（DoD）
- [ ] 每条都有一个先红后绿的复现测试。
- [ ] `cargo test --workspace` 无新增失败；`cargo clippy --workspace --all-targets` 0 warning。
- [ ] B1-1 端到端验证：DB `page_segments_json` 非空 + 按页翻译正文 job 非空。
- [ ] B1-2/3 DB 验证：回滚断言 + 第 2+ 连接 FK=1。
- [ ] 用「另一本书」做一次多书回归（CLAUDE.md §13），确认无 phase 间契约回归。

## 风险与回滚
- B1-1 修复 A 若 chunk JSON 字段与 `UnitPageSegmentRecord` serde 不同构，`from_value` 会得空 → **务必先写 phase4 单测验证反序列化成功**；不确定时叠加修复 B（fallback）确保不回退。
- B1-2 事务改造注意 `prepare` 借用作用域，避免 `tx` move 编译错误。
- 其余均为局部单行改动，回滚成本低（git revert 单条）。
