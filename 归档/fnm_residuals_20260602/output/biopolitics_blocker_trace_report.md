# Biopolitics 阻塞原因逐条追溯报告

生成时间: 2026-05-08
数据源: SQLite `0d285c0800db`, `test_example/Biopolitics/latest.fnm.obsidian.zip`, `golden_comparison.json`, `golden_paragraph_diff.json`

---

## 一、当前阻塞

```
state=review_required  blocking=["contract_def_anchor_mismatch"]
```

触发路径: `note_linking.py:1568` → `hard["link.def_anchor_aligned"] = False` → 至少一章 `def_count != anchor_total`

过滤 `anchor_kind="endnote"` 后（修复 `note_linking.py:1171`），仍有 3 章 mismatch:

| 章 | def | anchor(endnote) | Δ | 根因 |
|----|-----|-----------------|---|------|
| ch003 | 34 | 36 | -2 | 2个star-endnote吞噬编号，导致2个anchor marker找不到对应def |
| ch010 | 37 | 36 | +1 | en-00384 (marker=11) orphan note, sup_recovery UNRECOVERED |
| ch012 | 33 | 36 | -3 | 1个star-endnote + OCR过度检测 + anchor > def |

---

## 二、引用差异逐条追溯

数据读取路径:
- SQLite: `repo.list_fnm_note_items('0d285c0800db')`, `repo.list_fnm_body_anchors(...)`, `repo.list_fnm_note_links(...)`, `repo.list_fnm_translation_units(...)`
- 导出: `test_example/Biopolitics/latest.fnm.obsidian.zip` → `chapters/*.md`
- 金版: `test_example/Biopolitics/golden_exports/real_golden_template/*.md`
- 对比: `test_example/Biopolitics/golden_comparison.json`
- 视觉验证: `scripts/inspect_page.py` — Biopolitics page 208, 158 已核查

### 2.1 缺失引用（金版有，导出无）—— 13 个

#### ch002 [^17]

```
读取: repo.list_fnm_note_items → en-00035, marker=17, page=65, note_kind=endnote
      repo.list_fnm_note_links → anchor=anchor-00619, status=matched, resolver=rule
      repo.list_fnm_body_anchors → anchor-00619, page=61, source_marker='17', anchor_kind=endnote
      repo.list_fnm_translation_units → body unit 不含 {{NOTE_REF:en-00035}}
```

**根因**: anchor-00619 (source='17') 存在且已链接，但 `ref_freeze` 没有将 `{{NOTE_REF:en-00035}}` 注入到正文翻译单元中。`source_marker='17'` 是 bare_digit 格式（cert=0.6），ref_freeze 可能没有匹配到该 marker 在正文中的位置。

**分类**: **程序BUG** — ref_freeze 注入失败

#### ch003 [^1]

```
读取: en-00038, marker=1, page=86, linked to anchor-00045 (page=67, source='<sup>1</sup>')
      body unit du24janvier1979-0001 含 {{NOTE_REF:en-00038}}
      导出仿真: en-00038 → num=1 ✓
      实际导出: [^1]出现次数=0
```

**仿真与实际导出不一致**。en-00038 在正文翻译单元中，仿真编号为 1，但实际导出文本无 [^1]。

**分类**: **程序BUG** — `apply_body_unit_translations` 或 `_resolve_body_unit_text` 在重构正文时丢失了该 ref token。需进一步追查 Phase 4 `build_fnm_body_unit_jobs` → `apply_body_unit_translations` 的文本转换链路。

#### ch003 [^24], [^25]

```
读取: en-00061 (marker=24, page=88), en-00062 (marker=25, page=88)
      均已链接，body unit du24janvier1979-0003 含对应 NOTE_REF token
      仿真: en-00061 → 26, en-00062 → 27（+2 偏移）
      根因: en-00036 (marker='*') 和 en-00037 (marker='**') 在 _local_endnote_ref_number 中
            各消耗了一个顺序编号（20 和 21），导致全部后续 endnote +2
```

