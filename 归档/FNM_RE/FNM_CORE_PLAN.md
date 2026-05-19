# `fnm-core` 实施计划

> 🟢 **状态：100% 完成（2026-05-18）**
>
> - 110 lib tests + 9 集成测试通过
> - 全部 17 个 shared/ Python 模块 + 3 新基建 port 完成：
>   - `model_capabilities.rs`（462 行，5 家 provider ~40 ModelSpec）
>   - `config.rs`（278 行，AppConfig + ModelPoolSlot + 5 API key getter）
>   - `vision/spec.rs`（403 行，ResolvedModelSpec + thinking_request_overrides + 4 个 resolve_*）
> - 完整完成度见 [`fnm_re_rs/FNM_RE_REFACTOR.md` §2.1](../fnm_re_rs/FNM_RE_REFACTOR.md)
>
> 本文档作为历史实施计划保留。下方原文档内容未修改。

---

本文档是 `fnm-core` Rust crate 的完整实施说明书。读完即可独立开工，无需进一步澄清。

> 阅读前置：先看 [`RUST_MIGRATION_PLAN.md`](./RUST_MIGRATION_PLAN.md) 了解整个 FNM_RE → Rust 迁移的全局架构。

---

## 目标与定位

`fnm-core` 是 FNM_RE Rust 重写的**基础设施层**，被后续所有 phase crate（`fnm-phase1` 到 `fnm-phase6`、`fnm-llm-repair`、`fnm-orchestrator`）依赖。

**职责**：
1. **类型契约**：定义 `NoteKind`/`AnchorKind`/`NoteMode`/`PageRole` 等 enum，与 Python `FNM_RE.constants` 严格一一对应
2. **数据结构**：定义所有 Record struct（`ChapterRecord`/`NoteItemRecord`/`BodyAnchorRecord` 等），可序列化为 JSON 与 Python 互通
3. **共享工具**：纯函数式工具（文本规范化、marker 解析、ref token 处理、anchor kind 判定）
4. **DB 访问层**：基于 `rusqlite` 的 `Repository` trait，封装所有 phase 间通信需要的表读写
5. **测试基础设施**：snapshot 测试框架 + Python ↔ Rust JSON 对齐工具

**不做的事**（这些在后续 phase crate 实现）：
- 业务编排逻辑（`build_*_structure` 入口）
- LLM 调用
- PDF 渲染
- 单 phase 内部算法（chapter_split 等）

**Python 源对应**：
| Python 路径 | 行数 | 全 port |
|---|---:|:---:|
| `FNM_RE/constants.py` | 87 | ✅ |
| `FNM_RE/models.py` | 680 | ✅ |
| `FNM_RE/shared/anchors.py` | 374 | 部分（仅 `resolve_anchor_kind` 和正则常量）|
| `FNM_RE/shared/chapters.py` | 56 | ✅ |
| `FNM_RE/shared/export_constants.py` | 72 | ✅ |
| `FNM_RE/shared/marker_sequences.py` | 105 | ✅ |
| `FNM_RE/shared/notes.py` | 858 | 部分（仅 `normalize_note_marker` 等基础工具）|
| `FNM_RE/shared/note_lookup.py` | 16 | ✅ |
| `FNM_RE/shared/note_modes.py` | 77 | ✅ |
| `FNM_RE/shared/refs.py` | 134 | ✅ |
| `FNM_RE/shared/ref_rewriter.py` | 270 | ✅ |
| `FNM_RE/shared/review_overrides.py` | 46 | ✅ |
| `FNM_RE/shared/review.py` | 25 | ✅ |
| `FNM_RE/shared/segments.py` | 222 | ✅ |
| `FNM_RE/shared/segment_codec.py` | 139 | ✅ |
| `FNM_RE/shared/text.py` | 111 | ✅ |
| `FNM_RE/shared/title.py` | 63 | ✅ |
| `FNM_RE/shared/token_counter.py` | 108 | ✅ |
| `persistence/sqlite_schema.py` 相关表 | - | DDL 翻译 |
| **合计** | **~3,500 行** Python | → 预计 **~5,000 行** Rust |

---

## Crate 结构

