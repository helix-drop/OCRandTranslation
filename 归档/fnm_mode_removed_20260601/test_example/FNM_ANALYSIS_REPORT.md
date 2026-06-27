# FNM 模式五书分析报告

## 分析日期
2026-04-07

## 测试范围

### 已分析
- **Biopolitics** (`Foucault和Foucault - 2004 - Naissance de la biopolitique.pdf`)
  - 已上传并在数据库中
  - 已运行 FNM pipeline
  - 详细分析见下文

### 未分析（需要 PaddleOCR 上传）
- Germany_Madness
- Heidegger_en_France
- Mad_Act
- post-revolutionary

---

## Biopolitics 详细分析

### 1. FNM Pipeline 结果

| 指标 | 数值 |
|------|------|
| Status | done |
| Sections | 16 |
| Notes | 762 (288 footnotes + 474 endnotes) |
| Units | 804 (42 body + 762 note) |
| Page count | 370 |

### 2. Section 分布

| Section | Footnotes | Endnotes |
|---------|-----------|----------|
| sec-02-avertissement | 8 | 0 |
| sec-03-lecon-du-10-janvier-1979 | 17 | 18 |
| sec-05-lecon-du-17-janvier-1979 | 13 | 17 |
| sec-07-lecon-du-24-janvier-1979 | 23 | 31 |
| sec-09-lecon-du-31-janvier-1979 | 28 | 52 |
| sec-11-lecon-du-7-fevrier-1979 | 35 | 54 |
| sec-13-lecon-du-14-fevrier-1979 | 33 | 59 |
| sec-15-lecon-du-21-fevrier-1979 | 29 | 43 |
| sec-17-lecon-du-7-mars-1979 | 28 | 52 |
| sec-19-lecon-du-14-mars-1979 | 17 | 42 |
| sec-21-lecon-du-21-mars-1979 | 29 | 37 |
| sec-23-lecon-du-28-mars-1979 | 17 | 37 |
| sec-25-lecon-du-4-avril-1979 | 11 | 0 |
| sec-26-notes | 0 | 32 |

### 3. 边界划分评估

**正确的方面：**
- 16 个 section 对应书的章节结构
- 每个 lecture section 都有独立的 footnotes 和 endnotes
- NOTES 章节 (sec-26-notes) 被正确识别为尾注区域

**Body Units 页面范围示例：**
- sec-01: pages 1-8
- sec-02: pages 9-15
- sec-03: pages 17-23, 24-31, 32-39 (三个 units)
- 以此类推...

### 4. 尾注和标记对应

**问题发现：所有 notes 的 marker 字段都是 None**

这意味着：
- note_id 有编号 (如 `en-03-0001`, `fn-02-0001`)
- 但 marker（原文中的数字标记）没有被提取

**原文中的尾注引用格式：**
- 使用 `^{n}` 格式（LaTeX 上标风格）
- 例如：`^{12}`, `^{18}` 等
- 共 120 个页面包含上标引用

### 5. 导出分析

**导出结果：**
- 17 个文件（index.md + 16 章节）
- ZIP 大小 124,955 bytes

**关键问题：尾注引用未链接**
- 474 个尾注定义存在于 NOTES.md
- 0 个尾注引用存在于正文中
- 所有尾注定义都是"孤立"的

**原因分析：**
1. 导出依赖 `{{EN_REF:id}}` 或 `{{FN_REF:id}}` 格式的冻结引用
2. 这些冻结引用在翻译流程中被注入
3. 由于只运行了 pipeline 没有运行翻译，正文仍是原始 source_text
4. 原始文本中的 `^{n}` 格式没有被转换为链接

### 6. 段落划分

**正常情况：**
- 页面内容质量良好，无乱码
- 段落边界基本正确

**待翻译占位符：**
- 由于未运行翻译，导出的正文全是 `[待翻译]` 占位符
- 只有脚注定义 `[FN-*]` 被保留（非标准格式）

### 7. Validation 问题

| 原因 | 数量 |
|------|------|
| missing_annotation | 246 |
| unresolved_gap | 119 |
| gap_ratio_high_skip_auto_repair | 68 |
| **总计** | **433** |

这些都是脚注相关的 validation 问题，属于 OCR 层面的识别缺口。

---

## 问题汇总与优化建议

### 问题 1：尾注引用未链接
**现象：** 导出的正文中没有尾注引用链接，474 个尾注定义全部孤立
**原因：** 未运行翻译流程，缺少冻结引用注入步骤
**建议：**
- 方案 A：运行翻译流程（即使是 test 模式占位符）
- 方案 B：在导出时增加一个后处理步骤，将原文中的 `^{n}` 格式转换为 `[^en-xxx]` 链接
- 方案 C：在 FNM pipeline 阶段就将尾注引用注入到 source_text 中

### 问题 2：Notes 的 marker 字段为空
**现象：** 所有 footnotes 和 endnotes 的 marker 都是 None
**原因：** pipeline 阶段未解析原文中的标记数字
**建议：**
- 增强 note 解析逻辑，从 source_text 中提取标记数字
- 使用标记数字建立正文引用与尾注定义的对应关系

### 问题 3：脚注 validation 缺口较大
**现象：** 433 个 unresolved footnotes
**原因：** OCR 解析层面的脚注识别问题
**建议：**
- 继续优化 `missing_annotation` 检测逻辑
- 评估是否需要引入基于上下文的脚注匹配

### 问题 4：其他四本书未处理
**现象：** 数据库中只有 Biopolitics 一本书
**原因：** 需要 PaddleOCR token 上传
**建议：**
- 配置 PaddleOCR token 后重新上传测试

---

## 结论

Biopolitics 的 FNM pipeline 基本正确：
- ✅ Section 边界划分正确
- ✅ 脚注和尾注识别数量合理
- ✅ 页面内容无乱码
- ⚠️ 尾注引用链接依赖翻译流程
- ⚠️ 脚注 validation 缺口需要继续优化

**核心发现：当前 FNM 导出要求必须运行翻译流程，否则尾注引用不会被链接。** 如果需要在无翻译情况下也能正确导出尾注链接，需要调整架构。
