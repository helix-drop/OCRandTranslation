# fnm-phase4 审计报告

**审计日期**：2026-05-29
**代码规模**：19 文件，6,038 行
**编译状态**：零 warning，零 clippy lint

## 总体评价

负责引用注入和翻译单元。结构清晰，4 个子模块（ref_freeze/segments/text/units）职责边界清楚。`#![deny(unused_must_use)]` 开启。总体质量中上，但存在 1 个 P0 级可导致 panic 的运算符优先级 bug。

## 问题清单

### P0 — 高严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 1 | `text/markdown_parse.rs:911-912` | **运算符优先级 panic** | `!result.is_empty() && result[0]...== "cont_prev" \|\| result[0]...== "cont_both"` — `&&` 优先级高于 `\|\|`，result 为空时 `\|\|` 右侧仍执行 `result[0]` 导致越界 panic | 加括号：`&& (... \|\| ...)` |

### P1 — 中严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 2 | `ref_freeze/mod.rs:196,344,370` | unwrap 风险 | 三处 `page_data.as_object_mut().unwrap()` | 用 `.expect()` 或 `if let` |
| 3 | `ref_freeze/mod.rs:121` | 溢出风险 | `(-char_a).cmp(&(-char_b))` 对 i64 取负做逆序，`i64::MIN` 时未定义 | 改为 `char_b.cmp(&char_a)` |
| 4 | `ref_freeze/mod.rs:143` | 性能 | `page_order.contains(&page_no)` 在循环中对 Vec 线性查找 O(n²) | 用 `HashSet<i64>` |
| 5 | `text/markdown_parse.rs:328` | unwrap 风险 | `probe.chars().next().unwrap()` 当 probe 为空时 panic（虽有字节长度守卫） | `if let Some(first_char)` |
| 6 | `text/markdown_parse.rs:384-388` | 性能 | `normalize_heading_key(...)` 被完全相同参数调用两次 | 缓存到局部变量 |

### P2 — 低严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 7 | `ref_freeze/contract.rs` | **死代码** | `SkipReason`/`SkipCategory` 枚举及函数在整个 crate 中无调用方。`mod.rs` 用本地闭包+字符串完成同一功能 | 统一使用枚举或删除 |
| 8 | 多处 | 性能 | `Regex::new(...).unwrap()` 出现在非 `Lazy` 上下文，每次调用重编译正则（热路径） | 提升为 `static Lazy<Regex>` |
| 9 | `segments/mod.rs:16` + `units/page_split.rs:196` | 代码重复 | `synthetic_markdown_pages` 完全相同实现 | 保留一份 |
| 10 | `ref_freeze/mod.rs` | 超长函数 | `build_frozen_units` 760 行含 7 个 Phase | 按 Phase 拆分为子函数 |
| 11 | `ref_freeze/mod.rs` | 弱类型 | `HashMap<String, HashMap<i64, serde_json::Value>>` 传递页面数据 | 定义 `BodyPageData` struct |
| 12 | `lib.rs:51-55` | 魔法字符串 | `r.skip_category == "ceiling_skip"` 字符串匹配 | 用 #7 的枚举替代 |
| 13 | `markdown_parse.rs:829` | 可读性 | `1.max(6.min(toc_item.depth + 1))` | 改为 `.clamp(1, 6)` |
| 14 | `units/page_split.rs` | 可见性 | 多个 `pub` 函数 crate 内无调用 | 加注释或降为 `pub(crate)` |

### P3 — 轻微

| # | 描述 |
|---|------|
| 15 | `segments/chunking.rs:116` — `_segment_display` 计算后未使用 |
| 16 | `lib.rs:27` — `#[cfg(test)]` import 应移到 `mod tests` 内 |
| 17 | `markdown_parse.rs:132-135` — `get_page_note_scan` 永远返回 default，需醒目 TODO |
| 18 | `reviews.rs:238-244` — `NoteKind::Unknown` 产生的 review_type 被白名单静默丢弃，缺注释 |
| 19 | `tests/spec_tests.rs:42 vs 275` — 完全相同的测试重复定义 |
| 20 | `input.rs` — `raw_pages`/`note_regions` 等字段在 `build_phase4_structure` 中未引用 |

## 值得肯定的地方

1. **模块划分清晰**：ref_freeze/segments/text/units 无循环依赖
2. **类型系统**：`Phase4Input<'a>` 用生命周期借用，`InjectionOutcome` 优于元组
3. **注入 7 层候选逻辑**：`inject.rs` 从精确坐标到宽松 fallback 逐级降级
4. **字符坐标正确转换**：`character_range_to_byte_range` 正确处理 Python 字符索引到 Rust 字节索引
5. **`#![deny(unused_must_use)]`**
6. **零 clippy warning**
