# FNM_RE 完全 Rust 化 · 收尾计划

> 文档日期：2026-05-20
> 前置完成：18 个 commit（fnm-core/phase1-6/llm-repair/orchestrator/py 10 个 crate + FNM_RE/__init__.py 加 Rust 入口 + Biopolitics e2e 跑通 2.844s）
> 上一份计划：[`docs/FNM_PHASE5_PHASE6_PLAN.md`](../归档/FNM_RE/docs/FNM_PHASE5_PHASE6_PLAN.md)（已完成归档）

---

## 0. 项目背景（30 秒）

`fnm_re_rs/` 10 个 Rust crate 已完成 FNM_RE 核心 pipeline 1:1 翻译；
Python 端 `FNM_RE/__init__.py` 通过 pyo3 wheel `fnm-re-rs` 已能调用 Rust pipeline。

**遗留事实**：`FNM_RE/app/` 6535 行 Python 仍是生产路径——`web/translation/scripts` 共 17 个文件
通过 12 个旧公开 API（`run_doc_pipeline` / `run_llm_repair` / `build_doc_status` / ...）
调用 Python `app/`，进而调用 `modules/` / `stages/` / `shared/`。

**本计划目标**：在 fnm-py pyo3 端暴露这 12 个 API 的 Rust 等价 → 切换 17 个 caller → 归档 `app/` + 残余 Python pipeline 实现 → 让 FNM_RE 真正只剩 `__init__.py` + `dev/` + `README.md` 的薄壳。

---

## 1. 当前状态总览

### 1.1 Rust 端（10 crate · 940 tests）

| crate | 状态 | tests | 用途 |
|---|---|---:|---|
| fnm-core | ✅ 100% | 110 | 类型 / DB / 工具 |
| fnm-phase1 | ✅ 100% | 106 | TOC + chapter skeleton（chapter_boundary 12/12 byte-equal）|
| fnm-phase2 | ✅ 100% | 140 | note_regions + note_items + sup_recovery |
| fnm-phase3 | ✅ 100% | 26 | body_anchors + note_links（5 cascade tests ignored）|
| fnm-phase4 | ✅ 100% | 106 | ref_freeze + units + reviews |
| fnm-phase5 | ✅ 100% | 44 | chapter markdown merge |
| fnm-phase6 | ✅ 100% | 148 | export + audit + book_assemble |
| fnm-llm-repair | ✅ 100% | 121+39 | Step 3.5 LLM 修补 |
| fnm-orchestrator | ✅ MVP | 0 | pipeline 编排 + DB-driven + LLM repair 集成 |
| fnm-py | ✅ MVP | 0 | pyo3 binding（4 个 Python 函数）|

**测试**：940 lib + 6 biopolitics_phase4_parity + 8 spec + 12 phase2 / 27 phase1 集成 + 5 phase3 cascade ignored。

### 1.2 Python 端剩余（按归档可能性分类）

| 文件 | 行数 | 状态 | 外部依赖 |
|---|---:|---|---|
| `FNM_RE/__init__.py` | 250 | ✅ Rust 入口 + 旧 lazy-import 函数共存 | — |
| `FNM_RE/README.md` | 68 | ⚠️ 仍描述 Python 实现，待重写 | — |
| `FNM_RE/constants.py` | 70 | ⏳ 待归档（Rust types.rs 等价） | app/ 内部依赖 |
| `FNM_RE/models.py` | 670 | ⏳ 待归档（Rust records.rs 等价） | app/ 内部依赖 |
| `FNM_RE/app/mainline.py` | 1427 | ⏳ 待 port → 归档 | web/ 6 + translation/ 4 + scripts/ 7 |
| `FNM_RE/app/pipeline.py` | 1789 | ⏳ 待 port → 归档（已有 Rust orchestrator 等价） | 内部 |
| `FNM_RE/app/page_translate.py` | 880 | ⏳ 待 port → 归档 | translation/ |
| `FNM_RE/app/persist_helpers.py` | 313 | ⏳ 待归档 | 内部 |
| `FNM_RE/app/pipeline_converters.py` | 789 | ⏳ 待归档 | 内部 |
| `FNM_RE/app/mainline_repo.py` | 288 | ⏳ 待归档 | 内部 |
| `FNM_RE/app/status.py` | 748 | ⏳ 待 port | 内部 |
| `FNM_RE/app/db_reconstruct.py` | 276 | ⏳ 待归档 | 内部 |
| `FNM_RE/stages/` | ~3500 | ⏳ 跟 app 一起归档 | app/ |
| `FNM_RE/modules/` | ~6800 | ⏳ 跟 app 一起归档 | app/ |
| `FNM_RE/shared/` | ~2700 | ⏳ 跟 app 一起归档 | app/ + 部分外部直接 import |
| `FNM_RE/dev/` | ~2000 | ✅ **保留**（web/dev_routes + 10 测试 import） | 长期保留 |

