# FNM 当前程序合同修复交接计划

创建时间：2026-05-25
适用工作区：`/Users/hao/OCRandTranslation`
执行范围：`fnm-core -> fnm-phase1 -> fnm-phase2 -> fnm-phase3 -> fnm-llm-repair / fnm-orchestrator / fnm-py -> fnm-phase4 -> fnm-phase5 -> fnm-phase6`
当前执行约束：**不进行 Biopolitics / Goldstein 真实批跑，不调用视觉 TOC 或真实 LLM repair API。**

## 一、这份文件的作用

本文是当前修复工作的直接交接入口。接手人应先读本文，再按阶段读取审计文件和历史实施记录；不得只凭旧阶段文档中的“已完成”表述继续向下游推进。

本轮目标不是消除全部识别差异，而是确认并修复 Rust pipeline 的程序合同问题：

1. 上游事实不被下游重新分类、覆盖或伪造。
2. 错误和 blocker 能被保存、读回并阻止错误交付。
3. matched link、冻结引用、章节合并、导出审计之间的数据流闭合。
4. 程序合同稳定前，不为单本书的排版/OCR 细节新增规则。

## 二、当前裁决：什么修，什么后置

### 1. 当前必须修的 P0/P1

| 类型 | 例子 | 当前处理方式 |
|---|---|---|
| 事实被覆盖 | Phase3 重建 Phase2 `note_kind` / `chapter_note_modes` | 修代码并写等值保留测试 |
| 跨边界错误匹配 | note 跨章抢正文 anchor；同一 anchor 被多条 matched link 消费 | 修匹配约束并写失败测试 |
| 错误伪装成功 | matched 无法注入但继续导出；缺少 Phase6 数据却返回 ready | 保留/新增硬 blocker |
| 坐标或 schema 合同不闭合 | Python 字符索引被 Rust 当 UTF-8 字节偏移；输出 ID 与持久化 ID 分叉 | 统一合同并覆盖测试 |
| 修补链越权 | LLM repair 创建/改写 Phase2 note 事实；repair 后本轮仍消费旧结构 | 修接线和权限边界 |
| phase 职责倒挂 | Phase5 依赖 Phase6 helper 或 Phase6 修改内容以掩盖上游错误 | 重整职责边界 |

### 2. 当前不作为阶段阻断的 P2 内容问题

以下问题必须记录和保留证据，但不得在本轮驱动逐书启发式修补：

- `semantic_golden` 逐段正文差异、缺章和翻译占位符差异。
- OCR 未把某个模糊标题标成章节标题，例如 Goldstein 特定漏标题页。
- 依赖特定引号、语言符号或版式的弱 marker 提升规则。
- Biopolitics 或 Goldstein 专属阈值、marker 黑名单、页码特判。
- ignored parity 中仅体现识别质量、未证明事实边界被破坏的差异。

### 3. Phase4/历史阶段 5 门槛裁决

`freeze_matched_ref_not_injected` 不应放宽。若 Phase3 宣称一个 link 是 `Matched`，Phase4 必须能把它注入正文，或者用该 blocker 阻止后续交付。

此前 Phase4 blocker 主要由上游章节/link 事实错误触发；在刷新上游候选输出后的无模型复制库诊断中，Biopolitics 与 Goldstein 曾达到 `blocking=0`。因此本轮修复方向是继续向上游追溯合同，而不是关闭冻结门禁。

## 三、资料优先级与状态解释

### 1. 接手阅读顺序

| 顺序 | 文件 | 用途 |
|---|---|---|
| 1 | `fnm_re_rs/FNM_REPAIR_PROGRAM_CONTRACT_PLAN.md` | 当前执行计划，以本文状态和边界为准 |
| 2 | `fnm_re_rs/FNM_REPAIR_MASTER_PLAN.md` | 总目标、phase 边界和历史背景 |
| 3 | `FNM_TESTING.md` | 测试入口、产物和当前禁止真实批跑的边界 |
| 4 | `PROGRESS.md` | 最近追溯事实和尚未复核的候选改动 |
| 5 | `fnm_re_rs/FNM_*_AUDIT.md` | 各 crate 原始问题清单 |
| 6 | `fnm_re_rs/FNM_REPAIR_PHASE*.md` | 历史阶段实施/验收记录，仅作证据 |

