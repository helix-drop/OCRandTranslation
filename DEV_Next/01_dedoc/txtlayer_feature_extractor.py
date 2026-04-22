"""
来源: https://github.com/ispras/dedoc
文件: dedoc/readers/pdf_reader/pdf_auto_reader/txtlayer_classifier/txtlayer_feature_extractor.py
许可: Apache 2.0

功能: 从文本中提取特征，用于判断文字层是否损坏
核心思路: 
  1. 统计各类字符的比例
  2. 计算字符变化频率
  3. 检测"乱码特征"（trash_chars）

关键特征说明:
- letters_proportion: 正常文本应该有较高的字母比例
- trash_chars_proportion: 乱码文本会有很多不可打印字符
- case_changes: 正常文本的大小写变化是有规律的
- std_char_ord: 乱码文本的字符码点分布异常
"""

from collections import defaultdict
from typing import List

import numpy as np
import pandas as pd


# 字符集定义（简化版）
letters = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
digits = '0123456789'
special_symbols = '.,;:!?-–—\'\"()[]{}/'
brackets = '()[]{}⟨⟩'
rus = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
eng = 'abcdefghijklmnopqrstuvwxyz'
lower_letters = letters[:26] + rus
upper_letters = letters[26:] + rus.upper()
symbols = letters + digits


def count_symbols(text: str, char_set: str) -> int:
    """统计文本中属于指定字符集的字符数量"""
    return sum(1 for c in text if c in char_set)


class TxtlayerFeatureExtractor:
    """
    文字层特征提取器。
    
    用于从 PDF 提取的文本中提取特征，判断文字层是否有效。
    这是解决 Mad_Act 类乱码问题的关键组件。
    """

    def transform(self, texts: List[str]) -> pd.DataFrame:
        """
        从文本列表中提取特征。
        
        :param texts: 文本列表（每个元素是一页的文本）
        :return: 特征 DataFrame
        """
        features = defaultdict(list)

        for text in texts:
            if not text:
                # 处理空文本
                for key in self._get_feature_names():
                    features[key].append(0.0)
                continue
                
            num_letters = count_symbols(text, letters)
            num_digits = count_symbols(text, digits)
            num_special_symbols = count_symbols(text, special_symbols)
            num_brackets = count_symbols(text, brackets)
            num_rus = count_symbols(text, rus + rus.upper())
            num_eng = count_symbols(text, eng + eng.upper())

            # 基本比例特征
            features["letters_proportion"].append(num_letters / len(text))
            features["digits_proportion"].append(num_digits / len(text))
            features["special_symbols_proportion"].append(num_special_symbols / len(text))
            features["brackets_proportion"].append(num_brackets / len(text))
            features["rus_proportion"].append(num_rus / len(text))
            features["eng_proportion"].append(num_eng / len(text))

            # 所有有效字符的比例
            features["all_proportion"].append(
                (num_letters + num_digits + num_brackets + num_special_symbols) / len(text) 
                if len(text) != 0 else 0
            )

            # 大小写变化频率（正常文本有规律的变化）
            case_changes = sum(
                1 for s1, s2 in zip(text[:-1], text[1:]) 
                if (s1 in lower_letters) and (s2 in upper_letters)
            )
            features["case_changes"].append(case_changes / len(text))
            
            # 符号变化频率
            symbol_changes = sum(
                1 for s1, s2 in zip(text[:-1], text[1:]) 
                if (s1 in symbols) != (s2 in symbols)
            )
            features["symbol_changes"].append(symbol_changes / len(text))
            
            # 字母变化频率
            letter_changes = sum(
                1 for s1, s2 in zip(text[:-1], text[1:]) 
                if (s1 in letters) and (s2 not in symbols)
            )
            features["letter_changes"].append(letter_changes / len(text))

            # 词长统计
            words = text.split()
            if words:
                features["mean_word_length"].append(np.mean([len(word) for word in words]))
                features["median_word_length"].append(np.median([len(word) for word in words]))
            else:
                features["mean_word_length"].append(0)
                features["median_word_length"].append(0)

            # 乱码字符检测（关键特征！）
            # 乱码文本通常包含大量控制字符或特殊 Unicode 区域的字符
            all_characters_ord = [ord(character) for character in text]
            trash_chars = sum(
                1 for s in all_characters_ord 
                if s <= 32 or 160 <= s <= 879  # 控制字符和特殊区域
            )
            features["trash_chars_proportion"].append(trash_chars / len(text))
            features["trash_chars_number"].append(trash_chars)
            
            # 字符码点统计（乱码文本的分布异常）
            features["std_char_ord"].append(np.std(all_characters_ord))
            features["mean_char_ord"].append(np.mean(all_characters_ord))
            features["median_char_ord"].append(np.median(all_characters_ord))

        features = pd.DataFrame(features)
        return features[sorted(features.columns)].astype(float)
    
    def _get_feature_names(self) -> List[str]:
        """返回所有特征名称"""
        return [
            "letters_proportion", "digits_proportion", "special_symbols_proportion",
            "brackets_proportion", "rus_proportion", "eng_proportion", "all_proportion",
            "case_changes", "symbol_changes", "letter_changes",
            "mean_word_length", "median_word_length",
            "trash_chars_proportion", "trash_chars_number",
            "std_char_ord", "mean_char_ord", "median_char_ord"
        ]


