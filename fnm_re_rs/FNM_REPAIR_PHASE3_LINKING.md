# 阶段 3 收尾计划：Phase3 链接匹配边界

创建时间：2026-05-23
修订时间：2026-05-23
上位目标：`FNM_REPAIR_MASTER_PLAN.md`

本文给接手阶段 3 收尾的人使用。当前不是从零实现 Phase3，而是审查已有修改后，修完仍存在的流程级边界错误，并把不影响职责闭合的细节 parity 差异留为后续可追溯任务。读完本文后，应能直接编写回归测试、修改指定文件、跑验收并形成交接结论。

## 一、阶段职责与本次收尾口径

Phase3 只有以下决策权：

1. 在正文页面检测 `BodyAnchor`。
2. 使用 Phase2 已确定类型的 `NoteItem` 与 anchor 建立 `NoteLink`。
3. 对未匹配项产生 review/diagnostic 或类型不变的修复建议。

Phase3 没有以下决策权：

- 重新分类 `NoteItem.note_kind`。
- 使用 chapter 聚合模式覆盖个体 note/anchor 类型。
- 改写 Phase1 的 page/chapter 事实或 Phase2 的 region/item/mode 事实。
- 将不确定的 `Unknown`、跨章候选或不可注入 synthetic anchor 包装为正常成功匹配。

### 本阶段必须交付

本阶段必须修完会损坏流程判断的结构性 bug：

- 类型混流导致的 contract 假结论。
- `Unknown` anchor 被升级为普通脚注匹配。
- 上游 facts 保留没有真正等值测试保护。
- 与上述边界直接相关的缺失回归测试与可核验诊断。

### 本阶段不强行交付

以下项目不是“可以忽略”，而是带失败证据后置到整体流程固定后的内容收敛阶段：

- 当前 Biopolitics internal Phase3 golden 的全字段/全数量 parity 差异。
- bare digit、symbol、弱 OCR 的低置信度识别精调。
- 根底本语义比较中不证明跨 phase 边界错误的个别逐段差异。

收尾者不得为这些差异覆盖 golden 或放宽断言；只需把失败保留为待办并说明它不属于当前 P0/P1 的依据。

## 二、必须先掌握的上下文

### 1. 上游已验收基线

阶段 1 已闭合 DB/error/trace/PyO3 边界和基础类型 fallback。阶段 2 已完成双书完整回归：

| 书 | 阶段 2 证据目录 | 已确认结果 |
|---|---|---|
| Biopolitics | `/Users/hao/OCRandTranslation/output/fnm_real_batch/phase2_note_capture_v2/` | `ready`，`blocked=0`，LLM repair 请求 20 |
| Goldstein | `/Users/hao/OCRandTranslation/output/fnm_real_batch/phase2_note_capture_v2_goldstein/` | `ready`，`blocked=0`，Notes 第 331 页存在，LLM repair 请求 0 |

这意味着阶段 3 必须以 Phase2 的 note items / regions / modes 为事实输入，不能通过下游重解释来“修正”上游。

### 2. Golden 与真实底本

最终内容底本不可修改：

- `/Users/hao/OCRandTranslation/test_example/Biopolitics/golden_exports/real_golden_template/`
- `/Users/hao/OCRandTranslation/test_example/post-revolutionary/golden_exports/real_golden_template/`

供低内存逐段比较的派生底本只能从上述目录单向生成：

- `test_example/Biopolitics/golden_exports/semantic_golden_v1.jsonl`
- `test_example/post-revolutionary/golden_exports/semantic_golden_v1.jsonl`

`fnm-phase3/tests/fixtures/biopolitics_phase3_golden.json` 是内部 Phase3 结构回归 fixture，不是最终人工底本。本阶段：

- 不得用当前 Rust 输出重写它。
- 不得修改 `real_golden_template/`。
- 可把实际输出另存为诊断证据并报告差异。

翻译为 `[待翻译]` 在本阶段可接受；它不免除结构事实和 source 追溯链的验证。

## 三、当前核验结果：阶段 3 还未完成

以下结论来自 2026-05-23 对当前工作区代码和测试的审阅。接手人不应按旧总结将阶段 3 标为完成。

