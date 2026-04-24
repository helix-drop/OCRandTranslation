"""视觉模型解析与聊天请求合并的单元测试。"""

import unittest
from unittest.mock import patch

import translation.translator as translator


class TestChatKwargsMerge(unittest.TestCase):
    def test_extra_body_deep_merge_preserves_enable_thinking(self):
        kw = {"model": "qwen-plus", "extra_body": {"enable_thinking": False}}
        translator._merge_overrides_into_chat_kwargs(
            kw,
            {"extra_body": {"translation_options": {"source_lang": "auto"}}},
        )
        self.assertFalse(kw["extra_body"]["enable_thinking"])
        self.assertEqual(kw["extra_body"]["translation_options"]["source_lang"], "auto")

    def test_messages_system_user(self):
        msgs = translator._chat_messages_for_model("S", "U")
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")


class TestResolveVisualModelSpec(unittest.TestCase):
    def test_visual_resolver_reads_fnm_pool_primary_slot(self):
        from persistence.storage import resolve_model_spec, resolve_visual_model_spec

        with patch(
            "persistence.storage.get_translation_model_pool",
            return_value=[{"mode": "builtin", "builtin_key": "deepseek-chat"}, {"mode": "empty"}, {"mode": "empty"}],
        ), patch(
            "persistence.storage.get_fnm_model_pool",
            return_value=[{"mode": "builtin", "builtin_key": "qwen3.6-plus"}, {"mode": "empty"}, {"mode": "empty"}],
        ):
            self.assertEqual(resolve_model_spec().model_id, "deepseek-chat")
            self.assertEqual(resolve_visual_model_spec().model_id, "qwen3.6-plus")

    def test_mt_builtin_exposes_capabilities_and_companion_chat(self):
        from persistence.storage import resolve_model_spec

        with patch(
            "persistence.storage.get_translation_model_pool",
            return_value=[{"mode": "builtin", "builtin_key": "qwen-mt-plus"}, {"mode": "empty"}, {"mode": "empty"}],
        ):
            spec = resolve_model_spec()

        self.assertEqual(spec.model_id, "qwen-mt-plus")
        self.assertEqual(spec.api_family, "mt")
        self.assertTrue(spec.supports_translation)
        self.assertFalse(spec.supports_vision)
        self.assertTrue(spec.supports_stream)
        self.assertEqual(spec.stream_mode, "mt_cumulative")
        self.assertEqual(spec.companion_chat_model_key, "qwen3.6-plus")

    def test_visual_builtin_exposes_vision_capabilities(self):
        from persistence.storage import resolve_visual_model_spec

        with patch(
            "persistence.storage.get_fnm_model_pool",
            return_value=[{"mode": "builtin", "builtin_key": "qwen3.6-plus"}, {"mode": "empty"}, {"mode": "empty"}],
        ):
            spec = resolve_visual_model_spec()

        self.assertEqual(spec.model_id, "qwen3.6-plus")
        self.assertEqual(spec.api_family, "vision")
        self.assertTrue(spec.supports_translation)
        self.assertTrue(spec.supports_vision)
        self.assertTrue(spec.supports_stream)
        self.assertEqual(spec.stream_mode, "chat_json")


if __name__ == "__main__":
    unittest.main()
