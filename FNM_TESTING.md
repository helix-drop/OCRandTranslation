# FNM 测试与取证手册

本文说明当前 FNM 主链的测试入口、数据来源、输出产物和适用边界。以下命令均假定当前目录是仓库根目录 `/Users/hao/OCRandTranslation`。修复规则或判断 blocker 时，先选择正确的数据层，再运行对应脚本；不要用诊断输出替代验收结果。

**当前暂停边界（2026-05-26 更新）：** 实施顺序按 `fnm_re_rs/FNM_REPAIR_MASTER_PLAN.md` 的原阶段体系执行，阶段 5 的程序合同已通过无模型复制库回放完成验收。进入阶段 6 前，只编写并确认计划；在用户重新授权前，不执行真实整批、视觉检查或真实 repair。`fnm_re_rs/FNM_REPAIR_PROGRAM_CONTRACT_PLAN.md` 仅为问题盘点，不是实施入口。

## 判断顺序

| 要回答的问题 | 应使用的入口 | 依据 |
|---|---|---|
| 某个 phase 的规则修复是否成立 | Rust/Python 定向测试 + `test_fnm_incremental.py` | fresh pipeline 结果 |
| 当前书能否完整跑通真实视觉和修补链路 | `test_fnm_real_batch.py` | 当次批跑报告、trace、导出状态 |
| 导出内容是否与人工底本段对段一致 | `fnm_semantic_golden.py` | `real_golden_template` 派生的可追溯 JSONL |
| 某页、某 marker 或某次 LLM 请求为何出错 | `inspect_page.py`、trace、DB 查询 | 页面和阶段中间证据 |
| ZIP 内部合同是否闭合、能否交付 | `audit_fnm_exports.py --full` | export audit 的 `can_ship` |

必须遵守以下口径：

1. `test_example/<folder>/golden_exports/real_golden_template/` 是人工内容底本，只读，不由脚本回写。
2. `semantic_golden_v1.jsonl` 是由底本单向生成、供程序比对的派生数据；允许重建，但不得以当前 Rust/DB 输出反向更新底本。
3. 当前阶段允许正文为 `[待翻译]` 占位符。对照工具会将含占位符章节标为“文本未比较但当前允许”，不能据此宣称正文已与底本相等。
4. `Module Phase 3` 是 Phase 3 gate 的判定来源；持久化 readback 可能受 Phase 4 冻结/重新打开 link 影响。
5. 被 `#[ignore]` 跳过的 parity 测试不构成通过；要判断差异必须显式运行 ignored tests。
6. 每次判断产物前核验时间戳。旧的报告或 ZIP 不能作为当前代码的结论。

## 快速选择

| 类别 | 入口 | 是否调用真实模型 | 主要输出 | 能否作阶段验收 |
|---|---|---:|---|---:|
| 定向单测 | `pytest` / `cargo test -p ...` | 否 | 测试输出 | 是，针对修改范围 |
| 增量推进 | `scripts/test_fnm_incremental.py` | 仅 `--repair` 时调用 repair | 终端输出、可选 checkpoint | 是，phase gate |
| 常规批测 | `scripts/test_fnm_batch.py` | 不调用真实翻译，写测试占位译文 | `output/fnm_batch_test_result.{json,md}` | 是，非真实模型集成 |
| 下游回放 | `scripts/test_fnm_downstream_replay.py` | 否 | `output/fnm_downstream_replay/<tag>/` | 是，限 Phase4-6 改动 |
| 真实整批 | `scripts/test_fnm_real_batch.py` | 真实视觉 TOC + 真实 LLM repair | `output/fnm_real_batch/<tag>/` 与单书产物 | 当前暂停；恢复集成验收后使用 |
| 段落底本对照 | `scripts/fnm_semantic_golden.py` | 否 | JSONL 底本与 DB 对比报告 | 是，内容对照层 |
| 导出审计 | `scripts/audit_fnm_exports.py --full` | 否 | `output/fnm_book_audits/` | 是，导出合同层 |
| 页面定位 | `scripts/inspect_page.py` / `scripts/vision_page_check.py` | 视觉检查时调用 | `/tmp/fnm_inspect/` 或终端 JSON | 否，仅取证 |
| 修补实验 | `scripts/run_fnm_llm_repair.py` / `scripts/run_fnm_llm_tier1a.py` | 真实 LLM repair | JSON / Tier 1a 报告 | 否，须再走批测 |
| 旁路导出 | `scripts/force_export_and_compare.py` | 视重跑过程而定 | 测试 ZIP、status | 否，明确绕过 gate |

