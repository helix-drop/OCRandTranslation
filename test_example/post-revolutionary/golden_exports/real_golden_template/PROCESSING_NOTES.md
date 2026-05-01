# Golden export 处理笔记 — Goldstein

这批 `real_golden_template` 文件以原书 PDF 为最高依据，FNM 导出 ZIP 只作为 OCR 底稿。遇到源文与 PDF 冲突时，优先核对 PDF 页面图像。

## 书目信息

- **书名**: The Post-Revolutionary Self: Politics and Psyche in France, 1750-1850
- **作者**: Jan Goldstein
- **出版**: Harvard University Press, 2005
- **总页数**: 431 PDF pages
- **尾注总数**: PDF 确认正文 9 章合计 921 个；原书书末按章分组，每章内部从 1 重新编号，不采用全书连续编号
- **脚注**: 0（无页脚注，纯尾注书）
- **尾注位置**: PDF p.348-414（印刷页 p.331-398，按章分组）
- **TOC 章节**: 9（Introduction + Ch1-7 + Epilogue）

## 目录结构

| TOC Order | 标题 | printed_page | PDF fileIdx | 尾注数(推定) |
|---|---:|---|---|---|
| 1 | List of Illustrations | ix | 25 | - |
| 2 | Preface | xi | 27 | - |
| 3 | Introduction: Psychological Interiority versus Self-Talk | 1 | 17 | ~26 |
| 4 | I THE PROBLEM FOR WHICH PSYCHOLOGY FURNISHED A SOLUTION | - | - | (container) |
| 5 | 1 The Perils of Imagination at the End of the Old Regime | 21 | 37 | 86 |
| 6 | 2 The Revolutionary Schooling of Imagination | 60 | 76 | 95 |
| 7 | II THE POLITICS OF SELFHOOD | - | - | (container) |
| 8 | 3 Is There a Self in This Mental Apparatus? | 103 | 119 | 108 |
| 9 | 4 An A Priori Self for the Bourgeois Male: Victor Cousin's Project | 139 | 155 | 142 |
| 10 | 5 Cousinian Hegemony | 182 | 198 | 169 |
| 11 | 6 Religious and Secular Access to the Vie Intérieure: Renan at the Crossroads | 233 | 249 | 112 |
| 12 | 7 A Palpable Self for the Socially Marginal: The Phrenological Alternative | 269 | 285 | 152 |
| 13 | Epilogue | 316 | 332 | 31 |
| 14 | Notes | 331 | 347 | (endnotes container) |
| 15 | Note on Sources | 399 | 415 | (back_matter) |
| 16 | Index | 403 | 419 | (back_matter) |

## 已知问题 — FNM 导出阶段

### E1. 正文尾注标记缺失（严重）
导出的章节正文中没有稳定的 `[^n]` 尾注引用标记。原书 PDF 中使用上标数字；这些数字是“章内编号”，不是全书连续编号。FNM body_anchors 阶段成功检测到 953 个锚点，但导出阶段的 ref_materialization 未将其稳定转换为 `[^n]` 格式。

**修复方向**: 需要按章节建立正文上标 → 同章 NOTES 条目的映射，然后在正文中替换为 `[^n]`。不要把不同章节的尾注改造成全书连续编号。

### E2. 尾注定义仅出现在 Introduction 章节（严重）
导出的 ZIP 中只有 Introduction 章节包含 `### NOTES` 节，其他 8 章完全没有。且 Introduction 的 NOTES 内容是图片说明（figure captions），不是学术尾注。这是因为 book-level 尾注的所有定义被错误地归到了第一个章节。

**修复方向**: 每个章节应在文末附加其对应的 `### NOTES` 节，定义来自 p.348-414 中该章的 note section。

### E3. HTML 标签残留（中等）
Ch2, Ch3, Ch4, Ch6, Ch7, Ch8 中存在 `<div style="text-align: center;">` 和 `</div>` HTML 标签残留。这些来自 OCR 对居中图片/标题的处理。

