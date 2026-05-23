# FNM Rust 修复总领计划

创建时间：2026-05-22
修订时间：2026-05-23
适用目录：`/Users/hao/OCRandTranslation/fnm_re_rs`

本文是交接总入口。接手人应先读本文，再读当前阶段文件和相应审计文件。当前工作的首要目标不是一次性消灭每一个识别差异，而是把 Rust FNM pipeline 修成**职责边界可信、错误可追溯、可继续推进完整流程**的实现；待 Phase1-6 的数据流和验收链闭合后，再集中收敛逐段 parity、弱 OCR 和版面细节差异。

## 一、修复目标与优先级

### 1. 总领性目标

本轮重构解决两类问题：

1. **流程级代码质量问题**：下游重建或覆盖上游事实、类型分类来源不唯一、错误被静默吞掉、测试只验证非空而不验证契约、batch 证据无法追溯。
2. **造成错误结果的确定性 bug**：例如非法 `note_kind` fallback、Phase3 把 `Unknown` 匹配成脚注、endnote contract 混入 footnote marker、repair 后结果未被后续 phase 消费。

### 2. 缺陷分级

修复时按下表排序，不允许为了让报表变绿而跳层修补。

| 等级 | 定义 | 当前处理方式 |
|---|---|---|
| P0 结构性错误 | 破坏 phase 职责、改写上游事实、把未知/失败伪装成成功、contract 统计混流、导致证据不可信 | 当前阶段必须修；不修不得进入下游阶段 |
| P1 流程闭合错误 | repair/续跑/持久化/导出审计未消费真实结果，或 blocker 归属不清 | 在对应阶段修；必须有可复现实测 |
| P2 细节正确性差异 | OCR 弱标记识别、逐段 count/parity 数量差、容忍规则边缘 case、个别版面提取差异 | 保留可追溯失败证据；完整流程固定后集中收敛 |
| P3 工程清理 | 既有 clippy `too_many_arguments`、无行为影响 warning、文档整理 | 不掩盖 P0/P1；有余力时处理或归档 |

### 3. 当前不可妥协的规则

1. Phase N 只能消费 Phase N-1 的事实，不能重建或覆盖上游事实。
2. `note_kind` 只能由 Phase2 对每个 note item 决定；Phase3 及后续不得用 chapter 聚合属性重分类。
3. `Unknown` 表示未证实的类型，只能留在 review/orphan 路径，不能成为普通 `Matched` 的依据。
4. blocker 必须由产生问题的 phase 报出；下游不能通过 fallback 把 blocker 消失。
5. 修 bug 先增加能重现问题的测试，再改实现。
6. 禁止逐书硬编码、扩大黑名单、从 actual 输出反写 expected golden。
7. P2 差异可以延后修，但必须保留失败测试、报告和回溯数据；不得宣称已经通过 parity。

## 二、背景与资料入口

### 1. 审计文件

以下文件记录最初审计结论，作为定位风险的入口；实际完成情况必须以新测试与新批跑证据为准：

- `FNM_AUDIT_SUMMARY.md`
- `FNM_CORE_AUDIT.md`
- `FNM_PHASE1_AUDIT.md`
- `FNM_PHASE2_AUDIT.md`
- `FNM_PHASE3_AUDIT.md`
- `FNM_PHASE4_AUDIT.md`
- `FNM_PHASE5_AUDIT.md`
- `FNM_PHASE6_AUDIT.md`
- `FNM_LLM_REPAIR_AUDIT.md`
- `FNM_ORCHESTRATOR_AUDIT.md`
- `FNM_PY_AUDIT.md`

阶段执行文件：

- 阶段 1：`FNM_REPAIR_PHASE1_FOUNDATION.md`
- 阶段 2：`FNM_REPAIR_PHASE2_NOTE_CAPTURE.md`
- 阶段 3 收尾：`FNM_REPAIR_PHASE3_LINKING.md`

测试工具说明位于仓库根目录 `FNM_TESTING.md`。

### 2. 最初实测问题来源

2026-05-22 的 Biopolitics 真实全量实测使用：

- 真实 LLM repair API
- 模型 `gemini-3.1-flash-lite`
- 占位符翻译
- 产物目录：`/Users/hao/OCRandTranslation/output/fnm_real_batch/biopolitics_gemini31_full_20260522_rerun3/phase_artifacts/Biopolitics`

