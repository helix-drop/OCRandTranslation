# `fnm-phase4` 实施计划

本文档是自包含的——新 session 接手者读完本文件 + AGENTS.md Rust 规范 +
fnm-phase3 完成情况，即可开工 Phase 4。

---

## 0. 项目背景（30 秒）

正在做 Python `FNM_RE/` 到 Rust `fnm_re_rs/` 的全量重写。

| Phase | crate | 状态 |
|---|---|---|
| 0 基础设施 | `fnm-core` | ✅ 已完成（92 测试） |
| 1 章节骨架 | `fnm-phase1` | ✅ 已完成（77 测试 + 2 ignored）|
| 2 注释结构 + note_kind | `fnm-phase2` | ✅ 已完成（81 测试 + 2 ignored，含 endnote_repair/explorer 2 个 stub 未接主入口）|
| 3 body anchor + link 匹配 | `fnm-phase3` | ✅ **已完成（14/14 任务 + 2 轮审计修复）** |
| **4 引用注入 + 翻译单元** | **`fnm-phase4`** | **🔄 本文档** |
| 5 章 markdown 合并 | `fnm-phase5` | ⏳ 未开始 |
| 6 导出审计 | `fnm-phase6` | ⏳ 未开始 |
| LLM repair (3.5) | `fnm-llm-repair` | ⏳ 未开始 |

当前测试套件：
```
cargo test --workspace        → 全部 0 failed
cargo clippy --workspace --all-targets -- -D warnings  → clean
cargo fmt --check             → clean
```

---

## 1. 必读前置（按顺序）

| # | 路径 | 重点章节 |
|--:|---|---|
| 1 | `/Users/hao/OCRandTranslation/AGENTS.md` | "Rust 重构代码规范" 12 条铁律（行 281-540）|
| 2 | `/Users/hao/OCRandTranslation/CLAUDE.md` | 第 8/12 条 Phase 边界 + 树枝状条件 |
| 3 | `/Users/hao/OCRandTranslation/FNM_RE/RUST_MIGRATION_PLAN.md` | "Step 4" 段（行 322-346）|
| 4 | `/Users/hao/OCRandTranslation/FNM_RE/FNM_PHASE3_PLAN.md` | 参考 Phase 3 plan 任务粒度与 PR 流程 |
| 5 | `fnm_re_rs/fnm-phase3/tests/known_python_bugs.md` | Phase 3 已知遗留（Phase 2 cascade 5 个 ignored）|

**特别看 AGENTS.md 的 12 条铁律**——任何违反都会被审计拒绝。简版：
1. 翻译保真度禁简化（Rust ~ Python 80-120% 行数）
2. Regex 必须 `Lazy<Regex>` 静态
3. 复用 fnm-core 基础设施
4. mod.rs < 400 行
5. 每个 pub fn 标 `←→ Python xxx()` doc comment
6. 测试用真实 fixture
7. Parity byte-equal Python
8. 不允许 `let _ = ...` 忽略关键参数
9. Stub 用 `anyhow::bail!`，不静默返空
10. 0 `Rc<RefCell>` / 0 滥用 `Arc<Mutex>`
11. `.clone()` 节制
12. PR 验收 checklist 12 项

---

## 2. Phase 4 目标与职责

### 输入

通过 DB / 直接消费 Phase 3 输出：

| 来源 | 内容 |
|---|---|
| Phase 1 (`fnm_chapters` / `fnm_section_heads`) | 章节骨架 |
| Phase 2 (`fnm_note_items` / `fnm_note_regions`) | note 定义（含 note_kind）|
| Phase 3 (`fnm_body_anchors` / `fnm_note_links`) | 已 matched 的 link + anchor |
| raw_pages.json | markdown / blocks / fnBlocks |

### 输出

| 表 / 字段 | 内容 | 入口函数 |
|---|---|---|
| `fnm_translation_units` | 翻译单元（按段落 / 章 / 章节） | `build_translation_units` |
| `fnm_structure_reviews` | 结构复核记录 | `build_structure_reviews` |
| `Phase4Output.frozen_refs` | 冻结的引用 token | `build_frozen_units` |
| `Phase4Output.status` | StructureStatusRecord | 同上 |

