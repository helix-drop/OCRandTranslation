"""
文字层质量检测与修复模块

功能：
1. 检测PDF文字层提取的文本是否为乱码
2. 尝试常见的字符偏移修复
3. 无法修复时抛出异常，提供诊断信息

参考：Dedoc 项目的 txtlayer_feature_extractor.py
"""

from typing import Tuple, List, Optional
import re


class GarbledTextError(Exception):
    """
    文字层乱码且无法自动修复时抛出此异常。
    
    包含诊断信息帮助用户手动排查。
    """
    
    def __init__(self, message: str, sample: str, suggested_offsets: List[int] = None, 
                 stats: dict = None, encoding_analysis: dict = None):
        """
        :param message: 错误描述
        :param sample: 乱码文本样本（前200字符）
        :param suggested_offsets: 尝试过但未成功的偏移量列表
        :param stats: 检测统计信息
        :param encoding_analysis: 编码分析结果
        """
        super().__init__(message)
        self.sample = sample
        self.suggested_offsets = suggested_offsets or []
        self.stats = stats or {}
        self.encoding_analysis = encoding_analysis or {}
    
    def __str__(self):
        lines = [
            self.args[0],
            "",
            "=== 乱码样本（前200字符）===",
            self.sample[:200],
            "",
            "=== 诊断信息 ===",
            f"已尝试的偏移量: {self.suggested_offsets}",
        ]
        
        if self.stats:
            lines.append(f"检测统计: letter_ratio={self.stats.get('letter_ratio', 'N/A')}, "
                        f"lower_ratio={self.stats.get('lower_ratio', 'N/A')}, "
                        f"digit_ratio={self.stats.get('digit_ratio', 'N/A')}")
        
        if self.encoding_analysis:
            lines.append(f"字符范围: {self.encoding_analysis.get('ord_range', 'N/A')}")
            lines.append(f"可能的偏移量: {self.encoding_analysis.get('possible_offsets', [])}")
        
        lines.extend([
            "",
            "=== 建议 ===",
            "1. 用 `pdffonts <file.pdf>` 检查PDF字体编码",
            "2. 如果字体是 Identity-H 且 uni=no，说明使用了自定义编码",
            "3. 分析 common_chars 推测字符映射规律",
            "4. 如果是扫描件，考虑使用OCR重新识别",
            "5. 不同页面可能使用不同编码（如本例），需要分页处理",
        ])
        return "\n".join(lines)
    
    def to_dict(self) -> dict:
        """转换为字典，便于JSON序列化"""
        return {
            "error": self.args[0],
            "sample": self.sample[:200],
            "tried_offsets": self.suggested_offsets,
            "stats": self.stats,
            "encoding_analysis": self.encoding_analysis,
        }


# 字符集定义
LETTERS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
LETTERS_LOWER = 'abcdefghijklmnopqrstuvwxyz'
LETTERS_UPPER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
DIGITS = '0123456789'
PUNCTUATION = '.,;:!?-–—\'\"()[]{}/'
WHITESPACE = ' \t\n\r'

# 常见偏移量（按可能性排序，扩展范围）
COMMON_OFFSETS = [48, 47, 46, -48, -47, -46, 32, -32, 64, -64, 16, -16, 96, -96, 80, -80]


def count_chars(text: str, charset: str) -> int:
    """统计文本中属于指定字符集的字符数量"""
    return sum(1 for c in text if c in charset)


