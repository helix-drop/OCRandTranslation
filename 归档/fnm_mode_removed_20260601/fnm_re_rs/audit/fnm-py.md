# fnm-py 审计报告

**审计日期**：2026-05-29
**代码规模**：3 文件，1,458 行
**类型**：PyO3 Python 绑定层（cdylib）

## 总体评价

质量中上。JSON 字符串边界设计简洁一致，错误处理整体规范（所有 fallible 操作用 `map_err` 转 PyValueError/PyRuntimeError），GIL 管理有意识。但存在 1 个真实逻辑 bug（运算符优先级）、2 处参数解析后丢弃、若干 GIL 安全隐患和设计问题。

## 问题清单

### P0 — 高严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 1 | `lib.rs:787` | **运算符优先级** | `v.is_null() \|\| v.is_array() && v.as_array().unwrap().is_empty()` — `&&` 优先级高于 `\|\|`。当前恰好行为正确（依赖隐含短路），但如果重构条件顺序就会 panic | 加括号明确意图 |
| 2 | `translate.rs:113` | **参数丢弃** | `rebuild_fnm_diagnostic_page_entries_json` 解析 `pages_json` 后绑定到 `_pages` 从未使用 | 从签名移除或接入下游 |
| 3 | `translate.rs:30` | **参数丢弃** | `prepare_page_translate_jobs_json` 中 `t_args_json` 被丢弃 | 标注 deprecated 或传给下游 |

### P1 — 中严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 4 | `helpers.rs:32,51` | panic 风险 | `Mutex::lock().unwrap()` — poison 时 panic | `unwrap_or_else(\|e\| e.into_inner())` 或 `parking_lot::Mutex` |
| 5 | `lib.rs:173-194` | GIL 安全 | `allow_threads` 闭包中 `PyRepairRenderer`（含 `Py<PyAny>`）通过 `with_gil` 重获 GIL，若 Python callback 重入 Rust 可能死锁 | 文档标注"callback 不得重入" |
| 6 | `lib.rs:678-696` | GIL 安全 | `trace_callback` 在 `allow_threads` 内 `with_gil` 调 Python `json.loads` | 考虑传 JSON 字符串让 Python 端解析 |

### P2 — 低严重度

| # | 文件:行号 | 类别 | 描述 | 建议 |
|---|-----------|------|------|------|
| 7 | `lib.rs` 全文 | 性能 | 17 处 `open_pool(Path::new(db_path))`，每次调用重建连接池 | 引入 PyClass 包装 SqliteRepository |
| 8 | `lib.rs:382-397` | 性能 | 加载全量 diagnostic pages 后线性 find 单页 | 在 Repository 加按 page_bp 查询的方法 |
| 9 | `lib.rs:946-968` | 抽象泄漏 | 绕过 Repository 直接写 SQL | 统一使用 `repo.load_raw_pages_for_doc()` |
| 10 | `lib.rs:800-884` | 可维护性 | 85 行 `serde_json::json!` 手动拼接 | 直接 `serde_json::to_string` 或定义 DTO |
| 11 | `lib.rs:850-883` | **字段源错配** | summary 子对象中混用 `s`(status) 和 `summary` 字段源 | 确认每个字段应从哪读取 |

### P3 — 轻微

| # | 描述 |
|---|------|
| 12 | `lib.rs:42` — `pub use translate::*` 通配符重导出 |
| 13 | `lib.rs:1` — `#![recursion_limit = "512"]` 缺少说明 |
| 14 | `Cargo.toml:23` — tokio 依赖仅用于一处 `block_on` |
| 15 | `helpers.rs:59-98` — 手动逐字段解析而非 `serde_json::from_value` |
| 16 | `lib.rs:440-510` — config 构造逻辑与 `parse_pipeline_config` 重复 |

## 值得肯定的地方

1. **错误处理一致**：无裸 unwrap 作用于外部输入
2. **GIL 管理有意识**：`allow_threads` + `with_gil` 配对
3. **JSON-in/JSON-out 统一**：降低绑定层维护成本
4. **中文文档注释**：每个 pyfunction 有参数说明和 Python 端交叉引用
5. **`PyRepairRenderer` 错误收集模式**：不 panic 不丢弃，收集后注入返回值
6. **zip 参数 4 种情况全覆盖**