### E4. 标题层级缺失（中等）
所有章节只有一个 `##` 章标题，缺少文内 `###` 节标题。原书大部分章节确实没有显式节标题，但 Ch5 (Cousinian Hegemony) 和 Ch7 (Phrenological Alternative) 等较长章节可能有内部结构标记。

### E5. 段落跨页断裂（低）
正文跨页处的段落可能被切成两个段落。需要在 golden template 中按语义合并。

## 常见问题

### OCR 上标格式
- 原书 PDF 使用标准上标数字（superscript）作为尾注标记
- OCR 渲染为 `^{n}` 格式（如 `^{1}`, `^{23}`）
- golden template 中应统一为 `[^n]` 格式
- 注意：原书没有脚注星号标记（*, **, † 等）

### OCR 误字
- 法语人名中的特殊字符可能被误识（如 ç → c, é → e, è → e）
- 书名斜体中的特殊拼写需要保留
- 尾注页的 `_note_scan` 检测覆盖率约 45%（仅 28/67 页被标为 endnote_collection），大量尾注页被标为 mixed_body_endnotes 或 body

### 尾注编号映射
- 正文上标与书末 NOTES 均按章编号；Introduction 为 1-26，下一章重新从 1 开始
- 每个章节文件只附该章的 `### NOTES`，定义格式为 `[^n]: n. ...`
- 需要从 PDF 文字层和必要截图确认每章尾注的起止页；Introduction 的尾注 1-26 位于 PDF p.348-351，其中 p.351 下半页已经进入第 1 章尾注；Ch1 的尾注 1-86 位于 PDF p.351-359，p.359 下半页进入 Ch2 尾注；Ch2 的尾注 1-95 位于 PDF p.359-365，p.365 底部进入 Ch3 尾注说明；Ch3 的题头和 epigraph note 位于 PDF p.365 底部，尾注 1-108 位于 PDF p.366-373，p.373 下半页进入 Ch4 尾注；Ch4 的题头和 epigraph note 位于 PDF p.373 下半页，尾注 1-142 位于 PDF p.373-382，p.382 下半页进入 Ch5 尾注；Ch5 的题头和 epigraph note 位于 PDF p.382 下半页，尾注 1-169 位于 PDF p.382-393，p.393 下半页进入 Ch6 尾注；Ch6 的尾注 1-112 位于 PDF p.393-401，p.401 中段进入 Ch7 尾注；Ch7 的题头和 epigraph note 位于 PDF p.401 中段，尾注 1-152 位于 PDF p.401-411，p.411 中段进入 Epilogue 尾注；Epilogue 的 epigraph note 和尾注 1-31 位于 PDF p.411-414，p.415 为空白，p.416 进入 Note on Sources
- 特别注意：不要把章节之间相同的尾注编号视为冲突，也不要生成全书连续编号

## 修补流程

1. 以 FNM 导出的章节 Markdown 为底稿
2. 对正文：将 `^{n}` 格式的锚点替换为 `[^global_n]` 格式
3. 对尾注：从 p.348-414 提取该章的尾注定义，格式化为 `[^n]: n. text` 
4. 检查 OCR 断词和误字
5. 合并跨页断裂段落
6. 去除 HTML 标签残留

## 校验逻辑

- 正文 `[^n]` 引用与 `### NOTES` 下的定义必须一一对应
- 每个尾注定义必须形如 `[^n]: n. ...`
- 无 `^{n}` 残留、无 `<sup>` 残留、无 `{{NOTE_REF}}` 残留
- 无 HTML 标签残留
- 标题层级从 `##` 开始，无 `#` 出现
- 跨页无断裂段落（无孤立短句）
- 正文章节模板应保持“一个 markdown 段落一行”；不要把 PDF 版面行或生成器硬折行直接写入模板
- PDF 行尾落在 em dash 后时，合并时应去掉抽取产生的空格，形成 `word—word`，不要留下 `word— word`

