# 阶段 2 修复文档：Phase2 注释捕获与分类

创建时间：2026-05-22

本文是第二阶段的执行说明。接手人只读本文，应能知道阶段 2 为什么修、改哪些文件、每个文件怎么改、必须新增哪些测试，以及怎样跑完整验收。

> 2026-05-26 状态更新：当前执行以 `FNM_REPAIR_MASTER_PLAN.md` 的原阶段体系为准。阶段 5 程序合同已经闭合；本文中直接影响冻结输入的 Phase2 合同已完成复核。要求立即进行双书真实批跑的历史验收步骤仍暂时停用。

## 阶段目标

修掉 Biopolitics 当前主 blocker：

`endnote_region_marker_misalignment`

阶段 2 的唯一核心目标是让 Phase2 产出的 `NoteRegion`、`NoteItem`、`ChapterNoteMode` 成为下游可信事实。Phase3/4/5/6 不能替 Phase2 兜底修注释分类和 marker 序列。

本阶段完成后，应满足：

- Biopolitics 的 10 个 endnote region marker misalignment 消失。
- `1769`、`1944`、`6768`、`1977`、`631` 等年份/页码/书目信息数字不再作为 note marker。
- footnote 与 endnote 的 `note_kind` 逐 item 正确，不能由 chapter mode 广播。
- Phase2 parity/golden 测试用真实 fixture 证明输出稳定。

## 开工前清理项

阶段 1 有两个备注转入阶段 2 开工前处理：

1. 清掉 `fnm-core/src/vision/spec.rs` 里 `custom_gemini_has_no_enable_thinking` 的重复 `#[test]`。当前功能已通过，但重复属性会产生 `duplicated attribute` warning，污染后续验收日志。
2. 不使用 `output/fnm_real_batch/phase1_foundation_smoke/runtime_status.json` 作为阶段 2 证据。该文件曾显示 `running` 且没有 `results.json`；阶段 2 必须重新跑完整全量批，等待完成或明确失败落盘。

这两个清理项不属于 Phase2 业务修复，但要在阶段 2 第一次正式验证前完成。

## 本阶段输入证据

### Biopolitics 全量实测产物

上一轮可信产物目录：

`/Users/hao/OCRandTranslation/output/fnm_real_batch/biopolitics_gemini31_full_20260522_rerun3/phase_artifacts/Biopolitics`

关键文件：

- `summary.json`
- `phase2_note_capture/fnm_note_regions.json`
- `phase2_note_capture/fnm_note_items.json`
- `phase2_note_capture/fnm_chapter_note_modes.json`
- `final/final_structure_status.json`
- `final/final_export_verify.json`
- `post_resume_report.md`

关键事实：

- page_count：370
- chapter_count：13
- note_region_count：76
- note_item_count：572
- footnote_count：114
- endnote_count：458
- final blocker：`endnote_region_marker_misalignment`
- endnote_region_issue_count：10

问题 region 例子：

- `nr-en-ch-0015-ch-fallback-0003`：marker 出现 `1769`
- `nr-en-ch-0031-ch-fallback-0006`：marker 出现 `1944`
- `nr-en-ch-0038-ch-fallback-0007`：marker 出现 `6768`
- `nr-en-ch-0050-ch-fallback-0009`：marker 出现 `1977`
- `nr-en-bk-0062-ch-fallback-0010`：marker 出现 `631`

这些数字不可能是正常尾注 marker。它们来自年份、页码、书目信息、文本编号或 OCR 混入数字。修复必须在 Phase2 的 note item 捕获和序列验证处完成。

### 审计文件

本阶段主要读：

- `FNM_PHASE2_AUDIT.md`
- `FNM_AUDIT_SUMMARY.md`
- `FNM_REPAIR_MASTER_PLAN.md`
- `FNM_REPAIR_PHASE1_FOUNDATION.md`

重点审计结论：

