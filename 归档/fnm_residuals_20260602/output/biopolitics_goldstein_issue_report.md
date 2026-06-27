# Biopolitics / Goldstein FNM Pipeline 问题报告

生成时间: 2026-05-07
模型: mimo-v2.5, 视觉模型确认: page 208, 158

---

## Biopolitics

**Pipeline 状态**: pages=370, chapters=14, notes=588, anchors=657
**Linking**: matched=583, endnote_orphan_note=3, footnote_orphan_anchor=4, fallback=44 (7.5%)
**程序阻塞**: `contract_def_anchor_mismatch`
**金版对比**: +15 引用, -3 定义, 3/14 章通过

### P0 — 程序错误（必须修）

| # | 引用 | 页码 | source_marker | 问题描述 |
|---|------|------|---------------|----------|
| 1 | ch008 `[^7]` | 208 | `7` bare_digit, cert=0.6 | **章标题 "LEÇON DU 7 MARS 1979" 的普通数字 7 被 bare_digit 误判为尾注**。视觉模型已确认：7 是普通字体非上标。锚点 `anchor-00365` 被强行链到 `en-00286`（marker=7），占用了正确的 7 号位。 |
| 2 | ch003 `[^6]` | 72 | `<sup>6</sup>`, cert=1.0 | **OCR 把 `XVIIIᵉ`（18世纪，ᵉ 是 siècle 的缩写上标）误读为 `XVIII⁶`**。`<sup>6</sup>` 锚点 `anchor-00049` 链到了 `en-00043`（marker=6），但在原文中是 `XVIIIᵉ siècle` 而非尾注。 |
| 3 | ch011 `[^8]`×2 | 286 | `$ ^{8} $` linked | **段落重复**。翻译单元 `body-toc-ch-011-0002` 内同一段 "Skinner[^8]..." 出现两次。`units.py:293` `_chunk_visible_paragraphs` 的去重逻辑未覆盖该场景。 |
| 4 | ch011 `[^9]`×2 | 286 | `$ ^{9} $` linked | 同上，同一 translation unit 内 `[^9]` 段落重复。 |

**根因**:
- #1: `anchors.py _BARE_DIGIT_RE` 未排除章标题页的纯数字，且 `_is_bare_digit_marker_context` 守卫未对日期/标题场景生效
- #2: LaTeX `$ ^{6} $` 匹配到了 pymupdf 错误渲染的 `XVIIIᵉ`，Phase2 `body_anchors` 将其当作正常上标
- #3, #4: `units.py:293-311` 段落去重只在 `consumed_by_prev=True` 的段上生效，但 ch011 的重复发生在同一 page segment 内的不同 paragraph 索引

### P1 — bracketed `[n]` 假阳性（已修复，待 re-run 验证）

| # | 引用 | 页码 | source | 说明 |
|---|------|------|--------|------|
| 5 | ch001 `[^1]`×3 | 29, 31 | `[1]` bracket | 法语学术出版中的脚注标记。`resolve_anchor_kind` 已修复为 `unknown` |
| 6 | ch011 `[^8]`×2 | 290 | `[8]` bracket | 同上，已修复 |
| 7 | ch011 `[^9]`×2 | 290 | `[9]` bracket | 同上，已修复 |
| 8 | ch012 `[^17]` | 319 | `[17` broken_bracket | 同上，已修复 |

### P2 — 非程序问题（LLM/OCR 不可控，容许）

| # | 引用 | 页码 | source | 说明 |
|---|------|------|--------|------|
| 9 | 缺失 13 个引用 | 各页 | — | sup_recovery L3 UNRECOVERED: 33 个 marker，其中 13 个对应金版期望的引用。vision API 扫描了 3 层页面仍找不到 marker 的嵌入位置 |
| 10 | +10 个多余引用 | 48-319 | `<sup>n</sup>` / `$^{n}$` linked | ch002[^7], ch003[^22][^23][^33][^34], ch004[^6][^27][^31][^44], ch006[^36][^37][^38], ch009[^41], ch010[^3], ch011[^19], ch012[^33] — 格式正确、链接正确、有对应的 note 定义。视觉模型确认 page 158 的 [^36][^37][^38] 是句末真上标。金版 curator 选择不收录这些引用 |
| 11 | ch009 `[^1]` | 233 | `¹` unicode_sup | `[^11][^1]` 两个标记连续出现，均为合法上标格式 |

### P3 — 脚注 orphan（不阻塞，容许）

| # | note_item | 说明 |
|---|-----------|------|
| 12 | fn-00105 (marker=10), fn-00106 (marker=11) | ch014 的两个脚注 orphan，定义文本已在 body 中出现，只是 link 未配对 |

---

## Goldstein

