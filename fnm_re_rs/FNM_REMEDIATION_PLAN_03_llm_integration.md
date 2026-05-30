# 批次 3 详细计划 — LLM 验证层接入【重大功能 / 必做】

> 隶属 `FNM_REMEDIATION_PLAN_00_MASTER.md` 批次 B3。**这是功能开发，不是修 bug。**
> 前置：批次 2 完成（已分清「真死代码」与「本批接入对象」）。**独立分支** `feat/b3-llm-verify`。
> 目标：把已 port 但永久 `bail!`/仅设 ready 标志的 4 个 LLM 验证子系统**真正接入主流程**，由 `skip_llm_verify=false` 启用，默认（true）行为完全不变。
> 审计依据：`FNM_PHASE1_AUDIT2.md` P1-7、`FNM_PHASE2_AUDIT2.md` P2-4、`FNM_PHASE3_AUDIT2.md` P3-1、`FNM_AUDIT2_SUMMARY.md` §2 共性。
> **更新日期**：2026-05-30（基于源码实际验证，修正 §2/§3/§4 的执行时机）

---

## 0. 接入对象与现状（4 个子系统）

| # | 子系统 | 代码 | 现状 | 产物语义 |
|---|---|---|---|---|
| S1 | phase1 书型校验 | `fnm-phase1/src/llm_book_type_verify/*` + `book_note_type/mod.rs` | `verify_book_type_with_llm` 已实现（async）；主入口 `toc_structure.rs:99` 对 `skip=false` **bail** | 书型 prior（footnote/endnote/mixed）+ 可疑页 |
| S2 | phase2 视觉锚点恢复 | `fnm-phase2/src/visual_anchor_recovery/*` | `run_visual_anchor_recovery`（mod.rs:134）已实现；`lib.rs` 仅设 `visual_anchor_recovery_ready` 标志 | 恢复缺失 anchor → 经 override 注入 |
| S3 | phase2 bare_digit 校验 | `fnm-phase2/src/llm_bare_digit_verify/*` | `verify_bare_digit_candidates` 已实现（async）；`lib.rs` 仅设 `llm_bare_digit_verify_ready` 标志 | 校验 bare_digit note marker 真伪 |
| S4 | phase3 bare_digit anchor 校验 | `fnm-phase3/src/body_anchors/context_guard.rs` | `positive_gate_bare_digit` 返回 `llm_candidates`（count>2/假阳性候选）**当前被丢弃** | 校验弱 anchor → 经 review/override |

### 关键架构发现（2026-05-30 验证）

**S2/S3 不能在 Phase 2 内部执行**——它们依赖 Phase 3 的 `body_anchors` 产物。
Phase 2 `lib.rs:119` 注释明确说："LLM 路径诊断（llm_bare_digit_verify + visual_anchor_recovery **需 Phase 3 body_anchors**）"。

正确执行时机：
```
Phase 1 → Phase 2 → Phase 3 → [S2 + S3 post-phase3 LLM verify] → Phase 4
```

S2/S3 应在 **orchestrator 层**作为 Phase 3 后处理步骤执行，产物作为 review_overrides 反馈给后续 phase。

**Phase 3 无 tokio 依赖**：S4 需要为 `fnm-phase3/Cargo.toml` 添加 tokio 依赖。

**Phase 3 skip_llm_verify 硬编码**：`pipeline.rs:235` 硬编码 `skip_llm_verify: true`，需改为透传 `config.skip_llm_verify`。

---

## 1. 设计决策（D1–D4）

### D1　async/sync 桥接策略 → **采用「局部 block_on」**（与 llm-repair 一致）
各 phase 主入口保持**同步签名**。在入口内 `skip_llm_verify=false` 分支处，用：
```rust
let rt = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
let verify = rt.block_on(verify_xxx_with_llm(...))?;
```
- **参照**：`fnm-orchestrator/src/mainline.rs:506` 的 `run_llm_repair_sync`
- **py 侧**：`py.allow_threads(|| { rt.block_on(...) })`（释放 GIL）——**参照 `fnm-py/src/lib.rs:671`**

