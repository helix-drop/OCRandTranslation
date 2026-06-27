# fnm-phase5 审计报告

**审计日期**：2026-05-29
**代码规模**：20 文件，3,067 行
**编译状态**：零 warning

## 总体评价

负责章 markdown 合并。整体质量较好，模块划分清晰（核心入口 + 转换层 + 渲染层），测试覆盖含单元测试和真实 fixture 数据测试。无 P0 问题。主要问题集中在代码重复、未使用参数暗示功能不完整、弱类型 JSON 传递。

## 问题清单

### P1 — 中严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 1 | `render/footnote.rs:21-26` | 功能缺失 | 4 个 `_` 前缀参数被完全忽略，inline footnote 路径缺失 marker 重写、skipped note 处理、note_kind 过滤 | 实现或缩小签名+TODO |
| 2 | `render/footnote.rs:101-108` | 空上下文 | `rewrite_body_text_with_local_refs` 被传入 3 个空 HashMap，raw marker 会残留在输出中 | 与 #1 一并修复 |
| 3 | `lib.rs:86-101,111-127` | 代码重复 | `ChapterMarkdownEntry` 构造逻辑几乎一模一样出现两次 | 第二次只替换 `markdown_text` |
| 4 | `render/markdown_clean.rs:24` | 理论无限循环 | `loop` 反复 replace_all，若正则匹配空字符串可能死循环 | 加 iteration 上限 |
| 5 | `render/filename.rs:35` | 理论无限循环 | while 循环 suffix 递增无上限 | 加 suffix 上限 |
| 6 | `marker_rewrite.rs:47` | 冗余逻辑 | `starts_with("### NOTES") \|\| == "### NOTES"` 第二条件被第一条完全覆盖 | 删除冗余条件 |

### P2 — 低严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 7 | `render/body_render.rs:104` | 风格 | `use HashMap` 在函数体内 | 移到顶部 |
| 8 | `render/title.rs` | 过度抽象 | 6 行空壳函数只做 `title.to_string()` | 考虑 inline |
| 9 | `lib.rs:136-158` | 弱类型 | `serde_json::Value` 传递 export_summary/chapter_issue_counts | 定义 `MergeSummary` struct |
| 10 | `diagnostics.rs:67-76` | 弱类型 | `Vec<serde_json::Value>` 存 chapter_issue_summary | 定义 struct |
| 11 | `convert.rs:110-141` | 代码重复 | 逐字段手动映射 14 个字段 | 用 `From` trait |
| 12 | `convert.rs:146-185` | 代码重复 | 逐字段手动映射 22 个字段 | 用 `From` trait |
| 13 | `section_render.rs:51` + `convert.rs:187` | 代码重复 | `safe_int` 函数两处定义 | 提取到公共位置 |
| 14 | 三处 page_numbers | 代码重复 | 从 page_segments 提取页码逻辑在 body_render/section_builder/footnote 复制三次 | 提取公共函数 |
| 15 | `section_render.rs:269-295` | 逻辑可疑 | body units 循环已插入 section heads，循环后又独立遍历追加到末尾 | 确认兜底意图 |

### P3 — 轻微

| # | 描述 |
|---|------|
| 16 | `phase5_shadow.rs:37-57` — book_type 推导与 `book_type.rs` 重复 |
| 17 | `render/footnote.rs:129-137` — contract_summary 全部硬编码 0，未实际计算 |
| 18 | `diagnostic_helpers.rs:34-47` — 只检测 `### ` 三级标题，不检测其他级别 |
| 19 | `render/section_head.rs:9` — `level >= 0` 允许 level=0，可能无效 |
| 20 | `lib.rs:254-262` — chapters 为空时两个 warn 检查无意义 |
| 21 | `render/merge.rs:32-52` — filter 后 clone 整个 Vec，可改为引用 |

## 值得肯定的地方

1. **Phase 隔离**：只透传 Phase2 的 `chapter_note_modes`，不重新推导，有合同测试验证
2. **章节边界不被 endnote region 污染**：有专门 fixture 测试
3. **测试质量高**：空输入、正常路径、边界条件、幂等性全覆盖
4. **无 `allow(clippy::xxx)` 滥用**：全 crate 仅 1 个合理的 `expect`
5. **非测试代码无裸 `.unwrap()`**
6. **模块可见性控制合理**：`pub(super)` 限制内部使用
