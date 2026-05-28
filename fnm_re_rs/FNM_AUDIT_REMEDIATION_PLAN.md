# FNM Rust 审计遗留问题执行计划

创建时间：2026-05-27
适用目录：`/Users/hao/OCRandTranslation/fnm_re_rs`
状态：当前唯一实施入口

## 一、用途与上下文

本文替代旧的 `FNM_REPAIR_MASTER_PLAN.md`、`FNM_REPAIR_PROGRAM_CONTRACT_PLAN.md`
和 `FNM_REPAIR_PHASE*.md` 实施计划。旧计划按“阶段”推进，曾将程序合同、
内容差异和工程收尾混在同一完成判断中，且引用了已经过期的回放结果。

本文不改变 FNM pipeline 本身的职责分工。代码仍按
`Phase1 -> Phase2 -> Phase3 -> Phase3.5 -> Phase4 -> Phase5 -> Phase6`
运行；这些名称描述数据流，不再用作实施排期或交付批次。

近期范围已于 2026-05-27 收窄：只处理**程序逻辑与工程可靠性**，包括公开
API 合同、错误可追溯性、读写/回放一致性、可测试异常路径和 Rust 工程门禁。
`semantic_golden`、逐书文本差异、OCR/marker 识别精度和真实整批内容验收
保留为后置证据，不作为近期工作目标或退出条件。

当前工作的判断来源只有三类：

1. 2026-05-22 形成的十份 crate 审计文件，作为问题来源清单。
2. 当前源码、当前测试和当前严格门禁，作为问题是否仍存在的依据。
3. 新鲜无模型回放，作为程序合同是否自产 blocker 的依据；底本对照报告只
   用于登记后置内容问题，不用于近期程序逻辑结案。

审计文件保留原貌；若审计中的问题已经修复，必须以测试或回放证据在本文登记，
不能删除原始审计结论来制造“没有问题”。

## 二、当前核验结论

### 1. 已确认成立的结果

2026-05-27 重新构建 PyO3 bridge 后运行双书无模型下游回放：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs/fnm-py
../../.venv/bin/python -m maturin develop --release

cd /Users/hao/OCRandTranslation
.venv/bin/python -m pytest tests/unit/test_fnm_downstream_replay.py -q
.venv/bin/python scripts/test_fnm_downstream_replay.py \
  --tag phase6_audit_current_20260527 \
  --slug Biopolitics \
  --slug Goldstein