### 2. 历史文档状态漂移

旧阶段文档曾把 Phase2、Phase3 和 orchestrator/repair 写成“已完成”或要求立即进行双书真实批跑。后续 Phase4 blocker 追溯又确认了 Phase1/Phase3 上游合同缺陷，并在当前工作区形成新的候选改动。

因此当前规则是：

- 旧文档中的通过记录只证明当时运行结果，不证明当前工作区仍已验收。
- 当前工作区中的候选改动不能因已有测试名或旧总结而直接视为完成。
- 必须按本文顺序，从 Core 开始重新关闭 P0/P1。
- 真实批跑已暂停；旧文档里“阶段交付必须实批”的要求由本文临时覆盖，直至用户另行允许。

### 3. 当前已有证据，不是本轮重新验收

| 证据 | 说明 | 使用边界 |
|---|---|---|
| `output/fnm_downstream_replay/phase5_rootfix_diagnostic_v4/` | 刷新部分上游候选输出后的无模型回放，双书曾 `blocking=0` | 用于定位 Phase4 门槛不是根因，不作为当前代码验收 |
| `output/fnm_downstream_replay/phase5_rootfix_diagnostic_v5/` | 加入 Phase1 明确章节边界候选修复后的无模型回放 | 同上 |
| `semantic_golden` 比较报告 | 显示两书仍有缺章和内容差异 | 仅作后续内容追溯；当前不阻断 P0/P1 |

## 四、工作区现状与接管规则

### 1. 当前有候选修改的模块

当前工作区已有未提交修改，至少覆盖：

| 层 | 有候选修改的文件范围 | 接手动作 |
|---|---|---|
| Core | `fnm-core/src/records.rs`、`fnm-core/src/text.rs` | 按 Core 合同复核，不能先清理或重写 |
| Phase1 | `chapter_skeleton/{builder,fallback}.rs`、`page_partition/**` | 仅保留通用边界修复；排除逐书标题启发式 |
| Phase2 | `note_items/marker_parse.rs`、`note_regions/**` | 核对分类与 region 边界，不以捕获率单独判通过 |
| Phase3 | `body_anchors/**`、`endnote_links.rs`、`note_links.rs`、`lib.rs`、测试 | 优先核对跨章、重复 anchor、ID 和弱证据合同 |
| Repair / 编排 / Bridge | `fnm-llm-repair/**`、`fnm-orchestrator/{lib,mainline}.rs`、`fnm-py/src/lib.rs`、`FNM_RE/__init__.py` | 按 repair 权限和续跑消费链复核 |
| Phase4 | `ref_freeze/**`、`reviews.rs`、`units/mod.rs`、相关测试 | 核对冻结 blocker 和单一注入路径 |
| Phase6 | `diagnostics.rs`、`export/**`、`export_audit/mod.rs`、`lib.rs` | 不得提前认定导出闭合 |
| 测试/脚本 | `FNM_TESTING.md`、`scripts/test_fnm_batch.py`、`scripts/test_fnm_downstream_replay.py`、Python tests | 仅用于无模型验证接线，不启动实批 |

### 2. 接管时不得做的事

1. 不得回退当前已有改动后重新从审计抄写实现；应逐文件审阅候选改动是否满足合同。
2. 不得把 `real_golden_template/` 改成当前 Rust/DB 输出。
3. 不得为通过当前两本书新增书名判断、页码特例、marker 黑名单或经验阈值。
4. 不得启动 `scripts/test_fnm_real_batch.py`、视觉目录请求或真实 repair 请求。
5. 不得从 Phase4/6 blocker 直接在下游放宽检查；必须回到产生错误事实的最早 phase。
6. 不得把未运行过本阶段验证的候选修改报告为“完成”。

## 五、实施方法与统一完成标准

### 1. 每个阶段的工作循环

每个阶段严格执行以下顺序：

