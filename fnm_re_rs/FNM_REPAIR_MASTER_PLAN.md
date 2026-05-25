# FNM Rust 修复总领计划

创建时间：2026-05-22
修订时间：2026-05-25
适用目录：`/Users/hao/OCRandTranslation/fnm_re_rs`

本文是交接总入口。接手人应先读本文，再读当前阶段文件和相应审计文件。当前工作的首要目标不是一次性消灭每一个识别差异，而是把 Rust FNM pipeline 修成**职责边界可信、错误可追溯、可继续推进完整流程**的实现；待 Phase1-6 的数据流和验收链闭合后，再集中收敛逐段 parity、弱 OCR 和版面细节差异。

**当前执行入口（2026-05-25）：** 接手实施者在读完本文后，应直接按 `FNM_REPAIR_PROGRAM_CONTRACT_PLAN.md` 执行。该文件覆盖 Core 至 Phase6 的当前顺序复核、文件级任务和“暂停真实批跑”边界；旧阶段文档中的完成状态和实批要求仅保留为历史证据。

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

### 4. 2026-05-25 起的程序逻辑审查口径

当前轮只收敛 **P0/P1 程序合同问题**，暂停用模型批跑推动识别细节调校，也不以逐段 golden 差异阻断中间 phase。检查必须从上游顺序推进：

| 顺序 | 模块 | 本轮只确认的程序合同 |
|---|---|---|
| 1 | `fnm-core` | 类型默认值、DB schema/API、序列化与坐标/文本工具不会伪造或丢失事实 |
| 2 | `fnm-phase1` | page/chapter 事实可落库、错误可见；不在本轮追求每一本书的标题识别齐全 |
| 3 | `fnm-phase2` | `note_kind` 分类来源唯一、region/item 不被下游覆盖 |
| 4 | `fnm-phase3` | link 不跨章抢占、不重复消费 anchor、公开输出与落库 ID 一致 |
| 5 | `fnm-llm-repair` 与 orchestrator/PyO3 | repair 错误/trace 可见、override 不越权、续跑消费最新事实 |
| 6 | `fnm-phase4` | matched 可注入或明确阻断；translation units 只由 frozen facts 派生 |
| 7 | `fnm-phase5` / `fnm-phase6` | 合并和导出只消费上游事实，审计不反向修正文 |

只有前一步的 P0/P1 合同已由定向测试或可追溯诊断确认后，才进入下一步。`semantic_golden` 仍保留为追溯工具与最终内容验收依据，但缺章、段落差异、弱 OCR marker 差异在当前轮均记为 P2 待办，不用于判定 Phase4/Phase5 程序合同失败。

### 5. `fnm-core` 输入库前置合同与当前复核状态

`fnm-core` 不是独立构造原始文档库的导入器。依据 `DEV.md`，每个应用文档的 `doc.db` 已由上游维护 `documents` 与 `pages` 输入表；FNM migration 负责的是 `fnm_*` 阶段产物表。因此 repository 读取页面/目录的方法以“已导入的文档 DB”为前置条件，不要求仅运行 FNM migration 就能产生 raw page 输入。

2026-05-25 在暂停测试后的静态复核结果：

| 合同项 | 现有代码证据 | 当前判定 |
|---|---|---|
| 空 `paragraphs` 的 segment 编解码不能丢顶层文本 | `fnm-core/src/segment_codec.rs` 已保存/读回 `source_text` 与 `display_text`，并有对应单测 | 静态无新 P0/P1 |
| 非法 `note_kind` 不能伪装成 footnote/endnote | repository 读回已回退到 `NoteKind::Unknown` | 静态无新 P0/P1 |
| row 级 DB 失败不能被静默跳过 | `load_raw_pages_for_doc()` 已传播 row error；非法 JSON skip 仍保留 warning 语义 | 静态无新 P0/P1 |
| `documents` 两种应用 schema 可写 | `upsert_document()` 已有 legacy/app 插入与更新测试 | 静态无新 P0/P1 |
| 空 enriched 文本与字符坐标不能破坏下游冻结 | `fnm-core/src/text.rs` 已包含 null fallback 与字符/字节索引转换 | 静态无新 P0/P1 |

