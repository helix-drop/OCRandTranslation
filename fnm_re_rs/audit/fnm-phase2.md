# fnm-phase2 审计报告

**审计日期**：2026-05-29
**代码规模**：53 文件，11,344 行
**编译状态**：零 warning

## 总体评价

负责 note_kind 分类、note_mode 聚合、sup_recovery 三层架构、visual anchor recovery 等核心决策。架构清晰，决策树设计严谨（note_kind_resolver 优先级链、chapter_split 穷尽 match）。主要问题：跨模块代码重复（3 处函数级、2 处正则级）、少量潜在 panic 和静默数据丢失、性能热点（循环内创建 tokio Runtime、Mutex 正则缓存）。

## 问题清单

### P0 — 高严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 1 | `endnote_chapter_explorer/boundary_fallback.rs:407` | 边界条件 | `chapters[0].chapter_id.clone()` 无空数组守卫。调用方已检查但函数自身缺防御 | 函数开头加 `if chapters.is_empty()` 守卫 |
| 2 | `chapter_split/mod.rs:216-217` | 静默数据丢失 | `serde_json::to_value(p).unwrap_or_default()` 序列化失败返回 Null，下游静默产生错误投影 | 用 `?` 传播或至少 `warn!` |
| 3 | `chapter_split/endnote_project.rs:89-96` | 逻辑缺陷 | `unwrap_or(1000000)` 哨兵值。全部页码解析失败时 endnote 被分配给 distance=1000000 的章节 | 用 `Option<i64>` 替代哨兵值 |

### P1 — 中严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 4 | `sup_recovery/mod.rs:107` | 性能 | `tokio::runtime::Runtime::new()` 在 per-chapter 循环内调用，每次创建线程池 | 循环外创建一次 Runtime |
| 5 | `sup_recovery/layer2.rs:174-188` | 性能 | `Mutex<HashMap<String, Regex>>` 正则缓存在 rayon 并行中每次加锁 | 改用 `DashMap` 或 `thread_local!` |
| 6 | `endnote_repair/mod.rs` | 逻辑缺陷 | `repair_truncated_note_items` 只处理单步截断链，连续缺失多个 marker 不会被修复 | 改为迭代式修复 |
| 7 | `note_regions/book_regions.rs:51-52` | 死代码 | `if rebound.is_empty()` 分支永不执行（前面的 else 已 push+continue） | 删除死分支 |
| 8 | `chapter_split/overrides_apply.rs:82` | 静默忽略 | `_ => {}` 静默忽略未知 override action 类型 | 加 `warn!` 或返回错误 |
| 9 | `visual_anchor_recovery/parsing.rs:259` | 逻辑缺陷 | `VISUAL_ANCHOR_SERIAL` 全局 AtomicU64 跨书累加不重置 | per-context 计数器或每书重置 |
| 10 | `note_kind_resolver.rs:19` | 死代码 | `explicit_markers` 字段从未被使用（所有调用方传 `&[]`） | 删除 |

### P2 — 低严重度

| # | 文件 | 类别 | 描述 | 建议 |
|---|------|------|------|------|
| 11 | layer3/vision_client/llm_client | 代码重复 | `extract_json_block` 在三个文件中完全重复 | 提取到 fnm-core |
| 12 | endnote_candidate/endnote_regions_raw | 代码重复 | `has_endnote_scan_items` 两份相同 | 保留一份 |
| 13 | note_items/endnote_repair | 代码重复 | `PAGE_CITATION_PREFIX_RE` 两处定义 | 提到公共位置 |
| 14 | endnote_regions_raw/post_body_promote | 代码重复 | `compute_body_bounds` 各实现一次 | 提取公共函数 |
| 15 | `endnote_regions_raw.rs:200-230` | 风格 | `flush_region` 闭包接受 8 个 `&mut` 参数 | 封装为 `RegionBuilder` struct |
| 16 | `synth_markers.rs:19` | 性能 | `sort_by_key(|i| i.marker.clone())` 每次比较 clone String | `sort_by(|a,b| a.marker.cmp(&b.marker))` |
| 17 | `matching.rs:16,53` | 死代码 | `#[allow(dead_code)]` 标注的字段 | 移除 allow 或删除字段 |
| 18 | `boundary_fallback.rs` | 不必要 clone | 大量 `region.clone()` 在分支中反复出现 | 考虑 `Cow` |
| 19 | `endnote_project.rs:1-5` | 风格 | 完整路径 `crate::chapter_split::...` 而非 `use` 导入 | 统一为 `use` |
| 20 | `note_items/note_scan.rs` | 过度封装 | trivial wrapper（各约 10 行），无额外逻辑 | 考虑内联 |

### P3 — 轻微

| # | 描述 |
|---|------|
| 21 | `sequence_repair.rs` — 年份范围硬编码 1500-2100，对古籍可能偏高 |
| 22 | `numbering.rs` — roman_to_int 不处理非法输入如 "IIII" |
| 23 | `layer2.rs` — `scan_blocks_for_markers` 无 block 解析失败的单元测试 |
| 24 | `materialize.rs` — 模糊匹配阈值 0.6 硬编码 |
| 25 | `lib.rs` — 管线各步骤缺少 timing 日志 |

## 值得肯定的地方

1. **note_kind_resolver 决策树**：7 级优先级链条清晰，每级条件互斥
2. **chapter_split 穷尽 4-branch match**：`(fn_dominant, has_heading)` 四种组合全显式处理
3. **sup_recovery 三层架构**：Layer1(正则) → Layer2(OCR block) → Layer3(Vision LLM)，职责单一
4. **UTF-8 安全处理**：block text 切片使用 `char_indices`
5. **正则统一 `Lazy<Regex>`**
6. **endnote_chapter_explorer 3 路径**：TOC subentry → page signal → boundary fallback
7. **book_structure.rs exhaustive match**：无 wildcard
