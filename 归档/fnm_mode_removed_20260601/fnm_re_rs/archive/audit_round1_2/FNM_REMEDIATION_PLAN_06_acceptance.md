# 各批次完成要求 / 验收标准（DoD & Acceptance Criteria）

> 隶属 `FNM_REMEDIATION_PLAN_00_MASTER.md` 的配套验收文档。
> 原则：**每条「完成要求」必须可客观判定**——给出可执行检查（`cargo` 命令 / `grep` 计数 / 具名测试断言），不接受「我改好了」式主观结论。
> 用法：执行模型自检 + 验收人复核，逐项打勾才算批次完成。
> **进度更新**：2026-05-30 — B1 ✅ B2 ✅ B3 ⚠️ B4 ✅ B5 ⏳

---

## 0. 通用门禁（G0）—— 每个 PR、每个批次都必须满足

| 编号 | 要求 | 客观判据 |
|---|---|---|
| G0-1 | 编译通过 | `cargo build --workspace` 退出码 0 |
| G0-2 | **lint 零容忍** | `cargo clippy --workspace --all-targets -- -D warnings` 退出码 0（建议在 CI 固化 `-D warnings`，把当前「0 warning」从约定变成强制） |
| G0-3 | 测试不退化 | 改前 `cargo test --workspace 2>&1 \| tee /tmp/base.txt` 记基线；改后通过集 ⊇ 基线通过集，**不得新增失败/忽略** |
| G0-4 | 先红后绿 | 每个 bug 修复**至少 1 个新测试**，且能证明「未修时该测试失败」（PR 描述附复现） |
| G0-5 | 不新增抑制 | `git diff` 不得新增 `#[allow(...)]` / `unsafe` / `todo!` / `unimplemented!`（如必须，PR 内逐条注释论证） |
| G0-6 | 契约测试不变 | 各 crate 的 `*_parity` / `contract_*` / `spec_*` 测试**全部仍通过**（A 档质量护栏） |
| G0-7 | 提交规范 | 提交信息中文 + 引用审计 ID（如 `B1-7` / `C-2`）+ 结尾 `Co-Authored-By`；改代码前 PR 描述写明方案（CLAUDE.md §2） |
| G0-8 | 一书冒烟 | 任一改动后，至少跑通 1 本 fixture 书的 `run_pipeline_from_db` + 导出审计无新 blocker |

> **批次合并到主线前**：除上述外，须做 §6「整体工程验收」。

---

## 1. 批次 1（数据/panic）完成要求 【✅ 已完成】

### 任务级（逐条可验收）
| ID | 完成 = | 客观判据 |
|---|---|---|
| B1-1 | page_segments 不再恒空 | (a) `fnm-phase4` 新单测断言 `frozen.body_units[0].page_segments` 非空且段落数 == 输入；(b) 端到端：跑一本书后 DB `SELECT page_segments_json FROM fnm_translation_units LIMIT 1` ≠ `"[]"`；(c) `build_fnm_body_unit_jobs` 对正文 unit 返回 `len()>0` |
| B1-2 | 所有 `replace_*` 有事务 | `grep -n "conn.transaction()" fnm-core/src/db/repository.rs` 覆盖全部 7 个 replace_*；回滚单测：故意失败的 INSERT 后旧行仍在 |
| B1-3 | 每连接 FK=ON | 单测：从池取第 2、3 个连接 `PRAGMA foreign_keys` 均返回 1；插孤儿 fnm_* 行被拒 |
| B1-4 | 越界 panic 消除 | 触发该分支 + `result` 空的单测，修前 panic、修后绿 |
| B1-5 | 尾部截取正序 | 单测 `tail("abcdef",3)=="def"`（修前为 `"fed"`） |
| B1-6 | 页码转换安全 | `u16::try_from` 单测：`-1`/`70000` 返回 Err；`grep "as u16" fnm-core/src/vision/pdfium.rs fnm-phase1/src/chapter_skeleton/pdf_font.rs` 关于 page_index 的命中归零 |
| B1-7 | 标题切片 char 安全 | `grep "tk.len().min(20)" fnm-phase1/src` 归零；法语标题（key 含 é/à）panic 复现测试转绿 |
| B1-8 | 排序不因 NaN panic | `grep "partial_cmp" fnm-phase1/.../pdf_font_band.rs` 后均跟 `unwrap_or`；NaN 坐标单测不 panic |
| B1-9 | 上标偏移安全 | 多位上标 marker 单测偏移正确且 `is_char_boundary` 成立 |
| B1-10 | 排序键无溢出 | `grep "(-char_a)" fnm-phase4/src/ref_freeze/mod.rs` 归零（改 `Reverse`）；clippy 无 `arithmetic` 警告 |
| B1-11 | 哨兵/空守卫/静默处理 | boundary_fallback 空 pages 单测；mod.rs:216 序列化失败有日志或 `?`；endnote_project 哨兵**视 §B3-5 结论**（删则不计此项） |

