# fnm-orchestrator 审计报告

**审计日期**：2026-05-29
**代码规模**：15 文件，3,407 行
**编译状态**：零 warning

## 总体评价

Pipeline 编排器，负责协调 Phase1-6 和翻译流程。结构清晰，模块划分合理，错误处理链路完整（thiserror + anyhow）。但存在 4 个 P0 级问题，其中字节/字符混用问题在处理中文/法文时会产生实际数据偏差。

## 问题清单

### P0 — 高严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 1 | `jobs.rs:184-188` | **字节/字符混用** | `trim_context` 用 `s.len()` (字节) 比较但 `s.chars().take(limit)` (字符) 截断。CJK 文本 `s.len()` 远大于字符数，本应截断的文本未被截断 | 统一 `s.chars().count() <= limit` |
| 2 | `jobs.rs:191-198` | **字节/字符混用** | `tail_context` 同样混用 | 统一 `s.chars().count()` |
| 3 | `retry.rs:27` | **逻辑错误** | `collect_unit_failed_locations_value` 中 `consumed_by_prev` 段落错误递增 `visible_idx`，但类型化版本 `collect_failed_locations` 中不递增。两函数对同一语义处理不一致，Value 版 `para_idx` 会偏大 | 统一行为，consumed 分支不递增 |
| 4 | `load.rs:126` | 语义错误 | `note_links.clone()` 使 `note_links` 和 `effective_note_links` 始终相同，但语义上后者应为 review_overrides 过滤后的结果 | 加注释或实现过滤 |

### P1 — 中严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 5 | `mainline.rs:522-530` | panic 风险 | 在可能已有 tokio runtime 的上下文中创建 `new_current_thread` runtime，嵌套时 panic | doc comment 标注或用 `Handle::try_current()` |
| 6 | `pipeline.rs:110-121` | 可移植性 | `DefaultHasher` 不保证跨版本稳定，run_id 持久化后可能不匹配 | 改用 `format!` 或 UUID |
| 7 | `post_translate.rs:155-161` | 死代码 | 整个 `if` 块无任何副作用 | 删除 |
| 8 | `post_translate.rs:293-294` | **重复合并** | `trans_blockers` 已合入 `final_blocking_reasons`，又与之一起传给 `tail_blocking_summary`，导致 translation blocker 原因出现两次 | 修正参数避免重复 |
| 9 | `mainline.rs:211-221` | 文档缺失 | Phase4+5 reviews 合并依赖 `replace_fnm_structure_reviews` 的全量覆盖语义，缺注释 | 加注释说明 |
| 10 | `apply.rs:63` | 生命周期 | `String::new()` 临时值作为 `unwrap_or` 默认值 | 改为 `.map(\|s\| s.as_str()).unwrap_or("")` |
| 11 | `types.rs:122-144` | 类型设计 | `run_meta` 默认 `Value::Null`，下游可能不如 `{}` 易处理 | 默认改为 `Value::Object(Default::default())` |

### P2 — 低严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 12 | `mainline.rs:325-397` | 过度 clone | replay_phase4_to6_from_db 中 pages/chapters 等被 clone 3-5 次 | 长期用 Arc 共享 |
| 13 | `page_translate/` 模块 | 弱类型 | 几乎所有函数用 `Value` 而非类型化 struct | 定义 Rust struct |
| 14 | `jobs.rs:88-107` | 脆弱解析 | 手写 6 个 `strip_prefix` 分支解析 markdown heading | 提取为共享 utility |
| 15 | `error.rs` | 风格 | 7 个 Phase 错误 variant 结构完全相同 | 可用单一 `PhaseError { phase, source }` |
| 16 | `mainline.rs:624` | 风格 | `eprintln!` + TODO 注释 | 替换为 `tracing::warn!` |
| 17 | `apply.rs:17` | 死代码 | `_section_title` 计算后未使用 | 删除 |
| 18 | `progress.rs:14` | 偷懒代码 | `_use_lightweight: bool` 参数未实现 | 实现或删除 |
| 19 | `post_translate.rs:14-18` | 代码组织 | `NoopRenderer` 私有定义，其他测试需要时要重复 | 移到公共 testing module |

## 值得肯定的地方

1. **错误处理链路完整**：thiserror 分类 + anyhow context 传播
2. **`#![deny(unused_must_use)]`**
3. **错误路径也 finalize fnm_run**：pipeline 失败时不留 "running" 悬挂记录
4. **UTF-8 安全的 `preview_text`**：正确用 `chars().count()` 做字符截断（反衬 P0-1/2 不一致）
5. **Phase 快照序列化分离**：运行时/持久化类型分离
6. **`#[expect(clippy::too_many_arguments)]`**：用 expect 而非 allow