def detect_garbled_text(text: str, min_letter_ratio: float = 0.25) -> Tuple[bool, dict]:
    """
    检测文本是否为乱码。
    
    :param text: 待检测文本
    :param min_letter_ratio: 最低字母比例阈值
    :return: (is_valid, stats)
        - is_valid: True=有效文本, False=乱码
        - stats: 检测统计信息
    """
    if not text or len(text) < 10:
        return False, {"reason": "text_too_short", "length": len(text) if text else 0}
    
    # 去除空白后统计
    text_no_space = text.replace(" ", "").replace("\n", "").replace("\t", "")
    if len(text_no_space) < 5:
        return False, {"reason": "no_content"}
    
    # 统计各类字符
    num_letters = count_chars(text_no_space, LETTERS)
    num_lower = count_chars(text_no_space, LETTERS_LOWER)
    num_upper = count_chars(text_no_space, LETTERS_UPPER)
    num_digits = count_chars(text_no_space, DIGITS)
    num_punct = count_chars(text_no_space, PUNCTUATION)
    
    total = len(text_no_space)
    letter_ratio = num_letters / total
    lower_ratio = num_lower / total
    digit_ratio = num_digits / total
    punct_ratio = num_punct / total
    valid_ratio = (num_letters + num_digits + num_punct) / total
    
    # 统计乱码特征字符（控制字符、特殊Unicode区域）
    trash_chars = sum(
        1 for c in text_no_space
        if ord(c) < 32 or (127 < ord(c) < 160) or (160 <= ord(c) <= 879)
    )
    trash_ratio = trash_chars / total
    
    # 大小写变化检测（正常英文有规律的变化）
    case_changes = 0
    for i in range(len(text_no_space) - 1):
        c1, c2 = text_no_space[i], text_no_space[i+1]
        if c1 in LETTERS_LOWER and c2 in LETTERS_UPPER:
            case_changes += 1
    case_change_ratio = case_changes / total
    
    # 检测常见英语单词（关键特征！）
    common_words = ['the', 'and', 'for', 'that', 'this', 'with', 'from', 'are', 'was', 'have', 'not', 'but']
    text_lower = text.lower()
    words_found = sum(1 for w in common_words if w in text_lower)
    
    stats = {
        "length": total,
        "letter_ratio": round(letter_ratio, 3),
        "lower_ratio": round(lower_ratio, 3),
        "digit_ratio": round(digit_ratio, 3),
        "punct_ratio": round(punct_ratio, 3),
        "valid_ratio": round(valid_ratio, 3),
        "trash_ratio": round(trash_ratio, 3),
        "case_change_ratio": round(case_change_ratio, 3),
        "common_words_found": words_found,
    }
    
    # 判断逻辑
    is_valid = True
    reasons = []
    
    # 规则1：字母比例过低（纯数字混乱码常见模式）
    if letter_ratio < min_letter_ratio:
        is_valid = False
        reasons.append(f"letter_ratio={letter_ratio:.2f} < {min_letter_ratio}")
    
    # 规则2：小写字母比例过低（乱码特征：正常英文小写为主）
    # 对于长文本，小写字母应该占主导
    if total > 20 and lower_ratio < 0.15:
        is_valid = False
        reasons.append(f"lower_ratio={lower_ratio:.2f} < 0.15")
    
    # 规则3：数字比例过高（乱码经常表现为数字+大写字母）
    if digit_ratio > 0.4:
        is_valid = False
        reasons.append(f"digit_ratio={digit_ratio:.2f} > 0.4")
    
    # 规则4：乱码字符比例过高
    if trash_ratio > 0.15:
        is_valid = False
        reasons.append(f"trash_ratio={trash_ratio:.2f} > 0.15")
    
    # 规则5：大小写变化过于频繁（乱码特征）
    if case_change_ratio > 0.1:
        is_valid = False
        reasons.append(f"case_change_ratio={case_change_ratio:.2f} > 0.1")
    
    # 规则6：有效字符比例过低
    if valid_ratio < 0.5:
        is_valid = False
        reasons.append(f"valid_ratio={valid_ratio:.2f} < 0.5")
    
    # 规则7：长文本中没有常见单词（强烈乱码信号）
    if total > 50 and words_found == 0:
        is_valid = False
        reasons.append(f"no_common_words in {total} chars")
    
    if reasons:
        stats["reasons"] = reasons
    
    return is_valid, stats


def try_fix_encoding(text: str, offset: int) -> str:
    """
    尝试用字符偏移修复乱码。
    
    :param text: 乱码文本
    :param offset: 偏移量
    :return: 修复后的文本
    """
    result = []
    for c in text:
        if c in WHITESPACE:
            result.append(c)
            continue
        
        new_ord = ord(c) + offset
        # 保持在可打印ASCII范围或常见扩展范围
        if 32 <= new_ord <= 126:
            result.append(chr(new_ord))
        elif 160 <= new_ord <= 255:  # Latin-1扩展
            result.append(chr(new_ord))
        else:
            result.append(c)
    
    return ''.join(result)


def _candidate_readability_score(stats: dict, offset: int) -> tuple:
    """对多个可修复候选做排序，优先选择更像正常英文的结果。"""
    safe_stats = dict(stats or {})
    return (
        int(safe_stats.get("common_words_found") or 0),
        float(safe_stats.get("lower_ratio") or 0.0),
        float(safe_stats.get("letter_ratio") or 0.0),
        float(safe_stats.get("valid_ratio") or 0.0),
        -float(safe_stats.get("trash_ratio") or 0.0),
        -float(safe_stats.get("digit_ratio") or 0.0),
        -float(safe_stats.get("punct_ratio") or 0.0),
        -abs(int(offset or 0)),
    )