**合计待归档**：约 **19,500 行 Python**（其中 `app/` 6535 + `stages/modules/shared` ~13,000）。

### 1.3 已归档（前期完成）

- `归档/FNM_RE/docs/`（8 个 *.md 历史规划/分析）
- `归档/FNM_RE/handoff/`（2 个 *.md 交接清单）
- `归档/FNM_RE/subprocess/`（4 个 subprocess_*.py，不再需要）
- 早期 PHASE plan：`FNM_COMPLETION_PLAN.md` / `FNM_PHASE1_PLAN.md` / `FNM_PHASE2_PLAN.md` / `FNM_PHASE3_PLAN.md` / `FNM_CORE_PLAN.md` / `FNM_PHASE12_*.md`

---

## 2. 总体目标

1. **fnm-py 暴露 12 个旧 Python API 的 Rust 等价**（M1）
2. **`web/` / `translation/` / `scripts/` 共 17 个 caller 切到 Rust binding**（M2）
3. **DB-driven 主入口补足**：从 SQLite `documents` / `raw_pages` / `visual_toc` 读输入（M3）
4. **归档 `FNM_RE/app/` + `stages/` + `modules/` + `shared/` + `constants/models`**（M4）
5. **`fnm-py` wheel 正式发布流程**（M5）

**最终态**：`FNM_RE/` 仅含 `__init__.py` + `README.md` + `dev/` + `NEXT_PHASE_PLAN.md`（本文档完成后归档）。

**附加目标**：
- P1 清 Rust warnings（phase1=6 / phase2=20 / phase4=11）+ 5 个 phase3 ignored cascade tests
- P2 fnm-py pytest e2e 套件 + shadow mode 完整 diff 工具

---

## 3. P0 任务分解（M1 → M5 拓扑序）

### M1：pyo3 暴露 12 个旧公开 API（关键路径）

12 个 API 按"是否已有 Rust 等价"分组：

#### M1.A：薄包装（Rust 已等价，只需 pyo3 adapter）— 估 2 天

| Python API | Rust 等价 | pyo3 adapter 工作量 |
|---|---|---|
| `run_doc_pipeline(doc_id, pdf_path, ...)` | `fnm_orchestrator::run_pipeline_for_doc` | 加 DB-based pages/toc load + 路径转换 |
| `load_doc_structure(doc_id)` | DB 读 phase1-6 表后组装 | 已有 Repository.list_fnm_* 方法 |
| `audit_export_for_doc(doc_id)` | `fnm_phase6::export_audit::audit_phase6_export` | 已有，DB 读 export_bundle |
| `build_export_bundle_for_doc(doc_id)` | `fnm_phase6::build_module_export_bundle` | 已有 |
| `build_export_zip_for_doc(doc_id)` | phase6 输出 export_zip bytes | 已有 |
| `list_diagnostic_entries_for_doc(doc_id)` | DB 读 fnm_diagnostic_pages | 已有 list 方法 |
| `list_diagnostic_notes_for_doc(doc_id)` | DB 读 fnm_diagnostic_notes | 已有 |
| `get_diagnostic_entry_for_page(doc_id, page_no)` | filter list_diagnostic_entries | trivial filter |

#### M1.B：独立调用入口（Rust 已有逻辑但只在 pipeline 内调用）— 估 1 天

| Python API | Rust 等价 | 工作 |
|---|---|---|
| `run_llm_repair(doc_id, slug, auto_apply)` | `fnm_llm_repair::run::run_llm_repair` | pyo3 暴露独立调用 + PyRepairRenderer 包装 |

