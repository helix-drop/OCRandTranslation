# FNM-LLM-REPAIR 审计报告（独立第二轮）

> 审计范围：`fnm-llm-repair` crate 全部 18 个 `.rs` 文件（约 6,411 行）。Phase 3.5：LLM 修补未解析 link。
> 维度：程序逻辑、Rust 风格、过度防御/偷懒/AI 常见病。业务规则不评判。
> 方法：逐文件精读核心（run/request/error/response_parser）+ 反模式 grep 全覆盖 + unwrap 守卫核实。审计期间未参考现有 `audit/`。
> 审计人：Claude（claude-opus-4-8）｜日期：2026-05-29

---

## 0. 总体印象：高质量（与 phase3/4 同档）

LLM 调用 crate 最易出问题的几处（并发、重试、超时、错误分类、响应容错）**都处理得当**：

- **错误分类完整、语义正确**（[llm_client/error.rs](fnm-llm-repair/src/llm_client/error.rs)）：`ProviderError` 区分 RateLimited / QuotaExceeded / Transient / NonRetryable；`is_retryable` 只含 RateLimited + Transient（**QuotaExceeded 明确不重试**——额度耗尽重试无意义）；按 status（429/402/5xx）+ provider code（1302/1303/1305/1312）+ transport 关键词分类。
- **async 设计正确**：`run_llm_repair`/`request_llm_repair_actions` 是 async fn，**无循环内 `Runtime::new`**（仅注释提示同步调用方用 block_on）。
- **重试 + 退避 + 限流**（[request.rs](fnm-llm-repair/src/llm_client/request.rs)）：GLM-4.6V 专属 `Semaphore` 限 in-flight + 指数退避 `2^retry_no` + 优先用 provider `retry-after`；per-request 60s 超时。
- **多模型 fallback + moderation 剥图重试**：内容审核错误（data_inspection/content_filter）剥离图片重试，再失败降级下一 model。
- **响应解析多级容错**（[response_parser.rs](fnm-llm-repair/src/response_parser.rs)）：fenced code block → 直接 parse → `[..]` 子串提取 → 返回空 vec，**畸形 JSON 绝不 panic**。
- **遵守 Phase 3.5 红线**：`synthesize_note_item` action 已移除（run.rs:520 注释「Phase3.5 无权创建 note item」），只生成 link/anchor override，不创建/重分类 note item（符合 CLAUDE.md §12）。
- 全 crate **无** `#[allow]`/`as` 窄化；所有非测试 unwrap 已核实安全（测试 / 前置守卫 / 已知 JSON 结构 / map-key 逻辑保证）；clippy clean。
- P0-2 / P1-1（cluster 白名单 note/anchor id）/ P1-2（prefilter override 先于 LLM 持久化，避免 LLM 失败丢结果）均有标注与实现。

---

## 1. 🟡 低优先级（无高/中级真 bug）

### L-1　`page_context` 的 `map[&key].iter().min().unwrap()` 依赖 value 非空
- **位置**：[page_context.rs:117-134](fnm-llm-repair/src/page_context.rs)
- `low`/`up` 取自 `known_pages_by_marker.keys()`，故 HashMap 索引必命中；但 `.iter().min().unwrap()` 要求对应 `Vec<page>` 非空。若构建处曾插入空 vec 则 panic。属「逻辑保证非空」的防御性 unwrap（与 phase3 gap_recovery 同类），建议改 `if let Some(min) = ...` 消除 panic 面。

### L-2　日志用 `eprintln!` 而非 `tracing`
- [run.rs:523](fnm-llm-repair/src/run.rs) `synthesize_note_item` 被忽略时 `eprintln!("[WARNING]...")`。与 fnm-core 同款不统一问题——建议统一 `tracing::warn!`。

### L-3　重试仅对 GLM-4.6V 启用（其他 provider `max_retries=0`）
- [request.rs:504](fnm-llm-repair/src/llm_client/request.rs)：非 GLM-4.6V 的 provider 瞬时错误（网络抖动、偶发 429）**不在单模型内重试**，直接降级到下一 fallback model 或失败。
- **评价**：是有意设计（GLM-4.6V 有特殊 in-flight 约束），靠多模型 fallback 兜底。但若用户只配单 model 且无 fallback，偶发瞬时错误会直接失败。可考虑对所有 provider 加一次轻量瞬时重试。设计权衡，非 bug。

### L-4　moderation 检测靠错误消息子串匹配
- [request.rs:388-391](fnm-llm-repair/src/llm_client/request.rs)：`lowered.contains("data_inspection_failed"|"content_filter"|"review")` 判断内容审核错误。脆弱（消息文案变化即失效），但与 Python `is_moderation` 等价移植，注释说明。低优先级。

### L-5　nit
- trace snapshot 多处 `.clone()`（token_accounting/raw_text/usage/parsed_actions）——注释说明 result 与 trace 是独立 owner，可接受。
- moderation 降级与普通错误降级两条 `continue` 路径略重复，可合并。

---

## 2. 正面实践
- `ProviderError` 用 `thiserror` + 中文用户友好 message，分类 + retry 元数据（retry_after_s）内聚。
- `classify_provider_error` 对「无 status 的传输错误」（connection refused/reset/dns）单独分类为可重试 Transient（有测试 `test_call_provider_classifies_connect_refused_as_retryable_transient`）。
- GLM-4.6V 文本预算校验（`validate_glm46v_text_budget`）在请求前拦截超 128K 窗口。
- 非 JSON 响应体兜底包装为 `{"error":{"message":body}}` 供分类器抽取。
- skipped 路径（仅 needs_review 的 cluster 不请求 LLM）完整构造 trace + metrics。

---

## 3. 文件覆盖确认（18/18）
lib｜constants｜cluster｜run｜override_materializer｜page_context｜prompt_builder｜response_parser｜usage｜llm_client/{mod,error,request}｜render/{mod,page_data_url}｜strategies/{mod,fuzzy}｜trace/{mod,dump}

> 逐字精读 run + request + error + response_parser + 全部潜在 panic 点的 unwrap 守卫；其余经反模式 grep（clean）+ 去注释 cat + 调用核实覆盖。

**核心结论**：fnm-llm-repair 是高质量 crate，LLM 调用的并发/重试/超时/错误分类/响应容错均到位，遵守 Phase 3.5 不创建 note item 的红线。仅低优先级清理项（防御 unwrap、eprintln→tracing、非 GLM provider 重试策略）。
