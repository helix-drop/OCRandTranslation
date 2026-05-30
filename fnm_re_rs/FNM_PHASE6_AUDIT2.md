# FNM-PHASE6 审计报告（独立第二轮）

> 审计范围：`fnm-phase6` crate 全部 21 个 `.rs` 文件（约 4,244 行）。整书组装 + ZIP 导出 + 导出审计。
> 维度：程序逻辑、Rust 风格、过度防御/偷懒/AI 常见病。业务规则不评判。
> 方法：逐文件精读核心 + 反模式 grep 全覆盖 + 文件IO/zip 安全核实。审计期间未参考现有 `audit/`。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

---

## 0. 总体印象：高质量（与 phase3/4/5 同档），几乎无需修复

phase6（导出 + 审计）质量高，且在导出 crate 易出问题的几处都做对了：

- **ZIP-slip 防护**：[export/zip.rs:50-57](fnm-phase6/src/export/zip.rs) 过滤 `..`/`.`/空段 + `trim_start_matches('/')`，再 join 成 safe_path（测试 `zip_safe_path_dotdot` 验证）。
- **内存 ZIP（不落盘）**：用 `Cursor<Vec<u8>>`，无磁盘路径拼接，从根本上消除路径穿越/权限问题。
- **只读组装器**：[book_assemble/mod.rs:11](fnm-phase6/src/book_assemble/mod.rs) 注释「Phase6 为只读组装器：不修改 ChapterMarkdownEntry.markdown_text」，测试 `contract_phase6_does_not_modify_garbled_content` 验证乱码/控制字符原样保留（符合 CLAUDE.md §7 不猜测修补）。
- **审计正向验证**（CLAUDE.md §phase6 = 导出审计）：`audit_file_paths` 比对 bundle vs ZIP 实际路径（缺失/多余）；`audit_chapter_organization` 检测 post_body 缺失 / container 误导出为章 / 导出深度不足；`compute_semantic_gates` book-level raw marker leak；helpers 提供完整正向检测族（front_matter_opening / mid_sentence_opening / missing_tail / mid_paragraph_heading / duplicate_paragraph / raw_note_marker_hits）。
- **全部 unwrap 安全**：非测试 unwrap 仅 patterns.rs 5 处（全为 `Regex::new(...)` 编译期常量）；diagnostics.rs 2 处在测试。生产代码无 `panic!`/`expect`（均在测试）。
- 全 crate **无** `#[allow]`/`Runtime`/`as` 窄化/死代码丢弃；clippy clean。

---

## 1. 🟡 低优先级 / 观察（无真 bug）

- [diagnostics.rs](fnm-phase6/src/diagnostics.rs) 632 行（phase6 最大文件），是导出诊断聚合（chapter issue / print page map / 各类 summary）。职责单一但偏大，可按诊断类别拆分子模块；非必须。
- ZIP 写入对 `start_file`/`write_all` 用 `?` 传播错误（正确）；`build_export_zip` 整体返回 `Result`，调用方 book_assemble 也 `?` 上抛——错误处理链完整。
- 审计 file record 的 severity 用裸字符串 `"blocking"`（stringly-typed），与全局 enum 化方向略有出入，但仅审计报告内部使用，影响小。

---

## 2. 正面实践细节
- `build_module_export_bundle` 15 步线性组装，gate 计算（order_follows_toc / no_cross_chapter_contamination / export_semantic_contract_ok / missing/extra chapter）齐全。
- `read_markdown_files` 优先从 ZIP 读（验证真实产物），无 ZIP 时回退 bundle.files——审计对象是「实际写出的字节」而非内存假设。
- `build_followups_and_must_fix` 按 issue_code 计数排序 top-8 followups + blocking must_fix，诊断可操作。
- helpers `alphanumeric_key` / `split_body_and_definitions` 复用一致的正文/定义切分逻辑。

---

## 3. 文件覆盖确认（21/21）
lib｜diagnostics｜book_assemble/{mod,bundle_builder,chapter_order,marker_leak,toc_titles}｜export/{mod,contract,index_render,markdown_clean,paragraph_key,zip,tests}｜export_audit/{mod,audit_logic,zip_read,file_audit/mod,file_audit/tests,helpers/mod,helpers/patterns}

> 逐字精读 zip + book_assemble/mod + export_audit/audit_logic + helpers 函数清单 + patterns；其余经反模式 grep（clean）+ unwrap 全确认 + 去注释 cat 覆盖。

**核心结论**：phase6 是高质量收尾 crate，ZIP-slip 防护到位、只读组装不改正文、审计走正向验证、全部 unwrap 安全。无需修复，仅 diagnostics.rs 偏大为可选清理。