### 1. 已运行的核验命令

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo fmt --check
cargo test -p fnm-phase3
cargo test -p fnm-phase3 --test biopolitics_phase3_parity -- --ignored
cargo test -p fnm-phase2
cargo clippy -p fnm-phase3 --all-targets -- -D warnings
```

结果：

| 检查 | 结果 | 解释 |
|---|---|---|
| `cargo fmt --check` | 通过 | 格式无阻断 |
| `cargo test -p fnm-phase3` | 表面通过 | parity 中仍有 5 个 ignored，SPEC 中仍有 2 个 ignored |
| 显式运行 Phase3 ignored parity | **5/5 失败** | 当前不能宣称 Biopolitics parity 完成 |
| `cargo test -p fnm-phase2` | 通过，仍有已记录 ignored | 阶段 2 Layer2 OCR 细节项，不是当前 P0 |
| Phase3 clippy | 失败 | 由 `fnm-core` 已存在的 5 个 `too_many_arguments` 触发，登记为工程债，不作为阶段 3 逻辑 bug 替代品 |

显式 parity 的主要失败：

| 测试方向 | 当前失败摘要 |
|---|---|
| body anchors | Rust `536`，golden `664` |
| note links | Rust `622`，golden `650` |
| summary total | Rust `536`，golden `664` |
| contract def/anchor | endnote definitions `44`，anchor `0` |
| chapter contract | `has_marker_gap` Rust 为 `true`，golden 为 `false` |

这些差异目前作为 P2/parity backlog 保留；其中能直接归因于下述结构性代码 bug 的部分，必须先修。

### 2. 当前 P0 未完成项

#### P0-1：endnote contract 仍混入 footnote marker 序列

当前位置：`fnm-phase3/src/note_linking/chapter_contracts.rs`

现状：

- `endnote_def_count` 和 `footnote_def_count` 已分别计算。
- 但 `def_numeric_markers` 仍由 `footnote_items.chain(endnote_items)` 构建。
- `first_marker_is_one`、`has_marker_gap`、`def_count`、`marker_sequence` 仍使用混合序列。

后果：

- 同章存在脚注和尾注时，endnote contract 会被脚注数字污染。
- contract 报错无法判断是 endnote 链接失败还是混合统计造成的假阳性。

判定：必须在本阶段修复。

#### P0-2：Unknown anchor 仍可成为普通脚注 `Matched`

当前位置：`fnm-phase3/src/footnote_links.rs`

现状：

- 星号脚注的页内直配允许 `AnchorKind::Unknown`。
- OCR ordered-subsequence repair 允许 `AnchorKind::Unknown`，随后将其直接改写为 `Footnote` 并生成 `Matched`。

后果：

- Phase3 重新做了类型决定，违反 Phase2 唯一分类源和 Unknown review 规则。
- 失败证据会变成看似成功的 link，向 Phase4 传播错误事实。

判定：必须在本阶段修复。

#### P0-3：上游 facts 不变的测试仍不是等值验证

当前位置：

- `fnm-phase3/src/lib.rs`
- `fnm-phase3/src/note_linking/phase2_rebuild.rs`
- `fnm-phase3/tests/test_phase3_spec.rs`

现状：

- 已有代码部分改为从输入透传 page/chapter 相关信息。
- 现有名为“不修改 Phase2”的 SPEC 主要断言字段非空，不能证明输入 facts 与输出 facts 相同。
- Phase3 输出中的 note regions/items/modes 仍需审查其来源和 override 行为。

后果：

- 后续阶段看到差异时，仍无法确认差异产生于 Phase2 还是 Phase3 重建。

判定：必须先补真正等值测试；测试暴露的改写路径必须在本阶段修复。

### 3. 已存在但需要守住的改动

下列路径已有实现迹象或已通过局部测试，不要求重写，但本次修改不能使其回归：

| 行为 | 当前文件/测试 | 收尾要求 |
|---|---|---|
| unknown orphan anchor 输出 `NoteKind::Unknown` | `src/note_links.rs`，SPEC 已覆盖 | 保持，不等于允许 unknown 成功匹配 |
| gap recovery 限制章范围 | `src/body_anchors/gap_recovery.rs`，SPEC 已覆盖 | 保持同章限制 |
| paragraph 输出按 Phase2 note item 分类 | `src/paragraph_footnotes.rs`、`src/paragraph_endnotes.rs` | 不重引入 raw markdown 分类 |
| synthetic footnote 不伪装成普通 matched | `src/footnote_links.rs` | Unknown 修复不得破坏该路径 |
| OCR loop3 同章守卫 | `src/note_linking/ocr_repair/loop3_cross_chapter.rs` | 保持测试覆盖 |

### 4. 缺证据或需补验收的项

| 项目 | 当前判断 | 要求 |
|---|---|---|
| chapter 无初始 anchor，但存在 orphan endnote 时仍扫描 chapter body pages | 代码已有输入改动，但未找到满足计划语义的专门回归测试 | 本阶段补测试 |
| Phase3 diagnostic 输出 | 已看到 `llm_candidate_count` 等局部字段，gap/review 诊断是否齐全未证明 | 只补本阶段 P0 修复必要的诊断，不展开全量重构 |
| 阶段 3 双书真实批次 | 未找到本阶段代码对应的新批跑证据 | P0 测试通过后必须跑 |

## 四、本阶段禁止做法

- 不修改或重新生成 `real_golden_template/`。
- 不用当前 Rust actual 输出覆盖 Phase3 fixture 以消除失败。
- 不把 `Unknown` 当作 footnote/endnote 的自动匹配通配符。
- 不用 chapter mode 给章内每条 note/anchor 广播类型。
- 不因 internal parity 数量差而在 Phase3 临时发明 Phase2 分类规则。
- 不为 Biopolitics 或 Goldstein 添加逐书阈值、marker 黑名单或书名特例。
- 不跳过完整集成批而直接宣称阶段完成。

## 五、收尾执行顺序

修复按以下顺序进行。每个修复包必须先添加失败测试，确认能重现，再改代码。

### 修复包 A：Contract 类型隔离

#### 问题

`chapter_contracts.rs` 将 footnote marker 混入 endnote contract 的 sequence/gap 判定。

#### 先写测试

文件：`fnm-phase3/tests/test_phase3_spec.rs`，必要时补模块 unit test。

至少新增/改强以下测试：

1. 同章含连续 endnotes 和带有额外数字的 footnotes 时，endnote `marker_sequence` 只来自 endnote。
2. footnote 的 marker 断裂不使 endnote `has_marker_gap=true`。
3. Unknown item 不进入任一成功 contract 序列。

不要只测 `endnote_def_count`；当前 bug 正是 count 分离而 sequence 未分离。

#### 改代码

文件：`fnm-phase3/src/note_linking/chapter_contracts.rs`

要做：

1. 以 `chapter.endnote_items` 单独构建 endnote marker sequence。
2. endnote contract 的 `first_marker_is_one`、`has_marker_gap`、`def_anchor_mismatch`、`marker_sequence` 全部只使用 endnote 流。
3. 如果输出同时需要 footnote contract，使用独立结构/字段，不能复用 endnote 序列。
4. Unknown 进入 review/diagnostic，不计入成功序列。

#### 验收

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo test -p fnm-phase3 spec_mixed_footnote_endnote_contract_separate_counts
cargo test -p fnm-phase3 <新增的marker_sequence测试名>
```