1. 读取本阶段审计与当前 diff，列出 P0/P1 与 P2 的分界。
2. 对当前尚未覆盖的 P0/P1，先补可复现的定向测试。
3. 审阅现有候选修改；能满足合同则保留并补验证，不能满足合同则修正。
4. 只运行本阶段不调用模型的测试和必要的上游已关闭回归。
5. 在 `PROGRESS.md` 写清本阶段处理了什么、验证结果、后置 P2。
6. 当前阶段 P0/P1 关闭后，才允许进入下一阶段。

### 2. 当前允许的验证

实施者可运行：

- 单 crate Rust unit/spec/fixture 测试。
- 受影响 crate 的 `cargo fmt --check` 与定向 `cargo clippy`。
- 修改 Python bridge 时的 Python 编译检查、对应 pytest 和必要的 PyO3 本地 rebuild。
- 上游合同关闭后，用复制数据库执行不调用模型的 Phase4-6 下游回放。
- 读取既有报告、SQLite 和 trace 文件做静态/离线追溯。

### 3. 当前禁止的验证

直至用户重新授权，不运行：

- `scripts/test_fnm_real_batch.py`。
- 任何真实视觉 TOC 请求。
- 任何真实 LLM repair API 请求，包括 Gemini 或 GLM。
- 为重新生成内容基线而进行的整书模型流程。

## 六、阶段 A：Core 数据合同

### 目标

确认公共记录、DB 读写、文本提取和坐标单位不会丢失或伪造事实。Core 未关闭前，不进入 Phase1 新修复。

### 已知判断

- `documents` 与 `pages` 是应用导入后的 `doc.db` 输入表；FNM migration 不负责凭空生成 OCR 页面。
- `fnm_*` 表才是 FNM 各阶段持久化产物。
- 当前静态可见：空段落文本保存、`NoteKind::Unknown`、row error 传播、双 schema upsert、null markdown fallback、字符/字节转换已有实现或候选实现。

### 文件级任务

| 文件 | 要核对或实施的内容 | 必须验证的行为 |
|---|---|---|
| `fnm-core/src/segment_codec.rs` | 核对空 `paragraphs` 路径保留顶层 source/display text；若测试不足补 fixture | 空段落 roundtrip 不产生空正文 |
| `fnm-core/src/db/repository.rs` | 核对 `load_raw_pages_for_doc` row error 传播、目录读取错误传播、非法 `note_kind -> Unknown`、`documents` 两种 schema upsert | DB 错误不静默；两 schema 插入/更新可读回；分类不被默认成功态替代 |
| `fnm-core/src/records.rs` | 固定 `BodyAnchorRecord.char_start/char_end` 的单位为 Python 字符索引；所有默认状态必须为 unknown/review 而非 matched | 文档注释与 serde roundtrip 不矛盾 |
| `fnm-core/src/text.rs` | 审阅现有 `enriched_markdown=null` fallback 与字符/UTF-8 字节索引转换 | 重音与中文字符的 offset 转换精确、越界返回失败而非 panic |
| `fnm-core/src/ref_rewriter.rs`、`refs.rs` | 只审查无效 `endnote_mode` 是否会影响当前 P0/P1；若仅是兼容占位则登记 P2 | 当前逻辑不能因无效参数伪造不同模式已生效 |

### 不在本阶段做

- 为 `too_many_arguments` 做公共 API 大重构，除非它阻挡 P0/P1 测试修改。
- 调整内容识别或书型规则。
- 把应用输入表迁移到 FNM migration。

### 退出条件

- Core 所有 P0/P1 有对应定向测试或已存在可核对测试。
- DB 输入前置合同记录清楚。
- 候选 `records.rs` / `text.rs` 修改被确认可保留或已修正。
- 无真实批跑、无模型调用。

## 七、阶段 B：Phase1 页面角色与章节边界

### 目标

Phase1 只决定 page role 与章节骨架。它不得因尾注页面、下级小标题或缺省诊断而产生虚假章节事实。

### 主要程序风险

