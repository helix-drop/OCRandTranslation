# 阶段 5 计划：Phase4 引用冻结与翻译单元闭合

创建时间：2026-05-23
上位目标：`FNM_REPAIR_MASTER_PLAN.md`
主要审计依据：`FNM_PHASE4_AUDIT.md`
前置交接：`FNM_REPAIR_PHASE4_ORCHESTRATOR.md`

本文给接手阶段 5 的实现者使用。读完本文后，应能直接确定本阶段为什么要修、哪些行为必须保持、哪些文件要先写失败测试再修改、如何判断阶段完成。

> 2026-05-25 状态覆盖：Phase4 freeze blocker 门槛继续保留，但当前实现只视为候选闭合；必须先按 `FNM_REPAIR_PROGRAM_CONTRACT_PLAN.md` 完成 Core 至 repair/编排的顺序复核。用户重新授权前不进行真实批跑或模型请求。

## 一、阶段定位

### 1. 本阶段修什么

阶段 5 对应 pipeline 的 **Phase4**，只处理两项决策：

1. 把 Phase3 已确认 `Matched` 的注释链接冻结为正文中的引用 token。
2. 基于冻结后的正文与 Phase2 的注释事实生成 translation units。

本阶段的可信结果应满足：

- 每个可注入的 matched link 只通过一条权威路径注入一次。
- 每个不可注入的 matched link 留下明确 blocker/review 和可追溯证据。
- 注入失败不得删除原 marker、不得 panic、不得被下游当成成功。
- translation units 必须来自 frozen units，而不是重新扫描 raw pages 后再次猜测/注入。

### 2. 本阶段不修什么

- 不修 Phase3 的 anchor/link 分类与 weak OCR parity 差异；已登记的 strict parity 留到阶段 7。
- 不修 `fnm-phase5` 章节 Markdown 合并与 `fnm-phase6` 导出审计职责倒挂；它们属于阶段 6。
- 不以 `semantic_golden` 的缺章、逐段正文或弱 OCR 差异阻断本阶段；这些报告用于向上游追溯，并在流程合同闭合后集中收敛。
- 不为 Biopolitics 或 Goldstein 加书名特例、marker 黑名单或专书阈值。
- 不修改 `real_golden_template/`，也不使用当前 Rust actual 覆盖 expected fixture。

### 3. 不可破坏的 phase 边界

| 上游事实 | Phase4 允许做的事 | Phase4 禁止做的事 |
|---|---|---|
| Phase1 `ChapterRecord` / page partition | 按现有正文范围产出 units | 重算章节边界、把 note 页扩成正文边界 |
| Phase2 `NoteItem.note_kind` / owner / region | 生成相应 note unit | 重新推断 footnote/endnote 或覆盖 owner |
| Phase3 `Matched` links / body anchors | 按坐标或证据注入 frozen ref | 重做 link 匹配、吞掉 unmatched 或假装注入成功 |
| Phase3.5 repair overrides | 消费已物化的最新 Phase3 输出 | 在 Phase4 内解释或修正 override |

## 二、进入本阶段的已确认基线

### 1. 前序阶段历史状态（当前须按新计划复核）

| 阶段 | 已确认事实 | 本阶段如何使用 |
|---|---|---|
| 阶段 1 | DB/error/trace/PyO3 基础边界闭合 | blocker 和持久化错误必须可见 |
| 阶段 2 | note region/item/kind 是分类事实；双书曾 `ready` | Phase4 只透传 note metadata |
| 阶段 3 | 历史记录曾认为 P0/P1 闭合；后续已重新打开复核 | 只有重新确认后的 matched links 才可作为冻结输入 |
| 阶段 4 | repair 接线、PyO3 与 orchestrator 存在候选实现，待复核 | Phase4 只可接收复核后的最新 Phase3 状态 |

阶段 3 双书证据：

| 书 | 证据目录 | 结果 |
|---|---|---|
| Biopolitics | `output/fnm_real_batch/phase3_linking_closeout/` | `ready`，无 blocker |
| Goldstein | `output/fnm_real_batch/phase3_linking_closeout_goldstein/` | `ready`，无 blocker |

