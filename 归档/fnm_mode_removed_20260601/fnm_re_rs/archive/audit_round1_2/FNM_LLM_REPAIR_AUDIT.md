# fnm-llm-repair 审计记录

审计对象：`fnm-llm-repair`
审计日期：2026-05-22
审计范围：`src/`、`tests/`、workspace 构建/格式/测试/lint 状态。

## 结论

`fnm-llm-repair` 的测试数量比前几个 crate 更完整，且没有 ignored 测试；整体代码也有较多 Python 对照注释。但它仍存在几个会影响 FNM Phase 3.5 正确性的边界问题：

- synthesize anchor 的坐标单位混用，非 ASCII 正文中会写错 page-local char offset。
- duplicate anchor 预过滤只是从 cluster 中删除，不会物化 ignore override，导致 unresolved link 留在 DB。
- `synthesize_note_item` 允许 LLM 在 Phase 3.5 创建 note item，并用 cluster 的 `note_system` 写 `note_kind`，这绕开了 Phase2 的 note item 分类权。

这些问题会让 LLM repair 看起来“少了一些 unresolved”，但下游事实并没有真正闭合。

## P1：必须优先修复

### P1-1 fuzzy anchor 坐标是字符偏移，但 body spans 用的是 byte 偏移

位置：
- `fnm-llm-repair/src/strategies/fuzzy.rs`
- `fnm-llm-repair/src/page_context.rs`
- `fnm-llm-repair/src/override_materializer.rs`
- `fnm-llm-repair/src/run.rs`

`locate_anchor_phrase_in_body()` 明确返回字符偏移：

- `char_start`
- `char_end`

但 `build_chapter_body_text()` 生成 `BodySpan` 时使用 `text.len()` 和 `sep.len()`，这两个都是 byte 长度。随后 `enrich_synthesize_anchor_actions()` 把 fuzzy 的字符偏移传给 `resolve_page_span_from_range()`，再用 `global_start - span_start` 得到 page-local offset。

影响：
- 如果命中位置前面有中文、重音字符等多 byte 文本，page span 和 char offset 会错位。
- 跨页时尤其危险：前一页包含非 ASCII 字符后，第二页的字符 offset 可能仍落在第一页面的 byte span 范围内。
- 最终 `apply_synthesize_anchor()` 写入 override 的 `page_no`、`char_start`、`char_end` 可能错误。

修复方向：
- `BodySpan` 必须明确单位。若 `RepairAction.char_start/end` 是字符偏移，`BodySpan` 也必须用字符偏移。
- 如果下游 anchor 坐标 contract 是 byte offset，就在 fuzzy 命中后一次性转换为 byte offset，并用测试覆盖含中文/重音字符、跨页正文。
- 增加真实非 ASCII fixture 测试，不能只测同页 ASCII 或只验证 fuzzy 自身。

### P1-2 duplicate anchor 预过滤没有物化 override

位置：
- `fnm-llm-repair/src/run.rs`
- `fnm-llm-repair/src/override_materializer.rs`

`run_llm_repair()` 在每个 cluster 上先调用 `prefilter_duplicate_anchors(&mut cluster)`。这个函数会把同页同 marker 且已有 matched example 的 unmatched anchor 从 `cluster["unmatched_anchors"]` 中删除，只记录 `_prefilter_duplicates_removed`。

随后 `run_llm_repair()` 重新计算 `has_anchors` / `has_notes`，如果二者都为空就直接 `continue`。

影响：
- 被预过滤的 `orphan_anchor` 没有生成 `ignore_ref` override。
- DB 里的原始 unresolved link 仍然存在；本次 repair report 却不会包含它。
- 下一轮运行还会遇到同一个 orphan，除非其它阶段额外处理。

修复方向：
- 预过滤如果确认某 anchor 应忽略，必须生成等价的 `link` override：`{"action": "ignore"}`。
- 或者不要在 LLM 前删除，交给 `ignore_ref` 常规路径统一物化。
- `_prefilter_duplicates_removed` 不能替代持久化事实。

### P1-3 Phase 3.5 允许创建 note item，绕过 Phase2 分类权

位置：
- `fnm-llm-repair/src/prompt_builder.rs`
- `fnm-llm-repair/src/response_parser.rs`
- `fnm-llm-repair/src/run.rs`

当前允许的 action 包含 `synthesize_note_item`。在 `apply_synthesize_note_item()` 中，代码会创建：

