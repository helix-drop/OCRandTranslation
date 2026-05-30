# fnm-core 审计报告

**审计日期**：2026-05-29
**代码规模**：37 文件，11,355 行
**编译状态**：零 warning

## 总体评价

核心基础设施 crate，涵盖类型定义、DB 操作、PDF 渲染、文本处理等。整体质量中等偏上，核心模块（types、refs、anchor_kind、note_marker）设计清晰，Python 对齐测试覆盖充分。DB 层存在事务安全问题，PDF 渲染层存在类型截断隐患。

## 问题清单

### P0 — 高严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 1 | `db/repository.rs:270-387` | 逻辑缺陷 | 多表 DELETE+INSERT 缺少事务包裹。`write_phase1_tables` 先 DELETE 4 张表再 INSERT，全部在自动提交模式下运行。INSERT 失败时 DB 处于部分删除的不一致状态。同样问题出现在 Phase2-6 的所有 replace 函数中。 | 用 rusqlite `Transaction` API 包裹 DELETE+INSERT 为原子操作 |
| 2 | `vision/pdfium.rs:37,73,103` | 逻辑缺陷 | `page_index as u16` 类型截断。i64 直接 `as u16`：负值 -1→65535 访问错误页面，超过 65535 会溢出到 0。 | `u16::try_from(page_index).with_context(...)` 做范围检查 |

### P1 — 中严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 3 | `vision/pdfium.rs:30,65,96` | 逻辑缺陷 | `expect("PDFIUM mutex poisoned")` 导致 panic 传播。某次调用 panic 后所有后续 PDF 操作都会 panic。 | 返回 `Err` 而非 `expect` |
| 4 | `config.rs` 多处 | 逻辑缺陷 | RwLock 中毒时静默返回默认值，无日志警示。锁中毒后每次调用都从磁盘重新加载，性能退化。 | 锁中毒时至少 `tracing::warn!` |
| 5 | `text.rs:100-110` | 逻辑缺陷 | 浮点数直接用 `!=` 比较。OCR/PDF 坐标场景下极不可靠，同行 block 的 y 坐标可能差 0.001，导致排序错误。 | epsilon 比较 `(y_a - y_b).abs() > EPSILON` |
| 6 | `db/repository.rs` | 逻辑缺陷 | `review_id` 读取时通过 `format!("review-{}", idx)` 重建而非从 DB 读取。若 review_id 在其他地方被引用会关联失效。 | DB 中存储原始 review_id |

### P2 — 中等

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 7 | `db/repository.rs:210-233` | 偷懒代码 | `normalize_heading_family_guess` 未知值映射为 `"unknown"` 丢失原始信息 | 保留原始值 |
| 8 | `db/repository.rs:367-384` | 偷懒代码 | `SectionHeadRecord` 写入时多个字段硬编码占位值（confidence=1.0 等） | 增加字段或注释说明 |
| 9 | `note_marker.rs` | 性能 | `chars().nth(cursor)` 在循环中 O(n²) 复杂度 | 改用 `for ch in s.chars()` |
| 10 | `ref_rewriter.rs:100-120` | 性能 | `local_endnote_ref_number` 内 O(n) 线性扫描分配编号，总复杂度 O(N²) | 维护 `HashSet<i64>` |
| 11 | `ref_rewriter.rs` | 代码重复 | `replace_raw_footnote/endnote_refs_with_local_labels` 逻辑几乎相同 | 提取泛化函数 |
| 12 | `records.rs` | 代码重复 | Phase*Summary 大量字段重复，无共享基础结构体 | `#[serde(flatten)]` 复用 |
| 13 | `segment_codec.rs` | 类型设计 | 全程操作 `serde_json::Value`，key 名全是字符串字面量 | 定义类型化 struct |
| 14 | `model_capabilities.rs` | 过度防御 | ~40 个模型规格硬编码在 match 分支中 | 外部化为配置文件 |
| 15 | `export_constants.rs` / `note_lookup.rs` | 命名冲突 | `NOTE_TEXT_BODY_MARKUP_RE` 在两个模块中名字相同但正则不同 | 加模块前缀区分 |
| 16 | `vision/spec.rs` | 逻辑缺陷 | `spec_hash()` 基于 Debug trait 输出计算哈希，无稳定性保证 | 手动构建 hash 输入 |
| 17 | `token_counter.rs` | 测试问题 | 全局 `USAGE_RECORDS` 并行测试数据污染 | 用 `#[serial]` 或实例化 struct |

### P3 — 轻微

| # | 描述 |
|---|------|
| 18 | `refs.rs:267` — `use serde::{...}` 放在文件末尾而非顶部 |
| 19 | `title.rs` — `guess_title_family` 中 "introduction" 硬编码特例可能与正则重叠 |
| 20 | `chapters.rs` — `sort + last` 可用 `max_by_key` O(n) 替代 |
| 21 | `anchor_kind.rs` — 7 个 if 分支可用数据驱动 `(Regex, AnchorKind)` 数组替代 |
| 22 | `note_modes.rs` — 双向映射表需手动同步，应从单一数据源生成 |
| 23 | `config.rs` — `project_root()` 向上遍历 6 级目录，应支持环境变量 |
| 24 | `db/pool.rs` — 连接池大小硬编码为 4 |
| 25 | `db/schema.rs` — `ensure_contract_columns` 手动检查列存在性，与 migration 可能冲突 |
| 26 | `review_overrides.rs` — 7 个 scope 硬编码为字符串，应用 enum |
| 27 | `testing/mod.rs` — 空模块 |
| 28 | 测试文件 — setup 函数在 4 个测试文件中重复 |

## 值得肯定的地方

1. **`enum_with_str!` 宏**：一个宏为 12 个 enum 生成 `as_str()`/`FromStr`/`ALL`/`serde` 支持，消除手动 boilerplate
2. **Python parity 测试**：通过 JSON fixture 与 Python 输出逐字段对齐
3. **DB round-trip 测试**：Phase 1-6 读写路径全覆盖，含恶意数据注入防御测试
4. **`MarkerRewriteContext`**：将多参数封装为上下文结构体
5. **`UsageRecord` 优雅降级**：mutex 中毒时返回带 `_error` 字段的空 summary
6. **segment_codec 新旧格式兼容**：同时处理新旧 key 名