用户已要求暂停测试，本轮没有重新执行上述测试。因此 Core 当前只能标记为“静态未发现新的 P0/P1，待恢复可执行验证”；在验证恢复前，不把 Phase1 及其下游宣称为已复核完成。

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
- 阶段 4：`FNM_REPAIR_PHASE4_ORCHESTRATOR.md`
- 阶段 5：`FNM_REPAIR_PHASE5_REF_FREEZE.md`

测试工具说明位于仓库根目录 `FNM_TESTING.md`。

### 2. 最初实测问题来源

2026-05-22 的 Biopolitics 真实全量实测使用：

- 真实 LLM repair API
- 模型 `gemini-3.1-flash-lite`
- 占位符翻译
- 产物目录：`/Users/hao/OCRandTranslation/output/fnm_real_batch/biopolitics_gemini31_full_20260522_rerun3/phase_artifacts/Biopolitics`

该轮直接暴露 Phase2 `endnote_region_marker_misalignment`：尾注序列误收 `1769`、`1944`、`6768`、`1977`、`631` 等数字。这个问题已经推动阶段 1/2 修复；它是历史起点，不是当前阶段 3 的未完成判定。

## 三、截至 2026-05-25 的状态

| 阶段 | 状态 | 已确认结果 | 下一步意义 |
|---|---|---|---|
| 阶段 1：基础设施与可复现性 | 历史验收存在；Core 静态复核待运行确认 | DB/error trace/PyO3 panic 边界/Gemini custom provider/`NoteKind::Unknown` 等已有实现与历史验证；本轮已明确应用输入库前置合同 | 恢复验证后先确认 Core，再进入 Phase1 |
| 阶段 2：注释捕获与分类 | 历史验收存在，待顺序复核合同 | 历史批次均曾 `ready`；后续追溯发现 region 边界会影响 Phase3/4 输入 | Core/Phase1 复核后再确认本层 P0/P1 |
| 阶段 3：链接匹配边界 | 重新打开程序合同核查 | 后续已确认存在 book-scope fallback 跨章匹配与公开 link ID 分叉，并已写修复 | Phase2 合同确认后复核修复，不以 parity 差异卡住 |
| 阶段 4：Orchestrator、PyO3 与 repair 接线 | 历史实施存在，待顺序复核合同 | repair 回写、错误边界与 bridge 存在候选改动；当前工作区又增加了下游回放入口，不能按旧结论跳过复核 | Phase3 确认后审查 repair 权限、同轮消费与回放状态重建 |
| 阶段 5：Phase4 引用冻结与翻译单元 | 程序合同候选闭合，待上游顺序复核后确认 | 单一冻结路径、freeze blocker 与无模型诊断已落地；刷新 Phase1-3 输出后的复制库诊断曾达到双书 `blocking=0` | 不用段落 parity 卡本层；待查到 Phase4 时复核合同 |
| 阶段 6 | 未开始正式验收 | Phase5/Phase6 职责倒挂等风险已登记 | 待阶段 5 闭合后推进 |
| 阶段 7：最终 parity 与质量门禁 | 未开始 | 最终逐段相等、ignored 清零和完整发布门禁尚未完成 | 在整体流程闭合后集中完成 |

阶段 2 已确认的批跑证据：

| 书 | 目录 | 结论 |
|---|---|---|
| Biopolitics | `/Users/hao/OCRandTranslation/output/fnm_real_batch/phase2_note_capture_v2/` | `ready`，`blocked=0`，LLM repair 请求 20 |
| Goldstein | `/Users/hao/OCRandTranslation/output/fnm_real_batch/phase2_note_capture_v2_goldstein/` | `ready`，`blocked=0`，endnotes 第 331 页，LLM repair 请求 0 |

阶段 3 已全部修复并完成双书集成批。详见 `FNM_REPAIR_PHASE3_LINKING.md` 交接记录。关键事实更新：

- 全部 P0 已在 2026-05-23 Build 阶段修复：contract 类型隔离、Unknown 拦截、upstream facts 等值透传（含 chapter_note_modes）、link_overrides 严格候选过滤。
- `fnm-phase3/tests/biopolitics_phase3_parity.rs` 的 5 个真实 parity 测试仍为 `#[ignore]`（保持严格断言），登记到阶段 7 backlog。
- `cargo test -p fnm-phase3`：39 passed, 0 failed, 2 ignored。
- Biopolitics 批次：`output/fnm_real_batch/phase3_linking_closeout/`，`ready`、无 blocker。
- Goldstein 批次：`output/fnm_real_batch/phase3_linking_closeout_goldstein/`，`ready`、无 blocker。

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