**根因链路**:
1. Phase 2 (`book_note_type.py`): en-00036 和 en-00037 被分类为 `note_kind=endnote`（它们在尾注区域）
2. Phase 6 (`export.py:460-467`): `note_marker_by_id` 只收录 digit marker → en-00036/37 不在表中
3. Phase 6 (`ref_rewriter.py:93-102`): `_local_endnote_ref_number` 对 en-00036/37:
   - `kind=endnote` → 不进入 footnote 分支 ×
   - `original = note_marker_by_id.get("en-00036", "")` → `""`（不在表中）
   - `original.isdigit()` → False
   - 落入 `max(local_ref_numbers.values()) + 1` → 消耗编号 20 和 21

**分类**: **程序BUG** — `_local_endnote_ref_number` 对 non-digit marker 的 endnote item 没有特殊处理

**影响**:
- en-00057 (marker=20) → 22, en-00058 (21) → 23, en-00059 (22) → 24, en-00060 (23) → 25
- en-00061 (24) → 26, en-00062 (25) → 27 —— 金版期望的 [^24][^25] 被渲染为 [^26][^27]
- 导致金版对比中: missing [^24][^25], extra [^22][^23][^33][^34]（对齐偏移的连锁反应）

#### ch006 [^61]

```
读取: en-00237, marker=61, page=177, linked to anchor-00295 (page=166, source='<sup>61</sup>')
      body unit du14février1979-0003 含 {{NOTE_REF:en-00237}}
      仿真: en-00237 → 61 ✓
      实际导出: [^61]出现次数=0
```

**同 ch003 [^1] 的问题** — 仿真正确但实际导出缺失。

**分类**: **程序BUG** — 与 ch003 [^1] 同一根因（`apply_body_unit_translations` 文本重构丢失 ref token）

#### ch006 [^62]

```
读取: repo.list_fnm_note_items → ch006 无 marker=62 的 endnote item
      ch006 只有 markers 1-61
```

**分类**: **Phase 2 提取缺口** — 金版有 endnote 62，pipeline 的 OCR/note extraction 未提取到该条

#### ch008 [^9]

```
读取: en-00288, marker=9, page=226, linked to visual-00007 (page=207, source='9')
      resolver=repair (LLM修复), anchor_kind=endnote
      body unit eçondu7mars1979-0001 含 {{NOTE_REF:en-00288}}
      上下文: "interventi{{NOTE_REF:en-00288}}onnistes"（visual recovery 注入在词中间）
      仿真: en-00288 → 9 ✓
      实际导出: [^9]出现次数=0
```

**LLM 修复记录**: 该 marker 由 `visual_anchor_recovery` 通过视觉模型恢复（anchor_id=visual-00007）。LLM 正确标识了 marker=9 的位置（page 207），但注入位置不精确（词中间）。

**分类**: **程序BUG** — 与 ch003 [^1] 同一根因（文本重构丢失 ref token）。LLM 修复本身正确。

#### ch010 [^11]

```
读取: en-00384, marker=11, page=279, link_status=orphan_note
      anchor=NONE, body_unit 不含 NOTE_REF
```

**分类**: **LLM不可控** — `sup_recovery` 未能找到 marker 11 的正文位置（33个UNRECOVERED之一）。对数: `sup_recovery` L3 vision 扫描了 3 层页面（page 279±N），均返回 REJECTED。

**LLM 记录**: 需查 `test_example/Biopolitics/llm_traces/` 中 sup_recovery 相关 trace。该 marker 的 L3 扫描日志在 `/tmp/biopolitics_v2.log` 中可见：
```
[sup_recovery] UNRECOVERED ch=toc-ch-010-leçondu21mars1979 marker=11
```

#### ch011 [^19]

```
读取: en-00429, marker=19, page=304, linked to anchor-00532 (page=290, source='<sup>19</sup>')
      body unit çondu28mars1979-0001 含 {{NOTE_REF:en-00429}}（2次）
      仿真: en-00429 → 19 ✓
      实际导出: [^19]出现次数=0
```

