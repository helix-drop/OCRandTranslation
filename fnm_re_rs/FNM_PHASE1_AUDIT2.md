# FNM-PHASE1 审计报告（独立第二轮）

> 审计范围：`fnm-phase1` crate 全部 56 个 `.rs` 文件（约 11,946 行）。
> 维度：程序逻辑正确性、Rust 风格、过度防御/偷懒/AI 常见病。业务规则（书型/章节判定阈值）不评判。
> 方法：逐文件静态精读 + clippy 佐证。审计期间未参考现有 `audit/`。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

---

## 0. 总体印象

phase1 是页面角色 + 章节骨架构建层，是 10 个 crate 中**最大**的（56 文件）。算法实现（heading_graph 三轮锚点解析、toc_semantics 五遍 sanitize、fallback 章节分类评分）**质量较高、注释充分**，并诚实标注了语言 bias 与经验阈值的局限（CLAUDE.md §7/§10）。

但 phase1 集中暴露了本代码库（Python→Rust 移植）的几类**系统性 AI 代码病**：
1. **「构建后丢弃返回值」死代码**（≥4 处 `let _x = expensive_fn()`）；
2. **整个子系统未接入主流程**（book_note_type + llm_book_type_verify 约 1660 行）；
3. **`_` 前缀掩盖**——未用参数、死 regex、未读字段，靠 `_`/`#[allow(dead_code)]`/`pub` 逃过 clippy；
4. **重复 helper**（同名函数多份不同实现）；
5. **一处真实 panic 风险**（字节切片 multi-byte 标题）。

clippy（强制 `touch` 全源码后 `--all-targets`）**0 warning**——代码确实清理过，但 clippy clean 掩盖了上述靠可见性规则规避的死代码。

---

## 1. 🔴 高优先级

### P1-1　`&tk[..tk.len().min(20)]` 字节切片，法语标题会 panic
- **位置**：[toc_structure.rs:303](fnm-phase1/src/toc_structure.rs)
  ```rust
  chapter_id: format!("toc-ch-{:03}-{}", filtered_chapters.len() + 1, &tk[..tk.len().min(20)]),
  ```
- **类别**：程序逻辑 bug（panic）
- **分析**：`tk = chapter_title_match_key(&node.title)`。`chapter_title_match_key`（fnm-core/title.rs）用 `TITLE_KEY_CLEAN_RE = [^0-9a-zà-ÿ]+` 清理，**保留 `à-ÿ`**（这些是 2 字节 UTF-8），不做 NFKD 去重音。当 `tk` 的第 20 个字节落在某个 `é`/`à` 中间时，`&tk[..20]` 触发 `byte index is not a char boundary` panic。法语书（项目主力 fixture）的标题 key 极易命中。
- **反证**：同一 crate 的 [title_utils.rs:283](fnm-phase1/src/chapter_skeleton/toc_semantics/title_utils.rs) `normalize_toc_chapter_id` 对等价操作用了 `title_key.chars().take(24).collect()`（char 安全）——说明作者知道正确写法，此处是疏漏。
- **修复**：`tk.chars().take(20).collect::<String>()`。

---

## 2. 🟠 中优先级

### P1-2　`has_number_prefix` 只识别「恰好两位数字」章节号
- **位置**：[toc_tree.rs:247-248](fnm-phase1/src/toc_tree.rs)
  ```rust
  let has_number_prefix = nl.chars().take(2).all(|c| c.is_ascii_digit()) && nl.chars().nth(2) == Some('.');
  ```
- **分析**：`take(2).all(is_digit) && nth(2)=='.'` 要求前两字符都是数字且第三字符是 `.`。`"1."`（前两字符 `1`/`.`，`.` 非数字→false）、`"123."`（nth(2)=`3`≠`.`→false）都漏判，只有 `"12."` 这种恰好两位数才命中。应为 `\d+\.` 语义。有 `has_chapter_kw`/`page_changed` 兜底，但该判定本身有缺陷。