### 阶段 1：基础设施与可复现性（历史验收存在，Core 待运行复核）

目标是让 DB、错误、trace、批测入口和 Python/Rust 边界可信。阶段 1 记录见 `FNM_REPAIR_PHASE1_FOUNDATION.md`；当前先按新计划确认 Core 程序合同，再允许推进 Phase1。

### 阶段 2：Phase2 注释捕获与分类（历史批次通过，待顺序复核）

目标是让 `NoteRegion`、`NoteItem.note_kind`、`ChapterNoteMode` 成为可消费的事实。阶段 2 记录见 `FNM_REPAIR_PHASE2_NOTE_CAPTURE.md`；历史双书 ready 结果仅作证据，不能替代当前 Phase1/2 合同复核。

### 阶段 3：Phase3 链接匹配边界收尾（候选修复存在，重新打开复核）

**2026-05-23 曾形成交接记录；2026-05-25 追溯后不再按“已完成”处理。** 旧修复包仍需保留复核，并新增核查跨章 matched、重复 anchor 消费与 public/DB link ID 分叉。

**历史候选修复包：**

1. Contract 类型隔离：endnote sequence/gap/first-marker 使用 endnote-only 流（`chapter_contracts.rs`）。
2. Unknown 自动匹配拦截：星号直配与 OCR repair 要求 `AnchorKind::Footnote`（`footnote_links.rs`）。
3. upstream facts 等值保留：`Phase3Input` 新增 `phase2_chapter_note_modes` 字段；输出透传而非重建（`input.rs` / `lib.rs`）。
4. link_overrides 严格候选过滤：`find_existing_explicit_anchor` 排除 Unknown（`link_overrides.rs`）。

**复核时必须重新确认的边界：** gap recovery 章守卫、paragraph 分类来源、synthetic footnote 不伪装、OCR 跨章防护、endnote orphan recovery 不跨章、unknown orphan → `NoteKind::Unknown`。

**后置到阶段 7 的 P2：** Biopolitics internal Phase3 parity 差异（5 个 ignored 测试保持严格断言）；弱 OCR 消歧细节；根底本语义比较中的个段差异。

### 阶段 4：Orchestrator、PyO3 与 LLM repair 接线闭合（候选实现存在，待复核）

目标：repair auto-apply 后，本轮 Phase4-6 消费更新后的 link table；续跑不可用时明确拒绝，不静默假跑。

重点文件：

- `fnm-orchestrator/src/mainline.rs`
- `fnm-orchestrator/src/pipeline.rs`
- `fnm-orchestrator/src/post_translate.rs`
- `fnm-py/src/lib.rs`
- `FNM_RE/__init__.py`
- `fnm-llm-repair/src/run.rs`
- `fnm-llm-repair/src/override_materializer.rs`
- `fnm-llm-repair/src/response_parser.rs`

必须解决：

- repair 后 materialize 最新 Phase3 输出并继续下游。
- action/cluster 身份校验与 partial-write 状态。
- unsupported `start_phase` 明确报错。
- 不允许 Phase3.5 新建或重分类 Phase2 note item。

细节识别差异不在本阶段扩大修复范围。

历史计划与上下文入口见 `FNM_REPAIR_PHASE4_ORCHESTRATOR.md`。当前工作区已有对应候选改动；Phase3 确认后必须复核本阶段合同，若 Phase4 实施暴露接线回归，按本阶段职责归因，不在 freeze crate 内绕过。

### 阶段 5：Phase4 引用冻结与翻译单元（程序合同候选闭合，待顺序复核）

目标：普通 `Matched` link 必须可注入正文；不能注入则形成明确 Phase4 blocker。

重点文件：

- `fnm-phase4/src/ref_freeze.rs`
- `fnm-phase4/src/units/`
- `fnm-phase4/tests/biopolitics_phase4_parity.rs`

必须解决：

- 唯一权威 ref-freeze 路径。
- `BodyAnchorRecord` 坐标合同统一为 Python 字符索引：Rust Phase3 与 LLM repair 产出端写字符索引，Phase4 注入时转换为 UTF-8 字节边界；越界且无法回退的注入失败形成可追溯 blocker，不 panic 或静默丢标记。

