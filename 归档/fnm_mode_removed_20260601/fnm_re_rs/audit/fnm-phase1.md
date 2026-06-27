# fnm-phase1 审计报告

**审计日期**：2026-05-29
**代码规模**：58 文件，12,884 行
**编译状态**：零 warning

## 总体评价

负责页面角色分类和章节边界检测。从 Python 逐模块对齐移植，整体架构清晰、模块拆分合理。主要问题集中在：少量可导致 panic 的操作（字节切片、类型截断、浮点 partial_cmp）、多处死代码和重复定义、个别超长函数。

## 问题清单

### P0 — 高严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 1 | `toc_structure.rs:303` | 边界条件 | `&tk[..tk.len().min(20)]` 对多字节 UTF-8 字符串做字节切片，可能在字符中间切断导致 panic | 用 `tk.chars().take(20).collect::<String>()` |
| 2 | `chapter_skeleton/pdf_font.rs:65` | 类型截断 | `pages.get(idx as u16)` 将 i64 截断为 u16，负值或大值导致访问错误页面 | `u16::try_from(idx).ok()` |
| 3 | `heading_candidates/pdf_font_band.rs:256,263` | 浮点 panic | `.partial_cmp(...).unwrap()` 遇到 NaN 时 panic | `.unwrap_or(Ordering::Equal)` 或 `total_cmp()` |

### P1 — 中严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 4 | `book_note_type/mod.rs:364-366` | 逻辑错误 | `has_footnote` 检查包含 `ChapterEndnotePrimary`，语义上尾注不应算 footnote | 只检查 `FootnotePrimary` |
| 5 | `heading_candidates/toc_candidates.rs:133-146` | 不完整实现 | `resolve_toc_item_page()` 忽略 `_toc_offset`/`_raw_pages`/`_file_idx_map`，缺少 fallback | 实现完整解析或简化签名 |
| 6 | `fallback.rs:715` vs `normalize.rs:10` | 语义分裂 | 两处 `is_sentence_like_heading()` 实现不同（6词/8词阈值，不同标点集），同一标题可能判定不一致 | 统一为一个实现 |
| 7 | `toc_semantics/page_resolve.rs:41-64` | 性能 | `trimmed.remove(0)` 在循环中 O(n) 操作导致 O(n²) | 用 `VecDeque::pop_front()` |
| 8 | `page_partition/mod.rs:153` | 死值 | `_synthetic = build_synthetic_page_by_no(...)` 计算结果未使用，浪费 CPU 和内存 | 删除调用 |

### P2 — 低严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 9 | `fallback.rs:85,222,665` | 死代码 | 三处 `#[allow(dead_code)]`：`SectionRow`、`ClassifiedSection`、`merge_section_heads` 均未使用 | 删除 |
| 10 | `heading_graph/title_key.rs:11` | 死代码 | `_TRAILING_NOTE_MARKER_RE` 未使用的已编译正则 | 删除 |
| 11 | `toc_semantics/title_utils.rs:102,149` | 死代码 | `_CHAPTER_KEYWORD_RE` 和 `_YEAR_RANGE_RE` 未使用 | 删除 |
| 12 | 多文件 | 代码重复 | `NOTES_HEADER_RE` 在 4 个位置重复定义，正则略有不同 | 统一定义，命名区分严格/宽松版 |
| 13 | `section_heads.rs:75` | 死代码 | `_chapter_title_key_map` 计算后未使用 | 删除 |
| 14 | `builder.rs:423-442` | 冗余分支 | 三个 if/else 分支执行完全相同的操作 | 合并为一个无条件块 |
| 15 | `builder.rs:447` | 不必要 clone | `heading_candidates.clone()` 克隆整个 Vec | 传引用或 move |

### P3 — 轻微

| # | 描述 |
|---|------|
| 16 | `toc_semantics/mod.rs:107-688` — 超长函数 580 行，应拆分 |
| 17 | `fallback.rs` — 1215 行最大文件，应按关注点拆分 |
| 18 | `section_heads.rs:174` — 排序中 O(n*m) 线性查找，应预建 HashMap |
| 19 | `pdf_font_band.rs:184` — `safe_y()` 定义在函数内部，非惯用 |
| 20 | `book_note_type/mod.rs:311` — `serde_json::to_value(p)` 转整个 RawPage 仅为提取文本 |
| 21 | `toc_tree.rs:248` — `has_number_prefix` 仅检查 2 位数字+点，无法处理 "10.1" 或罗马数字 |
| 22 | `continuation/mod.rs` — 多处重复 clone `page_headings`/`page_texts` |
| 23 | `heading_candidates/matching.rs:80` — `is_anchor_candidate` 每次对 page_roles 线性扫描 |

## 值得肯定的地方

1. **规则引擎架构**：`page_partition/rules/` 每个规则独立成文件，优先级明确，扩展性好
2. **Heading graph 三轮解析**：local_exact → expanded_exact → monotonic_target 分层策略，渐进放宽
3. **正则集中管理**：`patterns.rs` 统一定义和预编译
4. **程序合同 gate_report**：hard/soft gate 对输出质量结构化验证
5. **LLM 验证模块**：异步设计、multi-model fallback、graceful degradation
6. **类型安全 PageRole**：enum 而非裸字符串，编译期防拼写错误
7. **延续性修复有序**：五个 continuation fix 明确顺序，manual override 最后
