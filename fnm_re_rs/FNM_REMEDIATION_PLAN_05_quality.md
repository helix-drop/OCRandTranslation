# 批次 5 详细计划 — 质量 / 重复 / 弱类型 / 日志 / 性能

> 隶属 `FNM_REMEDIATION_PLAN_00_MASTER.md` 批次 B5。**最后做，可增量**，不阻塞功能。
> 性质：质量改进 / 收敛重复 / 性能。中等工作量，分散低风险。分支 `chore/b5-quality`（可拆多个小 PR）。
> 原则：**优先高频路径 + 高收益低风险项**；A 档 crate（phase3-6/llm-repair）只做明显收益的，避免为重构而重构。
> 验证主轴：行为不变（重构）→ `cargo test/clippy` 0 warning + 关键 parity 测试不变。

---

## 优先级建议（自上而下做）

### P-高（高频 / 高收益）

**B5-4　`eprintln!` → `tracing`（≥6 处）** 〔低风险，先做〕
- 位置：`fnm-core/src/config.rs:140-147`（静默吞配置解析错误，应 `tracing::warn!` 而非 `unwrap_or_default` 默默丢 API key）、`fnm-core/src/db/repository.rs:1651`（load_raw_pages eprintln）、`fnm-core/src/token_counter.rs`（`_error` 字段）、`fnm-orchestrator/src/mainline.rs:623`（含 TODO）、`fnm-llm-repair/src/run.rs:523`。
- 做法：统一 `tracing::{warn,error}!`；config 解析失败必须记日志（当前静默丢所有用户配置）。确认 crate 已依赖 `tracing`（是）。
- 验证：行为不变，日志可见；config 损坏时有 warn。

**B5-5　fnm-py 连接池缓存（放大 B1-3 收益）** 〔中风险，高收益〕
- 位置：`fnm-py/src/lib.rs` + `translate.rs` 共 21 处 `open_pool(Path::new(db_path))`——每个 DB pyfunction 调用都新建池 + 跑 migrations，Python 按页/进度高频调用开销大。
- 做法：进程级 `once_cell::Lazy<Mutex<HashMap<String, SqlitePool>>>` 按 `db_path` 缓存池；首次建池 + migrations，后续复用。**与批次 1 B1-3 的 `with_init(foreign_keys)` 协同**（池缓存后 FK 设置只需正确一次）。
- 验证：连续调用同 db_path 的 pyfunction 不重复跑 migrations；功能不变；并发安全（Mutex）。

**B5-3　`serde_json::to_value(RawPage)` 循环内反复序列化** 〔低风险〕
- 位置：`fnm-phase1`（book_note_type/mod.rs:311,320、page_resolve.rs:32、page_rows.rs:58）、`fnm-phase2/chapter_split/mod.rs:216`。
- 做法：直接取 `RawPage` 字段（`enriched_markdown.as_deref().unwrap_or(&markdown)`）替代「序列化成 Value 再调 page_markdown_text」。为需要的提取写一个吃 `&RawPage` 的轻量 helper（放 fnm-core）。
- 验证：page text 提取结果不变；性能提升。

**B5-2　重复 helper 收敛到 fnm-core** 〔低风险，分多 PR〕
- `extract_json_block`（fnm-phase2 + fnm-llm-repair ×3）、`WHITESPACE_RE`（多 crate）、`extract_context`（phase3 ×2）、`safe_int`（phase5 ×2）、`compute_body_bounds`（phase2 ×2）、`build_chapter_by_page`（phase1 ×3：page_roles/book_note_type/selection）、page_numbers 提取（phase5 ×3）、`candidate_source_score`（phase1 row_collect vs heading_graph/scoring，**分值不同**——确认是否应统一）、role_heuristics vs page_resolve 的 `looks_like_copyright/course_listing/title_page`（phase1，简化版不一致）。
- 做法：提取到 fnm-core 或各 crate 公共模块；**分值/阈值不同的先确认语义再合并**（不要把有意不同的强行统一）。
- 验证：各调用点行为不变。

### P-中（结构改进）