- `note_kind`、region、chapter 是 Phase2 的事实边界。
- `build_note_items()` 中存在全局后处理，可能跨 region/chapter 污染。
- 年份修复缺 region/chapter/kind 边界。
- 续行合并按字符串 marker 排序，导致 `"10"` 排在 `"2"` 前。
- footnote region 按 marker 去重会删除连续页从 `1` 开始的合法脚注。
- `ChapterNoteModeRecord` 的事实字段从 `note_mode` 反推，违反聚合属性不能广播到个体事实的原则。

## 禁止做法

阶段 2 不允许：

- 在 Phase3/4/5/6 下游屏蔽 `endnote_region_marker_misalignment`。
- 写 Biopolitics 专用阈值、黑名单、年份列表、页码列表。
- 只靠 `max_marker < N` 这种外部假设过滤 marker。
- 用 chapter mode 覆盖 item 的 `note_kind`。
- 把未知 `note_kind` 默认当 footnote 或 endnote。
- 扩大 LLM repair 让它创建 note item 来绕过 Phase2。
- 跳过全量批跑，只用单测宣称完成。

正确方向：

- 用当前 region 内的真实 note item 序列做正向验证。
- 用 Phase1 page role/chapter boundary 和 Phase2 region 边界限制扫描范围。
- footnote/endnote 分支分开处理。
- 对无法验证的 item 标 review/blocker，而不是静默收进正常 note item。

## 文件级修复计划

### 1. `fnm-core/src/vision/spec.rs`

目的：

清理阶段 1 遗留 warning。

要做：

1. 删除 `custom_gemini_has_no_enable_thinking` 上重复的 `#[test]`。
2. 保留两个 Gemini 测试：
   - `custom_gemini_has_no_enable_thinking`
   - `custom_gemini_respects_explicit_extra_body`
3. 跑 `cargo test -p fnm-core custom_gemini_`，确认不再有 `duplicated attribute` warning。

验收：

- 测试仍通过。
- 输出中没有 `duplicated attribute` warning。

### 2. `fnm-phase2/src/note_items/mod.rs`

目的：

修 Phase2 note item 后处理主入口，避免全局排序、全局年份修复、跨 region 去重污染事实。

要做：

1. 找到 `build_note_items()` 的处理顺序。
2. 把全局后处理改成按 `(chapter_id, region_id, note_kind)` 分组执行。
3. `dedupe_region_items()` 拆成 footnote/endnote 两套策略：
   - footnote：key 至少包含 `(region_id, page_no, marker)`，或按页切 region 后再 `(region_id, marker)`。
   - endnote：可以继续 `(region_id, marker)`，但必须结合序列验证。
4. `merge_continuation_notes()` 不得按字符串 marker 排序。
5. 保留原始解析顺序。若必须排序，使用：
   - region 原始顺序
   - page_no
   - item occurrence/order
   - numeric marker sort key
   - 非数字 marker 明确排在独立分支
6. 输出前对每个 endnote region 做 marker 序列审计：
   - 记录 expected sequence。
   - 记录 rejected suspicious markers。
   - 不把 rejected marker 作为正常 `NoteItemRecord` 输出。

验收：

- `"10"` 不再排在 `"2"` 前导致续行错合。
- footnote 连续页都从 `1` 开始时不丢第二页脚注。
- Biopolitics 问题 region 中的大年份/页码数字被拒绝。

### 3. `fnm-phase2/src/note_items/year_filter.rs`

目的：

修年份误标过滤的边界。

要做：

1. 修改 `fix_year_markers_in_place()`，让它只处理同一 `(chapter_id, region_id, note_kind)` 内的相邻 item。
2. 不允许跨 region 边界使用 `prev/curr/next` 推断。
3. 不允许跨 chapter 边界删除或改 marker。
4. 对 `NoteKind::Unknown` 明确处理：
   - 不进入普通年份修复。
   - 标记 review 或原样返回，交给上游分类修复。