### P1-3　PDF 字体排序 `partial_cmp().unwrap()` 的 NaN panic 风险
- **位置**：[pdf_font_band.rs:256,262-266](fnm-phase1/src/chapter_skeleton/heading_candidates/pdf_font_band.rs)
  ```rust
  top_sorted.sort_by(|a, b| rank_item(a, true).partial_cmp(&rank_item(b, true)).unwrap());
  ```
- **分析**：`rank_item` 的分值由 `safe_float` 提取的 x/y/w/h 参与计算，而 `safe_float` 对字符串 `"NaN"` 返回 `Some(f64::NaN)`（`"NaN".parse::<f64>()` 成功）。任一分值为 NaN 时 `partial_cmp` 返回 `None`，`.unwrap()` panic。fnm-core/text.rs 的同类 sort 用 `.unwrap_or(Ordering::Equal)` 处理了——此处不一致。
- **修复**：`.unwrap_or(std::cmp::Ordering::Equal)`。

### P1-4　`idx as u16` 窄化截断（PDF 页索引）
- **位置**：[pdf_font.rs:65](fnm-phase1/src/chapter_skeleton/pdf_font.rs)（与 fnm-core C-6 同类）
- `pages.get(idx as u16)`：i64→u16 回绕。建议 `u16::try_from`。

### P1-5　`is_body_entry_page` 的 headings 条件不影响结果
- **位置**：[role_heuristics/mod.rs:80-83](fnm-phase1/src/page_partition/role_heuristics/mod.rs)
  ```rust
  if !headings.is_empty() && looks_like_prose_after_heading(text) { return true; }
  looks_like_prose_after_heading(text)
  ```
- **分析**：无论 `headings` 空与否，最终返回值都等于 `looks_like_prose_after_heading(text)`。`!headings.is_empty()` 这个守卫是**无效逻辑**，整个 if 块可删。

### P1-6　「构建后丢弃返回值」死代码（≥4 处）
- [page_partition/mod.rs:153](fnm-phase1/src/page_partition/mod.rs) `let _synthetic = build_synthetic_page_by_no(&page_info_cache);` —— 整个 `build_synthetic_page_by_no`（~40 行，构造 HashMap）白算后丢弃。
- [section_heads.rs:75](fnm-phase1/src/section_heads.rs) `let _chapter_title_key_map = chapter_title_keys(...);` —— 构建后从不使用。
- [toc_semantics/mod.rs:171](fnm-phase1/src/chapter_skeleton/toc_semantics/mod.rs) `let _missing: Vec<String> = ...` 丢弃。
- [toc_semantics/mod.rs:480](fnm-phase1/src/chapter_skeleton/toc_semantics/mod.rs) `let _page_row_by_no: HashMap = ...` 丢弃。
- **性质**：Python→Rust 移植时保留了中间变量但未接下游消费。clippy 不报（绑定到 `_`/`_name` 抑制 unused）。应删除或接回。

### P1-7　两个完整子系统未接入主入口（~1660 行）
- `book_note_type/`（467 行）+ `llm_book_type_verify/`（1196 行）当前都**不在 `build_phase1_structure` 主路径调用**：[toc_structure.rs:99-104](fnm-phase1/src/toc_structure.rs) 对 `skip_llm_verify=false` 直接 `bail!`（默认 true 跳过），[toc_structure.rs:161-165](fnm-phase1/src/toc_structure.rs) 注释说明 `build_book_note_profile` 故意不调（避免与 phase2 重复 note_mode 决策）。
- **评价**：架构意图清晰（注释诚实），但事实是 ~1660 行仅测试覆盖、不走生产。属「为未来保留的未完成功能」，应在路线图明确状态，避免被当作活代码维护。