该轮直接暴露 Phase2 `endnote_region_marker_misalignment`：尾注序列误收 `1769`、`1944`、`6768`、`1977`、`631` 等数字。这个问题已经推动阶段 1/2 修复；它是历史起点，不是当前阶段 3 的未完成判定。

## 三、截至 2026-05-23 的状态

| 阶段 | 状态 | 已确认结果 | 下一步意义 |
|---|---|---|---|
| 阶段 1：基础设施与可复现性 | 已验收 | DB/error trace/PyO3 panic 边界/Gemini custom provider/`NoteKind::Unknown` 等已修，Biopolitics smoke 可产出 artifacts | 不重复返工，除非后续发现回归 |
| 阶段 2：注释捕获与分类 | 已验收 | Biopolitics 与 Goldstein 完整批次均 `ready`、`blocked=0`；Goldstein Notes 第 331 页存在；Biopolitics 使用了 repair，Goldstein 为 0 repair | Phase2 事实作为 Phase3 权威输入 |
| 阶段 3：链接匹配边界 | **未完成** | 已有部分实现与测试，但审阅确认仍有 P0 缺陷；被 ignore 的真实 parity 当前明确失败；没有新的阶段 3 双书验收批次 | 当前接手重点 |
| 阶段 4-6 | 未开始正式验收 | 审计已有风险条目 | 待阶段 3 的结构边界封住后推进 |
| 阶段 7：最终 parity 与质量门禁 | 未开始 | 最终逐段相等、ignored 清零和完整发布门禁尚未完成 | 在整体流程闭合后集中完成 |

阶段 2 已确认的批跑证据：

| 书 | 目录 | 结论 |
|---|---|---|
| Biopolitics | `/Users/hao/OCRandTranslation/output/fnm_real_batch/phase2_note_capture_v2/` | `ready`，`blocked=0`，LLM repair 请求 20 |
| Goldstein | `/Users/hao/OCRandTranslation/output/fnm_real_batch/phase2_note_capture_v2_goldstein/` | `ready`，`blocked=0`，endnotes 第 331 页，LLM repair 请求 0 |

阶段 3 当前核验结论见 `FNM_REPAIR_PHASE3_LINKING.md`。关键事实是：

- `fnm-phase3/tests/biopolitics_phase3_parity.rs` 仍有 5 个真实 parity 测试被 ignore；显式执行 ignored tests 时 5 个均失败。
- `fnm-phase3/src/note_linking/chapter_contracts.rs` 当前只把 `def_anchor_mismatch` 的 count 分离，marker sequence / marker gap 仍混合 footnote 与 endnote。
- `fnm-phase3/src/footnote_links.rs` 当前仍允许 `AnchorKind::Unknown` 被星号直配和 OCR repair 转成普通脚注 `Matched`。
- “Phase3 不修改 Phase1/2 facts”的现有 SPEC 只验证字段有值，不足以证明等值透传。

## 四、Golden 与问题追溯原则

### 1. 根底本

最终内容正确性的人工确认底本只包括：

- Biopolitics：`/Users/hao/OCRandTranslation/test_example/Biopolitics/golden_exports/real_golden_template/`
- Goldstein：`/Users/hao/OCRandTranslation/test_example/post-revolutionary/golden_exports/real_golden_template/`

这些 Markdown 文件不可由 Rust、DB、ZIP、批跑结果或测试程序反写。

### 2. 派生比较数据

为适配 DB/Rust 比较与低内存流式读取，可从根底本单向生成：

- `test_example/Biopolitics/golden_exports/semantic_golden_v1.jsonl`
- `test_example/post-revolutionary/golden_exports/semantic_golden_v1.jsonl`

每条记录必须保留完整 expected 原文、来源文件、段序号、引用证据和 hash。这样对比失败后可以从最终段落回溯到 source-bearing 中间层，再定位到具体 phase。

### 3. 比较容忍范围

- 正文原则上必须段对段一一对应。
- 可容忍 Unicode 重音组合形式与空白规范化差异。
- 脚注引用只能在有同页原始证据且 actual 落在该页末正文段时，容忍“挂到页面最后一段”。
- 本阶段批跑允许翻译为 `[待翻译]`；占位翻译不属于正文内容差异，但章节覆盖、原文追溯链和结构事实仍必须核查。