5. 补测试：
   - region A 末尾 marker、region B 开头 marker 正好形成年份修复条件时，不得跨 region 删除。
   - chapter A/B 边界同理。
   - endnote region 内 `1944` 位于 `33` 和 `35` 之间时被拒绝或标 review，不作为 marker。

验收：

- 年份修复只在同一 region 内生效。
- 不再有跨 region/chapter item 数变化。

### 4. `fnm-phase2/src/note_items/sequence_repair.rs`

目的：

把序列修复变成 Phase2 的正向验证核心，而不是靠后续 export audit 才发现错乱。

要做：

1. 检查已有 `fix_sequence_outlier_markers_in_place()` 或同类函数。
2. 抽出 endnote region marker validator：
   - 输入：同一 region 的候选 item。
   - 输出：accepted items、rejected candidates、sequence summary。
3. validator 只信 region 内可解释的序列：
   - 连续递增。
   - 小缺口可由 OCR 丢失解释，但不能接受大跳跃年份。
   - 重复 marker 要结合 page/order 判断是否 OCR split 或误捕。
4. 不使用全书固定上限作为主要判断。
5. rejected candidates 写 diagnostic/review 数据，方便后续确认。

验收：

- Biopolitics 10 个问题 region 的 `numeric_marker_contiguous` 恢复正常，或明确 review 但不进入正常 note item。

### 5. `fnm-phase2/src/note_items/marker_parse.rs`

目的：

收紧 marker 解析入口，减少年份、页码、书目信息数字进入候选集。

要做：

1. 检查 marker regex 是否把正文页码、年份、书目信息里的裸数字当 note marker。
2. 解析 marker 时保留 evidence：
   - 行首编号
   - note block/fnBlock 来源
   - heading 后 note list 来源
   - OCR superscript 来源
3. 对 endnote note page：
   - 优先接受行首 note definition marker。
   - 对行内数字默认不作为 marker，除非有明确 note item 结构证据。
4. 删除或接线阶段 1 遗留的 unused static，例如 `INLINE_FOLLOWUP_TOKEN_RE`。不要靠 `allow(dead_code)` 压 warning。

验收：

- `cargo clippy -p fnm-phase2 --all-targets -- -D warnings` 中对应 unused static 不再出现。
- 解析测试覆盖年份/页码/书目数字。

### 6. `fnm-phase2/src/note_regions/endnote_candidate.rs`

目的：

修 `page_role == note` 时条件过宽的问题。

要做：

1. `page_role == note` 不等于 endnote page。
2. endnote candidate 必须有正向证据之一：
   - `## NOTES` / `## Endnotes` 等 heading。
   - note_scan items 中存在 endnote kind。
   - page_kind 明确 endnote/mixed。
   - 该页落在 Phase1/TOC 推导的 endnote region。
3. footnote-only note page 不得送进 endnote region 构建。
4. 加测试：
   - role=note + footnote items，不是 endnote candidate。
   - role=note + endnote heading，是 endnote candidate。

验收：

- endnote region 不再靠 page role 宽松吸入非 endnote 内容。

### 7. `fnm-phase2/src/note_regions/footnote_band.rs`

目的：

修多页 footnote region 去重删除合法脚注的问题。

要做：

1. 决定策略：
   - 推荐：footnote region 按页切分；或
   - 保留多页 region，但 note item dedupe key 必须包含 page_no。
2. 不影响 endnote region 的去重策略。
3. 加真实或半真实 fixture：
   - 连续两页都有 footnote `1`。
   - 两个 `1` 都应保留。

验收：

- footnote item count 不因跨页重复 marker 被压低。

### 8. `fnm-phase2/src/note_kind_resolver.rs`

目的：

让 unknown/review 状态真正进入 Phase2，不再把未知事实编码成 footnote。

要做：