| 风险 | 是否当前 P0/P1 | 说明 |
|---|---|---|
| TOC semantic diagnostic 被错误读取或默认放行 | 是 | 审计 P1，须核对是否已经真正修复 |
| 明确 `doc_title` 章界被章内子标题截短 | 是 | 会污染下游 chapter ownership；当前已有候选修改 |
| 开始处连续尾注页被误认正文/章节 | 是 | 会制造 fallback chapter 并导致 Phase3 跨章匹配；当前已有候选修改 |
| OCR 没将某个标题标成 `doc_title`，因此漏章 | 否，当前 P2 | 先保留原页证据，不新增特定版式启发式 |

### 文件级任务

| 文件 | 要核对或实施的内容 | 测试要求 |
|---|---|---|
| `fnm-phase1/src/toc_structure.rs`、`chapter_skeleton/toc_semantics/mod.rs` | 核对 diagnostics 字段读写完全一致，不存在缺字段后默认成功 | 构造 semantic gate 失败结构，顶层状态必须阻断 |
| `fnm-phase1/src/chapter_skeleton/fallback.rs` | 审阅候选的“显式章级标题跨度只由下一章级标题界定”改动；不得推广未标注的普通 text 为标题 | 明确 `doc_title` + 章内 subsection fixture 保持完整章节边界 |
| `fnm-phase1/src/chapter_skeleton/builder.rs` | 确认 fallback/TOC 构建消费同一边界事实 | 章节范围落库前后等值 |
| `fnm-phase1/src/page_partition/role_heuristics.rs` | 审阅 leading note page 的通用证据条件 | 连续定义页属于 note；带正文的混合页不被整体错误提升 |
| `fnm-phase1/src/page_partition/continuation/mod.rs`、`page_partition/mod.rs` | 核对 note-run 向前扩展仅限有定义证据的相邻页，不截掉真正 body | 有内部 note band 的正文仍保留 |
| `fnm-phase1/tests/test_phase1_spec.rs`、fixture tests | 补上述 P0/P1 回归测试；用真实 fixture 或从真实页最小抽取的证据片段 | 测试解释规则来源，不加入书名分支 |

### 明确后置

- Goldstein 漏识别未标注章节标题页保留为内容任务。
- 不引入 `ocr_layout_recovery` 一类新 candidate source 来绕过 schema 或识别边界。

### 退出条件

- Page role 与 chapter boundary 的程序合同定向测试通过。
- 现有 Phase1 候选修改仅剩通用、数据驱动的边界修复。
- 未用漏章内容差异阻断本阶段。

## 八、阶段 C：Phase2 注释捕获与分类

### 目标

Phase2 是 `note_kind` 的唯一分类来源。该层必须保证 region/item 分类和 scope 不被跨区域修补污染。

### 必须处理的审计合同

| 项 | 文件范围 | 要求 |
|---|---|---|
| 多页 footnote region 去重不能删合法重复 marker | `note_items/mod.rs` | 去重必须受 region/item identity 约束，不能只凭 marker |
| 年份误标修复不得跨 region/chapter | `note_items/year_filter.rs` | 按 `(chapter_id, region_id, note_kind)` 分组处理 |
| 续行/marker 排序不得使用字符串数序 | `note_items/sequence_repair.rs` | 数字 marker 按数值序列处理 |
| note kind 兜底必须为 Unknown | `note_kind_resolver.rs`、读写路径 | 不把未知项广播成 footnote/endnote |
| endnote candidate / raw region 规则只能用数据证据 | `note_regions/endnote_candidate.rs`、`endnote_regions_raw.rs`、`mod.rs` | 审阅当前 post-body note candidate 候选修改是否会混入正文 footnote band |

### 当前候选修改的处理

当前 `marker_parse.rs` 与 `note_regions/**` 有修改，意图是接受正文结束后的可解析尾注页。接手人必须先证明：

1. 只在最后正文之后应用。
2. 不把章内 footnote band 提升为 book endnote。
3. 不通过章级 `note_mode` 覆盖逐 item `note_kind`。
4. 输出给 Phase3 的 `region_id`、`chapter_id`、scope 与 kind 可追溯。

### 文件级任务