### 批次级
- [ ] `grep -rEn "as u16|tk.len\(\).min|partial_cmp\(\).unwrap\(\)" fnm-*/src`（排除测试）关于本批的命中**全部归零**。
- [ ] page-translate 端到端 fixture 测试存在且通过（正文 job 非空）。
- [ ] 一本新书多书回归（CLAUDE.md §13）无 phase 间契约回归。

---

## 2. 批次 2（死代码清理）完成要求 【✅ 已完成】

### 量化判据（核心：删干净 = grep 归零 + clippy 自然守门）
- [ ] **构建后丢弃归零**：`grep -rEn "let _[a-z][a-z_]* = " fnm-*/src | grep -v test | grep -vE "_permit|_ =|_t_args_json|_pages"` 中 §B2-1/B2-7 列出项全部消失。
- [ ] **死 regex 归零**：`grep -rn "static _[A-Z].*Lazy<Regex>" fnm-phase1/src` 归零。
- [ ] **掩盖式 allow 归零**：`grep -rn "#\[allow(dead_code)\]" fnm-phase1/src fnm-phase2/src` 在源码（非 tests/）中归零，且**删除后 `cargo clippy` 仍 0 warning**（若报 dead_code = 还有连带未删）。
- [ ] post_translate 空操作 if（155-160）已删。
- [ ] 行为零变更：`cargo test --workspace` 通过集与基线**完全一致**（删除不应改任何测试结果）。

### 决策留痕（§2 需确认项）
- [ ] B2-6（`chapter_split/{endnote_project,overrides_apply,synth_markers}`）：PR 描述附**Python 对照结论**（grep 到的 Python 调用点截图/路径）+ 处置（删除 / 接入到新批次）。**不允许无结论地保留或盲删。**
- [ ] B2-7 pub 无调用者函数：每个附「已确认无外部消费」证据后删除或私有化。

### 红线
- [ ] `git diff --stat` **不含** `llm_book_type_verify/`、`book_note_type/`、`visual_anchor_recovery/`、`llm_bare_digit_verify/`、`context_guard.rs` 的删除（这些是批次3对象）。

---

## 3. 批次 3（LLM 接入）完成要求 【⚠️ 部分完成：S1+S4 完成，S2+S3 基础设施就绪】

### 最高优先验收：向后兼容（skip 默认 true 零变化）
- [ ] 在 `skip_llm_verify=true`（默认）下，**全 workspace 测试通过集与接入前基线完全一致**——证明接入不改变现有 rule-based 行为。这是批次3能合并的前提。

### 功能验收（skip=false）
| 子系统 | 完成 = |
|---|---|
| S1 phase1 书型 | skip=false + 有 key → phase1 `diagnostics` 含 `llm_book_type_verify` evidence；book_type 由 phase2 决定**未被 LLM 覆盖** |
| S2 visual_anchor | skip=false → 缺口 anchor 经 override 出现在 `body_anchors`；`note_kind` 不变 |
| S3 phase2 bare_digit | skip=false → 假阳性 bare_digit 被标记/剔除；`note_kind` 唯一来源仍是 phase2 |
| S4 phase3 anchor | `llm_candidates` 不再被丢弃；接受/拒绝经 review/override 通道；`llm_candidate_count` 与实际处置一致 |

### 红线守卫（§8/§12，必须有专门测试）
- [ ] 构造「LLM 返回与 rule-based 冲突的 note_kind」用例，断言 **phase2 决策不被 LLM 覆盖**（note_kind 唯一来源不破）。
- [ ] `grep -rn "\.note_kind = " fnm-phase1/src fnm-phase3/src`（非 phase2、非测试）仍**无对 note_item 的 note_kind 赋值**。

### 健壮性
- [ ] **graceful skip**：`skip=false` 但无 API key（不设环境变量）→ pipeline 正常完成、产物等同 rule-based、诊断标 `skipped`、**不 panic、不报错**。
- [ ] async 桥接：py 路径用 `allow_threads` 外包 `block_on`，无「runtime within runtime」panic（mock LLM 集成测试覆盖）。

### 收尾
- [ ] 删除全部 `*_ready` 占位标志、相关 `bail!`、`note_linking/mod.rs:150` 的 `_pdf_path` 占位。
- [ ] parity 测试对齐 Python LLM 验证输出；多书实批回归（含至少 1 本会触发 LLM 路径的书）通过。

---

## 4. 批次 4（逻辑/契约）完成要求 【✅ 已完成】

