# FNM Rust 修复总领计划

创建时间：2026-05-22
修订时间：2026-05-26
适用目录：`/Users/hao/OCRandTranslation/fnm_re_rs`

本文是交接总入口。接手人应先读本文，再读当前阶段文件和相应审计文件。当前工作的首要目标不是一次性消灭每一个识别差异，而是把 Rust FNM pipeline 修成**职责边界可信、错误可追溯、可继续推进完整流程**的实现；待 Phase1-6 的数据流和验收链闭合后，再集中收敛逐段 parity、弱 OCR 和版面细节差异。

**当前执行入口（2026-05-26 更新）：** 本文定义的原阶段 1-7 是唯一实施顺序。**阶段 5：Phase4 引用冻结与翻译单元**已按程序合同闭合；下一步只能编写并确认阶段 6 计划，再实施 `fnm-phase5`/`fnm-phase6` 的职责问题。`FNM_REPAIR_PROGRAM_CONTRACT_PLAN.md` 仅保留为问题盘点记录，其中 A-H 编号不得替代原阶段编号。

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

当前轮只收敛**通过原阶段 5 所必需的 P0/P1 程序合同问题**，暂停用模型批跑推动识别细节调校，也不以逐段 golden 差异阻断阶段 5。发现阶段 6/7 问题时只登记，不提前改代码：

| 原阶段 | 模块 | 本轮处理边界 |
|---|---|---|
| 阶段 1 | `fnm-core` 及基础接线 | 仅保留会影响阶段 5 输入读取、文本坐标或回放可信性的修复 |
| 阶段 2 | `fnm-phase1` / `fnm-phase2` | 仅复核阶段 5 所消费的章节、region、item 事实 |
| 阶段 3 | `fnm-phase3` | 仅保留会造成冻结注入失败或伪 matched 的合同修复 |
| 阶段 4 | `fnm-llm-repair` / orchestrator / PyO3 | 仅保证阶段 5 消费已物化结果及无模型回放不伪造上游失败 |
| 阶段 5 | `fnm-phase4` 与 blocker 最小透传 | 已完成程序合同验收；内容差异不纳入本阶段 |
| 阶段 6 | `fnm-phase5` / `fnm-phase6` | 已发现职责倒挂、审计边界问题；下一步先编写计划，不由阶段 5 越界实施 |
| 阶段 7 | parity / 内容质量 | 只保留证据，整体流程固定后处理 |

`semantic_golden` 仍保留为追溯工具与最终内容验收依据，但缺章、段落差异、弱 OCR marker 差异在当前轮均记为 P2 待办，不用于判定阶段 5 的 Phase4 冻结合同失败。

#### 程序合同通过与业务内容通过的分界

当前阶段的“上游可用于验证”不等于“上游已经识别得完全正确”。Phase1-3 数据可进入阶段 5 程序验收，必须满足：

- 字段、坐标单位、类型和 owner 等事实可完整落库并由 Rust 严格读回。
- `Matched` link 不引用不存在的 note/anchor，不存在已知的跨章抢配、重复消费或 ID 分叉。
- 不确定判断继续以 `review_required`、`Unknown` 或 orphan 形式可见，不被下游覆盖为成功。
- Phase4 输入使用的是本轮新生成事实，不是合同修复前的污染数据。

以下现象本身不构成阶段 5 的 P0/P1 阻断：

- Phase2 产生 `review_required` 的章，但该标记被完整保留并且 Phase4 不据此重分类或伪造匹配。
- 章节缺漏、note 捕获数量差、weak OCR 标记差异或逐段 golden 不一致。
- 最终 export 尚未达到 `can_ship`，只要原因不来自 Phase4 冻结合同失败。

上述内容必须保留为后续追溯证据；只有证明程序改写事实、吞掉错误或制造错误成功状态时，才回到当前阶段阻断处理。

### 5. `fnm-core` 输入库前置合同与当前复核状态

`fnm-core` 不是独立构造原始文档库的导入器。依据 `DEV.md`，每个应用文档的 `doc.db` 已由上游维护 `documents` 与 `pages` 输入表；FNM migration 负责的是 `fnm_*` 阶段产物表。因此 repository 读取页面/目录的方法以“已导入的文档 DB”为前置条件，不要求仅运行 FNM migration 就能产生 raw page 输入。

2026-05-26 已恢复无模型验证并完成直接影响阶段 5 的 Core/持久化复核：

