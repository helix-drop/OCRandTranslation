"""
document/text_layer_fixer.py 的单元测试
"""
import unittest
from document.text_layer_fixer import (
    detect_garbled_text,
    try_fix_encoding,
    detect_and_fix_text,
    analyze_encoding_pattern,
    process_pages_text,
    GarbledTextError,
)


class TestDetectGarbledText(unittest.TestCase):
    """测试乱码检测"""
    
    def test_normal_english_text_is_valid(self):
        """正常英文文本应识别为有效"""
        text = "The quick brown fox jumps over the lazy dog. This is a normal English sentence."
        is_valid, stats = detect_garbled_text(text)
        self.assertTrue(is_valid)
        self.assertGreater(stats['letter_ratio'], 0.8)
        self.assertGreater(stats['common_words_found'], 0)
    
    def test_mad_act_garbled_text_detected(self):
        """Mad_Act 类乱码应识别为无效"""
        garbled = "D85C5C3B9@DC G5B5D5=@<1D5C6?B45C3B929>7B51<9DI"
        is_valid, stats = detect_garbled_text(garbled)
        self.assertFalse(is_valid)
        self.assertIn('reasons', stats)
        # 应该有低小写字母比例的原因
        reasons_str = str(stats['reasons'])
        self.assertTrue('lower_ratio' in reasons_str or 'digit_ratio' in reasons_str)
    
    def test_short_text_invalid(self):
        """太短的文本应识别为无效"""
        is_valid, stats = detect_garbled_text("Hi")
        self.assertFalse(is_valid)
        self.assertEqual(stats['reason'], 'text_too_short')
    
    def test_empty_text_invalid(self):
        """空文本应识别为无效"""
        is_valid, stats = detect_garbled_text("")
        self.assertFalse(is_valid)


class TestTryFixEncoding(unittest.TestCase):
    """测试偏移修复"""
    
    def test_offset_48_fixes_mad_act(self):
        """+48 偏移应修复 Mad_Act 类乱码"""
        garbled = "D85C5C3B9@DC"  # "thesescripts" 的乱码版本
        fixed = try_fix_encoding(garbled, 48)
        self.assertEqual(fixed, "thesescripts")
    
    def test_preserves_whitespace(self):
        """空白字符应保留"""
        garbled = "D85 C5C"
        fixed = try_fix_encoding(garbled, 48)
        self.assertEqual(fixed, "the ses")


class TestDetectAndFixText(unittest.TestCase):
    """测试自动检测修复"""
    
    def test_normal_text_unchanged(self):
        """正常文本应原样返回"""
        text = "This is normal English text with common words."
        fixed, method = detect_and_fix_text(text, raise_on_failure=False)
        self.assertEqual(fixed, text)
        self.assertEqual(method, 'original')
    
    def test_mad_act_auto_fixed(self):
        """Mad_Act 乱码应自动用 offset_48 修复"""
        garbled = "D85C5C3B9@DC G5B5D5=@<1D5C6?B45C3B929>7B51<9DI"
        fixed, method = detect_and_fix_text(garbled, raise_on_failure=False)
        self.assertEqual(method, 'offset_48')
        # 修复后应包含可读英文
        self.assertIn('the', fixed.lower())

    def test_prefers_more_readable_candidate_when_multiple_offsets_are_valid(self):
        """多个偏移都可用时，应优先选择更像正常英文的结果"""
        garbled = "D85C5C3B9@DC G5B5D5=@<1D5C6?B45C3B929>7B51<9DI"
        fixed, method = detect_and_fix_text(garbled, raise_on_failure=False, custom_offsets=[46, 48])

        self.assertEqual(method, 'offset_48')
        self.assertIn('thesescripts', fixed.lower())
    
    def test_raises_on_unfixable(self):
        """无法修复时应抛出 GarbledTextError"""
        # 一个无法用简单偏移修复的字符串
        weird = "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
        with self.assertRaises(GarbledTextError) as ctx:
            detect_and_fix_text(weird, raise_on_failure=True)
        
        error = ctx.exception
        self.assertIn(weird[:20], error.sample)
        self.assertIsInstance(error.suggested_offsets, list)
    
    def test_no_raise_returns_none(self):
        """raise_on_failure=False 时应返回 None"""
        weird = "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
        fixed, method = detect_and_fix_text(weird, raise_on_failure=False)
        self.assertIsNone(method)


class TestAnalyzeEncodingPattern(unittest.TestCase):
    """测试编码模式分析"""
    
    def test_returns_analysis_dict(self):
        """应返回包含关键字段的字典"""
        garbled = "D85C5C3B9@DC G5B5D5=@<1D5C"
        analysis = analyze_encoding_pattern(garbled)
        
        self.assertIn('sample_chars', analysis)
        self.assertIn('ord_range', analysis)
        self.assertIn('common_chars', analysis)
        self.assertIn('possible_offsets', analysis)
    
    def test_suggests_plausible_offsets(self):
        """应能推测出可能的偏移量"""
        garbled = "D85C5C3B9@DC"
        analysis = analyze_encoding_pattern(garbled)
        # 应该返回一些可能的偏移量
        self.assertIsInstance(analysis['possible_offsets'], list)
        # 偏移量应该在合理范围内
        for offset in analysis['possible_offsets']:
            self.assertTrue(-200 < offset < 200)


class TestProcessPagesText(unittest.TestCase):
    """测试批量处理"""
    
    def test_process_mixed_pages(self):
        """应正确处理混合页面"""
        pages = [
            "Normal text with the word hello.",
            "D85C5C3B9@DC G5B5D5=@<1D5C",  # 可修复
            "",  # 空页
        ]
        
        fixed_texts, report = process_pages_text(pages, raise_on_failure=False)
        
        self.assertEqual(len(fixed_texts), 3)
        self.assertEqual(report['original_valid'], 1)
        self.assertGreaterEqual(report['fixed'], 1)


class TestGarbledTextError(unittest.TestCase):
    """测试错误类"""
    
    def test_str_output(self):
        """__str__ 应包含诊断信息"""
        error = GarbledTextError(
            "测试错误",
            sample="ABC123",
            suggested_offsets=[48, 32],
            stats={'letter_ratio': 0.5},
            encoding_analysis={'ord_range': (65, 90)}
        )
        
        output = str(error)
        self.assertIn("测试错误", output)
        self.assertIn("ABC123", output)
        self.assertIn("48", output)
        self.assertIn("pdffonts", output)
    
    def test_to_dict(self):
        """to_dict 应返回可序列化的字典"""
        error = GarbledTextError(
            "测试",
            sample="XYZ",
            suggested_offsets=[48]
        )
        
        d = error.to_dict()
        self.assertEqual(d['error'], "测试")
        self.assertEqual(d['sample'], "XYZ")
        self.assertEqual(d['tried_offsets'], [48])


if __name__ == '__main__':
    unittest.main()