```
fnm-core/
├── Cargo.toml
├── README.md
├── build.rs                       # 嵌入 migrations/*.sql
├── migrations/
│   └── 0001_initial.sql           # 来自 persistence/sqlite_schema.py 的 SQL
├── src/
│   ├── lib.rs                     # crate 入口：re-export 公开 API
│   ├── types.rs                   # ←→ FNM_RE/constants.py
│   ├── records.rs                 # ←→ FNM_RE/models.py
│   ├── text.rs                    # ←→ FNM_RE/shared/text.py
│   ├── title.rs                   # ←→ FNM_RE/shared/title.py
│   ├── refs.rs                    # ←→ FNM_RE/shared/refs.py
│   ├── ref_rewriter.rs            # ←→ FNM_RE/shared/ref_rewriter.py
│   ├── anchor_kind.rs             # ←→ FNM_RE/shared/anchors.py 子集（resolve_anchor_kind + regex）
│   ├── note_marker.rs             # ←→ FNM_RE/shared/notes.py 子集（normalize_note_marker、is_notes_heading_line）
│   ├── note_modes.rs              # ←→ FNM_RE/shared/note_modes.py
│   ├── marker_seq.rs              # ←→ FNM_RE/shared/marker_sequences.py
│   ├── chapters.rs                # ←→ FNM_RE/shared/chapters.py
│   ├── note_lookup.rs             # ←→ FNM_RE/shared/note_lookup.py
│   ├── review.rs                  # ←→ FNM_RE/shared/review.py
│   ├── review_overrides.rs        # ←→ FNM_RE/shared/review_overrides.py
│   ├── segments.rs                # ←→ FNM_RE/shared/segments.py
│   ├── segment_codec.rs           # ←→ FNM_RE/shared/segment_codec.py
│   ├── token_counter.rs           # ←→ FNM_RE/shared/token_counter.py
│   ├── export_constants.rs        # ←→ FNM_RE/shared/export_constants.py
│   ├── db/
│   │   ├── mod.rs                 # Repository trait + 类型别名
│   │   ├── pool.rs                # r2d2_sqlite 连接池
│   │   ├── schema.rs              # migrations 加载
│   │   └── repository.rs          # SQLite 实现
│   └── testing/
│       ├── mod.rs                 # 仅 `cfg(test)` 启用
│       ├── fixtures.rs            # 测试 fixture 加载（与 Python tests/unit/fixtures/ 同源）
│       └── json_diff.rs           # JSON 对齐对比工具
├── tests/
│   ├── parity/                    # Python ↔ Rust 输出对齐测试
│   │   ├── test_normalize_note_marker.rs
│   │   ├── test_resolve_anchor_kind.rs
│   │   ├── test_cleanup_nested_note_refs.rs
│   │   ├── test_note_modes_roundtrip.rs
│   │   ├── test_segment_codec_roundtrip.rs
│   │   └── ...（每个公开函数一个 parity 测试）
│   └── snapshots/                 # cargo test --features=insta 用
│       └── ...
└── benches/
    ├── bench_regex.rs             # 与 Python re 比对的性能基准
    └── bench_serialize.rs
```

---

## 实施顺序（按依赖关系分 12 个任务）

每个任务都是独立 PR 单元。完成顺序严格按下表（任务 N 完成才能开始任务 N+1，除非显式可并行）。

| # | 任务 | 工时 | 依赖 | 可并行 |
|--:|---|---:|---|---|
| T1 | 项目骨架 + Cargo.toml + CI | 0.5 天 | - | - |
| T2 | `types.rs`：Literal → enum | 0.5 天 | T1 | - |
| T3 | `records.rs`：dataclass → struct | 1 天 | T2 | - |
| T4 | `note_marker.rs`：normalize + heading 判定 | 0.5 天 | T2 | 与 T5 并行 |
| T5 | `title.rs` + `text.rs`：文本工具 | 1 天 | T2 | 与 T4 并行 |
| T6 | `refs.rs`：NOTE_REF token 处理 | 0.5 天 | T4 | 与 T7 并行 |
| T7 | `note_modes.rs`：alias 双向映射 | 0.25 天 | T2 | 与 T6 并行 |
| T8 | `anchor_kind.rs`：resolve_anchor_kind + 正则池 | 0.5 天 | T4 | - |
| T9 | `marker_seq.rs` + `chapters.rs` + `note_lookup.rs` + `review.rs` + `review_overrides.rs` | 0.5 天 | T3 | 与 T10 并行 |
| T10 | `segments.rs` + `segment_codec.rs` | 1 天 | T3 | 与 T9 并行 |
| T11 | `ref_rewriter.rs` + `token_counter.rs` + `export_constants.rs` | 1 天 | T6 | - |
| T12 | DB 层（migrations + Repository trait + r2d2 pool） | 1.5 天 | T3 | - |
| **总计** | | **~8 天** | | |

---

## 关键基础设施（T1 一次性建立）

### Cargo.toml

```toml
[package]
name = "fnm-core"
version = "0.1.0"
edition = "2021"
rust-version = "1.75"

[dependencies]
# 序列化
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
serde_with = "3.4"

# 正则与字符串
regex = "1.10"
once_cell = "1.19"
unicode-normalization = "0.1"

# 错误处理
thiserror = "1.0"
anyhow = "1.0"

# 日志
tracing = "0.1"

# SQLite
rusqlite = { version = "0.31", features = ["bundled", "chrono"] }
r2d2 = "0.8"
r2d2_sqlite = "0.24"

# Tokenizer（用于 token_counter）
tokenizers = { version = "0.15", default-features = false, features = ["onig"] }

[dev-dependencies]
insta = { version = "1.34", features = ["json", "redactions"] }
pretty_assertions = "1.4"
tempfile = "3.10"

[build-dependencies]
# 嵌入 migrations/*.sql
```

### CI 配置（`.github/workflows/rust.yml`）

```yaml
name: Rust CI
on:
  push:
    branches: [main]
    paths: ['fnm_re_rs/**']
  pull_request:
    paths: ['fnm_re_rs/**']

jobs:
  build-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: rustfmt, clippy
      - run: cargo fmt --check
      - run: cargo clippy --all-targets -- -D warnings
      - run: cargo test --all
      - run: cargo bench --no-run
```

### 测试基础设施

每个公开函数必须有 **parity test**：用 Python 同名函数的输出作为 ground truth。

**Parity 测试模板**（放在 `tests/parity/`）：

```rust
// tests/parity/test_normalize_note_marker.rs
use fnm_core::note_marker::normalize_note_marker;
use serde_json::Value;

#[test]
fn matches_python_output() {
    let cases: Vec<Value> = serde_json::from_str(include_str!("../fixtures/normalize_note_marker_cases.json"))
        .expect("load fixture");
    for case in cases {
        let input = case["input"].as_str().unwrap();
        let expected = case["expected"].as_str().unwrap();
        let actual = normalize_note_marker(input);
        assert_eq!(
            actual, expected,
            "input={:?} expected={:?} got={:?}",
            input, expected, actual
        );
    }
}
```

