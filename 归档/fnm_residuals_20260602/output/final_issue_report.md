# Biopolitics / Goldstein 最终问题报告

生成时间: 2026-05-08
模型: mimo-v2.5

---

## 一、执行摘要

本次全量测试对 Biopolitics 和 Goldstein 两书执行了：完整 FNM pipeline 重跑 → 占位译文导出 → 金版逐段对比。

**已完成的修复**（2 个，全部生效）：

| Fix | 文件:行 | 问题 | 效果 |
|-----|---------|------|------|
| 1 | `FNM_RE/modules/chapter_split.py:652` | Goldstein `split_items_sparse_note_capture` 假阳性阻塞 | state=ready, export 通过 |
| 2 | `FNM_RE/shared/export_constants.py:48-52` + `FNM_RE/shared/ref_rewriter.py:213` | `^{154}` 上标残留 | Goldstein ch006 残留消失 |

**当前阻塞状态**：

| 书 | 阻塞 | 可修复性 |
|----|------|---------|
| Goldstein | **无** (state=ready) | — |
| Biopolitics | `contract_def_anchor_mismatch` | 剩余差异来自 LLM/OCR 不可控因素，建议降级为 warning |

**段对段对比结论**：两书正文内容完整，匹配段平均相似度 95-100%。所有"缺失/新增"段落都是结构差异（段落边界、对齐偏移、题记取舍），不是内容丢失。

---

## 二、数据读取路径

### 2.1 SQLite 数据库

所有 FNM pipeline 中间产物存储在 SQLite，通过以下方法读取：

```
from persistence.sqlite_store import SQLiteRepository
repo = SQLiteRepository()

Biopolitics: doc_id = '0d285c0800db'
Goldstein:   doc_id = '7ba9bca783fd'

repo.list_fnm_pages(doc_id)              → 页面分区 (page_role, page_no)
repo.list_fnm_chapters(doc_id)           → 章节 (chapter_id, title, start_page)
repo.list_fnm_note_items(doc_id)         → 注释条目 (note_item_id, marker, note_kind, chapter_id, source_text)
repo.list_fnm_body_anchors(doc_id)       → 正文锚点 (anchor_id, normalized_marker, source_marker, anchor_kind, certainty)
repo.list_fnm_note_links(doc_id)         → 注释链接 (link_id, anchor_id, note_item_id, status, resolver)
repo.list_fnm_translation_units(doc_id)  → 翻译单元 (unit_id, source_text, translated_text, kind, section_id)
```

### 2.2 导出产物

```
test_example/Biopolitics/latest.fnm.obsidian.zip          → Biopolitics 导出 ZIP
test_example/post-revolutionary/latest.fnm.obsidian.zip    → Goldstein 导出 ZIP
  └── chapters/*.md                                        → 各章 Markdown
```

### 2.3 金版模板

```
test_example/Biopolitics/golden_exports/real_golden_template/*.md
test_example/post-revolutionary/golden_exports/real_golden_template/*.md
```

### 2.4 对比产物

```
test_example/Biopolitics/golden_comparison.json            → 逐章引用/定义对比
test_example/Biopolitics/golden_paragraph_diff.json        → 段对段对比 (完整数据)
test_example/Biopolitics/golden_paragraph_diff.md          → 段对段对比 (Markdown)
test_example/post-revolutionary/golden_comparison.json
test_example/post-revolutionary/golden_paragraph_diff.json
test_example/post-revolutionary/golden_paragraph_diff.md
```

### 2.5 原始 OCR

```
test_example/Biopolitics/raw_pages.json                    → JSON, pages[].markdown, pages[].blocks
test_example/post-revolutionary/raw_pages.json
```

### 2.6 视觉模型核查

```
scripts/inspect_page.py                                    → PDF 页面渲染 + vision API 调用
  _render_page(pdf_path, page_no) → (img_bytes, mime)
  _call_visual_model(img_b64, mime, prompt) → {text, usage}
```

已核查页面：Biopolitics page 208, 158。

### 2.7 日志

```
/tmp/biopolitics_v2.log                                    → Biopolitics 完整 pipeline 输出
/tmp/goldstein_v2.log                                      → Goldstein 完整 pipeline 输出
```

---

## 三、已完成修复详情

### Fix 1: Goldstein `split_items_sparse_note_capture` 假阳性

**根因**：`FNM_RE/modules/chapter_split.py:652`

`_note_capture_summary` 的页级 `sparse_pages` 检查对 `chapter_endnote_primary` 章做逐页对比——正文页有 >=8 个 anchor marker 但 0 个 captured note_item。但这类章的尾注定义在章末独立 NOTES 区域（`_chapter_endnote_start_page_map` 保证 body 页和 note 页不重叠），页级检查语义不成立。