| 合同项 | 现有代码证据 | 当前判定 |
|---|---|---|
| 空 `paragraphs` 的 segment 编解码不能丢顶层文本 | `fnm-core/src/segment_codec.rs` 已保存/读回 `source_text` 与 `display_text`，并有对应单测 | 已验证 |
| 非法 `note_kind` 不能伪装成 footnote/endnote | repository 读回回退到 `NoteKind::Unknown` | 已验证 |
| Phase1/2/3 事实字段不能在落库读回后丢失 | repository/schema 已保存 heading、region、item、mode、anchor 合同字段，并新增 roundtrip/坏 JSON 测试 | 已验证 |
| 旧 byte anchor 坐标不能混入新 Phase4 | `coordinate_unit=char` 被持久化；非 `char` 读回明确失败 | 已验证 |
| 空 enriched 文本与字符坐标不能破坏下游冻结 | `fnm-core/src/text.rs` 已包含 null fallback 与字符/字节索引转换 | 已验证 |

本轮执行了 `cargo test -p fnm-core -p fnm-phase2 -p fnm-phase3 -p fnm-orchestrator --no-fail-fast` 与 `cargo fmt --check`，结果通过。该结论只覆盖程序合同，不宣称 Phase2 的内容识别已经完成调校。

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

## 三、截至 2026-05-26 的状态

| 阶段 | 状态 | 已确认结果 | 下一步意义 |
|---|---|---|---|
| 阶段 1：基础设施与可复现性 | 阶段 5 所需合同已复核 | 合同列持久化、严格读回、字符坐标和 DB 清理入口已有测试并通过 | 不再阻断阶段 5 |
| 阶段 2：注释捕获与分类 | 程序事实已重建；内容信号仍保留 | 新 DB 可严格读回 region/item/mode；Biopolitics 的 `review_required` 可见且未被掩盖 | 仅将内容调校移后，不阻断 Phase4 合同 |
| 阶段 3：链接匹配边界 | 阶段 5 所需合同已复核 | 新 DB 均无 matched 缺 note/anchor、无旧 byte 坐标；Phase3/消费方测试通过 | 可作为阶段 5 输入 |
| 阶段 4：Orchestrator、PyO3 与 repair 接线 | 无模型路径已复核 | PyO3 已重建；增量脚本修正为使用文档私有 DB；当前验证不调用 repair API | 可启动复制库 Phase4 验证 |
| 阶段 5：Phase4 引用冻结与翻译单元 | **程序合同完成** | 双书复制库报告 `phase4_contract_passed=true`；上游未改写、freeze blocker=0、模型请求=0 | 阶段 5 已关闭 |
| 阶段 6 | 未开始正式验收 | Phase5/Phase6 职责倒挂、`export_ready_real=false` 等风险已登记 | 编写阶段 6 详细计划后推进 |
| 阶段 7：最终 parity 与质量门禁 | 未开始 | 最终逐段相等、ignored 清零和完整发布门禁尚未完成 | 在整体流程闭合后集中完成 |

阶段 2 已确认的批跑证据：

| 书 | 目录 | 结论 |
|---|---|---|
| Biopolitics | `/Users/hao/OCRandTranslation/output/fnm_real_batch/phase2_note_capture_v2/` | `ready`，`blocked=0`，LLM repair 请求 20 |
| Goldstein | `/Users/hao/OCRandTranslation/output/fnm_real_batch/phase2_note_capture_v2_goldstein/` | `ready`，`blocked=0`，endnotes 第 331 页，LLM repair 请求 0 |

阶段 3 的历史 P0 修复和双书集成批证据见 `FNM_REPAIR_PHASE3_LINKING.md` 交接记录；本轮又以新 DB 和定向测试复核其中直接影响 Phase4 的程序合同。关键事实更新：

- 全部 P0 已在 2026-05-23 Build 阶段修复：contract 类型隔离、Unknown 拦截、upstream facts 等值透传（含 chapter_note_modes）、link_overrides 严格候选过滤。
- `fnm-phase3/tests/biopolitics_phase3_parity.rs` 的 5 个真实 parity 测试仍为 `#[ignore]`（保持严格断言），登记到阶段 7 backlog。
- `cargo test -p fnm-phase3`：39 passed, 0 failed, 2 ignored。
- Biopolitics 批次：`output/fnm_real_batch/phase3_linking_closeout/`，`ready`、无 blocker。
- Goldstein 批次：`output/fnm_real_batch/phase3_linking_closeout_goldstein/`，`ready`、无 blocker。

2026-05-26 阶段 5 前置数据刷新（不调用视觉或 repair 模型）：