### P1-8　重复 helper：`build_chapter_by_page` / `looks_like_*` / `candidate_*_score`
- `build_chapter_by_page`（pages+range 填充）在 [page_roles.rs:23-42](fnm-phase1/src/page_roles.rs) 与 [book_note_type/mod.rs:40-60](fnm-phase1/src/book_note_type/mod.rs) 各一份；`chapter_by_page` 在 [selection.rs:56](fnm-phase1/src/llm_book_type_verify/selection.rs) 第三份。
- [page_resolve.rs:99-141](fnm-phase1/src/chapter_skeleton/toc_semantics/page_resolve.rs) 重新实现了 `looks_like_copyright_front_matter_page`/`looks_like_course_listing_page`/`looks_like_title_page`/`looks_like_prose_after_heading`，是 [role_heuristics/](fnm-phase1/src/page_partition/role_heuristics/) 已有函数的**简化且不一致**版本（前者纯 `contains`，后者用 regex+行数统计）——同名不同行为，易误用。
- `candidate_source_score`/`candidate_family_score` 在 [row_collect.rs:272](fnm-phase1/src/chapter_skeleton/toc_semantics/row_collect.rs) 与 [heading_graph/scoring.rs:6](fnm-phase1/src/heading_graph/scoring.rs) 各一套，**分值体系完全不同**（前者 doc_title=36，后者=300），同名极易混淆。

### P1-9　`build_toc_semantics` 580 行单体函数
- [toc_semantics/mod.rs:107-687](fnm-phase1/src/chapter_skeleton/toc_semantics/mod.rs)：单函数 16 个步骤。虽有步骤注释，但难测试/难维护，应按步骤拆分子函数。

### P1-10　`serde_json::to_value(RawPage)` 在循环内反复序列化
- [book_note_type/mod.rs:311,320](fnm-phase1/src/book_note_type/mod.rs)、[page_resolve.rs:32](fnm-phase1/src/chapter_skeleton/toc_semantics/page_resolve.rs)、[page_rows.rs:58](fnm-phase1/src/chapter_skeleton/heading_candidates/page_rows.rs)：把强类型 `RawPage` 序列化成 `serde_json::Value` 仅为调用接受 `Value` 的 fnm-core 函数（`page_markdown_text` 等）。在循环里对每页 serialize 一次，性能浪费 + 丧失类型安全。根因是 fnm-core 的 page 工具为兼容 Python dict 而以 `Value` 为入参；可加 `RawPage` 直取 `enriched_markdown/markdown` 的轻量 helper。

---

## 3. 🟡 低优先级 / nit

### 死代码 / 可见性规避（补充 P1-6/7）
- **下划线死 regex**（定义未用，`_` 抑制告警）：[heading_graph/title_key.rs:11](fnm-phase1/src/heading_graph/title_key.rs) `_TRAILING_NOTE_MARKER_RE`、[title_utils.rs:102](fnm-phase1/src/chapter_skeleton/toc_semantics/title_utils.rs) `_CHAPTER_KEYWORD_RE`、[title_utils.rs:149](fnm-phase1/src/chapter_skeleton/toc_semantics/title_utils.rs) `_YEAR_RANGE_RE`。
- **`#[allow(dead_code)]` 掩盖死代码**：[fallback.rs:85](fnm-phase1/src/chapter_skeleton/fallback.rs)（`SectionRow` 未读字段）、[fallback.rs:222](fnm-phase1/src/chapter_skeleton/fallback.rs)（`ClassifiedSection` 未读字段）、[fallback.rs:665](fnm-phase1/src/chapter_skeleton/fallback.rs)（`merge_section_heads` 无生产调用者）。
- **pub 函数疑似无项目内调用者**（`pub` 豁免 clippy dead_code）：`alignment::align_toc_to_chapters`、`container_detection::{is_container_chapter, expand_container_chapters}`、`monotonic::reorder_chapters_monotonic`、`fallback::build_chapter_skeleton_fallback`（builder 走分步调用而非它）、`normalize::role_by_no`。建议确认后删除或私有化。
- **`_` 前缀未用参数**（接口占位/未实现）：[pdf_font_band.rs:23-28](fnm-phase1/src/chapter_skeleton/heading_candidates/pdf_font_band.rs)（`_heading_candidates`/`_toc_items`/`_toc_offset`/`_doc_id`）、[toc_candidates.rs:135-137](fnm-phase1/src/chapter_skeleton/heading_candidates/toc_candidates.rs)（`_toc_offset`/`_raw_pages`/`_file_idx_map`，`resolve_toc_item_page` 只用 target_pdf_page）。