## 批跑与阶段验收

### 常规批测：`test_fnm_batch.py`

用途：清理并重跑 pipeline，写入测试占位译文，重建导出并检查脚注/尾注与导出审计合同。它适合检查主链和导出逻辑，不覆盖真实视觉 TOC、真实 LLM repair 的网络行为。

```bash
# 默认 manifest 批次
.venv/bin/python scripts/test_fnm_batch.py

# 单书、指定分组或数据库全部文档
.venv/bin/python scripts/test_fnm_batch.py --slug Biopolitics
.venv/bin/python scripts/test_fnm_batch.py --group baseline
.venv/bin/python scripts/test_fnm_batch.py --all-docs
```

参数：`--group default|baseline|extension|all`、`--slug`、`--all-docs`、`--limit`、`--output`。

默认产物：

| 产物 | 内容 |
|---|---|
| `output/fnm_batch_test_result.json` | 每本书各步骤和最终状态 |
| `output/fnm_batch_test_result.md` | 人可读批测报告 |
| `test_example/<folder>/latest.fnm.obsidian.zip` | 放行导出包 |
| `test_example/<folder>/latest_export_status.json` | 导出状态与新鲜度依据 |

### 真实整批：`test_fnm_real_batch.py`

用途：执行真实视觉目录识别、真实 LLM repair、占位翻译和导出验证；用于阶段交付与跨书回归。全量批跑时间长时应等待完整结束，不因耗时而跳过。

```bash
# 单书阶段验收
.venv/bin/python scripts/test_fnm_real_batch.py --slug Biopolitics --batch-tag phase3_biopolitics
.venv/bin/python scripts/test_fnm_real_batch.py --slug Goldstein --batch-tag phase3_goldstein

# manifest 全组验收
.venv/bin/python scripts/test_fnm_real_batch.py --group all --include-all --batch-tag phase3_all
```

参数：`--slug`、`--folder`、`--doc-id`、`--group baseline|extension|all`、`--include-all`、`--limit`、`--skip-translation`、`--batch-tag`、`--verbose`。

`--skip-translation` 会跳过占位翻译步骤，不应在需要验证最终导出装配的交付验收中启用。默认占位译文在当前阶段是允许状态。

产物分为批次和单书两层：

| 目录/文件 | 内容 |
|---|---|
| `output/fnm_real_batch/<batch_tag>/runtime_status.json` | 正在运行的阶段进度 |
| `output/fnm_real_batch/<batch_tag>/results.json` | 本批每书结果及 freshness 信息 |
| `output/fnm_real_batch/<batch_tag>/token_summary.json` | 请求/模型 token 统计 |
| `output/fnm_real_batch/<batch_tag>/batch_report.md` | 批次汇总 |
| `test_example/<folder>/FNM_REAL_TEST_REPORT.md` | 单书报告，使用前需查时间戳 |
| `test_example/<folder>/fnm_real_test_{progress,result,modules}.json` | 单书阶段产物 |
| `test_example/<folder>/llm_traces/` | 视觉和 repair 请求/响应 trace |

真实整批用于验证真实视觉/repair 调用链或最终内容交付，不应作为每次程序合同修正的默认动作。当前按程序逻辑顺序审查时，Phase1-3 的 P0/P1 修复先用对应 Rust 测试和复制诊断库验证；完成整条合同复核、需要刷新模型调用证据时，再运行 Biopolitics 与 Goldstein 两本真实整批。仅修改 Phase4-6 且已有可接受的 Phase1-3 DB 时，先按下节执行不耗模型配额的下游回放。

### 下游回放：`test_fnm_downstream_replay.py`

用途：当改动只涉及 Phase4-6 时，从已有验收 DB 复制 Phase1-3 落库事实，只回放 Rust 冻结、合并和导出审计；回放后在复制库写入测试占位译文并执行翻译后导出检查。不调用视觉目录或 LLM repair，不消耗模型配额，也不改写源数据库。