2026-05-24 验收补充事实：

- 新增 `scripts/test_fnm_downstream_replay.py`，复制已验收的 Phase1-3 DB，只重跑 Rust Phase4-6；不调用视觉 TOC 或 LLM repair，且校验 Phase1-3 表未改写。
- 修复 `fnm-core/src/text.rs` 中 `enriched_markdown=null` 会屏蔽真实 `markdown` 的通用缺陷；否则所有正文单元为空。
- 修复 book-scope endnote link 以 note 归属章查找正文页的问题；注入位置改由 anchor 所属章决定，note 归属不被重分类。
- 当前最终回放产物 `output/fnm_downstream_replay/phase5_acceptance_final/results.json` 判定未通过：两书复制库均成功写入占位译文且模型请求为 0；Biopolitics 有 1 条 `token_not_found`；Goldstein 有 90 条 `token_not_found` 与 1 条 `coordinate_out_of_range`。该回放复用坐标修复前的 Phase1-3 数据，因此用于证明旧输入被可靠阻断，不用于证明新 Phase3 产物已刷新。Goldstein 样本已证实包含同一正文坐标对应两条 `matched` link 的 Phase3 残余断层。
- 验证显示 `cargo test --all` 与 `cargo build --release` 通过；并行全量测试暴露的 `fnm-llm-repair` trace dump 共享用量记录竞争已修复。`cargo clippy --no-deps -p fnm-phase4 -p fnm-phase6 --all-targets -- -D warnings` 已通过，阶段 5 范围内曾暴露的循环内编译正则等 lint 已清除。全 workspace 严格 clippy 仍被 `fnm-core`、`fnm-phase3`、`fnm-llm-repair` 与未由本轮修改产生的 `fnm-orchestrator` 债务阻断，应另行治理。
- 翻译单元从 frozen units 派生。

2026-05-25 重新归因：

- `phase5_rootfix_diagnostic_v4` 与 `v5` 是不调用模型的当前代码复制库诊断；两书在刷新上游结构/link 输出后均为 `blocking=0`，Goldstein 也不再存在跨章 matched 或重复 anchor 消费。这说明此前 Phase4 blocker 的主要原因在 Phase1/3 输入合同，不是 Phase4 门禁过严。
- `semantic_golden` 对照仍显示 Biopolitics 与 Goldstein 有缺章和大范围内容差异。这些差异是重要追溯证据，但属于后续内容质量/P2 阶段；不能反过来把 Phase4 引用冻结合同判为未闭合。
- 诊断过程中发现 Phase1 漏标题恢复尝试既属于内容调校，又曾写入 schema 不接受的 candidate source；该启发式已从当前改动中移除，留待阶段 7 按原页证据单独设计。

详细执行文件：`FNM_REPAIR_PHASE5_REF_FREEZE.md`。

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

## 七、接下来的工作

当前暂停模型批跑和内容调校。下一步按程序合同顺序：

1. 将 `FNM_REPAIR_PROGRAM_CONTRACT_PLAN.md` 作为实施主文档，从 `fnm-core` 开始核查现有改动与审计项，只处理 P0/P1：schema/API、默认类型、错误传播、文本/坐标合同。
2. Core 确认后进入 Phase1，再依次检查 Phase2、Phase3、LLM repair/编排边界、Phase4、Phase5、Phase6；不得从下游失败倒推后直接在下游放宽门禁。
3. 逐段 golden 差异、漏章节识别和弱 OCR marker 仍保留报告与原页证据，但移入阶段 7 内容收敛清单；当前不据此触发模型调用或逐书规则补丁。
4. 当前工作树中已有一次追溯期间加入的 Phase3 quoted bare-digit recovery 调整；到 Phase3 复核时必须重新判定：只允许修“弱/synthetic evidence 不得伪装为可注入 matched”的程序合同，不把具体排版启发式直接视为本轮验收成果。

当前不变规则：
- 不修改 `real_golden_template/`。
- 不用 Rust actual 覆盖 fixture。
- 5 个 parity ignored 测试保持严格断言，登记到阶段 7 backlog。
- `clippy::too_many_arguments` 作为工程债不挡阶段门禁。
