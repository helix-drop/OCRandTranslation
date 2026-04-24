"""双池三槽模型配置与 MiMo 解析测试。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

import config


class ModelPoolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = tempfile.mkdtemp(prefix="model-pools-")
        self._patch_config_dirs(self.temp_root)
        config.ensure_dirs()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str) -> None:
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def test_load_config_migrates_legacy_single_model_fields_to_primary_slots(self) -> None:
        with open(config.CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "model_key": "deepseek-chat",
                    "active_model_mode": "custom",
                    "custom_model": {
                        "enabled": True,
                        "display_name": "Qwen 3.5 Plus",
                        "provider_type": "qwen",
                        "model_id": "qwen3.5-plus",
                        "qwen_region": "sg",
                        "extra_body": {"enable_thinking": False},
                    },
                    "active_visual_model_mode": "builtin",
                    "active_builtin_visual_model_key": "qwen-vl-plus",
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )

        migrated = config.load_config()

        self.assertIn("translation_model_pool", migrated)
        self.assertIn("fnm_model_pool", migrated)
        self.assertEqual(len(migrated["translation_model_pool"]), 3)
        self.assertEqual(len(migrated["fnm_model_pool"]), 3)
        self.assertEqual(migrated["translation_model_pool"][0]["mode"], "custom")
        self.assertEqual(migrated["translation_model_pool"][0]["provider_type"], "qwen")
        self.assertEqual(migrated["translation_model_pool"][0]["model_id"], "qwen3.5-plus")
        self.assertEqual(migrated["fnm_model_pool"][0]["mode"], "builtin")
        self.assertEqual(migrated["fnm_model_pool"][0]["builtin_key"], "qwen3.6-plus")

    def test_resolve_translation_model_pool_specs_supports_mimo_paygo(self) -> None:
        from persistence.storage import resolve_translation_model_pool_specs

        config.save_config(
            {
                "mimo_api_key": "mimo-paygo-key",
                "translation_model_pool": [
                    {
                        "mode": "builtin",
                        "builtin_key": "deepseek-chat",
                    },
                    {
                        "mode": "custom",
                        "display_name": "MiMo Flash",
                        "provider_type": "mimo",
                        "model_id": "mimo-v2-flash",
                    },
                    {"mode": "empty"},
                ],
                "fnm_model_pool": [{"mode": "builtin", "builtin_key": "qwen-vl-plus"}, {"mode": "empty"}, {"mode": "empty"}],
            }
        )

        specs = resolve_translation_model_pool_specs()

        self.assertEqual(len(specs), 2)
        self.assertEqual(specs[1].provider, "mimo")
        self.assertEqual(specs[1].model_id, "mimo-v2-flash")
        self.assertEqual(specs[1].base_url, "https://api.xiaomimimo.com/v1")
        self.assertEqual(specs[1].api_key, "mimo-paygo-key")

    def test_resolve_fnm_model_pool_specs_supports_mimo_token_plan(self) -> None:
        from model_capabilities import get_selectable_models
        from persistence.storage import resolve_fnm_model_pool_specs

        config.save_config(
            {
                "translation_model_pool": [{"mode": "builtin", "builtin_key": "deepseek-chat"}, {"mode": "empty"}, {"mode": "empty"}],
                "fnm_model_pool": [
                    {
                        "mode": "custom",
                        "display_name": "MiMo Omni Token Plan",
                        "provider_type": "mimo_token_plan",
                        "model_id": "mimo-v2-omni",
                        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                        "custom_api_key": "mimo-token-plan-key",
                    },
                    {"mode": "empty"},
                    {"mode": "empty"},
                ],
            }
        )

        specs = resolve_fnm_model_pool_specs()

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].provider, "mimo_token_plan")
        self.assertEqual(specs[0].base_url, "https://token-plan-cn.xiaomimimo.com/v1")
        self.assertEqual(specs[0].api_key, "mimo-token-plan-key")
        self.assertIn("mimo-v2.5", get_selectable_models("fnm"))
        self.assertIn("mimo-v2-omni", get_selectable_models("fnm"))
        self.assertNotIn("mimo-v2.5-pro", get_selectable_models("fnm"))

    def test_selectable_model_pools_are_curated_by_capability(self) -> None:
        from model_capabilities import get_selectable_models

        translation_models = get_selectable_models("translation")
        fnm_models = get_selectable_models("fnm")

        for key in (
            "deepseek-chat",
            "deepseek-reasoner",
            "qwen3.6-max-preview",
            "qwen3.6-plus",
            "qwen3.6-flash",
            "qwen-mt-plus",
            "glm-5.1",
            "glm-5",
            "kimi-k2.6",
            "kimi-k2.5",
            "moonshot-v1-128k",
            "mimo-v2.5-pro",
            "mimo-v2-pro",
        ):
            self.assertIn(key, translation_models)

        for key in (
            "qwen-vl-plus",
            "qwen-vl-ocr",
            "qwen3-vl-plus",
            "glm-5v-turbo",
            "moonshot-v1-128k-vision-preview",
            "mimo-v2-omni",
        ):
            self.assertNotIn(key, translation_models)

        for key in (
            "qwen3.6-plus",
            "qwen3.6-flash",
            "qwen3-vl-plus",
            "qwen3-vl-flash",
            "glm-5v-turbo",
            "glm-4.6v",
            "kimi-k2.6",
            "kimi-k2.5",
            "mimo-v2.5",
            "mimo-v2-omni",
        ):
            self.assertIn(key, fnm_models)

        for key in (
            "deepseek-chat",
            "qwen-mt-plus",
            "qwen-vl-plus",
            "qwen-vl-ocr",
            "glm-5.1",
            "kimi-k2-0905-preview",
            "moonshot-v1-128k",
            "mimo-v2.5-pro",
        ):
            self.assertNotIn(key, fnm_models)

    def test_qwen_multimodal_thinking_payload_survives_fnm_pool_resolution(self) -> None:
        from persistence.storage import resolve_fnm_model_pool_specs

        config.save_config(
            {
                "dashscope_key": "dashscope-key",
                "fnm_model_pool": [
                    {
                        "mode": "builtin",
                        "builtin_key": "qwen3.6-plus",
                        "thinking_enabled": True,
                    },
                    {"mode": "builtin", "builtin_key": "qwen3.6-flash"},
                    {"mode": "empty"},
                ],
            }
        )

        specs = resolve_fnm_model_pool_specs()

        self.assertEqual(specs[0].model_id, "qwen3.6-plus")
        self.assertTrue(specs[0].supports_vision)
        self.assertEqual(specs[0].request_overrides, {"extra_body": {"enable_thinking": True}})
        self.assertEqual(specs[1].model_id, "qwen3.6-flash")
        self.assertEqual(specs[1].request_overrides, {"extra_body": {"enable_thinking": False}})

    def test_translation_retry_pool_skips_slots_without_credentials(self) -> None:
        from translation.service import _get_translation_model_pool_args

        config.save_config(
            {
                "translation_model_pool": [
                    {"mode": "builtin", "builtin_key": "deepseek-chat"},
                    {
                        "mode": "custom",
                        "display_name": "Missing Key",
                        "provider_type": "openai_compatible",
                        "model_id": "missing-key-model",
                        "base_url": "https://example.invalid/v1",
                        "custom_api_key": "",
                    },
                    {
                        "mode": "custom",
                        "display_name": "Ready Model",
                        "provider_type": "openai_compatible",
                        "model_id": "ready-model",
                        "base_url": "https://example.invalid/v1",
                        "custom_api_key": "ready-key",
                    },
                ],
            }
        )

        candidates = _get_translation_model_pool_args()

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][1]["model_id"], "ready-model")

    def test_custom_openai_compatible_fnm_slot_defaults_to_visual_capability(self) -> None:
        from persistence.storage import resolve_fnm_model_pool_specs

        config.save_config(
            {
                "fnm_model_pool": [
                    {
                        "mode": "custom",
                        "display_name": "Vision Compat",
                        "provider_type": "openai_compatible",
                        "model_id": "vision-compatible-model",
                        "base_url": "https://example.invalid/v1",
                        "custom_api_key": "vision-key",
                    },
                    {"mode": "empty"},
                    {"mode": "empty"},
                ],
            }
        )

        specs = resolve_fnm_model_pool_specs()

        self.assertEqual(len(specs), 1)
        self.assertTrue(specs[0].supports_vision)

    def test_resolve_model_pool_specs_supports_glm_and_kimi_with_thinking(self) -> None:
        from model_capabilities import get_selectable_models
        from persistence.storage import resolve_fnm_model_pool_specs, resolve_translation_model_pool_specs

        config.save_config(
            {
                "glm_api_key": "glm-key",
                "kimi_api_key": "kimi-key",
                "translation_model_pool": [
                    {
                        "mode": "builtin",
                        "builtin_key": "glm-5.1",
                        "thinking_enabled": True,
                    },
                    {
                        "mode": "builtin",
                        "builtin_key": "kimi-k2.6",
                        "thinking_enabled": False,
                    },
                    {"mode": "empty"},
                ],
                "fnm_model_pool": [
                    {
                        "mode": "builtin",
                        "builtin_key": "glm-5v-turbo",
                        "thinking_enabled": True,
                    },
                    {
                        "mode": "builtin",
                        "builtin_key": "kimi-k2.6",
                        "thinking_enabled": True,
                    },
                    {"mode": "empty"},
                ],
            }
        )

        translation_specs = resolve_translation_model_pool_specs()
        fnm_specs = resolve_fnm_model_pool_specs()

        self.assertIn("glm-5.1", get_selectable_models("translation"))
        self.assertIn("glm-5v-turbo", get_selectable_models("fnm"))
        self.assertIn("kimi-k2.6", get_selectable_models("translation"))
        self.assertIn("kimi-k2.6", get_selectable_models("fnm"))
        self.assertEqual(translation_specs[0].provider, "glm")
        self.assertEqual(translation_specs[0].base_url, "https://open.bigmodel.cn/api/paas/v4/")
        self.assertEqual(translation_specs[0].api_key, "glm-key")
        self.assertEqual(
            translation_specs[0].request_overrides,
            {"extra_body": {"thinking": {"type": "enabled"}}},
        )
        self.assertEqual(translation_specs[1].provider, "kimi")
        self.assertEqual(translation_specs[1].base_url, "https://api.moonshot.ai/v1")
        self.assertEqual(translation_specs[1].api_key, "kimi-key")
        self.assertEqual(
            translation_specs[1].request_overrides,
            {"extra_body": {"thinking": {"type": "disabled"}}},
        )
        self.assertEqual(fnm_specs[0].provider, "glm")
        self.assertEqual(fnm_specs[0].request_overrides["extra_body"]["thinking"]["type"], "enabled")
        self.assertEqual(fnm_specs[1].provider, "kimi")
        self.assertEqual(fnm_specs[1].request_overrides["extra_body"]["thinking"]["type"], "enabled")

    def test_custom_provider_slots_apply_provider_specific_thinking_payloads(self) -> None:
        from persistence.storage import resolve_translation_model_pool_specs

        config.save_config(
            {
                "translation_model_pool": [
                    {
                        "mode": "custom",
                        "display_name": "DeepSeek Chat Think",
                        "provider_type": "deepseek",
                        "model_id": "deepseek-chat",
                        "thinking_enabled": True,
                    },
                    {
                        "mode": "custom",
                        "display_name": "Qwen Think",
                        "provider_type": "qwen",
                        "model_id": "qwen-plus",
                        "thinking_enabled": True,
                    },
                    {
                        "mode": "custom",
                        "display_name": "GLM Custom",
                        "provider_type": "glm",
                        "model_id": "glm-5",
                        "thinking_enabled": False,
                    },
                ],
            }
        )

        specs = resolve_translation_model_pool_specs()

        self.assertEqual(
            specs[0].request_overrides,
            {"extra_body": {"thinking": {"type": "enabled"}}},
        )
        self.assertEqual(
            specs[1].request_overrides,
            {"extra_body": {"enable_thinking": True}},
        )
        self.assertEqual(
            specs[2].request_overrides,
            {"extra_body": {"thinking": {"type": "disabled"}}},
        )


if __name__ == "__main__":
    unittest.main()