### 修复包 B：Unknown 不得自动匹配

#### 问题

`footnote_links.rs` 的星号路径和 OCR repair 路径把 unknown anchor 当作脚注成功使用。

#### 先写测试

至少覆盖：

1. `AnchorKind::Unknown` 的星号 anchor 与 footnote item 同页同 marker 时，不生成普通 `Matched`。
2. `AnchorKind::Unknown` 的短 marker 可被 OCR subsequence 命中时，不被改写为 `Footnote`，不生成普通 `Matched`。
3. 明确 `AnchorKind::Footnote` 的对应正常路径仍可匹配，防止修复把合法功能关掉。

#### 改代码

文件：

- `fnm-phase3/src/footnote_links.rs`
- 必要时 `fnm-phase3/src/note_linking/note_kind_inference.rs`

要做：

1. 用于自动成功 link 的候选过滤必须要求明确 `AnchorKind::Footnote`。
2. Unknown 候选若需要留作 repair 提示，只能写 review/diagnostic，不改变类型、不占用 ordinary matched link。
3. 检查共享 compatible helper：review 可宽松，自动 link 必须严格；如语义混用，拆成命名明确的函数。

#### 验收

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo test -p fnm-phase3 <新增的unknown-star测试名>
cargo test -p fnm-phase3 <新增的unknown-ocr测试名>
```

### 修复包 C：Phase1/2 facts 等值保留

#### 问题

已有测试未证明 Phase3 不重建或覆盖上游事实。

#### 先写测试

文件：`fnm-phase3/tests/test_phase3_spec.rs` 或新的针对真实 fixture 的 integration test。

测试至少比较输入与输出的：

- pages/page roles
- chapters 与 source/boundary 字段
- heading candidates / section heads
- note regions
- note items，包括 `note_kind`、marker、ownership
- chapter note modes

允许 Phase3 新增的只有 anchors、links、alignment、review/diagnostic 这类自身产物。比较优先使用完整序列化值或逐字段等值，不用“非空”替代。

若 override 的预期确实会修改某个 Phase3 产物，测试必须将它与上游 facts 分开断言；不能把输入 facts 修改写成“修复”。

#### 改代码

文件：

- `fnm-phase3/src/lib.rs`
- `fnm-phase3/src/note_linking/phase2_rebuild.rs`
- 必要时 `fnm-phase3/src/input.rs` / `src/output.rs`

要做：

1. Phase3 输出透传上游事实，而非从 chapter layers 或临时 materialization 重建。
2. 若 `phase2_rebuild` 仍是 link 内部临时结构，缩小返回范围并在命名/注释中表明不具备事实所有权。
3. 任何发现上游事实不正确的路径应返回 review/blocker 或回到 Phase2 修，不在 Phase3 重分类。

#### 验收

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo test -p fnm-phase3 <新增的facts_equal测试名>
```