### D2　结果协调（**铁律红线，最重要**）
**§8 / §12：`note_kind` 只在 phase2 决定，LLM 不得成为第二决策源。**

| 子系统 | 合法落点 | 禁止 |
|---|---|---|
| S1 书型 verify | 写 phase1 `diagnostics`（不改 chapters/book_type） | 禁止用 LLM 书型直接覆盖 phase2 结果 |
| S2 visual_anchor | 经 override 通道注入恢复的 anchor | 禁止改写 note_item.note_kind |
| S3 bare_digit verify | 消费于 orchestrator post-phase3，经 review/override 通道 | 禁止在 phase2 外改 note_kind |
| S4 phase3 anchor verify | 裁决 anchor 去留/置信度，经 review/override 通道 | 禁止重分类 note_kind |

### D3　配置与「无 key graceful」
- `PipelineConfig.skip_llm_verify` 已存在（默认 true），fnm-py 已解析。
- **无 API key 时 graceful skip**：返回 skipped 诊断，不报错，不改变 rule-based 结果。
- 模型来源：`fnm_core::vision::VisionConfig::default()`（从 `OPENAI_API_KEY` 环境变量读取）。

### D4　PDF 渲染依赖
S1/S2/S4 需页面截图。复用 `fnm_core::vision::render_page_to_base64_png` + `PDFIUM`。
**fnm-py 无需新增 renderer 参数**（内置 PDFIUM，不需 Python 回调）。

---

## 2. 接入点 S1 — phase1 书型校验

**位置**：`fnm-phase1/src/toc_structure.rs:97-104`（当前 bail）

**精确接口**：
```rust
// llm_book_type_verify/mod.rs:41
pub async fn verify_book_type_with_llm(
    structure: &Phase1Structure,
    book_note_profile: &BookNoteProfile,
    chapter_note_modes: &[ChapterNoteModeRecord],
    pdf_path: &str,
) -> Result<LlmVerifyResult>
// 返回：LlmVerifyResult { llm_book_type: Option<String>, agreement_with_rules: bool, evidence: Value }
```

**实现**：在 `build_phase1_structure` 中 structure 构建完成后，替换 bail 为实际调用：
```rust
let llm_verify_result = if !config.skip_llm_verify {
    let profile = crate::book_note_type::build_book_note_profile(&structure.chapters, pages, None);
    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    match rt.block_on(crate::llm_book_type_verify::verify_book_type_with_llm(
        &structure, &profile, &profile.chapter_modes,
        config.pdf_path.as_deref().unwrap_or(""),
    )) {
        Ok(r) => Some(r),
        Err(e) => { tracing::warn!("book_type verify 失败（降级 rule-based）: {e}"); None }
    }
} else { None };
```

**红线**：结果仅写 `diagnostics["llm_book_type_verify"]`，不改 structure.chapters/book_type。

---

## 3. 接入点 S2 — orchestrator post-phase3 visual_anchor_recovery

**位置**：`fnm-orchestrator/src/pipeline.rs`（Phase 3 完成后）

**精确接口**：
```rust
// visual_anchor_recovery/mod.rs:134
pub async fn run_visual_anchor_recovery(
    gap: &ChapterAnchorGap,
    page_by_no: &HashMap<i64, &RawPage>,
    pdf_path: &str,
) -> anyhow::Result<(Vec<BodyAnchorRecord>, Value)>
```

**关键**：S2 需要 `ChapterAnchorGap`（Phase 3 的 body_anchors 产物），因此必须在 Phase 3 之后执行。

**实现**：在 orchestrator 中 Phase 3 完成后，作为 post-phase3 步骤调用。

**红线**：只产 anchor/override，不碰 note_kind。

---

## 4. 接入点 S3 — orchestrator post-phase3 bare_digit 校验