阶段 4 的代码入口与提交事实：

- `fnm-orchestrator/src/pipeline.rs` 已将 Phase4 的 `note_regions` 改为取自 Phase2。
- `fnm-orchestrator/src/mainline.rs` 已包含 repair 后重新物化 Phase3 并供 Phase4-6 消费的路径。
- 当前提交历史包含 orchestrator/LLM repair/PyO3 的阶段 4 修复提交。

若阶段 5 测试发现上述接线退化，应记录为阶段 4 回归并修其源头，不在 `fnm-phase4` 里加补丁掩盖。

### OpenCode Plan 审阅确认

2026-05-23 已将本文、总览与阶段 4 交接文档提交给 OpenCode Plan 会话审阅，使用模型 `deepseek/deepseek-v4-pro`（供应商 DeepSeek）。审阅结论为：**阶段 5 计划已确认，可进入 Build 实施**，不存在开工前必须修订的 P0 缺口。

审阅同时明确三条实现约束，已合并进下方任务描述：

- `frozen_units.body_units` 已完成分段与切块，翻译单元层只能直接映射，不得二次分块或修改文本。
- `freeze_matched_ref_not_injected` 默认复用现有 `fnm_structure_reviews` 持久化，不为 blocker 单独扩 schema；只有证据确实无法保存时才进入任务 8。
- `units` 改为纯派生层后，移除仅服务于旧 raw-page 注入路径的依赖；仍需保留的 metadata 必须说明用途。

### 2. 当前模型与批测口径

阶段交付真实批次继续使用当前模型职责：

| 用途 | 模型 |
|---|---|
| 视觉目录主模型 | `gemini-3.1-flash-lite` |
| LLM repair 主模型 | `glm-4.6v` |
| repair 最后一轮兜底 | `gemini-3.1-flash-lite` |

repair 模型具备视觉能力时，最多附加 5 页页面证据。真实批跑必须保留占位翻译步骤，不得使用 `--skip-translation` 规避导出装配验证。

### 3. 当前基线测试

在编写本计划前核对到的现状：

| 检查 | 结果 | 解读 |
|---|---|---|
| GLM 传输瞬时失败回归测试 | 通过 | repair 基础设施不是本阶段待办 |
| `cargo test -p fnm-orchestrator` | 22 passed | orchestrator 可作为上游入口 |
| `cargo test -p fnm-phase4` | 106 unit + 6 parity-name tests + 8 spec passed | crate 可运行，但不能证明职责正确 |

注意：当前 `biopolitics_phase4_parity.rs` 只读取 golden 后断言 golden 自身数量和字段，不运行 Rust Phase4 输出，因此不是真实 parity 门禁。

## 三、当前代码问题与修复判定

### P0-1 两条引用注入路径导致结果不唯一

位置：

- `fnm-phase4/src/lib.rs`
- `fnm-phase4/src/ref_freeze/mod.rs`
- `fnm-phase4/src/units/mod.rs`
- `fnm-phase4/src/units/ref_inject.rs`
- `fnm-phase4/src/units/body_pages.rs`

现状：

1. `ref_freeze::build_frozen_units()` 已经按 anchors/links 注入 token，生成 `frozen_units.body_units` 和 `ref_map`。
2. 顶层随后调用 `build_phase4_structure_for_units()`，再调用 `units::build_translation_units()`。
3. `build_translation_units()` 从 raw pages 重新构造 body pages，并通过 `units/ref_inject.rs` 再注入一遍。

判定：

- 这是本阶段最高优先级缺陷。Phase4 同一决策存在两条实现路径，任何修补都不能证明最终 translation unit 使用了正确冻结文本。

完成条件：

- `translation_units` 的 body source text 直接从 `frozen_units.body_units` 派生。
- 常规路径不再调用第二套 raw-page ref injection。
- 新测试构造两条旧路径会产生不同结果的输入，并断言顶层输出等于 frozen 路径。

