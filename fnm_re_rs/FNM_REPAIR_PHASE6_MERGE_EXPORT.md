# 阶段 6 交接计划：Phase5 Markdown 合并与 Phase6 导出审计闭合

- 创建时间：2026-05-26
- 核验基线提交：`7754e18`（`fnm: 完成阶段5程序合同收尾并恢复阶段边界`）
- 上位计划：`FNM_REPAIR_MASTER_PLAN.md`
- 主要审计依据：`FNM_PHASE5_AUDIT.md`、`FNM_PHASE6_AUDIT.md`
- 前置交接：`FNM_REPAIR_PHASE5_REF_FREEZE.md`
- 当前状态：**未完成，重新打开验收**（2026-05-26 23:18 最新回放仍出现 Phase5 合并 blocker）

本文是原阶段 6 的实施与交接文档。接手人应按本文先写失败测试，再修改 `fnm-phase5`、`fnm-phase6` 及必要的 orchestrator/持久化接线。阶段 6 解决的是 Markdown 合并和导出审计的程序合同，不在导出层修补内容识别差异。

## 一、先理解阶段编号

本轮总计划中的“阶段”是修复推进顺序，不等于 crate 名字中的 pipeline phase：

| 原修复阶段 | Pipeline 职责 | Rust crate | 当前判定 |
|---|---|---|---|
| 阶段 5 | Phase4 引用冻结与翻译单元 | `fnm-phase4` | 程序合同已完成 |
| **阶段 6** | **Phase5 章节 Markdown 合并 + Phase6 组书/ZIP/导出审计** | **`fnm-phase5`、`fnm-phase6`** | **未完成：存在 `merge_*` blocker 与工程收尾缺口** |
| 阶段 7 | 内容 parity、弱 OCR 与最终发布验收 | 多 crate + 真实批跑 | 不得提前开始收口 |

不得把旧报告中“phase5/phase6 已 100% 完成”的表述当作当前事实。`FNM_RE_REFACTOR.md` 写于 2026-05-19；随后 2026-05-22 审计确认了职责倒挂与错误 ship gate，2026-05-26 总计划已经将这些问题明确转入原阶段 6。

## 二、接手上下文

### 1. 当前为什么可以进入阶段 6

阶段 5 已用新生成的 Phase1-3 数据和无模型复制库回放关闭了 Phase4 冻结合同：

| 书 | Phase4 回放结论 | Translation units | 证据 |
|---|---|---:|---|
| Biopolitics | `phase4_contract_passed=true`，`freeze_blocker_count=0`，上游未改写 | 644 | `output/fnm_downstream_replay/phase5_contract_closeout_20260526_v3/results.json` |
| Goldstein | `phase4_contract_passed=true`，`freeze_blocker_count=0`，上游未改写 | 978 | 同上 |

该回放 `model_requests=0`。因此阶段 6 可以消费 Phase4 已冻结文本与已有结构事实；它不能回头重分类 note、重建 anchor/link 或用导出修补掩盖上游问题。

### 2. 阶段 6 输入的权威事实

| 事实 | 权威来源 | Phase5/6 可以做什么 | 禁止做什么 |
|---|---|---|---|
| 章节边界、顺序、标题 | Phase1 `ChapterRecord` | 按原顺序输出文件、审计缺章/顺序 | 从 note 页重新扩张章节边界 |
| 每个 note 的 `note_kind`、marker、owner/region | Phase2 `NoteItemRecord` / `ChapterNoteModeRecord` | 按既有分类生成定义、审计 raw marker | 根据章内 item 再推断模式或分类 |
| anchor 与 link 结果 | Phase3 `NoteLinkRecord` | 仅用于追溯合同 | 重配、跨章兜底 |
| frozen 正文与 note units | Phase4 `FrozenUnits` / translation units | Phase5 合并成章节 Markdown | 从 raw page 重注入引用 |
| Phase4 blocker | `StructureReviewRecord` | Phase6 纳入最终 gate | 仅写摘要或吞掉 |

### 3. 阶段 6 不负责的内容

- 不修 Biopolitics `review_required` 的内容判断。
- 不收敛 Phase3 ignored parity、bare digit、弱 OCR marker 或漏章节内容差异。
- 不运行真实视觉 TOC 或真实 LLM repair 来碰运气。
- 不修改 `test_example/*/golden_exports/real_golden_template/`，不以当前 Rust 输出覆盖 expected fixture。
- 不要求双书在本阶段必然 `can_ship=true`；若阶段 7 内容差异仍会阻断，必须以准确 blocker 显示，而不是静默失败或下游修正文。