| 书 | Phase1-3 新数据 | 程序合同核查 | 仅作后续内容证据 |
|---|---|---|---|
| Biopolitics | pages=370, chapters=13, regions=80, items=471, anchors=531, links=489 | 合同缺字段=0；非字符坐标=0；matched 缺实体=0；Phase4-6 已清空 | 11 章 `review_required`，保留供内容调校 |
| Goldstein | pages=431, chapters=9, regions=8, items=778, anchors=904, links=778 | 合同缺字段=0；非字符坐标=0；matched 缺实体=0；Phase4-6 已清空 | 章节/内容 parity 留后续判断 |

重生成前备份位于 `output/fnm_phase13_regen_backup/20260526_130612/`。上述 DB 是阶段 5 后续复制库回放的输入基线；不把历史 `ready` 报表或坐标修复前的回放结果当作新验收结果。

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

### 3. 程序合同交付与真实整批的边界

阶段 1-6 当前优先验证程序是否正确处理既有事实，不把“模型是否成功识别所有内容”混成代码合同门禁。因此阶段 5 收尾使用**双书复制库无模型回放**，不要求运行真实视觉 TOC 或真实 LLM repair：

| 时点 | 验证目的 | 使用入口 | 阻断依据 |
|---|---|---|---|
| 阶段 5 收尾 | 验证 Phase4 对新 Phase1-3 事实的冻结、unit 派生与 blocker 透传 | `scripts/test_fnm_downstream_replay.py`，但仅读取 Phase4 专属结论 | `freeze_matched_ref_not_injected`、上游被改写、单位派生合同失败 |
| 阶段 6 收尾 | 验证 Markdown 合并与导出审计职责 | 阶段 6 计划另定 | Phase5/6 自身 blocker |
| 阶段 7 最终验收 | 验证模型调用链与最终内容质量 | 双书真实整批 + semantic golden | 根底本语义比较及最终 gate |

`scripts/test_fnm_downstream_replay.py` 会为方便诊断继续执行 Phase5/6，并保留将 `export_ready_real` 纳入顶层 `passed` 的完整回放口径；它现已提供 `--phase4-contract-only` 与独立字段 `phase4_contract_passed`。脚本使用 SQLite online backup 制作含 WAL 提交内容的一致性副本，并将每本书放在独立 worker 进程执行，避免复制证据受连接生命周期污染。

阶段 5 最低证据：

- 回放复制 DB 的 Phase1-3 摘要在前后 byte/hash 不变。
- 两书 Phase4 `freeze_matched_ref_not_injected` 为 0；若非 0，必须列出 reason 和定位。
- translation units 来自 frozen units，已有定向测试通过且回放可生成 units。
- `model_requests=0`，证明该结论不依赖模型内容调校。

只有要验证真实模型接线或进入阶段 7 内容交付时，才启动真实整批；一旦启动，必须等待正常结束或明确错误落盘。

## 六、阶段路线图

### 阶段 1：基础设施与可复现性（历史验收存在，Core 待运行复核）

目标是让 DB、错误、trace、批测入口和 Python/Rust 边界可信。阶段 1 记录见 `FNM_REPAIR_PHASE1_FOUNDATION.md`；阶段 5 收尾期间只回看其中直接影响冻结输入或回放证据的合同。

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

### 阶段 5：Phase4 引用冻结与翻译单元（程序合同已完成）

目标：普通 `Matched` link 必须可注入正文；不能注入则形成明确 Phase4 blocker。

重点文件：

- `fnm-phase4/src/ref_freeze.rs`
- `fnm-phase4/src/units/`
- `fnm-phase4/tests/biopolitics_phase4_parity.rs`

必须解决：

- 唯一权威 ref-freeze 路径。
- `BodyAnchorRecord` 坐标合同统一为 Python 字符索引：Rust Phase3 与 LLM repair 产出端写字符索引，Phase4 注入时转换为 UTF-8 字节边界；越界且无法回退的注入失败形成可追溯 blocker，不 panic 或静默丢标记。

2026-05-24 验收补充事实：

