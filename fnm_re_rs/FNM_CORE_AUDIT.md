# fnm-core 审计记录

审计时间：2026-05-22

范围：`fnm-core` crate，包含 `src/`、`tests/`、`migrations/`。

## 结论

`fnm-core` 可以编译和通过现有测试，但不能通过 Rust 验收清单。主要风险集中在 segment 序列化丢正文、SQLite 迁移与 Repository API 不闭合、Clippy/format 门禁失败、公开参数无效，以及 DB 读回时静默把异常分类降级为 footnote。

## 发现

### P1：segment_codec 在 paragraphs 为空时丢正文

位置：
- `fnm-core/src/segment_codec.rs:21`
- `fnm-core/src/segment_codec.rs:41`

问题：
当输入 segment 只有顶层 `source_text` / `display_text`，但 `paragraphs=[]` 时，`serialize_segment()` 只输出 `{"p": page_no}`；`deserialize_segment_to_dict()` 只能从 `ps/paragraphs` 重建正文，最终 `source_text` 和 `display_text` 都变成空字符串。

复现：

```bash
.venv/bin/python - <<'PY'
import json, fnm_re_rs
segments=[{"page_no":7,"paragraph_count":1,"source_text":"top source","display_text":"top display","paragraphs":[]}]
compressed=json.loads(fnm_re_rs.serialize_segments_json(json.dumps(segments)))
restored=json.loads(fnm_re_rs.deserialize_segments_to_dicts_json(json.dumps(compressed)))
print(compressed)
print(restored)
PY
```

实测：

```text
[{"p": 7}]
[{"display_text": "", "page_no": 7, "paragraph_count": 0, "paragraphs": [], "source_text": ""}]
```

影响：
这会影响 Phase4/Phase5 的翻译单元文本安全。`segments.rs::normalize_unit_page_segment()` 有 fallback，但 `segment_codec` 作为公开 Pyo3 API 和 DB 压缩工具，本身不应丢字段。

建议：
先补失败测试，再修：如果 `paragraphs` 为空但顶层正文非空，序列化应保留必要字段，或反序列化旧格式时回退到顶层 `source_text/display_text`。

### P1：SQLite 迁移与 Repository API 不闭合

位置：
- `fnm-core/src/db/repository.rs:1534`
- `fnm-core/src/db/repository.rs:1568`
- `fnm-core/migrations/0001_initial.sql:12`

问题：
`Repository::load_raw_pages_for_doc()` 固定读取 `pages` 表；`load_toc_items_for_doc()` 固定读取 `documents.toc_user_json/toc_auto_visual_json/toc_auto_pdf_json`。但 `fnm-core` 迁移只创建最小 `documents`，不创建 `pages` 表，也不创建三个 TOC 列。

证据：
测试 helper 需要手动创建 `pages` 表并手动 `ALTER TABLE documents ADD COLUMN toc_*`，见 `fnm-core/src/db/repository.rs:1655` 和 `fnm-core/src/db/repository.rs:1665`。

影响：
`open_pool()` 创建的新库不能直接支撑 DB-driven pipeline；独立 Rust 入口或新临时库会在读 pages/TOC 前失败。

建议：
要么把 `pages` 表和 TOC 列纳入 `fnm-core` 迁移，要么把这些输入表明确移出 `fnm-core` Repository 契约。当前状态是 API 声称能读，迁移却不保证表存在。

### P2：fmt 和 clippy 门禁失败

位置：
- `fnm-core/src/title.rs:62`
- `fnm-core/src/db/repository.rs:182`
- `fnm-core/src/db/repository.rs:1561`
- `fnm-core/src/marker_seq.rs:74`
- `fnm-core/src/model_capabilities.rs:23`
- `fnm-core/src/ref_rewriter.rs:224`
- `fnm-core/src/segments.rs:298`

复现：

```bash
cargo fmt --check -p fnm-core
cargo clippy -p fnm-core --all-targets -- -D warnings
```

结果：
- `cargo fmt --check -p fnm-core` 失败，diff 在 `title.rs`。
- `cargo clippy -p fnm-core --all-targets -- -D warnings` 失败 14 个错误，包含 `too_many_arguments`、`match_result_ok`、`unnecessary_map_or`、`should_implement_trait`、`needless_update`、`len_zero`。

影响：
不满足当前仓库 Rust 验收 checklist。

建议：
先做纯机械修复，不改变行为；`too_many_arguments` 的公开 API 则需要用参数结构体收束。

### P2：replace_frozen_refs 的 endnote_mode 参数无效