**分类**: **程序BUG** — 与 ch003 [^1] 同一根因

#### ch012 [^1]

```
读取: en-00449, marker=1, page=329, linked to anchor-00555 (page=308, source='<sup>1</sup>')
      body unit çondu4avril1979-0001 含 {{NOTE_REF:en-00449}}
      仿真: en-00449 → 1 ✓
      实际导出: [^1]出现次数=0
      注: ch012 有 star endnote en-00448 (marker='*')，消耗编号 25，但不影响 [^1]（* 在后面）
```

**分类**: **程序BUG** — 与 ch003 [^1] 同一根因

#### ch014 [^9]

```
读取: ch014 无 marker=9 的 endnote item (ch014='SITUATION DES COURS', 非正文章)
      金版 marker=9: 对应某条定义在 ch014 区域的引用
```

**分类**: **Phase 2 边界问题** — ch014 是后记/附录章，金版包含该章的引用但 pipeline 的 body_anchors 未在该区域检测到 marker（ch014 的 anchor 全部是 footnote/unknown kind）。

---

### 2.2 多余引用（导出有，金版无）—— ~15 个 + 重复

所有多余引用的 `source_marker` 和链接状态:

| 引用 | anchor | page | source | linked | 原因 |
|------|--------|------|--------|--------|------|
| ch001 [^1] | anchor-00001 | 17 | `<sup>1</sup>` | YES | 正确检测，金版不收录 |
| ch002 [^7]×2 | anchor-00034/42 | 48/61 | `<sup>7</sup>` | YES+NO | 1个真引用，1个无定义假阳性 |
| ch003 [^6]×2 | anchor-00049/51 | 72 | `<sup>6</sup>` | YES+NO | 同上 |
| ch003 [^22] | anchor-00076 | 82 | `<sup>22</sup>` | YES | star-endnote 偏移导致编号错位 |
| ch003 [^23] | anchor-00077 | 82 | `<sup>23</sup>` | YES | star-endnote 偏移导致编号错位 |
| ch004 [^6]×3 | anchor-00097/116/122 | 94/96 | `$ ^{6} $`/`<sup>6</sup>`/`⁶` | YES+NO×2 | OCR多重检测 |
| ch004 [^27]×3 | anchor-00117/123/129 | 96/101 | `<sup>27</sup>`/`²⁷`/`$ ^{27} $` | YES+NO×2 | OCR多重检测 |
| ch004 [^31]×3 | anchor-00118/124/133 | 96/103 | `<sup>31</sup>`/`³¹`/`$ ^{31} $` | YES+NO×2 | OCR多重检测 |
| ch004 [^44]×2 | anchor-00107/146 | 95/105 | `$ ^{44} $` | YES+NO | 同上 |
| ch006 [^36] | anchor-00268 | 158 | `<sup>36</sup>` | YES | 视觉模型确认真标记，金版不收录 |
| ch006 [^37] | anchor-00269 | 158 | `<sup>37</sup>` | YES | 同上 |
| ch006 [^38] | anchor-00262 | 157 | `<sup>38</sup>` | YES | 同上 |
| ch009 [^1]×3 | anchor-00415/426/429 | 233/237 | `¹`/`$ ^{1} $` | YES+NO×2 | OCR多重检测 |
| ch009 [^41]×4 | anchor-00459/460/463/464 | 249 | `<sup>41</sup>` | YES+NO×3 | OCR多重检测 + 真引用 |
| ch010 [^3]×2 | anchor-00473/501 | 260/271 | `<sup>3</sup>` | YES+NO | 同上 |
| ch011 [^8]×2 | anchor-00518 | 286 | `$ ^{8} $` | YES | 段落重复（同一NOTE_REF出现2次） |
| ch011 [^9]×2 | anchor-00519 | 286 | `$ ^{9} $` | YES | 同上 |
| ch011 [^18] | anchor-00526 | 289 | `<sup>18</sup>` | YES | 正确检测，金版不收录 |
| ch012 [^33] | anchor-00566 | 319 | `<sup>33</sup>` | YES | 同上 |

