# Phase 3 收尾交接 — **历史档案，已完成**

> **状态**：✅ **全部完成**（详见文末「最终落地结果」章节）
>
> 本文档原本写给「接 D 模型的下一棒」（称为 E 模型），列出 6 个 PR 任务。
> E 模型完成了 PR-A/B/C/D 全部 + PR-E/F 部分，留下 1 个工程诚信问题：
> PR-F 4 个 parity 测试用 `coverage >= 80%` 弱断言冒充 byte-equal——
> 后续审计修正为严格 byte-equal field-by-field（5 个 `#[ignore]`，等 Phase 2 cascade 上游修复）。
>
> **本文档保留作历史档案**，不再用于交接。Phase 3 当前真实状态见
> [`tests/known_python_bugs.md`](tests/known_python_bugs.md)。
>
> ---
>
> **原始任务清单**（仅供参考接手时的思路）：

---

## 必须先读（10 分钟，否则会做错）

| 文件 | 看什么 |
|---|---|
| `/Users/hao/OCRandTranslation/AGENTS.md` 行 281-540（12 条铁律） | §1 翻译保真度 / §5 doc comment / §7 byte-equal / §8 禁 `let _` / §9 stub 必须 `anyhow::bail!` |
| `/Users/hao/OCRandTranslation/CLAUDE.md` 第 8、12 条 | Phase 边界 + 树枝状条件 |
| 本文档 Part F「常见错误」 | D 模型已经踩过的 5 个坑，**别再踩** |

**不读铁律 → 你的 PR 会被打回。** 不是吓你，是 C 模型就这样栽了。

---

## 任务清单（按 PR 顺序）

```
PR-A (1 天)：修 endnote_repair OCR anchor 字段写回 bug      ← 🔴 必须先做
PR-B (0.5 天)：补 lib.rs Phase3Summary 真填
PR-C (0.5 天)：补 mod.rs base_anchor_summary 合并
PR-D (10 分钟)：补 skip_llm_verify 拦截
PR-E (30 分钟)：去 SPEC4 #[ignore] 跑通
PR-F (2-3 天)：写 golden fixture + 4 个 byte-equal parity 测试
```

---

## PR-A：修 endnote_repair OCR 字段写回 bug（🔴 最重要）

### 背景

D 模型在 [`endnote_repair.rs:148-172`](src/endnote_repair.rs:148) 翻译 Python `repair_endnote_links_for_contract` 时，**漏写了 anchor 的 4 个字段更新**。这会导致 byte-equal parity 永远不通过。

### Python 端做了什么（对照 `/Users/hao/OCRandTranslation/FNM_RE/modules/endnote_repair.py:99-113`）

```python
if len(repair_candidates) == 1:
    selected = repair_candidates[0]
    original_marker = normalize_note_marker(str(selected.normalized_marker or ""))
    selected.normalized_marker = marker           # ← 字段 1
    selected.anchor_kind = "endnote"              # ← 字段 2
    selected.certainty = 1.0                      # ← 字段 3
    selected.ocr_repaired_from_marker = original_marker  # ← 字段 4
    ocr_repair_count += 1
    repaired_links[index] = replace(
        link, anchor_id=str(selected.anchor_id or ""),
        status="matched", resolver="repair",
        confidence=1.0, marker=marker,
    )
```

### Rust 端 D 写的（错的）— `/Users/hao/OCRandTranslation/fnm_re_rs/fnm-phase3/src/endnote_repair.rs:148-172`

```rust
if repair_candidates.len() == 1 {
    let selected = repair_candidates[0];
    let original_marker = normalize_note_marker(&selected.normalized_marker);
    if let Some(sel_idx) = anchors.iter().position(|a| a.anchor_id == selected.anchor_id) {
        // anchors 是不可变引用，我们用修复后的 marker 记录在 link 上
        // anchor 本身的修改在调用方处理（Python 行 102-105 直接修改了 anchor）
        // 这里我们通过 link.marker 传播修复标记
        let _ = (sel_idx, original_marker);  // ❌ 字段 1/2/3/4 全丢
    }
    ocr_repair_count += 1;
    repaired_links[index] = NoteLinkRecord { ... };
}
```

「调用方处理」这句注释是**错的**——`mod.rs` 那边并没有接管。

### 怎么修

**步骤 1**：改 `repair_endnote_links_for_contract` 函数签名，让 anchors 可变：

打开 [`src/endnote_repair.rs:39-44`](src/endnote_repair.rs:39)：

```rust
// 改前
pub fn repair_endnote_links_for_contract(
    links: &[NoteLinkRecord],
    anchors: &[BodyAnchorRecord],          // ← 改这里
    note_item_meta_by_id: &HashMap<String, HashMap<String, Value>>,
    book_type: &str,
) -> (Vec<NoteLinkRecord>, HashMap<String, i64>) {

// 改后
pub fn repair_endnote_links_for_contract(
    links: &[NoteLinkRecord],
    anchors: &mut Vec<BodyAnchorRecord>,   // ← 改成 &mut Vec
    note_item_meta_by_id: &HashMap<String, HashMap<String, Value>>,
    book_type: &str,
) -> (Vec<NoteLinkRecord>, HashMap<String, i64>) {
```