位置：
- `fnm-core/src/refs.rs:125`
- `fnm-core/src/refs.rs:144`
- `fnm-py/src/lib.rs:1003`

问题：
`EndnoteMode` 支持 `Legacy` 和 `Standard`，Pyo3 也公开 `endnote_mode` 参数，但 `replace_frozen_refs(text, _mode)` 完全忽略该参数。

复现：

```bash
.venv/bin/python - <<'PY'
import fnm_re_rs
text="{{NOTE_REF:en-3}} {{EN_REF:4}}"
print(fnm_re_rs.replace_frozen_refs_json(text, "standard"))
print(fnm_re_rs.replace_frozen_refs_json(text, "legacy"))
PY
```

实测：

```text
[^en-3][^en-4]
[^en-3][^en-4]
```

建议：
如果两种模式本应不同，补 parity/行为测试后实现；如果没有差异，删掉参数或文档中明确它只是兼容占位。

### P2：chapter_title_match_key 清理不完整

位置：
- `fnm-core/src/title.rs:179`
- `fnm-core/src/title.rs:183`

问题：
`chapter_title_match_key()` 没复用 `normalized_title_key()`，最后使用 `TITLE_KEY_CLEAN_RE.replace()` 而不是 `replace_all()`。标题里存在多个非字母数字片段时，可能只清掉第一段，残留标点/空格。

影响：
TOC 与章节标题匹配可能出现假 mismatch。

建议：
先加包含多个标点、空格和重音的测试，再改成与 `normalized_title_key()` 一致的清理流程。

### P2：DB 读回时静默改写分类事实

位置：
- `fnm-core/src/db/repository.rs:492`
- `fnm-core/src/db/repository.rs:532`
- `fnm-core/src/db/repository.rs:702`
- `fnm-core/src/records.rs:321`
- `fnm-core/src/records.rs:561`

问题：
读回 note region / note item / note link 时，非法或缺失 `note_kind` 会 fallback 到 `NoteKind::Footnote`。`NoteItemRecord::default()` 也默认 footnote，`NoteLinkRecord::default()` 默认 `Matched + Footnote`。

影响：
这违反“分类源头唯一”和“不能静默广播/推断”的原则。异常数据可能被写成看似正常的 footnote/matched link，隐藏 Phase2/Phase3 的真实断层。

建议：
DB 读回应对非法 enum 报错，或显式进入 `review_required` / `orphan_note` 等保守状态；测试 helper 里也应显式填关键字段，不依赖危险 default。

### P2：load_raw_pages_for_doc 吞掉 row 级 DB 错误

位置：
- `fnm-core/src/db/repository.rs:1534`
- `fnm-core/src/db/repository.rs:1561`

问题：
`for row in rows { if let Some(Some(page)) = row.ok() { ... } }` 会把 rusqlite row 错误吞掉。跳过非法 JSON 可以接受，但 DB 读取错误不应静默丢页。

建议：
改为匹配 `Ok(Some(page))`、`Ok(None)`、`Err(e)` 三支；`Err(e)` 返回错误。

### P3：PDFIUM 全局 Mutex 需要例外说明

位置：
- `fnm-core/src/vision/pdfium.rs:15`

问题：
仓库规则要求 0 个 `Rc<RefCell>` / 0 个 `Arc<Mutex>`，唯一允许的 `Mutex` 是 `token_counter` 全局用量记录。这里存在 `Lazy<Mutex<Pdfium>>`。

判断：
这可能是 PDFium 绑定线程安全限制导致的合理工程选择，但当前没有注释解释例外。

建议：
如果必须保留，补充注释说明 PDFium 绑定的 Sync/Send 限制和为何需要串行化；否则应改成无全局 Mutex 的渲染资源管理。

## 验证记录

通过：

```bash
cargo build --release -p fnm-core
cargo test -p fnm-core
.venv/bin/python -m pytest fnm_re_rs/fnm-py/tests/test_segment_codec.py fnm_re_rs/fnm-py/tests/test_replace_frozen_refs.py -q
```

失败：

```bash
cargo fmt --check -p fnm-core
cargo clippy -p fnm-core --all-targets -- -D warnings
```

## 修复优先级

1. 先补 `segment_codec` 空 paragraphs 丢正文的失败测试并修复。
2. 补齐 DB migration 或收窄 Repository 契约。
3. 机械清理 fmt/clippy，公开多参 API 用参数结构体。
4. 明确并实现/删除 `EndnoteMode` 差异。
5. 收紧 DB enum 读回策略，禁止非法分类静默 fallback 到 footnote。
