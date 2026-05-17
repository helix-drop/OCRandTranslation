# 当前任务：A1 — phase3 chapter_id 前缀 bug

**Session size**：S（单 bug 调查 + 修，~50-150 LOC 改动）
**前置**：读 [FNM_RE/FNM_COMPLETION_PLAN.md](../FNM_RE/FNM_COMPLETION_PLAN.md) 了解 4 Step 20 任务全景

---

## 1. 问题描述

[`fnm-phase3/tests/biopolitics_phase3_parity.rs::biopolitics_phase3_chapter_contracts_parity`](fnm-phase3/tests/biopolitics_phase3_parity.rs) `#[ignore]` 测试用 `--ignored` 跑会 fail：

```
thread 'biopolitics_phase3_chapter_contracts_parity' panicked at biopolitics_phase3_parity.rs:424:9:
assertion `left == right` failed: contract[0].chapter_id
  left:  "toc-ch-1"
 right:  "toc-toc-ch-1"
```

**Python golden** 期待 `toc-toc-ch-1`（双 `toc-` 前缀，Python 历史命名）。
**Rust 实际产出** `toc-ch-1`（剥了一层前缀）。

## 2. 已知线索（省你 grep 时间）

### A. parity test 端硬编码 双前缀（这是对的，模拟 Python golden）

[`fnm-phase3/tests/biopolitics_phase3_parity.rs:50-52`](fnm-phase3/tests/biopolitics_phase3_parity.rs:50)：
```rust
// Python 端 chapter_id 命名约定：`toc-{item_id}`，而 item_id 已是
// `toc-ch-N`——双 toc 前缀（见 known_python_bugs §7 chapter_id 命名）。
chapter_id: format!("toc-toc-ch-{}", i + 1),
```

### B. phase1 builder 端也已显式处理双前缀

[`fnm-phase1/src/chapter_skeleton/builder.rs:56-64`](fnm-phase1/src/chapter_skeleton/builder.rs:56)：
```rust
// ←→ Python `_build_visual_toc_chapters`：chapter_id 用
// `toc-{item_id}` 而非硬编码 `toc-ch-{i+1}`，对齐 Python 命名
// 约定（item_id 已含 `toc-ch-N` 时会出现 `toc-toc-ch-N`，
// 这是 Python 端历史命名导致，Rust 必须 byte-equal 复制）。
let chapter_id = if !item.item_id.trim().is_empty() {
    format!("toc-{}", item.item_id.trim())
} else {
    format!("toc-ch-{}", i + 1)
};
```

**所以 phase1 是对的**。如果 caller 传入 `item_id = "toc-ch-1"`，phase1 输出 `chapter_id = "toc-toc-ch-1"`。

### C. parity test 实际不走 phase1，它自己构造 chapter

[`build_chapters()`](fnm-phase3/tests/biopolitics_phase3_parity.rs:25-63) 直接 hand-craft 12 个 ChapterRecord 喂给 `build_phase3_structure`——chapter_id 已经是 `toc-toc-ch-N`（line 52 硬编码）。所以 **phase3 应该原样收到 `toc-toc-ch-N`，但实际产出变成 `toc-ch-N`——某处剥了前缀**。

### D. 关键嫌疑点

`build_phase3_structure` → `build_chapter_layers` (phase2) → `phase2_from_chapter_layers` (phase3 内部，重建 phase2 结构)

phase2 / phase3 内部某处可能：
- 用 `chapter_id` 作为 key 时做了 trim 或 strip prefix
- 或者用别的字段（如 `title`）重新生成 chapter_id，丢了原来的

## 3. 调查步骤

**Step 1**：用 grep 找所有写 `chapter_id` 的位置（phase2/phase3）：
```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
grep -rn "chapter_id:\s*\|chapter_id\s*=" fnm-phase2/src fnm-phase3/src --include="*.rs" | grep -v "//\|test\|tests" | head -40
```

**Step 2**：聚焦 phase3 `chapter_contracts` 输出的 `ChapterLinkContract.chapter_id` 来源——sequence 是：
1. `lib.rs::build_phase3_structure` 调用 `build_chapter_layers` (phase2) → `ChapterLayers`
2. `note_linking/mod.rs::build_note_link_table` 调 `phase2_rebuild::phase2_from_chapter_layers`
3. `chapter_contracts::chapter_contracts(&chapter_layers, ...)` 用 `cl.chapter_id` 写入 contract
4. 装到 `Phase3Output.note_link_table.chapter_link_contracts`

可能位置：
- `build_chapter_layers` 内构造 `ChapterLayer.chapter_id` 时是不是直接用 `ChapterRecord.chapter_id`？检查 `fnm-phase2/src/chapter_split/mod.rs::build_chapter_layers`
- 或者 phase2 入口 `Phase2Input.phase1_chapters` 传入时 caller 改了

