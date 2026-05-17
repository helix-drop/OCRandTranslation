# fnm_re_rs 完善计划（fnm-core / phase1 / phase2）

**目的**：在 Phase 4 启动前补完 fnm-core / phase1 / phase2 的所有剩余工作。共 20 个任务，分 4 个 Step 串行执行。

**派单方式**：单 AI dev 顺序执行。每个任务对应一份 `fnm_re_rs/HANDOFF_NEXT.md` 详细 brief。完成一个 → 更新本文件勾选 + 重写 HANDOFF_NEXT.md 派下一个。

**Session size 含义**（替代「天」单位）：
- **S**：单文件改动，<100 LOC，1 session 内完成
- **M**：跨 2-3 文件，100-300 LOC，1-2 session
- **L**：跨多文件 + 测试，300-700 LOC，2-3 session
- **XL**：架构性改动，>700 LOC 或多模块接线，3+ session

---

## 总览

| Step | 任务数 | 性质 | 必须完成才能进下一 Step |
|---|---:|---|---|
| A | 4 | silently-wrong + 跨阶段阻塞 | ✅ 必须（不解这些 phase3 parity 永远不真） |
| B | 5 | SPEC 补完 + 关键骨架 | ✅ 必须（业务功能完整性） |
| C | 5 | LLM / PDF G-任务 | 🟡 可与 B 并行（需 vision API key） |
| D | 6 | 工程纪律收尾 | 🟢 推荐做完再启 Phase 4 |

---

## Step A — silently-wrong + 阻塞项（最高优先级）

| # | 任务 | Size | 状态 |
|---|---|---|---|
| **A1** | 修 fnm-phase3 chapter_id 前缀 bug（重跑 phase3 ignored parity 暴露：rust=`toc-ch-1` vs python=`toc-toc-ch-1`） | S | ⏳ **当前任务** |
| A2 | fnm-phase1 Biopolitics phase1 byte-equal parity 完整验证（F12） | M | ⬜ |
| A3 | fnm-phase2 endnote_chapter_explorer + endnote_repair 接入主入口（F8，核心 cascade 根因） | XL | ⬜ |

**已确认无需做**：原 A1「records.rs 5 个 `_xxx` 字段破 parity」是 false positive——Python `models.py:501-528` 全有对应字段，Rust 用 `rename = "_xxx"` 严格对齐输出，不破 parity。

**Step A 完成后**：跑 `cargo test -p fnm-phase3 --test biopolitics_phase3_parity -- --ignored` 验真 phase3 cascade 是否消除。

## Step B — SPEC 测试 + 关键骨架补完

| # | 任务 | Size | 状态 |
|---|---|---|---|
| B1 | fnm-phase1 翻译 3 个缺失 SPEC（biopolitics_toc_gate / manual_override_recorded / visual_toc_export_candidate_default） | M | ⬜ |
| B2 | fnm-phase2 翻译 5 个缺失 sup_recovery SPEC（layer2 ×3 + layer3 ×2） | L | ⬜ |
| B3 | fnm-phase1 chapter_skeleton/fallback 完整补完（F4-fallback，16% → 100%） | XL | ⬜ |
| B4 | fnm-phase2 note_kind 写入点收敛到 note_kind_resolver 唯一来源（CLAUDE.md §12 第 1 条） | L | ⬜ |
| B5 | fnm-phase1 接通 endnotes_start_page + heading_candidates PDF font band | M | ⬜ |

## Step C — LLM / PDF G-任务

| # | 任务 | Size | 状态 |
|---|---|---|---|
| C1 | fnm-phase1 + fnm-phase2 pdf_render 真实 pdfium（G1，两 crate 共享 helper） | L | ⬜ |
| C2 | fnm-phase2 sup_recovery/layer3 vision LLM 接通（G2） | M | ⬜ |
| C3 | fnm-phase2 llm_bare_digit_verify 接入主入口（G4） | S | ⬜ |
| C4 | fnm-phase1 LLM book_type_verify wire up（G5） | M | ⬜ |
| C5 | fnm-core token_counter 并发安全测试 | S | ⬜ |

**注：visual_anchor_recovery 接入（G3）需 phase3 反向喂入 body_anchors——留到 phase3 完成后做，不放本计划**

## Step D — 工程纪律收尾

| # | 任务 | Size | 状态 |
|---|---|---|---|
| D1 | fnm-core db/repository.rs 829 行拆 4 子模块（按 phase） | M | ⬜ |
| D2 | 跨 crate doc comment `←→ Python` 覆盖率提升到 ≥ 80% | L | ⬜ |
| D3 | fnm-phase2 endnote_repair / endnote_chapter_explorer stub fn 改 `anyhow::bail!`（若 A3 已接入则跳过） | S | ⬜ |
| D4 | fnm-phase2 persist_phase2 round-trip 测试 | S | ⬜ |
| D5 | fnm-phase2 chapter_split mode_override_reason 字段持久化或注释「仅日志」 | S | ⬜ |
| D6 | fnm-core testing/ 模块充实（fixtures.rs + json_diff.rs） | S | ⬜ |

---

## 完成后总状态

完成全部 20 任务后预期：

- `cargo test --workspace -- --include-ignored` 全过（含 phase3 parity）
- fnm-phase1 SPEC 8/8 ✅
- fnm-phase2 SPEC 11/11 ✅
- fnm-phase3 parity 5/5 ✅
- 所有 src 文件 ≤ 400 LOC 或带 `// SPLIT-EXEMPT` 注释
- doc comment 覆盖率 ≥ 80%
- 0 业务 `let _ = ...`，0 静默 stub
- 准备好启动 **Phase 4: 翻译单元 + frozen refs**（参考 `RUST_MIGRATION_PLAN.md` Step 4 段）

---

## 派单流程

1. 接手者读 `fnm_re_rs/HANDOFF_NEXT.md` 拿到当前任务详细 brief
2. 执行任务（含跑完所有验收命令）
3. 提 commit（消息格式见 HANDOFF brief 中的模板）
4. 在本文件勾选当前任务、更新「当前任务」标记到下一项
5. 重写 `fnm_re_rs/HANDOFF_NEXT.md` 派下一个任务
6. push main

**单任务原则**：一份 HANDOFF 只描述一个任务，完成即归档（重命名为 `fnm_re_rs/HANDOFF_<task_id>_done.md`）。