### 修复包 D：缺失的边界证据

本包只补与 Phase3 职责闭合直接有关的证据，不展开识别精调。

#### 要做

1. 在 `fnm-phase3/src/endnote_links.rs` 对“章内没有已检测 anchor，但有 orphan endnotes，仍只扫描该章 body pages”增加专门测试。
2. 检查 `src/output.rs` 或当前 evidence 输出，使本阶段新增的 unknown review/contract 隔离失败能从结果中被查到。
3. 保持已有 gap recovery 和 OCR 跨章测试继续通过。

## 六、文件级工作清单

接手者应按此表审查和提交；“保持/验证”项不需要无目的重构。

| 文件 | 当前状态 | 本阶段动作 | 完成证据 |
|---|---|---|---|
| `fnm-phase3/src/note_linking/chapter_contracts.rs` | **未完成，P0** | 分离 endnote sequence/gap/first marker；Unknown 不入成功序列 | mixed contract 新回归通过 |
| `fnm-phase3/src/footnote_links.rs` | **未完成，P0** | 去除 Unknown 自动直配及 OCR 升格 | unknown star/OCR 回归通过 |
| `fnm-phase3/src/lib.rs` | 部分完成 | 配合真实 facts 等值测试修剩余覆盖路径 | 输入/输出 facts 等值 |
| `fnm-phase3/src/note_linking/phase2_rebuild.rs` | 部分完成 | 限制为内部匹配 materialization，不拥有上游事实 | 等值测试及审阅 |
| `fnm-phase3/src/endnote_links.rs` | 代码部分存在 | 增加“无 anchor 仍按章 body pages recovery”测试 | 新测试通过 |
| `fnm-phase3/src/note_links.rs` | 已有 Unknown orphan 修复 | 保持，不回归 | 现有 SPEC 通过 |
| `fnm-phase3/src/body_anchors/gap_recovery.rs` | 已有章范围守卫 | 保持，不做弱识别调参 | 现有 boundary SPEC 通过 |
| `fnm-phase3/src/paragraph_footnotes.rs` | 已向 Phase2 派生靠拢 | 审阅保持类型来源，不展开精调 | 相关测试通过 |
| `fnm-phase3/src/paragraph_endnotes.rs` | 已向 Phase2 派生靠拢 | 审阅保持类型来源，不展开精调 | 相关测试通过 |
| `fnm-phase3/src/note_linking/ocr_repair/loop3_cross_chapter.rs` | 已有同章守卫 | 保持 | 原回归通过 |
| `fnm-phase3/src/output.rs` | 诊断部分存在 | 只补本次修复必要的可观察信息 | evidence 可定位失败 |
| `fnm-phase3/tests/test_phase3_spec.rs` | 局部边界覆盖存在 | 先补 A-D 回归，再修实现 | 新增测试真实失败后转绿 |
| `fnm-phase3/tests/biopolitics_phase3_parity.rs` | **5 个 ignored 且显式执行失败** | 保留严格断言和失败证据，不覆盖 fixture；归入阶段 7 内容收敛 | 交接列出失败摘要 |
| `fnm-phase3/tests/fixtures/biopolitics_phase3_golden.json` | 固定 fixture | 不修改 | `git diff` 无变化 |