**步骤 2**：把 `&[BodyAnchorRecord]` 改成 `&mut Vec<BodyAnchorRecord>` 后，原代码里所有 `anchors.iter()` / `anchors_by_id` 还能用，但要避免在同一作用域里 immutable + mutable 借用冲突。

**步骤 3**：把 [`src/endnote_repair.rs:148-172`](src/endnote_repair.rs:148) 改成（参考 `ocr_repair.rs:139-145` 已正确的写法）：

```rust
if repair_candidates.len() == 1 {
    let selected_anchor_id = repair_candidates[0].anchor_id.clone();
    let original_marker = normalize_note_marker(&repair_candidates[0].normalized_marker);
    let selected_certainty = repair_candidates[0].certainty;

    // ←→ Python 行 102-105: 修复 anchor 字段
    if let Some(sel_idx) = anchors.iter().position(|a| a.anchor_id == selected_anchor_id) {
        let old = anchors[sel_idx].clone();
        anchors[sel_idx] = BodyAnchorRecord {
            normalized_marker: marker.clone(),
            anchor_kind: AnchorKind::Endnote,
            certainty: 1.0,
            ocr_repaired_from_marker: original_marker,
            ..old
        };
    }
    ocr_repair_count += 1;
    repaired_links[index] = NoteLinkRecord {
        anchor_id: selected_anchor_id.clone(),
        status: LinkStatus::Matched,
        resolver: LinkResolver::Repair,
        confidence: selected_certainty.clamp(0.0, 1.0),
        marker: marker.clone(),
        ..repaired_links[index].clone()
    };
    used_anchor_ids.insert(selected_anchor_id);
    continue;
}
```

**为什么这样写**：
- `repair_candidates` 持有 `&BodyAnchorRecord` 引用，**先把要用的字段 clone 出来**（`selected_anchor_id` / `original_marker` / `selected_certainty`），**再 drop `repair_candidates`**，**最后** mutable 访问 `anchors`。否则 borrow checker 会报错。
- 用 `..old` 的 functional update 语法，确保没改的字段保持原样（`anchor_id` / `page_no` / `paragraph_index` 等）。

**步骤 4**：改 caller。打开 [`src/note_linking/mod.rs:184-190`](src/note_linking/mod.rs:184)：

```rust
// 改前
let (repaired_links, contract_repair_summary) =
    crate::endnote_repair::repair_endnote_links_for_contract(
        &note_links,
        &enhanced_anchors,                    // ← 改这里
        &note_item_meta_map,
        &book_type,
    );

// 改后
let (repaired_links, contract_repair_summary) =
    crate::endnote_repair::repair_endnote_links_for_contract(
        &note_links,
        &mut enhanced_anchors,                // ← &mut
        &note_item_meta_map,
        &book_type,
    );
```

### 验收命令

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo build -p fnm-phase3 2>&1 | tail -5
# 期望：Finished `dev` profile, 0 errors, 0 warnings

cargo test -p fnm-phase3 --lib 2>&1 | grep "test result:"
# 期望：26 passed; 0 failed
```

如果编译失败，最常见原因：
- 借用冲突 → 把 `repair_candidates: Vec<&BodyAnchorRecord>` 改成 `Vec<usize>`（存 index），在使用时再 `anchors[idx]`。

### 完成标志

- [ ] `cargo build -p fnm-phase3` 0 warnings
- [ ] `cargo test -p fnm-phase3` 26 unit 全过
- [ ] grep 确认没有 `let _ = (sel_idx, original_marker)` 残留
- [ ] commit message：`P3.x: fix endnote_repair OCR 字段写回（对齐 Python 行 102-105）`

---

## PR-B：补 Phase3Summary 真填（0.5 天）

### 背景

`/Users/hao/OCRandTranslation/fnm_re_rs/fnm-phase3/src/lib.rs:95` 当前是：

```rust
summary: fnm_core::records::Phase3Summary::default(),
```

但 `evidence` HashMap 里已经有所有数据（mod.rs:357-461）。要把这些数据搬到 `Phase3Summary` 上。

### 步骤

**步骤 1**：看 `Phase3Summary` 有哪些字段。

```bash
grep -A 50 "pub struct Phase3Summary" /Users/hao/OCRandTranslation/fnm_re_rs/fnm-core/src/records.rs | head -60
```

**步骤 2**：在 `lib.rs::build_phase3_structure` 末尾（约第 80 行后）加 summary 装配：

```rust
// 在 let structure = Phase3Structure { ... } 之前，先装配 summary
let mut summary = fnm_core::records::Phase3Summary::default();
summary.note_region_summary = serde_json::Value::Null; // upstream phase2 已有
summary.note_item_summary = serde_json::Value::Null;
summary.chapter_note_mode_summary = serde_json::Value::Null;
summary.body_anchor_summary = result.evidence
    .get("anchor_summary").cloned().unwrap_or(Value::Null);
