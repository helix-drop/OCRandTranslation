# FNM 重构设计方案

基于对 5 本测试书籍的分析和参考项目的调研，本文档提出 FNM 模块的重构方案。

## 当前问题总结

| 问题类型 | 案例 | 影响 |
|---------|------|------|
| 文字层乱码 | Mad_Act (+48 偏移) | 无法识别任何注释 |
| 章节边界检测不足 | Germany_Madness, Post-Revolutionary | 最后一章与后续部分合并 |
| 边界微偏 | Heidegger | 12% 未解决率 |
| 脚注编号重置未检测 | Germany_Madness (Epilogue) | 误报大量缺失 |

## 重构目标

1. **可靠性**: 能处理各种 PDF 质量问题
2. **准确性**: 章节边界和注释匹配准确
3. **可扩展性**: 易于添加新的注释模式支持

## 架构设计

### 整体流程

```
PDF
 │
 ▼
┌──────────────────────────────────────────────────────────────┐
│ 第一层: 文字层质量评估                                          │
│ ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│ │ 特征提取    │ → │ 质量分类    │ → │ 修复/回退   │        │
│ │ (Dedoc式)   │    │ (XGBoost)   │    │ (偏移/OCR)  │        │
│ └─────────────┘    └─────────────┘    └─────────────┘        │
└──────────────────────────────────────────────────────────────┘
 │
 ▼
┌──────────────────────────────────────────────────────────────┐
│ 第二层: 文档结构识别                                            │
│ ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│ │ 布局分析    │ → │ 章节检测    │ → │ 注释区域    │        │
│ │ (标签+位置) │    │ (多信号)    │    │ 识别        │        │
│ └─────────────┘    └─────────────┘    └─────────────┘        │
└──────────────────────────────────────────────────────────────┘
 │
 ▼
┌──────────────────────────────────────────────────────────────┐
│ 第三层: 注释匹配                                               │
│ ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│ │ 引用提取    │ → │ 定义提取    │ → │ 匹配算法    │        │
│ │ (正文中)    │    │ (注释区)    │    │             │        │
│ └─────────────┘    └─────────────┘    └─────────────┘        │
└──────────────────────────────────────────────────────────────┘
 │
 ▼
验证 & 输出
```

### 第一层: 文字层质量评估

#### 核心组件

```python
class TextLayerQualityChecker:
    """文字层质量检查器"""
    
    def __init__(self):
        self.feature_extractor = TxtlayerFeatureExtractor()
        # 可选: 加载预训练分类器
        
    def check_quality(self, pages: List[str]) -> QualityResult:
        """
        检查文字层质量。
        
        返回:
        - is_valid: bool - 整体是否有效
        - page_results: List[bool] - 每页是否有效
        - suggested_fix: str - 建议的修复方法
        """
        pass
    
    def try_fix(self, text: str, method: str) -> str:
        """尝试修复乱码文本"""
        if method == 'offset_48':
            return self._fix_offset(text, 48)
        elif method == 'ocr':
            return self._fallback_ocr(text)
        return text
```

#### 快速检测策略

```python
def quick_quality_check(text: str) -> bool:
    """快速检测文字层是否有效"""
    if len(text) < 50:
        return True  # 太短无法判断
    
    # 1. 字母比例检查
    letter_ratio = sum(1 for c in text if c.isalpha()) / len(text)
    if letter_ratio < 0.3:
        return False
    
    # 2. 乱码字符检查
    trash_ratio = sum(1 for c in text if ord(c) <= 32 or 160 <= ord(c) <= 879) / len(text)
    if trash_ratio > 0.2:
        return False
    
    # 3. 词长检查
    words = text.split()
    if words:
        avg_word_len = sum(len(w) for w in words) / len(words)
        if avg_word_len < 2 or avg_word_len > 15:
            return False
    
    return True
```

### 第二层: 文档结构识别

#### 章节边界检测 (增强版)

```python
class EnhancedSectionDetector:
    """增强的章节边界检测器"""
    
    # 标准后置章节名称
    BACK_MATTER_TITLES = {
        'conclusion', 'conclusions', 'epilogue', 'afterword',
        'bibliography', 'references', 'works cited',
        'notes', 'endnotes', 'footnotes',
        'index', 'indices', 'appendix', 'appendices',
        'acknowledgments', 'acknowledgements',
        'glossary', 'abbreviations'
    }
    
    def detect_sections(self, pages: List[Page]) -> List[Section]:
        """
        检测章节边界。
        
        使用多种信号:
        1. doc_title 标签
        2. paragraph_title 标签
        3. 脚注编号重置
        4. 标准章节名称
        5. 页面空白/分隔页
        """
        boundaries = []
        
        # 信号 1: doc_title 标签
        boundaries.extend(self._detect_by_doc_title(pages))
        
        # 信号 2: 标准章节名称
        boundaries.extend(self._detect_by_standard_names(pages))
        
        # 信号 3: 脚注编号重置
        boundaries.extend(self._detect_by_footnote_reset(pages))
        
        # 合并和去重
        return self._merge_boundaries(boundaries)
    
    def _detect_by_footnote_reset(self, pages: List[Page]) -> List[Boundary]:
        """通过脚注编号重置检测章节边界"""
        boundaries = []
        prev_max_marker = 0
        
        for page in pages:
            for note in page.footnotes:
                marker = int(note.marker)
                if marker == 1 and prev_max_marker > 10:
                    # 编号从高数字重置为 1，可能是新章节
                    boundaries.append(Boundary(
                        page=page.number,
                        confidence=0.8,
                        signal='footnote_reset'
                    ))
                prev_max_marker = max(prev_max_marker, marker)
        
        return boundaries
```

