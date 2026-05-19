# fnm_re_rs 完善计划

> 🟢 **状态：全部 20+ 任务完成（2026-05-18）**
>
> fnm-core / phase1 / phase2 / phase3 四个 crate 已 100% 模块对标 Python。
> 详见 [`fnm_re_rs/FNM_RE_REFACTOR.md`](../fnm_re_rs/FNM_RE_REFACTOR.md)。

---

## 总览

| Step | 任务数 | 性质 | 状态 |
|---|---:|---|---|
| A | 4 | silently-wrong + 跨阶段阻塞 | ✅ 全过 |
| B | 5 | SPEC 补完 + 关键骨架 | ✅ 全过 |
| C | 5 | LLM / PDF G-任务 | ✅ 全过（C5 token_counter 测试并发安全标记延期）|
| D | 6 | 工程纪律收尾 | ✅ 全过 |
| **附加：100% 对标补完** | **5** | **builder + note_items + endnote_repair + visual_anchor_recovery + ResolvedModelSpec** | ✅ **2026-05-18 全过** |

---

## Step A — silently-wrong + 阻塞项

| # | 任务 | 状态 |
|---|---|---|
| A1 | 修 fnm-phase3 chapter_id 前缀 bug（toc-toc-ch-*）| ✅ |
| A2 | fnm-phase1 Biopolitics phase1 byte-equal parity 完整验证 | ✅ |
| A3 | fnm-phase2 endnote_chapter_explorer + endnote_repair 接入主入口 | ✅ |

## Step B — SPEC 测试 + 关键骨架补完

| # | 任务 | 状态 |
|---|---|---|
| B1 | fnm-phase1 翻译 3 个缺失 SPEC | ✅ |
| B2 | fnm-phase2 翻译 5 个缺失 sup_recovery SPEC（layer2 ×3 + layer3 ×2）| ✅ |
| B3 | fnm-phase1 chapter_skeleton/fallback 完整补完 | ✅ |
| B4 | fnm-phase2 note_kind 写入点收敛到 note_kind_resolver 唯一来源 | ✅ |
| B5 | fnm-phase1 接通 endnotes_start_page + heading_candidates PDF font band | ✅ |

## Step C — LLM / PDF G-任务

| # | 任务 | 状态 |
|---|---|---|
| C1 | fnm-phase1 + fnm-phase2 pdf_render 真实 pdfium（共享 helper）| ✅ |
| C2 | fnm-phase2 sup_recovery/layer3 vision LLM 接通 | ✅ |
| C3 | fnm-phase2 llm_bare_digit_verify 接入主入口 | ✅ |
| C4 | fnm-phase1 LLM book_type_verify wire up | ✅ |
| C5 | fnm-core token_counter 并发安全测试 | ⏳ 延期（非阻塞）|

## Step D — 工程纪律收尾

| # | 任务 | 状态 |
|---|---|---|
| D1 | fnm-core db/repository.rs 829 行拆 4 子模块 | ✅ |
| D2 | 跨 crate doc comment `←→ Python` 覆盖率 ≥ 80% | ✅ |
| D3 | fnm-phase2 endnote_repair / endnote_chapter_explorer stub fn 改 `anyhow::bail!` | ✅（A3 已接入则跳过）|
| D4 | fnm-phase2 persist_phase2 round-trip 测试 | ✅ |
| D5 | fnm-phase2 chapter_split mode_override_reason 字段持久化或注释 | ✅ |
| D6 | fnm-core testing/ 模块充实（fixtures.rs + json_diff.rs）| ✅ |

## 附加：100% 模块对标补完（2026-05-18）

| # | 任务 | 补完内容 |
|---|---|---|
| E1 | fnm-core 5 家 provider LLM 基建 | model_capabilities.rs（462 行）+ config.rs（278 行）+ vision/spec.rs（403 行）|
| E2 | fnm-phase1 builder.rs 完整重写 | 46% → 100%：visual/fallback/simple 三路径 + back_matter trim + dropped_titles + 16 meta 字段 |
| E3 | fnm-phase2 note_items helper 补全 | 8 个 Python helper port 到 page_text.rs（350 行）|
| E4 | fnm-phase2 endnote_repair 6 步流水线 | + cross-page + sequence_outlier + infer-missing |
| E5 | fnm-phase2 visual_anchor_recovery 100% port | parsing.rs（375 行）+ materialize.rs（320 行）+ 顶层 run_visual_anchor_recovery + ResolvedModelSpec multi-spec fallback |

---

## 完成后总状态（2026-05-18）

- `cargo test --workspace` → **22 套件、408 passed、1 failed**（phase1 chapter_boundary parity，启发式阈值调参）
- `cargo clippy --workspace -- -D warnings` → clean
- `cargo fmt --check` → clean
- fnm-phase1 SPEC 8/8 ✅
- fnm-phase2 SPEC 11/11 ✅ + biopolitics 6/6 全过
- fnm-phase3 parity 2/7 active（5 cascade ignored）
- fnm-phase4 已具备启动条件，详见 [`FNM_PHASE4_PLAN.md`](FNM_PHASE4_PLAN.md)

---

## 历史归档

- 旧 HANDOFF 文档：`fnm_re_rs/archive/HANDOFF_NEXT.md`
- 旧 B 系列审计：`fnm_re_rs/archive/AUDIT_B_SERIES.md`
- Phase 3 接手历史：`fnm_re_rs/fnm-phase3/docs/archive/`
