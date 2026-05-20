# Biopolitics 22 orphan endnote 问题分析

## 现象

Biopolitics（福柯《生命政治的诞生》，370 页法语书）在 Phase 3-6 完整运行后报告 **22 个 endnote_orphan_note**，导致 `contract_def_anchor_mismatch`、`freeze_error_skip_detected`、`merge_local_refs_unclosed`、`export_audit_blocking` 四个阻塞原因。全书 493 个尾注中 22 个（4.5%）没有匹配到 body anchor。

## 追踪方法

以 en-00026（marker=8, ch-002 "Leçon du 17 janvier 1979"）为例，从原书 PDF 页面出发，逐层追踪数据流：

PDF 页面渲染 → OCR markdown → Phase 2 anchor 检测 → Phase 3 link 匹配 → LLM repair → Phase 4 注入 → Phase 5 导出

使用了 MiMo V2.5、GLM-5V-Turbo 两个视觉模型交叉验证、raw_pages.json 原文、SQLite 数据库持久化数据、全书索引页交叉引用。

## 根因（三层叠加）

### 第 1 层：Phase 1 页面分类遗漏

ch-002 的 page 64（PDF page 64，bookPage 64）的实际内容结构：

```
上半部分（正文结尾）:
  "...rien n'est plus aisé à déterminer que le bon prix : 
   c'est le prix commun et peu variable du marché génér..."

下半部分（尾注定义区域）:
  5. Cf. A. Marshall, Principles of Economics, Londres, Macmillan & Co., 1890...
  6. Sur cette nouvelle définition du marché comme lieu de véridiction...
  7. Cf. Sécurité, Territoire, Population, leçon du 18 janvier 1978, p. 33 sq.
  8. Cette expression est déjà utilisée par Foucault dans la conférence prononcée...
  9. Sur le rapport de Foucault à l'École de Francfort...
  10. Auteur du célèbre traité Dei delitti e delle pene...
```

`raw_pages.json` 中 page 64 的 `_note_scan.page_kind = "body"`——整页被分类为正文页。尾注定义区域的编号（5-10）未被识别为 note definition，而是被当作页面正文内容。

### 第 2 层：Phase 2 anchor 误检

`body_anchors.py` 的 `scan_anchor_markers` 扫描 page 64 时，`_BARE_DIGIT_RE` 匹配了行首的 `8.`（定义编号），创建了一个 body anchor：

```
BodyAnchorRecord:
  source_marker = "8"          ← 裸数字，无格式
  normalized_marker = "8"
  page_no = 64
  anchor_kind = "unknown"
```

这本质上是**假阳性**——把尾注定义编号当成了正文中的 note marker。真正的正文 marker 8 应该在 ch-002 的前部正文页面（pages 43-62），但 OCR 丢失了它的上标格式（superscript ⁸ 被渲染为普通文本或误读为其他字符，与 page 262 上 "Migué 9" 和 "lu 10" 的模式相同）。

### 第 3 层：Phase 4 跳过注入 + 连锁 orphan

LLM repair（52 次 MIMO 调用）在 page 64 的 `8.` 位置创建了 `llm-anchor-en-00026`，override payload 为：

```json
{
  "action": "create",
  "source_marker": "8",
  "normalized_marker": "8",
  "anchor_kind": "endnote",
  "synthetic": false
}
```

LLM repair 创建的 anchor 的 `source_marker` 是裸数字 "8"（来自 `_materialize_anchor_overrides` 用 `normalized_marker` 填充 `source_marker`），而非页面上的实际标记格式（如 `$^{8}$` 或 `<sup>8</sup>`）。

进入 Phase 4 `ref_freeze.py:291-299`：

```python
if bool(anchor.synthetic):
    sm = str(anchor.source_marker or "").strip()  # "8"
    nm = str(anchor.normalized_marker or "").strip()  # "8"
    if sm == nm:  # "8" == "8" → True
        _append_skipped("synthetic_anchor")  # ← 跳过！
        continue
```

Phase 4 正确跳过了这个裸数字 anchor——但真正的正文 marker 8 从未被检测到（OCR 格式丢失），所以 en-00026 没有任何可注入的 anchor。link 保持 `orphan_note` 状态进入 Phase 5。

### 数据流完整追踪