| 文件 | 要做什么 | 测试要求 |
|---|---|---|
| `fnm-phase2/src/note_kind_resolver.rs` | 作为唯一 dispatch 入口复核所有调用者 | mixed footnote/endnote/unknown fixture 逐 item 等值 |
| `fnm-phase2/src/note_items/{mod,year_filter,sequence_repair,marker_parse}.rs` | 关闭去重、年份修复、数字排序与解析边界污染 | 不同 region 相同 marker 均保留；跨章年份不影响合法 note |
| `fnm-phase2/src/note_regions/{mod,endnote_candidate,endnote_regions_raw,footnote_band}.rs` | 限制 candidate 与 region 合并边界 | 后正文尾注页可捕获；章内脚注不错误重类 |
| `fnm-phase2/src/chapter_split/**`、`output.rs` | 检查 chapter summary 不广播覆盖 item facts | summary 可与逐 item 不同而不改 item |
| `fnm-phase2/tests/test_phase2_spec.rs`、fixture/parity tests | 强化事实合同测试 | parity 内容差异可登记，但类型/scope 不得放行 |

### 退出条件

- `note_kind` 分类来源唯一，Unknown 能贯穿输出。
- 不存在跨 region/chapter 的清理或序列修补。
- 当前候选 region 改动被测试证明不扩大分类边界。

## 九、阶段 D：Phase3 锚点与链接匹配

### 目标

Phase3 只检测 anchor、建立 link、记录 unmatched/override；不能重建或覆盖 Phase1/2 事实。

### 已确认的程序错误和候选修复

| 错误 | 当前候选文件 | 修复方向 |
|---|---|---|
| fallback/book-scope note 可跨章抢 anchor | `endnote_links.rs`、`note_links.rs` | 没有 owner evidence 时不得跨章自动 matched |
| 对外 `effective_links` 与持久化 `structure.note_links` ID 分叉 | `lib.rs` | public output 与 DB persistence 使用同一编号后的列表 |
| 相同 anchor 被重复消费 | link resolution 路径与测试 | 一对一消费成为硬合同 |
| weak/synthetic gap anchor 伪装成可注入 matched | `body_anchors/gap_recovery.rs` | 只保留“弱证据不能无条件匹配”的合同；特定右引号启发式不作为本轮通过依据 |

### 还需按审计核查的合同

| 文件 | 核查点 |
|---|---|
| `note_linking/phase2_rebuild.rs`、`input.rs`、`lib.rs` | 不重新构造或覆盖 Phase2 的 `chapter_note_modes`、regions/items |
| `footnote_links.rs`、`note_links.rs` | Unknown anchor 不得变成普通 matched footnote/endnote |
| `note_linking/chapter_contracts.rs` | footnote 与 endnote 的 definition/anchor/gap 计数隔离 |
| `note_linking/link_overrides.rs`、`anchor_overrides.rs` | override 不允许 unknown 候选挤掉明确 kind anchor |
| `paragraph_footnotes.rs`、`paragraph_endnotes.rs` | 不重新解析定义并替代 Phase2 权威 note item |

### 文件级任务

| 文件 | 要做什么 | 必须验证的行为 |
|---|---|---|
| `fnm-phase3/src/endnote_links.rs`、`note_links.rs` | 审阅并完成不跨章匹配与一对一消费合同 | fallback note 不偷取其它章 anchor；重复 matched 被阻断 |
| `fnm-phase3/src/lib.rs` | 统一对外/持久化 link ID 和 Phase2 facts 透传 | 两个公开 link view JSON 等值 |
| `fnm-phase3/src/body_anchors/{pattern_scan,context_guard,gap_recovery}.rs` | 固定字符 offset 合同；隔离 weak evidence | 非 ASCII 坐标正确；synthetic evidence 不自动可冻结 |
| `fnm-phase3/src/note_linking/**` | 逐项比对审计 P1/P2 是否仍会改上游事实 | 输入 regions/items/modes 输出前后等值 |
| `fnm-phase3/tests/test_phase3_spec.rs`、`biopolitics_phase3_parity.rs` | 保留/完善 P0 回归；parity 内容失败只登记 | 程序合同测试不得 ignore |

### 明确后置