**Pipeline 状态**: pages=431, chapters=9, notes=921, anchors=957
**Linking**: matched=898, orphan=0, fallback=0, repair=60
**程序阻塞**: `split_items_sparse_note_capture`
**金版对比**: +126 引用, -23 定义, 0/9 章通过

### P0 — 程序错误（必须修）

| # | 引用 | 页码 | source | 问题描述 |
|---|------|------|--------|----------|
| 1 | 段落重复 — **41 个 body unit 中有 33 个含重复 NOTE_REF** | | | 整个文档的 body unit assembly 存在系统性段落重复。最严重的 unit `body-toc-ch-002-0002`: en-00051 重复 5 次。根因：`units.py:293` 段落去重未生效——与 Biopolitics #3 同一根因。这导致 ch002 额外 +13 引用、ch006 额外 +25、ch008 额外 +45 |
| 2 | ch006 `[^13]`×2, `[^15]`×2 | 234, 242 | `[13]`, `[15]` bracket, kind=**endnote** | **bracket 标记仍被判为 endnote**——同事的 `resolve_anchor_kind` 修复未在 Goldstein 上生效（Goldstein 未 re-run）。视觉模型待确认，但法语/英语学术格式中 `[n]` 是脚注标记，不应归为 endnote |
| 3 | ch006 `^{154}` 上标残留 | 243 | `^{154}` | 导出文本中存在 1 处未转换的 raw LaTeX 上标 `^{154}`，说明 ref_freeze 或 export 没有处理该格式 |

### P1 — unlinked `$^{n}$` 锚点（待核查）

| # | 引用 | 页码 | 说明 |
|---|------|------|------|
| 4-44 | 41 个 unlinked endnote anchor | 20-343 | `$ ^{n} $` (29个), `<sup>n</sup>` (3个), `[n]` bracket (4个), bare_digit (4个), `^{n}` (1个)。格式多数正确但找不到对应 note_item。部分可能是 LaTeX 公式中的数字被误识别（如 `$^{7}$` 在数学语境中），需视觉模型逐页确认 |

### P2 — 缺失引用（LLM 不可控）

| # | 引用 | 说明 |
|---|------|------|
| 45-67 | 缺失 23 个引用 | ch002 [7,47,60], ch003 [8,44], ch005 [30,75,76,77,78,114], ch006 [63,131,151], ch007 [32,71,96], ch008 [118,142,143], ch009 [22,25]。sup_recovery 日志中有 5 个 UNRECOVERED，其余可能是 OCR 漏检 |

### P3 — `split_items_sparse_note_capture` 假阳性阻塞

| # | 说明 |
|---|------|
| 68 | **阻塞条件不应触发**。Goldstein 的 link 质量完美（matched=898, orphan=0, fallback=0），note capture 很充分。`_note_capture_summary()` 的 `expected_count` 来自 body anchor 计数，被段落重复推高了（重复段 → 多余的 anchor 计数 → 虚高的 expected_count → ratio < 0.6 → 触发 sparse）。修复段落重复后，该阻塞应自动消失。 |

---

## 两书问题对照

| 问题类型 | Biopolitics | Goldstein | 责任代码 |
|----------|-------------|-----------|----------|
| bare_digit 标题数字 | ch008 [^7], cert=0.6 | 无 | `anchors.py` `_BARE_DIGIT_RE` |
| OCR `e` → `6` | ch003 `XVIIIᵉ` → `⁶` | 无 | pymupdf 渲染 + Phase2 |
| 段落重复 | ch011 [^8][^9]×2 | 33 个 unit 含重复 | `units.py:293` `_chunk_visible_paragraphs` |
| `[n]` bracket 误判 | 8 个，已修复 | 4 个，待 re-run | `anchors.py:113` `resolve_anchor_kind` |
| 上标残留 | ch008 HTML 1处 | ch006 `^{154}` 1处 | export / ref_freeze |
| unlinked `<sup>` / `$^{n}$` | 49 个 | 41 个 | sup_recovery / Phase2 |
| sup_recovery UNRECOVERED | 33 个 marker | 5 个 UNRECOVERED | vision API |
| 程序阻塞假阳性 | `contract_def_anchor_mismatch` 部分假阳性 | `split_items_sparse_note_capture` 全假阳性 | `note_linking.py:1568`, `chapter_split.py:629` |
| 脚注 orphan | 2 个，def 已在 body | 0 个 | 不阻塞 |

---

## 修复优先级

1. **段落重复** (`units.py:293`) — 影响两个书、Goldstein 最严重（系统性重复）
2. **bare_digit 标题过滤** (`anchors.py`) — ch008 标题数字
3. **OCR `e`→`6` 守卫** — `XVIIIᵉ` 场景，可能需要视觉模型辅助确认
4. **[^] 上标残留** — ch006 `^{154}` 未转换
5. **Goldstein re-run** — 同事的 bracket/unknown/段落去重修复需要 fresh run 验证
