# GROBID 架构笔记

## 项目概述

- **仓库**: https://github.com/kermitt2/grobid
- **语言**: Java
- **许可**: Apache 2.0
- **定位**: 学术 PDF 解析的生产级方案

## 核心特点

### 1. 级联序列标注模型

GROBID 使用多个级联的序列标注模型来解析文档：

```
PDF → Segmentation Model → Header Model → Fulltext Model → Citation Model
          ↓                    ↓              ↓               ↓
     文档分段            提取标题/作者     提取正文结构     解析引用
```

每个模型专注于一个子任务，输出作为下一个模型的输入。

### 2. Layout Tokens（布局令牌）

GROBID 不直接处理原始文本，而是处理"布局令牌"：

```java
// 每个 token 包含:
- 文本内容
- 页面位置 (x, y, width, height)
- 字体信息 (name, size, style)
- 行号、块号
```

这允许模型同时利用**文本信息**和**视觉/布局信息**。

### 3. 68 个细粒度标签

GROBID 支持 68 个标签，用于构建精细的文档结构：

```
# 元数据相关
title, author, affiliation, address, email
date, abstract, keywords, doi, pmid

# 正文结构
section_title, paragraph
reference_marker, footnote_marker, callout

# 参考文献
reference, author_ref, title_ref, journal, volume, issue, pages

# 其他
figure, table, caption, header, footer
```

### 4. 脚注处理

GROBID 区分：
- `footnote_marker`: 正文中的脚注标记（如上标数字）
- `footnote`: 页底的脚注内容
- `footnote_callout`: 脚注内容中的回引标记

这种区分正是我们 FNM 需要的！

## 可借鉴的设计

### 1. 分层处理策略

```
第一层: 文档分段 (识别首页、正文、参考文献等区域)
第二层: 区域细化 (在每个区域内识别子结构)
第三层: 实体提取 (提取具体实体如引用、脚注)
```

### 2. 训练数据策略

GROBID 使用小规模高质量标注数据：
- 不使用自动生成的训练数据
- 手工标注几百到几千个样本
- 质量优于数量

### 3. 容错设计

- 即使某些模型失败，仍然返回部分结果
- 对 PDF 解析错误有降级策略
- 提供置信度分数

## API 示例

```bash
# 处理单个 PDF
curl -v --form input=@paper.pdf localhost:8070/api/processFulltextDocument

# 返回 TEI XML 格式
<TEI>
  <text>
    <body>
      <div type="section">
        <head>Introduction</head>
        <p>This is the introduction
          <ref type="foot" target="#foot_0">1</ref>
        </p>
      </div>
    </body>
    <div type="notes">
      <note place="foot" xml:id="foot_0" n="1">
        This is footnote 1.
      </note>
    </div>
  </text>
</TEI>
```

## 集成方案

### 方案 A: 作为预处理器

1. 用 GROBID 提取文档结构
2. 获取脚注标记和内容的位置
3. 与我们的 OCR 结果对齐
4. 增强 FNM 的结构识别

### 方案 B: 参考其架构

1. 借鉴级联模型的思路
2. 在我们的视觉模型中增加布局信息
3. 使用类似的标签体系

### 方案 C: 混合使用

1. 对于学术论文，优先使用 GROBID
2. 对于书籍，使用我们自己的 FNM
3. 根据文档类型自动选择

## 部署考虑

```bash
# Docker 部署
docker pull grobid/grobid:0.8.1
docker run -p 8070:8070 grobid/grobid:0.8.1

# 需要资源
- 内存: 至少 4GB (推荐 8GB)
- 首次加载模型需要 30-60 秒
```

## 相关论文

1. "GROBID: Combining Automatic Bibliographic Data Recognition and Term Extraction for Scholarship Publications" (2008)
2. "Automatic verification of the text layer correctness in PDF documents" (2024) - 关于文字层验证

## 局限性

1. **主要针对学术论文**：对书籍的支持可能有限
2. **Java 实现**：与我们的 Python 代码库集成需要 API 调用
3. **不专门处理尾注**：GROBID 主要关注脚注和引用
4. **对非英语支持有限**：训练数据主要是英语论文