### 4. 当前阶段如何使用失败结果

在阶段 3-6 流程尚未闭合时，P2 级逐段/parity 失败可以作为**待收敛诊断清单**保留，不自动阻断进入下一职责阶段。以下情况仍属于 P0/P1，不能后置：

- 失败证明 Phase3 改写了 Phase2 的 `note_kind` 或事实记录。
- 失败来自 Unknown 被伪装为 Matched。
- 失败来自跨章 recovery、contract 类型混流或不可注入 link 被标成功。
- 失败使后续 phase 无法判断真实 blocker 来源。

## 五、验证与批跑规则

### 1. 开发迭代

每次修改先运行受影响 crate 的重现测试和局部验证，不反复支付真实 API 全量批成本：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo fmt --check
cargo test -p <affected-crate> <new-regression-test-name>
cargo test -p <affected-crate>
```

涉及跨 phase contract 时补跑直接消费者 crate 的相关测试。

### 2. Python 与 PyO3

- 只有修改 Python 文件时，才把 `py_compile` 作为该轮必需检查。
- 只有准备让 Python 载入新的 Rust 动态库进行集成或阶段批跑时，才运行 PyO3 rebuild。

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs/fnm-py
../../.venv/bin/python -m maturin develop
```

### 3. 阶段交付全量批

影响业务输出的阶段在收尾前仍必须运行 Biopolitics 与 Goldstein 完整批次。批次启动后不能因耗时而中止，必须等待正常结束或明确错误落盘。

全量批的作用按阶段区分：

| 时点 | 批跑目的 | 是否要求逐段最终相等 |
|---|---|---|
| 阶段 3-6 收尾 | 证明本阶段结构性修复未导致新 blocker，记录剩余问题归属 | 不要求一次性清空已归档的 P2 细节差异 |
| 阶段 7 最终验收 | 证明完整流程和内容质量均可交付 | 要求根底本语义比较通过，除明确容忍项外逐段对应 |

最低证据：

- `runtime_status.json` 显示自然完成或明确错误。
- `results.json`/`batch_report.md` 列出 status 与 blocker。
- `token_summary.json` 记录本轮模型调用，即使为 0。
- 对本阶段影响的结构保存可核验的 modules/DB 导出/report 路径与生成时间。

当前批测脚本不保证自动创建 `phase_artifacts/`；不得把目录是否存在误当作通过条件。若本阶段专门改了归档/埋点功能，才将对应 artifact 作为新增门禁。

## 六、阶段路线图

### 阶段 1：基础设施与可复现性（已验收）

目标是让 DB、错误、trace、批测入口和 Python/Rust 边界可信。阶段 1 记录见 `FNM_REPAIR_PHASE1_FOUNDATION.md`；后续只处理新发现的回归。

### 阶段 2：Phase2 注释捕获与分类（已验收）

目标是让 `NoteRegion`、`NoteItem.note_kind`、`ChapterNoteMode` 成为可消费的事实。阶段 2 记录见 `FNM_REPAIR_PHASE2_NOTE_CAPTURE.md`；其双书 ready 结果是阶段 3 的输入基线。

### 阶段 3：Phase3 链接匹配边界收尾（当前阶段）

**必须本阶段解决的 P0：**

- endnote contract 的 sequence/gap/first-marker 判断不能混入 footnote definitions。
- footnote matching 与 OCR repair 不能把 `Unknown` 升格为普通成功匹配。
- Phase3 对 Phase1/2 facts 的保留必须用真正的字段等值/序列化等值测试固定。
- recovery、override、paragraph output 的边界测试必须能证明不跨章、不跨类型、不重新分类。

**已经实现但需通过回归守住的行为：**

- orphan unknown anchor 输出 `NoteKind::Unknown`。
- gap recovery 有 chapter scope 守卫。
- paragraph footnote/endnote 路径使用 Phase2 item 作为分类来源。
- synthetic footnote 不再直接伪装成可注入 `Matched`。
- OCR repair loop3 有同章守卫。

**允许后置到阶段 7 的 P2：**

- Biopolitics 当前内部 Phase3 fixture 的全字段/全数量 parity 差异，前提是失败仍被保留且不被覆盖 golden 隐藏。
- 弱 bare digit / symbol OCR 消歧的细节提升。
- 由根底本语义比较发现、但不证明 phase 职责错误的单段内容差异。