1. 找到 `note_kind: NoteKind::Footnote, review_required: true` 的 fallback。
2. 改为 `NoteKind::Unknown` 或直接阻断普通 region 输出。
3. 下游 `build_note_regions()` / `build_note_items()` 遇到 Unknown 时：
   - 不进入普通 matched/link 流程。
   - 生成 review/blocker。
4. 补测试：
   - 不确定 region 不得输出 footnote kind。
   - Unknown 不被 chapter mode 覆盖。

验收：

- `rg "note_kind: NoteKind::Footnote" fnm-phase2/src/note_kind_resolver.rs` 不再命中 fallback。

### 9. `fnm-phase2/src/chapter_split/mod.rs`

目的：

修 `ChapterNoteModeRecord` 从聚合 `note_mode` 反推事实字段的问题。

要做：

1. `has_footnote_band` 从实际 footnote regions/items 计算。
2. `has_endnote_region` 从实际 endnote regions/items 计算。
3. `primary_region_scope` 从实际主 region scope 计算。
4. `note_mode` 只作为章级摘要，用于 gate，不得广播到 item。
5. 混合章节必须能同时有 footnote/endnote item。

验收：

- 同章混合 footnote/endnote 时，item 的 `note_kind` 保持逐 item 分类。
- `ChapterNoteModeRecord` 字段与实际 region/items 对齐。

### 10. `fnm-phase2/src/chapter_split/structure_model.rs`

目的：

保证 Phase2 输出结构能表达 Unknown/review 和真实 region scope。

要做：

1. 检查 `ChapterLayers` / `ChapterNoteModeRecord` 转换逻辑。
2. 补 `NoteKind::Unknown` 分支。
3. 对 review 状态不要 default 成 ready。
4. 修 clippy 中 `derivable impl` 等质量项。

验收：

- Phase2 structure 不因 Unknown panic。
- clippy 对该文件不再报已知问题。

### 11. `fnm-phase2/src/note_regions/mod.rs`

目的：

删除旧 explorer stub，减少误导性数据流。

要做：

1. 删除或隔离 `let _explorations = explore_endnote_chapter_regions(...)` 这种“接入但丢弃结果”的路径。
2. 只保留一个 endnote chapter explorer 入口。
3. 如果暂不实现 explorer 接线，用 `anyhow::bail!` 或明确 TODO 文档，不要静默调用。

验收：

- Phase2 主流程没有“调用但丢弃”的旧 explorer stub。

### 12. `fnm-phase2/src/sup_recovery/mod.rs`

目的：

防止 sup recovery 后续接入时跨章污染。

要做：

1. `recover_book_chapter_scoped()` 给每章 recovery 传当前章 page range。
2. Layer 1/2/3 只扫描当前章 body pages。
3. 对重复 marker 跨章出现的情况加测试。

验收：

- recovery diagnostics 不引用其它章节页面作为当前章证据。

### 13. `fnm-phase2/src/sup_recovery/layer2.rs`

目的：

清理阶段 1 后仍存在的 warning，并按 Rust 规范推进。

要做：

1. 删除或接线 unused helper：
   - `chars_before`
   - `chars_after`
   - `truncate_to_chars`
2. 如果 helper 需要保留，必须被真实逻辑或测试使用。
3. 处理 clippy 的 explicit counter loop。
4. 不允许新增 `allow(clippy::*)`。

验收：

- `fnm-phase2` 不再因 layer2 unused helper 产生 warning。

### 14. `fnm-phase2/src/endnote_chapter_explorer/mod.rs`

目的：

处理 printed page 与 book page 直接比较的风险。

要做：

1. 找到所有 printed page 与 book page 直接比较的位置。
2. 统一使用 Phase1 page mapping 或明确字段类型。
3. 字段名里区分：
   - `book_page`
   - `pdf_page`
   - `printed_page`
4. 对无法映射的页面标 review，不猜。

验收：

- explorer 不用 printed page 直接判断 raw book page 范围。

