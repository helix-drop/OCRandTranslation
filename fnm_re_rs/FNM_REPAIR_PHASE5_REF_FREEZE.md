# 阶段 5 计划：Phase4 引用冻结与翻译单元闭合

创建时间：2026-05-23
上位目标：`FNM_REPAIR_MASTER_PLAN.md`
主要审计依据：`FNM_PHASE4_AUDIT.md`
前置交接：`FNM_REPAIR_PHASE4_ORCHESTRATOR.md`

本文给接手阶段 5 的实现者使用。读完本文后，应能直接确定本阶段为什么要修、哪些行为必须保持、哪些文件要先写失败测试再修改、如何判断阶段完成。

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

### 1. 前序阶段状态

| 阶段 | 已确认事实 | 本阶段如何使用 |
|---|---|---|
| 阶段 1 | DB/error/trace/PyO3 基础边界闭合 | blocker 和持久化错误必须可见 |
| 阶段 2 | note region/item/kind 是分类事实；双书曾 `ready` | Phase4 只透传 note metadata |
| 阶段 3 | P0/P1 链接边界闭合；双书真实整批通过 | matched links 可作为冻结输入 |
| 阶段 4 | repair 接线、PyO3 与 orchestrator 闭合已完成 | Phase4 将接收 repair 后的最新 Phase3 状态 |

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

### P0-3 UTF-8 非边界坐标可能 panic

位置：

- `fnm-phase4/src/ref_freeze/inject.rs`

现状：

- `inject_token_once()` 对 `payload[..ce]`、`payload[cs..ce]` 直接 byte slice，未验证 `is_char_boundary()`。
- repair/视觉/override 坐标落在法语重音或其它多字节字符中间时会 panic。

完成条件：

- 非 UTF-8 边界坐标返回明确的未注入结果与 reason，不 panic。
- 测试至少包含重音文本和非边界 offset。
- 坐标单位在记录类型或函数文档中明确为 byte offset。

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

- 给坐标切片增加 UTF-8 boundary 校验，并返回含 reason 的结果类型；不要只返回 `(String, bool)` 后丢失原因。
- 区分 `token_not_found`、`invalid_utf8_boundary`、`missing_anchor` 等 reason。
- 读取并尊重权威 owner 字段；若核心 records 不足，先扩合同再继续。
- 失败不调用 marker 清理。

验收：

- 法语重音/中文非边界坐标测试不 panic，并产生 blocker。
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
| 5 | 非 ASCII 非边界坐标不 panic 且有 reason | `src/ref_freeze/inject.rs` tests | P0 |
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

### 3. 阶段交付真实整批

阶段 5 改变最终业务输出，交付前必须重建 PyO3 并完整顺序跑两书。不能使用 `--skip-translation`，不能因时间长而中断：

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
| 4 | 非 UTF-8 边界坐标不 panic，错误有可追溯 reason |
| 5 | 注入失败保留原 marker，不把失败伪装成正文 clean |
| 6 | note kind 与 owner 透传上游事实，footnote/endnote/book-scope 测试通过 |
| 7 | Phase4 blocker 能持久化并穿过 orchestrator 被最终状态观察 |
| 8 | 真实 Rust Phase4 fixture 测试已建立；P2 差异不被伪装为通过 |
| 9 | `cargo fmt --check` 与受影响 crate 测试通过，无新增 lint 抑制 |
| 10 | Biopolitics 与 Goldstein 完整真实批次自然结束，无新增阶段 5 P0/P1 blocker |
| 11 | `real_golden_template/` 无改动，actual 未覆盖 expected |

## 九、交接输出要求

实施者完成后应在本文件末尾追加交接记录，至少包括：

1. 按任务号列出的修改文件与实现结果。
2. 新增测试名称及其 RED/GREEN 证据。
3. 双书整批目录、状态、blocker、模型调用数与 trace 位置。
4. 已明确后置到阶段 7 的 P2 差异及回溯入口。
5. 若阶段 5 未完成，精确说明阻断在哪个任务和哪条证据，不得写“基本完成”。