#### M1.C：跨 SQLite-translation 桥接（Python 端有较多业务逻辑）— 估 2-3 天

| Python API | 复杂度 | 工作 |
|---|---|---|
| `build_doc_status(doc_id, ...)` | 748 行（FNM_RE/app/status.py） | 需 port build_phase4_status / build_phase6_status + StructureStatusRecord |
| `prepare_page_translate_jobs(pages, ...)` | 880 行（page_translate.py 主入口）| port 翻译任务调度 |
| `build_retry_summary(doc_id, ...)` | page_translate 内辅助 | 中等 |
| `build_unit_progress(doc_id, ...)` | page_translate 内辅助 | 简单 |
| `run_post_translate_export_checks_for_doc(doc_id)` | mainline 内辅助 | 中等 |

**M1 工时估计：5-6 天 single-developer。**

**M1 验收**：
- `fnm-py` 暴露 12 个新 pyo3 函数，签名与 Python 旧版兼容（参数 + 返回类型）
- `FNM_RE/__init__.py` 旧 lazy-import 函数改为薄包装 Rust 调用
- Biopolitics e2e 仍 byte-equal Python golden
- workspace 940 tests + 新增 pyo3 集成 tests 0 failed

### M2：caller 切换（mechanical）— 估 1-2 天

17 个文件需改 import 路径：

| 类别 | 文件 | 数量 | 工作 |
|---|---|---:|---|
| web/ | reading_routes / export_routes / translation_routes / dev_routes / services / reading_view | 6 | grep -r 替换 import |
| translation/ | service / translate_runtime / translate_worker_common / translate_worker_fnm | 4 | 同上 |
| scripts/ | onboard_example_books / test_fnm_incremental / inspect_page / apply_manual_toc_to_examples / run_sup_recovery / test_fnm_real_batch / audit_fnm_exports / force_export_and_compare | 7-8 | 同上 |
| tests/ | 暂保留 Python 实现作 fallback test ground，单独 mark | — | 后续 M4 时一并归档或保留 |

**关键事实**：M1 完成后 `FNM_RE.run_doc_pipeline` 等函数已经在 `__init__.py` 走 Rust 实现，
**caller 不需改 import**——直接复用现有签名即可。

**M2 工时估计：1-2 天**（含 web 端冒烟测试）。

**M2 验收**：
- web/ + translation/ + scripts/ 全部能正常启动，不依赖 Python `FNM_RE/app/`
- 6 个 web 路由 manual smoke：导入 PDF → pipeline → export ZIP 端到端
- scripts/test_fnm_real_batch.py 跑 1 本书通过

### M3：DB-driven 输入完善 — 估 1-2 天

当前 `fnm_orchestrator::run_pipeline_for_doc` 接受 caller 自备的 `raw_pages` + `toc_items`，
Python 端 `mainline.run_phase6_pipeline_for_doc` 是从 SQLite `documents` / `raw_pages` /
`visual_toc.manual_inputs` 读取后调用。

M3 工作：
- M3.1 在 fnm-orchestrator 加 `load_inputs_from_db(repo, doc_id) -> (Vec<RawPage>, Vec<TocItem>, PipelineConfig)`
- M3.2 暴露 `run_pipeline_for_doc_from_db(repo, doc_id)`——caller 只需 doc_id
- M3.3 fnm-py 加对应 pyo3 函数

**M3 验收**：调用 `fnm_re_rs.run_pipeline_from_db_json(db_path, doc_id)` 一行跑通整本书 e2e。

### M4：Python `app/` + `stages/` + `modules/` + `shared/` + constants/models 全归档 — 估 0.5-1 天

- M4.1 `git mv FNM_RE/{app,stages,modules,shared,constants.py,models.py}` → `归档/FNM_RE/python/`
- M4.2 `FNM_RE/__init__.py` 删除全部旧 lazy-import 函数（M1/M2/M3 后已无 caller）
- M4.3 重写 `FNM_RE/README.md` 仅描述 Rust binding 用法
- M4.4 `cargo test --workspace` + Python smoke test 验证无 regression