#### 注释区域识别

```python
class NoteRegionDetector:
    """注释区域检测器"""
    
    def detect_footnote_region(self, page: Page) -> Optional[Region]:
        """检测页底脚注区域"""
        # 策略 1: 位置启发式 (底部 20%)
        # 策略 2: 字体大小变化
        # 策略 3: 分隔线检测
        pass
    
    def detect_endnote_section(self, pages: List[Page]) -> Optional[Section]:
        """检测尾注章节"""
        # 策略 1: "Notes" 标题
        # 策略 2: 大量编号段落
        # 策略 3: 引用格式检测
        pass
```

### 第三层: 注释匹配

#### 匹配算法

```python
class NoteMatchingEngine:
    """注释匹配引擎"""
    
    def match_footnotes(self, section: Section) -> MatchResult:
        """
        匹配章节内的脚注。
        
        对于每个正文中的引用标记 [^N]:
        1. 在同页或附近页面的脚注区域查找定义
        2. 验证编号连续性
        3. 处理跨页脚注
        """
        pass
    
    def match_endnotes(self, sections: List[Section]) -> MatchResult:
        """
        匹配尾注。
        
        尾注有两种模式:
        1. 书末统一尾注: 所有引用指向最后的 Notes 章节
        2. 章末尾注: 每章的引用指向该章末尾
        """
        # 检测尾注模式
        mode = self._detect_endnote_mode(sections)
        
        if mode == 'book_end':
            return self._match_book_end_endnotes(sections)
        else:
            return self._match_chapter_end_endnotes(sections)
    
    def _detect_endnote_mode(self, sections: List[Section]) -> str:
        """检测尾注模式"""
        # 检查是否有统一的 Notes 章节
        notes_section = self._find_notes_section(sections)
        if notes_section:
            return 'book_end'
        
        # 检查每章末尾是否有注释
        for section in sections:
            if self._has_chapter_end_notes(section):
                return 'chapter_end'
        
        return 'unknown'
```

## 数据结构设计

```python
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class NoteType(Enum):
    FOOTNOTE = "footnote"  # 页底脚注
    ENDNOTE = "endnote"    # 尾注 (章末或书末)
    SIDENOTE = "sidenote"  # 边注 (少见)

class NoteMode(Enum):
    PER_PAGE = "per_page"      # 每页编号
    PER_CHAPTER = "per_chapter"  # 每章编号
    PER_BOOK = "per_book"      # 全书编号

@dataclass
class NoteReference:
    """正文中的注释引用"""
    marker: str           # 标记 (如 "1", "*")
    page: int             # 所在页码
    position: int         # 在页面中的位置
    text_context: str     # 周围文本上下文

@dataclass  
class NoteDefinition:
    """注释定义"""
    marker: str           # 标记
    page: int             # 所在页码
    content: str          # 注释内容
    note_type: NoteType   # 注释类型

@dataclass
class NoteMatch:
    """匹配结果"""
    reference: NoteReference
    definition: Optional[NoteDefinition]
    confidence: float     # 匹配置信度
    status: str           # 'matched', 'unresolved', 'ambiguous'

@dataclass
class Section:
    """章节"""
    id: str
    title: str
    start_page: int
    end_page: int
    note_mode: NoteMode
    references: List[NoteReference]
    definitions: List[NoteDefinition]
    matches: List[NoteMatch]
```

## 实施计划

### 阶段 1: 文字层质量检测 (优先级高)

1. [ ] 实现 `TxtlayerFeatureExtractor` (基于 Dedoc)
2. [ ] 实现 `quick_quality_check` 函数
3. [ ] 实现字符偏移修复 (`try_fix_shifted_encoding`)
4. [ ] 集成到 OCR 流程

### 阶段 2: 章节边界增强

1. [ ] 实现 `EnhancedSectionDetector`
2. [ ] 添加脚注编号重置检测
3. [ ] 添加标准章节名识别
4. [ ] 更新 `build_sections()` 函数

### 阶段 3: 匹配算法优化

1. [ ] 实现尾注模式检测
2. [ ] 实现章末/书末尾注匹配
3. [ ] 改进验证逻辑

### 阶段 4: 测试和验证

1. [ ] 用 5 本测试书籍验证
2. [ ] 对比改进前后的结果
3. [ ] 记录问题和改进

## 参考资料

- `01_dedoc/`: Dedoc 的文字层检测代码
- `02_papermage/`: PaperMage 的 VILA 预测器
- `03_grobid/`: GROBID 的架构笔记