### P0-2 matched link 注入失败没有硬 blocker

位置：

- `fnm-phase4/src/ref_freeze/mod.rs`
- `fnm-phase4/src/reviews.rs`
- `fnm-phase4/src/output.rs`
- 必要时 `fnm-core/src/db/repository.rs`

现状：

- `ref_freeze` 已计算 skipped rows、`error_skip_count` 与内部 `_hard`，但 `_hard` 未进入输出合同。
- `structure_reviews` 没有消费 freeze skip 明细。
- 下游只看到缺少引用的 unit，无法知道 Phase4 注入失败。

完成条件：

- matched link 因 `token_not_found`、`missing_anchor`、非法坐标等不能注入时，输出包含 `freeze_matched_ref_not_injected` blocker/review。
- blocker 可通过持久化读回或阶段报告观察到。
- `summary` 不是唯一证据；失败必须能阻止交付。

### P0-3 Python 字符坐标在 Rust 中被误作 UTF-8 字节坐标

位置：

- `fnm-phase4/src/ref_freeze/inject.rs`

现状：

- `inject_token_once()` 对 `payload[..ce]`、`payload[cs..ce]` 直接 byte slice。
- 实批 DB 的 `char_start/char_end` 源于 Python 字符索引；在法语重音或其它多字节文本中直接按 Rust byte offset 使用会 panic 或误报失败。

完成条件：

- Python 字符 offset 先转换为合法 UTF-8 byte boundary 后再切片，不 panic。
- 超出字符范围且无法通过 marker 证据回退的坐标，返回明确 reason 并形成 blocker。
- 测试至少包含重音/中文字符 offset 成功注入与越界 offset 阻断。

### P1-1 note units 元数据在中间转换中丢失

位置：

- `fnm-phase4/src/lib.rs::build_phase4_structure_for_units`
- `fnm-phase4/src/units/mod.rs`
- `fnm-phase4/src/input.rs`

现状：

- 顶层把 `FrozenUnit` lossy 转回 `NoteItemRecord`，仅填 `note_item_id/chapter_id/page_no/text`。
- `region_id`、`marker`、`note_kind`、`source_page_label` 丢失，note unit 可能被跳过。

完成条件：

- 删除这条 lossy round-trip，或用明确结构保留完整 note metadata。
- 顶层 Phase4 集成测试含 footnote 与 endnote，断言 note units 均存在且 `kind/owner/note_id` 继承上游事实。

### P1-2 note owner 没有优先消费权威 owner

位置：

- `fnm-phase4/src/ref_freeze/inject.rs::resolve_note_item_owner`
- 与 `FrozenUnit.owner_id` 组装相关的代码

现状：

- owner 解析仅看 `chapter_id`/region chapter，未按 Phase2 owner 字段处理 book-scope 或 projection 情况。

完成条件：

- 先检查当前 records 是否已提供 `owner_chapter_id`；如已存在，按权威 owner 优先级实现。
- 若 records 尚无该字段，不得在 Phase4 猜 owner；应先把必要字段加入上游/核心合同并配套持久化。
- Goldstein 的 book-level endnotes 场景必须纳入回归。

### P1-3 注入失败会清理原 marker

位置：

- `fnm-phase4/src/ref_freeze/mod.rs`
- `fnm-phase4/src/ref_freeze/inject.rs::clean_skipped_marker`

现状：

- 若 link 被 skip，代码可能从正文删除 raw marker，导致后续无法看到原始错误证据。

完成条件：

- 失败注入保留正文原 marker。
- 只有被上游明确判定为噪声或重复的记录才可清理，且需独立 decision/reason。
- 回归测试断言失败后 source text 仍含原 marker，同时 blocker 已存在。

## 四、按文件的实施任务

执行时遵循测试先行：每个 P0/P1 先让对应测试失败，再修改实现。

### 任务 1：`fnm-phase4/tests/spec_tests.rs`

新增最低合同测试：