**Fixture 生成脚本**（Python 端，放在 `tools/gen_parity_fixtures.py`，在 T2 后由实施者创建）：

```python
# 生成 tests/parity_fixtures/*.json，用 Python 函数喂入测试用例后写出 (input, expected) 对
# fnm-core 端跑 cargo test 时读这些 JSON
import json
from pathlib import Path
from FNM_RE.shared.notes import normalize_note_marker

cases = []
for raw in ["12", " 1 2 ", "12a", "<sup>5</sup>", "", "abc", "1.", "[3]", " ⁵ "]:
    cases.append({"input": raw, "expected": normalize_note_marker(raw)})

Path("fnm_re_rs/fnm-core/tests/fixtures/normalize_note_marker_cases.json").write_text(
    json.dumps(cases, ensure_ascii=False, indent=2)
)
```

---

## 任务详细规格

### T1: 项目骨架（0.5 天）

**交付物**：
1. `fnm_re_rs/Cargo.toml`（workspace 根，列出 9 个 member crate，目前只 push fnm-core）
2. `fnm_re_rs/fnm-core/Cargo.toml`（上面的模板）
3. `fnm_re_rs/fnm-core/src/lib.rs`（空骨架，含 `pub mod types;` 等占位）
4. `.github/workflows/rust.yml`
5. `tools/gen_parity_fixtures.py`（脚本骨架，后续每个任务往里加 case 生成代码）
6. `README.md`：说明 parity 测试如何跑

**验收**：
- `cargo build` 通过
- `cargo test` 跑过（0 个测试，但通过编译）
- `cargo clippy -- -D warnings` 通过

---

### T2: `types.rs` ←→ `constants.py`（0.5 天）

**Python 源**（`FNM_RE/constants.py`）的所有 Literal 类型 + 验证函数。

**Rust 实现**：

```rust
// src/types.rs
use serde::{Deserialize, Serialize};

/// 与 Python `Literal["noise", "front_matter", "body", "note", "other"]` 对应。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PageRole {
    Noise,
    FrontMatter,
    Body,
    Note,
    Other,
}

impl PageRole {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Noise => "noise",
            Self::FrontMatter => "front_matter",
            Self::Body => "body",
            Self::Note => "note",
            Self::Other => "other",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s.trim() {
            "noise" => Some(Self::Noise),
            "front_matter" => Some(Self::FrontMatter),
            "body" => Some(Self::Body),
            "note" => Some(Self::Note),
            "other" => Some(Self::Other),
            _ => None,
        }
    }
}

// 同样的模式：
// ChapterSource: visual_toc / fallback
// BoundaryState: ready / review_required
// NoteKind: footnote / endnote
// RegionScope: chapter / book
// RegionSource: heading_scan / footnote_band / continuation_merge / manual_rebind /
//               explorer_toc_match / explorer_signal_match / fallback_nearest_prior
// NoteMode: footnote_primary / chapter_endnote_primary / book_endnote_bound / no_notes / review_required
// AnchorKind: footnote / endnote / unknown
// LinkStatus: matched / orphan_note / orphan_anchor / ambiguous / ignored
// LinkResolver: rule / fallback / repair
// PipelineState: idle / running / error / done
```

**关键约束**：
- `#[serde(rename_all = "snake_case")]` 确保 JSON 序列化与 Python Literal 字符串完全一致
- 每个 enum 都实现 `as_str()` 和 `from_str()`，对外的字符串契约固定
- `from_str` 接收字符串前先 `.trim()`（与 Python `is_valid_*` 行为一致）

**测试**：
```rust
#[test]
fn page_role_serialize_matches_python() {
    assert_eq!(serde_json::to_string(&PageRole::FrontMatter).unwrap(), "\"front_matter\"");
}

#[test]
fn page_role_parse_strips_whitespace() {
    assert_eq!(PageRole::from_str("  body  "), Some(PageRole::Body));
}
```

**Parity fixture**（`tests/fixtures/types_validity_cases.json`）：
- 由 `gen_parity_fixtures.py` 跑 Python `is_valid_page_role` 等 10 个函数生成，覆盖空串、空格、未知值等边界

---

### T3: `records.rs` ←→ `models.py`（1 天）

**Python 源**（`FNM_RE/models.py` 共 37 个 dataclass，680 行）。

**Rust 实现策略**：
- 每个 dataclass → `#[derive(Debug, Clone, Serialize, Deserialize)] pub struct`
- `field(default_factory=list)` → `#[serde(default)] Vec<T>`
- `field(default_factory=dict)` → `#[serde(default)] serde_json::Map<String, serde_json::Value>`（保留 Python dict 的灵活性）
- `Optional[X]` → `Option<X>`，加 `#[serde(skip_serializing_if = "Option::is_none")]`

**示例**：