## 三、接手执行规则与剩余工作

本节是接手人的当前执行入口，优先级高于下文历史审计和原实施清单。现有代码已经完成了大量拆分工作，接手人不得把“代码已经存在”误判成“阶段已经验收通过”，也不得跳过下列闭环直接进入阶段 7。

### 1. 当前唯一有效的判定证据

2026-05-26 已重新安装当前 Rust bridge，并执行无模型双书回放：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs/fnm-py
../../.venv/bin/python -m maturin develop --release

cd /Users/hao/OCRandTranslation
.venv/bin/python scripts/test_fnm_downstream_replay.py \
  --tag phase6_verify_rebuilt_20260526 \
  --slug Biopolitics \
  --slug Goldstein
```

最新证据为 `output/fnm_downstream_replay/phase6_verify_rebuilt_20260526/results.json`，`generated_at=2026-05-26T23:18:15`：

| 项 | Biopolitics | Goldstein |
|---|---:|---:|
| `upstream_unchanged` | `true` | `true` |
| `phase4_contract_passed` | `true` | `true` |
| `model_requests` | 0 | 0 |
| `replay.blocking_reasons` | 19 | 10 |
| `export_check.blocking_reasons` | 35 | 16 |
| 本轮 export 新增的 `merge_*` | 17 | 7 |

本轮 `passed=false` 且 `exit_passed=false`。Biopolitics 新增 `merge_frozen_ref_leak` 与 `merge_raw_marker_leak`，Goldstein 新增 `merge_frozen_ref_leak`。因此以下结论已经失效：

- “双书回放没有 Phase5/6 自身 blocker”；
- “剩余 blocker 全部可直接移交阶段 7”；
- “阶段 6 程序合同已关闭”。

### 2. 不可协商的归属规则

1. `merge_*`、ZIP 路径/内容不一致、audit 漏报或误报、`can_ship` 汇总错误、`doc_id` 错写，均由阶段 6 负责。在这些问题清零前，禁止移交阶段 7。
2. `legacy_note_token_leak`、`raw_note_marker_leak`、`duplicate_paragraph`、`chapter_boundary_missing_tail` 只有在证明其已存在于 Phase5 输入、且 Phase5/6 没有新增或改写该问题后，才可登记为上游或阶段 7 内容问题。
3. 若导出复核新产生 `merge_frozen_ref_leak` 或 `merge_raw_marker_leak`，即使根因最终位于 Phase4 输入，也必须重新打开产生错误事实的上游阶段；不得把带有 `merge_*` 的回放报告归档到阶段 7。
4. Phase6 只报告和阻断，不改正文消除错误；不得恢复 canonicalization、乱码修补、重复段折叠或任何静默文本改写。
5. 不得通过删除 blocker、清空已持久化 reason、降低 `can_ship` gate、改变回放统计口径来制造“通过”。重复读取或重复审计不得重复累加同一条 reason。
6. 不得新增 `#[allow(clippy::...)]`、`#![allow(clippy::...)]` 或用 `let _ = ...` 掩盖未使用输入；真实 fixture 必须纳入版本控制后才算交付证据。

### 3. 接手人必须按顺序完成的工作

| 顺序 | 要做的事 | 通过标准 |
|---:|---|---|
| 1 | 为最新双书 `merge_frozen_ref_leak` / `merge_raw_marker_leak` 写失败测试，保存最小真实 fixture 和输入/输出对照 | 未修前测试稳定失败，能区分 Phase4 输入、Phase5 Markdown、Phase6 ZIP 三层 |
| 2 | 逐条定位新增 `merge_*` 的来源 | 每一类 blocker 都有证据说明是 Phase5 未消费 frozen token、Phase5 错写文本，还是 Phase4 已产出错误输入 |
| 3 | 在拥有决策权的最上游阶段修复 | Phase5 负责 Markdown 合同；若 Phase4 输入即违规则重新打开 Phase4，不在 Phase6 修正文 |
| 4 | 清理工程收尾缺口 | 移除 `fnm-phase5/src/render/footnote.rs` 的新增 clippy allow；移除 `fnm-orchestrator/src/load.rs` 的无效 `let _`；将 Goldstein 真实 fixture 纳入变更集 |
| 5 | 重跑阶段 6 证据链并更新本文件、总计划和 `PROGRESS.md` | 新鲜回放无 Phase5/6 blocker 后，文档才可改写为完成 |