**M4 验收**：`FNM_RE/` 仅剩 `__init__.py` + `README.md` + `dev/` + 本计划文档（也归档）。

### M5：fnm-py wheel 发布流程 — 估 0.5-1 天

- M5.1 `.github/workflows/rust.yml` 加 maturin build job（macOS + linux aarch64 + linux x86_64）
- M5.2 `maturin build --release` 产出 wheel artifact
- M5.3 PyPI 发布 / 内部 wheelhouse 文档说明
- M5.4 用户面向 README：装 + 切 backend

**M5 验收**：CI 通过后产出 3 个 abi3 wheel；本机 `pip install dist/fnm_re_rs-*.whl` 一键装好。

---

## 4. P1 任务分解（代码质量，非关键路径，可并行）

### P1.1：清 Rust warnings — 估 0.5 天

```bash
cargo build --workspace 2>&1 | grep "warning:" | sort -u
# phase1=6 / phase2=20 / phase4=11 = 37 个
```

主要类别：
- dead code（never used const/fn/regex）
- unused mut
- unused fields

按 `cargo fix --lib -p fnm-phaseN` 半自动修，逐 crate verify 940 tests 不退步。

### P1.2：phase3 5 个 ignored cascade tests — 估 2-3 天（需追根因）

5 个 parity tests 被 `#[ignore]` 标记，等 phase2 cascade 修复：
- `biopolitics_phase3_body_anchors_parity`
- `biopolitics_phase3_chapter_contracts_parity`
- `biopolitics_phase3_note_links_parity`
- `biopolitics_phase3_summary_parity`
- 详见 [`known_python_bugs.md`](../fnm_re_rs/fnm-phase3/tests/known_python_bugs.md) §7

工作：逐个跑 ignore 测试，diff Python golden，定位 phase2 上游 cascade，按 CLAUDE.md §11 区分（数据统计 bug vs 模式过宽）。

### P1.3：PDFium binary 集成 — 估 0.5 天

`fnm-phase1::pdf_font::tests::empty_for_missing_pdf` ignored 等 PDFium binary。
- 加 PDFium bundled feature 到 fnm-core
- 或在 CI 安装 PDFium runtime

---

## 5. P2 任务分解（工程化，可推迟）

### P2.1：fnm-py pytest e2e 套件 — 估 1 天

替代 `smoke_test.py` ad-hoc 脚本：
- `fnm_re_rs/fnm-py/tests/test_pipeline_e2e.py` — 用 Biopolitics fixture 跑完整 6-phase + DB persist
- `tests/test_llm_repair_pyo3.py` — NoopRenderer + 真实 cluster
- `tests/test_shadow_mode.py` — env on/off

集成到 pytest + CI。

### P2.2：完整 Python ↔ Rust shadow diff 工具 — 估 1-2 天

当前 `run_with_shadow` 只跑 Rust + 写日志。完整 diff 需：
- 接受 Python `ModulePipelineSnapshot` 对象
- 把它转 dict（dataclasses.asdict 或手动）
- 与 Rust dict 逐字段 diff，按严重度（critical / warning / info）报告

`FNM_RE.compare_python_vs_rust_snapshots(py_obj, rust_dict) -> diff_report`

### P2.3：用户文档 — 估 0.5 天

重写 `FNM_RE/README.md`：
- 安装指南（maturin develop / pip install wheel）
- 4 个公开 API 的使用样例
- shadow mode 指南
- 故障排查

---

## 6. 验收 checklist（P0 全完成后）

- [ ] `cargo test --workspace` ≥ 940 passed / 0 failed
- [ ] `pip install dist/fnm_re_rs-*.whl` 一键装好
- [ ] `python -c "import fnm_re_rs; fnm_re_rs.run_pipeline_from_db_json('x.db', 'doc-id')"` 跑通
- [ ] `FNM_RE/` 只剩 4 个条目：`__init__.py` / `README.md` / `dev/` / `__pycache__/`
- [ ] `grep -r "from FNM_RE.app\|from FNM_RE.stages\|from FNM_RE.modules\|from FNM_RE.shared" --include="*.py" .` 返回 0 行（除归档/）
- [ ] Biopolitics e2e 12/12 chapter byte-equal Python golden（用归档前的 golden fixture）
- [ ] web/ 6 个路由 smoke 通过
- [ ] scripts/test_fnm_real_batch.py 跑 ≥3 本书通过
- [ ] `cargo clippy --workspace -- -D warnings` 0 warning