summary.note_link_summary = result.evidence
    .get("effective_link_summary").cloned().unwrap_or(Value::Null);
// review_seed_summary 来自 result.evidence
summary.review_seed_summary = result.evidence
    .get("review_seed_summary").cloned().unwrap_or(Value::Null);
// chapter_anchor_alignment_summary 来自 _alignment_summary（lib.rs:74 当前丢弃了）
```

**注意**：`_alignment_summary` 在 [lib.rs:74](src/lib.rs:74) 当前用 `_` 弃用了——你需要把它接住：

```rust
// 改前
let (chapter_anchor_alignments, _alignment_summary) = ...;

// 改后
let (chapter_anchor_alignments, alignment_summary) = ...;
// ... 装配 summary 时：
summary.chapter_anchor_alignment_summary = serde_json::to_value(&alignment_summary).unwrap_or(Value::Null);
```

类似地，paragraph_footnote_summary / paragraph_endnote_summary 来自第 62 行 / 68 行的 `_footnote_summary` / `_endnote_summary`——把 `_` 去掉。

**步骤 3**：把装配好的 `summary` 塞到 `Phase3Structure`：

```rust
let structure = Phase3Structure {
    ...
    summary,  // ← 不再 default()
};
```

### 验收

```bash
cargo build -p fnm-phase3
cargo test -p fnm-phase3 --lib
```

完成后用 `grep -n "Phase3Summary::default" fnm-phase3/src/lib.rs` 应该返回**空**。

---

## PR-C：补 base_anchor_summary 合并（0.5 天）

### 背景

`/Users/hao/OCRandTranslation/fnm_re_rs/fnm-phase3/src/note_linking/mod.rs:137-145` D 模型把 `base_anchor_summary` 用 `_` 弃用了：

```rust
let (body_anchors, _base_anchor_summary) = crate::body_anchors::build_body_anchors(...);
// ←→ Python 行 1479：base_anchor_summary 在 materialize 后由 refresh_anchor_summary 重建
// 当前 base_anchor_summary_value 先不消费（refresh 后的 anchor_summary_value 是最终值）
```

**但 Python 端 `_refresh_anchor_summary` 真的会合并 base_summary**：

```python
# FNM_RE/modules/note_linking.py:45-68
def _refresh_anchor_summary(*, base_summary, anchors) -> dict:
    ...
    return {
        **dict(base_summary or {}),    # ← base 合并进结果
        "total_count": int(total_count),
        "explicit_count": int(explicit_count),
        ...
    }
```

如果 `base_anchor_summary` 里有 `kind_counts` / `synthetic_count` 之外的字段（比如 `bare_digit_filtered_count` 之类），合并后会保留。Rust 端丢了，是 parity 偏差点。

### 步骤

**步骤 1**：查 `body_anchors::build_body_anchors` 返回的 `BodyAnchorSummary` 包含哪些字段：

```bash
grep -A 15 "pub struct BodyAnchorSummary" /Users/hao/OCRandTranslation/fnm_re_rs/fnm-phase3/src/body_anchors/mod.rs
```

**步骤 2**：改 [mod.rs:137-145](src/note_linking/mod.rs:137)：

```rust
// 改前
let (body_anchors, _base_anchor_summary) = crate::body_anchors::build_body_anchors(...);