详细执行计划见 `FNM_REPAIR_PHASE3_LINKING.md`。

### 阶段 4：Orchestrator、PyO3 与 LLM repair 接线闭合

目标：repair auto-apply 后，本轮 Phase4-6 消费更新后的 link table；续跑不可用时明确拒绝，不静默假跑。

重点文件：

- `fnm-orchestrator/src/mainline.rs`
- `fnm-orchestrator/src/pipeline.rs`
- `fnm-orchestrator/src/post_translate.rs`
- `fnm-py/src/lib.rs`
- `FNM_RE/__init__.py`
- `fnm-llm-repair/src/actions.rs`
- `fnm-llm-repair/src/apply.rs`

必须解决：

- repair 后 materialize 最新 Phase3 输出并继续下游。
- action/cluster 身份校验与 partial-write 状态。
- unsupported `start_phase` 明确报错。
- 不允许 Phase3.5 新建或重分类 Phase2 note item。

细节识别差异不在本阶段扩大修复范围。

### 阶段 5：Phase4 引用冻结与翻译单元

目标：普通 `Matched` link 必须可注入正文；不能注入则形成明确 Phase4 blocker。

重点文件：

- `fnm-phase4/src/ref_freeze.rs`
- `fnm-phase4/src/units/`
- `fnm-phase4/tests/biopolitics_phase4_parity.rs`

必须解决：

- 唯一权威 ref-freeze 路径。
- 注入失败/UTF-8 offset 错误形成可追溯 blocker，不 panic 或静默丢标记。
- 翻译单元从 frozen units 派生。

### 阶段 6：Phase5/Phase6 合并与导出审计边界

目标：Phase5 仅生成章节 Markdown，Phase6 仅组书、打包和审计。

重点文件：

- `fnm-phase5/src/`
- `fnm-phase6/src/book_assemble/`
- `fnm-phase6/src/export_audit/`

必须解决：

- Phase5 不重建 chapter/note mode 或反向依赖 Phase6 contract。
- Phase6 对真实 ZIP bytes 做 gate，不修正文内容。
- `can_ship=true` 只能来自所有结构门禁通过。

### 阶段 7：内容 parity、细节收敛与发布门禁

目标：在职责边界固定后，处理先前归档的 P2 差异并完成最终业务验收。

必须完成：

- 对根底本运行 Biopolitics 与 Goldstein 的逐段语义比较；只保留明确容忍项。
- 对仍有价值的 internal phase fixture parity 解开 ignore 并修复差异，或经过人工审查将其替换为从根底本导出的明确 contract fixture。
- 处理弱 OCR/bare digit/symbol 等细节清单，每项附 source 页面和回归测试。
- 完整 workspace 质量门禁和双书全量实批。

最终命令至少包括：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo build --release
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --all

cd /Users/hao/OCRandTranslation
.venv/bin/python scripts/fnm_semantic_golden.py compare-db --slug Biopolitics --layer export
.venv/bin/python scripts/fnm_semantic_golden.py compare-db --slug Goldstein --layer export
.venv/bin/python scripts/test_fnm_real_batch.py --slug Biopolitics --group all --include-all --verbose
.venv/bin/python scripts/test_fnm_real_batch.py --slug Goldstein --group all --include-all --verbose
```

## 七、接手人现在应做什么

当前不要重新生成 golden，也不要先做 Phase4。按以下顺序接手阶段 3：

1. 读 `FNM_REPAIR_PHASE3_LINKING.md` 的“当前未完成结论”和“必须修复包”。
2. 先为 contract 混流、Unknown 成功匹配、上游 facts 等值保留增加会失败的回归测试。
3. 修 Phase3 代码直到这些 P0 测试与现有局部测试通过。
4. 保留当前 internal parity 和语义 golden 的失败报告，把剩余 P2 逐项登记，不覆盖底本、不弱化断言。
5. PyO3 rebuild 后完整跑两书阶段 3 集成批，记录新 blocker 是否属于 Phase3。
6. 只有 P0/P1 Phase3 blocker 清空，才进入阶段 4；P2 细节问题带着证据进入阶段 7 backlog。

交接记录必须回答三件事：修复了哪些职责边界、哪些失败被明确后置及其证据路径、当前是否允许进入下一阶段。