```rust
// src/records.rs
use crate::types::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PipelineIdentity {
    #[serde(default)] pub run_id: String,
    #[serde(default)] pub pipeline_version: String,
    #[serde(default)] pub raw_pages_hash: String,
    #[serde(default)] pub toc_hash: String,
    #[serde(default)] pub override_hash: String,
    #[serde(default)] pub parser_version: String,
    #[serde(default)] pub freeze_version: String,
    #[serde(default)] pub chunk_plan_hash: String,
    #[serde(default)] pub max_body_chars: i64,
    #[serde(default)] pub created_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PagePartitionRecord {
    pub page_no: i64,
    pub target_pdf_page: i64,
    pub page_role: PageRole,
    pub confidence: f64,
    pub reason: String,
    pub section_hint: String,
    pub has_note_heading: bool,
    #[serde(default)] pub note_scan_summary: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterRecord {
    pub chapter_id: String,
    pub title: String,
    pub start_page: i64,
    pub end_page: i64,
    pub pages: Vec<i64>,
    pub source: ChapterSource,
    pub boundary_state: BoundaryState,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NoteItemRecord {
    pub note_item_id: String,
    pub region_id: String,
    pub chapter_id: String,
    pub page_no: i64,
    pub marker: String,
    pub marker_type: String,
    pub text: String,
    pub source: String,
    pub source_page_label: String,
    pub is_reconstructed: bool,
    pub review_required: bool,
    pub note_kind: NoteKind,  // 注意：Issue 9 已升级为 NoteKind Literal，Rust 端跟进
}

// ... 共 37 个 struct
```

**关键约束**：
- 所有 struct 必须能从 Python JSON 输出（`asdict()` + `json.dumps()`）反序列化成功
- 反过来：Rust 序列化的 JSON 喂给 Python dataclass，字段名要对齐
- **`note_kind` 字段必须 `NoteKind` 枚举类型**（不是 `String`），强制类型安全（参考 Issue 9）

**测试**：
为每个 struct 写 round-trip parity 测试：
```rust
#[test]
fn chapter_record_roundtrip() {
    let python_json = include_str!("../fixtures/chapter_record_example.json");
    let parsed: ChapterRecord = serde_json::from_str(python_json).unwrap();
    let re_serialized = serde_json::to_string(&parsed).unwrap();
    let re_parsed: ChapterRecord = serde_json::from_str(&re_serialized).unwrap();
    assert_eq!(parsed.chapter_id, re_parsed.chapter_id);
    assert_eq!(parsed.source, re_parsed.source);
    // ... 逐字段断言
}
```

**Fixture 生成**（Python 端）：
```python
# tools/gen_parity_fixtures.py
from dataclasses import asdict
from FNM_RE.models import ChapterRecord
import json

example = ChapterRecord(
    chapter_id="toc-ch-1",
    title="Chapter One",
    start_page=10,
    end_page=20,
    pages=list(range(10, 21)),
    source="visual_toc",
    boundary_state="ready",
)
Path("fnm-core/tests/fixtures/chapter_record_example.json").write_text(
    json.dumps(asdict(example), ensure_ascii=False, indent=2)
)
```

---

### T4: `note_marker.rs` ←→ `notes.py` 子集（0.5 天）

**Python 源**：`FNM_RE/shared/notes.py` 中的纯函数子集：
- `normalize_note_marker` (line 187)
- `strip_markdown_heading` (line 206)
- `is_notes_heading_line` (line 214)
- `first_notes_heading` (line 219)
- 相关正则：`_MARKDOWN_HEADING_RE`、`_NOTES_HEADING_RE`、`_SYMBOLIC_MARKER_RE`

**不 port 的部分**：`parse_note_items_from_text` 等复杂业务（留给 `fnm-phase2`）

**Rust 实现**：

```rust
// src/note_marker.rs
use once_cell::sync::Lazy;
use regex::Regex;

static MARKDOWN_HEADING_RE: Lazy<Regex> = Lazy::new(||
    Regex::new(r"^\s{0,3}#{1,6}\s*(.+?)\s*$").unwrap()
);
static NOTES_HEADING_RE: Lazy<Regex> = Lazy::new(||
    Regex::new(r"(?im)^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*|注释|脚注|尾注)\s*$").unwrap()
);
static SYMBOLIC_MARKER_RE: Lazy<Regex> = Lazy::new(||
    Regex::new(r"^[\*†‡§¶]{1,4}$").unwrap()
);

/// 规范化注释 marker。
///
/// 与 Python `FNM_RE.shared.notes.normalize_note_marker` 行为一致：
/// - 空白去除
/// - Unicode 上标数字 (`¹²³...`) → ASCII 数字
/// - 保留符号型 marker (`*`/`**`/`†` 等)
/// - 其余只保留数字
pub fn normalize_note_marker(raw: &str) -> String {
    // ... 实现细节（按 Python 行 187-204 翻译）
}

pub fn strip_markdown_heading(line: &str) -> String { /* line 206 */ }

pub fn is_notes_heading_line(line: &str) -> bool {
    NOTES_HEADING_RE.is_match(line.trim())
}

pub fn first_notes_heading(markdown: &str) -> String { /* line 219 */ }
```

**Parity 测试**：fixture 覆盖
- 普通数字：`"1"`, `"  12  "`, `"123"`
- Unicode 上标：`"¹"`, `"⁴⁵"`, `"²³⁴⁵"`
- 符号：`"*"`, `"**"`, `"†"`, `"‡‡"`
- 边界：`""`, `"abc"`, `"1.2"`, `"<sup>5</sup>"`（应只取 `5`）
- 长度：4 位以内保留，5 位以上截断为 `""`

**验收**：用 Python `parse_note_items_from_text` 调用过的全部 marker 字符串作 fixture，确保 Rust 端输出完全一致。

---

### T5: `title.rs` + `text.rs`（1 天）

**Python 源**：`FNM_RE/shared/title.py`、`FNM_RE/shared/text.py`

**Rust 公开 API**：