```bash
.venv/bin/python scripts/test_fnm_downstream_replay.py --tag phase5_acceptance

# 仅以 Phase4 引用冻结/翻译单元合同决定退出状态（阶段 5 收尾口径）
.venv/bin/python scripts/test_fnm_downstream_replay.py \
  --tag phase5_contract_closeout_20260526_v3 \
  --phase4-contract-only
```

默认回放 Biopolitics 与 Goldstein。脚本用 SQLite 一致性快照复制源 DB，并为每本书启动隔离 worker，避免 WAL 内容或跨书连接生命周期影响证据。报告位于 `output/fnm_downstream_replay/<tag>/results.json`，并在每本书目录保存复制后的 `doc.db` 与 `result.json`。

报告有两个不可混用的判定字段：

| 字段 | 用途 | 判定内容 |
|---|---|---|
| `phase4_contract_passed` | 阶段 5 程序合同验收 | 上游摘要不变、生成 translation units、无 `freeze_matched_ref_not_injected` |
| `passed` | Phase4-6 完整下游观察 | 另含占位翻译与 `export_ready_real` 等后续放行结果 |

使用 `--phase4-contract-only` 时，进程退出状态由 `phase4_contract_passed` 决定；完整回放的 `passed` 仍写入报告供阶段 6 定位，但不得拿它否定已通过的阶段 5。

此入口不能替代真实模型调用验证或最终内容验收。若回放揭示 Phase1-3 已持久化事实存在程序合同缺陷，应回到相应 phase 修复并按顺序复核；不应仅因已知内容差异立刻启动真实整批。

### 文档库前置条件

FNM 的批测、回放和 repository 定向验证都以应用已经导入的文档 `doc.db` 为输入。该数据库必须含有应用维护的 `documents` 与 `pages` 表及 raw page 数据；Rust FNM migration 只负责创建和更新 `fnm_*` 流水线产物表，不负责凭空生成 OCR 页面。由此产生的“空 FNM migration DB 无 raw page 可读”不是 pipeline blocker，真正需要报告的是在已有文档输入上读取失败、吞错或阶段产物损坏。

## 增量推进

### `test_fnm_incremental.py`

用途：修某一 phase 时冻结已确认结果，快速查看 fresh module 输出与 DB 落库结果。它不是替代真实整批的交付手段。

```bash
# 跑完整 pipeline，不调用 LLM repair
.venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics

# 只推进到某 phase，并保存检查点
.venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics --run-phase 3 --checkpoint

# 只读已有数据；或清除从 Phase 3 开始的派生结果
.venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics --check
.venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics --reset-from 3

# 对残余 orphan 调用真实 LLM repair
.venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics --repair --verbose
```

参数：`--slug` 为必填且可逗号分隔多书；另有 `--repair`、`--check`、`--run-phase 0..6`、`--checkpoint`、`--reset-from`、`--verbose`。

判断口径：

| 数据 | 用途 |
|---|---|
| `Module Phase 2/3` snapshot | Phase 2/3 当前规则是否通过的权威结果 |
| SQLite `fnm_note_items` / `fnm_body_anchors` / `fnm_note_links` | 后续持久化、冻结和导出链的输入 |
| `fnm_dev_snapshots` / `fnm_phase_runs` checkpoint | 已确认阶段的回溯点 |

## 段落底本对照

### `fnm_semantic_golden.py`

用途：把人工 Markdown 底本转为可流式读取、仍保留原文定位的 JSONL，并将 DB 中的当前导出/章节正文与底本作段对段对照。此工具是刚新增的内容真相对照入口。

不可修改的根底本：

| 书 | 根底本目录 | 派生 JSONL |
|---|---|---|
| Biopolitics | `test_example/Biopolitics/golden_exports/real_golden_template/` | `test_example/Biopolitics/golden_exports/semantic_golden_v1.jsonl` |
| Goldstein | `test_example/post-revolutionary/golden_exports/real_golden_template/` | `test_example/post-revolutionary/golden_exports/semantic_golden_v1.jsonl` |