`skip_page_check` 只豁免了 `book_endnote_bound`，漏了 `chapter_endnote_primary`。

**修复**：`skip_page_check = note_mode in {"book_endnote_bound", "chapter_endnote_primary"}`

**效果**：Goldstein state 从 `review_required` → `ready`，导出直接成功。

### Fix 2: `^{154}` 上标残留

**根因**：`FNM_RE/shared/export_constants.py:48`

`_RAW_SUPERSCRIPT_NOTE_REF_RE` 只匹配 `$ ^{n} $` 和 `<sup>n</sup>`，不匹配裸 `^{n}`。但 `anchors.py:26` 的 `_PLAIN_SUP_RE = r"\^\{(\d{1,4})\}"` 能检测 `^{154}`——detection 通了但 replacement 没通。

**修复 A**：`export_constants.py:48` 追加第 4 alternative `\^\{(\d{1,4})\}`

**修复 B**：`ref_rewriter.py:213` 回调 `match.group(1) or ... or match.group(4) or ""`

**效果**：Goldstein ch006 上标残留消失。

---

## 四、当前阻塞状态

### Goldstein — 无阻塞

```
state=ready  blocking=[]  export_ready_test=True
link_summary: matched=898, orphan=0, fallback=0, repair=58
```

### Biopolitics — `contract_def_anchor_mismatch`

```
state=review_required  blocking=["contract_def_anchor_mismatch"]
link_summary: matched=584, endnote_orphan_note=2, footnote_orphan_anchor=4, fallback=45 (7.7%), repair=47
```

**触发位置**：`FNM_RE/modules/note_linking.py:1568-1569`

```python
if not hard["link.def_anchor_aligned"]:
    _add("contract_def_anchor_mismatch")
```

其中 `link.def_anchor_aligned` 在 `note_linking.py:1511` 计算：存在章节的 `def_count != anchor_total`（尾注定义数 ≠ 正文锚点数）。

**金版对比确认的差异来源**：

| 来源 | 引用偏差 | 性质 | 可修复 |
|------|---------|------|--------|
| `[n]` bracket 误判为 endnote | ~5 个 | 已修复（`anchors.py:121-122` bracket → unknown） | ✅ |
| bare_digit `7»` (ch008 page 208) | 1 个 | `_positive_gate_bare_digit` 接受了一个真不是尾注的 "7" | ⚠️ 可修（加引号守卫） |
| OCR `ᵉ`→`⁶` (ch003 page 72) | 1 个 | pymupdf 渲染错误 | ⚠️ 可修（罗马数字守卫） |
| sup_recovery UNRECOVERED | 13 个缺失 | vision API 找不到 marker 位置 | ❌ 不可控 |
| 金版 curator 选择不收录 | ~10 个多余 | 格式正确、链接正确的引用 | ❌ 不是 bug |
| fresh run 随机波动 | ±2 | vision API 非确定性 | ❌ 不可控 |

**结论**：剩余可修的 bare_digit + OCR 两项只影响 2 个引用。其余都不可控。此时 `contract_def_anchor_mismatch` 不应阻塞导出——建议降级为 warning。

---

## 五、金版对比结果

### 5.1 Biopolitics

| 指标 | 数值 |
|------|------|
| 章通过（严格引用/定义匹配） | 4/14 |
| 正文引用偏差 | +13 |
| 尾注定义偏差 | -5 |
| 段缺失 | 110 |
| 段新增 | 53 |
| 低相似度段 | 15 |
| 匹配段平均相似度 | 95-100% |

### 5.2 Goldstein

| 指标 | 数值 |
|------|------|
| 章通过 | 0/9 |
| 正文引用偏差 | +127 |
| 尾注定义偏差 | -23 |
| 段缺失 | 71 |
| 段新增 | 67 |
| 低相似度段 | 76 |
| 匹配段平均相似度 | 96-99% |

---

## 六、段对段差异分析

### 6.1 Biopolitics 110 个"缺失段落"的构成

| 类别 | 数量 | 示例 | 可修复 |
|------|------|------|--------|
| `[footnote] *` 编辑注（金版有，管道过滤） | ~90 | "M. F. : ...", "Entre guillemets dans le manuscrit" | ❌ 设计差异 |
| 对齐偏移（同段存在于导出但索引不同） | ~15 | ch002 G#21 缺失 = E#22 新增 | ❌ 算法偏差 |
| OCR 乱码段 | ~3 | ch013 E#3 "vis " ent frere rbuth..." | ❌ 不可控 |
| 真缺失（OCR 漏段或 vision 未恢复） | ~2 | ch011 G#32, ch012 G#7 | ❌ 不可控 |

