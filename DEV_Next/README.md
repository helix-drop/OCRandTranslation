# DEV_Next - FNM 重构参考资料

本目录收集用于 FNM（脚注/尾注机制）重构的参考资料和代码示例。

## 目录结构

```
DEV_Next/
├── README.md                      # 本文件
├── 01_dedoc/                      # Dedoc 项目参考
│   ├── txtlayer_detector.py       # PDF文字层质量检测
│   ├── txtlayer_feature_extractor.py  # 特征提取
│   └── ml_txtlayer_classifier.py  # ML分类器
├── 02_papermage/                  # PaperMage 项目参考
│   └── vila_predictors.py         # VILA文档结构预测
├── 03_grobid/                     # GROBID 项目说明
│   └── notes.md                   # 架构笔记
└── 04_design_notes/               # 设计笔记
    └── fnm_redesign.md            # FNM重构方案
```

## 参考项目概览

### 1. Dedoc (推荐借鉴)

- **仓库**: https://github.com/ispras/dedoc
- **价值点**: PDF文字层质量自动检测
- **核心思路**: 
  - 提取文本特征（字母比例、特殊字符比例、大小写变化等）
  - 使用 XGBoost 分类器判断文字层是否有效
  - 可直接解决 Mad_Act 类乱码问题

### 2. PaperMage (架构参考)

- **仓库**: https://github.com/allenai/papermage
- **价值点**: 多层 Entity 架构，有 `footnotes` 层
- **核心思路**:
  - Document 包含多个可交叉引用的 Entity 层
  - 使用 VILA 模型进行文档结构预测
  - 16类标签包括 Footnote

### 3. GROBID (成熟方案)

- **仓库**: https://github.com/kermitt2/grobid
- **价值点**: 学术PDF解析的生产级方案
- **核心思路**:
  - 级联序列标注模型
  - 基于 Layout Tokens 而非纯文本
  - Java 实现，部署较重

## 关键技术点

### 文字层质量检测（来自 Dedoc）

```python
# 特征提取关键指标
- letters_proportion    # 字母占比
- digits_proportion     # 数字占比  
- special_symbols_proportion  # 特殊符号占比
- trash_chars_proportion     # 乱码字符占比
- case_changes         # 大小写变化频率
- mean_word_length     # 平均词长
- std_char_ord         # 字符码点标准差
```

### 文档结构预测标签（来自 PaperMage/VILA）

```python
VILA_LABELS = [
    "Title", "Author", "Abstract", "Keywords",
    "Section", "Paragraph", "List", "Bibliography",
    "Equation", "Algorithm", "Figure", "Table",
    "Caption", "Header", "Footer", "Footnote"  # 有专门的脚注标签
]
```

## FNM 重构建议

1. **文字层预处理**
   - 参考 Dedoc 的特征提取方法检测乱码
   - 乱码时尝试字符偏移修复（如 +48）
   - 修复失败则回退 OCR

2. **章节边界增强**
   - 不依赖单一 `doc_title` 标签
   - 检测脚注编号重置点
   - 识别标准章节名（Conclusion, Bibliography 等）

3. **多层架构**
   - 参考 PaperMage 的 Entity 层设计
   - 脚注/尾注作为独立层
   - 支持跨层引用关系

## 更新日志

- 2026-04-06: 初始创建，收集 Dedoc、PaperMage、GROBID 参考资料