```bash
# 只从人工底本生成/刷新派生 JSONL
.venv/bin/python scripts/fnm_semantic_golden.py build --slug Biopolitics
.venv/bin/python scripts/fnm_semantic_golden.py build --slug Goldstein

# 对 DB 的最终导出层做段落对照
.venv/bin/python scripts/fnm_semantic_golden.py compare-db --slug Biopolitics --layer export
.venv/bin/python scripts/fnm_semantic_golden.py compare-db --slug Goldstein --layer export

# 定位差异发生在 markdown 合并层还是更上游页面层
.venv/bin/python scripts/fnm_semantic_golden.py compare-db --slug Biopolitics --layer markdown
.venv/bin/python scripts/fnm_semantic_golden.py compare-db --slug Biopolitics --layer body-pages
```

参数：`compare-db` 支持 `--db-path`、`--layer export|markdown|body-pages`、`--report`、`--max-mismatches`。默认报告写到 `output/fnm_golden_compare/<slug>_<layer>_db_report.json`。

比对规则：

| 规则 | 处理方式 |
|---|---|
| 法语重音等轻微字符差异 | 规范化后允许 |
| 正文中的 `[待翻译]` | 当前阶段接受，但记录为未执行正文一致性判断 |
| 脚注标记未识别而移到页末段 | 仅当已从 `raw_pages.json` 验证为同一页且位于该页最后正文段时允许 |
| 其它缺段、多段、顺序错位、引用/定义错位 | 报失败，并保留底本原文和 DB 路径供反查 |

`body-pages` 是上游定位证据，不是最终验收 gate：页面片段尚不等同于合并后的最终段落。

旧的 `scripts/golden_paragraph_diff.py` 只提供基于相似度的段落辅助函数，不保存足以向前追溯的底本证据；新的验收应使用 `fnm_semantic_golden.py`。

## 导出与新鲜度

### `audit_fnm_exports.py`

用途：审计 ZIP/导出 bundle 的正文引用、定义闭合和导出阻断问题。

```bash
# 抽样报告
.venv/bin/python scripts/audit_fnm_exports.py --slug Biopolitics

# 逐文件全量审计，作为导出层验收
.venv/bin/python scripts/audit_fnm_exports.py --slug Biopolitics --full
.venv/bin/python scripts/audit_fnm_exports.py --group all --full
```

`--full` 的报告写到 `output/fnm_book_audits/<slug>.{json,md}`，以 `can_ship=true` 且 `blocking_issue_count=0` 为放行条件。未加 `--full` 时，默认输出是 `output/fnm_extension_export_audit.{json,md}`。

### `fnm_golden_freshness.py`

这是供 golden/导出对比调用的新鲜度检查模块，不是独立批测入口。它用 `latest_export_status.json`、ZIP 修改时间与 SQLite 最新 `fnm_run` 比较；产物早于最新 run 时必须拒绝继续对照。

## 定位与修补支撑工具

| 脚本 | 用途 | 输出/注意事项 |
|---|---|---|
| `inspect_page.py` | 按 slug 渲染具体 PDF 页并调用视觉模型核对 marker/标题 | `/tmp/fnm_inspect/`；可加 `--no-vision` 只导数据 |
| `vision_page_check.py` | 按 `doc_id` 与页码执行针对性视觉核查 | 适合现象确认，不替代 pipeline |
| `reingest_fnm_from_snapshots.py` | 从 `test_example` 的 raw/TOC 快照重注入 DB | 默认复用快照；`--rerun-auto-toc` 才重新调用视觉目录 |
| `run_fnm_llm_repair.py` | 对单文档 unresolved cluster 发 repair 请求 | 用于定位/试修；自动应用后可 rebuild |
| `run_fnm_llm_tier1a.py` | 多书 repair 效果实验与报告 | 输出 `output/tier1a_runs/<tag>/`，不跑导出 |
| `run_sup_recovery.py` | 上标恢复 POC 测量 | 仅专项诊断，不是主链 gate |
| `force_export_and_compare.py` | 跳过结构检查强制产生测试 ZIP | 明确不能作为验收结果 |

常用页面定位命令：

