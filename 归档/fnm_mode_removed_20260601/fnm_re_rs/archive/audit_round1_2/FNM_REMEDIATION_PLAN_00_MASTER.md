# FNM Rust 修复总纲（Master Plan）

> **本文件是给执行修复的大模型看的总纲。** 它提供自包含上下文、审计文件地图、代码地图、批次划分与依赖顺序。
> 每个批次的**步骤级详细计划**在单独文件（见 §6），本文件只给范围与边界。
> 约束：**仅修程序逻辑 / Rust 风格 / 死代码，不碰业务逻辑**。
> 编制：Claude（claude-opus-4-8）｜日期：2026-05-29
> **进度更新**：2026-05-30（B1-B4 完成，B3 部分完成，B5 未开始）

---

## 0. 进度总览（2026-05-30）

| 批次 | 状态 | 完成度 | 备注 |
|---|---|---|---|
| **B1** 数据/panic | ✅ 完成 | 11/11 | 15 个新测试，clippy 0 warning |
| **B2** 死代码清理 | ✅ 完成 | 全部 | 含 Python 对照确认集成缺口保留 |
| **B3** LLM 接入 | ⚠️ 部分完成 | S1+S4 完成，S2+S3 基础设施就绪 | S2/S3 需 orchestrator post-phase3 步骤（与 B5 无关） |
| **B4** 逻辑/契约 | ✅ 完成 | 10/10 | DB enum 统一、review_id、visible_idx 等 |
| **B5** 质量 | ⏳ 未开始 | 0/10 | 详细计划见 `FNM_REMEDIATION_PLAN_05_quality.md` |

**当前测试基线**：842 passed / 0 failed / clippy 0 warning（48 个文件变更）

**B3 部分完成原因**：S2/S3 依赖 Phase 3 的 body_anchors 产物作为输入，但 Phase 2 在 Phase 3 之前执行。原计划假设 S2/S3 在 Phase 2 内部执行，实际验证源码后发现不可行。正确执行位置是 orchestrator 层 post-phase3，需要添加新的执行步骤，这是独立工程量，与 B5 无关。详见 `FNM_REMEDIATION_PLAN_03_llm_integration.md` §0「关键架构发现」。

---

## 1. 给执行模型的须知（先读这一节）

1. **你接手的是一个已审计、可编译、clippy 0 warning、测试通过的 Rust workspace。** 不要从零理解全部代码——按批次只读「该批次涉及文件 + 对应审计文件」即可。
2. **逐批次执行，一个批次一个分支/提交序列。** 不要跨批次混改。每批次结束跑 §5 验证。
3. **不可破坏的底线**：
   - `cargo clippy --workspace --all-targets` 必须保持 **0 warning**；
   - `cargo test --workspace` 不得新增失败（先记录基线）；
   - 不得违反 `CLAUDE.md` / `AGENTS.md` 的铁律（§2 列出关键条）；
   - A 档 crate（phase3/4/5/6/llm-repair，见 §3）质量已达标，**改动要克制**，主要在 B 档（core/phase1/phase2）和接入工程（批次3）。
4. **改代码前先说明方案**（CLAUDE.md 约束2）；**改 bug 先写能复现的测试再修**（约束5）；**写完列边缘情况并自验**（约束6）。
5. **全程中文注释/提交信息**（约束1）。

---

## 2. 项目上下文（自包含）

### 2.1 这是什么
`fnm_re_rs` 是 Python 项目 `FNM_RE`（书籍 OCR→脚注/尾注结构化→翻译→Obsidian 导出）的 **Rust 重写**。数据流分 6 个 phase + 1 个修复回环 + 编排 + Python 绑定，共 **10 个 crate / 268 源文件 / ~63.8k 行**。

### 2.2 crate 依赖与职责（数据流自上而下）
```
fnm-core        基础设施：类型/records/DB(SQLite,rusqlite+r2d2)/segment 编解码/vision(ResolvedModelSpec,HTTP_CLIENT,PDFIUM)/token
  ├─ fnm-phase1   页面角色 + 章节骨架（TOC 语义、heading graph、fallback）
  ├─ fnm-phase2   note 分类（note_kind 全书唯一来源）+ 聚合
  ├─ fnm-phase3   body anchor 检测 + note link 匹配
  ├─ fnm-phase4   引用冻结注入 + 翻译单元切分
  ├─ fnm-llm-repair  Phase3.5：LLM 修补未解析 link（已接入，async+vision）
  ├─ fnm-phase5   章 markdown 合并
  ├─ fnm-phase6   导出 + 审计（ZIP）
  ├─ fnm-orchestrator  pipeline 串联 + DB 持久化 + 按页翻译 job + LLM repair 接入
  └─ fnm-py       PyO3 绑定，把上述能力暴露给 Python（37 个 #[pyfunction]）
```
- **两个 pipeline 入口**：`run_pipeline`（纯内存）、`run_pipeline_for_doc`/`run_pipeline_from_db`（DB-driven，逐 phase persist）。
- **LLM repair** 不在 `run_pipeline` 内，由 caller（mainline phase3.5 / post_translate / py）显式调用——这是设计，非缺陷。
- **翻译**在 pipeline 之后，由 Python 调 orchestrator 的 `page_translate::*`（经 fnm-py 暴露）执行。