```
PDF page 64
  ├─ 上半: 正文结尾 "rien n'est plus aisé..."
  └─ 下半: 尾注定义 "8. Cette expression est déjà utilisée par Foucault..."

↓ OCR (markdown)
  "8. Cette expression est déjà utilisée par Foucault dans la conférence..."

↓ Phase 1 (page_partition.py)
  page_role = "body"  ← 整页被分类为 body
  _note_scan.page_kind = "body"  ← 尾注定义区域未被识别

↓ Phase 2 (body_anchors.py)
  _BARE_DIGIT_RE 匹配 "8." → anchor(source_marker="8", page=64)  ← 假阳性！

↓ Phase 2 正文中的真 marker 8
  未检测到（OCR 丢失了 superscript ⁸ 的格式，可能表现为裸数字或误读）

↓ Phase 3 (note_links.py)
  en-00026(marker=8) 无匹配 anchor → orphan_note

↓ LLM repair
  创建 llm-anchor-en-00026(source_marker="8", page=64)  ← 在假阳性位置
  创建 link override (link-00026 → llm-anchor-en-00026)

↓ Phase 4 rebuild (ref_freeze.py)
  anchor.synthetic=False, sm="8", nm="8" → sm==nm → skip  ← 正确跳过
  link-00026 仍为 orphan_note

↓ Phase 5 export
  en-00026 无 body 引用 → local_ref_numbers 补入 → 编号 138
  但 body text 中无 [^138]
  → merge_local_refs_unclosed → contract 失败
  → export_audit_blocking
```

## 影响范围

22 个 orphan endnote 均遵循此模式，分布在多个章节：

| 章节 | 受影响 marker | 共同特征 |
|------|-------------|---------|
| ch-002 | 8, 14, 17 | page 64 分类错误 + OCR 格式丢失 |
| ch-004 | 14, 20, 22, 23 | 类似模式 |
| ch-006 | 27, 40 | 类似模式 |
| ch-007 | 10, 18, 23, 24, 25, 32, 33, 34, 35 | 类似模式 |
| ch-008 | 9, 45 | 类似模式 |
| ch-009 | 11, 36 | 类似模式 |
| ch-010 | 9, 10, 11, 25 | 类似模式 |
| ch-012 | 11, 19 | 类似模式 |
| ch-014 | 9 | 类似模式 |

共同模式：章节末的混合页（正文+尾注定义）未被正确分类 → 定义编号被误检为 body marker → 正文中真标记的 OCR 格式丢失 → LLM repair 在假阳性位置创建裸数字 anchor → Phase 4 跳过 → orphan。

## 修复方向

问题在 Phase 1/2 层面，不在 Phase 4/5：

1. **Phase 1**：改进 `_note_scan` 对混合页（body + endnote definitions）的检测，将尾注定义行识别为 `note_start_line_index` 而非正文
2. **Phase 2**：对检测到的 anchor，如果 `source_marker` 是裸数字且上下文匹配 `_NOTE_DEFINITION_LINE_RE`（行首数字+点+空格），标记为 note definition 而非 body marker
3. **LLM repair**：修复 `_materialize_anchor_overrides` 中 `source_marker = normalized_marker` 的问题——应使用 LLM 提供的 `matched_text` 或从页面搜索实际标记格式

## 附录：为什么不是 gap_fill 删除导致的问题

删除 gap_fill 之前，gap_fill 会"算术补全"缺失的 marker 序列。对于 ch-002，gap_fill 发现 markers 1-17 中缺少 14，会创建一个 `source_marker=""` 的 synthetic anchor。这个空壳 anchor 在 Phase 4 会因为 `sm="" != nm="14"` 而通过 bare digit 检查，但进入 `_inject_token_once` 后会因 `source_marker=""` 而无法匹配任何页面文本（`token_not_found`）。所以 gap_fill 从未真正解决 orphan 问题——它只是制造了"有 anchor"的假象，而孤儿本质（正文引用丢失）从未改变。

删除 gap_fill 后：
- Phase 3 orphan_note 数量可能增加（少了 gap_fill 制造的假 anchor）
- 但 orphan_note 是**真实暴露**而非新增——正文 marker 的 OCR 丢失问题本就存在
- 修复应集中在 Phase 1/2 层面改进检测和分类，而非在下游制造假数据