### 误导命名：`_` 前缀参数实际被使用
- [toc_tree.rs:108](fnm-phase1/src/toc_tree.rs) `_chapter_rows`（111 行起使用）、[heading_candidates/mod.rs:349,353](fnm-phase1/src/chapter_skeleton/heading_candidates/mod.rs) `_pdf_path`/`_doc_id`（375-383 使用）。`_` 前缀按惯例表示「有意忽略」，却被读取，误导读者。

### 字符串长度语义（byte vs char）
- 多处用 `str.len()`（字节）作行长度阈值（`>= 40/60/160`）：[role_heuristics/front_matter.rs:148-164](fnm-phase1/src/page_partition/role_heuristics/front_matter.rs)、back_matter.rs、note_pages.rs、section_heads.rs。Python `len()` 是字符数，Rust `.len()` 是字节数；法语（重音 2 字节）/中文（3 字节）文本下阈值系统性偏松，与 Python 不等价。建议需字符数处用 `.chars().count()`。

### 其他
- **stringly-typed**：heading_graph `anchor_state`/`anchor_strategy` 用裸字符串（"resolved"/"provisional"）；`visual_toc_chapter_level_style` 返回 `HashMap<String,bool>`（应 struct）。与 fnm-core types.rs 的 enum 努力不一致。
- **过时/不符注释**：[heading_candidates/mod.rs:374](fnm-phase1/src/chapter_skeleton/heading_candidates/mod.rs) 称 pdf_font_band「当前 stub」，实为完整实现；[monotonic.rs:5](fnm-phase1/src/chapter_skeleton/toc_semantics/monotonic.rs) 注释「严格递增」但实现是 `<=`（非严格）。
- **性能**：[continuation/mod.rs](fnm-phase1/src/page_partition/continuation/mod.rs) 各 fix 对每页 `page_texts.get().cloned()` clone 整页文本（应借 `&str`）；[rules/mod.rs:58](fnm-phase1/src/page_partition/rules/mod.rs) `all_rules()` 每页重建 `Vec<fn>`（可 const）。
- **未实现占位**：[selection.rs:112-113](fnm-phase1/src/llm_book_type_verify/selection.rs) endnote_regions 用「章边界近似」（注释诚实标注简化）。
- **`#[allow(dead_code)]` in tests**：phase1/tests/test_biopolitics_parity.rs 多处（测试辅助，可接受）。

---

## 4. 正面实践
- 规则引擎 `page_partition/rules/*` 模块化清晰（每规则一文件 + `all_rules()` 注册）。
- LLM verify 用 `chars().take()` 安全截断、`tokio::task::spawn_blocking` 渲染、`tracing::warn!` 记录失败、multi-model fallback。
- toc_structure 注释清楚解释了「为何不调 book_note_profile」（分类源头唯一）。
- 普遍测试覆盖好（含边界：lecture 集、misleveled、book endnote replay）。

---

## 5. 文件覆盖确认（56/56）
lib｜input｜page_roles｜section_heads｜toc_structure｜toc_tree｜book_note_type/mod｜heading_graph/{mod,matching,composite,scoring,title_key}｜llm_book_type_verify/{mod,client,prompt,selection}｜page_partition/{mod,role_resolver,continuation/mod}｜page_partition/role_heuristics/{mod,front_matter,back_matter,note_pages,patterns}｜page_partition/rules/{mod,archive_noise,copyright,course_listing,early_other,note_scan,notes_heading,rear_author,rear_sparse,rear_toc,title_page}｜chapter_skeleton/{mod,builder,fallback,pdf_font}｜chapter_skeleton/heading_candidates/{mod,family_guess,font_features,normalize,page_rows,pdf_font_band,toc_candidates}｜chapter_skeleton/toc_semantics/{mod,alignment,container_detection,lecture,monotonic,page_resolve,role_inference,row_collect,sanitize,title_utils}

**核心结论**：phase1 算法扎实，但需优先修 **P1-1（字节切片 panic）**；其次系统性清理「构建后丢弃」死代码（P1-6）、明确两大未接入子系统的状态（P1-7）、收敛重复 helper（P1-8）。死代码靠 `_`/`pub`/`#[allow]` 规避 clippy 是本 crate 最普遍的 AI 代码病。