### 2.3 质量分层（决定改动力度）
| 档 | crate | 处理原则 |
|---|---|---|
| **A 高质量（后期重构）** | phase3 / phase4 / phase5 / phase6 / llm-repair | 仅做点状修复（panic/死代码），**不重构** |
| **B 问题集中（早期/基础设施）** | core / phase1 / phase2 | 修复 + 去重 + 死代码清理主战场 |
| 薄层 | orchestrator / py | 骨架好，但承接 B 档数据契约缺陷（page_segments） |

### 2.4 必须遵守的铁律（摘自 CLAUDE.md / AGENTS.md）
- **§8 / §12 分类源头唯一**：`note_kind` 只在 **phase2** 决定，下游透传不可覆盖；**LLM 验证层接入后只能作 prior / 校验 / review 信号，不得成为 note_kind 的第二决策源**（这是批次3的红线）。
- **§1 只消费上游事实、§4 不重建上游事实**：phase N 只读 phase N-1 的事实。
- **§3 禁止广播**：章的聚合属性不赋给个体 entity；footnote 的 def 不混入 endnote。
- **§7 正向验证而非黑名单**：不靠猜测改写正文 raw marker，用数据驱动 + blocker。
- **§10/§11 强弱信号守卫**：bare_digit 等弱信号需正向门 + 守卫。
- **AGENTS.md §2** 避免 hot-loop `Regex::new`；**§9** LLM 路径不因副作用 panic、未实现宁可 `bail!`；**§10** 避免静态 `Mutex<HashMap>` 用 caller-owned cache。

---

## 3. 审计材料地图（执行时按需读）

| 文件 | 内容 | 何时读 |
|---|---|---|
| `FNM_AUDIT2_SUMMARY.md` | **跨 crate 总览 + 与旧审计对照**（H-1~H-6、质量分层、共性） | 先读，建立全局 |
| `FNM_AUDIT2_REMEDIATION.md` | **问题清单底稿**（B1-1…B5-10 编号 + 根因/修复/验证） | 每条修复的索引 |
| `FNM_CORE_AUDIT2.md` … `FNM_PY_AUDIT2.md`（10 份） | **各 crate 逐问题详情**（file:line、严重度、说明） | 改某 crate 前读对应份 |
| `audit/*.md`（旧审计，11 份） | 另一轮独立审计，**19 P0/45 P1/80 P2/59 P3 量化 + 逐行单行 bug** | 逐行查漏对账 |
| `CLAUDE.md` / `AGENTS.md`（仓库根 `/Users/hao/OCRandTranslation/`） | 铁律与 phase 职责边界 | 全程约束 |
| `FNM_RE/`（Python 原版，仓库内） | 接入/去留决策时对照「Python 主流程调了什么」 | 批次3、批次2的 B3-5 |

> 两轮审计**核心高度一致**（互证可信）；本轮独有：page_segments 跨 4-crate 链、foreign_keys per-connection。旧审计独有：若干单行 bug（已在 REMEDIATION B1-4/5/9/10 收录）。

---

## 4. 代码地图（各批次主战场文件）

| 批次 | 主要代码路径 |
|---|---|
| B1 数据/panic | `fnm-core/src/db/{pool,repository}.rs`、`fnm-core/src/vision/pdfium.rs`、`fnm-phase1/src/{toc_structure.rs, chapter_skeleton/heading_candidates/pdf_font_band.rs, chapter_skeleton/pdf_font.rs}`、`fnm-phase3/src/endnote_links.rs`、`fnm-phase4/src/{text/markdown_parse.rs, ref_freeze/mod.rs}`、`fnm-phase6/src/export_audit/file_audit/mod.rs`、`fnm-orchestrator/src/page_translate/jobs.rs`、`fnm-py/src/lib.rs` |
| B2 死代码 | `fnm-phase1/src/{page_partition/mod.rs, section_heads.rs, chapter_skeleton/{toc_semantics/{mod,title_utils}.rs, fallback.rs}, heading_graph/title_key.rs}`、`fnm-phase3/src/paragraph_footnotes.rs`、`fnm-orchestrator/src/page_translate/apply.rs`、`fnm-orchestrator/src/post_translate.rs` |
| **B3 LLM 接入** | `fnm-phase1/src/{llm_book_type_verify/*, book_note_type/mod.rs, toc_structure.rs}`、`fnm-phase2/src/{visual_anchor_recovery/*, llm_bare_digit_verify/*, lib.rs}`、`fnm-phase3/src/{body_anchors/context_guard.rs, note_linking/mod.rs, lib.rs}`、`fnm-orchestrator/src/{pipeline.rs, mainline.rs}`、`fnm-py/src/lib.rs`、依赖 `fnm-core/src/vision/*` 基础设施 |
| B4 逻辑/契约 | `fnm-core/src/db/repository.rs`、`fnm-core/src/ref_rewriter.rs`、`fnm-orchestrator/src/page_translate/{retry.rs}`、`fnm-orchestrator/src/load.rs`、`fnm-phase1/src/chapter_skeleton/heading_candidates/normalize.rs` |
| B5 质量 | 跨 crate（弱类型 Value、重复 helper、eprintln、open_pool、超长函数、records Summary） |