### 4. 最终放行口径

以下条件必须同时满足；缺一项均写为“阶段 6 未完成”：

| 验收项 | 要求 |
|---|---|
| 权威输入不被改写 | 双书 `upstream_unchanged=true` 且 `phase4_contract_passed=true` |
| Phase5 合并合同 | 无 `merge_frozen_ref_leak`、`merge_raw_marker_leak`、`merge_local_refs_unclosed` 或缺章节文件 blocker |
| Phase6 导出审计 | 审计真实 ZIP；缺、多、损坏文件均阻断；重复审计不重复累加 reason |
| 最终 gate | `can_ship=false` 时原因完整可追溯；`doc_id` 不被 slug 代替 |
| 责任移交 | 只把已经证明为输入既有、且未被 Phase5/6 新增的内容差异移交阶段 7 |
| 工程质量 | 相关 fmt/test/strict clippy 通过，且无新增 lint allow、无无效忽略、无未纳入变更集的测试 fixture |

## 四、历史核验与已实施背景

### 1. 已读取资料

| 类型 | 文件 |
|---|---|
| 总体入口 | `FNM_REPAIR_MASTER_PLAN.md`、`PROGRESS.md`、`FNM_TESTING.md`、`verification.md` |
| 审计 | `FNM_AUDIT_SUMMARY.md`、`FNM_PHASE5_AUDIT.md`、`FNM_PHASE6_AUDIT.md` |
| 已完成阶段 | `FNM_REPAIR_PHASE2_NOTE_CAPTURE.md`、`FNM_REPAIR_PHASE3_LINKING.md`、`FNM_REPAIR_PHASE4_ORCHESTRATOR.md`、`FNM_REPAIR_PHASE5_REF_FREEZE.md` |
| 补充问题盘点 | `FNM_REPAIR_PROGRAM_CONTRACT_PLAN.md` |

### 2. 开工基线证据：当时导出为何未放行

对阶段 5 最终回放复制库直接读取 `fnm_export_audit.report_json`：

| 书 | DB 中 `doc_id` | 报告内 `doc_id` | `blocking_issue_count` | `can_ship` | `must_fix` 文件数 |
|---|---|---|---:|---:|---:|
| Biopolitics | `0d285c0800db` | `Biopolitics` | 11 | false | 11 |
| Goldstein | `7ba9bca783fd` | `Goldstein` | 8 | false | 8 |

回放顶层 JSON 却只显示两书 `blocking_reasons=[]`、`export_ready_real=false`。也就是说，文件审计已找到 blocker，但 post-translate/回放汇总没有把可行动原因暴露出来。

最直接的阶段 6 自身 bug 已在产物中复现：

| 证据 | 结果 |
|---|---|
| Biopolitics `fnm_chapter_markdowns` 中含 `[1]:` 的章节抽样 | 至少 `ch-fallback-0002/0003/0005/0006` 均有 `[1]:`，没有对应 `[^1]:` |
| Goldstein `fnm_chapter_markdowns` 中含 `[1]:` 的章节数 | 8 |
| 审计结果 | 上述章节被报 `missing_note_definition`、`local_note_contract_broken`，并伴随 raw/legacy marker 问题 |

正文引用已使用 `[^N]`，但 endnote 定义曾输出 `[N]:`（已在 Phase5 渲染中修复为 `[^N]:`，Phase6 旧渲染路径也已被删除）。

### 3. 原审计发现（开工清单，不是当前完成证明）

以下问题在计划编写时发现；多数已有代码改动，但是否闭合只能以第三节的最新回放规则判定。表中的代码位置是开工时证据，不用于声称当前仍缺实现或已经验收：