```rust
// src/title.rs
pub fn normalize_title(raw: &str) -> String { ... }
pub fn normalized_title_key(text: &str) -> String { ... }
pub fn title_word_similarity(left: &str, right: &str) -> f64 { ... }
pub fn shared_title_tokens(left: &str, right: &str) -> Vec<String> { ... }

// src/text.rs
use serde_json::Value;

pub fn page_markdown_text(page: &Value) -> String { ... }
pub fn page_blocks(page: &Value) -> Vec<Value> { ... }
pub fn extract_page_headings(page: &Value) -> Vec<String> { ... }
pub fn has_note_heading(page: &Value) -> bool { ... }
pub fn first_section_hint(page: &Value, note_scan: Option<&Value>) -> String { ... }
pub fn note_scan_summary(note_scan: &Value) -> Value { ... }
pub fn plain_text_lines(text: &str) -> Vec<String> { ... }
```

**关键设计**：
- 输入 page 用 `&serde_json::Value`（保持 Python dict 兼容），因为 page 是 OCR 输出的原始 JSON，结构不强制
- 上层 phase crate 之后可以包装成 `Page` struct，但 fnm-core 保持灵活

**测试**：用 Biopolitics fixture 中的 page JSON 喂入，比对 Python 输出。

---

### T6: `refs.rs`（0.5 天）

**Python 源**：`FNM_RE/shared/refs.py`（134 行）

**Rust 公开 API**：

```rust
// src/refs.rs
use once_cell::sync::Lazy;
use regex::Regex;

pub static NOTE_REF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\{\{NOTE_REF:([^}]+)\}\}").unwrap());
pub static FN_REF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\{\{FN_REF:([^}]+)\}\}").unwrap());
pub static EN_REF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\{\{EN_REF:([^}]+)\}\}").unwrap());
pub static NOTE_REF_TOKEN_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\{\{NOTE_REF:[^}]+\}\}").unwrap());
// VISIBLE_ENDNOTE_RE、VISIBLE_FOOTNOTE_RE 同样

pub fn cleanup_nested_note_refs(text: &str) -> String {
    // 实现 Python `FNM_RE.shared.refs.cleanup_nested_note_refs`
    // 关键算法：
    //   while changed:
    //     1. 找 SPLIT pattern (NOTE_REF 被嵌套 NOTE_REF 分裂) → 替换为两个独立 token
    //     2. 找 NESTED pattern (NOTE_REF 内部包含 NOTE_REF) → 拆分为相邻两个 token
    //   循环直到无变化
}

pub fn frozen_note_ref(note_id: &str) -> String {
    let token = note_id.trim();
    if token.is_empty() { String::new() } else { format!("{{{{NOTE_REF:{}}}}}", token) }
}

pub fn note_kind_from_id(note_id: &str) -> NoteKind {
    if note_id.trim().to_lowercase().starts_with("en-") {
        NoteKind::Endnote
    } else {
        NoteKind::Footnote
    }
}

pub fn replace_frozen_refs(text: &str, endnote_mode: EndnoteMode) -> String { ... }

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EndnoteMode { Legacy, Standard }

pub fn extract_note_refs(text: &str) -> Vec<NoteRef> { ... }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NoteRef {
    pub kind: NoteKind,
    pub note_id: String,
}
```

**测试重点**：`cleanup_nested_note_refs` 用 Python 中触发过的真实嵌套样本作 fixture，确保算法完全一致。

---

### T7: `note_modes.rs`（0.25 天）

**Python 源**：`FNM_RE/shared/note_modes.py`（77 行）

**Rust 实现**：

```rust
// src/note_modes.rs
use crate::types::NoteMode;
use once_cell::sync::Lazy;
use std::collections::HashMap;

static MODE_TO_DB_ALIAS: Lazy<HashMap<&'static str, &'static str>> = Lazy::new(|| {
    [
        ("footnote_primary", "footnote_primary"),
        ("chapter_endnote_primary", "chapter_endnotes"),
        ("book_endnote_bound", "book_endnotes"),
        ("no_notes", "body_only"),
    ].iter().cloned().collect()
});

static DB_ALIAS_TO_MODE: Lazy<HashMap<&'static str, NoteMode>> = Lazy::new(|| {
    [
        ("footnote_primary", NoteMode::FootnotePrimary),
        ("chapter_endnotes", NoteMode::ChapterEndnotePrimary),
        ("book_endnotes", NoteMode::BookEndnoteBound),
        ("body_only", NoteMode::NoNotes),
    ].iter().cloned().collect()
});

pub fn to_db_alias(canonical: &str) -> &'static str {
    MODE_TO_DB_ALIAS.get(canonical.trim()).copied().unwrap_or("mixed_or_unclear")
}

pub fn from_db_alias(alias: &str) -> Option<NoteMode> {
    DB_ALIAS_TO_MODE.get(alias.trim()).copied()
}

pub fn new_chapter_mode_summary() -> HashMap<&'static str, i64> {
    ["footnote_primary", "chapter_endnotes", "book_endnotes", "body_only", "mixed_or_unclear"]
        .iter().map(|k| (*k, 0)).collect()
}

pub fn increment_chapter_mode_summary(summary: &mut HashMap<&'static str, i64>, canonical: &str) {
    let bucket = to_db_alias(canonical);
    *summary.entry(bucket).or_insert(0) += 1;
}
```

---

### T8: `anchor_kind.rs`（0.5 天）

**Python 源**：`FNM_RE/shared/anchors.py` 的子集：
- `resolve_anchor_kind` (line 113)
- `looks_like_year_marker` (line 102)
- 所有 regex 常量（_HTML_SUP_RE 等 14 个）

**不 port 的部分**：`scan_anchor_markers`、`page_body_paragraphs` 等复杂业务（留给 `fnm-phase3`）

**Rust 实现**：