# ============================================================
# 简化版快速检测函数（可直接使用）
# ============================================================

def quick_detect_garbled_text(text: str, threshold: float = 0.3) -> bool:
    """
    快速检测文本是否为乱码。
    
    :param text: 待检测文本
    :param threshold: 阈值，低于此值认为是乱码
    :return: True 表示有效文本，False 表示乱码
    """
    if not text or len(text) < 10:
        return False
    
    # 计算字母比例
    num_letters = count_symbols(text, letters)
    letters_ratio = num_letters / len(text)
    
    # 计算乱码字符比例
    trash_chars = sum(
        1 for c in text 
        if ord(c) <= 32 or 160 <= ord(c) <= 879
    )
    trash_ratio = trash_chars / len(text)
    
    # 判断逻辑
    # 1. 字母比例过低
    # 2. 乱码字符比例过高
    if letters_ratio < threshold or trash_ratio > 0.2:
        return False
    
    return True


def try_fix_shifted_encoding(text: str, offset: int = 48) -> str:
    """
    尝试修复字符偏移类型的乱码。
    
    这是针对 Mad_Act 类问题的专门修复方案。
    某些 PDF 使用非标准字体编码，字符码点有固定偏移。
    
    :param text: 乱码文本
    :param offset: 偏移量（Mad_Act 是 +48）
    :return: 修复后的文本
    """
    decoded = []
    for c in text:
        new_ord = ord(c) + offset
        if 32 <= new_ord <= 126:  # 可打印 ASCII 范围
            decoded.append(chr(new_ord))
        else:
            decoded.append(c)
    return ''.join(decoded)


def detect_and_fix_garbled(text: str) -> tuple:
    """
    检测并尝试修复乱码文本。
    
    :param text: 待检测文本
    :return: (is_valid, fixed_text, method)
        - is_valid: 最终是否有效
        - fixed_text: 修复后的文本（如果需要修复）
        - method: 使用的方法 ('original', 'offset_48', 'failed')
    """
    # 先检测原文是否有效
    if quick_detect_garbled_text(text):
        return True, text, 'original'
    
    # 尝试常见偏移修复
    for offset in [48, -48, 32, -32]:
        fixed = try_fix_shifted_encoding(text, offset)
        if quick_detect_garbled_text(fixed):
            return True, fixed, f'offset_{offset}'
    
    # 修复失败
    return False, text, 'failed'