- scope = `note_item`
- `note_item_id = llm-note-*`
- `note_kind = note_system`
- `chapter_id` 从 anchor 或页码推断
- `page_no` 使用 anchor 页码

这与当前 pipeline 职责边界冲突：Phase2 是 note item 和 `note_kind` 的唯一分类来源，Phase3.5 只应合成 anchor 或建议 link override，不能凭 cluster 聚合属性广播生成 note item。

影响：
- endnote 的 orphan anchor 也可能走 `synthesize_note_item`，在正文页创建 endnote item。
- `note_kind` 来源是 cluster 的 `note_system`，不是 Phase2 的逐 item 分类。
- 这会让下游看见一个“LLM 创建的注释事实”，但上游 Phase2 没有真实 region/item 支撑。

修复方向：
- 默认禁用 `synthesize_note_item`，只允许 `synthesize_anchor` 和 link override。
- 如果确实需要创建 note item，应回到 Phase2 repair contract：必须绑定真实 note region、page role、note_kind evidence，并以 Phase2 override 形式进入，而不是 Phase3.5 直接写。
- 至少先按 `note_system == "footnote"` 且同页 `fnBlock`/footnote evidence 明确时才允许，endnote 禁止。

### P1-4 auto-apply match 没有校验 action ID 属于当前 cluster

位置：
- `fnm-llm-repair/src/response_parser.rs`
- `fnm-llm-repair/src/run.rs`
- `fnm-llm-repair/src/override_materializer.rs`

`select_auto_applicable_actions()` 只检查 action 字段是否非空、confidence 是否过阈值、同批是否重复使用。它不校验：

- `note_item_id` 是否属于当前 cluster 的 unmatched/rebind 集合。
- `anchor_id` 是否属于当前 cluster 的 unmatched anchor。
- `anchor_id` 是否真实存在于 `anchors_by_id`。
- `note_kind` 是否与当前 cluster 一致。

`apply_action("match")` 又会优先用 `note_item_id` 找 link。如果 LLM 返回一个有效 note item id 但错误 anchor id，`find_link_id_for_match()` 仍能找到 link，然后写入错误 anchor override。

影响：
- LLM 输出跨 cluster ID 或不存在 ID 时，可能被自动应用。
- 这会直接污染 `fnm_review_overrides_v2`，比单纯 suggestion 错误更危险。

修复方向：
- 构造当前 cluster 的允许 ID 白名单。
- auto-apply 前验证 action 中的 `note_item_id` / `anchor_id` 都来自白名单。
- `match` 覆盖必须同时验证 link、note item、anchor 三者关系，而不是只凭其中一个 ID 找 link。

## P2：重要质量问题

### P2-1 page role 读取失败会静默放宽正文范围

位置：
- `fnm-llm-repair/src/page_context.rs`

`fnm_page_role_by_no()` 读取 DB 失败时直接返回空 `HashMap`。`build_chapter_body_text()` 看到 page_roles 为空，就不再过滤 page role，章节范围内所有 raw pages 都可能进入 `chapter_body_text`。

影响：
- note/back matter 页可能被当作正文，LLM 可能在注释区合成 body anchor。
- DB 或 migration 问题被隐藏成“repair 质量差”，不利于追上游断层。

修复方向：
- 读取 page role 失败应进入 request_metrics / trace，并禁用 synthesize_anchor auto-apply。
- 至少在 `build_chapter_body_text()` 中显式区分“没有 page role 数据”和“repo 查询失败”。

### P2-2 `derive_actions()` 对 endnote 也允许 `synthesize_note_item`

位置：
- `fnm-llm-repair/src/prompt_builder.rs`

`derive_actions()` 只看 cluster 中 unmatched anchors、rebind candidates、body text/page context，不看 `note_system`。因此 `ref_only_visual` 和部分 `anchor_rebind` 场景会对 endnote 也允许 `synthesize_note_item`。

影响：
- endnote 的缺失 note item 不应该从 body anchor page 的截图中创建。
- 这会把 body 页证据广播成 note item 事实。

修复方向：
- `derive_actions()` 接收 `note_system`，按 footnote/endnote 分流。
- endnote orphan anchor 默认只允许 `ignore_ref` 或 `needs_review`，不能创建 note item。

### P2-3 LLM 请求失败会留下部分已保存 overrides

位置：
- `fnm-llm-repair/src/run.rs`