```rust
// src/anchor_kind.rs
use crate::types::AnchorKind;
use std::collections::HashSet;

pub fn resolve_anchor_kind(
    has_page_footnote_band: bool,
    normalized_marker: &str,
    chapter_endnote_markers: Option<&HashSet<i64>>,
    pattern: &str,
) -> AnchorKind {
    let pat = pattern.trim();
    if pat == "bracket" || pat == "broken_left_bracket" {
        return if has_page_footnote_band { AnchorKind::Footnote } else { AnchorKind::Unknown };
    }
    if let Ok(n) = normalized_marker.parse::<i64>() {
        if let Some(markers) = chapter_endnote_markers {
            if markers.contains(&n) {
                return AnchorKind::Endnote;
            }
        }
    }
    if has_page_footnote_band { AnchorKind::Footnote } else { AnchorKind::Unknown }
}

pub fn looks_like_year_marker(marker: &str) -> bool {
    let m = marker.trim();
    if m.len() != 4 { return false; }
    match m.parse::<i64>() {
        Ok(v) => (1500..=2100).contains(&v),
        Err(_) => false,
    }
}

// 暴露所有 14 个 regex 常量给后续 phase crate 复用：
pub mod patterns {
    use once_cell::sync::Lazy;
    use regex::Regex;
    pub static HTML_SUP_RE: Lazy<Regex> = Lazy::new(|| ...);
    pub static LATEX_SUP_RE: Lazy<Regex> = Lazy::new(|| ...);
    pub static FOOTNOTE_REF_RE: Lazy<Regex> = Lazy::new(|| ...);
    pub static BRACKET_REF_RE: Lazy<Regex> = Lazy::new(|| ...);
    // ...
}
```

**Parity 测试**：覆盖 `resolve_anchor_kind` 的所有 7 个判定分支：
- bracket + footnote_band → footnote
- bracket + 无 footnote_band → unknown
- 数字 + endnote_markers 命中 → endnote
- 数字 + endnote_markers 未命中 + footnote_band → footnote
- 数字 + endnote_markers 未命中 + 无 footnote_band → unknown
- 非数字 + footnote_band → footnote
- 非数字 + 无 footnote_band → unknown

---

### T9: `marker_seq.rs` + `chapters.rs` + `note_lookup.rs` + `review.rs` + `review_overrides.rs`（0.5 天）

5 个小模块，每个 50 行内的工具函数。每个模块按 Python 源 1:1 翻译，逐函数加 parity 测试。

**关键函数**：
- `marker_seq::infer_marker_sequence(markers: &[i64]) -> SequenceInfo`：判断 marker 序列是不是 1-based 连续、是否有跳号
- `chapters::is_fallback_chapter_id(s: &str) -> bool`：判断 chapter_id 是不是 `"ch-fallback-*"` 前缀
- `chapters::is_toc_chapter_id(s: &str) -> bool`：判断 chapter_id 是不是 `"toc-ch-*"` 前缀
- `note_lookup::build_note_item_lookup(items: &[NoteItemRecord]) -> NoteLookup`：构建 `(chapter_id, kind, marker) → note_item_id` 的索引
- `review_overrides::group_review_overrides(raw: &Value) -> GroupedOverrides`：把外部 review_overrides JSON 按 scope 分组（page/chapter/anchor/link/note_item）

---

### T10: `segments.rs` + `segment_codec.rs`（1 天）

**Python 源**：`shared/segments.py`、`shared/segment_codec.py`

`segment_codec` 是 DB 存储用的短键名压缩格式（`{"p": 1, "ps": [{"o": 0, "k": "body", "s": "..."}]}`），反序列化时还原为完整 dict。

**Rust 公开 API**：

```rust
// src/segment_codec.rs
use serde_json::Value;

pub fn serialize_segments(segments: &[Segment]) -> Vec<Value> {
    segments.iter().map(serialize_segment).collect()
}

pub fn deserialize_segments_to_dicts(raw: &[Value]) -> Vec<Value> {
    raw.iter().map(deserialize_segment_to_dict).collect()
}

fn serialize_segment(seg: &Segment) -> Value { /* 按 Python _serialize_segment */ }
fn deserialize_segment_to_dict(v: &Value) -> Value { /* 按 Python _deserialize_segment_to_dict */ }
```

**测试重点**：
- 编码 → 解码 round-trip 必须 100% 恢复原始字段
- 旧格式（带 `paragraphs` 而非 `ps`）也要兼容（Python 端有兼容逻辑）

---

### T11: `ref_rewriter.rs` + `token_counter.rs` + `export_constants.rs`（1 天）

**`ref_rewriter`**：根据 phase4 的 `frozen_refs` 把段落中的 `{{NOTE_REF:...}}` token 改写为 markdown 脚注 `[^id]`。Python 源 270 行，主要是状态机扫描。

**`token_counter`**：用 `tokenizers` crate 加载 `o200k_base` 或 `cl100k_base`（GPT-4 tokenizer），计数函数与 Python `tiktoken` 输出 1:1 对齐。

```rust
// src/token_counter.rs
use tokenizers::Tokenizer;
use once_cell::sync::Lazy;

static O200K_BASE: Lazy<Tokenizer> = Lazy::new(|| {
    Tokenizer::from_pretrained("Xenova/gpt-4o", None).expect("load tokenizer")
});

pub fn count_tokens(text: &str) -> usize {
    O200K_BASE.encode(text, false).map(|e| e.len()).unwrap_or(0)
}
```

**关键约束**：`count_tokens` 对同一字符串的输出必须与 Python `tiktoken.encoding_for_model("gpt-4o").encode(text)` 完全一致。Parity fixture 至少覆盖 100 个真实段落。