### 15. `fnm-phase2/tests/biopolitics_phase2_parity.rs`

目的：

用 Biopolitics 真实 fixture 验证 Phase2 修复。

要做：

1. 加入本次 10 个问题 region 的断言。
2. 断言 forbidden markers 不存在：
   - `1769`
   - `1944`
   - `6768`
   - `1977`
   - `631`
3. 断言 endnote region marker 序列不出现大跳跃。
4. 如果 expected fixture 要更新，必须说明是 Rust 修复了 Python bug，还是 Python expected 同步更新。

验收：

- `cargo test -p fnm-phase2 --test biopolitics_phase2_parity` 通过。
- 测试不是只断言 count，而是断言 marker 序列质量。

### 16. `fnm-phase2/tests/audit_note_items_against_golden.rs`

目的：

把 note item 捕获质量变成 golden 审计。

要做：

1. 增加 suspicious marker 审计：
   - marker 数字远大于 region expected range。
   - marker 与相邻序列不连续。
   - marker 来自疑似年份/页码上下文。
2. 输出失败信息包含：
   - region_id
   - chapter_id
   - page_no
   - marker
   - source text preview
3. 不允许用 `assert!(count >= N)` 这类弱断言替代 parity。

验收：

- 失败时能直接定位 region 和源文本。

### 17. `fnm-phase2/tests/test_phase2_spec.rs`

目的：

恢复被 ignore 的 SPEC 测试，并覆盖边缘情况。

要做：

1. 找出当前 ignored tests。
2. 对仍然合理的 SPEC，修实现让测试通过。
3. 对 SPEC 已过期的，更新 SPEC 文档和测试原因，不能长期 ignore。
4. 增加：
   - 多页 footnote 都从 `1` 开始。
   - endnote region 内年份误捕。
   - Unknown note kind 不被广播。

验收：

- 不新增 ignored。
- 已知 ignored 数量减少。

## 本阶段必须新增的测试

最少测试集：

1. endnote marker validator：
   - `33, 1944, 35` 中 `1944` 不进入 accepted note items。
   - `1,2,3,4,10,23,244,51,8` 这类乱序候选不会被原样接受。
2. year filter boundary：
   - region/chapter 边界处不跨组修复。
3. continuation merge ordering：
   - `"10"` 不排在 `"2"` 前造成错误续行合并。
4. footnote dedupe：
   - 连续两页脚注 `1` 都保留。
5. endnote candidate：
   - `page_role=note` + footnote-only 不算 endnote page。
6. note kind unknown：
   - fallback 不输出 footnote/endnote。
7. Biopolitics fixture：
   - 10 个已知 problem region 不再 misalignment。
   - forbidden markers 不存在。
8. Goldstein 回归：
   - 不因 Biopolitics 修复造成另一书退化。

## 本阶段验证命令

### 基础 Rust 验证

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo fmt --check
cargo test -p fnm-phase2
cargo test -p fnm-phase2 --test biopolitics_phase2_parity
cargo test -p fnm-phase2 --test audit_note_items_against_golden
cargo clippy -p fnm-phase2 --all-targets -- -D warnings
```

如果 clippy 被前序 crate 阻断，先记录具体阻断；但阶段 2 本体新增代码不得引入新的 warning 或 `allow`。

### PyO3 重建

Phase2 修复如果影响 Python binding 或 pipeline 入口，必须重建：

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs/fnm-py
../../.venv/bin/python -m maturin develop
```

注意：必须从 `fnm_re_rs/fnm-py` 目录运行，不能从仓库根目录运行。

### Python 编译检查

```bash
cd /Users/hao/OCRandTranslation
.venv/bin/python -m py_compile FNM_RE/__init__.py scripts/test_fnm_batch.py scripts/test_fnm_real_batch.py
```

### Biopolitics 全量批跑，禁止跳过

阶段 2 修完后必须跑完整全量批：

