# Biopolitics / Goldstein 金版对比汇总报告

生成时间: 2026-05-07
FNM 模型: mimo-v2.5 (custom token-plan + builtin)
翻译模式: 测试占位符

---

## Biopolitics

| 指标 | 数值 |
|------|------|
| Pipeline | pages=370, chapters=14, notes=588, anchors=657 |
| Links | matched=584, fallback=44 (7.5%), repair=49, orphan_anchor=2, orphan_note=2 |
| 阻塞原因 | contract_def_anchor_mismatch |
| 章通过 | **3/14** (21%) |
| 问题数 | 41 |
| 正文引用 | 导出 498 vs 金版 484 (+14) |
| 尾注定义 | 导出 487 vs 金版 491 (-4) |
| 段缺失 | 110 |
| 段新增 | 57 |
| 低相似度段 | 16 |

### 逐章相似度

| 章 | 相似度 | 引用 | 定义 | 通过 |
|----|--------|------|------|------|
| 001-Leçon du 10 janvier 1979 | 33.2% | 19/18 | 18/18 | ✗ |
| 002-Leçon du 17 janvier 1979 | 57.0% | 16/16 | 16/17 | ✗ |
| 003-Leçon du 24 janvier 1979 | 65.1% | 32/29 | 33/32 | ✗ |
| 004-Leçon du 31 janvier 1979 | 96.9% | 57/53 | 53/53 | ✗ |
| 005-Leçon du 7 février 1979 | 94.3% | 54/54 | 54/54 | ✓ |
| 006-Leçon du 14 février 1979 | 78.6% | 62/62 | 60/62 | ✗ |
| 007-Leçon du 21 février 1979 | 89.4% | 42/42 | 42/42 | ✓ |
| 008-Leçon du 7 mars 1979 | 99.1% | 51/52 | 51/52 | ✗ |
| 009-Leçon du 14 mars 1979 | 97.1% | 43/41 | 42/42 | ✗ |
| 010-Leçon du 21 mars 1979 | 89.7% | 36/36 | 36/37 | ✗ |
| 011-Leçon du 28 mars 1979 | 86.2% | 41/36 | 37/37 | ✗ |
| 012-Leçon du 4 avril 1979 | 84.5% | 33/32 | 33/32 | ✗ |
| 013-RÉSUMÉ DU COURS | 91.7% | 0/0 | 0/0 | ✓ |
| 014-SITUATION DES COURS | 99.9% | 12/13 | 12/13 | ✗ |

### 主要差异模式

1. **跨章编号偏移**: Biopolitics 全书尾注连续编号，第 1 章从 marker 5 开始（而非 1），导致 cascading mismatch
2. **脚注段落**: 金版中 `[footnote] *` 段落被 filter 掉，导出中保留或相反
3. **章标题页**: "LEÇON DU ..." 在导出中作为独立段落，金版中附带在 subtitle/TOC 结构
4. **HTML 残留**: 第 8 章有 1 处 HTML 标签残留
5. **OCR 重音差异**: 少量低相似度段由 é/e 等重音差异导致（段落匹配仍然正确）

---

## Goldstein

| 指标 | 数值 |
|------|------|
| Pipeline | pages=431, chapters=9, notes=921, anchors=957 |
| Links | matched=898, fallback=0 (0%), repair=60, orphan_anchor=0, orphan_note=0 |
| 阻塞原因 | split_items_sparse_note_capture |
| 章通过 | **0/9** (0%) |
| 问题数 | 35 |
| 正文引用 | 导出 1047 vs 金版 921 (+126) |
| 尾注定义 | 导出 898 vs 金版 921 (-23) |
| 段缺失 | 71 |
| 段新增 | 67 |
| 低相似度段 | 76 |

### 逐章相似度

| 章 | 相似度 | 引用 | 定义 | 通过 |
|----|--------|------|------|------|
| 001-Introduction | 91.0% | 28/26 | 26/26 | ✗ |
| 002-Perils of Imagination | 85.1% | 99/86 | 83/86 | ✗ |
| 003-Revolutionary Schooling | 73.7% | 108/95 | 93/95 | ✗ |
| 004-Self in Mental Apparatus | 83.9% | 113/108 | 107/108 | ✗ |
| 005-A Priori Self | 77.2% | 152/142 | 136/142 | ✗ |
| 006-Cousinian Hegemony | 71.3% | 194/169 | 166/169 | ✗ |
| 007-Religious and Secular | 76.5% | 118/112 | 109/112 | ✗ |
| 008-Palpable Self (Phrenology) | 38.2% | 197/152 | 149/152 | ✗ |
| 009-Epilogue | 22.7% | 38/31 | 29/31 | ✗ |

### 主要差异模式

1. **过度检测引用**: 导出(+126 引用)远超金版，尤其在 ch008 (+45) 和 ch006 (+25)，说明 bare_digit 或弱信号模式过于敏感
2. **低相似度但不缺失**: ch008 有 105/120 段匹配、ch009 有 33/40 段匹配，但整章相似度低——说明段落顺序不同或引用密度差异大
3. **上标残留**: 第 6 章有 1 处上标残留
4. **分裂段落**: 大量"缺失"和"新增"实际是同一段落的不同版本（如诗行分行 vs 合并、引用块断开 vs 连续）
5. **脚注段落**: 与 Biopolitics 相同，金版和导出对 footnote paragraphs 的处理不同

---

## 差异分类

### 类型 A: 引用检测偏差（需关注）
- Biopolitics: 前几章编号起点偏移（全书连续编号 vs 每章独立编号）
- Goldstein: 全局过度检测（+126 引用），集中在 bare_digit 误识别

### 类型 B: 段落结构差异（轻微）
- 章标题作为独立段落（导出）vs 合并到首段（金版）
- 诗行/引用块的分行策略不同
- 脚注编辑器注释 `[footnote] *` 的取舍

### 类型 C: 实质内容差异（需逐一判断）
- 低相似度段落（Biopolitics 16 段, Goldstein 76 段）
- 真正缺失段落（Biopolitics 110 段, Goldstein 71 段）

### 类型 D: 技术残留（已知问题）
- Biopolitics ch008: 1 处 HTML 标签
- Goldstein ch006: 1 处上标残留

---

## 程序阻塞 vs 金版差异对照

| 程序阻塞项 | Biopolitics | Goldstein | 与金版关系 |
|-----------|-------------|-----------|-----------|
| contract_def_anchor_mismatch | ✓ | - | 对应：引用编号偏移 |
| split_items_sparse_note_capture | - | ✓ | 对应：过度检测导致稀疏捕获 |
| visual_recovery gaps | 3 chapters | 0 | 无关金版 |
| sup_recovery unrecovered | 26-31 markers | 5 markers | 部分对应：少数引用缺失 |

结论：程序阻塞项确实反映了部分金版差异，但不是 1:1 对应。金版对比揭示的段落级差异比程序阻塞项更细粒度。
