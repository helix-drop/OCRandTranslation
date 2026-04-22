"""
来源: https://github.com/ispras/dedoc
文件: dedoc/readers/pdf_reader/pdf_auto_reader/txtlayer_detector.py
许可: Apache 2.0

功能: 检测 PDF 文档的文字层是否有效/可用
核心思路: 
  1. 使用 pdfminer 提取文字层
  2. 用 ML 分类器判断文字层是否损坏
  3. 支持按页检测，处理首页特殊情况
"""

import logging
import math
from copy import deepcopy
from itertools import chain
from typing import List

import numpy as np

# from dedoc.data_structures.unstructured_document import UnstructuredDocument
# from dedoc.readers.pdf_reader.pdf_auto_reader.txtlayer_classifier import get_classifiers
# from dedoc.readers.pdf_reader.pdf_auto_reader.txtlayer_classifier.abstract_txtlayer_classifier import AbstractTxtlayerClassifier
# from dedoc.readers.pdf_reader.pdf_auto_reader.txtlayer_result import TxtLayerResult
# from dedoc.readers.pdf_reader.pdf_txtlayer_reader.pdf_tabby_reader import PdfTabbyReader
# from dedoc.utils.parameter_utils import get_bool_parameter, get_param_page_slice
# from dedoc.utils.pdf_utils import get_pdf_page_count


class TxtLayerDetector:
    """
    检测 PDF 文字层是否有效。
    
    这个类的核心价值:
    1. 自动判断文字层质量
    2. 支持按页检测
    3. 处理首页特殊情况（很多PDF只有首页无文字层）
    """

    def __init__(self, pdf_reader, *, config: dict) -> None:
        self.config = config
        self.logger = config.get("logger", logging.getLogger())
        # self.classifiers = get_classifiers(config=config)
        self.pdf_reader = pdf_reader

    def detect_txtlayer(self, path: str, parameters: dict):  # -> List[TxtLayerResult]:
        """
        检测 PDF 文档是否有有效的文字层。

        :param path: PDF 文件路径
        :param parameters: 参数字典
        :return: 文字层检测结果列表
        """
        classifier_name = str(parameters.get("textual_layer_classifier", "ml")).lower()
        txtlayer_classifier = self.classifiers.get(classifier_name)
        if txtlayer_classifier is None:
            raise ValueError(f"Unknown textual layer classifier `{classifier_name}`")

        classify_each_page = parameters.get("each_page_textual_layer_detection", False)
        detect_function = self.__classify_each_page if classify_each_page else self.__classify_all_pages
        
        try:
            return detect_function(path, parameters, txtlayer_classifier)
        except Exception as e:
            self.logger.debug(f"Error occurred white detecting PDF textual layer ({e})")
            # 出错时默认认为文字层无效
            return [{"correct": False, "start": 1, "end": None}]

    def __classify_all_pages(self, path: str, parameters: dict, txtlayer_classifier):
        """
        只检查文档前8页，结果应用于整个文档。
        单独处理首页（首页无文字层是常见情况）。
        
        这是一个优化策略：不需要检查所有页面。
        """
        start = 1
        parameters_copy = deepcopy(parameters)
        parameters_copy["pages"] = "1:8"  # 只检查前8页
        parameters_copy["need_pdf_table_analysis"] = "false"

        document = self.pdf_reader.read(path, parameters=parameters_copy)
        is_correct = txtlayer_classifier.predict([document.lines])[0]
        
        if not is_correct:
            return [{"correct": False, "start": start, "end": None}]

        # 单独检查首页
        first_page_lines = [line for line in document.lines if line.metadata.page_id == 0]
        first_page_correct = txtlayer_classifier.predict([first_page_lines])[0]
        
        if first_page_correct:
            return [{"correct": True, "start": start, "end": None}]
        else:
            # 首页无效，其他页有效
            return [
                {"correct": False, "start": start, "end": start}, 
                {"correct": True, "start": start + 1, "end": None}
            ]

    def __classify_each_page(self, path: str, parameters: dict, txtlayer_classifier):
        """
        逐页检测文字层是否有效。
        
        返回结果是连续相同状态的页面范围列表。
        例如: [
            {"correct": False, "start": 1, "end": 2},  # 1-2页无效
            {"correct": True, "start": 3, "end": 10},  # 3-10页有效
            {"correct": False, "start": 11, "end": 15} # 11-15页无效
        ]
        """
        document = self.pdf_reader.read(path, parameters=parameters)
        start = 1
        
        if not document.lines:
            return [{"correct": False, "start": start, "end": None}]

        # 按页分组行
        lines = sorted(document.lines, key=lambda l: (l.metadata.page_id, l.metadata.line_id))
        lines_by_page = []
        last_page_id = lines[-1].metadata.page_id
        
        for page_id in range(0, last_page_id + 1):
            page_lines = [l for l in lines if l.metadata.page_id == page_id]
            lines_by_page.append(page_lines)

        # 批量预测
        predictions = txtlayer_classifier.predict(lines_by_page)
        
        # 找出状态变化点
        # 例如 predictions = [0, 0, 1, 1, 0, 1, 0, 0, 1]
        # transitions = [2, 4, 5, 6, 8] (状态变化的位置)
        transitions = list(np.where(predictions[:-1] != predictions[1:])[0] + 1)
        transitions.append(len(predictions))
        
        # 构建结果
        result = []
        is_correct = predictions[0]
        prev_idx = 0
        
        for transition_idx in transitions:
            result.append({
                "start": prev_idx + start,
                "end": transition_idx + start - 1,
                "correct": bool(is_correct)
            })
            is_correct = not is_correct
            prev_idx = transition_idx

        return result
