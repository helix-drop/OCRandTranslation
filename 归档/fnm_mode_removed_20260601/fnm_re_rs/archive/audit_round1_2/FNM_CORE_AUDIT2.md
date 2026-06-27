# FNM-CORE 审计报告（独立第二轮）

> 审计范围：`fnm-core` crate 全部 30 个 `.rs` 文件（约 10,170 行）。
> 审计维度：**程序逻辑正确性、Rust 代码风格、过度防御/偷懒/AI 常见病**。业务逻辑（书型识别规则等）不在范围内。
> 方法：逐文件静态精读 + `cargo clippy` 客观佐证。审计期间未参考现有 `audit/` 结论。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

---

## 0. 总体印象

fnm-core 是基础设施层，整体**质量偏高**：
- 用 `enum_with_str!` 宏把 Python `Literal` 翻译为强类型 enum（[types.rs](fnm-core/src/types.rs)），下游避免字符串字面量拼写错误；
- `parse_required_json` 对 NULL **fail-fast 不猜测**（[db/repository.rs:24](fnm-core/src/db/repository.rs)），符合 CLAUDE.md「不猜测事实值」；
- `db/schema.rs` 补列时旧行保持 NULL、读回明确失败而非伪造默认；
- `vision/pdfium.rs` 全局 `Mutex<Pdfium>` 有清晰注释说明是「资源管理例外」；
- 测试覆盖普遍充分（repository 有 30+ 测试，覆盖 schema 兼容、脏 JSON、BLOB 错误传播）。

但存在 **3 个数据正确性级别的问题**（外键约束失效、批量替换无事务、review_id 合成碰撞）和一批重复/不一致/防御冗余。下面按严重度列出。

---

## 1. 🔴 高优先级（数据正确性 / 原子性）

### C-1　连接池 `foreign_keys` 只对单个连接生效，外键约束实质失效
- **位置**：[db/pool.rs:20-24](fnm-core/src/db/pool.rs)
- **类别**：程序逻辑 bug
- **现象**：
  ```rust
  let conn = pool.get()?;
  conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
  schema::run_migrations(&conn)?;
  ```
  `PRAGMA foreign_keys` 是 **per-connection** 设置，不持久化到数据库。这里只在「迁移用的那一个连接」上开启；该连接归还池后，池中后续新建的连接（`max_size(4)`，最多 4 条）默认 `foreign_keys=OFF`。`PRAGMA journal_mode=WAL` 是数据库级、持久，设一次没问题——但 FK 不是。
- **后果**：schema（migration 0001）为 `fnm_*` 表定义了对 `documents` 的外键（`upsert_document` 注释也确认「满足 fnm_* 表的外键约束」），但运行期绝大多数连接**不强制外键**，可写入孤儿行（`doc_id` 不存在于 `documents`），约束形同虚设。
- **建议**：在 manager 上挂 init hook，让**每个**连接执行：
  ```rust
  let manager = SqliteConnectionManager::file(db_path)
      .with_init(|c| c.execute_batch("PRAGMA foreign_keys=ON;"));
  ```
  WAL 可保留在迁移连接里设一次。

### C-2　所有 `replace_*` 批量替换缺事务，失败留下半损坏状态
- **位置**：[db/repository.rs](fnm-core/src/db/repository.rs) `write_phase1_tables`(259)、`replace_fnm_phase2_products`(606)、`replace_fnm_phase3_products`(786)、`replace_fnm_translation_units`(1145)、`replace_fnm_structure_reviews`(1239)、`replace_fnm_phase5_products`(1360)、`replace_fnm_phase6_products`(1493)
- **类别**：程序逻辑 bug（原子性）+ 性能
- **现象**：这些函数模式一致——先 `DELETE FROM ... WHERE doc_id=?` 删多张表，再循环 `INSERT`，**全程无事务**。若中途某条 INSERT 失败（约束/IO），旧数据已删、新数据只写了一部分，DB 处于不一致状态。
- **反证**：同文件 `batch_save_fnm_review_overrides_v2`(961) **正确**用了 `conn.transaction()` —— 说明作者知道事务，但在更关键的全量替换路径系统性遗漏。
- **附带**：无事务时 SQLite 每条 INSERT 各自 autocommit/落盘，批量写入性能差。
- **建议**：每个 `replace_*` 用 `let tx = conn.transaction()?; ... tx.commit()?;` 包裹 DELETE+INSERT。