```bash
cd /Users/hao/OCRandTranslation
PYTHONUNBUFFERED=1 .venv/bin/python scripts/test_fnm_real_batch.py \
  --slug Biopolitics \
  --group all \
  --include-all \
  --batch-tag phase2_note_capture_full \
  --verbose \
  2>&1 | tee /tmp/phase2_note_capture_full.console.log
```

强制要求：

- 不允许因为时间长跳过。
- 不允许只跑 Phase2 单测后宣称完成。
- 不允许看到 LLM repair 慢就提前终止。
- 必须一直等待到脚本自然结束，或出现明确错误并落盘。
- 如果命令长时间运行，继续等待；每 30 秒检查状态，但不要中断。
- 只有 `runtime_status.json` 进入 `completed`，或 `results.json` / `batch_report.md` 写出明确失败原因，才算这次全量批有结论。

批跑后必须检查：

```bash
cd /Users/hao/OCRandTranslation
.venv/bin/python - <<'PY'
import json
from pathlib import Path
base = Path("output/fnm_real_batch/phase2_note_capture_full")
for rel in ["runtime_status.json", "results.json", "batch_report.md", "token_summary.json"]:
    p = base / rel
    print("\\n---", rel, p.exists())
    if not p.exists():
        continue
    if p.suffix == ".json":
        print(json.dumps(json.loads(p.read_text()), ensure_ascii=False, indent=2)[:5000])
    else:
        print(p.read_text()[:3000])
PY
```

并检查 phase artifacts：

```bash
find output/fnm_real_batch/phase2_note_capture_full/phase_artifacts/Biopolitics -maxdepth 2 -type f | sort
```

### Biopolitics 结果断言

全量批跑结束后，必须确认：

- `endnote_region_marker_misalignment` 不再出现；或如果仍出现，必须列出剩余 region 和 marker。
- `final/final_structure_status.json` 中 Phase2 相关 blocker 消失。
- `phase2_note_capture/fnm_note_items.json` 中 forbidden markers 不存在于对应 endnote region。
- 如果导出仍 blocked，必须确认 blocker 已经转移到 Phase3/4/5/6，不是 Phase2 marker 捕获。

### Goldstein 回归

Biopolitics 通过后，必须跑 Goldstein 回归：

```bash
cd /Users/hao/OCRandTranslation
PYTHONUNBUFFERED=1 .venv/bin/python scripts/test_fnm_real_batch.py \
  --slug Goldstein \
  --group all \
  --include-all \
  --batch-tag phase2_note_capture_goldstein \
  --verbose \
  2>&1 | tee /tmp/phase2_note_capture_goldstein.console.log
```

同样不允许跳过或提前终止。

## 阶段完成判定

满足以下条件才进入阶段 3：

- 阶段 1 遗留 warning 已清理。
- `cargo fmt --check` 通过。
- `cargo test -p fnm-phase2` 通过。
- Phase2 Biopolitics parity/golden 测试通过。
- 新增 edge case 测试通过。
- Biopolitics 完整全量批自然结束并落盘。
- Biopolitics 不再出现 `endnote_region_marker_misalignment`。
- forbidden markers 不再作为 endnote note item。
- Goldstein 完整全量批自然结束并落盘。
- Goldstein 没有因 Phase2 修改出现新的 Phase2 blocker。

如果 Biopolitics 全量批仍 blocked，但 blocker 已不属于 Phase2 note capture，应把剩余 blocker 归入对应下一阶段，并在交接记录中写清楚证据文件路径。

## 交接输出要求

阶段 2 完成后，修复者必须提交一份简短交接记录，包含：

- 修改了哪些文件。
- 每个文件修了哪类 Phase2 事实污染。
- 新增了哪些测试。
- Biopolitics 全量批路径。
- Goldstein 回归路径。
- 最终 blocker 列表。
- 若仍 blocked，说明 blocker 属于哪个后续阶段。
- 明确写出是否可以进入阶段 3。
