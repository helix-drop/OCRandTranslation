"""Smoke tests for the redesigned settings page layout."""

from __future__ import annotations

import unittest

from web.app_factory import create_app


class SettingsPageRedesignSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True)

    def setUp(self):
        self.client = self.app.test_client()

    def _get_html(self):
        resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 200)
        return resp.get_data(as_text=True)

    def test_sidebar_shows_all_seven_panels(self):
        html = self._get_html()
        for nav_key in (
            'data-nav="providers"',
            'data-nav="translation-pool"',
            'data-nav="fnm-pool"',
            'data-nav="concurrency"',
            'data-nav="glossary"',
            'data-nav="toc"',
            'data-nav="data"',
        ):
            self.assertIn(nav_key, html, f"missing sidebar entry: {nav_key}")

    def test_providers_panel_has_six_rows(self):
        html = self._get_html()
        for section in ("paddle", "deepseek", "dashscope", "glm", "kimi", "mimo"):
            self.assertIn(f'data-section="{section}"', html)
        self.assertIn('id="providersForm"', html)

    def test_model_pools_render_three_slots_each(self):
        html = self._get_html()
        for prefix in (
            "translation_model_pool_slot1_mode",
            "translation_model_pool_slot2_mode",
            "translation_model_pool_slot3_mode",
            "fnm_model_pool_slot1_mode",
            "fnm_model_pool_slot2_mode",
            "fnm_model_pool_slot3_mode",
        ):
            self.assertIn(prefix, html)

    def test_preserves_current_model_labels(self):
        html = self._get_html()
        self.assertIn("当前主翻译模型", html)
        self.assertIn("当前主 FNM 模型", html)

    def test_loads_new_css_and_js(self):
        html = self._get_html()
        self.assertIn("static/settings.css", html)
        self.assertIn("static/settings.js", html)


if __name__ == "__main__":
    unittest.main()