### C-3　`structure_reviews` 的 `review_id` 不持久化、读回合成且会碰撞
- **位置**：[db/repository.rs:1208-1234](fnm-core/src/db/repository.rs)（读）vs `replace_fnm_structure_reviews`:1250（写不含 review_id 列）
- **类别**：程序逻辑 bug
- **现象**：写入时丢弃 `review_id`；读回时用 `format!("review-{type}-{chapter}-{page_start}-{page_end}-na")` 合成，**末尾写死 `"na"`**。两条 `(review_type, chapter_id, page_start, page_end)` 相同的 review 会得到**完全相同的 review_id**。
- **后果**：下游若按 review_id 去重/索引，会丢条目或互相覆盖。
- **建议**：要么持久化 review_id 列，要么在合成键里纳入能区分同坐标多条 review 的字段（如 ordinal / 内容 hash），去掉占位 `"na"`。

---

## 2. 🟠 中优先级（逻辑/不一致/重复）

### C-4　`local_endnote_ref_number` 的 while 循环是不可达的死代码
- **位置**：[ref_rewriter.rs:176-179](fnm-core/src/ref_rewriter.rs)
  ```rust
  let mut next_num = local_ref_numbers.values().max().copied().unwrap_or(0) + 1;
  while local_ref_numbers.values().any(|&v| v == next_num) { next_num += 1; }
  ```
- **类别**：过度防御 / 死代码
- **分析**：`next_num = max + 1` 已严格大于所有现存 value，`while any(v == next_num)` 恒为 false，循环体永不执行。这是从 Python 逐行移植带来的冗余守卫（Python 版可能有不同前置）。
- **建议**：删除 while，直接 `let next_num = max + 1;`。

### C-5　DB enum 读回的容错策略不一致
- **位置**：[db/repository.rs](fnm-core/src/db/repository.rs) —— `note_kind`/`page_role`/`source`/`boundary_state`/`status`/`resolver` 用 `.unwrap_or(默认)` 静默兜底（如 405、432-439、533、767-777）；而 `region_scope`/`region_source` 用 `.map_err(|e| invalid_db_value(...))?` **fail-fast**（522-525）。
- **类别**：逻辑不一致
- **分析**：silent fallback 是**有意行为**（被测试 `invalid_note_kind_reads_back_as_unknown`:2134 覆盖），但同为 DB enum 读回，scope/source 严格、其余宽松，且无注释解释差异；这也与 `schema.rs` 的「缺列 fail-fast」哲学相悖。容错与严格混用，读者难判断哪种是契约。
- **建议**：统一策略并加注释——要么都 fail-fast（推荐，配合 C-1/C-2 的数据完整性），要么都容错并记录降级日志。

### C-6　`page_index as u16` 窄化截断
- **位置**：[vision/pdfium.rs:37、72、103](fnm-core/src/vision/pdfium.rs)
- **类别**：程序逻辑（不安全转换）
- **分析**：`page.get(page_index as u16)`，`i64 -> u16` 直接 `as` 会回绕（-1→65535，70000→4464）。负页码不会报「页不存在」而是变成大正数。
- **建议**：`u16::try_from(page_index).map_err(...)`，越界返回明确错误。

### C-7　`render_page_to_base64_png` 的 `_dpi` 参数被忽略
- **位置**：[vision/pdfium.rs:64-77](fnm-core/src/vision/pdfium.rs)
- **类别**：偷懒 / 误导性 API
- **分析**：函数签名收 `_dpi: u32`，但函数体硬编码 `set_target_width(2000)`，dpi 完全不参与渲染。调用方以为能控制分辨率，实际无效。
- **建议**：要么用 dpi 计算 target_width，要么删除该参数。

### C-8　`segment_codec.rs::deserialize_paragraph` 的 `has_*` 分支全部冗余
- **位置**：[segment_codec.rs:316-481](fnm-core/src/segment_codec.rs)
- **类别**：AI 冗余代码（~150 行可压缩到 ~40 行）
- **分析**：11 个字段每个都写
  ```rust
  let has_o = obj.contains_key("o") || obj.contains_key("order");
  ... if has_o { obj.get("o").or(obj.get("order")).cloned().unwrap_or(DEFAULT) } else { DEFAULT }
  ```
  `if has_o { ... unwrap_or(DEFAULT) } else { DEFAULT }` 的两个分支结果**完全等价**（key 不存在时 `get().or().unwrap_or(DEFAULT)` 本就返回 DEFAULT）。所有 `has_*` 变量与 if/else 都是无效防御。