1. `spec_phase4_translation_units_derive_from_frozen_body_units`
   - 构造 raw page 与 frozen 注入结果可能分叉的输入。
   - 断言顶层 `build_phase4_structure()` 产出的 body unit 使用 frozen token 文本。
2. `spec_phase4_keeps_footnote_and_endnote_note_units`
   - 同一 fixture 同时含 footnote/endnote。
   - 断言顶层入口不因 metadata 丢失跳过 note units。
3. `spec_matched_ref_not_injected_becomes_blocker`
   - matched link 无可定位 marker/anchor。
   - 断言输出 review/status 包含 `freeze_matched_ref_not_injected`。
4. `spec_injection_failure_preserves_raw_marker`
   - 注入失败后 source text 中原 marker 保持存在。
5. `spec_book_scope_note_owner_is_preserved`
   - 覆盖 Goldstein 型 book-level endnotes ownership。

这些测试是本阶段必需测试，不用手工拼出专书期望值；涉及书型行为时从真实 fixture 提取最小结构证据。

### 任务 2：`fnm-phase4/src/lib.rs`

目标：建立唯一 Phase4 顶层数据流。

改法：

- 删除或停止调用 `build_phase4_structure_for_units()` 的 lossy 中间结构。
- 将 `frozen_units` 直接传入翻译单元生成路径。
- 将 freeze blocker/review 与单位生成结果一起组装入 `Phase4Output`。
- `summary` 中保留 injected/skipped 数量供观察，但不能用 summary 替代 blocker。

验收：

- 顶层入口测试能同时看到 frozen body units、note units 与 blocker。
- 不再出现“内部 frozen 成功，但持久化 translation units 来自第二套注入”的路径。

### 任务 3：`fnm-phase4/src/units/mod.rs`

目标：将 units 变成 frozen units 的纯派生层。

改法：

- 增加以 `FrozenUnits` 和必要上游 metadata 为输入的生成接口，或重构现有接口使其不再读取 raw pages 做引用物化。
- `frozen_units.body_units` 已在 freeze 路径完成分段和切块；body translation units 只能直接字段映射，不得二次分块、重新识别 marker、重新注入 ref 或修改 source text。
- note units 使用上游携带的 `note_kind` 和 owner，不从丢字段的中间对象反推。
- 删除仅用于旧 raw-page 注入路径的 `raw_pages`、`page_partitions`、endnote 起始页推断等参数；若某项 metadata 仍用于排序或合同检查，应在接口和测试中明确用途。
- 保持 unit 顺序稳定并为同一输入 deterministic。

验收：

- body unit 文本和单元边界 byte-equal frozen body units，不允许二次 chunk segmentation 差异。
- footnote/endnote unit 数与上游可翻译 note unit 对齐。

### 任务 4：`fnm-phase4/src/units/ref_inject.rs` 与 `units/body_pages.rs`

目标：退出常规主链，而不是再增强第二条猜测路径。

改法：

- 若这些函数仅供旧常规路径使用，将其从生产主链移除；保留必要 helper 时清楚标记用途。
- 不新增基于 raw page 的 marker fallback。
- 若删除路径后成为 dead code，删除对应代码和只覆盖旧路径的测试。
- 触及正则时清理 `Lazy<Mutex<HashMap<String, Regex>>>`，不得新加 lint allow。

验收：

- `rg` 能确认顶层 Phase4 不再调用第二套引用注入。
- 无新增动态 regex/Mutex 反模式。

### 任务 5：`fnm-phase4/src/ref_freeze/inject.rs`

目标：让权威注入路径在错误坐标和 owner 上可追溯。

改法：

- 将上游 Python 字符 offset 转换为 Rust UTF-8 byte boundary，并返回含 reason 的结果类型；不要只返回 `(String, bool)` 后丢失原因。
- 区分 `token_not_found`、`coordinate_out_of_range`、`missing_anchor` 等 reason。
- 读取并尊重权威 owner 字段；若核心 records 不足，先扩合同再继续。
- 失败不调用 marker 清理。

验收：