| ID | 完成 = |
|---|---|
| B4-1 | DB enum 读回策略**全文统一**（全 fail-fast 或全容错+日志）+ 注释说明；相关测试期望同步更新并通过 |
| B4-2 | 同坐标两条 review 单测断言 `review_id` 不碰撞、`len()==2` |
| B4-3 | Value 版与类型化版 `collect_*failed_locations` 对同一含 `consumed_by_prev` 的 unit 返回 `para_idx` **逐项一致**（单测） |
| B4-4 | load 的 `effective_note_links` 语义已确认（注释或分别加载），与 phase3 出口一致 |
| B4-5 | `grep "while .*values().any" fnm-core/src/ref_rewriter.rs` 归零；ref_rewriter 测试不变 |
| B4-6 | refs.rs 改 `captures_iter` + 结构化标志；`grep 'as_str().contains("\\\\[\\\\^")' fnm-core/src/refs.rs` 归零；区分 en/fn 用例通过 |
| B4-7 | `is_sentence_like_heading` 两实现统一或注释差异理由；边界词数（6/7/8）用例通过 |
| B4-8 | 注释订正项（stub/严格递增/行数/byte-char）全部修正；`cargo build` 通过 |

- [ ] 批次级：多书实批回归无翻译进度/失败定位错位（B4-3/B4-4 重点）。

---

## 5. 批次 5（质量）完成要求 【⏳ 未开始】

> 重构性质——核心验收是**行为/JSON 不变**，用快照守护。

| 项 | 完成 = |
|---|---|
| B5-4 eprintln→tracing | `grep -rn "eprintln!" fnm-*/src \| grep -v test` 归零（除有意保留并注释的）；config 解析失败有 `warn` |
| B5-5 py 池缓存 | 连续调同 db_path 的 pyfunction **不重复跑 migrations**（日志/计数断言）；并发安全；功能不变 |
| B5-3 to_value 浪费 | `grep -rn "to_value(p)" fnm-phase1/src fnm-phase2/src \| grep -v test` 关于 RawPage 的命中归零；page text 提取结果不变 |
| B5-2 重复收敛 | 各重复 helper 收敛到单一定义（`grep` 确认定义点唯一）；**分值/阈值不同的两套先确认再合并**，PR 注明 |
| B5-1 弱类型定型 | 高频 job/action 路径有 typed struct/accessor；行为不变 |
| B5-6 超长函数 | 拆分后**快照测试逐字节一致**（build_toc_semantics / build_frozen_units） |
| B5-7 records flatten | **JSON 序列化与 Python asdict 逐字段一致**（快照测试，最高风险项必须有此守护） |
| B5-8 草稿注释 | `sequence_repair.rs` 的 AI 流水账注释已删 |
| B5-9 测试隔离 | token_counter 测试不再依赖弹性 `>=`；BookType 入 roundtrip；config 测试名副实 |
| B5-10 性能 nit | all_rules const 化；continuation 借用；segment_codec has_* 简化（行为不变快照） |

- [ ] 批次级：全量 parity + 多书回归输出与重构前**逐字节一致**（质量改进不得改行为）。

---

## 6. 整体工程验收（所有批次合并到主线后）

- [ ] **门禁全绿**：`cargo build/test --workspace` + `cargo clippy --workspace --all-targets -- -D warnings`（0 warning）。
- [ ] **H-1~H-6 全部 closed**（对照 `FNM_AUDIT2_SUMMARY.md §2）：page_segments 正文非空、DB 事务、foreign_keys、运算符 panic、byte-char、as-u16，每项有对应回归测试。
- [ ] **死代码归零**：源码 `#[allow(dead_code)]`、死 regex、构建后丢弃、空操作 if 全清；clippy 自然守门。
- [ ] **LLM 层接入完成**：skip=false 4 子系统可用、skip=true 零变化、note_kind 红线守卫测试存在并通过、graceful skip 通过。
- [ ] **多书完整回归（CLAUDE.md §13）**：≥2 本书（含一本会触发 LLM 路径的）完整 pipeline + 翻译 + 导出审计，无新 blocker、无 phase 间契约回归。
- [ ] **对账闭环**：旧审计 `audit/*.md` 的 19 P0 逐条标注「已修 / 经核实非问题 / 归入死代码删除」，无遗漏。
- [ ] **文档更新**：受影响的 `←→ Python (file:line)` 注释、各 `FNM_*_AUDIT2.md` 中「待修」项状态更新为已修。

---

## 验收口径速记
- **修 bug 类**（B1/B4）：先红后绿测试 + grep 反模式归零 + 回归不变。
- **删除类**（B2）：grep 计数归零 + clippy 自然守门 + 测试结果零变化 + 决策留痕。
- **功能类**（B3）：向后兼容零变化（最重要）+ 新功能可启用 + 红线守卫 + graceful。
- **重构类**（B5）：快照/parity 逐字节一致（行为绝不变）。