---

## 7. 依赖图

```
                    ┌───────────────────────┐
                    │  M1: pyo3 暴露 12 API │
                    │  (5-6 days)           │
                    └──────────┬────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
   ┌──────────────────┐ ┌─────────────┐ ┌───────────────────┐
   │ M2: caller 切换   │ │ M3: DB load │ │ P1.1: 清 warnings │
   │ (1-2 days)       │ │ (1-2 days)  │ │ (0.5 day)         │
   └──────────┬───────┘ └──────┬──────┘ └───────────────────┘
              └─────────┬──────┘
                        ▼
              ┌──────────────────────┐
              │ M4: 归档 app/ + ...  │
              │ (0.5-1 day)          │
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │ M5: wheel 发布       │
              │ (0.5-1 day)          │
              └──────────────────────┘

P1.2 (phase3 cascade) / P1.3 (PDFium) / P2.* 可并行
```

---

## 8. 工时估计汇总

| Milestone | 估计 | 关键路径 |
|---|---:|---|
| M1: pyo3 12 API | 5-6 d | ✓ |
| M2: caller 切换 | 1-2 d | ✓ |
| M3: DB-driven load | 1-2 d | ✓ |
| M4: 归档 | 0.5-1 d | ✓ |
| M5: wheel 发布 | 0.5-1 d | ✓ |
| **P0 合计** | **8-12 d** | — |
| P1.1: warnings | 0.5 d | 并行 |
| P1.2: phase3 cascade | 2-3 d | 并行 |
| P1.3: PDFium | 0.5 d | 并行 |
| **P1 合计** | **3-4 d** | 可与 P0 并行 |
| P2.1: pytest 套件 | 1 d | 并行 |
| P2.2: shadow diff | 1-2 d | 并行 |
| P2.3: 用户文档 | 0.5 d | 并行 |
| **P2 合计** | **2.5-3.5 d** | 可推迟 |

**single-developer full-time grand total**：
- 仅 P0：8-12 天（约 2 周）
- P0 + P1：11-16 天（约 3 周）
- P0 + P1 + P2：13-19 天（约 3-4 周）

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| M1.C 中 `build_doc_status` / `prepare_page_translate_jobs` Python 实现含隐式约束 Rust 漏译 | 中 | M2 caller smoke 失败 | 严格 snapshot diff，参考 P2.2 shadow tool |
| M2 caller 切换破坏 web 生产路径 | 中 | 生产中断 | 先在 staging 环境验证 1 周；保留 Python `FNM_RE/app/` 一份归档可回滚 |
| M3 SQLite schema 不一致 Rust 读不到 raw_pages | 低 | M1 全卡 | M3.1 先单独跑 schema validator |
| pyo3 cdylib 跨平台 build | 中 | M5 wheel 失败 | macOS arm64 已验证；linux x86_64 用 manylinux docker；windows 可选不发 |
| phase3 cascade 涉及 phase2 数据 bug | 中 | P1.2 拖延 | 标 known issue 不阻断 P0；专项 phase2 audit |

---

## 10. 下一步行动

按依赖图，**第一步是 M1.A（薄包装 8 个 API）**——大部分只需 pyo3 adapter + DB 读路径，不涉及新业务逻辑。

建议拆为 8 个独立 PR（每个 API 1 个），每个 PR 含：
1. 新 pyo3 函数（fnm-py/src/lib.rs）
2. `FNM_RE/__init__.py` 旧 lazy-import 改为 Rust 调用
3. 1 个 pytest 用例（用 Biopolitics fixture 跑过即可）
4. 验证 workspace 940 tests 仍 0 failed

每天合 1-2 个 PR，M1.A 约 1 周完成。然后 M1.B（1 天）+ M1.C（2-3 天）。

完整 P0 预期 2 周收官；M5 后此文档归档到 `归档/FNM_RE/docs/`。
