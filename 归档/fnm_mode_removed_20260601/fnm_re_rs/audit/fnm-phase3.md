# fnm-phase3 审计报告

**审计日期**：2026-05-29
**代码规模**：41 文件，11,878 行
**编译状态**：零 warning

## 总体评价

负责 body anchor 检测和 note link 匹配。整体质量中等偏上，模块划分清晰、注释充分（含 Python 行号对照）、错误处理整体合理。主要不足：部分 `unwrap()` 可被更安全的 pattern 替代，`serde_json::Value` 运行时操作模式脆弱，少量边界条件遗漏，存在死代码/冗余转换层。

**统计**：非测试 unwrap() 46 处，非测试 clone() 223 处，todo!/unimplemented! 0，unsafe 0。

## 问题清单

### P0 — 高严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 1 | `endnote_links.rs:434-436` | 边界条件 | Unicode 上标搜索 `byte_end = byte_start + unicode_pat.len()` 可能越界，后续 `text[byte_end..]` panic | 加 `byte_end.min(body_text.len())` 守卫 |
| 2 | `gap_recovery.rs:483-492` | 代码重复 | `extract_context` 在 endnote_links.rs 和 gap_recovery.rs 各实现一次，分别维护可能分叉 | 提取为公共工具函数 |

### P1 — 中严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 3 | `anchor_overrides.rs:66,112,127` | unwrap 滥用 | `summary["rejected_reasons"].as_array_mut().unwrap()` 约 12 处，JSON 结构被篡改时 panic | 用强类型 struct 替代 Value 做 summary |
| 4 | `endnote_links.rs:85-112` | 逻辑冗余 | book-scope fallback 搜索与首次搜索参数完全一样，首次返回空则 fallback 必然也空 | 确认是否需放宽条件，否则删除 |
| 5 | `gap_recovery.rs:174-185` | 死分支 | `right_stripped.trim_start()` 再 trim 一次后 `c.is_whitespace()` 永远为 false | 重新审视意图，对 `right` 操作 |
| 6 | `paragraph_footnotes.rs:167-181` | 可读性 | `para_idx` 赋值后在 Some 分支 continue，写法易误读 | 简化为 if-else |

### P2 — 低严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 7 | `lib.rs:122` | 错误吞没 | `serde_json::to_value(...).unwrap_or(Value::Null)` 约 5 处 | 至少 `tracing::warn!` |
| 8 | `lib.rs:217-241` | 风格 | `use std::collections::HashMap` 在函数体内 | 移到文件顶部 |
| 9 | `body_anchors/mod.rs:76` | 类型设计 | `HashSet<(String,String,String,i64,i64,i64,i64)>` 7 元组做 key | 定义 `AnchorDedupeKey` struct |
| 10 | `body_anchors/mod.rs:123` | 不必要 clone | `chapter_id.clone()` 每次内层循环 | 改 HashSet 为 `(&str, i64)` |
| 11 | `pattern_scan.rs:81` | unwrap 风格 | `caps.get(0).unwrap()` 约 12 处 | 改为 `.expect("regex group 0")` |
| 12 | `context_guard.rs:47-59` | 风格 | `HashSet` 用 12 行 `insert()` 初始化 | `HashSet::from([...])` |
| 13 | `layer_conversion.rs` | 死代码 | `to_anchor_layers`/`to_link_layers` 只是 `.to_vec()`，无调用者 | 删除或标记 deprecated |
| 14 | `phase2_rebuild.rs:140` | 风格 | `eprintln!` 用于生产日志 | 改为 `tracing::warn!` |
| 15 | `note_linking/mod.rs:309` | 不必要 clone | `all_override_logs.clone()` 可能不必要 | 检查是否可 move + 引用 |
| 16 | `endnote_links.rs:326-341` | 语义不精确 | orphan recovery 使用 `page_nos[0]` 作为 page_no 而非实际匹配所在页 | 记录页面边界偏移 |
| 17 | `endnote_repair/contract_repair.rs:45-50` | 性能 | `anchors.to_owned()` 全量克隆绕过 borrow checker | index-based lookup |
| 18 | `dp_alignment.rs:226` | 性能 | Needleman-Wunsch O(n*m) 内存，1000+ endnote 时 ~8MB | 当前可接受 |

### P3 — 轻微

| # | 描述 |
|---|------|
| 19 | `body_anchors/mod.rs:88` — 空字符串 `""` 作为有效 page_role，缺注释 |
| 20 | `paragraph_endnotes.rs:18-20` — `_chapters`/`_pages`/`_raw_pages` 未使用参数 |
| 21 | `footnote_links.rs:23` — `synthetic_serial` 从未更新 |
| 22 | `paragraph_footnotes.rs:195` — `_anchor_matched_count` 计算后未使用 |
| 23 | `note_item_overrides.rs:22` — `HashMap::new()` 被创建然后 clone |
| 24 | `anchor_summary.rs:66` — `if let Some(ref mut map)` 可简化为 expect |

## 值得肯定的地方

1. **Python 行号对照注释**：几乎每个函数标注 `←→ Python ...`
2. **铁律约束注释**：关键位置标注遵循哪条铁律
3. **`mem::take` 替代 clone**：OCR repair 三个 loop 大量使用
4. **无 `todo!`/`unimplemented!`/`unsafe`**
5. **Regex 预编译**：全部 `Lazy<Regex>`，动态正则也有 `MarkerPatterns` cache
6. **类型安全枚举**：`LinkStatus`、`NoteKind`、`AnchorKind` 等
7. **测试覆盖**：ocr_repair、endnote_repair 等核心模块有充分单元测试