| 优先级 | 原问题 | 修复证据 | 判定 |
|---|---|---|---|
| P0 | Phase5 反向调用 Phase6 生成章节 Markdown | `fnm-phase5/src/lib.rs:22-23,79-80` 依赖 `fnm_phase6::export::*`；`Cargo.toml` 直接依赖 `fnm-phase6` | 已确认 |
| P0 | Phase5 重建章节边界和章级 note mode | `fnm-phase5/src/phase5_shadow.rs:26-27,52-64`；`convert.rs:31-93,211-250` | 已确认 |
| P0 | endnote 定义格式错误 | `fnm-phase6/src/export/section_render.rs:153-162` 输出 `[N]:`；复制库已复现 | 已确认且已产生 blocker |
| P0 | Phase5 merge gate 不形成结构化 blocker | `fnm-phase5/src/lib.rs:145-203` 只将 gate 写入 `merge_summary`，`_chapter_files_emitted` 还被丢弃 | 已确认 |
| P0 | Phase6 审计不审计实际 ZIP | `fnm-phase6/src/book_assemble/mod.rs:115-147` 创建 `zip_bytes` 后调用 audit 时传 `None` | 已确认 |
| P0 | Phase6 审计缺 note marker 上下文 | `book_assemble/mod.rs:128-144` 构造的 `Phase6Structure` 未填 `note_items` | 已确认 |
| P0 | `can_ship` 不是唯一闭合 gate | `export_audit/mod.rs:301-374` 只以文件及 freeze review 计数判定；`book_assemble/mod.rs:149-235` 的语义/order/raw-marker gate 在 audit 后另算 | 部分修复后仍未闭合 |
| P1 | Phase6 会改变正文内容 | `book_assemble/mod.rs:59-61` 调用 `apply_semantic_canonicalization()`；`canonicalize.rs:103-187` 做乱码修补与重复段折叠 | 已确认 |
| P1 | Phase5 raw marker 函数名义修复但忽略关键序列 | `fnm-phase5/src/marker_rewrite.rs:211-263` 参数 `_marker_note_sequences` 不使用，只处理 legacy token | 已确认 |
| P1 | `doc_id` 被换成 slug | `book_assemble/mod.rs:47` 为 `_doc_id`；`export_audit/mod.rs:350-353` 报告写 `doc_id: slug`；复制库已复现 | 已确认 |
| P1 | 文件级 blocker 没有进入回放/交付原因 | `fnm-orchestrator/src/post_translate.rs:200-304` 最终原因只从 `phase6.status.blocking_reasons` 与翻译 blocker 取；复制库已复现 | 已确认 |
| P2 | audit 内仍动态编译 Regex | `fnm-phase6/src/export_audit/helpers.rs:261,264,352,371,380,383,451` 等 | 已确认 |

### 4. 开工时已变化的审计项

不能照抄 2026-05-22 审计的所有表述：

| 旧审计项 | 当前代码状态 | 阶段 6 处理方式 |
|---|---|---|
| Phase6 完全不消费 Phase4 freeze blocker | `export_audit/mod.rs:8-10,285-315` 已识别 `freeze_matched_ref_not_injected` | 保留并纳入统一 gate 回归测试，不重复声称未接线 |
| `book_assemble` 动态 regex | `canonicalize.rs` / `garbled_repair.rs` 已使用 `Lazy<Regex>` | 不再列为 active defect |
| 严格 clippy 可通过 | 当前 `fnm-phase5` 测试存在 10 个 `field_reassign_with_default` 错误 | 阶段 6 需实际清零，而非引用旧结论 |

### 5. 开工基线命令（历史记录）

2026-05-26 执行：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo test -p fnm-phase5 -p fnm-phase6 --no-fail-fast
cargo clippy --no-deps -p fnm-phase5 -p fnm-phase6 --all-targets -- -D warnings
```

结果：

| 检查 | 结果 |
|---|---|
| `fnm-phase5` 测试 | 44 passed，0 failed，0 ignored |
| `fnm-phase6` 测试 | 149 passed，0 failed，0 ignored |
| 两 crate strict clippy | 失败；先在 `fnm-phase5/src/convert.rs` 与 `phase5_shadow.rs` 测试中命中 10 个 `field_reassign_with_default` |

现有单测通过只能说明旧行为被测试锁住，不能证明 phase 边界或导出合同正确。

## 五、目标架构与单一事实流

### 1. 修复后的职责边界

```text
Phase1 authoritative chapters/order
Phase2 authoritative note items/modes
Phase4 frozen units + Phase4 structure reviews
                 |
                 v
fnm-phase5: 仅生成 ChapterMarkdownSet
  - 使用 frozen 正文
  - 生成 [^N] / [^N]: 闭合的本章注释文本
  - 产生 merge_* blocker，不修 anchor/link/note kind
                 |
                 v
fnm-phase6: 仅组装文件 -> ZIP -> 读取实际 ZIP 审计
  - 不修改 ChapterMarkdownSet 文本
  - 汇总 Phase4/Phase5 blocker 与 Phase6 文件/语义 gate
  - 只输出一个权威 can_ship