- 不为特定法语引号附近 bare digit 建通用成功规则，除非后续内容阶段有跨书证据。
- 不修改根底本使 parity 通过。

### 退出条件

- 无跨章自动 matched、无重复 anchor 消费、无 public/DB link ID 分叉。
- Phase2 facts 做 JSON 级等值透传。
- weak evidence 不会伪装为已可注入的 matched link。

## 十、阶段 E：LLM Repair、Orchestrator 与 PyO3 接线

### 目标

Repair 只能在 Phase3.5 辅助 anchor/link，不得创建或重分类 Phase2 事实；编排必须消费 repair 后的新事实，并可靠报告错误和 incomplete 状态。

### 文件级任务

| 文件 | 要核对或实施的内容 | 测试要求 |
|---|---|---|
| `fnm-llm-repair/src/override_materializer.rs`、`response_parser.rs`、`run.rs` | 禁止创建/改写 note item 分类；action ID 必须属于当前 cluster；partial write 明确报告 | 非法 action 不落库；失败报告 partial 状态 |
| `fnm-llm-repair/src/strategies/fuzzy.rs`、`page_context.rs` | 坐标统一为字符索引；正文上下文范围不能因 role 读取失败静默放宽 | 非 ASCII anchor 坐标可交给 Phase4 正确注入 |
| `fnm-llm-repair/src/llm_client/{request,error}.rs`、`trace/dump.rs` | HTTP 400/429 原始 message 与 body 可追踪；trace 并行用量不互相清空 | 使用模拟响应/fixture，不发送真实请求 |
| `fnm-orchestrator/src/mainline.rs`、`pipeline.rs` | repair auto-applied 后重新构建 Phase3 并把最新 links 送入 Phase4；现有 `replay_phase4_to6_from_db()` 候选入口不得以 `..Default::default()` 伪造未持久化的上游 gate 为成功或失败 | override 后同轮 Phase4 看见 matched；回放不改 Phase1-3 表，且其状态只报告可由 DB 重建的事实 |
| `fnm-orchestrator/src/load.rs`、`types.rs` | 缺 export/audit 时返回 incomplete；summary bool 不得靠 `Default` 假失败/假成功 | 缺产物明确阻断；已有事实字段可读回 |
| `fnm-py/src/lib.rs`、`FNM_RE/__init__.py` | 错误转 PyResult、配置/trace callback 透传、status 与 Rust 事实一致 | 无 panic；Python 参数确实到达 Rust |

### 当前不运行真实 API 的处理方式

- Provider 400/429 只用已有 trace fixture、构造 HTTP error response 或本地单测验证。
- Gemini/GLM 模型角色和频率限制保留配置，不在本轮通过网络调用确认效果。
- 页面上下文最多 5 页的接线变更若已存在，仅验证参数/裁剪逻辑，不发请求。

### 退出条件

- Repair 不越过 Phase2 权限边界。
- auto-applied repair 在同次流程中能被 Phase4 消费。
- 错误、partial 和 incomplete 可在 Rust/Python 两侧观察。
- 所有验证均不调用真实 API。

## 十一、阶段 F：Phase4 引用冻结与 Translation Units

注：这是 pipeline 的 `fnm-phase4`，在历史项目计划中曾称“阶段 5”。

### 目标

将 Phase3 已匹配引用可靠注入正文，并从冻结后的唯一事实生成 translation units。

### 文件级任务

| 文件 | 要核对或实施的内容 | 测试要求 |
|---|---|---|
| `fnm-phase4/src/ref_freeze/inject.rs` | Python 字符 offset 转 UTF-8 字节边界；失败有 reason；不 panic | 重音/中文成功注入；越界产生 blocker |
| `fnm-phase4/src/ref_freeze/mod.rs` | matched 注入失败生成 `freeze_matched_ref_not_injected`；失败保留原 marker | 不可注入 link 阻断后续 |
| `fnm-phase4/src/lib.rs` | 顶层只调用唯一冻结路径；不丢 footnote/endnote units | units 和 reviews 均进入 output |
| `fnm-phase4/src/units/mod.rs` | body units 从 `frozen_units.body_units` 直接映射，不再次切块或重新注入 | 输入 frozen text 与 unit text 等值 |
| `fnm-phase4/src/units/ref_inject.rs`、`units/body_pages.rs` | 删除或停止使用第二条正文 ref 注入路径 | 测试证明不会发生双注入 |
| `fnm-phase4/src/reviews.rs`、`output.rs` | blocker 复用结构 review 持久化路径，不建立分叉真相来源 | review roundtrip 保留 reason/link ID |
| `fnm-orchestrator/src/mainline.rs`、`fnm-core/src/db/repository.rs` | blocker 持久化并传入导出状态 | 最终状态看见 freeze blocker |

