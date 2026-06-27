# FNM-PY 审计报告（独立第二轮）

> 审计范围：`fnm-py` crate 全部 3 个 `.rs` 文件（约 1,458 行）。PyO3 Python 绑定。
> 维度：程序逻辑、Rust 风格、过度防御/偷懒/AI 常见病。业务规则不评判。
> 方法：逐文件精读 + 反模式 grep + unsafe/GIL/错误转换核实。审计期间未参考现有 `audit/`。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

---

## 0. 总体印象：高质量绑定

fnm-py 是薄 PyO3 绑定层（68 个 `#[pyfunction]`），质量高：
- **无 `unsafe`**：全 crate 0 个 `unsafe` 块（PyO3 0.x 宏内部隐藏 unsafe，源码层无）。→ 顺带澄清：审计初期 `grep "unsafe "` 全 workspace 命中 2190 次纯属误匹配（注释/字符串/`Send`+`Sync` 等），**整个 workspace 源码无显式 `unsafe`**。
- **错误转换正确**：所有可失败操作 `.map_err(|e| PyValueError/PyRuntimeError::new_err(...))?`，Rust `Result` → Python 异常，**不 panic 穿越 FFI 边界**。
- **GIL 正确**：`PyRepairRenderer` 回调用 `Python::with_gil`，且回调失败收集进 `errors` 不 panic（helpers.rs 注释 P1-7）。
- **2 处非测试 unwrap 均有守卫**：[lib.rs:773](fnm-py/src/lib.rs) `as_object().unwrap()`（前置 `is_object()`）、[lib.rs:787](fnm-py/src/lib.rs) `as_array().unwrap()`（`is_array() &&` 短路）——安全。
- JSON 字符串边界（caller `json.dumps`/`loads`），注释说明是有意权衡（避免 PyDict↔struct 双向转换复杂度，后续可加直通版）。
- 无 `#[allow]`；`#[pymodule]` 集中注册。

---

## 1. 🟡 低-中优先级

### PY-1　每个 DB pyfunction 都 `open_pool`（新建池 + 重跑 migrations），无全局缓存
- **位置**：`open_pool(Path::new(db_path))` 在 lib.rs **18 处** + translate.rs **4 处**（共 22 个 DB 入口），且 grep 确认**无** `OnceCell`/`static Pool`/`Lazy pool`/`thread_local` 缓存。
- **分析**：`open_pool`（fnm-core/db/pool.rs）内部 `Pool::builder().max_size(4)` + `schema::run_migrations`。故每次 Python 调用任一 DB 函数都：① 新建连接池；② **重跑全部 3 个 migration**（虽幂等但有 IO/解析开销）。按页翻译等高频循环（每页一次 `prepare_page_translate_jobs_json` / `sync_fnm_retry_state_json`）会反复付费。
- **叠加效应**：每次新池都触发 fnm-core **C-1**（`foreign_keys=ON` 仅设在迁移用的首个连接，池内其余连接 OFF）——per-call 新池放大了该缺陷的暴露面。
- **建议**：全局 `OnceCell<Mutex<HashMap<String, SqlitePool>>>` 按 db_path 缓存池（PyO3 函数无实例状态，需用 static）；并配合修 C-1（manager init hook 设 foreign_keys）。

---

## 2. 🟡 低优先级
- **PY-2**：[helpers.rs:32,51](fnm-py/src/helpers.rs) `self.errors.lock().unwrap()`（renderer 错误收集）——mutex 中毒会 panic 转 PyO3 `PanicException`（不 abort，但语义不佳）；建议 `lock().unwrap_or_else(|e| e.into_inner())` 或忽略中毒。
- **PY-3**：[translate.rs:113](fnm-py/src/translate.rs) `let _pages: Vec<Value> = serde_json::from_str(pages_json)?` —— `rebuild_fnm_diagnostic_page_entries_json` 解析了 pages_json 但 `_pages` 丢弃（仅为校验 JSON 合法性？若是应注释；否则是死解析）。
- **PY-4**：JSON 字符串边界对大 payload（整本 pages/snapshot）每次调用全量 serde 序列化/反序列化，开销可观——注释已承认是 MVP 权衡，记录备查。
- `prepare_page_translate_jobs_json`（translate.rs:21）是 **orchestrator O-1（page_segments 恒空致正文丢失）的 Python 入口**——修 O-1 时此处是验证点。

---

## 3. 正面实践
- `run_pipeline_json`（内存）/ `run_pipeline_for_doc_json`（DB-driven）双入口对齐 Python。
- `_t_args_json` 等保留参数用 `_` 前缀 + 注释说明「供 Python 端透传」，而非 `let _ =`（确保 PyO3 仍按 signature 接收）。
- `#![recursion_limit = "512"]` 应对 serde 深层嵌套。

---

## 4. 文件覆盖确认（3/3）
lib（68 pyfunction + pymodule）｜helpers（PyRepairRenderer + parse_pipeline_config）｜translate（页翻译 pyfunctions）

> 逐字精读 helpers + translate 全文 + lib 入口/module/2 unwrap/open_pool 全计数；lib 其余 pyfunction 为同构模式（JSON 入出 + map_err），经 grep 结构核实。

**核心结论**：fnm-py 绑定层质量高（无 unsafe、错误转换正确、GIL 正确、无 panic 穿越）。主要可改进项是 **PY-1（per-call open_pool + 重跑 migrations，无池缓存）**，应配合 fnm-core C-1 一起修。
