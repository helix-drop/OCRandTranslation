# 批次 5 剩余工作执行计划 — 阶段 B/C 质量改进

> 隶属 `FNM_REMEDIATION_PLAN_05_quality.md`。阶段 A（B5-4/5/3/8）已完成。
> 本文档覆盖剩余 6 项：**B5-2 重复收敛、B5-1 弱类型、B5-9 测试隔离、B5-6 超长函数、B5-7 records flatten、B5-10 性能 nit**。
> 编写日期：2026-05-30。位置已抽样验证（`ln()` 两处 / 超长函数行数 / records 结构行号），其余沿用 05 计划并标注。
> 总原则：**行为不变**。重构项必须有快照/parity 测试守护后再动手。每项独立小 PR。

---

## 0. 现状

阶段 A 已完成：B5-4(`eprintln!`→`tracing`)、B5-5(连接池缓存)、B5-3(RawPage 序列化)、B5-8(草稿注释)。
剩余 6 项，按**风险/收益重排**，低风险先做、最高风险 B5-7 殿后。

---

## 1. 执行顺序总览

| 序 | 项 | 风险 | 收益 | 测试守护 |
|---|---|---|---|---|
| 1 | B5-9 测试隔离 | 低 | 中（消除 flaky） | 自身即测试 |
| 2 | B5-10 性能 nit | 低 | 低 | 行为不变断言 |
| 3 | B5-2 重复收敛 | 低–中 | 中 | 各调用点 parity |
| 4 | B5-1 弱类型定型 | 中 | 中 | 行为不变 |
| 5 | B5-6 超长函数拆分 | 中 | 中（可读性） | 快照测试 |
| 6 | B5-7 records flatten | **高** | 中（去重） | JSON 快照（数据契约） |

---

## 2. 逐项详细

### B5-9 测试隔离〔先做，低风险〕
- `fnm-core/src/token_counter.rs`：全局 `USAGE_RECORDS: Mutex<Vec>` 致并行测试污染（现用 `>=` 弹性断言绕过）→ 测试内用独立 recorder 实例，或加 `#[serial]`（`serial_test`）串行标注。
- `fnm-core/src/types.rs`：`BookType` 漏入 `all_enums_roundtrip` / `all_enums_have_all_const` → 补上。
- `fnm-core/src/config.rs:286`：`default_pool_has_4_slots_with_builtin_at_zero` 测试名不副实（只断言非空）→ 补全断言或改名。
- **验证**：测试自身即守护，反复跑稳定（消除弹性断言）。

### B5-10 性能 nit〔低风险〕
- `fnm-phase1/page_partition/rules/mod.rs:58` `all_rules()` 每页重建 `Vec<fn>` → `const`/`static` 数组。
- `fnm-phase1/page_partition/continuation/mod.rs` 每页 `.cloned()` 整页文本 → 借 `&str`。
- `fnm-core/segment_codec.rs` `deserialize_paragraph` 11 个 `has_*` 冗余分支（~150→~40 行，if/else 两分支等价）→ `get().or().unwrap_or(default)`。**需 codec roundtrip 测试守护**。
- `fnm-phase1/note_marker.rs:150` `chars().nth(cursor)` O(n²) → 字节索引（短串影响小，可缓）。
- **验证**：行为不变；segment_codec 改动跑现有 roundtrip 测试。

### B5-2 重复 helper 收敛〔低–中风险，分多 PR〕
**第一步必做：diff 每对，确认分值/阈值是否一致**（§12 强调不可盲目合并）。已验证待 diff：
- **`ln(source, block_label) -> i64`**：`heading_graph/scoring.rs` 与 `chapter_skeleton/toc_semantics/row_collect.rs`，**同签名疑似复制** → 先 diff 分值表（`pdf_font_band_composite=>320` 等）：一致→提 `fnm-core`；不一致→保留 + 注释「为何不同」。
- `extract_json_block`：fnm-phase2 + fnm-llm-repair（×3）
- `WHITESPACE_RE`：多 crate
- `extract_context`：phase3 ×2
- `safe_int`：phase5 ×2
- `compute_body_bounds`：phase2 ×2
- `build_chapter_by_page`：phase1 ×3
- `looks_like_copyright/course_listing/title_page`：phase1 `role_heuristics` vs `page_resolve`（**简化版不一致，可能有意** → 重点确认）
- **做法**：一致的提 `fnm-core` 公共模块；不一致的保留 + 注释差异来源。
- **验证**：各调用点 parity 测试不变。