### 退出条件

- Matched 必须注入或阻断。
- 只有一条注入路径。
- Translation units 不重读 raw pages 重新物化引用。
- Phase4 blocker 能被 Phase6 审计读取。

## 十二、阶段 G：Phase5 章节 Markdown 合并

### 目标

Phase5 只把 Phase4 已冻结的 body 和 note definitions 合并成章节 Markdown，不重新匹配、不重分类、不在本层猜测章节边界。

### 当前重点：该 crate 尚未因 Phase4 候选修复而自动闭合

当前工作区主要改动集中在 Phase4/6，并不等于 `fnm-phase5` 审计中的 P1 已解决。本阶段必须单独实施。

### 文件级任务

| 文件 | 要做什么 | 测试要求 |
|---|---|---|
| `fnm-phase5/src/lib.rs` | 移除对 Phase6 export helper 的反向依赖；仅消费 Phase4/上游明确输入；merge gate 形成硬 blocker | Phase5 可在不调用 Phase6 修正器的情况下构建结果 |
| `fnm-phase5/src/marker_rewrite.rs` | 审查 residual raw marker rewrite：若无法由已知 link/note 序列确定，不得名义修复；改为 blocker | 未知 raw marker 不被静默改写 |
| `fnm-phase5/src/phase5_shadow.rs` | 不重新推断 chapter note mode，不重新扩张章节范围 | 输入 mode/boundary 透传等值 |
| `fnm-phase5/src/convert.rs` | 转换层保留 `note_kind`、owner 与 link identity | footnote/endnote/book-scope metadata 不丢失 |
| `fnm-phase5/src/diagnostics.rs` | diagnostics 只报告问题，不修正文或替代 gate | blocker 可观察且不改变 markdown |

### 退出条件

- Phase5 不依赖 Phase6 才能完成自身决策。
- 不重推 note mode、chapter boundary 或 link。
- raw marker、unclosed local ref、frozen token leak 形成明确 blocker。

## 十三、阶段 H：Phase6 导出与审计

### 目标

Phase6 组装导出并判断是否可交付；不得修改正文内容来隐藏 Phase5 或更上游错误。

### 文件级任务

| 文件 | 要做什么 | 测试要求 |
|---|---|---|
| `fnm-phase6/src/export_audit/mod.rs` | 审阅现有 freeze blocker 消费候选改动；`can_ship` 必须综合结构 blocker 与文件审计 | `freeze_matched_ref_not_injected` 明确令 `can_ship=false` |
| `fnm-phase6/src/export_audit/file_audit.rs`、`helpers.rs` | 验证 ZIP 实际内容、raw marker leak 与 note_items 上下文；移除函数内动态 regex | ZIP 字节与报告一致；无上下文不假判成功 |
| `fnm-phase6/src/export/**` | 对齐 endnote definition 与正文引用 contract；不在导出时重分类 | 输出引用/定义合同一致 |
| `fnm-phase6/src/book_assemble/{garbled_repair,canonicalize}.rs` | 内容级乱码修补/重复段折叠不得静默改变最终正文；必要时改成审计问题或后置任务 | 上游错误不会因导出 normalization 消失 |
| `fnm-phase6/src/diagnostics.rs`、`lib.rs` | diagnostics 与 audit 状态同一事实来源；`doc_id`/slug 不混用 | status 与 audit 报告一致 |

### 退出条件

- `can_ship` 会受所有程序级 blocker 阻断。
- ZIP 审计读取实际导出字节。
- Phase6 不再用内容修补掩盖上游断层。