**`export_constants`**：纯常量，按 Python 1:1 翻译为 Rust `pub const`。

---

### T12: DB 层（1.5 天）

**目标**：提供 `Repository` trait，封装所有 phase 间通信的表读写。后续 phase crate 通过 `Repository` 调用 SQLite，不直接拼 SQL。

**架构**：

```rust
// src/db/mod.rs
pub mod pool;
pub mod schema;
pub mod repository;

pub use pool::SqlitePool;
pub use repository::{Repository, SqliteRepository};
```

**Trait 定义**：

```rust
// src/db/repository.rs
use crate::records::*;
use anyhow::Result;

#[allow(async_fn_in_trait)]
pub trait Repository {
    // ── Phase 1 ──
    fn list_fnm_pages(&self, doc_id: &str) -> Result<Vec<PagePartitionRecord>>;
    fn list_fnm_chapters(&self, doc_id: &str) -> Result<Vec<ChapterRecord>>;
    fn list_fnm_section_heads(&self, doc_id: &str) -> Result<Vec<SectionHeadRecord>>;
    fn list_fnm_heading_candidates(&self, doc_id: &str) -> Result<Vec<HeadingCandidate>>;
    fn replace_fnm_phase1_products(&self, doc_id: &str, payload: &Phase1Products) -> Result<()>;

    // ── Phase 2 ──
    fn list_fnm_note_regions(&self, doc_id: &str) -> Result<Vec<NoteRegionRecord>>;
    fn list_fnm_note_items(&self, doc_id: &str) -> Result<Vec<NoteItemRecord>>;
    fn list_fnm_chapter_note_modes(&self, doc_id: &str) -> Result<Vec<ChapterNoteModeRecord>>;
    fn replace_fnm_phase2_products(&self, doc_id: &str, payload: &Phase2Products) -> Result<()>;

    // ── Phase 3 ──
    fn list_fnm_body_anchors(&self, doc_id: &str) -> Result<Vec<BodyAnchorRecord>>;
    fn list_fnm_note_links(&self, doc_id: &str) -> Result<Vec<NoteLinkRecord>>;
    fn replace_fnm_phase3_products(&self, doc_id: &str, payload: &Phase3Products) -> Result<()>;

    // ── Phase 4-6 ──（同上，按 fnm_translation_units / fnm_chapter_markdowns / fnm_export_chapters 等表展开）

    // ── Review overrides（贯穿 phase）──
    fn list_fnm_review_overrides(&self, doc_id: &str) -> Result<Vec<ReviewOverrideRecord>>;
    fn upsert_fnm_review_overrides(&self, doc_id: &str, rows: &[ReviewOverrideRecord]) -> Result<()>;

    // ── Pipeline metadata ──
    fn get_pipeline_state(&self, doc_id: &str) -> Result<PipelineState>;
    fn set_pipeline_state(&self, doc_id: &str, state: PipelineState) -> Result<()>;
}
```

**Phase products payload**：

```rust
pub struct Phase1Products {
    pub pages: Vec<PagePartitionRecord>,
    pub chapters: Vec<ChapterRecord>,
    pub heading_candidates: Vec<HeadingCandidate>,
    pub section_heads: Vec<SectionHeadRecord>,
}

pub struct Phase2Products {
    pub pages: Vec<PagePartitionRecord>,
    pub chapters: Vec<ChapterRecord>,
    pub heading_candidates: Vec<HeadingCandidate>,
    pub section_heads: Vec<SectionHeadRecord>,
    pub note_regions: Vec<NoteRegionRecord>,
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    pub note_items: Vec<NoteItemRecord>,
}

// 等等
```

**SQLite 实现**：

```rust
// src/db/repository.rs
pub struct SqliteRepository {
    pool: SqlitePool,
}

impl SqliteRepository {
    pub fn open(db_path: &str) -> Result<Self> {
        let pool = SqlitePool::new(db_path)?;
        Ok(Self { pool })
    }
}

impl Repository for SqliteRepository {
    fn list_fnm_chapters(&self, doc_id: &str) -> Result<Vec<ChapterRecord>> {
        let conn = self.pool.get()?;
        let mut stmt = conn.prepare(
            "SELECT chapter_id, title, start_page, end_page, page_nos_json, source, boundary_state
             FROM fnm_chapters
             WHERE doc_id = ?
             ORDER BY start_page"
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(ChapterRecord {
                chapter_id: row.get(0)?,
                title: row.get(1)?,
                start_page: row.get(2)?,
                end_page: row.get(3)?,
                pages: serde_json::from_str(&row.get::<_, String>(4)?).unwrap_or_default(),
                source: ChapterSource::from_str(&row.get::<_, String>(5)?)
                    .unwrap_or(ChapterSource::Fallback),
                boundary_state: BoundaryState::from_str(&row.get::<_, String>(6)?)
                    .unwrap_or(BoundaryState::Ready),
            })
        })?;
        rows.collect::<Result<_, _>>().map_err(Into::into)
    }
    // ... 其余方法
}
```

**Schema migrations**：

```sql
-- migrations/0001_initial.sql
-- 从 persistence/sqlite_schema.py 复制以下表（不修改、不重命名）：
-- fnm_pages, fnm_chapters, fnm_section_heads, fnm_heading_candidates,
-- fnm_note_regions, fnm_note_items, fnm_chapter_note_modes, fnm_chapter_body_pages,
-- fnm_body_anchors, fnm_note_links, fnm_review_overrides,
-- fnm_translation_units, fnm_structure_reviews,
-- fnm_chapter_markdowns, fnm_export_chapters, fnm_export_audit,
-- fnm_diagnostic_pages, fnm_diagnostic_notes
```