```bash
.venv/bin/python scripts/inspect_page.py --slug Biopolitics --page 104
.venv/bin/python scripts/inspect_page.py --slug Goldstein --page 160 --range 3
.venv/bin/python scripts/inspect_page.py --slug Biopolitics --page 104 --compare 111
.venv/bin/python scripts/inspect_page.py --slug Biopolitics --page 104 --no-vision
```

## 自动化测试文件

### Python 测试

| 测试范围 | 文件/命令 | 说明 |
|---|---|---|
| 新段落底本工具 | `tests/unit/test_fnm_semantic_golden.py` | 锁定只读底本、原文追溯、允许差异和占位符口径 |
| 批跑脚本与报告 | `tests/unit/test_fnm_batch_report.py`、`test_fnm_real_batch_report.py`、`test_fnm_real_batch_runtime.py`、`test_fnm_incremental_script.py` | 锁定脚本输出和运行态 |
| 导出审计与快照重注入 | `tests/unit/test_audit_fnm_exports.py`、`test_reingest_fnm_from_snapshots.py` | 锁定支撑工具 |
| Python/Rust 主链集成 | `tests/integration/test_fnm_re_mainline_biopolitics.py`、`test_fnm_real_mode.py`、`fnm_re_rs/fnm-py/tests/` | 锁定绑定和端到端行为 |

```bash
.venv/bin/python -m pytest \
  tests/unit/test_fnm_semantic_golden.py \
  tests/unit/test_fnm_incremental_script.py \
  tests/unit/test_fnm_real_batch_report.py \
  tests/unit/test_fnm_real_batch_runtime.py \
  tests/unit/test_audit_fnm_exports.py -q
```

### Rust 测试

| crate | 重点 |
|---|---|
| `fnm-core` | 类型、marker、repository、Phase 2/3 与 Phase 5/6 落库合同 |
| `fnm-llm-repair` | 请求/错误解析与 repair 集成 |
| `fnm-phase1` / `fnm-phase2` | TOC 与注释捕获 parity/spec |
| `fnm-phase3` | anchor/link/spec 与 Biopolitics parity |
| `fnm-phase4` / `fnm-phase5` / `fnm-phase6` | 冻结、markdown 合并、导出及审计 |
| `fnm-orchestrator` / `fnm-py` | 串行编排与 Python 边界 |

```bash
# 修改所在 crate 的快速验证
cargo test --manifest-path fnm_re_rs/Cargo.toml -p fnm-phase3 --test test_phase3_spec

# 主链完整 Rust 回归
cargo test --manifest-path fnm_re_rs/Cargo.toml --all

# 显式查看目前仍被忽略的 Phase 3 parity 差异；失败表示差异尚未修好
cargo test --manifest-path fnm_re_rs/Cargo.toml -p fnm-phase3 --test biopolitics_phase3_parity -- --ignored
```

## 交付流程

| 修改范围 | 开发过程中 | 交付前必须完成 |
|---|---|---|
| Core / Phase 1/2/3 程序合同 | 按顺序运行对应 Rust spec 与复制库诊断；差异报告只用于定位 | P0/P1 合同闭合并留证；不要求当前轮清空 `semantic_golden` 内容差异 |
| 真实视觉/LLM repair 接线 | 对应 crate/bridge 测试与受控请求 trace | Biopolitics 与 Goldstein 真实整批，自然结束并保留 trace |
| Phase 4-6 合并/导出合同 | crate 定向测试 + 下游回放 | 上游合同已复核时跑两书复制库回放且无本层 blocker |
| 阶段 7 内容/发布验收 | `semantic_golden` 定位与人工复核 | 两书真实整批、导出审计、允许项以外逐段对照通过 |
| Python bridge/批跑脚本 | 对应 `pytest` + PyO3 build/test | 仅下游回放桥接改动时用两书下游回放；改变真实批跑或模型调用时用受影响书真实整批 |

不应作为通过证明的内容：

- 历史 `FNM_REAL_TEST_REPORT.md` 或未验证 freshness 的旧 ZIP。
- 被 `#[ignore]` 跳过的 parity 测试。
- `body-pages` 单层对照结果。
- `run_sup_recovery.py`、Tier 1a 或强制导出脚本的成功输出。
- 以程序当前输出来重写人工 `real_golden_template` 的结果。