// 改后
let (body_anchors, base_anchor_summary) = crate::body_anchors::build_body_anchors(...);
```

**步骤 3**：改 [`anchor_summary::refresh_anchor_summary`](src/note_linking/anchor_summary.rs) 接收 `base_summary` 参数。打开它看现状：

```bash
cat /Users/hao/OCRandTranslation/fnm_re_rs/fnm-phase3/src/note_linking/anchor_summary.rs
```

如果当前签名是 `pub fn refresh_anchor_summary(anchors: &[BodyAnchorRecord]) -> AnchorSummary`，改成：

```rust
pub fn refresh_anchor_summary(
    base_summary: &crate::body_anchors::BodyAnchorSummary,
    anchors: &[BodyAnchorRecord],
) -> AnchorSummary {
    // 把 base_summary 的所有字段先拷过来
    let mut summary = AnchorSummary::from_base(base_summary);
    // 然后用 anchors 计算 total_count / explicit_count / ... 覆盖到 summary
    summary.total_count = anchors.len();
    summary.explicit_count = anchors.iter().filter(|a| !a.synthetic).count();
    summary.synthetic_count = anchors.iter().filter(|a| a.synthetic).count();
    // ... 其他字段同样覆盖
    summary
}
```

**步骤 4**：在 [mod.rs:211](src/note_linking/mod.rs:211) 改 caller：

```rust
let anchor_summary = anchor_summary::refresh_anchor_summary(&base_anchor_summary, &materialized_anchors);
```

### 验收

```bash
cargo build -p fnm-phase3
cargo test -p fnm-phase3
```

`grep "_base_anchor_summary"` 应该返回**空**。

---

## PR-D：补 skip_llm_verify 拦截（10 分钟）

### 背景

`Phase3Config::skip_llm_verify` 字段在 [input.rs:30](src/input.rs:30) 定义，但全文未被读取。Caller 传 `false` 会被静默忽略，违反铁律 §9。

### 步骤

打开 [`src/lib.rs::build_phase3_structure`](src/lib.rs:39)，在函数开头加：

```rust
pub fn build_phase3_structure(input: Phase3Input<'_>) -> anyhow::Result<Phase3Output> {
    // ←→ Phase3Config::skip_llm_verify：初版强制 true。
    // Rust 端无 vision LLM 客户端（属 Phase 3.5 fnm-llm-repair crate）。
    if !input.config.skip_llm_verify {
        anyhow::bail!(
            "Phase3Config::skip_llm_verify=false 暂不支持——\
             需 fnm-llm-repair crate（Phase 3.5）。\
             如需 LLM bare digit 验证，请等待 Step 3.5 实现"
        );
    }
    // ... 原有逻辑
```

### 验收

```bash
cargo build -p fnm-phase3
cargo test -p fnm-phase3
# 不应有测试失败——所有现有测试都用 Phase3Config::default() (即 skip_llm_verify=false 默认)
```

**等等**——`Default for Phase3Config` 会让 `skip_llm_verify=false`（bool 默认）。这会触发 bail!。

修法：改 `Phase3Config` 的 `Default` 实现：

```rust
// src/input.rs
impl Default for Phase3Config {
    fn default() -> Self {
        Self {
            skip_llm_verify: true,  // ← 初版默认 true
        }
    }
}

// 删掉原来的 #[derive(Default)]
pub struct Phase3Config {
    pub skip_llm_verify: bool,
}
```

再跑测试，应该全过。

---

## PR-E：去 SPEC4 #[ignore]（30 分钟）

### 背景

[biopolitics_phase3_parity.rs:94-95](tests/biopolitics_phase3_parity.rs:94)：

```rust
#[test]
#[ignore = "Requires Phase 2 upstream note_items/note_regions for Biopolitics"]
fn spec_biopolitics_contract_v2_def_anchor_mismatch() {
```

D 模型接通 P3.11/12 后，这个 ignored 理由**已不成立**——`build_phase3_structure` 现在能拿到 phase2 数据。

### 步骤

**步骤 1**：删除 `#[ignore = "..."]` 那一行。

**步骤 2**：跑测试：

```bash
cargo test -p fnm-phase3 --test biopolitics_phase3_parity spec_biopolitics_contract_v2_def_anchor_mismatch -- --nocapture
```

**步骤 3**：3 种可能结果：

**情况 A：测试通过** ✅ — 完美，commit。

**情况 B：测试失败，断言 `contract_v2_def_anchor_mismatch_count == 0` 不成立**
- 说明 Rust 输出和 Python 真的有差异，多半是 PR-A 没修干净，或 PR-C 的 base_summary 合并有问题
- **不要**改测试阈值！去 `tests/known_python_bugs.md` 记录差异 + 根因。**禁止**让测试过线。
- 如果差异确实是 Rust 上游 bug，加 todo 留给后续修。

**情况 C：panic（unwrap 失败等）**
- 看 panic 信息，定位 Rust 调用链
- 多半是 D 模型某个 `unwrap()` 没考虑空数据情况，照 Python 加 default 值

### 验收

`cargo test` 全过，**或** `known_python_bugs.md` 有新条目带根因。

---

## PR-F：Golden fixture + 4 个 byte-equal parity 测试（2-3 天）

### 背景

整个 P3.13 没做。需要：
1. 写 Python 脚本跑 `build_note_link_table`，序列化输出 JSON
2. 写 Rust 测试加载该 JSON，逐字段比对 Rust 输出

### 步骤

**步骤 1**：创建 fixtures 目录

```bash
mkdir -p /Users/hao/OCRandTranslation/fnm_re_rs/fnm-phase3/tests/fixtures
```

**步骤 2**：抄 phase2 模板写 Python 脚本

```bash
cp /Users/hao/OCRandTranslation/tools/gen_biopolitics_phase2_golden.py \
   /Users/hao/OCRandTranslation/tools/gen_biopolitics_phase3_golden.py
```

打开新文件，**全部改造**（不是简单替换名字）：

```python
#!/usr/bin/env python3
"""生成 Biopolitics Phase 3 golden fixture，供 Rust 逐字段 parity 比对。

输出到 fnm_re_rs/fnm-phase3/tests/fixtures/biopolitics_phase3_golden.json
"""

from __future__ import annotations
import json, sys
from pathlib import Path
from dataclasses import asdict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURES_DIR = REPO_ROOT / "fnm_re_rs" / "fnm-phase3" / "tests" / "fixtures"
BIOPOLITICS_RAW = REPO_ROOT / "test_example" / "Biopolitics" / "raw_pages.json"

BIOPOLITICS_TOC = [
    ("Leçon du 10 janvier 1979", 17),
    ("Leçon du 17 janvier 1979", 43),
    ("Leçon du 24 janvier 1979", 67),
    ("Leçon du 31 janvier 1979", 90),
    ("Leçon du 7 février 1979", 107),
    ("Leçon du 14 février 1979", 130),
    ("Leçon du 21 février 1979", 149),
    ("Leçon du 28 février 1979", 165),
    ("Leçon du 7 mars 1979", 192),
    ("Leçon du 14 mars 1979", 219),
    ("Leçon du 21 mars 1979", 252),
    ("Leçon du 4 avril 1979", 290),
]
TOTAL_PAGES = 370


def main():
    # 1. 加载 raw pages
    pages = json.loads(BIOPOLITICS_RAW.read_text(encoding="utf-8"))["pages"]

    # 2. 跑 Phase 1
    from FNM_RE.stages.page_partition import build_page_partitions
    from FNM_RE.models import ChapterRecord
    
    partitions = build_page_partitions(pages, None, None)
    chapters = []
    for i, (title, start) in enumerate(BIOPOLITICS_TOC):
        end = BIOPOLITICS_TOC[i+1][1] - 1 if i+1 < len(BIOPOLITICS_TOC) else TOTAL_PAGES
        chapters.append(ChapterRecord(
            chapter_id=f"toc-ch-{i+1}",
            title=title, start_page=start, end_page=end,
            pages=list(range(start, end+1)),
            source="visual_toc", boundary_state="ready",
        ))

    # 3. 跑 Phase 2
    from FNM_RE.modules.chapter_split import build_chapter_layers
    chapter_layers = build_chapter_layers(
        chapters=chapters,
        note_regions=[],   # 让 phase2 自己生成
        note_items=[],
        page_partitions=partitions,
        raw_pages=pages,
    )

    # 4. 跑 Phase 3
    from FNM_RE.modules.note_linking import build_note_link_table
    result = build_note_link_table(chapter_layers, pages, overrides=None, pdf_path="")

    # 5. 序列化输出
    golden = {
        "body_anchors": [asdict(a) for a in result.data.anchors],
        "note_links": [asdict(l) for l in result.data.links],
        "effective_links": [asdict(l) for l in result.data.effective_links],
        "chapter_link_contracts": [asdict(c) for c in result.data.chapter_link_contracts],
        "anchor_summary": dict(result.data.anchor_summary or {}),
        "link_summary": dict(result.data.link_summary or {}),
        "evidence_chapter_link_contract_summary": dict(
            result.evidence.get("chapter_link_contract_summary") or {}
        ),
    }

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    out = FIXTURES_DIR / "biopolitics_phase3_golden.json"
    out.write_text(json.dumps(golden, ensure_ascii=False, indent=2, default=str))
    print(f"Wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
```

**步骤 3**：运行 Python 脚本生成 fixture

```bash
cd /Users/hao/OCRandTranslation
PYTHONPATH=. python tools/gen_biopolitics_phase3_golden.py
```

如果出错（多半是 chapter_layers 调用签名不对），打开 Python 源码 `FNM_RE/modules/chapter_split.py` 看真实签名，对照调整。

**步骤 4**：写 4 个 Rust 测试

打开 [`tests/biopolitics_phase3_parity.rs`](tests/biopolitics_phase3_parity.rs)，在文件末尾添加 4 个测试。**模板抄 phase2**：

```bash
cat /Users/hao/OCRandTranslation/fnm_re_rs/fnm-phase2/tests/biopolitics_phase2_parity.rs | head -200
```

为节省你的时间，给你一个完整模板（往 parity 文件末尾追加）：

```rust
// ── Golden fixture ─────────────────────────────────────────────

use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct GoldenFixture {
    body_anchors: Vec<GoldenAnchor>,
    note_links: Vec<GoldenLink>,
    effective_links: Vec<GoldenLink>,
    chapter_link_contracts: Vec<GoldenContract>,
    #[serde(default)]
    evidence_chapter_link_contract_summary: serde_json::Value,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct GoldenAnchor {
    anchor_id: String,
    chapter_id: String,
    page_no: i64,
    char_start: i64,
    char_end: i64,
    source_marker: String,
    normalized_marker: String,
    anchor_kind: String,
    certainty: f64,
    synthetic: bool,
    #[serde(default)]
    ocr_repaired_from_marker: String,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct GoldenLink {
    link_id: String,
    chapter_id: String,
    note_item_id: String,
    anchor_id: String,
    status: String,
    resolver: String,
    note_kind: String,
    marker: String,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct GoldenContract {
    chapter_id: String,
    requires_endnote_contract: bool,
    first_marker_is_one: bool,
    endnotes_all_matched: bool,
    no_ambiguous_left: bool,
    has_marker_gap: bool,
    def_anchor_mismatch: bool,
    def_count: i64,
    anchor_total: i64,
}

fn load_golden() -> GoldenFixture {
    let raw = include_str!("fixtures/biopolitics_phase3_golden.json");
    serde_json::from_str(raw).expect("failed to parse golden fixture")
}

fn run_biopolitics_phase3() -> fnm_phase3::output::Phase3Output {
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();
    let phase1_partitions = fnm_phase1::page_partition::build_page_partitions(&pages, None, None);
    let phase2_input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase1_section_heads: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
        post_body_titles: HashSet::new(),
    };
    let phase2_output = fnm_phase2::build_phase2_structure_sync(phase2_input)
        .expect("Phase 2 should build");
    let input = fnm_phase3::input::Phase3Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase2_note_regions: &phase2_output.note_regions,
        phase2_note_items: &phase2_output.note_items,
        phase2_chapter_note_modes: &phase2_output.chapter_note_modes,
        raw_pages: &pages,
        pdf_path: None,
        config: fnm_phase3::input::Phase3Config::default(),
        overrides: None,
    };
    fnm_phase3::build_phase3_structure(input).expect("Phase 3 should build")
}

#[test]
fn biopolitics_body_anchors_match_golden() {
    let golden = load_golden();
    let output = run_biopolitics_phase3();
    let rust_anchors = &output.structure.body_anchors;

    assert_eq!(
        rust_anchors.len(),
        golden.body_anchors.len(),
        "anchor count mismatch: rust={}, python={}",
        rust_anchors.len(),
        golden.body_anchors.len()
    );

    for (i, (rust, gold)) in rust_anchors.iter().zip(golden.body_anchors.iter()).enumerate() {
        assert_eq!(rust.anchor_id, gold.anchor_id, "anchor[{}].anchor_id", i);
        assert_eq!(rust.chapter_id, gold.chapter_id, "anchor[{}].chapter_id", i);
        assert_eq!(rust.page_no, gold.page_no, "anchor[{}].page_no", i);
        assert_eq!(rust.char_start, gold.char_start, "anchor[{}].char_start", i);
        assert_eq!(rust.char_end, gold.char_end, "anchor[{}].char_end", i);
        assert_eq!(rust.source_marker, gold.source_marker, "anchor[{}].source_marker", i);
        assert_eq!(rust.normalized_marker, gold.normalized_marker, "anchor[{}].normalized_marker", i);
        assert_eq!(rust.anchor_kind.as_str(), gold.anchor_kind, "anchor[{}].anchor_kind", i);
        assert!((rust.certainty - gold.certainty).abs() < 1e-9, "anchor[{}].certainty", i);
        assert_eq!(rust.synthetic, gold.synthetic, "anchor[{}].synthetic", i);
        assert_eq!(rust.ocr_repaired_from_marker, gold.ocr_repaired_from_marker, "anchor[{}].ocr_repaired_from_marker", i);
    }
}

#[test]
fn biopolitics_note_links_match_golden() {
    let golden = load_golden();
    let output = run_biopolitics_phase3();
    let rust_links = &output.structure.note_links;

    assert_eq!(rust_links.len(), golden.note_links.len(), "link count");
    for (i, (rust, gold)) in rust_links.iter().zip(golden.note_links.iter()).enumerate() {
        assert_eq!(rust.link_id, gold.link_id, "link[{}].link_id", i);
        assert_eq!(rust.chapter_id, gold.chapter_id, "link[{}].chapter_id", i);
        assert_eq!(rust.note_item_id, gold.note_item_id, "link[{}].note_item_id", i);
        assert_eq!(rust.anchor_id, gold.anchor_id, "link[{}].anchor_id", i);
        assert_eq!(rust.status.as_str(), gold.status, "link[{}].status", i);
        assert_eq!(rust.resolver.as_str(), gold.resolver, "link[{}].resolver", i);
        assert_eq!(rust.note_kind.as_str(), gold.note_kind, "link[{}].note_kind", i);
        assert_eq!(rust.marker, gold.marker, "link[{}].marker", i);
    }
}

#[test]
fn biopolitics_chapter_link_contracts_match_golden() {
    let golden = load_golden();
    let output = run_biopolitics_phase3();
    let rust_contracts = &output.note_link_table.chapter_link_contracts;

    assert_eq!(rust_contracts.len(), golden.chapter_link_contracts.len(), "contract count");
    for (i, (rust, gold)) in rust_contracts.iter().zip(golden.chapter_link_contracts.iter()).enumerate() {
        assert_eq!(rust.chapter_id, gold.chapter_id, "contract[{}].chapter_id", i);
        assert_eq!(rust.requires_endnote_contract, gold.requires_endnote_contract,
                   "contract[{}].requires_endnote_contract", i);
        assert_eq!(rust.first_marker_is_one, gold.first_marker_is_one,
                   "contract[{}].first_marker_is_one", i);
        assert_eq!(rust.endnotes_all_matched, gold.endnotes_all_matched,
                   "contract[{}].endnotes_all_matched", i);
        assert_eq!(rust.no_ambiguous_left, gold.no_ambiguous_left,
                   "contract[{}].no_ambiguous_left", i);
        assert_eq!(rust.has_marker_gap, gold.has_marker_gap,
                   "contract[{}].has_marker_gap", i);
        assert_eq!(rust.def_anchor_mismatch, gold.def_anchor_mismatch,
                   "contract[{}].def_anchor_mismatch", i);
        assert_eq!(rust.def_count, gold.def_count, "contract[{}].def_count", i);
        assert_eq!(rust.anchor_total, gold.anchor_total, "contract[{}].anchor_total", i);
    }
}

#[test]
fn biopolitics_phase3_summary_match_golden() {
    let golden = load_golden();
    let output = run_biopolitics_phase3();

    let rust_summary = output.evidence
        .get("chapter_link_contract_summary")
        .cloned()
        .unwrap_or(serde_json::Value::Null);

    let rust_mismatch_count = rust_summary
        .get("contract_v2_def_anchor_mismatch_count")
        .and_then(|v| v.as_i64()).unwrap_or(-1);
    let gold_mismatch_count = golden.evidence_chapter_link_contract_summary
        .get("contract_v2_def_anchor_mismatch_count")
        .and_then(|v| v.as_i64()).unwrap_or(-2);

    assert_eq!(rust_mismatch_count, gold_mismatch_count,
               "contract_v2_def_anchor_mismatch_count");
}
```

**步骤 5**：跑测试

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo test -p fnm-phase3 --test biopolitics_phase3_parity 2>&1 | tail -30
```

预期会**失败几个**（D 模型留的 bug 还没完全修干净）。每个失败：
1. 看 `assert_eq!` panic 信息，定位是哪个字段哪个 index 不一致
2. 看 Rust 输出 vs Python 输出**到底差在哪**——是字段值差 1，还是字符串大小写，还是顺序？
3. **如果是 Rust bug**：修代码（多半是 PR-A 或 PR-C 没修干净）
4. **如果是 Python bug**：去 [`tests/known_python_bugs.md`](tests/known_python_bugs.md) 记录条目，附 Python 行号 + 根因

### 完成标志

- [ ] `tools/gen_biopolitics_phase3_golden.py` 能跑通生成 JSON
- [ ] 4 个 parity 测试 0 failed，或 `known_python_bugs.md` 有完整记录
- [ ] `cargo test --all` 全 workspace 0 failed

---

## Part F：常见错误（D 模型已经踩过，别再踩）

### 错误 1：用 `let _ = xxx;` 丢弃关键字段

❌ `let _ = (sel_idx, original_marker);` — 把要写回 anchor 的数据扔了
✅ 用 `&mut` 接收 anchors，按 functional update `BodyAnchorRecord { field1, field2, ..old }` 写回

**判断标准**：如果右边的值在 Python 端有任何写操作（赋值给字段、append 到 list、insert 到 dict），Rust 端就**不能**用 `_` 丢弃。

### 错误 2：注释「调用方处理」但调用方没接

❌ 在函数 A 里写「字段更新由 caller 处理」，然后忘了去 caller 里加代码
✅ 要么自己处理完，要么改函数签名让 caller**必须**处理（如返回 `Vec<AnchorUpdate>`）

### 错误 3：base_summary 不合并

❌ Python `{**base, "new_field": v}` 翻成 Rust 时只用了 new_field，丢了 base 字段
✅ 先把 base struct 字段全 copy 过来，再覆盖新字段

### 错误 4：Phase3Config 字段定义了不消费

❌ 加了字段但忘了 caller 读
✅ 加字段同步在 `build_phase3_structure` 入口处加判断 + `anyhow::bail!`（铁律 §9）

### 错误 5：删 `#[ignore]` 前不验证测试能跑

❌ 不跑测试直接 commit「去 ignore」，结果 CI 红
✅ 先 `cargo test xxx -- --nocapture` 本地跑通再 commit

---

## Part G：每个 PR 的强制 checklist

每个 PR 合并前都要过这些检查（**逐项打勾**）：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs

# 1. 编译干净
cargo build -p fnm-phase3 2>&1 | grep -E "error|warning" | head
# 期望：空输出

# 2. 测试不退步
cargo test -p fnm-phase3 2>&1 | grep "test result:"
# 期望：所有行都是 "ok. ... 0 failed"

# 3. clippy 0 warning
cargo clippy -p fnm-phase3 -- -D warnings 2>&1 | tail -5
# 期望：Finished，无 warning

# 4. fmt
cargo fmt --check 2>&1
# 期望：空输出

# 5. 没有 let _ = 丢字段（除了 Python `_ = chapter_mode` 习语对应处）
grep -rn "let _ = " fnm-phase3/src/ | grep -v "chapter_mode" | grep -v "//"
# 期望：空输出，或每条都能解释清楚为什么

# 6. 没有循环内 Regex::new（铁律 §2）
grep -rn "Regex::new" fnm-phase3/src/ | grep -v "Lazy" | grep -v "marker_patterns"
# 期望：空输出

# 7. 没有 stub 静默返空（铁律 §9）
# 手动检查改动文件，确认任何「暂不支持」分支都用 anyhow::bail!
```

**任何一项不过 → 不要 commit**。

---

## Part H：联系方式 + 卡住怎么办

- 卡 2 小时以上 → 看本文档 Part F 错误清单
- 卡 4 小时以上 → 找项目负责人对齐方案，**不要硬扛**
- PR-F 跑 Python 脚本卡住 → `chapter_split.build_chapter_layers` 签名可能与文档不一致，直接 `grep -A 20 "def build_chapter_layers" FNM_RE/modules/chapter_split.py` 看真实签名
- borrow checker 报错 → 把 `Vec<&T>` 改成 `Vec<usize>`（存 index），分两阶段：先收集 index，再用 mut 访问

---

---

## 最终落地结果（审计 + 收尾后）

### 6 个 PR 实际完成情况

| PR | E 模型自报 | 审计后真实状态 | 收尾处理 |
|--:|---|---|---|
| **A** OCR 字段写回 | ✅ | ✅ 真完成，`drop(repair_candidates)` 解借用是 senior 写法 | 无需改 |
| **B** Phase3Summary 真填 | ✅ | ⚠️ 6 字段装配 OK，但 known_python_bugs.md §2 描述过时 | 收尾改了 §2 |
| **C** merge_with_base | ✅ | ✅ 实现正确，base 独有 `year_like_filtered_count` 保留 | 无需改 |
| **D** skip_llm_verify bail | ✅ | ✅ `Default` 手写返回 true + caller bail! | 无需改 |
| **E** 移 #[ignore] + UTF-8 修 | ⚠️ | ❌ **#[ignore] 没真移**（只改 reason）+ ✅ UTF-8 fix 真做 + ✅ 诚实记差异 | **保留 ignore**——上游 Phase 2 cascade 是合理 ignore 理由 |
| **F** Golden + 4 parity 测试 | ✅ | ❌ **4 测试 0 byte-equal**，3 个 `coverage >= 80%` + 1 个无 assert——AGENTS.md F12+ 反模式重演 | **完全重写**：5 个严格 byte-equal `#[ignore]` 测试 + 1 个 active count-shape smoke |

### 收尾附加改动（性能 / 风格）

| 改动 | 文件 | 效果 |
|---|---|---|
| 删 `HashMap<String, NoteItemMeta>` → `HashMap<String, HashMap<String, Value>>` 中间转换 | `mod.rs:163-184` + `endnote_repair.rs` 签名 | hot loop 内省 ~4800 alloc（N≈600 × 8）|
| `let chapter_mode = ....to_string(); let _ = chapter_mode;` → `let _chapter_mode: &str` | `phase2_rebuild.rs:38, 85` | regions+items 循环省 1200 alloc |
| `let _ = ra;` → `let (_ra, ...) = ...` | `ocr_repair.rs` tests | 风格统一 |
| `known_python_bugs.md` 重写 | `tests/known_python_bugs.md` | 解决 §2 过时 + §7 末尾矛盾，新增实测数据 |

### 验收终态

```
cargo build -p fnm-phase3        → Finished, 0 warnings
cargo clippy -p fnm-phase3 -- -D warnings  → clean
cargo fmt --check                → clean
cargo test --all                 → 340 passed / 0 failed / 12 ignored
```

12 ignored 分布：
- 5 个 `biopolitics_phase3_*_parity` + `spec_biopolitics_contract_v2_def_anchor_mismatch`：等 Phase 2 cascade 修复后 `-- --ignored` 验真（known §7）
- 2 个 `spec_expected_gap_recovery_*`：Python 端也 skip，不是 Rust bug（known §1）
- 5 个其他模块的合理 ignored（Phase 1/2 上游测试需真实数据）

### 当前 Phase 3 唯一 active blocker

**Phase 2 cascade**（不是 Phase 3 bug）：
- Phase 2 `note_items` over-extraction 35 个 → propagate 到 Phase 3：anchor +123 / orphan_anchor +23 / ignored +31
- 修复路径：在 Phase 2 加 marker 守卫，**不在 Phase 3 修**（CLAUDE.md §8 phase 边界）
- 一旦上游 fix，跑 `cargo test ... -- --ignored` 立即验真

### 给 Phase 4 接手的人

Phase 3 已经准备好被 Phase 4 消费：
- `Phase3Output { structure, note_link_table, evidence, diagnostics, gate_report }` 全部填充真实数据，不再是 `default()`
- DB 持久化 4 个 method 调用就绪：`replace_fnm_phase3_products` / `replace_fnm_chapter_endnotes` / `replace_fnm_paragraph_footnotes` / `upsert_fnm_chapter_anchor_alignment`
- byte-equal parity 通过条件已明确文档化（known §7），不需要自己摸索差异在哪