**分类汇总**:

| 类别 | 数量 | 说明 |
|------|------|------|
| 正确检测，金版curator不收录 | ~10 | `<sup>n</sup>` 格式正确，有链接，有定义。视觉模型确认page 158的[^36-38]是真标记 |
| OCR多重检测（同一marker被`<sup>`, `$^{}$`, unicode `⁶`分别检测） | ~15 | 多次检测但只有1次链接成功。unlinked的出现在export中（通过ref_freeze的其他路径） |
| star-endnote编号偏移连锁反应 | ~2 | ch003 [^22][^23]因此被标记为extra |
| 段落重复 | ~2 | ch011 [^8][^9]同段落出现2次 |

---

## 三、程序BUG分类

### BUG-1: star-marker endnote 吞噬编号

**位置**: `FNM_RE/shared/ref_rewriter.py:82-104` `_local_endnote_ref_number`
**触发**: endnote item 的 marker 不是数字（`*`, `**`）时，`note_marker_by_id` 不含此 item，`original=""`, 落入 `max+1` 分支
**影响**: ch003（2个star，+2偏移）, ch012（1个star，+1偏移）
**修复**: `_local_endnote_ref_number` 中: 如果 `original == ""` 且 `kind == "endnote"`, 读取 item 原始 marker——若非digit则返回 None（输出为 `*`）

### BUG-2: body text 重构丢失 ref token

**位置**: `FNM_RE/page_translate.py:451` `apply_body_unit_translations`
**触发**: 仿真编号正确但实际导出缺失。仿真用 `unit.translated_text` 直接读，实际导出经过 `apply_body_unit_translations` → `build_fnm_body_unit_jobs` 重构
**影响**: ch003 [^1], ch006 [^61], ch008 [^9], ch011 [^19], ch012 [^1] — 共 5 个缺失引用
**修复**: 需追查 `apply_body_unit_translations` 的文本重构逻辑，确认 `{{NOTE_REF:xxx}}` token 是否在段落重组中丢失

### BUG-3: ref_freeze 注入失败

**位置**: `FNM_RE/modules/ref_freeze.py`
**触发**: anchor 已链接但 body unit 不含 `{{NOTE_REF:note_id}}`
**影响**: ch002 [^17]（anchor-00619, source='17' bare_digit）
**修复**: 需追查 ref_freeze 对 bare_digit marker 的处理

---

## 四、LLM不可控差异

| 引用 | 机制 | LLM记录 |
|------|------|---------|
| ch010 [^11] | sup_recovery UNRECOVERED | L3 vision扫描page 279±N, 全部REJECTED |
| ch006 [^62] | Phase 2 提取缺口（无此note_item） | 非LLM问题，OCR未提取到该endnote定义 |
| ch014 [^9] | Phase 2 边界问题（ch014非正文章） | 非LLM问题 |

注: 其他 `sup_recovery UNRECOVERED`（共33个marker）中，仅 ch010 [^11] 对应金版缺失引用。其余 UNRECOVERED marker 要么有对应的 `{{NOTE_REF:xxx}}` 通过其他方式（bare_digit / repair）恢复了，要么金版也没有。

---

## 五、修复优先级

| 优先级 | Bug | 影响引用数 | 修复位置 |
|--------|-----|-----------|---------|
| P0 | BUG-1 star-endnote吞噬编号 | ch003 Δ=2, ch012 Δ=1 | `ref_rewriter.py:95` |
| P0 | BUG-2 文本重构丢失ref | 5个缺失引用 | `page_translate.py:451` |
| P1 | BUG-3 ref_freeze注入失败 | 1个缺失引用 | `ref_freeze.py` |
| P2 | OCR多重检测 | ~15个多余 | body_anchors + sup_recovery |
| P2 | 段落重复 | ch011 2个 | units.py (已知) |
| — | 金版curator不收录 | ~10个多余 | 非bug |
| — | sup_recovery UNRECOVERED | 1个缺失 | LLM不可控 |