```

### 2. 必须作出的接口决策

当前 `ChapterMarkdownSet` 没有状态或 review 字段，`Phase5Products` 也只持久化 markdown 与 diagnostic；因此 Phase5 自己发现的 `merge_local_refs_unclosed`、`merge_frozen_ref_leak`、`merge_raw_marker_leak` 无法可靠流到 Phase6。实施时应采用以下方案：

1. 新增明确的 Phase5 输出/输入结构，而不是继续从 `ChapterLayers` 重建事实。
   - 输入必须含 Phase1 `chapters`、Phase2 `note_items`/`chapter_note_modes`、Phase4 frozen units 与已有 reviews。
   - `ChapterLayers` 若暂留，只可承载已经确定的正文/定义容器数据，不能提供重新分类或重算 boundary 的决策。
2. Phase5 blocker 继续复用 `StructureReviewRecord` 作为唯一持久化载体，不另造第二套 blocker 真相来源。
   - 为 Phase5 使用 `merge_*` review type。
   - 持久化 Phase5 review 时不得覆盖 Phase4 `freeze_matched_ref_not_injected`。
3. Phase6 构建审计输入时接收完整上下文：真实 `doc_id`、Phase2 `note_items`、累计 structure reviews 和 Phase5 输出，而不是 `..Default::default()` 的残缺 `Phase6Structure`。
4. `can_ship` 只能由 Phase6 一处计算并持久化；consumer 只读该结果及同一份 blocker 明细。

### 3. endnote 格式修复的归属

错误代码当前位于 `fnm-phase6/src/export/section_render.rs`，但修复边界完成后，单章 Markdown 定义生成应属于 Phase5。执行顺序应是：

1. 先在当前路径补一个失败测试，锁定 endnote 正文引用和定义必须同时使用 `[^N]` / `[^N]:`。
2. 将章节渲染职责迁到 Phase5 时携带该测试或等价 contract fixture。
3. 最终 Phase6 只验证 ZIP 中合同闭合，不再负责生成注释定义。

不要为了快速变绿只把当前一行 `[N]:` 改成 `[^N]:` 然后保留 Phase5 依赖 Phase6 的结构问题。

## 六、原实施顺序

任务 1 至任务 6 已存在相应代码改动，本节保留为检查覆盖面的背景清单。接手人当前不得从头照单重做，必须先执行第三节定义的失败复现、归属判断和收尾闭环。

所有 bug 修复先写能失败的测试。每一包完成后运行该包涉及的 crate 测试；只有第 7 包才运行复制库回放。

### 任务 0：冻结输入证据与失败测试清单

目的：保证后续重构没有用 actual 覆盖预期，也不丢失现有真实复现。

要做：

1. 保留只读输入基线：
   - `output/fnm_downstream_replay/phase5_contract_closeout_20260526_v3/results.json`
   - 两个复制库中的 `fnm_export_audit.report_json`。
2. 从真实 fixture 提取最小结构输入，建立 Phase5/6 集成测试；fixture 的 expected 只写合同事实，例如 `[^1]:`、章节边界等值、`can_ship` 阻断原因，不复制当前错误章节全文。
3. 给回放报告测试添加“`can_ship=false` 必须能显示 audit blocker 摘要”的失败用例。

新增测试至少包括：

| 测试方向 | 初始应失败原因 |
|---|---|
| endnote 章节定义为 `[^N]:` | 当前输出 `[N]:` |
| Phase5 保持 Phase1 chapter boundary | 当前会合入 note/endnote region 页 |
| Phase5 透传 Phase2 chapter note mode | 当前从 layer 重新推断 |
| Phase5 merge issue 输出 blocker | 当前只写 summary |
| Phase6 实际 ZIP 损坏/缺文件时阻断 | 当前组书审计不读取所生成 ZIP，ZIP 解析错误会降为空集合 |
| `doc_id != slug` 时报告仍保留 doc_id | 当前报告写 slug |
| 回放输出包含 audit 文件 blocker | 当前顶层 `blocking_reasons=[]` |

### 任务 1：Phase5 去掉对 Phase6 的反向依赖

涉及文件：

- `fnm-phase5/Cargo.toml`
- `fnm-phase5/src/lib.rs`
- `fnm-phase5/src/phase5_shadow.rs`
- 新增或拆分的 Phase5 merge/render 模块
- `fnm-orchestrator/src/pipeline.rs`
- `fnm-orchestrator/src/mainline.rs`

实施要求：

1. `fnm-phase5` 最终不得依赖 `fnm-phase6`。
2. 将“本章 frozen body + 本章定义 -> Markdown”的代码归 Phase5 所有；Phase6 不应提供 Phase5 业务 helper。
3. 修改 orchestrator 调用，使 Phase5 显式接收权威 `ChapterRecord`、`NoteItemRecord` 和 `ChapterNoteModeRecord`。
4. 不通过 `ChapterLayer.footnote_items/endnote_items` 推导 chapter mode，不从 note region 页扩写 `ChapterRecord.pages/start_page/end_page`。

完成判定：

- `rg 'fnm_phase6' fnm_re_rs/fnm-phase5` 对业务依赖无命中。
- mixed note 和 book-scope endnote fixture 中，输出章边界/类型等值于输入事实。

### 任务 2：Phase5 合并合同与 blocker 落地

涉及文件：

- `fnm-phase5/src/marker_rewrite.rs`（应拆分职责或删除名义 repair 路径）
- `fnm-phase5/src/diagnostics.rs`
- `fnm-core/src/records.rs`
- `fnm-core/src/db/repository.rs`
- `fnm-orchestrator/src/types.rs` / `mainline.rs` / `load.rs`

实施要求：

1. endnote 和 footnote 的正文引用/定义均以 Obsidian local ref contract 输出：`[^N]` 与 `[^N]: text`。
2. 删除不能由 Phase4 frozen ref 确定的 raw marker“修复”；发现正文残留 raw marker 时生成 `merge_raw_marker_leak` blocker，不猜测替换。
3. `marker_note_sequences` 不能继续作为 `_marker_note_sequences` 被忽略。若不属于合并必要输入，删除参数；若用于正向审计，实际使用并加测试。
4. 下列 merge gate 形成结构化 Phase5 reviews，并持久化后能由 Phase6 读取：
   - `merge_local_refs_unclosed`
   - `merge_frozen_ref_leak`
   - `merge_raw_marker_leak`
   - `merge_chapter_file_missing`
5. contract row 缺失本身必须是 blocker，不能按 `missing=0/orphan=0` 当 clean。
6. `apply_notes_block_format()` 不得悄悄改写定义文本语义；若保留显示用编号前缀，需有明确 contract 测试证明这是要求而非内容污染。

完成判定：

- 当前由 `[N]:` 导致的双书 `missing_note_definition` 不再出现。
- 故障 fixture 中每一类 merge 失败都有 review/blocking reason，重载 DB 后仍可见。

### 任务 3：Phase6 变为只读组装器

涉及文件：

- `fnm-phase6/src/book_assemble/mod.rs`
- `fnm-phase6/src/book_assemble/canonicalize.rs`
- `fnm-phase6/src/book_assemble/garbled_repair.rs`
- `fnm-phase6/src/export/`

实施要求：

1. Phase6 可做路径清洗、换行规范化、index 与 ZIP 容器生成，但不得改变正文段落或注释定义。
2. 移除组书路径中的 `repair_garbled_markdown_blocks()` 与 `canonicalize_adjacent_duplicate_paragraphs()` 内容修改。
3. 如仍需发现乱码或重复段落，把检测结果转为 audit issue；内容是否真正修复应回到产生文本的上游或阶段 7 内容处理。
4. `export/contract.rs` 与 `section_render.rs` 中属于章节 Markdown 生成的逻辑随任务 1 移归 Phase5；Phase6 仅保留与文件打包、审计直接相关的代码。

完成判定：

- 输入 `ChapterMarkdownEntry.markdown_text` 与 ZIP 中对应章文件在允许的容器规范化之外内容等值。
- 构造重复段或乱码 fixture 时，Phase6 报错/阻断而不输出“被修好的”正文。

### 任务 4：以实际 ZIP 为审计对象并补齐上下文

涉及文件：

- `fnm-phase6/src/book_assemble/mod.rs`
- `fnm-phase6/src/export_audit/mod.rs`
- `fnm-phase6/src/export_audit/file_audit.rs`
- `fnm-phase6/src/export_audit/helpers.rs`
- `fnm-phase6/src/lib.rs`
- `fnm-orchestrator/src/pipeline.rs`

实施要求：

1. `build_module_export_bundle()` 生成 ZIP 后，必须以该 `zip_bytes` 调用 audit。
2. `read_zip_markdown_files()` 失败必须产生 blocking audit record 或返回使 Phase6 明确失败的错误；禁止 `unwrap_or_default()`。
3. 比较 bundle 应有的 Markdown 路径与 ZIP 实际路径，缺失、重复或额外文件均形成明确 issue。
4. Phase6 audit 输入必须携带 Phase2 note items，raw marker 检测只能基于本章真实 marker 做正向判断。
5. 若某调用路径确实没有 note marker 上下文，raw marker 检测只能记 diagnostic/incomplete，不能误报或误放行。

完成判定：

- 损坏 ZIP、ZIP 丢章文件、ZIP 多出文件、内存 bundle 与 ZIP 内容分叉均 `can_ship=false` 且有 issue code。
- 双书回放不再因缺 note marker 上下文放大 raw marker 误报。

### 任务 5：统一最终 ship gate、doc_id 与报告可见性

涉及文件：

- `fnm-phase6/src/export_audit/mod.rs`
- `fnm-phase6/src/book_assemble/mod.rs`
- `fnm-orchestrator/src/load.rs`
- `fnm-orchestrator/src/post_translate.rs`
- `scripts/test_fnm_downstream_replay.py`
- 对应 Python/Rust tests

实施要求：

1. 定义唯一 `can_ship` 计算条件，至少全部为真才可放行：
   - Phase4/Phase5 累计结构 blocker 为空。
   - Phase6 file audit blocking issue 为 0。
   - ZIP 读取与文件集合一致性通过。
   - `export_semantic_contract_ok=true`。
   - TOC 顺序、缺章/多章、cross-chapter contamination、book-level raw marker gates 全通过。
2. audit API 必须接收真实 `doc_id`，`slug` 只用于文件名/展示，不得写入 `report.doc_id`。
3. `blocking_reasons` 要包含 file audit/semantic/ZIP/gate 阻断的简明 code；`must_fix_before_next_book` 保留文件明细。
4. post-translate 与回放汇总读取同一份 audit blocker，不能再出现 `can_ship=false` 但 `blocking_reasons=[]`。
5. DB reload 后不得把缺失 summary 默认成成功 gate；缺审计产物继续明确 `export_audit_missing`。

完成判定：

- clean fixture：`can_ship=true`，无 blocker。
- 每种 fault fixture：`can_ship=false`，`blocking_reasons` 能直接解释失败。
- `doc_id="0d285c0800db", slug="Biopolitics"` 的测试输出仍保留真实 `doc_id`。

### 任务 6：工程质量与真实 fixture

涉及文件：

- `fnm-phase5/src/convert.rs`
- `fnm-phase5/src/phase5_shadow.rs`
- `fnm-phase6/src/export_audit/helpers.rs`
- 过大模块的拆分文件
- `fnm-phase5/tests/`、`fnm-phase6/tests/`（新增）

实施要求：

1. 修掉当前 Phase5 strict clippy 的 10 处测试构造错误，不加 `allow()` 压制。
2. 把 `export_audit/helpers.rs` 函数内 `Regex::new()` 全部提升为模块级 `Lazy<Regex>`。
3. 按职责拆分超过 400 行且本阶段正在修改的文件，至少优先处理：
   - `fnm-phase5/src/marker_rewrite.rs`
   - `fnm-phase5/src/convert.rs`
   - `fnm-phase6/src/export_audit/helpers.rs`
   - `fnm-phase6/src/export/section_render.rs`（若逻辑迁移后仍过大）
4. 新增基于 Biopolitics 与 Goldstein 真实 fixture 的 Phase5/6 集成测试；不能只有手工字符串 smoke test。
5. 若建立 expected JSON，只能来自明确合同或 Python 权威输出，并记录生成方式；禁止用修复后的 Rust actual 自我固化。

### 任务 7：无模型集成回放与阶段交付

阶段 6 收尾仍先用无模型复制库，不立即运行真实 API：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo fmt --all --check
cargo test -p fnm-phase5 -p fnm-phase6 -p fnm-orchestrator --no-fail-fast
cargo clippy --no-deps -p fnm-phase5 -p fnm-phase6 -p fnm-orchestrator --all-targets -- -D warnings

cd /Users/hao/OCRandTranslation
.venv/bin/python -m pytest tests/unit/test_fnm_downstream_replay.py -q
.venv/bin/python scripts/test_fnm_downstream_replay.py \
  --tag phase6_merge_export_closeout \
  --slug Biopolitics \
  --slug Goldstein
```

