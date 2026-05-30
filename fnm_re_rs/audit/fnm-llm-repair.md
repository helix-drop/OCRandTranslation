# fnm-llm-repair 审计报告

**审计日期**：2026-05-29
**代码规模**：20 文件，7,583 行
**编译状态**：零 warning，146 测试全通过

## 总体评价

负责 LLM 修复。代码整体质量良好，模块按数据流 6 步组织（cluster → page_context → prompt_builder → llm_client → response_parser → override_materializer），每个模块职责单一。测试覆盖率高，错误处理规范，无 lint 压制。主要问题：一处逻辑缺陷（双重切片）、`serde_json::Value` 弱类型模式、少量代码重复。

## 问题清单

### P1 — 中严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 1 | `prompt_builder.rs:348-349` | **逻辑缺陷** | `repair_user_prompt` 内部再次调用 `slice_cluster_for_request`，但调用方 `request.rs:107` 已切片过。双重切片导致 prompt 与 metrics 的 cluster 视图不一致 | 接受已切片的 `request_cluster`，内部不再二次切片 |
| 2 | `prompt_builder.rs:321-325` | 死分支 | `derive_actions` 中 `anchor_rebind` 的 if/else 两个分支返回完全相同的值 | 确认意图，合并或修正 |
| 3 | `run.rs:148-152` | 边界条件 | `cluster_limit` 为 `Some(0)` 时不截断（`limit > 0` 守卫），语义上 `Some(0)` 应表示"不处理" | 直接 `clusters.truncate(limit)` |

### P2 — 低严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 4 | `cluster.rs:206-265` | unwrap 滥用 | `cluster["key"].as_array_mut().unwrap()` 约 6 处 | 强类型 struct 或 `if let` |
| 5 | `run.rs:389` | unwrap 风格 | `entry.as_object_mut().unwrap()` | 加 `expect` |
| 6 | `page_context.rs:117-134` | unwrap 风格 | `min().unwrap()` 在 Vec 应非空的上下文 | `unwrap_or(&0)` 或 assert 注释 |

### P2 — 代码质量

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 7 | `page_context.rs:457` + `prompt_builder.rs:97` | 代码重复 | `should_attach_repair_images` 两份独立实现 | 提取到共享位置 |
| 8 | 全 crate | 弱类型 | cluster/note_item/body_anchor/note_link 全用 `serde_json::Value` | 至少高频字段定义 accessor helper |
| 9 | `page_context.rs:31` + `prompt_builder.rs:26` | 代码重复 | `WHITESPACE_RE` 两份 | 移到 constants.rs |
| 10 | `response_parser.rs:39-44` | 文档错误 | `char_start`/`char_end` 的 doc comment 标注"字节偏移"，实际是字符索引 | 修正为"字符索引" |
| 11 | `run.rs:522-528` + `llm_client/mod.rs:38` | 风格 | `eprintln!` 而非 `tracing::warn!` | 替换 |

### P3 — 轻微

| # | 描述 |
|---|------|
| 12 | `cluster.rs:47-59` — 内部函数的 doc comment 过长，更适合放 PR description |
| 13 | `request.rs:361-434` — `run_fallback_loop` 末尾 unreachable 路径用 `unwrap_or_else` 而非 `unreachable!` |
| 14 | `usage.rs:28-30` — `safe_float` 中 `as_i64()`/`as_u64()` 分支是 Python 对齐冗余 |

## 值得肯定的地方

1. **模块拆分清晰**：按数据流 6 步组织
2. **Python 对齐注释全覆盖**：每个函数标注 `←→ Python ... (llm_repair.py:行号)`
3. **146 个测试**：覆盖正常路径、边界情况、错误分类
4. **错误处理层次分明**：`ProviderError` 枚举精确分类 4 种错误 + `is_retryable()`
5. **无 lint 压制**
6. **Semaphore 限流**：GLM-4.6V 全局限制并发
7. **JSON 解析 3 层降级**：strict → 包装 → bracket extraction
8. **confidence_numeric 守卫**：区分数字/文字置信度