```

证据文件：
`/Users/hao/OCRandTranslation/output/fnm_downstream_replay/phase6_audit_current_20260527/results.json`
（`generated_at=2026-05-27T18:22:51`）。

| 核验项 | Biopolitics | Goldstein | 结论 |
|---|---:|---:|---|
| `upstream_unchanged` | `true` | `true` | 下游回放未改写上游事实 |
| `phase4_contract_passed` | `true` | `true` | 引用冻结程序合同可消费当前输入 |
| `model_requests` | 0 | 0 | 回放不依赖模型请求 |
| `merge_*` blocker | 0 | 0 | Phase5/Phase6 未再自产合并 blocker |
| 最终 `can_ship` | `true` | `false` | Goldstein 仍有内容/上游阻断 |

据此，Phase5/Phase6 的职责拆分、只读导出审计和自产 `merge_*` 问题不再列为
当前功能 blocker。它们仍有格式、lint 和版本控制收尾事项，见工作包 Q。

### 2. 近期活跃的程序问题

| 类别 | 当前证据 | 当前判断 |
|---|---|---|
| 公开能力合同 | `EndnoteMode` 被接收但无差异行为；`start_phase` 与 `_start_phase` 尚无真实续跑能力 | 必须实现真实合同或移除公开承诺 |
| 错误可追溯性 | Rust trace 文件写入与 Python callback 结果仍可被静默忽略 | 失败必须向调用方或 diagnostic 可见 |
| scope 与持久化合同 | `recover_book_json()` 仍将逐章 marker 汇总到 `"auto"`；Phase4 双注入路径与 post-translate 重导出仍待证明 | 用程序测试关闭事实丢失和结果陈旧风险 |
| Rust 门禁 | `cargo fmt --all --check` 失败；`cargo clippy --workspace --all-targets -- -D warnings` 失败 | 当前工作树不可交付 |
| 版本控制完整性 | 三个已接线 Rust 源文件仍 untracked | 当前改动不可形成完整提交 |

### 3. 已知但近期排除的内容问题

下列失败已经留证，但属于内容识别、逐书差异或最终验收，不在近期程序逻辑
修复范围内。除非后续发现其根因是公开合同或错误传播缺陷，否则不在当前计划
中实施修复。

| 项目 | 已有证据 | 处置 |
|---|---|---|
| Goldstein 导出内容 blocker | 回放报告 `raw_note_marker_leak`、`duplicate_paragraph`、`gate_no_raw_marker_leak_book_level` | 后置内容追查 |
| 最终逐段对照 | replay DB 的 `semantic_golden export`：Biopolitics `14/14` 章失败，Goldstein `9/9` 章失败 | 后置内容验收 |
| Phase2 OCR 恢复 | ignored SPEC 中 marker `11`、`37` 失败 | 后置识别规则工作 |
| Phase3 parity 与 gap recovery | ignored 测试中 5 项 parity 与 2 项 gap recovery 失败 | 后置业务 parity 工作 |

### 4. 当前证据报告

| 报告 | 用途 |
|---|---|
| `output/fnm_downstream_replay/phase6_audit_current_20260527/results.json` | 近期程序合同证据；Goldstein 内容阻断仅作登记 |
| `output/fnm_golden_compare/biopolitics_phase6_audit_current_export_report.json` | 后置内容证据，不是近期 gate |
| `output/fnm_golden_compare/goldstein_phase6_audit_current_export_report.json` | 后置内容证据，不是近期 gate |

## 三、不可违反的执行规则

1. **只以新鲜证据判定状态。** 改过受测源码后，旧 JSON、旧 ZIP 和旧测试输出全部失效。
2. **问题从最早产生错误事实的位置修。** 下游审计发现文本、marker 或章节错误时，先定位其首次出现的产物，不在导出层改正文遮盖问题。
3. **分类来源唯一。** `note_kind` 只能由 Phase2 的逐 item 证据决定；后续模块只透传和消费。
4. **不写逐书补丁。** 不能以书名、固定页码、固定 marker 上限或黑名单修 Biopolitics/Goldstein；规则必须由已有 page/region/item/link 证据驱动。
5. **每个近期 bug 先有失败测试。** 程序合同和错误路径修复必须先复现；属于
   D 的 ignored 内容测试只留证，不因本条规则提前进入实现。
6. **底本只读。** 禁止以 Rust/DB 当前输出覆盖
   `test_example/*/golden_exports/real_golden_template/` 或倒写 expected fixture。
7. **忽略测试不算通过。** 被 `#[ignore]` 遮住的问题，在解除 ignore 通过前保持未完成。
8. **错误必须可见。** 不允许删除 blocker、吞写入错误、默认构造成功 status、或降低 `can_ship` 条件来让报告变绿。
9. **公开参数必须真实。** 一个配置/参数若不支持，删除公开入口或明确返回 unsupported；不能接收后忽略。
10. **提交前必须完整。** 被 `mod` 引用的新源文件、真实 fixture、文档和测试都必须进入版本控制；不能依赖未跟踪文件获得通过。
11. **工程规则同样是交付条件。** 不新增 `allow(clippy::...)`，不新增函数内动态 regex，不以 `let _ =` 吞掉关键错误。

## 四、审计问题总账

状态说明：

- `已闭合`：当前已有直接测试或回放证据，不再作为工作项；若回归失败则重新打开。
- `活跃`：当前源码、门禁或显式测试已经证明仍存在。
- `后置`：问题存在，但属于内容识别或最终验收，排除在近期程序逻辑工作之外。
- `待复核`：原审计提出且可能影响近期程序合同，但本轮尚无足够证据；按 R 补验证。

### 1. `fnm-core`

来源：`FNM_CORE_AUDIT.md`

| 审计问题 | 状态 | 依据 / 待办 |
|---|---|---|
| 空 `paragraphs` 时丢顶层正文 | 已闭合 | `segment_codec::tests::empty_paragraphs_preserves_top_text` 通过 |
| SQLite/Repository Phase5/6 落库合同 | 已闭合于当前消费面 | `test_repository_phase56` 12 tests 通过；完整迁移兼容性仍按 schema 变更复核 |
| DB 非法 `note_kind` 被改成正常分类 | 已闭合 | `invalid_note_kind_reads_back_as_unknown` 通过 |
| `replace_frozen_refs()` 忽略 `EndnoteMode` | 活跃 | `refs.rs` 明示 `Legacy` 与 `Standard` 行为一致；要实现差异或删除参数 |
| `chapter_title_match_key` 清理不足 | 后置 | 属于标题匹配业务 parity；进入内容工作后补 case |
| raw page 行错误处理 | 待复核 | 当前非法 JSON 为 warning + skip、DB row error 传播；补合同测试说明允许口径 |
| PDFium 全局 Mutex 例外说明 | 待复核 | 若仍为必须的全局串行化，补原因与并发测试说明 |
| fmt/clippy 门禁 | 活跃 | workspace strict clippy 首先在 `fnm-core` 失败 |

### 2. `fnm-phase1`

来源：`FNM_PHASE1_AUDIT.md`

| 审计问题 | 状态 | 依据 / 待办 |
|---|---|---|
| `toc_semantic_meta` gate 读取路径 | 已闭合于现有 fixture | `test_phase1_spec` 与 Biopolitics parity 通过；若修改 TOC 再复核 |
| 合法 `noise`、manual override 字段消费 | 待复核 | 属于输入合同；补覆盖 gate 与 `section_hint/reason` 的测试 |
| book-type overrides 识别行为 | 后置 | 属于页面/书型判断业务逻辑 |
| 简化 page resolve / LLM book-type 近似 note region | 后置 | 属于结构/识别业务逻辑；源码仍有 `heading_graph incomplete (simplified...)` 注释 |
| 无效中间结构和 role 默认映射 | 待复核 | 对 `other`、front/back、无匹配规则补明确 contract |
| `role_heuristics.rs` 整模块 dead-code allow | 活跃 | 源码仍有 `#![allow(dead_code)]` |

### 3. `fnm-phase2`

来源：`FNM_PHASE2_AUDIT.md`

| 审计问题 | 状态 | 依据 / 待办 |
|---|---|---|
| 年份修复跨 region/chapter | 已闭合于单测 | `year_filter` 的 cross-region/cross-chapter tests 通过 |
| fallback 将未知 item 归为 footnote | 已闭合 | `fallback_review_required` 通过 |
| 多页 region 去重、续行排序、chapter mode 布尔事实 | 后置 | 属于注释捕获业务 parity；待进入内容工作时补字段级断言 |
| `sup_recovery` chapter scope / explorer / 旧视觉路径 | 后置，binding scope 除外 | 识别路径后置；`fnm-py` 丢 scope 作为程序合同在 P 中处理 |
| Layer2 OCR 标点/数字后缀恢复 | 后置 | `--ignored` 实测：marker `11`、`37` 两条 SPEC 失败 |
| 已知差异文档自相矛盾 | 已闭合于记录 | 文档已改为记录 ignored SPEC 失败，不再声称已实现 |
| 大文件与 lint allow | 活跃 | `endnote_chapter_explorer/mod.rs` 超 1300 行，`endnote_regions_raw.rs` 有 clippy allow |

### 4. `fnm-phase3`

来源：`FNM_PHASE3_AUDIT.md`

| 审计问题 | 状态 | 依据 / 待办 |
|---|---|---|
| 重写上游 facts、Unknown 自动匹配、混流 contract | 已闭合于 active SPEC | 对应 Phase3 SPEC 当前通过 |
| 跨章 gap/orphan 边界基础守卫 | 已闭合于 active SPEC | active chapter-boundary SPEC 通过 |
| Biopolitics strict parity | 后置 | 解除 ignore 后 5 项全失败：anchors `536 != 664`、links `622 != 650` 等 |
| weak digit / symbol gap recovery | 后置 | 解除 ignore 后两项 SPEC 均失败 |
| ignored reason 仍归因 Phase2 `-20` | 已闭合于记录 | 已知差异文档已改为说明该归因不足；实现定位后置 |
| `contract_repair.rs` 过大且有 allow | 活跃 | 文件 467 行并保留 `#[allow(clippy::needless_range_loop)]` |

### 5. `fnm-phase4`

来源：`FNM_PHASE4_AUDIT.md`

| 审计问题 | 状态 | 依据 / 待办 |
|---|---|---|
| note units 丢失、注入失败无 blocker、UTF-8 panic | 已闭合 | `cargo test -p fnm-phase4` 通过；回放 `phase4_contract_passed=true` |
| owner / frozen evidence / review 透传 | 已闭合于双书下游回放 | 两书 freeze blocker 为 0 且上游摘要不变 |
| 两套 ref injection 是否仍有行为分叉 | 待复核 | `units/ref_inject.rs` 仍存在；证明其仅用于不同产物或统一实现 |
| 大文件/动态 regex/工程质量 | 待复核 | 纳入 workspace 门禁清理后再结案 |

### 6. `fnm-phase5`

来源：`FNM_PHASE5_AUDIT.md`

| 审计问题 | 状态 | 依据 / 待办 |
|---|---|---|
| 反向依赖 Phase6、重建 chapter/note mode、缺 merge blocker | 已闭合于当前回放 | 双书回放无 `merge_*`；Phase5 使用已有 `chapters` 时透传 |
| raw marker rewrite / local refs 合同 | 已闭合于当前回放的本层责任 | Biopolitics 本层无 blocker，Goldstein blocker 未被本层新增 |
| 跨章 note text fallback 与定义文本改写 | 后置 | 属于文本保真；进入内容验收时加跨章 fixture |
| 工程门禁 | 活跃 | `section_render.rs` 未 fmt；`body_render.rs` / `section_render.rs` 仍有新增 lint allow |
| 文件纳管 | 活跃 | `render/section_builder.rs` 已接线但仍未跟踪 |

### 7. `fnm-phase6`

来源：`FNM_PHASE6_AUDIT.md`

| 审计问题 | 状态 | 依据 / 待办 |
|---|---|---|
| endnote 定义合同、真实 ZIP、note_items 上下文、`doc_id`、统一 `can_ship` | 已闭合于当前回放和合同测试 | 双书不再生成 `merge_*`；Goldstein 上游问题仍被正确阻断 |
| 导出层修补正文 | 已闭合于当前职责面 | canonicalize/garbled repair 删除，内容差异没有被静默抹掉 |
| diagnostics 的 `EndnoteMode` | 活跃依赖 | 由 `fnm-core` 无效 mode 问题阻断 |
| 工程门禁 | 活跃 | `bundle_builder.rs` / `export_audit/mod.rs` 未 fmt；`file_audit/mod.rs` 仍有 lint allow |
| 文件纳管 | 活跃 | `bundle_builder.rs` 与 `audit_logic.rs` 已接线但未跟踪 |
| 测试覆盖迁移 | 待复核 | 删除旧 export/audit 大量测试后，确认关键合同没有随删除丢失 |

### 8. `fnm-llm-repair`

来源：`FNM_LLM_REPAIR_AUDIT.md`

| 审计问题 | 状态 | 依据 / 待办 |
|---|---|---|
| 字符/byte 坐标、禁止创建 note item、action ID 白名单 | 已闭合于当前 tests | 相关 parser/fuzzy/spec tests 通过 |
| duplicate anchor 预过滤 override 物化 | 待复核 | 代码已有 `_prefiltered_anchors` 合同，需集成断言 DB override 落地 |
| page role 读取失败放宽范围、失败后 partial write | 待复核 | 增加故障注入测试 |
| `safe_float()` 接受文字置信度 | 活跃 | 测试仍明确接受 label；auto-apply 应只接受数值 |
| trace IO 错误被吞并错误计数 | 活跃 | `trace/dump.rs` 对 create/write 使用 `let _ =` |
| lint allow / Value schema 过宽 | 活跃工程债 | 严格 clippy 收口时处理 |

### 9. `fnm-orchestrator`

来源：`FNM_ORCHESTRATOR_AUDIT.md`

| 审计问题 | 状态 | 依据 / 待办 |
|---|---|---|
| LLM repair 后本轮下游不消费、diagnostic 丢失 | 已闭合于定向测试/源码路径 | 当前 mainline 有重新物化路径，orchestrator 23 tests 通过 |
| `start_phase` 假支持 | 活跃能力缺口 | 当前改为明确报错，仍未实现续跑；应删除公共承诺或实现 DB 续跑 |
| `load_phase6_structure()` 缺失数据掩盖 | 待复核 | 添加缺 bundle/status 时不可放行测试 |
| post-translate repair 后续重跑 | 待复核 | 添加实际 repair 应导致重导出结果改变的集成测试 |
| run finalize / 配置字段 / run ID / JSON error | 待复核 | 按公开 API 行为逐项补故障和并发测试 |
| `page_translate.rs` 过大及 clippy | 活跃工程债 | 文件超过 1300 行，纳入门禁工作包 |

### 10. `fnm-py`

来源：`FNM_PY_AUDIT.md`

| 审计问题 | 状态 | 依据 / 待办 |
|---|---|---|
| LLM repair panic、renderer error 不回报、status 默认造成功 | 部分闭合 | panic 与 renderer report 已修；仍需异常路径回归 |
| `recover_book_json()` 丢失 chapter scope | 活跃 | 当前将全部 marker 汇入 `"auto"` key |
| trace callback 错误被吞 | 活跃 | `callback.call1()` 的结果仍被忽略 |
| `_start_phase` 参数接收但无行为 | 活跃 | `build_doc_status_json()` 仍暴露无效参数 |
| zip path、post-translate SQL、body-unit 错误合同 | 待复核 | 为不存在 ZIP、数据库错误、输入错误补 Python API 测试 |
| 单文件过大和重复 DB pool | 活跃工程债 | `lib.rs` 超过 1400 行 |

## 五、工作包与实施顺序

下列编号是问题包，不是 pipeline 阶段。依赖关系仅表示先取得可靠事实，再处理其消费者。

### P：程序合同与可观察错误

目标：公开 API 声称支持的行为真实可用，程序错误能被调用方判断，读写结果
不会因 scope 丢失或流程短路而失真。

范围：

- `fnm-core/src/refs.rs`
- `fnm-phase4/src/`
- `fnm-llm-repair/src/`
- `fnm-orchestrator/src/`
- `fnm-py/src/lib.rs`

任务：

1. 对 `EndnoteMode` 作决策：实现 `Legacy`/`Standard` 的可测试差异，或删除 Rust/Python 暴露的无效参数并统一调用方。
2. 对 `start_phase` 作决策：实现从持久化前置产品续跑，或从公开配置/API/文档删除该能力；仅报 unsupported 不算实现完成。
3. 修复 `recover_book_json()` 的 chapter scope，输入必须接收或构建逐章 marker map，不得汇总为 `"auto"`。
4. 将 Python trace callback 和 Rust trace 文件写入失败变成返回状态或可查询 diagnostic，不能静默吞掉。
5. 为 LLM repair duplicate prefilter、partial write、page role 读取失败增加集成测试。
6. 收紧 `safe_float()`：auto-apply 置信度必须是 JSON number；文字标签只能进入 review 或报 schema 错误。
7. 为 post-translate repair 验证“应用修补后确实重新产生导出审计结果”，而非只记录轮次。
8. 复核 Phase4 两套 ref injection 路径：若服务不同产物，增加行为边界测试；若
   行为重叠则收敛到同一实现，避免同一合同出现两套结果。

必须通过：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo test -p fnm-core -p fnm-phase4 -p fnm-llm-repair -p fnm-orchestrator -p fnm-py

cd /Users/hao/OCRandTranslation
.venv/bin/python -m pytest tests/unit/test_fnm_downstream_replay.py -q
```

退出条件：

- 无公开参数被接收后无效忽略。
- API 错误能由调用方判断，异常路径有测试。
- repair、post-translate、status 的持久化读回与当次 pipeline 输出一致。
- 修改程序合同后，下游回放不新增本层自产 blocker。

### Q：工程门禁与可提交性

目标：让当前实现达到仓库规定的提交质量，不能以内容差异为理由跳过。

范围：全部 Rust workspace 与当前新增/移动文件。

任务：

1. 先纳管已接线但未跟踪的三个模块：
   `fnm-phase5/src/render/section_builder.rs`、
   `fnm-phase6/src/book_assemble/bundle_builder.rs`、
   `fnm-phase6/src/export_audit/audit_logic.rs`。
2. 修复当前 `cargo fmt --all --check` 失败。
3. 将新增 raw marker API 参数集合抽为结构化上下文，关闭 `fnm-core` 新增 `too_many_arguments`。
4. 移除新增 `allow(clippy::...)`；对历史 allow 建独立清理清单并逐个用结构拆分消除。
5. 拆分明显超限文件：`fnm-py/src/lib.rs`、`fnm-orchestrator/src/page_translate.rs`、
   `fnm-phase2/src/endnote_chapter_explorer/mod.rs`、`fnm-phase1/src/page_partition/role_heuristics.rs`、
   `fnm-phase3/src/endnote_repair/contract_repair.rs`。
6. 复核 Phase6 删除旧测试后的合同覆盖：真实 ZIP、read-only、不改正文、定义闭合、统一 gate 和双书 fixture 均必须保留测试。

必须通过：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo fmt --all --check
cargo test --workspace --no-fail-fast
cargo clippy --workspace --all-targets -- -D warnings
cargo build --release
```

退出条件：

- 门禁四项全部通过。
- 没有新增 lint allow、函数体动态 regex、静默关键错误。
- 所有被编译/测试使用的新文件均已纳管。

### D：范围外问题登记（冻结）

本节只防止遗忘，不提供近期任务或退出条件。以下事项已知存在，但明确排除
在当前程序逻辑计划之外：

- Phase2 OCR marker 恢复失败与 Phase3 parity/gap recovery 失败。
- Goldstein 当前内容 blocker 及双书逐段内容差异。
- `semantic_golden` 对照、真实整批和最终内容发布验收。

只有在用户另行启动内容收敛工作后，才为这些事项建立独立计划；不得在 P、Q
或 R 的实现过程中顺带修补具体书内容。

### R：程序审计补证

目标：把总账中仍为 `待复核` 的**程序合同项**转为 `已闭合` 或可复现的
`活跃` 工作项；已标为 `后置` 的内容项不在本包内展开。

任务：

1. 逐 crate 为表中 `待复核` 的程序合同项补最小行为测试。
2. 若测试失败且属于程序合同、错误传播或工程门禁，将问题并入 P 或 Q。
3. 若测试失败属于文本识别、逐书 parity 或最终内容差异，将问题登记到 D，
   不在近期实现中展开。
4. 若测试通过，在本文登记测试名和日期，不改写审计原文。
5. 更新 `PROGRESS.md` 与 `verification.md`，只记录可重复运行的结论。

退出条件：

- 本文程序合同条目不存在 `待复核` 状态。
- 后置内容条目保持范围说明和已有证据，不冒充已经修复。

## 六、推荐执行顺序

执行次序按依赖确定，不按 pipeline 阶段编号：

1. `Q` 中的文件纳管与 fmt 修复，先让后续测试结果可提交、可复现。
2. `P` 关闭无效公开能力、scope 丢失、repair/trace 异常路径与流程一致性缺口。
3. `R` 只对可能属于程序逻辑的未定审计项补证；内容类结果登记到 D 后暂停。
4. `Q` 完成 workspace strict clippy、必要拆分和完整构建门禁。
5. 重跑无模型下游回放，确认程序修复未新造 Phase4-6 blocker。
6. `D` 仅作冻结登记；不以 `semantic_golden`、逐书 blocker 或真实整批判定近期完成。

任何实施中发现的 OCR、anchor 匹配精度、段落差异或具体书内容问题，只记录
触发证据和责任模块，不顺势扩张当前程序逻辑修复范围。

## 七、交付汇报要求

每次提交或交接只报告以下内容：

1. 关闭了本文哪一条活跃问题，失败测试如何转为通过。
2. 新生成的证据文件路径、生成时间和关键结果。
3. 仍未关闭的活跃问题与待复核项目。
4. `fmt`、`test`、`clippy`、`build` 是否全部通过。
5. 是否触及真实模型、是否修改底本、是否存在未跟踪交付文件。
6. 是否发现被明确后置的内容问题，且未将其冒充为近期程序合同 blocker。

不得使用“整体基本完成”“只剩少量细节”这类无法由证据验证的表述。