- 法语重音/中文合法字符坐标测试可注入；越界坐标不 panic 且产生 blocker。
- 注入成功路径行为不退化。

### 任务 6：`fnm-phase4/src/ref_freeze/mod.rs`

目标：将冻结结果从诊断摘要提升为正式 gate。

改法：

- 替换当前未消费的 `_hard`/`_soft` 局部值：形成结构化 outcome。
- 所有 matched link 必须落入 injected 或明确 skipped-with-reason；error skip 触发 blocker。
- 保留 skipped rows 的 `link_id/anchor_id/note_item_id/chapter_id/page/reason`。
- 删除“失败即清理 marker”的行为。

验收：

- `matched_link_count = injected + skipped_with_reason`。
- `error_skip_count > 0` 时 Phase4 不可能报告 ready。

### 任务 7：`fnm-phase4/src/reviews.rs` 与 `output.rs`

目标：把 Phase4 自己产生的错误交给调用方和持久化层。

改法：

- `build_structure_reviews()` 接收 freeze error rows，生成 `freeze_matched_ref_not_injected` error review。
- 默认将 `freeze_matched_ref_not_injected` 作为 error review 复用现有 `fnm_structure_reviews` 持久化路径；调用方必须显式将该 review_type 解释为 blocker。
- `Phase4Output` 增加明确状态或 `blocking_reasons` 字段时，不得另造一份与 review 分叉的真相来源。
- `to_products()` 不能丢失阶段 5 判定所需的 review/diagnostic 事实。

验收：

- DB 读回或下游快照能观察到 blocker 与定位证据。
- report 中能定位具体 link/页面，而不只是计数。

### 任务 8：`fnm-core/src/db/repository.rs`、records/schema（仅在持久化合同不足时）

目标：补足跨进程/重新加载后的 Phase4 证据。

决策点：

- 默认以 `fnm_structure_reviews` 存放 blocker 证据，不新增 DB schema。
- 若 Phase5/6 必须读取逐条 frozen ref decision，新增明确结构化持久化产品；不得把 JSON 摘要当唯一真相。

验收：

- 新增/更新的 repository roundtrip 测试覆盖错误注入记录读回。
- 不影响已有 documents 双 schema 和前序 phase 数据合同。

### 任务 9：`fnm-orchestrator/src/pipeline.rs`、`types.rs`、`mainline.rs`、`load.rs`

目标：让新 Phase4 gate 被下游消费。

改法：

- `Phase4Snapshot` 与序列化快照保留 Phase4 blocking evidence。
- `mainline` 持久化不丢 Phase4 reviews/status。
- loader 不在缺少 Phase4 evidence 时默认构造“成功”。
- 不重做阶段 4 repair 路由；仅接收其最新 Phase3 结果。

验收：

- 集成测试构造 injection failure，断言最终 pipeline blocking reason 仍为 Phase4 产生的 `freeze_matched_ref_not_injected`。

### 任务 10：`fnm-phase4/tests/biopolitics_phase4_parity.rs`

目标：把伪 parity 转为真实输出测试。

改法：

- 保留 fixture 格式检查时重命名为 fixture contract 测试。
- 新增运行 Rust Phase4 入口的真实 fixture 测试，对输出的 frozen refs、translation units 和 blocker/reviews 做严格比较。
- expected 数据必须来源可说明；不得以本次 actual 无审查覆盖。
- 如果现有 fixture 本身属于旧内部实现差异，保持失败并登记阶段 7，不为使本阶段绿而降断言。

验收：

- 测试失败能指向 Rust 输出字段，而不是只证明 JSON 可解析。

## 五、本阶段必须新增或强化的测试