**位置**：`fnm-orchestrator/src/pipeline.rs`（Phase 3 完成后）

**精确接口**：
```rust
// llm_bare_digit_verify/mod.rs:19
pub async fn verify_bare_digit_candidates(
    anchors: &[BodyAnchorRecord],
    pdf_path: &str,
    config: &VisionConfig,
    max_concurrent: usize,
    min_confidence: f64,
) -> anyhow::Result<(Vec<BareDigitVerifyResult>, Vec<BareDigitVerifyResult>)>
// 返回：(accepted, rejected)
```

**关键**：S3 需要 Phase 3 的 `body_anchors` 产物作为输入，因此必须在 Phase 3 之后执行。

**红线**：经 review/override 通道生效，不改 note_kind。

---

## 5. 接入点 S4 — phase3 bare_digit anchor 校验

**位置**：
- `fnm-phase3/src/lib.rs:55`（bail）
- `fnm-phase3/src/note_linking/mod.rs:150`（`_pdf_path` 占位）
- `fnm-phase3/src/body_anchors/mod.rs:192-194`（`llm_candidates` 被丢弃）

**精确接口**：
```rust
// body_anchors/context_guard.rs:106
pub fn positive_gate_bare_digit(
    anchors: &[BodyAnchorRecord],
    chapter_note_items: &HashMap<String, HashSet<i64>>,
) -> (Vec<BodyAnchorRecord>, Vec<BodyAnchorRecord>)
// 返回：(通过的 anchors, 需要 LLM 验证的候选)
```

**实现**：
1. 为 `fnm-phase3/Cargo.toml` 添加 tokio 依赖
2. `build_body_anchors` 新增 `llm_verify_config` 参数
3. 将 `llm_candidates` 传给 verifier（block_on vision 调用）
4. 接受 → 加入 anchors；拒绝 → 丢弃
5. `pipeline.rs:235` 改 `skip_llm_verify: true` 为 `config.skip_llm_verify`

**红线**：只裁决 anchor 去留/置信度，不碰 note_kind。

---

## 6. orchestrator / fnm-py 贯通

- **pipeline.rs:235**：Phase3 `skip_llm_verify: true` → `config.skip_llm_verify`
- **pipeline.rs**：Phase 3 后添加 S2/S3 post-phase3 步骤
- **fnm-py**：无需新增参数（`skip_llm_verify` + `pdf_path` 已透传）
- **mainline.rs**：DB-driven 路径同理透传

---

## 7. 测试策略

1. **向后兼容（最重要）**：`skip_llm_verify=true`（默认）下**零变化**。
2. **graceful skip**：`skip=false` 但无 API key → pipeline 正常完成、诊断标 skipped。
3. **红线守卫测试**：构造「LLM 给出与 rule-based 冲突的 note_kind」场景，断言 phase2 决策不被 LLM 覆盖。
4. **mock LLM**：用 stub HTTP 避免真实 API 依赖。

---

## 8. 执行顺序 / DoD / 风险

**顺序**：S1（phase1，最独立）→ S4（phase3，接 llm_candidates）→ S2+S3（orchestrator post-phase3）→ 贯通 → 测试

**DoD**：
- [ ] 4 个子系统 `skip=false` 可启用、`skip=true` 行为零变化
- [ ] graceful skip（无 key）通过
- [ ] 红线守卫测试通过（note_kind 唯一来源不破）
- [ ] 删除所有 `*_ready` 占位标志 + `bail!` + `_pdf_path` 占位
- [ ] `cargo clippy` 0 warning；多书实批回归通过

**风险**：
- **最大风险**：违反 §8/§12（LLM 变 note_kind 第二决策源）——D2 红线 + 守卫测试必须落实
- async 桥接：py 侧务必 `allow_threads` 外包
- S2/S3 执行时机：必须在 Phase 3 之后（依赖 body_anchors 产物）
- 回滚：独立分支，每个 S 独立提交，可单独回退