## 章节核对记录

- Ch4: PDF p.156 截图确认 epigraph 中 `Ecole polytechnique` 无重音、`à merveille` 有重音；PDF p.191 截图确认跨行 `idea- / generating` 应合并为 `idea-generating`；PDF p.188 与 p.198 截图确认 `and or his anxieties`、`a nonetheless an ambiguous` 为原书形态，保留不改；PDF p.381 截图确认尾注 121 中 `Stendahl, Correspondance générale` 为原书形态，保留不改；PDF p.382 截图确认 Ch4 尾注止于 142，下半页进入 Ch5。
- Ch5: PDF p.199 截图确认章题与 epigraph；PDF p.227 为 Figure 4 专页，处理时将图占位和图注移至被插图打断的正文段落之后；PDF p.212、p.214、p.216、p.218、p.249 截图确认 `institutionalizating`、`adumbated`、`volontary`、`Caroline Angbert`、`willfullness`、`Cousianian` 为原书形态，保留不改；PDF p.382 截图确认 epigraph note 中 `C. ‘Latreille` 为原书形态；PDF p.393 截图确认 Ch5 尾注止于 169，下半页进入 Ch6。
- Ch6: PDF p.250 截图确认章题和正文起点，原书正文中 `mid- nineteenth-century` 带连字符后空格，按 PDF 保留；PDF p.261 截图确认 Figure 5 图占位与图注，处理时将其移至被插图打断的引文段落之后；PDF p.396 截图确认 `Poussielgue-Rusand` 为跨行连字符、尾注 44 中 `seventeen-century` 为原书形态；PDF p.398 截图确认尾注 71 起首为 `”Notes...`；PDF p.400 截图确认 `prepared` 为跨行断词修复结果、`Adophe Garnier` 为原书形态；PDF p.401 截图确认 Ch6 尾注止于 112，中段进入 Ch7。
- Ch7: PDF p.286 截图确认章题与 epigraph，其中 `14` 是正文中的颅相学编号，不是脚注；PDF p.303 截图确认 Figure 6 图占位和图注，处理时将图占位和图注移至被插图打断的正文段落之后；PDF p.289 截图确认正文中 `Theophile Thoré` 无重音，按原书保留；PDF p.401 截图确认 epigraph note、Ch7 尾注起点和尾注 2 中跨行 `Institut`、`in which`；PDF p.405 截图确认 `Etienne-André-Théodore`、`l’outrage` 为跨行修复结果；PDF p.411 截图确认 Ch7 尾注止于 152，中段进入 Epilogue。
- Epilogue: PDF p.333 截图确认章题、epigraph、`on so on` 为原书形态，按原书保留；PDF p.333-346 确认正文范围，p.347 为空白；PDF p.411 截图确认 epigraph note 和 Epilogue 尾注起点，PDF p.414 截图确认尾注止于 31，p.416 进入 Note on Sources。旧 md 中重复错位的 `mood of the people`、1880 programme 段落和 `This debate...` 段落均按 PDF 顺序重建；`dislocations`、`biologistic`、`self shattered`、`philosopher-educator`、`libre-arbitre` 等均按 PDF 页面修复或保留。

## 2026-04-30 全书 QA 复核

- 复核范围：`001`-`009` 正文章节，包含正文、文内引用、`### NOTES`、尾注定义。
- 修复：`007`、`008`、`009` 此前三章由生成器硬折为约 95 字一行，已恢复为“一个 markdown 段落一行”；连续 blockquote 和每条尾注定义也已合并回单段。
- 修复：全书检出 PDF 行尾 em dash 拼接产生的多余空格，涉及 Ch3-Ch7 的 `— ` 形态，已按原书无空格 em dash 风格统一修正；Ch5 PDF p.213 和 Ch7 PDF p.271 以截图复核。
- 修复：Ch6 `allpowerful God` 经 PDF p.255 截图确认来自 `all- / powerful` 跨行，已修为 `all-powerful God`。
- 保留：Ch6 正文 `mid- nineteenth-century` 经 PDF p.250 截图确认原书即有连字符后空格，仍按原书保留；`eighteenth- and nineteenth-century`、`sixteenth- and seventeenth-century` 等为正常悬挂复合词。
- 校验结果：9 章正文引用和尾注定义均一一对应；无旧 `$^{n}`/`^{n}`、HTML 标签、`NOTE_REF` 泄漏；重复长段落为 0；普通正文硬折行检测为 0。