### Phase 边界纪律（CLAUDE.md §12）

Phase 4 **绝对不做**：
- ❌ **重新检测 anchor / link**（Phase 3 唯一来源，Phase 4 只透传 matched links）
- ❌ **重分类 note_kind**（Phase 2 唯一来源）
- ❌ **重新切分章节**（Phase 1 唯一来源）
- ❌ 修改上游 DB 表（只读 phase1/2/3 表）

Phase 4 **该做**：
- ✅ 把 matched link 的 anchor 坐标注入 body markdown（`{{NOTE_REF:N}}` token 替换）
- ✅ 检测 unsupported link（matched 但 anchor 坐标缺失 / synthetic）→ blocker
- ✅ 切分翻译单元（按段落 / 章 / 跨页边界）
- ✅ 生成结构复核记录（structure_reviews）

---

## 3. Python 源对应

| Python 路径 | 行数 | Rust 子模块 |
|---|---:|---|
| `FNM_RE/modules/ref_freeze.py` | 678 | `ref_freeze.rs` (~600-700 行) |
| `FNM_RE/stages/units.py` | 868 | `units.rs` (~800-900 行) |
| `FNM_RE/stages/reviews.py` | 210 | `reviews.rs` (~200-250 行) |
| **合计** | **~1756 行** Python | → 预计 **~1700-2000 行** Rust |

### `ref_freeze.py` 内部职责

- `build_frozen_units(...)`: 顶层编排
- `_inject_anchor_into_body(...)`: 把 `{{NOTE_REF:N}}` 注入 markdown
- `_check_freeze_contract(...)`: blocker 检查（`freeze_matched_ref_not_injected`）
- `_cleanup_nested_note_refs(...)`: 嵌套清理（已在 fnm-core）

### `units.py` 内部职责

- `build_translation_units(...)`: 顶层编排
- `_split_paragraph_boundaries(...)`: 段落边界识别
- `_chunk_into_translation_units(...)`: 按 token budget 切块
- `_assign_unit_metadata(...)`: 单元元数据

### `reviews.py` 内部职责

- `build_structure_reviews(...)`: 结构复核生成

---

## 4. crate 结构与实施顺序

### 已就绪
- `fnm-phase4/Cargo.toml`（依赖 phase1/2/3 + fnm-core）
- `fnm-phase4/src/lib.rs`（placeholder）
- workspace member 已加入

### 实施顺序（7-8 任务，~2 周）

| # | 任务 | 工时 | 依赖 |
|--:|---|---:|---|
| P4.0 | `placeholder()` 删除 + 子模块声明开放 | 0.5 天 | — |
| P4.1 | `input.rs` + `output.rs` 类型契约（用 fnm-core records）| 0.5 天 | P4.0 |
| P4.2 | `ref_freeze.rs` — frozen_units 编排 + 注入 + blocker | 4 天 | P4.1 |
| P4.3 | `units.rs` — translation_units 切分 | 4 天 | P4.2 |
| P4.4 | `reviews.rs` — structure_reviews 生成 | 1.5 天 | P4.2 |
| P4.5 | `lib.rs::build_phase4_structure` 顶层编排 | 1 天 | P4.2-P4.4 |
| P4.6 | `persist_phase4` + DB 持久化 | 1 天 | P4.5 |
| P4.7 | Biopolitics parity + 3 SPEC 测试翻译 | 2 天 | P4.6 |
| **总计** | | **~14.5 天** | |

---

## 5. 各任务详细规格

### P4.0: 启动（0.5 天）

1. 删除 `lib.rs::placeholder()` + test
2. 创建空文件：`input.rs` / `output.rs` / `ref_freeze.rs` / `units.rs` / `reviews.rs`
3. lib.rs 加 `pub mod` 声明（暂时全空）

