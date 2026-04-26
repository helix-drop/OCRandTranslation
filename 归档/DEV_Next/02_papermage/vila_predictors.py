"""
来源: https://github.com/allenai/papermage
文件: papermage/predictors/vila_predictors.py
许可: Apache 2.0

功能: 使用 VILA 模型进行文档结构预测
核心思路:
  1. 将文档转换为 token + bbox 格式
  2. 使用预训练的布局感知 Transformer 模型
  3. 预测每个 token 的标签（包括 Footnote）

VILA 支持的标签:
  Title, Author, Abstract, Keywords,
  Section, Paragraph, List, Bibliography,
  Equation, Algorithm, Figure, Table,
  Caption, Header, Footer, Footnote  <-- 脚注标签

这个架构的价值:
  1. 多层 Entity 设计，支持跨层引用
  2. 使用视觉+文本信息联合判断
  3. 可以识别文档的结构元素（包括脚注）
"""

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import itertools
from abc import abstractmethod
from typing import Dict, List, Optional, Tuple

# import torch
# from vila.predictors import LayoutIndicatorPDFPredictor

# VILA 模型支持的标签列表
VILA_LABELS = [
    "Title",
    "Author", 
    "Abstract",
    "Keywords",
    "Section",
    "Paragraph",
    "List",
    "Bibliography",
    "Equation",
    "Algorithm",
    "Figure",
    "Table",
    "Caption",
    "Header",
    "Footer",
    "Footnote",  # 脚注标签 - 这正是我们需要的
]

# 页面尺寸限制
MAX_PAGE_WIDTH = 1000
MAX_PAGE_HEIGHT = 1000


def normalize_bbox(
    bbox: Tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    target_width: int = MAX_PAGE_WIDTH,
    target_height: int = MAX_PAGE_HEIGHT,
) -> Tuple[float, float, float, float]:
    """
    将 bbox 归一化到目标尺寸。
    
    Transformer 模型通常需要固定尺寸的输入。
    """
    x1, y1, x2, y2 = bbox

    if page_width > target_width or page_height > target_height:
        x1 = float(x1) / page_width * target_width
        x2 = float(x2) / page_width * target_width
        y1 = float(y1) / page_height * target_height
        y2 = float(y2) / page_height * target_height

    return (x1, y1, x2, y2)


def convert_document_page_to_pdf_dict(
    tokens: List[dict], 
    page_width: int, 
    page_height: int
) -> Dict[str, List]:
    """
    将文档页面转换为模型输入格式。
    
    输出格式:
    {
        'words': ['word1', 'word2', ...],
        'bbox': [[x1, y1, x2, y2], ...],
        'block_ids': [0, 0, 0, 1 ...],
        'line_ids': [0, 1, 1, 2 ...],
        'labels': [0, 0, 0, 1 ...],  # 可能为空
    }
    """
    words = []
    bboxes = []
    line_ids = []
    block_ids = []
    
    for token in tokens:
        words.append(token['text'])
        
        # 转换 bbox 到绝对坐标
        bbox = token.get('bbox', [0, 0, 0, 0])
        abs_bbox = (
            bbox[0] * page_width,
            bbox[1] * page_height,
            bbox[2] * page_width,
            bbox[3] * page_height
        )
        bboxes.append(abs_bbox)
        
        line_ids.append(token.get('line_id', 0))
        block_ids.append(token.get('block_id', 0))
    
    return {
        "words": words,
        "bbox": bboxes,
        "block_ids": block_ids,
        "line_ids": line_ids,
        "labels": [None] * len(words),
    }


def convert_sequence_tagging_to_spans(
    token_prediction_sequence: List[int],
) -> List[Tuple[int, int, int]]:
    """
    将序列标注结果转换为 span 列表。
    
    例如:
    输入: [0, 0, 0, 1, 1, 2, 2, 2]
    输出: [(0, 3, 0), (3, 5, 1), (5, 8, 2)]
    
    每个 tuple 是 (start, end, label)
    """
    prev_len = 0
    spans = []
    
    for label, group in itertools.groupby(token_prediction_sequence):
        cur_len = len(list(group))
        spans.append((prev_len, prev_len + cur_len, label))
        prev_len = prev_len + cur_len
    
    return spans


class BaseDocumentStructurePredictor:
    """
    文档结构预测器基类。
    
    子类需要实现:
    - preprocess: 将文档转换为模型输入
    - predict: 执行预测
    - postprocess: 将预测结果转换为 Entity 列表
    """
    
    def __init__(self, model_name_or_path: str):
        self.model_name_or_path = model_name_or_path
        # self.model = load_model(model_name_or_path)
        
        # 标签映射
        self.id2label = {i: label for i, label in enumerate(VILA_LABELS)}
        self.label2id = {label: i for i, label in enumerate(VILA_LABELS)}
    
    @abstractmethod
    def predict(self, document) -> List[dict]:
        """
        预测文档结构。
        
        :param document: 文档对象
        :return: 预测结果列表，每个元素是一个 Entity
        """
        pass
    
    def get_footnote_entities(self, document) -> List[dict]:
        """
        获取文档中的所有脚注实体。
        
        :param document: 文档对象
        :return: 脚注实体列表
        """
        all_entities = self.predict(document)
        return [e for e in all_entities if e.get('label') == 'Footnote']


# ============================================================
# 简化版脚注区域检测（可直接使用）
# ============================================================

def detect_footnote_region_by_position(
    blocks: List[dict],
    page_height: float,
    bottom_ratio: float = 0.2
) -> List[dict]:
    """
    基于位置启发式检测脚注区域。
    
    简单策略: 页面底部 20% 区域的小字体内容可能是脚注。
    
    :param blocks: 页面块列表，每个块包含 bbox 和 text
    :param page_height: 页面高度
    :param bottom_ratio: 底部区域比例
    :return: 可能是脚注的块列表
    """
    threshold_y = page_height * (1 - bottom_ratio)
    
    footnote_candidates = []
    for block in blocks:
        bbox = block.get('bbox', [0, 0, 0, 0])
        # bbox 格式: [x1, y1, x2, y2]
        if bbox[1] > threshold_y:  # y1 在底部区域
            footnote_candidates.append(block)
    
    return footnote_candidates


def detect_footnote_by_marker(
    text: str,
    markers: List[str] = None
) -> Optional[Tuple[str, str]]:
    """
    通过标记检测脚注。
    
    :param text: 待检测文本
    :param markers: 脚注标记列表
    :return: (marker, content) 或 None
    """
    import re
    
    if markers is None:
        # 常见脚注标记模式
        markers = [
            r'^(\d+)\.\s+',      # "1. content"
            r'^(\d+)\s+',        # "1 content"
            r'^\*\s+',           # "* content"
            r'^†\s+',            # "† content"
            r'^‡\s+',            # "‡ content"
            r'^§\s+',            # "§ content"
        ]
    
    for pattern in markers:
        match = re.match(pattern, text)
        if match:
            marker = match.group(1) if match.lastindex else match.group(0).strip()
            content = text[match.end():]
            return (marker, content)
    
    return None