## 七、后置问题登记：不要在本阶段误修

### 1. Internal Phase3 parity

当前 ignored parity 明确失败，不能写成“完成”。但是在修完 P0 之后，若剩余差异仅是 anchor 数量、弱 OCR 或 Python/Rust 历史行为差异，而没有上下游事实覆盖或类型错配证据，则登记到阶段 7：

- 保留 ignored 测试和显式运行的失败输出。
- 记录差异的 chapter/page/marker 范围。
- 之后以根底本与 source evidence 判定应修 Rust 还是替换不可靠的内部 fixture。

### 2. 根底本语义比较

当前可用命令：

```bash
cd /Users/hao/OCRandTranslation
.venv/bin/python scripts/fnm_semantic_golden.py build --slug Biopolitics
.venv/bin/python scripts/fnm_semantic_golden.py build --slug Goldstein
.venv/bin/python scripts/fnm_semantic_golden.py compare-db --slug Biopolitics --layer export \
  --report output/fnm_golden_compare/phase3_biopolitics_export.json
.venv/bin/python scripts/fnm_semantic_golden.py compare-db --slug Goldstein --layer export \
  --report output/fnm_golden_compare/phase3_goldstein_export.json
```

在未 rebuild 并重新全量批之前，已有 DB 的失败结果只能说明当前持久化产物不能支持交付，不能直接归因于本轮源码。阶段 3 交接时应保存新批次对应报告；若失败仅属内容精调，归入阶段 7 backlog。

### 3. Clippy 工程债

当前 `cargo clippy -p fnm-phase3 --all-targets -- -D warnings` 会因 `fnm-core` 既有的 5 个 `too_many_arguments` 失败：

- `fnm-core/src/db/repository.rs`
- `fnm-core/src/model_capabilities.rs`
- `fnm-core/src/ref_rewriter.rs` 三处

这些应作为公共 API 参数收束任务处理，不得通过新增 `allow` 抑制；它们不是用来绕开本阶段 P0 修复的理由。

## 八、验证流程

### 1. 每个修复包开发时

顺序必须是：新增重现测试失败 -> 改实现 -> 新测试通过 -> 跑 crate 回归。

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo fmt --check
cargo test -p fnm-phase3 <本包新增测试名>
cargo test -p fnm-phase3
```

还应主动显式运行仍被后置的 parity，以记录其失败没有被隐藏：

```bash
cargo test -p fnm-phase3 --test biopolitics_phase3_parity -- --ignored
```

该命令在阶段 3 收尾期间允许因已登记 P2 差异失败，但结果必须进入交接记录。

### 2. 只有改 Python 时

若本阶段顺带修改了批测或 semantic golden Python 脚本，补：

```bash
cd /Users/hao/OCRandTranslation
.venv/bin/python -m py_compile scripts/test_fnm_batch.py scripts/test_fnm_real_batch.py scripts/fnm_semantic_golden.py
.venv/bin/python -m pytest tests/unit/test_fnm_semantic_golden.py -q
```

只修改 Rust 时不以 Python compile check 代替 Rust 测试。

### 3. 阶段收尾集成批

P0 回归和 crate 测试通过后，Python 必须加载最新 Rust 动态库：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs/fnm-py
../../.venv/bin/python -m maturin develop
```