**验收**：`cargo build -p fnm-phase4` 通过。

### P4.1: 类型契约（0.5 天）

`fnm-core` 已经定义了所有 Phase 4 Record 类型：
- `StructureReviewRecord` (records.rs:581)
- `StructureStatusRecord` (records.rs:593)
- `TranslationUnitRecord`
- `Phase4Summary` (records.rs:695)
- `Phase4Structure` (records.rs:751)

`input.rs`:
```rust
use fnm_core::records::*;
use fnm_phase1::input::RawPage;

pub struct Phase4Input<'a> {
    pub phase1_chapters: &'a [ChapterRecord],
    pub phase2_note_items: &'a [NoteItemRecord],
    pub phase2_note_regions: &'a [NoteRegionRecord],
    pub phase3_body_anchors: &'a [BodyAnchorRecord],
    pub phase3_note_links: &'a [NoteLinkRecord],
    pub raw_pages: &'a [RawPage],
    pub config: Phase4Config,
}
```

`output.rs`:
```rust
pub struct Phase4Output {
    pub structure: Phase4Structure,
    pub diagnostics: HashMap<String, serde_json::Value>,
}
```

### P4.2: `ref_freeze.rs` — frozen_units（4 天，**最大头**）

**Python 源**：`FNM_RE/modules/ref_freeze.py` 678 行

核心算法（注入 anchor 坐标）：
1. 遍历 matched note_links
2. 找到对应 body_anchor 的 (page_no, char_start, char_end)
3. 在 page markdown 的对应位置插入 `{{NOTE_REF:N}}` token
4. 处理嵌套（复用 `fnm_core::refs::cleanup_nested_note_refs`）
5. 输出 frozen_pages + frozen_units（用于下游 translation_units 切分）

**blocker**：`freeze_matched_ref_not_injected`——matched link 但 anchor 坐标缺失/无效 → bail!

**子模块拆分（如果超 §4）**：
- `ref_freeze/mod.rs`：顶层编排
- `ref_freeze/inject.rs`：anchor 注入
- `ref_freeze/contract.rs`：blocker 检查

### P4.3: `units.rs` — translation_units（4 天）

**Python 源**：`FNM_RE/stages/units.py` 868 行

核心算法：
1. 消费 frozen_units（已注入 NOTE_REF token）
2. 按段落边界切分
3. 按 token budget（用 `fnm_core::token_counter`）切块
4. 生成 TranslationUnitRecord

**SPEC 测试覆盖**：
- `test_ch5_note_4_definition_is_full_length`（长注完整保留）
- `test_superscript_note_definition_lines_are_filtered`

**性能关注点**：
- token 计数：`fnm_core::token_counter` 已有
- 字符串拼接：`String::with_capacity` 预分配

### P4.4: `reviews.rs` — structure_reviews（1.5 天）

**Python 源**：`FNM_RE/stages/reviews.py` 210 行

生成 StructureReviewRecord（章级 / 段落级复核）。最小，建议单文件不拆。

### P4.5: `lib.rs` 顶层编排（1 天）

```rust
pub fn build_phase4_structure(input: Phase4Input) -> anyhow::Result<Phase4Output>;
```

### P4.6: `persist_phase4` + DB（1 天）

fnm-core 应已有 `replace_fnm_phase4_products`。如缺先去 fnm-core 补。

### P4.7: SPEC + parity（2 天）

**SPEC 测试**（参照 RUST_MIGRATION_PLAN.md "SPEC 测试清单"）：
- `test_load_phase6_for_doc_keeps_synthesized_note_items_from_overrides`
- `test_ch5_note_4_definition_is_full_length`
- `test_superscript_note_definition_lines_are_filtered`

**Biopolitics parity**：参考 phase3 `tools/gen_biopolitics_phase3_golden.py` 模板，
写 `tools/gen_biopolitics_phase4_golden.py`，输出 JSON fixture，逐字段 byte-equal 比对。