**Step 3**：加临时 `eprintln!` 跟踪：
```rust
// 在 fnm-phase2/src/chapter_split/mod.rs::build_chapter_layers 入口加：
eprintln!("[DEBUG] input chapters[0].chapter_id = {:?}", chapters[0].chapter_id);

// 在 fnm-phase3/src/note_linking/chapter_contracts.rs 入口加：
eprintln!("[DEBUG] chapter_layers.chapter_layers[0].chapter_id = {:?}",
          chapter_layers.chapter_layers.get(0).map(|c| &c.chapter_id));
```

跑 `cargo test -p fnm-phase3 biopolitics_phase3_chapter_contracts_parity -- --ignored --nocapture 2>&1 | grep DEBUG` 看在哪一层剥的前缀。

## 4. 修复方向（不要预先假设根因，先调查）

可能的修法（按发现的根因选）：
- **方向 A**：若 `build_chapter_layers` 重新构造 chapter_id（用 i+1 索引），改成透传原值
- **方向 B**：若 phase2 某 trim / strip_prefix 误剥前缀，删除该处理
- **方向 C**：若 `Phase2Input` 转换时丢字段，加 owner_chapter_id 字段保留原值

**禁止**：
- 改 parity test 把 expected 改成 `toc-ch-N` 来"绕过"（违反 AGENTS.md §7 byte-equal）
- 改 phase1 builder.rs 改命名（phase1 是对的）

## 5. 验收命令

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs

# 1. 修复后 chapter_id 不再剥前缀
cargo test -p fnm-phase3 biopolitics_phase3_chapter_contracts_parity -- --ignored --nocapture 2>&1 | tail -10
# 期望：chapter_id 维度 PASS（其他维度仍 fail，因 phase2 cascade 待 A3 修）

# 2. 现有测试 0 regression
cargo test --workspace 2>&1 | grep "FAILED\|test result:" | grep -v "0 failed"
# 期望：所有 active test 仍 0 failed

# 3. clippy + fmt
cargo clippy --workspace --all-targets -- -D warnings 2>&1 | tail -3
cargo fmt --check
# 期望：均 clean

# 4. 删除调试 eprintln!（如有加过）
grep -rn "eprintln!" fnm-phase2/src fnm-phase3/src --include="*.rs" | grep -v "test\|//"
# 期望：空输出
```

## 6. 完成后

1. **更新 [`fnm-phase3/tests/known_python_bugs.md`](fnm-phase3/tests/known_python_bugs.md)** §7，把 chapter_id 前缀 bug 标为 ✅ 已修，注明根因
2. **更新 [`FNM_RE/FNM_COMPLETION_PLAN.md`](../FNM_RE/FNM_COMPLETION_PLAN.md)** Step A 表，A1 状态从 ⏳ 改为 ✅，当前任务标记移到 A2
3. **重写本文件 `HANDOFF_NEXT.md`** 派下一个任务 A2（phase1 Biopolitics parity）。模板见下方
4. **commit**（消息见下方）+ push main

### Commit message 模板

```
A1 fix: phase3 chapter_id 双 toc- 前缀 bug

phase3 ignored parity test 暴露 chapter_contracts.chapter_id 维度差异：
  rust=toc-ch-1 vs python=toc-toc-ch-1（剥了一层前缀）

根因：<填实际根因，如 phase2 chapter_split 重新构造 chapter_id>

修复：<填实际修法>

验证：
- cargo test biopolitics_phase3_chapter_contracts_parity --ignored 通过 chapter_id 维度
- 其他维度仍 fail（phase2 note_items cascade，待 A3 修）
- cargo test --workspace 全 active test 0 regression
- known_python_bugs.md §7 chapter_id 行已勾 ✅

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

### 下一个任务 HANDOFF 模板（写到本文件覆盖）

参考本文件结构：
- 第 1 节：问题描述
- 第 2 节：已知线索（grep 出关键代码 + 行号）
- 第 3 节：调查/实施步骤
- 第 4 节：修复方向 + 禁止事项
- 第 5 节：验收命令
- 第 6 节：完成后流程

下一个任务 A2 详细 brief 见 [FNM_RE/FNM_COMPLETION_PLAN.md](../FNM_RE/FNM_COMPLETION_PLAN.md) Step A 表第 2 行：fnm-phase1 Biopolitics phase1 byte-equal parity 完整验证（F12，M 大小，抄 phase3 parity 模板）。

---

## 附录：项目级强制约束（必读）

| 文档 | 重点 |
|---|---|
| [AGENTS.md](../AGENTS.md) §「Rust 重构代码规范」12 条铁律 | §1 翻译保真度 / §2 Lazy<Regex> / §7 byte-equal parity / §8 禁 let _ / §9 stub 用 bail / §11 clone 节制 |
| [CLAUDE.md](../CLAUDE.md) §12「树枝状条件处理」 | 5 条铁律（分类源头唯一 / 分支穷尽互斥 / 禁止广播 / 上下游隔离 / 集中 dispatch） |
| [FNM_RE/FNM_COMPLETION_PLAN.md](../FNM_RE/FNM_COMPLETION_PLAN.md) | 完善计划全景（4 Step / 20 任务 / 顺序）|

**不要打破现有 byte-equal 约束**。本任务修复后 chapter_id 应严格等于 Python golden，不是「差一点也算过」。