随后完整运行两书真实批次。启动后即使时间长也必须等待自然结束或明确错误落盘：

```bash
cd /Users/hao/OCRandTranslation
PYTHONUNBUFFERED=1 .venv/bin/python scripts/test_fnm_real_batch.py \
  --slug Biopolitics \
  --group all \
  --include-all \
  --batch-tag phase3_linking_closeout \
  --verbose \
  2>&1 | tee /tmp/phase3_linking_closeout.console.log

PYTHONUNBUFFERED=1 .venv/bin/python scripts/test_fnm_real_batch.py \
  --slug Goldstein \
  --group all \
  --include-all \
  --batch-tag phase3_linking_closeout_goldstein \
  --verbose \
  2>&1 | tee /tmp/phase3_linking_closeout_goldstein.console.log
```

本次集成批的判定方式：

- 若出现 Phase3 类型混流、Unknown 成功匹配、跨章 recovery、上游 facts 覆盖等 blocker，阶段 3 未完成。
- 若只剩已有或新定位的 P2 内容/parity 差异，保存证据并归档到阶段 7，不强迫本阶段做逐项识别精调。
- 若 blocker 属于 Phase4-6 的消费、冻结、合并或审计边界，清楚归属后可进入对应阶段处理。

## 九、阶段 3 完成判定

满足以下全部条件，才可将“Phase3 结构性收尾”标为完成并进入阶段 4：

1. contract marker sequence/gap/first-marker 的 endnote/footnote 类型隔离已通过回归测试。
2. Unknown anchor 不会通过直配、OCR repair 或 override 自动成为普通 footnote/endnote `Matched`。
3. Phase3 不覆盖 Phase1/2 facts 的等值测试通过。
4. 无 anchor 的 endnote recovery 章范围行为有明确测试并通过。
5. 已有 gap recovery、paragraph 派生、synthetic footnote、OCR 跨章防护测试没有回归。
6. `cargo fmt --check` 与 `cargo test -p fnm-phase3` 通过。
7. 阶段 3 的 Biopolitics/Goldstein 集成批均自然结束，且没有新增属于 Phase3 P0/P1 的 blocker；属于后续 phase 或 P2 细节的剩余项已附证据归档。
8. 两书 `real_golden_template/` 与固定 Phase3 fixture 均未被当前修复过程覆盖。
9. 被后置的 ignored parity 测试仍保持严格断言，并在交接中明确列为“未通过、阶段 7 处理”，不得表述为完成。

这里的“可进入阶段 4”只表示 Phase3 的职责边界已固定，不表示最终内容 parity 已达交付标准。最终逐段一致与 ignored 清理归阶段 7 验收。

## 十、阶段 3 交接记录模板

修复者交付时填写以下内容，不能只写“测试通过”：

```markdown
# Phase3 结构性收尾交接

完成日期：
修复者：

## 已修 P0/P1
- 问题：
  - 修改文件：
  - 重现测试：
  - 修复结果：

## 保持通过的既有边界
- gap recovery chapter scope：
- paragraph classification source：
- synthetic/ocr cross-chapter 防护：

## 后置到阶段 7 的 P2 差异
- 失败测试或报告：
- 具体差异：
- 为什么不属于 Phase3 职责破坏：
- source/golden 回溯路径：

## 验证结果
- `cargo fmt --check`：
- `cargo test -p fnm-phase3`：
- 显式 ignored parity 结果：
- PyO3 rebuild：
- Biopolitics 批次目录/status/blocker：
- Goldstein 批次目录/status/blocker：
- semantic golden 报告路径：
- golden 无修改检查：

## 结论
- Phase3 P0/P1 是否清空：
- 是否允许进入阶段 4：
- 下一阶段必须读取的证据：
```
