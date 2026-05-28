# FNM Rust Workspace 审计总览

审计时间：2026-05-22

审计范围：`/Users/hao/OCRandTranslation/fnm_re_rs` 下 10 个 crate。

> 本文是 2026-05-22 的原始审计快照，不是当前实施计划。部分发现已经关闭，
> 部分仍可复现。2026-05-27 起唯一处置入口为
> `FNM_AUDIT_REMEDIATION_PLAN.md`，其中按当前源码和新鲜验证记录状态。

## 审计文件

已按 crate 落盘：

1. `FNM_CORE_AUDIT.md`
2. `FNM_PHASE1_AUDIT.md`
3. `FNM_PHASE2_AUDIT.md`
4. `FNM_PHASE3_AUDIT.md`
5. `FNM_PHASE4_AUDIT.md`
6. `FNM_LLM_REPAIR_AUDIT.md`
7. `FNM_PHASE6_AUDIT.md`
8. `FNM_PHASE5_AUDIT.md`
9. `FNM_ORCHESTRATOR_AUDIT.md`
10. `FNM_PY_AUDIT.md`

## 总体结论

当前 Rust workspace 已经有完整 phase1→6 + PyO3 绑定的形状，但还不能当作可信的 Python FNM pipeline 等价替代。主要问题不是单点语法，而是跨 phase contract 没有闭合：

- 上游事实会在下游被重建或覆盖。
- `note_kind`、chapter boundary、status、diagnostic、repair override 等关键事实没有单一来源。
- 多个公开 API 声称支持续跑、diagnostic、LLM repair、post-translate repair，但实际没有完整接线。
- 测试多为 hand-crafted 或 smoke，缺少真实 fixture 的 byte-equal parity。

## 最高优先级问题

### 1. 先修 core 数据合同

必须先处理：

- `segment_codec` 顶层正文丢失。
- SQLite migration 与 Repository API 不闭合。
- DB 读回非法/缺失 `note_kind` fallback 到 `Footnote`。
- `NoteLinkRecord::default()` 默认为 `Matched + Footnote`。
- `replace_frozen_refs` 忽略 `EndnoteMode`。

这些属于基础设施问题，不先修会让后续 phase 的审计结果继续漂移。

### 2. 切断下游重建上游事实

重点位置：

- Phase3 的 `phase2_rebuild`。
- Phase4 两套 ref injection 路径。
- Phase5 重新构造 `ChapterRecord` 和 `ChapterNoteModeRecord`。
- Phase6 对导出内容做最终修补。
- Orchestrator / loader 默认构造 status 和 summary。

原则：Phase N 只能消费 Phase N-1 的事实，发现错误修上游，不在下游重新解释。

### 3. 修复 orchestrator 与 Python 入口的虚假能力

重点位置：

- `start_phase` 目前只进 meta，不会续跑。
- LLM repair auto-apply 后本轮 Phase4/5/6 不消费结果。
- post-translate repair 没有重跑 Phase3-6。
- Phase5 diagnostic pages/notes 不落库。
- `run_doc_pipeline_json()` 丢失大量 config。
- `run_llm_repair_json()` 用 `expect()` 造成 panic。

这些问题会直接影响用户从 Python 调用 Rust pipeline 的真实结果。

### 4. 重新定义 Phase5/Phase6 边界

当前 Phase5 调用 Phase6 export contract 生成 chapter markdown，Phase6 又做最终导出审计和部分内容修补，职责倒挂。

建议边界：

- Phase5：只合并单章 markdown。
- Phase6：只组装整书 ZIP 并审计，不修补上游内容。

### 5. 补真实 parity 测试

必须补：

- Python expected JSON fixture。
- Rust 输出 byte-equal 对比。
- Biopolitics + Goldstein 双书回归。
- start_phase 续跑不覆盖前序产物。
- LLM repair 后本轮 Phase4/5/6 结果变化。
- diagnostic entries 非空和 page translate note jobs 存在。
- raw marker leak / frozen ref leak blocker。

## 建议修复顺序

1. `fnm-core`：修数据丢失、schema/API 不闭合、默认值和 clippy baseline。
2. `fnm-orchestrator` + `fnm-py`：禁用或实现 `start_phase`，修 LLM repair 接线和 Python panic。
3. `fnm-phase2`：修 `note_kind` 分类与 note item 捕获边界，禁止全局/字符串序列修补。
4. `fnm-phase3`：移除 lossy phase2 rebuild，Phase3 只消费 Phase2 权威 note items/regions。
5. `fnm-phase4`：统一 ref freeze/injection 路径，matched link 注入失败必须 blocker。
6. `fnm-phase5`：切断 Phase6 反向依赖，不再重建 chapter/note mode。
7. `fnm-phase6`：只审计和组装，不做内容修补；审计必须基于真实 ZIP bytes。
8. `fnm-llm-repair`：修坐标单位、duplicate override 物化、cluster action 校验。
9. 全 workspace：补真实 fixture parity，解除 ignored tests，跑通 PR checklist。

## 验证概况

| crate | build | fmt | test | clippy |
|---|---|---|---|---|
| `fnm-core` | 通过 | 失败 | 通过 | 失败 |
| `fnm-phase1` | 通过 | 失败 | 通过 | 失败 |
| `fnm-phase2` | 通过 | 失败 | 通过 | 失败 |
| `fnm-phase3` | 通过 | 通过 | 通过 | 被前序阻断；放宽前序后本体通过 |
| `fnm-phase4` | 通过 | 失败 | 通过 | 失败 |
| `fnm-llm-repair` | 通过 | 通过 | 通过 | 失败 |
| `fnm-phase6` | 通过 | 通过 | 通过 | 失败 |
| `fnm-phase5` | 通过 | 通过 | 通过 | 被前序阻断；放宽前序后本体通过 |
| `fnm-orchestrator` | 通过 | 通过 | 通过 | 失败 |
| `fnm-py` | 通过 | 通过 | 0 个 Rust 测试；Python 78 passed | 被前序阻断；放宽已知 lint 后通过 |

说明：

- 多数后序 crate 的普通 clippy 会先被 `fnm-core` 阻断。
- `fnm-phase2` 和 `fnm-llm-repair` 当前 build 会产生 warning。
- `fnm-py` Python 测试使用当前 venv 中已安装的 `fnm_re_rs` 模块。

## 工作区状态说明

本轮只新增审计文档和总览文档。审计过程中发现工作区已有多处 Rust 源码变更和一个删除文件，这些不是本轮审计新增内容，未做回退。
