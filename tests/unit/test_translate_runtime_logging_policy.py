from __future__ import annotations

import unittest

from translation.translate_runtime import _translate_event_log_message


class TranslateRuntimeLoggingPolicyTest(unittest.TestCase):
    def test_stream_delta_content_is_not_logged(self) -> None:
        message = _translate_event_log_message("stream_para_delta", {"text": "不应写入日志的翻译正文"})
        self.assertIsNone(message)

    def test_stream_error_is_logged(self) -> None:
        message = _translate_event_log_message("stream_para_error", {"para_idx": 2, "error": "rate limit"})
        self.assertIsNotNone(message)
        level, text = message or ("", "")
        self.assertEqual(level, "ERROR")
        self.assertIn("第 3 段翻译失败", text)


if __name__ == "__main__":
    unittest.main()