**测试**：
- 单元测试：用 `tempfile::NamedTempFile` 创建临时 SQLite，跑增删改查
- Parity 测试：Python 端写一条记录、Rust 端读出来对比

---

## 整体验收 checklist

### 代码质量
- [ ] `cargo build --release` 通过
- [ ] `cargo clippy --all-targets -- -D warnings` 通过
- [ ] `cargo fmt --check` 通过
- [ ] `cargo test --all` 所有测试通过
- [ ] Code coverage ≥ 85%（用 `cargo-llvm-cov`）

### Parity 测试覆盖
- [ ] 12 个 enum（PageRole 等）全部有 parity 测试
- [ ] 37 个 Record struct 全部有 round-trip 测试
- [ ] `normalize_note_marker`：≥ 50 个 fixture case
- [ ] `cleanup_nested_note_refs`：≥ 20 个真实嵌套样本
- [ ] `resolve_anchor_kind`：覆盖全 7 个判定分支
- [ ] `count_tokens`：≥ 100 个真实段落，与 tiktoken 输出 byte-equal
- [ ] `segment_codec`：旧/新格式 round-trip 都通过
- [ ] 所有 `note_modes` 双向映射函数有测试

### DB 集成
- [ ] 18 张 `fnm_*` 表的 `list_*` 和 `replace_*` 方法都实现
- [ ] 同一 doc_id 的 Python 输出可被 Rust 读取（用 Biopolitics 真实 DB 做测试）
- [ ] Rust 写入的 phase1 产物可被 Python `mainline_repo._repo_chapter_record` 读取

### 性能基线
- [ ] `cargo bench` 提供 `normalize_note_marker` 的基准（与 Python 同函数对比，目标 ≥ 10x）
- [ ] `count_tokens` 性能基准（目标 ≥ 20x Python tiktoken）

### 文档
- [ ] `README.md` 说明：如何 build、如何跑 parity 测试、如何添加新的 parity fixture
- [ ] 每个 `pub fn` 有 doc comment，说明与 Python 哪个函数对应
- [ ] `CHANGELOG.md` 记录每个 task 的完成

---

## 工程纪律

### 1. 每个任务一个 PR

每个 T1–T12 都是独立 PR。PR 必须：
- 通过 CI（build + clippy + fmt + test）
- 包含 parity fixture 生成代码（在 `tools/gen_parity_fixtures.py` 加新段落）
- 包含对应的 parity 测试（`tests/parity/*.rs`）

### 2. Parity 测试是验收门

**任何 Rust 公开函数的输出必须 byte-equal 匹配 Python 同名函数的输出**。如果不一致，要么改 Rust 实现，要么把 Python 行为视为 bug 标记到 `FNM_RE_REFACTOR.md` 第二轮清单（不是默默调整 Rust）。

### 3. 不引入新概念

`fnm-core` 严格只翻译现有 Python 实现。**不引入新的抽象、不重构 API 形状、不"顺手优化"**。优化在 phase crate 实施时再做。

### 4. Issue 9 的类型升级延续

Python 侧已经把 `NoteItemRecord.note_kind` 从 `str=""` 升级为 `NoteKind` Literal。Rust 这边的 `NoteItemRecord` 必须用 `pub note_kind: NoteKind`，**不要回退**为 `String`。其他 Record 同样：所有 `note_kind`/`anchor_kind`/`note_mode`/`page_role` 字段都用强类型 enum。

### 5. 不动 SQLite schema

`fnm-core` 嵌入的 `migrations/0001_initial.sql` **必须与 `persistence/sqlite_schema.py` byte-equal**。如果需要改 schema，要在 `persistence/` 侧改，Rust 这边跟进。

### 6. PR 模板

每个 PR 描述里必须包含：

```markdown
## Task
T<N>: <task title>

## Python 源
- FNM_RE/<path>:<line ranges>

## 新增 Rust 模块
- fnm-core/src/<module>.rs

## Parity 测试
- tests/parity/<test>.rs
- fixture 数量：<N> cases

## 验收
- [ ] cargo test --all 通过
- [ ] clippy clean
- [ ] fmt check 通过
- [ ] parity fixture 是用 Python 真实输出生成的（不是手写）
```

---

## 下一步（T1 启动 checklist）

接手 T1 后立刻可以做的事：

1. 在仓库根创建 `fnm_re_rs/` 目录，里面建 Cargo workspace
2. 写 `fnm_re_rs/Cargo.toml`（workspace 文件，先只列 `fnm-core` 作为 member）
3. 写 `fnm_re_rs/fnm-core/Cargo.toml`（按本文档"基础设施"段的模板）
4. 写 `fnm_re_rs/fnm-core/src/lib.rs`（先放占位模块声明）
5. 写 `.github/workflows/rust.yml`
6. 写 `tools/gen_parity_fixtures.py`（先放 1 个占位 case，T2 起填充）
7. 写 `fnm_re_rs/README.md`，包含：
   - 如何构建：`cd fnm_re_rs && cargo build`
   - 如何跑测试：`cargo test --all`
   - 如何生成 parity fixture：`python tools/gen_parity_fixtures.py`
8. 提 PR，验收 checklist：
   - [ ] CI 全绿
   - [ ] `cargo test` 输出 `0 passed; 0 failed`（说明骨架就绪）

完成 T1 后，T2-T11 各自独立可做。T12（DB 层）建议放最后，因为它需要前面所有 Record struct 就绪。
