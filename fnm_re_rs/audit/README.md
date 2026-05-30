# FNM Rust 代码库审计总览

**审计日期**：2026-05-29
**审计范围**：10 个 crate，287 个 `.rs` 文件，73,258 行代码
**审计重点**：程序逻辑、Rust 代码风格、AI 写代码常见问题（不含业务逻辑）

## 全局问题统计

| Crate | 文件 | 行数 | P0 | P1 | P2 | P3 |
|-------|------|------|-----|-----|-----|-----|
| [fnm-core](fnm-core.md) | 37 | 11,355 | 2 | 4 | 11 | 15 |
| [fnm-phase1](fnm-phase1.md) | 58 | 12,884 | 3 | 5 | 7 | 8 |
| [fnm-phase2](fnm-phase2.md) | 53 | 11,344 | 3 | 7 | 10 | 5 |
| [fnm-phase3](fnm-phase3.md) | 41 | 11,878 | 2 | 4 | 12 | 6 |
| [fnm-phase4](fnm-phase4.md) | 19 | 6,038 | 1 | 5 | 8 | 6 |
| [fnm-phase5](fnm-phase5.md) | 20 | 3,067 | 0 | 6 | 9 | 6 |
| [fnm-phase6](fnm-phase6.md) | 21 | 4,244 | 1 | 1 | 5 | 5 |
| [fnm-llm-repair](fnm-llm-repair.md) | 20 | 7,583 | 0 | 3 | 5 | 3 |
| [fnm-orchestrator](fnm-orchestrator.md) | 15 | 3,407 | 4 | 7 | 8 | 0 |
| [fnm-py](fnm-py.md) | 3 | 1,458 | 3 | 3 | 5 | 5 |
| **合计** | **287** | **73,258** | **19** | **45** | **80** | **59** |

## 全局 P0 问题汇总（需优先修复）

### 1. 运算符优先级 bug（3 处）
- `fnm-phase4/text/markdown_parse.rs:911` — `&&` / `||` 优先级导致 `result[0]` 越界 panic
- `fnm-py/lib.rs:787` — 同类问题，当前恰好因短路正确但重构时必 panic
- `fnm-py/translate.rs:113,30` — 参数解析后丢弃（API 合同破损）

### 2. 数据库事务缺失（1 处，影响 Phase1-6 全部写入）
- `fnm-core/db/repository.rs:270-387` — 多表 DELETE+INSERT 无事务包裹，中途失败导致数据不一致

### 3. 类型截断（2 处）
- `fnm-core/vision/pdfium.rs:37,73,103` — `page_index as u16` 负值/大值访问错误页面
- `fnm-phase1/chapter_skeleton/pdf_font.rs:65` — 同类问题

### 4. UTF-8 字节/字符混用（4 处）
- `fnm-orchestrator/jobs.rs:184-198` — trim/tail_context 字节长度比较 + 字符截断混用
- `fnm-phase1/toc_structure.rs:303` — 字节切片多字节字符 panic
- `fnm-phase3/endnote_links.rs:434-436` — Unicode 上标 byte_end 越界

### 5. 逻辑错误
- `fnm-orchestrator/retry.rs:27` — visible_idx 递增逻辑与类型化版本不一致
- `fnm-orchestrator/load.rs:126` — note_links/effective_note_links 语义混淆
- `fnm-phase2/boundary_fallback.rs:407` — 空数组无守卫
- `fnm-phase2/chapter_split/mod.rs:216` — 序列化失败静默返回 Null
- `fnm-phase2/endnote_project.rs:89` — 哨兵值 1000000 代替 Option
- `fnm-phase6/file_audit/mod.rs:320` — chars().rev() 产出倒序字符串
- `fnm-phase1/pdf_font_band.rs:256,263` — partial_cmp().unwrap() 遇 NaN panic

## 跨 crate 共性问题

### 1. `serde_json::Value` 弱类型滥用
出现在 fnm-llm-repair、fnm-orchestrator/page_translate、fnm-phase3/note_linking、fnm-phase4/ref_freeze、fnm-core/segment_codec 等模块。大量 `.get("key").and_then(|v| v.as_str())` 样板代码，字段名拼写错误无法编译期捕获。

**建议**：为高频使用的中间数据定义类型化 struct，至少为最常用字段提供 accessor helper。

### 2. 代码重复
- `extract_json_block` 在 fnm-phase2 和 fnm-llm-repair 共 3 份
- `WHITESPACE_RE` 在多个 crate 各自定义
- `extract_context` 在 fnm-phase3 两处
- `safe_int` 在 fnm-phase5 两处
- `synthetic_markdown_pages` 在 fnm-phase4 两处
- page_numbers 提取逻辑在 fnm-phase5 三处

**建议**：公共函数/正则提取到 fnm-core 或各 crate 的公共模块。

### 3. `eprintln!` 代替结构化日志
全部 crate 都依赖 `tracing`，但至少 6 处仍使用 `eprintln!`。

### 4. 死代码 / 未使用参数
多个 crate 存在 `_` 前缀参数（从未实现）、`#[allow(dead_code)]` 标注的结构体/函数、计算后赋给 `_` 变量的无效计算。

### 5. 正则每次调用重编译
fnm-phase4/text 和 segments 模块多处 `Regex::new().unwrap()` 未用 `Lazy`。

## 全局亮点

1. **零编译 warning / 零 clippy lint**（大部分 crate）
2. **`#![deny(unused_must_use)]`** 在 fnm-core、fnm-phase4、fnm-orchestrator 开启
3. **Python 对齐注释全覆盖**：函数级 `←→ Python ... (file:line)` 标注
4. **铁律约束注释**：Phase3 关键位置标注遵循哪条铁律
5. **程序合同 gate_report**：Phase1 结构化验证输出质量
6. **无 unsafe、无 todo!/unimplemented!**（绝大部分 crate）
7. **测试覆盖**：parity 测试（Python golden fixture 对齐）、spec 测试（行为不变量）、合同测试（Phase6 只读保证）
8. **`enum_with_str!` 宏**：一个宏为 12 个 enum 消除手动 boilerplate

## 修复优先级建议

1. **立即修复**（P0，共 19 项）：大部分是 1-5 行改动（加括号、加守卫、改类型转换）
2. **短期修复**（P1，共 45 项）：unwrap 改 expect、死分支清理、性能热点
3. **中期清理**（P2，共 80 项）：代码去重、弱类型替换为 struct、超长函数拆分
4. **长期改进**（P3，共 59 项）：风格统一、测试补充、模型配置外部化