- 新增 `scripts/test_fnm_downstream_replay.py`，复制符合程序合同的 Phase1-3 DB，驱动 Rust Phase4-6；不调用视觉 TOC 或 LLM repair，且校验 Phase1-3 表未改写。
- 修复 `fnm-core/src/text.rs` 中 `enriched_markdown=null` 会屏蔽真实 `markdown` 的通用缺陷；否则所有正文单元为空。
- 修复 book-scope endnote link 以 note 归属章查找正文页的问题；注入位置改由 anchor 所属章决定，note 归属不被重分类。
- 当前最终回放产物 `output/fnm_downstream_replay/phase5_acceptance_final/results.json` 判定未通过：两书复制库均成功写入占位译文且模型请求为 0；Biopolitics 有 1 条 `token_not_found`；Goldstein 有 90 条 `token_not_found` 与 1 条 `coordinate_out_of_range`。该回放复用坐标修复前的 Phase1-3 数据，因此用于证明旧输入被可靠阻断，不用于证明新 Phase3 产物已刷新。Goldstein 样本已证实包含同一正文坐标对应两条 `matched` link 的 Phase3 残余断层。
- 验证显示 `cargo test --all` 与 `cargo build --release` 通过；并行全量测试暴露的 `fnm-llm-repair` trace dump 共享用量记录竞争已修复。`cargo clippy --no-deps -p fnm-phase4 -p fnm-phase6 --all-targets -- -D warnings` 已通过，阶段 5 范围内曾暴露的循环内编译正则等 lint 已清除。全 workspace 严格 clippy 仍被 `fnm-core`、`fnm-phase3`、`fnm-llm-repair` 与未由本轮修改产生的 `fnm-orchestrator` 债务阻断，应另行治理。
- 翻译单元从 frozen units 派生。

2026-05-25 重新归因：

- `phase5_rootfix_diagnostic_v4` 与 `v5` 是不调用模型的当前代码复制库诊断；两书在刷新上游结构/link 输出后均为 `blocking=0`，Goldstein 也不再存在跨章 matched 或重复 anchor 消费。这说明此前 Phase4 blocker 的主要原因在 Phase1/3 输入合同，不是 Phase4 门禁过严。
- `semantic_golden` 对照仍显示 Biopolitics 与 Goldstein 有缺章和大范围内容差异。这些差异是重要追溯证据，但属于后续内容质量/P2 阶段；不能反过来把 Phase4 引用冻结合同判为未闭合。
- 诊断过程中发现 Phase1 漏标题恢复尝试既属于内容调校，又曾写入 schema 不接受的 candidate source；该启发式已从当前改动中移除，留待阶段 7 按原页证据单独设计。

2026-05-26 收尾口径更新：

- 已用当前代码无模型重生成两书 Phase1-3，清除 Phase4-6 派生产物，并验证持久化合同可严格读回。
- `cargo test -p fnm-phase4 -p fnm-orchestrator --no-fail-fast` 通过：Phase4 为 106 unit + 8 fixture/parity + 12 spec，orchestrator 为 23 tests。
- Biopolitics 的 `review_required` 是可见的上游内容判断，不是 Phase4 程序失败；Phase4 的责任是原样消费，不得消除或广播该判断。
- 阶段 5 不以回放脚本总体 `passed` 或 `export_ready_real` 收口；只以 Phase4 专属冻结证据收口。
- 已补 `tests/unit/test_fnm_downstream_replay.py` 与脚本口径：验证 Phase4 通过可与 Phase6 未放行并存、SQLite WAL 快照完整、双书回放按独立 worker 运行。
- 最终无模型证据位于 `output/fnm_downstream_replay/phase5_contract_closeout_20260526_v3/results.json`：Biopolitics `translation_unit_count=644`，Goldstein `translation_unit_count=978`；两书均 `upstream_unchanged=true`、`freeze_blocker_count=0`、`phase4_contract_passed=true`，批次 `model_requests=0`。
- 该报告的总体 `passed=false` 来源于两书 `export_ready_real=false`，属于阶段 6/7 的后续判定，不改变阶段 5 完成结论。
- 提交前复核已通过 `cargo fmt --all --check`、`cargo test --workspace --no-fail-fast`、`cargo clippy --no-deps -p fnm-phase4 -p fnm-phase6 --all-targets -- -D warnings` 与相关 Python 回归；既有 ignored 内容/parity 用例不被误报为本阶段通过。

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

当前暂停模型批跑和内容调校。阶段 5 已关闭，下一步按原阶段推进：

1. 为阶段 6 编写详细计划，限定 `fnm-phase5` 合并职责、`fnm-phase6` 导出/审计职责与 `can_ship` gate 的边界；未确认计划前不实施代码。
2. 阶段 6 只消费本次阶段 5 产物与其可观察 blocker，不重新解释 Phase1-4 事实。
3. 前序修复继续归入其原阶段记录；不得再以 A-H 新编号扩展实施范围。
4. 逐段 golden 差异、`review_required` 内容判断、漏章节识别和弱 OCR marker 保留报告与原页证据，移入阶段 7；当前不据此触发模型调用或逐书规则补丁。

当前不变规则：
- 不修改 `real_golden_template/`。
- 不用 Rust actual 覆盖 fixture。
- 5 个 parity ignored 测试保持严格断言，登记到阶段 7 backlog。
- `clippy::too_many_arguments` 作为工程债不挡阶段门禁。