## 十四、无真实批跑的验证矩阵

本计划的实施验证必须分层进行。命令仅供接手人实际修复时运行；本计划编写过程中未执行。

| 修复范围 | 开发验证 | 本轮阶段退出验证 | 禁止事项 |
|---|---|---|---|
| Core | `cargo test -p fnm-core` 中的定向测试 | `cargo fmt --check` + `cargo test -p fnm-core` | 不跑批 |
| Phase1 | 新增 spec 先红后绿 | `cargo test -p fnm-phase1` | 不用真实视觉 TOC |
| Phase2 | note item/region/kind 定向测试 | `cargo test -p fnm-phase2` | 不调 LLM/OCR 修补 API |
| Phase3 | link/contract/ID/synthetic 定向测试 | `cargo test -p fnm-phase3`，内容 parity 失败单列 | 不以改 golden 消除失败 |
| Repair/Orchestrator/PyO3 | 模拟 response、fixture、bridge tests | 受影响 crate 测试；修改 bridge 才 rebuild 与跑对应 pytest | 不发真实 repair 请求 |
| Phase4 | freeze/unit/review 定向测试 | `cargo test -p fnm-phase4` | 不放宽 blocker |
| Phase5 | merge/gate 定向测试 | `cargo test -p fnm-phase5` | 不从 Phase6 helper 倒借业务逻辑 |
| Phase6 | audit/export/ZIP 定向测试 | `cargo test -p fnm-phase6` | 不静默修正文 |
| Phase4-6 集成 | 上游全部合同关闭后，复制 DB 下游回放 | `scripts/test_fnm_downstream_replay.py`，确认模型请求为 0 | 不运行真实批测 |

### 仅在最后允许的无模型集成动作

当 Core 至 Phase6 的 P0/P1 均按顺序关闭后，可以运行复制库下游回放，条件是：

1. 输入 DB 明确来自已复核的 Phase1-3 facts。
2. 脚本只复制 DB 并执行 Phase4-6，不覆盖源 DB。
3. 输出报告明确记录 `llm_repair`/视觉请求数为 0。
4. 若 blocker 仍在，继续追溯到最早产生错误事实的 phase，不启动真实批跑碰运气。

## 十五、交付记录模板

接手人每关闭一个阶段，都在 `PROGRESS.md` 追加以下内容：

```markdown
## YYYY-MM-DD 程序合同复核：<stage>

### 处理的问题
| 等级 | 合同问题 | 最早责任文件 | 处理结论 |
|---|---|---|---|

### 修改文件
| 文件 | 改动 | 为什么属于程序合同而非内容调校 |
|---|---|---|

### 验证
| 命令/检查 | 结果 | 是否调用模型 |
|---|---|---|

### 后置问题
| 问题 | 为什么是 P2/后置 | 证据路径 |
|---|---|---|

### 下一阶段门槛
- 当前阶段 P0/P1 是否关闭：
- 是否允许进入下一阶段：
```

## 十六、最终完成判定与后续真实批跑

### 本计划完成的判定

只有满足以下全部条件，才能报告“程序合同修复完成，可申请真实集成验收”：

1. Core 至 Phase6 按本文顺序逐层复核，无未关闭 P0/P1。
2. 每个修复都有定向测试或明确可重复的离线诊断证据。
3. `note_kind`、owner、chapter boundary、anchor/link identity 不被下游重建覆盖。
4. repair 不越权，错误与 incomplete 状态可追踪。
5. matched freeze、merge、export blocker 能阻断错误交付。
6. 不修改 `real_golden_template/`，不掩盖已有内容 parity 差异。
7. 无模型复制 DB 下游回放通过，或明确记录其暴露的最早未关闭合同问题。

### 本计划结束后才讨论的事项

- 是否重新开启 Biopolitics 与 Goldstein 真实整批。
- 是否重新请求视觉 TOC / GLM repair / Gemini 兜底 trace。
- 是否进入 `semantic_golden` 逐段收敛、缺章识别和弱 OCR 识别增强。

在用户重新授权之前，上述真实批跑和内容调校均不属于接手人的执行任务。