**已知 Phase 2 cascade 影响**：如果 phase3 ignored 测试因 phase2 over-extraction
未解，phase4 parity 也会有类似数字差异——参照 phase3 `known_python_bugs.md §7` 做法。

---

## 6. Phase 4 验收 checklist（每个 PR）

抄 phase3 PLAN §8：

### 代码层
- [ ] `cargo build --release -p fnm-phase4` 通过
- [ ] `cargo clippy -p fnm-phase4 -- -D warnings` 通过（0 新增 allow）
- [ ] `cargo fmt --check` 通过
- [ ] `cargo test --all` 通过（保持现有测试 0 failed）
- [ ] 0 个 `let _ = ...` 忽略关键参数
- [ ] 0 个静默 stub（必须 `anyhow::bail!`）
- [ ] 0 个循环内 `Regex::new()`
- [ ] 0 `Rc<RefCell>` / 0 滥用 `Arc<Mutex>`

### 复用层
- [ ] PR 描述列出复用的 fnm-core / phase1/2/3 API
- [ ] 复用 `fnm_core::refs::cleanup_nested_note_refs` / `token_counter` 等
- [ ] 不重新定义 fnm-core 已有的类型

### Phase 边界纪律
- [ ] 0 处 `note_kind = ...` 赋值（只透传）
- [ ] 0 处重检测 anchor / link
- [ ] 0 处 chapter 重切分
- [ ] PR 描述声明："Phase 4 严守边界，仅消费上游事实"

### Parity
- [ ] Biopolitics parity 测试通过 OR 在 `known_python_bugs.md` 记录根因
- [ ] SPEC 测试翻译并通过

---

## 7. 已知风险与缓解

| 风险 | 缓解 |
|---|---|
| Phase 2/3 上游 cascade（35 个 over-extraction note_items）| Phase 4 透传不修复，blocker 报但允许进入下游验证；待 Phase 2 endnote_repair 接入主入口后 cascade 自然解 |
| `ref_freeze.py` 678 行复杂度 | 按 §4 拆 3 子模块（inject / contract / cleanup） |
| ref token 注入算法 O(n×m) | 用 `aho-corasick`（fnm-phase3 已是依赖）做多模式匹配优化为 O(n) |
| Python 端 frozen_units 数据结构未在 fnm-core records 直接对应 | 优先在 fnm-core 加 FrozenUnitRecord，避免 phase4 内重新定义 |

---

## 8. Phase 2 cascade 修复任务（独立，不阻塞 Phase 4 启动）

Phase 3 留下的 5 个 `#[ignore]` byte-equal parity 测试根因是 Phase 2 上游
`note_items` over-extraction（35 个）。这是 Phase 4 启动前**可以并行处理**的独立任务：

| 任务 | 描述 |
|---|---|
| Phase 2 endnote_repair 接入 | `fnm-phase2/src/lib.rs` 在 step 5 真实调用 `endnote_repair::repair_endnote_items` |
| Phase 2 endnote_chapter_explorer 接入 | 同上，step 4 |
| 跑 phase3 `--ignored` 验证 | 修完后跑 `cargo test -p fnm-phase3 -- --ignored`，期望 5 个 parity 测试通过 |
| 删 `#[ignore]` 注解 | 验证通过后把 phase3 测试转为 active |

**推荐**：Phase 4 启动后由其他人/同期推进，两者解耦。

---

## 9. PR 流程

每个 P4.x 一个独立 PR。PR title：

```
P4.X: <模块名> — <核心功能>（<行数>）
```

例：`P4.2: ref_freeze — frozen_units 编排 + 注入（约 700 行）`

每个 PR 合并前做代码审查。

---

## 10. 开工 checklist

1. 读完 §1 必读前置（5 个文档）
2. `cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --all`（确认基线全过）
3. 看 phase3 完成参考实现：`fnm-phase3/src/lib.rs::build_phase3_structure`
4. P4.0 开始：替换 placeholder() + 创建子模块占位
5. 每个 P4.X 一个 PR，标题严格按 §9 格式
6. P4.7 完成后通知用户做最终审计