| # | 测试目标 | 文件 | 阻断级别 |
|---|---|---|---|
| 1 | translation units 只来自 frozen body units | `tests/spec_tests.rs` | P0 |
| 2 | 顶层入口保留 footnote/endnote note units | `tests/spec_tests.rs` | P0 |
| 3 | matched 注入失败形成 blocker | `tests/spec_tests.rs` | P0 |
| 4 | 注入失败保留原 marker | `tests/spec_tests.rs` | P1 |
| 5 | 非 ASCII 字符坐标正确注入、越界坐标有 reason | `src/ref_freeze/inject.rs` tests | P0 |
| 6 | owner/book-scope note 归属透传 | `tests/spec_tests.rs` | P1 |
| 7 | freeze reviews/products 持久化 roundtrip | `fnm-core` 或 orchestrator tests | P1 |
| 8 | Phase4 blocker 能穿过 orchestrator 到最终状态 | `fnm-orchestrator` tests | P1 |
| 9 | Biopolitics 真实 Rust Phase4 parity/contract | `tests/biopolitics_phase4_parity.rs` | P1；内容 P2 可登记 |
| 10 | Goldstein book-endnotes smoke/contract | 新增或现有集成测试 | P1 |

新增行为测试必须先证明在修改前失败。不能以“已有单测通过”代替本表中的合同测试。

## 六、工程清理与非阻塞遗留

本阶段优先修 P0/P1。以下内容在触及对应文件时一并处理，不为单纯清洁扩大工作范围：

| 项 | 处理原则 |
|---|---|
| `units/ref_inject.rs` 的 Mutex regex cache | 若移出主链或修改该文件，删除/改为无锁方案 |
| `ref_freeze/inject.rs` marker 动态 regex | 若修改注入逻辑，优先复用 `fnm-core` 工具或解析逻辑 |
| 超过 400 行的 `ref_freeze/mod.rs` | 重构 gate/skip handling 时拆出 outcome 或 blocker 子模块 |
| `text/markdown_parse.rs` 大文件及循环 regex | 非唯一冻结路径阻断项；没有触及则登记阶段 6/工程债 |
| `clippy::too_many_arguments` 前序阻断 | 不用 `allow` 掩盖；在相关公共 API 真正需要变更时收束参数结构体 |

## 七、验证流程

### 1. 开发期验证

每个任务先跑新增失败测试，再修复并执行受影响 crate：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo fmt --check
cargo test -p fnm-phase4
cargo test -p fnm-orchestrator
```

涉及 DB contract 时补：

```bash
cargo test -p fnm-core
```

### 2. parity 与证据检查

必须显式运行真实 Phase4 fixture 测试。若发现内容级差异，仅在不属于 P0/P1 的情况下登记阶段 7，不能覆盖 golden：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo test -p fnm-phase4 --test biopolitics_phase4_parity -- --nocapture
```

确认根底本未修改：

```bash
cd /Users/hao/OCRandTranslation
git diff -- test_example/Biopolitics/golden_exports/real_golden_template \
  test_example/post-revolutionary/golden_exports/real_golden_template
```

### 3. 阶段交付回放与真实整批边界

阶段 5 只改 Phase4-6。已有 Phase1-3 验收 DB 足够时，先重建 PyO3 后运行不调用模型的下游回放；它复制源 DB，不覆盖上游验收事实：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs/fnm-py
../../.venv/bin/maturin develop --release

cd /Users/hao/OCRandTranslation
.venv/bin/python scripts/test_fnm_downstream_replay.py --tag phase5_acceptance
```

若目标是验证视觉/repair 网络调用或完成最终内容交付，才必须完整顺序跑两书真实整批。仅为排查 P0/P1 程序合同而修改 Phase1-3 时，应先在相应 crate 和可复制诊断库中逐层验证，不为已知内容差异消耗模型额度。启动真实整批后不能使用 `--skip-translation`，也不能因时间长而中断：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs/fnm-py
../../.venv/bin/python -m maturin develop

cd /Users/hao/OCRandTranslation
PYTHONUNBUFFERED=1 .venv/bin/python scripts/test_fnm_real_batch.py \
  --slug Biopolitics \
  --group all \
  --include-all \
  --batch-tag phase5_ref_freeze_closeout \
  --verbose \
  2>&1 | tee /tmp/phase5_ref_freeze_closeout.console.log

PYTHONUNBUFFERED=1 .venv/bin/python scripts/test_fnm_real_batch.py \
  --slug Goldstein \
  --group all \
  --include-all \
  --batch-tag phase5_ref_freeze_closeout_goldstein \
  --verbose \
  2>&1 | tee /tmp/phase5_ref_freeze_closeout_goldstein.console.log
```

