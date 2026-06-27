# fnm_re_rs 历史档案

本目录归档已过期的阶段性文档。当前真实状态见 [`../FNM_RE_REFACTOR.md`](../FNM_RE_REFACTOR.md)。

| 文件 | 用途 | 归档原因 |
|---|---|---|
| `HANDOFF_NEXT.md` | Step A 完成后的下一步派单 | 后续 Step B/C/D + 100% 模块对标补完已全部落地，HANDOFF 流程结束 |
| `AUDIT_B_SERIES.md` | B 系列 + A 系列 审计说明 | 所列 stub（sup_recovery layer2 / endnote_chapter_explorer 20% / endnote_repair 37% / B3 fallback 5% / role_heuristics）已在 2026-05-18 完整 port 到 100% |
| `audit_round1_2/`（34 份） | 两轮审计报告（24）+ 全部修复执行计划/记录（10） | 审计发现的 B1-B4 + B3 LLM 接入 + B5 质量（含 B5-10 性能项）已全部修复落地（2026-05-31 核实）；仅 2 项纯可读性重构刻意搁置（见下） |

### `audit_round1_2/` 明细（34 份）

**审计报告（24）**
- **第 1 轮（12，2026-05-22~29）**：`FNM_{CORE,PHASE1-6,LLM_REPAIR,ORCHESTRATOR,PY}_AUDIT.md` + `FNM_AUDIT_SUMMARY.md` + `FNM_AUDIT_REMEDIATION_PLAN.md`（已被第 2 轮取代）。
- **第 2 轮（12，2026-05-30）**：`FNM_*_AUDIT2.md`（10 个 crate）+ `FNM_AUDIT2_SUMMARY.md` + `FNM_AUDIT2_REMEDIATION.md`。

**修复执行计划/记录（10，2026-05-29~31）**
- `FNM_REMEDIATION_PLAN_00_MASTER.md`~`06`（总纲 + B1-B5 分批）+ `FNM_B3_REMAINING_PLAN.md` + `FNM_B5_REMAINING_PLAN.md` + `FNM_B5_DEFERRED_PLAN.md`。
- **结案状态**：B1 panic/数据、B2 死代码、B3 LLM 验证接入、B4 逻辑契约、B5 质量（含 B5-10 性能：note_marker O(n²)→O(n)、continuation 整页 clone→borrow、segment_codec 冗余分支）**均已落地并验证**。

**唯一刻意搁置的 backlog（未做，非遗漏）**
- **B5-6 核心函数深拆**（`build_toc_semantics` step 1-10、`ref_freeze` Phase 1/3/5/6）：纯可读性收益，需「借用→索引」改写（高风险），决策为「将来需改这两个函数功能时顺带做」。现成方案见 `FNM_B5_DEFERRED_PLAN.md` §2c。
- **B5-7 S3 Structure 层 flatten**：仅 24 行去重、各 Structure 的 summary 类型不同，收益过低跳过。见 `FNM_B5_DEFERRED_PLAN.md` §1.6。

> 这些文档以**文件名**互相引用（如「审计依据：\`FNM_CORE_AUDIT2.md\` C-2」），均在本目录内，原本就无可点击链接、不存在失效问题。
> `fnm_re_rs/` 根目录已不再保留任何审计/修复文档（仅余重构总纲 `FNM_RE_REFACTOR.md` 与 `FNM_REPAIR_PHASE6_MERGE_EXPORT.md`）。

**新接手 Phase 4 的人**：直接看 [`../../FNM_RE/FNM_PHASE4_PLAN.md`](../../FNM_RE/FNM_PHASE4_PLAN.md)，不需要读本目录任何文件。