若本阶段修改了 `fnm-py` bridge，回放前还需：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs/fnm-py
../../.venv/bin/python -m maturin develop --release
```

回放判定：

| 结果 | 阶段 6 判定 |
|---|---|
| 出现 `missing_note_definition`，原因仍是 Phase5/6 输出 `[N]:` | 未完成 |
| 出现 `can_ship=false` 但无对应 blocker reason | 未完成 |
| Phase6 修改正文来消除重复/乱码/marker issue | 未完成 |
| Phase5/6 自身合同 issue 清零，但另有带来源的阶段 7 内容 blocker | 阶段 6 可完成，并移交阶段 7 |
| 双书 `can_ship=true` 且无阶段 7 差异 | 可直接进入阶段 7 最终验证，不能跳过真实批跑 |

## 七、建议测试矩阵

| 层次 | 测试用例 | 必须证明的合同 |
|---|---|---|
| Phase5 单元 | mixed footnote/endnote chapter | 不广播 note kind，定义均为 `[^N]:` |
| Phase5 单元 | book-scope endnote 定义页位于书末 | 章节正文 boundary 不被 note 页扩张 |
| Phase5 单元 | raw marker 未由 frozen ref 解释 | 原文不被猜测替换，产生 merge blocker |
| Phase5 单元 | contract row 缺失 | 不能默认为 clean |
| Phase5 持久化 | Phase4 freeze review + Phase5 merge review | 两者均可读回且不互相覆盖 |
| Phase6 单元 | clean chapter set -> ZIP | ZIP audit 通过，`can_ship=true` |
| Phase6 单元 | corrupt/缺文件/多文件 ZIP | audit 阻断且原因可见 |
| Phase6 单元 | status/merge/freeze blocker | 任一 blocker 使 `can_ship=false` |
| Phase6 单元 | semantic/order/raw marker gate false | 统一阻断而非只写摘要 |
| Phase6 单元 | `doc_id != slug` | 报告身份不混淆 |
| 集成 fixture | Biopolitics endnote 章节 | 不再由 `[N]:` 制造 missing definition |
| 集成 fixture | Goldstein book-level endnotes | endnote 定义/owner/boundary 合同闭合 |
| 脚本回放 | 两书复制库 | 顶层报告能展示所有 audit blockers，模型请求为 0 |

## 八、退出条件

阶段 6 只有同时满足以下条件才可标为程序合同完成：

1. `fnm-phase5` 不再依赖 `fnm-phase6` 完成章节 Markdown 生成。
2. Phase5 只消费权威 chapters/note types/frozen units，不重建章节边界或注释分类。
3. 本章引用与定义合同闭合；endnote 不再输出 `[N]:`。
4. Phase5 merge blocker 可持久化、可读回、可阻止 Phase6 放行。
5. Phase6 对输入章节文本只读；没有乱码修补或重复段折叠式静默改文。
6. Phase6 审计实际 ZIP bytes，并带有真实 note marker 上下文。
7. `can_ship` 是唯一、闭合且可解释的最终 gate；`doc_id` 与 slug 正确区分。
8. clean/fault fixture 均通过合同测试；Biopolitics 与 Goldstein 无模型回放中没有 Phase5/6 自身制造的 blocker。
9. 本阶段相关 `cargo fmt`、测试和 strict clippy 通过，不新增 lint `allow()`。

## 九、边缘情况与移交边界

| 边缘情况 | 阶段 6 处理 |
|---|---|
| 同章同时有 footnote/endnote | 按每个 note 的既定 `note_kind` 输出；章级 mode 只作摘要 |
| book-scope endnote 定义页在正文范围外 | 可合并定义，但不修改正文 chapter boundary |
| Phase4 已有 blocker | 原样纳入最终 gate，不再尝试导出修复 |
| 注释定义存在但正文无冻结引用 | 按 Phase5 merge blocker 报出，不输出孤儿定义假装通过 |
| ZIP 不可解压或文件列表不一致 | Phase6 blocking issue |
| 没有 note item 上下文的外部 audit 调用 | 返回 incomplete/diagnostic 或显式要求上下文，不做肯定放行 |
| 检测到乱码/重复段落 | 报告问题，不能在 Phase6 改正文 |
| semantic golden 显示段落/章节内容差异 | 保留证据并移交阶段 7，除非证明由 Phase5/6 改写引起 |

## 十、交接摘要

阶段 6 已完成大量实现改造：Phase5 不再依赖 Phase6、endnote 定义格式已有修复、Phase6 只读化与 ZIP 审计路径已有测试覆盖。但阶段尚未验收通过：2026-05-26 23:18 的新鲜无模型双书回放仍由导出复核新增 `merge_*` blocker，且当前改动仍有新增 lint allow、无效忽略及未纳入变更集的真实 fixture。接手人必须先按第三节关闭这些问题；在新回放满足退出条件之前，不得将阶段 6 标为完成或把全部剩余问题转交阶段 7。