---

## 5. 批次总览与依赖顺序

```
B1 数据/panic ─┬─> B4 逻辑/契约 ──> B5 质量
               └─> B2 死代码清理 ──> B3 LLM 验证接入（重大，独立分支）
```
- **B1 先做**（独立、低风险、高收益，多为 1–5 行）。
- **B2 在 B3 前**（清理真死代码后，接入工程视野更干净）；**B2 严禁删 LLM 验证层**（那是 B3 的接入对象）。
- **B3 最大、独立分支**，依赖 B2 把「真死代码 vs LLM 层」分清。
- **B4 在 B1 后**；**B5 最后**。

### 批次速览（详细见各自计划文件）

| 批次 | 目标 | 件数 | 风险 | 详细计划文件（待产出） |
|---|---|---|---|---|
| **B1** | 修数据正确性 + panic（page_segments 链、DB 事务、foreign_keys、运算符越界、字节切片、as-u16、NaN、倒序串…） | 11 | 低（点状） | `FNM_REMEDIATION_PLAN_01_panic_data.md` |
| **B2** | 删明确死代码（构建后丢弃×6、死 regex×3、`#[allow(dead_code)]` 掩盖项、空操作 if）；确认 chapter_split 0 引用函数去留 | 8 类 | 低（删除） | `FNM_REMEDIATION_PLAN_02_deadcode.md` |
| **B3** | **接入 LLM 验证层**（见下，必做） | 4 子系统 | **高（功能开发）** | `FNM_REMEDIATION_PLAN_03_llm_integration.md` |
| **B4** | 逻辑/契约一致性（enum 读回策略、review_id 持久化、retry visible_idx、load effective_links、死分支、注释订正） | ~10 | 中 | `FNM_REMEDIATION_PLAN_04_logic.md` |
| **B5** | 质量（弱类型定型、重复收敛、eprintln→tracing、py 池缓存、超长函数、records flatten、AI 草稿注释、测试隔离） | 跨 crate | 中 | `FNM_REMEDIATION_PLAN_05_quality.md` |

---

## 6. 批次 3「LLM 验证层接入」总览（重点，必做）

> 详细的接口设计、调用时序、prior/override 协调策略在 `FNM_REMEDIATION_PLAN_03_llm_integration.md`。此处给范围与边界，供总纲对齐。

### 6.1 现状（已有代码，主入口一律 `bail!`）
四个子系统**代码已 port、有测试、但 0 生产调用**，且各 phase 主入口对 `skip_llm_verify=false` 直接 `bail!`（从任何入口都无法启用）：

| 子系统 | 代码 | 作用 |
|---|---|---|
| phase1 `llm_book_type_verify`（+`book_note_type` 作 prior） | `fnm-phase1/src/llm_book_type_verify/*`（client/prompt/selection/mod） | LLM 视觉校验书型（footnote/endnote/mixed），5 维选页 + 多模型 fallback |
| phase2 `visual_anchor_recovery` | `fnm-phase2/src/visual_anchor_recovery/*` | 视觉恢复缺失 anchor |
| phase2 `llm_bare_digit_verify` | `fnm-phase2/src/llm_bare_digit_verify/*` | LLM 校验 bare_digit note marker |
| phase3 bare_digit verifier | `fnm-phase3/src/body_anchors/context_guard.rs`（`positive_gate_bare_digit` 的 `llm_candidates` 当前被丢弃） | 校验 count>2 / 假阳性上下文的 bare_digit anchor |