- **建议**：直接 `obj.get("short").or(obj.get("long")).cloned().unwrap_or(DEFAULT)`，删除全部 `has_*`。

### C-9　`ref_rewriter.rs` 四个 `replace_raw_*_refs_*` 高度重复
- **位置**：[ref_rewriter.rs](fnm-core/src/ref_rewriter.rs) `replace_note_refs_with_local_labels`(187)、`replace_raw_bracket_refs_*`(237)、`replace_raw_superscript_refs_*`(289)、`replace_raw_unicode_superscript_refs_*`(335)
- **类别**：复制粘贴
- **分析**：4 个函数尾部 `match ref_num { Some(n) => format!("[^{}]", n), None => { footnote_ids_seen push; "*" } }` 块逐字相同。
- **建议**：抽 `fn emit_local_label(ref_num, note_id, footnote_ids_seen) -> String`。

### C-10　`token_counter.rs::get_usage_summary` metric 累加重复 3 次
- **位置**：[token_counter.rs:82-129](fnm-core/src/token_counter.rs)
- **类别**：复制粘贴
- **分析**：stage / model / total 三段各有一份相同的 `match *key { "request_count" => c.request_count, ... }` + `or_insert_with(HashMap::from([4个0]))`。
- **建议**：抽 `fn add_metrics(entry: &mut HashMap<String,i64>, rec: &UsageRecord)`，三处复用。

### C-11　`records.rs` 6 个 PhaseNSummary / PhaseNStructure 字段大量平铺重复
- **位置**：[records.rs](fnm-core/src/records.rs) `Phase1Summary`(183)…`Phase6Summary`(1452)、`Phase1Structure`(250)…`Phase6Structure`(1521)
- **类别**：结构重复 / 可维护性
- **分析**：16+ 个公共字段（`page_partition_summary`、`heading_review_summary`…`toc_semantic_blocking_reasons`）在 6 个 Summary 间逐字重复；Structure 同理。新增一个公共字段需改 6 处，易漏。
- **建议**：抽 `BaseSummary` / `BaseStructure` 子结构，用 `#[serde(flatten)]` 嵌入以保持 JSON 平铺兼容。

### C-12　`refs.rs` / 多处 `find` 后再 `captures` 重复正则匹配
- **位置**：[refs.rs:59-69](fnm-core/src/refs.rs)（`cleanup_nested_note_refs` 的 SPLIT 分支 `find` 后又 `captures` 两次）、[refs.rs:226-250](fnm-core/src/refs.rs)（`extract_note_refs` 先 `find_iter` 再对每个 match `pattern.captures(m.as_str())`）
- **类别**：效率 / 风格
- **分析**：同一文本上重复跑同一正则。`extract_note_refs` 还用 `pattern.as_str().contains("\\[\\^")`（用正则源码字符串做控制流判断，脆弱）。
- **建议**：改用一次 `captures` / `captures_iter`；用结构化标志替代「正则源码字符串包含」判断。

---

## 3. 🟡 低优先级（风格 / 偷懒 / nit）

### C-13　`note_modes.rs` 放弃了 types.rs 的 NoteMode enum，用 `&str` + `_ =>` 吞底
- [note_modes.rs:8-16,44-47](fnm-core/src/note_modes.rs)：`to_db_alias(&str)`/`increment_chapter_mode_summary(&str)` 接受字符串，`_ => "mixed_or_unclear"` 吞掉一切未知。若误传 alias（非 canonical）会被统计进 `mixed_or_unclear`。与 types.rs 的强类型努力矛盾。建议改用 `NoteMode` 入参。

### C-14　`config.rs::load_config` 静默吞掉配置解析错误
- [config.rs:140-147](fnm-core/src/config.rs)：`read_to_string().ok().and_then(parse.ok()).unwrap_or_default()`。config.json 存在但 JSON 损坏时，用户全部 API key 静默丢失且无任何日志。crate 已依赖 `tracing` 却未使用。建议解析失败时 `tracing::warn!`。

### C-15　全 crate 错误日志方式不统一
- config.rs 静默、[repository.rs:1651](fnm-core/src/db/repository.rs) 用 `eprintln!("[WARNING]…")`、[token_counter.rs:61](fnm-core/src/token_counter.rs) 塞 `_error` JSON 字段、[pdfium.rs:23](fnm-core/src/vision/pdfium.rs) 用 `expect` panic。建议统一到 `tracing`。