### B5-1 弱类型定型〔中风险〕
- **范围（只做最高频热点，不全量替换）**：llm-repair `cluster`/`action`（反复 `.get("key")`）、orchestrator `page_translate` job、phase3-4 中间结构、core `segment_codec`。
- **做法**：为热点定义 typed struct（serde `Deserialize`）或 accessor helper，字段名编译期可查。
- **验证**：行为不变；减少 `.get(...).and_then(as_str)` 样板。

### B5-6 超长函数拆分〔中风险，需快照守护〕
实测文件行数：
- `chapter_skeleton/toc_semantics/mod.rs` `build_toc_semantics`：**807 行**（函数约 580 行 / 16 步）
- `fnm-phase4/ref_freeze/mod.rs` `build_frozen_units`：**958 行**（函数约 740 行 / 7 phase）
- `fnm-phase1/toc_structure.rs` `build_phase1_structure`：**526 行**（注意已被 B3 S1 改动，混入 LLM 接入逻辑）
- **做法**：按已有「步骤注释」边界抽子函数（每步一函数），状态用 struct 承载。
- **前置守护**：拆分前先为这些函数补端到端快照测试（输入→输出 JSON 逐字节），拆后比对一致。
- **范围控制**：phase4 `ref_freeze` 是 A 档，仅在必要时动；否则可缓。

### B5-7 records flatten〔最高风险，殿后〕
位置：`fnm-core/src/records.rs`，**6 份 Summary**（行 184/386/588/831/1247/1453）+ **6 份 Structure**（行 251/434/646/887/1311/1521），16+ 公共字段重复。
- **做法**：抽 `BaseSummary`/`BaseStructure`，用 `#[serde(flatten)] common: BaseSummary` 保持 JSON 平铺兼容。
- **最高风险**：直接关系 Python `asdict` 数据契约；flatten 若改变字段顺序/缺省，可能**静默破坏导出 JSON**。
- **强制前置**：先为 6×2 结构写 JSON 序列化快照测试（与当前输出逐字段比对），有快照守护才动手；任何字段差异即回退。
- **建议**：最后做或暂缓（决策点 1）。

---

## 3. DoD
- [ ] B5-9/10/2 完成，行为不变，测试稳定（消除弹性断言）。
- [ ] B5-1/6 有快照/parity 守护，JSON 与行为不变。
- [ ] B5-7 有 JSON 快照守护，或明确决定暂缓。
- [ ] `cargo clippy` 0 warning；多书实批回归（含导出）无差异。
- [ ] 每项独立小 PR，便于审查与回退。

---

## 4. 决策点（需拍板）
1. **B5-7（records flatten）**：做还是暂缓？（数据契约高风险，收益仅去重）
2. **B5-6**：是否含 phase4 `ref_freeze`（A 档，958 行）？
3. **B5 整体范围**：全做 6 项，还是只做低风险（B5-9/10/2）先交付？

---

## 执行结果（2026-05-30，commit 5c8aa20 / 5dd5fb2 / 256d7df）

| 项 | 状态 | 实现 / 说明 |
|---|---|---|
| B5-9 测试隔离 | ✅ 完成 | token_counter 合并单测 + 精确断言；BookType 补 enum 测试；config 抽 `default_fnm_model_pool`（修了原断言依赖默认环境、在用户 custom pool 下误判的真问题）|
| B5-10 性能 nit | ✅ 部分 | `all_rules()` → const 数组；continuation/segment_codec/note_marker 经评估按「不为重构而重构」跳过 |
| B5-2 重复收敛 | ✅ 核心 3 对 | `extract_json_block`（3→`llm_json.rs`）、`extract_context`（2→`link_utils`）合并；`candidate_source_score` 两处分值体系不同→注释防误合并（§12）。余简单对留待 |
| B5-1 弱类型 | ✅ 代表热点 | `build_fnm_body_unit_jobs` 的 `paragraph_rows`：`Vec<Value>` → typed `ParagraphRow`，7 处 `.get` 变字段访问。其余热点留待 |
| B5-6 超长函数拆分 | ✅ 轻量 | toc_semantics 抽 step 11/12/15；ref_freeze 抽 Phase 2。**核心阶段状态/借用交织，全拆会参数爆炸/生命周期复杂，按发现的真实复杂度留待深拆**（见 commit 5dd5fb2）|
| B5-7 records flatten | ⏸ 缓 | 决策点 1 = 暂缓（数据契约高风险）|

**验证**：6 crate lib 589 passed / 0 failed；clippy 0 warning；phase1/phase4 集成 parity（真实书数据）守护拆分行为不变。

**留待单独 PR**：B5-2 余简单对（safe_int/compute_body_bounds/build_chapter_by_page/looks_like_*）、B5-1 其余热点（llm-repair prompt_builder/action）、B5-6 核心阶段深拆、B5-7 records flatten。
