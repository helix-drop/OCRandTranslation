"""视觉模型解析与聊天请求合并的单元测试。"""

import unittest
from unittest.mock import patch

import translation.translator as translator
from config import _normalize_custom_model_config, load_config


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
    def test_visual_builtin_matches_translate_when_config_synced(self):
        from persistence.storage import resolve_model_spec, resolve_visual_model_spec

        disabled_custom = _normalize_custom_model_config({})
        with patch("persistence.storage.get_active_model_mode", return_value="builtin"), patch(
            "persistence.storage.get_active_builtin_model_key", return_value="deepseek-chat"
        ), patch("persistence.storage.get_active_visual_model_mode", return_value="builtin"), patch(
            "persistence.storage.get_active_builtin_visual_model_key", return_value="deepseek-chat"
        ), patch("persistence.storage.get_custom_model_config", return_value=disabled_custom), patch(
            "persistence.storage.get_visual_custom_model_config", return_value=disabled_custom
        ):
            self.assertEqual(
                resolve_visual_model_spec().model_id,
                resolve_model_spec().model_id,
                msg="迁移后视觉默认应与翻译一致",
            )
        self.assertIn("active_visual_model_mode", load_config())

    def test_mt_builtin_exposes_capabilities_and_companion_chat(self):
        from persistence.storage import resolve_model_spec

        disabled_custom = _normalize_custom_model_config({})
        with patch("persistence.storage.get_active_model_mode", return_value="builtin"), patch(
            "persistence.storage.get_active_builtin_model_key", return_value="qwen-mt-plus"
        ), patch("persistence.storage.get_custom_model_config", return_value=disabled_custom):
            spec = resolve_model_spec()

        self.assertEqual(spec.model_id, "qwen-mt-plus")
        self.assertEqual(spec.api_family, "mt")
        self.assertTrue(spec.supports_translation)
        self.assertFalse(spec.supports_vision)
        self.assertTrue(spec.supports_stream)
        self.assertEqual(spec.stream_mode, "mt_cumulative")
        self.assertEqual(spec.companion_chat_model_key, "qwen-plus")

    def test_visual_builtin_exposes_vision_capabilities(self):
        from persistence.storage import resolve_visual_model_spec

        disabled_custom = _normalize_custom_model_config({})
        with patch("persistence.storage.get_active_visual_model_mode", return_value="builtin"), patch(
            "persistence.storage.get_active_builtin_visual_model_key", return_value="qwen-vl-plus"
        ), patch("persistence.storage.get_visual_custom_model_config", return_value=disabled_custom):
            spec = resolve_visual_model_spec()

        self.assertEqual(spec.model_id, "qwen-vl-plus")
        self.assertEqual(spec.api_family, "vision")
        self.assertFalse(spec.supports_translation)
        self.assertTrue(spec.supports_vision)
        self.assertTrue(spec.supports_stream)
        self.assertEqual(spec.stream_mode, "chat_json")


if __name__ == "__main__":
    unittest.main()