**B5-1　`serde_json::Value` 弱类型高频路径定型** 〔中风险〕
- 范围：llm-repair `cluster`/`action`、orchestrator `page_translate` job、phase3-4 中间结构、core segment_codec。
- 做法：为**最高频**的中间数据定义 typed struct 或至少 accessor helper（字段名拼写编译期可查）。**不必全量替换**——优先 job/action 这类反复 `.get("key")` 的热点。
- 验证：行为不变；减少 `.get(...).and_then(as_str)` 样板。

**B5-6　超长函数拆分** 〔中风险〕
- `fnm-phase1/toc_semantics/mod.rs:build_toc_semantics`（580 行，16 步）、`fnm-phase4/ref_freeze/mod.rs:build_frozen_units`（740 行，7 phase）、`fnm-phase1/toc_structure.rs:build_phase1_structure`。
- 做法：按已有「步骤注释」边界抽子函数（每步一函数），状态用 struct 承载。**phase4 是 A 档，仅在批次1 B1-1 改 page_segments 时顺带、否则可缓**。
- 验证：拆分前后输出逐字节一致（快照测试）。

**B5-7　core `PhaseNSummary`/`PhaseNStructure` 字段平铺重复** 〔中风险〕
- 位置：`fnm-core/src/records.rs` 6 份 Summary（16+ 公共字段重复）、6 份 Structure。
- 做法：抽 `BaseSummary`/`BaseStructure`，用 `#[serde(flatten)] common: BaseSummary` 保持 JSON 平铺兼容。**务必快照测试验证 JSON 输出与 Python asdict 不变**（这是数据契约）。
- 验证：序列化 JSON 与现状逐字段一致。

### P-低（清理 / 测试 / nit）

**B5-8　AI 推导草稿注释** 〔零风险〕
- `fnm-phase2/src/note_items/sequence_repair.rs:230-272` 测试内 ~40 行「Let me think… Wait… 公式好像错了… Hmm」流水账 → 删，只留最终用例 + 一句说明。

**B5-9　测试隔离 / 覆盖** 〔低风险〕
- `fnm-core/token_counter.rs`：全局 `USAGE_RECORDS: Mutex<Vec>` 致并行测试污染（现用 `>=` 弹性断言绕过）→ 测试内用独立实例或串行标注。
- `fnm-core/types.rs`：`BookType` 漏入 `all_enums_roundtrip`/`all_enums_have_all_const` → 补上。
- `fnm-core/config.rs:286`：`default_pool_has_4_slots_with_builtin_at_zero` 测试名不副实（只断言非空）→ 补全断言或改名。

**B5-10　性能 nit** 〔低风险〕
- `fnm-phase1/page_partition/rules/mod.rs:58` `all_rules()` 每页重建 `Vec<fn>` → 改 `const`/`static` 数组。
- `fnm-phase1/page_partition/continuation/mod.rs` 每页 `.cloned()` 整页文本 → 借用 `&str`。
- `fnm-core/segment_codec.rs:deserialize_paragraph` 11 个 `has_*` 冗余分支（~150 行可压到 ~40，if/else 两分支等价）→ 直接 `get().or().unwrap_or(default)`。
- `fnm-phase1/note_marker.rs:150` `chars().nth(cursor)` O(n²) → 字节索引（短串影响小，可缓）。

---

## 完成标准（DoD）
- [ ] 高优先项（B5-4/5/3/2）完成并验证行为不变。
- [ ] 重构项（B5-1/6/7）有快照/parity 测试守护 JSON 与行为不变。
- [ ] `cargo clippy` 0 warning；多书实批回归无差异。
- [ ] 每个收敛/拆分单独小 PR，便于审查与回退。

## 风险与回滚
- **B5-7（records flatten）风险最高**：直接关系 Python asdict 数据契约，必须快照测试逐字段验证，否则可能静默改变导出 JSON 结构。
- B5-1/B5-2 收敛时注意「分值/阈值不同的重复」是否有意为之（如两套 candidate_source_score），不可盲目合并。
- 全为质量改进，可增量、可随时暂停；每项独立 PR 回退成本低。