### C-16　测试相关
- [config.rs:286-292](fnm-core/src/config.rs) `default_pool_has_4_slots_with_builtin_at_zero` 测试名承诺验证「4 槽 + builtin 在 0」，实际只 `assert!(!pool.is_empty())`，名不副实。
- [types.rs:207-242](fnm-core/src/types.rs) `all_enums_roundtrip` / `all_enums_have_all_const` 覆盖 11 个 enum 但**漏了 BookType**。
- [token_counter.rs:195-262](fnm-core/src/token_counter.rs) 因全局 `USAGE_RECORDS: Mutex<Vec>` 单例，并行测试互相污染，只能用 `>=` 弹性断言绕过。根因是全局可变状态。

### C-17　其他 nit
- [note_marker.rs:150](fnm-core/src/note_marker.rs) `short_digits.chars().nth(cursor)` 在循环里 O(n²)（marker 短，无实质影响）；可改字节索引。
- [chapters.rs:35-66](fnm-core/src/chapters.rs) `chapter_id_for_page` 第三级兜底与 `nearest_prior_chapter` 逐字重复，前者可直接调后者。
- [db/schema.rs:9](fnm-core/src/db/schema.rs) migration 写入 `schema_version='25'` 但 `run_migrations` 从不读取，版本机制空置（每次 open 全量重跑——幸而全部 `IF NOT EXISTS`/`INSERT OR IGNORE` 幂等）。
- [records.rs:25-26](fnm-core/src/records.rs) 文件头注释自称「1361 行」，实际 1657 行，注释已过时。
- [model_capabilities.rs:50-82](fnm-core/src/model_capabilities.rs) `chat_model` 相邻 bool 位置参数 `selectable, thinking` 易传反（`vision_model` 已用 `VisionModelParams` struct，不一致）；`thinking_request_format` 计算在 chat_model/vision_model 重复。
- [db/repository.rs:1138-1142](fnm-core/src/db/repository.rs) list 实现风格混用（`collect::<Result<Vec<_>,_>>` vs 手写 `for row in rows { push(row?) }`）。
- [db/repository.rs:1695-1706](fnm-core/src/db/repository.rs) `load_toc_items_for_doc` 变量名 `_user/_visual/_pdf` 带下划线前缀（通常表示 unused）但实际使用，命名误导。
- [vision/spec.rs:156-160](fnm-core/src/vision/spec.rs) `resolve_builtin_model_spec` 多余 `model.clone()`（`m_ref`），可省。
- 测试用 `SqliteConnectionManager::memory()` + r2d2 池依赖「连接复用」才能共享 schema（每个 `:memory:` 连接本是独立 db），单线程顺序 get 才碰巧成立——脆弱但非生产路径。

---

## 4. clippy 结果

强制 `touch` 全源码后 `cargo clippy --workspace --all-targets` 运行中（后台），完成后并入总览对照。源码中 `#[allow(...)]` 抑制初步 grep 命中 56 处（全 workspace），将在总览核实是否集中于测试或存在掩盖告警。

> 注：`grep "unsafe "` 初步命中 2190 次系误匹配（注释/字符串/`// SAFETY` 等），fnm-core 实际无 `unsafe` 块（仅 pdfium 经 FFI 但封装在 crate 内）。

---

## 5. 文件覆盖确认（30/30）

lib.rs｜types.rs｜config.rs｜anchor_kind.rs｜note_marker.rs｜note_modes.rs｜marker_seq.rs｜refs.rs｜ref_rewriter.rs｜chapters.rs｜note_lookup.rs｜text.rs｜title.rs｜review.rs｜review_overrides.rs｜export_constants.rs｜token_counter.rs｜segments.rs｜segment_codec.rs｜records.rs｜model_capabilities.rs｜db/mod.rs｜db/pool.rs｜db/schema.rs｜db/repository.rs｜vision/mod.rs｜vision/http.rs｜vision/pdfium.rs｜vision/spec.rs｜testing/mod.rs（1 行占位）

**核心结论**：fnm-core 基础扎实，但 DB 层（pool/repository）的 **C-1 外键失效、C-2 替换无事务、C-3 review_id 碰撞** 是应优先修复的真问题；其余以重复代码与防御冗余为主，可在重构中收敛。