### 6.2 已就绪的基础设施（接入时复用，勿重造）
- `fnm-core::vision`：`ResolvedModelSpec`、`resolve_fnm_model_pool_specs`、`HTTP_CLIENT`、`PDFIUM`、`render_page_to_base64_png`。
- **参照实现**：`fnm-llm-repair`（已接入的标准范式）——async fn + `Builder::new_current_thread().block_on()` 同步包装、`py.allow_threads` + `with_gil` 回调、`ProviderError` 错误分类、多模型 fallback、`tracing::warn` 失败不 panic。phase1 `llm_book_type_verify::client` 已有类似 async 调用，可直接启用。

### 6.3 接入工作范围（每点详见批次3计划）
1. **解除 bail**：各 phase 主入口（`fnm-phase1/src/toc_structure.rs:99`、`fnm-phase3/src/lib.rs:55`，phase2 同理）把 `skip_llm_verify=false → bail!` 改为 **实际调用对应 verify**。
2. **同步/异步桥接**：verify 是 async（HTTP+vision）。pipeline 是同步 → 在各 `run_phaseN` 或 verify 入口用 `Runtime::block_on`（参照 llm-repair），或把需要 LLM 的 phase 入口改 async。**决策点见批次3计划**。
3. **配置贯通**：`PipelineConfig.skip_llm_verify` 已存在并经 fnm-py 透传（默认 true）；接入后允许 Python 传 `false` 启用。补 fnm-py 的 renderer/model_args 透传（参照 `run_llm_repair_json`）。
4. **结果协调（铁律红线）**：LLM 验证产物**只能作 prior / review 信号 / 显式 override**，**不得**直接改写 phase2 的 `note_kind`（§8/§12）。具体：
   - phase1 book-type verify → 写入诊断 + 作为 phase2 的 prior（不强制覆盖）；
   - phase2 bare_digit verify / phase3 bare_digit verifier → 把 `llm_candidates` 接到 verifier，**通过既有 override / review_required 通道**生效，不绕过 note_kind 唯一来源。
5. **phase2 两子系统接主流程**：`build_phase2_structure_sync` 把 `visual_anchor_recovery_ready` / `llm_bare_digit_verify_ready` 标志改为实际调用（受 `skip_*` 控制）。
6. **测试**：为每个接入点补 parity 测试（对齐 Python LLM 验证输出）+ skip=true 旧行为不回归 + 无 API key 时 graceful skip。

### 6.4 边界（批次3不做）
- 不改 note_kind 决策权归属；不把 LLM 结果变成第二分类源；不破坏 skip=true（默认）下的现有 rule-based 行为；不动 A 档其它逻辑。

---

## 7. 全局验证策略（每批次结束执行）

1. `cargo build --workspace` → `cargo clippy --workspace --all-targets`（**0 warning** 守门）。
2. `cargo test --workspace`（对比修前基线，不得新增失败）。
3. **panic 类**：每条补可复现 fixture 单测，先红后绿。
4. **数据正确性（B1-1/2/3）**：page-translate 端到端断言正文 job 非空 + DB `page_segments_json != "[]"`；INSERT 失败回滚断言；池第 2+ 连接 `PRAGMA foreign_keys=1`。
5. **B3**：parity 测试对齐 Python；skip=true 行为不变；无 key graceful。
6. **实批回归（CLAUDE.md §13）**：B1/B3/B4 后用「另一本书」做多书完整回归 + 导出审计，确认 phase 间契约不回归。

---

## 8. 产出物清单（本计划体系，均已产出）
- `FNM_REMEDIATION_PLAN_00_MASTER.md` ←本文件（总纲）
- `FNM_REMEDIATION_PLAN_01_panic_data.md` —— 批次1：数据正确性/panic（含 before/after 骨架）
- `FNM_REMEDIATION_PLAN_02_deadcode.md` —— 批次2：死代码清理（边界：不删 LLM 层）
- `FNM_REMEDIATION_PLAN_03_llm_integration.md` —— 批次3：LLM 验证层接入（最详细，含红线）
- `FNM_REMEDIATION_PLAN_04_logic.md` —— 批次4：逻辑/契约一致性
- `FNM_REMEDIATION_PLAN_05_quality.md` —— 批次5：质量/重复/弱类型/性能
- `FNM_REMEDIATION_PLAN_06_acceptance.md` —— **各批次完成要求/验收标准（DoD，可执行判据）**
- 支撑材料：`FNM_AUDIT2_SUMMARY.md` + `FNM_AUDIT2_REMEDIATION.md` + 10×`FNM_*_AUDIT2.md` + `audit/*.md`

> **执行入口**：读本总纲 → 按 §5 依赖顺序（B1→B2→B3→B4→B5）逐批次执行 → 每批次/每 PR 用 `PLAN_06` 的可执行判据自检与验收。每个批次详细文件含：逐条任务（位置/根因/改法/骨架/验证/回归）、批次内顺序、风险与回滚。