## 2026-04-30 基准版再验收

- 本轮按“以后 FNM 模式产物的对照标准”重新验收，不以 md 或 PDF 文字层单独为准；自动命中异常后，回 PDF 截图和上下文复核。
- 正文 PDF token 对照范围：Introduction p.18-36；Ch1 p.38-76；Ch2 p.77-118；Ch3 p.120-155；Ch4 p.156-198；Ch5 p.199-249；Ch6 p.250-285；Ch7 p.286-332；Epilogue p.333-346。
- 正文 token 对照结果：9 章均无大段漏文、错章或重复；显著差异只剩图像占位语与图注在 PDF 文字层中的读取顺序，以及分部标题页文字，不作为正文错误处理。
- 尾注 PDF token 对照范围：p.348-414，按书末 Notes 内的章节小标题切分回各章；9 章尾注 token 相似度均不低于 0.996，且无 8-token 以上显著差异。
- 修复：`002`-`006` 中散文 blockquote 仍保留 PDF 版式硬折行，本轮已合并为单个 markdown 引文段；`002` 中四组戏剧/诗行引文保留原分行，因为其分行承载原引文形态。
- 复核保留：Ch2 正文引文 `than though the ears` 经 PDF p.96 截图确认原书如此；Ch6 正文 `neither paid heed and nor devoted` 经 PDF p.264 截图确认原书如此；Ch7 epigraph 中两处 `14` 经 PDF p.286 截图确认是原书颅相学编号，不是 `it` 误读；Epilogue epigraph note 中 `p 23.` 经 PDF p.411 截图确认原书即无 `p.` 句点，保留。
- 结构校验结果：9 章正文引用与尾注定义均一一对应，定义均为 `[^n]: n. ...`；无旧上标、HTML、占位符、em dash 后多余空格；无全书级长段重复；普通正文和散文 blockquote 均无硬折行残留。

## FNM 锚点数据（从数据库获取）

| 章节 | body_anchors | note_items (FNM) | 预期尾注数 | note_scan 条目 |
|---|---:|---:|---:|---|
| Introduction | 29 | 26 | 26 | PDF p.348-351 |
| Ch1 Perils of Imagination | 86 | 86 | 86 | PDF p.351-359 |
| Ch2 Revolutionary Schooling | 95 | 95 | 95 | PDF p.359-365 |
| Ch3 Mental Apparatus | 114 (PDF 确认有效正文引用 108) | 103 (FNM；PDF 确认 108) | 108 | PDF p.365-373 |
| Ch4 A Priori Self | 141 (PDF 确认有效正文引用 142) | 128 (FNM；PDF 确认 142) | 142 | PDF p.373-382 |
| Ch5 Cousinian Hegemony | 175 (PDF 确认有效正文引用 169) | 176 (FNM；PDF 确认 169) | 169 | PDF p.382-393 |
| Ch6 Religious & Secular | 114 (PDF 确认有效正文引用 112) | 100 (FNM；PDF 确认 112) | 112 | PDF p.393-401 |
| Ch7 Palpable Self | 155 (PDF 确认有效正文引用 152) | 155 (FNM；PDF 确认 152) | 152 | PDF p.401-411 |
| Epilogue | 32 (PDF 确认有效正文引用 31) | 29 (FNM；PDF 确认 31) | 31 | PDF p.411-414 |
| **总计** | **953** | **888** | **921** | **753** |