def detect_and_fix_text(
    text: str,
    raise_on_failure: bool = True,
    custom_offsets: List[int] = None
) -> Tuple[str, Optional[str]]:
    """
    检测文本质量，必要时尝试修复。
    
    :param text: 待检测/修复的文本
    :param raise_on_failure: 无法修复时是否抛出异常
    :param custom_offsets: 自定义偏移量列表（会优先尝试）
    :return: (fixed_text, method)
        - fixed_text: 修复后的文本
        - method: 使用的方法 ('original', 'offset_48', 等)
    :raises GarbledTextError: 当 raise_on_failure=True 且无法修复时
    """
    # 先检测原文
    is_valid, stats = detect_garbled_text(text)
    if is_valid:
        return text, 'original'
    
    # 构建偏移量列表
    offsets_to_try = []
    if custom_offsets:
        offsets_to_try.extend(custom_offsets)
    offsets_to_try.extend([o for o in COMMON_OFFSETS if o not in offsets_to_try])
    
    # 尝试各种偏移
    tried_offsets = []
    best_candidate: Optional[Tuple[tuple, str, str]] = None
    for offset in offsets_to_try:
        tried_offsets.append(offset)
        fixed = try_fix_encoding(text, offset)
        is_valid, fixed_stats = detect_garbled_text(fixed)
        if is_valid:
            candidate = (_candidate_readability_score(fixed_stats, offset), fixed, f'offset_{offset}')
            if best_candidate is None or candidate[0] > best_candidate[0]:
                best_candidate = candidate
    
    if best_candidate is not None:
        _, fixed_text, method = best_candidate
        return fixed_text, method
    
    # 修复失败 - 收集诊断信息
    if raise_on_failure:
        encoding_analysis = analyze_encoding_pattern(text)
        raise GarbledTextError(
            "文字层乱码且无法自动修复",
            sample=text[:200],
            suggested_offsets=tried_offsets,
            stats=stats,
            encoding_analysis=encoding_analysis
        )
    
    return text, None


def analyze_encoding_pattern(text: str, sample_size: int = 100) -> dict:
    """
    分析乱码文本的编码模式，帮助手动诊断。
    
    :param text: 乱码文本
    :param sample_size: 分析的字符数量
    :return: 分析结果
    """
    sample = text[:sample_size].replace(" ", "").replace("\n", "")
    
    # 字符码点分布
    ords = [ord(c) for c in sample]
    
    result = {
        "sample_chars": sample[:50],
        "char_count": len(sample),
        "ord_range": (min(ords), max(ords)) if ords else (0, 0),
        "ord_mean": sum(ords) / len(ords) if ords else 0,
        "common_chars": {},
        "possible_offsets": [],
    }
    
    # 统计最常见的字符
    from collections import Counter
    char_counts = Counter(sample)
    result["common_chars"] = dict(char_counts.most_common(10))
    
    # 猜测可能的偏移量
    # 假设最常见的字符应该是 'e', 't', 'a', 'o', 'i', 'n', 's', 'r'
    common_english = 'etaoinsrhl'
    if char_counts:
        most_common_char = char_counts.most_common(1)[0][0]
        most_common_ord = ord(most_common_char)
        for expected in common_english:
            offset = ord(expected) - most_common_ord
            if offset != 0 and abs(offset) < 200:
                result["possible_offsets"].append(offset)
    
    result["possible_offsets"] = list(set(result["possible_offsets"]))[:5]
    
    return result


# 批量处理接口

def process_pages_text(
    pages_text: List[str],
    raise_on_failure: bool = True
) -> Tuple[List[str], dict]:
    """
    批量处理多页文本。
    
    :param pages_text: 每页的文本列表
    :param raise_on_failure: 无法修复时是否抛出异常
    :return: (fixed_texts, report)
        - fixed_texts: 修复后的文本列表
        - report: 处理报告
    """
    fixed_texts = []
    report = {
        "total_pages": len(pages_text),
        "original_valid": 0,
        "fixed": 0,
        "failed": 0,
        "methods_used": {},
        "failed_pages": [],
    }
    
    for i, text in enumerate(pages_text):
        try:
            fixed, method = detect_and_fix_text(text, raise_on_failure=False)
            fixed_texts.append(fixed)
            
            if method == 'original':
                report["original_valid"] += 1
            elif method:
                report["fixed"] += 1
                report["methods_used"][method] = report["methods_used"].get(method, 0) + 1
            else:
                report["failed"] += 1
                report["failed_pages"].append(i)
                
        except Exception as e:
            fixed_texts.append(text)
            report["failed"] += 1
            report["failed_pages"].append(i)
    
    # 如果失败比例过高，抛出异常
    if raise_on_failure and report["failed"] > len(pages_text) * 0.5:
        sample = pages_text[0] if pages_text else ""
        raise GarbledTextError(
            f"超过50%的页面无法修复 ({report['failed']}/{len(pages_text)})",
            sample=sample[:200],
            suggested_offsets=COMMON_OFFSETS
        )
    
    return fixed_texts, report