批次必须保留：

- `output/fnm_real_batch/<tag>/runtime_status.json`
- `output/fnm_real_batch/<tag>/results.json`
- `output/fnm_real_batch/<tag>/token_summary.json`
- `output/fnm_real_batch/<tag>/batch_report.md`
- 单书 `fnm_real_test_modules.json` 与 `llm_traces/`

### 4. 完整门禁

交付前运行：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo build --release
cargo fmt --check
cargo test --all
cargo clippy --all-targets -- -D warnings
```

若 clippy 仍仅由已登记的前序 `too_many_arguments` 阻断，报告中逐项列出；阶段 5 不得新增 warning 或 `allow(clippy::*)`。

## 八、完成判定

满足全部条件后，才能把阶段 5 标为完成：

| # | 条件 |
|---|---|
| 1 | 顶层 Phase4 只有一条权威 ref-freeze/injection 路径 |
| 2 | translation units 从 frozen units 派生，不从 raw pages 二次注入 |
| 3 | matched link 无法注入时产生 `freeze_matched_ref_not_injected` blocker/review |
| 4 | Python 字符 offset 可安全转换，越界错误有可追溯 reason |
| 5 | 注入失败保留原 marker，不把失败伪装成正文 clean |
| 6 | note kind 与 owner 透传上游事实，footnote/endnote/book-scope 测试通过 |
| 7 | Phase4 blocker 能持久化并穿过 orchestrator 被最终状态观察 |
| 8 | 真实 Rust Phase4 fixture 测试已建立；P2 差异不被伪装为通过 |
| 9 | `cargo fmt --check` 与受影响 crate 测试通过，无新增 lint 抑制 |
| 10 | 程序合同验收使用已完成上游合同复核后的双书复制库回放且无 Phase4 blocker；真实视觉/repair 与内容交付由后续集成/最终验收执行 |
| 11 | `real_golden_template/` 无改动，actual 未覆盖 expected |

## 九、交接输出要求

实施者完成后应在本文件末尾追加交接记录，至少包括：

1. 按任务号列出的修改文件与实现结果。
2. 新增测试名称及其 RED/GREEN 证据。
3. 双书回放或真实整批目录、状态、blocker、模型调用数与 trace 位置。
4. 已明确后置到阶段 7 的 P2 差异及回溯入口。
5. 若阶段 5 未完成，精确说明阻断在哪个任务和哪条证据，不得写“基本完成”。

## 十、2026-05-24 实施与验收记录

已落地：

- Phase4 translation units 从 `FrozenUnits` 单向映射，freeze 错误通过 `freeze_matched_ref_not_injected` 持久化并由 Phase6 阻断。
- `fnm-core/src/text.rs` 修复 `enriched_markdown=null` 导致正文读取为空的问题。
- `BodyAnchorRecord.char_start/char_end` 合同统一为 Python 字符索引；`fnm-phase3` 与 `fnm-llm-repair` 产出端已按字符写入，`ref_freeze/inject.rs` 仅在切片时转换为 Rust 字节边界，越界记录 `coordinate_out_of_range`。
- `ref_freeze/mod.rs` 使用 anchor 所属章定位正文注入，保留 book-scope note 原归属。
- 新增 `scripts/test_fnm_downstream_replay.py` 与 PyO3 回放入口，双书复制 DB 后只运行 Phase4-6，再在复制库写占位译文并执行翻译后导出检查；模型请求数为 0。

当前验收结论：**阶段 5 尚不能标为交付完成**。

| 书 | 产物 | 回放结果 | 冻结 blocker |
|---|---|---|---|
| Biopolitics | `output/fnm_downstream_replay/phase5_acceptance_final/Biopolitics/` | 上游表未改写；占位译文成功；未放行 | `token_not_found=1` |
| Goldstein | `output/fnm_downstream_replay/phase5_acceptance_final/Goldstein/` | 上游表未改写；占位译文成功；未放行 | `token_not_found=90`, `coordinate_out_of_range=1` |

该回放故意复制坐标合同修复前的 Phase1-3 DB；其结论是旧输入能够被 Phase4 稳定阻断，而不是新 Phase3 已生成干净数据。Goldstein 的主要证据：同一正文坐标存在两条 Phase3 `matched` link，例如 page 288 的 `$ ^{8} $` 同时对应 `link-00395` 与 `link-00495`，Phase4 首次注入后第二条必然无法再注入。下一步应修 Phase3 重复 matched 来源与 Biopolitics page 96 单元缺失来源；由于坐标产出端已经改变，修清后必须运行新的双书真实整批刷新证据，而不是降低 Phase4 blocker。

验证补充：

- `cargo test --all`、`cargo build --release`、Python 批测单测/编译检查通过；`real_golden_template/` 未修改。
- 本阶段实现范围的严格 lint 已闭合：`cargo clippy --no-deps -p fnm-phase4 -p fnm-phase6 --all-targets -- -D warnings` 通过，其中已清除 Phase4 循环内 `Regex::new()` 等违反仓库规范的项目。
- 全 workspace 的 `cargo clippy --all-targets -- -D warnings` 仍被前序或相邻模块债务阻断：`fnm-core` 有 5 个 `too_many_arguments`；隔离检查暴露 `fnm-phase3` 的 `too_many_arguments`/`ptr_arg`、`fnm-llm-repair` 的 `filter_map_bool_then`/`assertions_on_constants`/`redundant_locals`，以及 `fnm-orchestrator` 的参数过多、无效 `.into()`、可派生默认实现等 lint。这些不是降低 Phase4 blocker 的理由，应纳入后续代码质量清理。
- 全量测试过程中复现并修复了 `fnm-llm-repair` trace dump 测试的共享全局用量记录竞争：无预置状态测试不再清空其他并行测试的记录。`cargo test --all` 与 `cargo build --release` 已重新通过。

## 十一、2026-05-25 门槛校正与当前结论

本阶段原先把“上游事实有误后造成的冻结 blocker”和“根底本内容仍不一致”混在同一收口判断里。现按总领计划重新划分：

| 证据 | 说明 | 本阶段判定 |
|---|---|---|
| `phase5_acceptance_final` 中的冻结 blocker | 旧 Phase1-3 输入可稳定触发 Phase4 拒绝，且拒绝是正确行为 | 不应放宽门禁，应回到上游修合同 |
| `phase5_rootfix_diagnostic_v4/` | 刷新上游 link/region 后，Biopolitics 与 Goldstein 复制库均 `blocking=0`；模型请求为 0 | Phase4 冻结合同已有闭合证据 |
| `phase5_rootfix_diagnostic_v5/` | Goldstein 恢复两个具有明确 `doc_title` 证据的章节后仍 `blocking=0` | 上游章节边界变化未打破冻结合同 |
| `semantic_markdown_report.json` 失败 | 仍有缺章、文本与 refs/defs 差异 | 记录为内容/P2 追溯，不作为 Phase4 门禁 |

当前处理策略：

1. 阶段 5 不再因逐段 golden 失败而保持阻断；冻结合同是否成立只看 Phase4 自身事实是否可注入或明确阻断、诊断是否可追溯。
2. 因后续追溯已经修改 Core/Phase1-3，正式确认状态前按 `Core -> Phase1 -> Phase2 -> Phase3 -> LLM repair/编排 -> Phase4` 顺序复核程序合同。
3. 诊断末尾发现 Phase1 漏标题恢复尝试使用了数据库不允许的新 `source` 值，且该识别启发式属于内容调校；当前已将此尝试移出代码变更，Goldstein 剩余漏章留到内容收敛阶段处理。按暂停测试要求，不宣称新的验证结果。