`run_llm_repair()` 每处理完一个 cluster 就调用 `batch_save_fnm_review_overrides_v2()`。如果后续 cluster 的 LLM 请求失败，函数整体返回 Err，但前面已经保存的 overrides 不会回滚。

影响：
- 调用方看到 repair run 失败，但 DB 中可能已经有部分新 override。
- 重跑时前置 `clear_materialized_overrides` 只清 `llm_suggestion`，而非所有 scope，可能留下半次运行产物。

修复方向：
- 要么用 run_id 标记本轮 overrides，并在失败时清理本轮写入。
- 要么先收集全部 overrides，整轮成功后一次性写入。
- 报告中应明确 partial-write 状态。

### P2-4 `safe_float()` 接受 high/medium/low 文字置信度

位置：
- `fnm-llm-repair/src/usage.rs`
- `fnm-llm-repair/src/response_parser.rs`

系统 prompt 明确要求 confidence 必须是数字，但 parser 仍把 `"high"` 映射成 `0.9`、`"medium"` 映射成 `0.7`、`"low"` 映射成 `0.4`。

影响：
- 模型违反输出 contract 时仍可能 auto-apply。
- 这是偏防御性的兼容逻辑，会降低 schema 约束的实际强度。

修复方向：
- 对 auto-apply 路径要求 confidence 必须是 JSON number。
- 文字置信度最多保留为 suggestion，不进入 auto-apply。

### P2-5 trace 写入吞掉 IO 错误且计数可能不真实

位置：
- `fnm-llm-repair/src/trace/dump.rs`

`dump_traces()` / `write_summary_traces()` 忽略 `create_dir_all` 和 `write` 的错误。`written += 1` 只依赖 JSON 序列化成功，不依赖文件写入成功。

影响：
- 报告称写入成功，但磁盘上可能没有 trace 文件。
- 后续调试 LLM repair 时，缺少失败原因。

修复方向：
- 返回 `Result<i64>` 或同时返回 `errors`。
- `written` 只在 `std::fs::write()` 成功后递增。

## P3：代码质量与测试缺口

### P3-1 大文件需要继续拆分

超过 400 行的文件：

- `fnm-llm-repair/src/prompt_builder.rs`：788 行
- `fnm-llm-repair/src/page_context.rs`：776 行
- `fnm-llm-repair/src/run.rs`：703 行
- `fnm-llm-repair/src/llm_client/request.rs`：702 行
- `fnm-llm-repair/src/cluster.rs`：633 行
- `fnm-llm-repair/src/response_parser.rs`：526 行
- `fnm-llm-repair/src/override_materializer.rs`：476 行

这些文件已经超过 Rust 重构规范的单一职责线，尤其 `run.rs` 同时包含编排、action 物化、override 写入、report 组装。

### P3-2 `serde_json::Value` schema 过宽

大量核心路径用 `Value` 传递 cluster/action/link/note/anchor。这样虽然接近 Python dict，但 Rust 侧缺少编译期 schema 约束，导致 P1-4 这类 ID 白名单问题更容易出现。

建议：
- 对 request cluster、action payload、override payload 建最小 typed struct。
- `Value` 只保留在 trace/output 边界。

### P3-3 当前 clippy 未达验收标准

验证结果：

- `cargo build --release -p fnm-llm-repair`：通过，但有 `unused import: anyhow::Result` warning。
- `cargo fmt --check -p fnm-llm-repair`：通过。
- `cargo test -p fnm-llm-repair`：通过，126 个 lib tests、4 个 integration tests、39 个 spec tests，0 ignored。
- `cargo clippy -p fnm-llm-repair --all-targets -- -D warnings`：先被 `fnm-core` 既有 lint 阻断。
- 放宽前序已知 lint 后，`fnm-llm-repair` 本体仍有 2 个错误：
  - `page_context.rs` unused import。
  - `response_parser.rs` 测试中 redundant local。

## 建议修复顺序

1. 统一 fuzzy/body span/override 坐标单位，并补非 ASCII 跨页测试。
2. 删除或禁用 `synthesize_note_item` 自动落地路径，至少先禁止 endnote。
3. duplicate anchor 预过滤必须物化 ignore override，或移除预过滤。
4. auto-apply 前增加 cluster ID 白名单校验。
5. 处理 LLM run partial-write 语义。
6. 拆分大文件，减少 `Value` 在核心逻辑中的传播。

