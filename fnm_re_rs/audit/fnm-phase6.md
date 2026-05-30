# fnm-phase6 审计报告

**审计日期**：2026-05-29
**代码规模**：21 文件，4,244 行
**编译状态**：零 warning，62 测试全通过

## 总体评价

负责导出审计。代码质量整体良好。无 `todo!`/`unimplemented!`/`panic!`，生产代码无裸 `unwrap()`，错误处理使用 `anyhow::Result` + `thiserror`。模块划分清晰（book_assemble/export/export_audit/diagnostics）。无偷懒代码。

## 问题清单

### P0 — 高严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 1 | `export_audit/file_audit/mod.rs:320` | **逻辑缺陷** | `last.chars().rev().take(120).collect::<String>()` 产出字符**倒序**的字符串（"Hello" → "olleH"），不是有意义的诊断信息 | 取最后 120 字符：`.rev().take(120).collect::<Vec<_>>().into_iter().rev().collect()` |

### P1 — 中严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 2 | `export/contract.rs:55-134` | 弱类型 | `compute_export_semantic_contract` 返回 `HashMap<String, bool>`，调用方用字符串键取值，拼写错误无法编译期捕获 | 定义 `SemanticContractResult` struct |

### P2 — 低严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 3 | `book_assemble/mod.rs:66,81-83` | 性能 | 大型 HashMap/Vec 被 clone 3-4 次 | move 而非 clone |
| 4 | `book_assemble/mod.rs:40` | 死参数 | `_book_structure_model: Option<&BookStructureModel>` 未使用，导致多余依赖 fnm-phase2 | 移除参数和依赖 |
| 5 | `book_assemble/toc_titles.rs:26` | 死参数 | `_toc_tree: &[TocNode]` 未使用 | 移除 |
| 6 | `diagnostics.rs:15,19` | 命名 | `_ERROR_TRANSLATION_STATUSES` / `_DONE_UNIT_STATUSES` 以下划线开头但在生产代码中多处使用 | 去掉下划线前缀 |
| 7 | `export_audit/helpers/patterns.rs:82,90,123,132` | 命名 | 同 #6，多个常量以下划线开头但被使用 | 去掉下划线前缀 |
| 8 | `export/contract.rs:22` + `paragraph_key.rs:10` | 代码重复 | `WHITESPACE_RE` 同模块两处定义 | 提取共享 |
| 9 | `export_audit/helpers/mod.rs:50-58` | 逻辑缺陷 | `alphanumeric_key` 只保留 ASCII，中文/法语特殊字符全部丢弃，纯中文标题返回空字符串 | 改用 `c.is_alphanumeric()` |
| 10 | `diagnostics.rs:384-391` | 过度防御 | `raw_segment` 被先 `to_value()` 再 `from_value()` 双重序列化 | 直接使用或只走一条路径 |
| 11 | `diagnostics.rs:453` | 逻辑可疑 | `start_page` 使用 `.max()` 取较大值，语义上"开始页"通常应取较小值 | 核实 Python 原始逻辑 |

### P3 — 轻微

| # | 描述 |
|---|------|
| 12 | `book_assemble/mod.rs:57` — 步骤注释编号跳过了 3 |
| 13 | `export_audit/mod.rs:102-104` — clone 所有章节仅为适配函数签名 |
| 14 | `export/zip.rs:21` — `bundle.files.clone()` 可用 Cow 避免 |
| 15 | `diagnostics.rs:243-261` — refs 候选列表冗余，大部分被 seen_refs 去重丢弃 |
| 16 | `helpers/mod.rs:185` — `lines.len() - 1` 依赖隐式前置守卫，用 `saturating_sub` 更安全 |

## 值得肯定的地方

1. **零编译警告**
2. **良好测试覆盖**：62 个测试含 ZIP 打包/解包、语义合同、章节排序、文件审计
3. **安全 ZIP 处理**：过滤 `..` 和 `.` 路径段防路径穿越，有测试验证
4. **只读保证**：Phase6 声明"不修改正文内容"，有合同测试验证（含控制字符和重复段落场景）
5. **无偷懒代码**：全文无 todo!/unimplemented!/空函数体
6. **模块划分清晰**：book_assemble/export/export_audit/diagnostics 四大模块