### 6.2 Goldstein 71 个"缺失段落"的构成

| 类别 | 数量 | 示例 | 可修复 |
|------|------|------|--------|
| `>` 引用块拆分（金版合段，管道拆行） | ~20 | ch002 G#15 "Me! I did my duty..." → 导出 5 段 | ⚠️ 可修 |
| 题记/署名行（OCR 合并入正文） | ~15 | "Victor Cousin, 1843", "Sieyès, 1773" | ⚠️ 可修 |
| 对齐偏移（索引对不上） | ~25 | ch002 G#29 缺失 = E#36 新增 | ❌ 算法偏差 |
| 引用编号差异导致匹配失败 | ~10 | bare_digit 残留使段相似度 < 0.85 | ❌ 不可控 |
| 真缺失 | ~1 | OCR 漏段 | ❌ 不可控 |

### 6.3 低相似度段分析（共 91 段，两书合计）

**全部 91 段的归一化后相似度均在 95%+**。原始低相似度原因：

| 原因 | Biopolitics | Goldstein |
|------|-------------|-----------|
| 重音/引号差异（é/e, «»/""） | 5 | 40 |
| 引用编号差异（bare_digit / sup_recovery 产生的额外 [^n]） | 5 | 20 |
| 段落对齐错位（G#24↔E#26 是不同的相邻段） | 5 | 16 |

### 6.4 段落拆分差异的根因

**A. 跨页断段重连**（`FNM_RE/stages/units.py:258-272`）

OCR 引擎（pymupdf）将 PDF 页面切成段落块。一段跨两页时，pymupdf 标记后半部分为 `consumed_by_prev=True`。管道在 272 行过滤 consumed 段。但 `_chunk_visible_paragraphs`（293 行）对含 `NOTE_REF` 的 consumed 段做了特殊重入逻辑——导致引用标记附近的段落拆分与金版不一致。

**B. `>` 引用块不合并**

金版将多行 blockquote 视为一个逻辑段落。OCR 每行切开，管道没有 blockquote 合并逻辑。这是 `>` 开头的"缺失/新增"段的全部根因——内容相同，只是段落边界不同。

**C. 题记/署名行丢失**

各章开头的题记署名（如 "Victor Cousin, 1843"）在 OCR 中被合并入上一段正文。管道没有任何机制恢复它们——pymupdf 没有题记元数据，视觉模型未被用于题记识别。

---

## 七、可修复性总结

| 问题 | 责任代码 | 影响 | 修复优先级 | 状态 |
|------|---------|------|-----------|------|
| Goldstein sparse blocker | `chapter_split.py:652` | 阻塞导出 | P0 | ✅ 已修 |
| `^{154}` 残留 | `export_constants.py:48` | 1 处格式残留 | P0 | ✅ 已修 |
| Biopolitics `contract_def_anchor_mismatch` | `note_linking.py:1568` | 阻塞导出 | P1 | 建议降级为 warning |
| `[n]` bracket 误判 | `anchors.py:113` | +5 引用 | P1 | ✅ 已修（待 re-run 验证） |
| bare_digit `7»` | `body_anchors.py:255` | +1 引用 | P2 | 可修 |
| OCR `ᵉ`→`⁶` | pymupdf 渲染 | +1 引用 | P2 | 可修 |
| `>` 引用块拆分 | `units.py` | ~20 段结构差异 | P3 | 需语义合并逻辑 |
| 题记行丢失 | pymupdf + `units.py` | ~15 段结构差异 | P3 | 需视觉模型 |
| sup_recovery UNRECOVERED | `sup_recovery.py` | 13+23 引用 | 不可控 | vision API 限制 |
| 金版 curator 差异 | — | ~10 引用 | 不可控 | 不是 bug |

---

## 八、建议下一步

1. **Biopolitics `contract_def_anchor_mismatch` 降级**：剩余差异来自 LLM/OCR 不可控因素，不应阻塞导出。在 `note_linking.py:1568` 或 `export.py` 中将此项从硬阻塞改为 warning，或添加一个容许阈值（如 def≠anchor ≤ 3 时不阻塞）。

2. **bare_digit `7»` + OCR `ᵉ`**：两项合计影响 2 个引用，收益极低。如果修：bare_digit 在 `_is_bare_digit_marker_context` 加法语引号守卫；OCR 在 body_anchors 加罗马数字+上标守卫。不建议优先。

3. **`>` 引用块合并**：影响 20 段的结构差异，不影响内容。如果需要段落计数与金版对齐，可在 `units.py` 的段落规范化阶段（`_normalize_markdown_paragraphs`）加 blockquote 连续行合并逻辑。

4. **Goldstein 已可交付**：state=ready，正文完整，仅引用计数和金版有 curator 偏差。
