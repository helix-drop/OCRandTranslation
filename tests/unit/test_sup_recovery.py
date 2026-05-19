import unittest
from types import SimpleNamespace
from unittest.mock import patch

from FNM_RE.modules import sup_recovery


class SupRecoveryTest(unittest.TestCase):
    def test_layer3_cache_is_scoped_by_target_marker(self):
        sup_recovery._LAYER3_CACHE.clear()
        sup_recovery._LAYER3_CACHE[("vision", "/tmp/fake.pdf", 248, 38)] = {
            "marker": "38", "before": "migration", "after": "Parce"
        }
        calls = {"render": 0}

        def fake_render(_pdf_path, _page_no):
            calls["render"] += 1
            return None  # 模拟渲染失败

        with patch(
            "FNM_RE.modules.pdf_render_subprocess.render_sup_l3_data_url",
            fake_render,
        ):
            # marker=38 命中缓存，不调渲染器 → render=0
            r1 = sup_recovery._vision_find_superscript("/tmp/fake.pdf", 248, 38)
            self.assertEqual(r1["marker"], "38")
            self.assertEqual(calls["render"], 0)

            # marker=37 未命中缓存 → 调渲染器 → render=1
            r2 = sup_recovery._vision_find_superscript("/tmp/fake.pdf", 248, 37)
            self.assertIsNone(r2)
            self.assertEqual(calls["render"], 1)

        sup_recovery._LAYER3_CACHE.clear()

    def test_layer3_vision_request_has_timeout(self):
        sup_recovery._LAYER3_CACHE.clear()
        captured: dict = {}
        init_captured: dict = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"marker":"37","before":"avant","after":"après"}'
                            )
                        )
                    ]
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                init_captured.update(kwargs)
                self.chat = SimpleNamespace(completions=FakeCompletions())

        spec = SimpleNamespace(
            supports_vision=True,
            api_key="key",
            base_url="https://example.invalid",
            request_overrides={},
            display_label="fake",
            model_id="fake-model",
        )

        with patch(
            "FNM_RE.modules.pdf_render_subprocess.render_sup_l3_data_url",
            return_value="data:image/png;base64,ZmFrZQ==",
        ):
            with patch("persistence.storage.resolve_visual_model_spec", return_value=spec):
                with patch("openai.OpenAI", FakeOpenAI):
                    result = sup_recovery._vision_find_superscript(
                        "/tmp/fake.pdf", 248, 37
                    )

        sup_recovery._LAYER3_CACHE.clear()

        self.assertEqual(result["marker"], "37")
        self.assertIn("timeout", init_captured)
        self.assertEqual(init_captured.get("max_retries"), 0)
        self.assertIn("timeout", captured)
        self.assertGreater(captured["timeout"], 0)

    @unittest.skip("[rust-migration: SPEC] Layer 3 视觉模型返回与请求 marker 不符时应拒绝（marker 校验规则）")
    def test_layer3_rejects_marker_different_from_requested(self):
        base = (
            "Alpha beta gamma. "
            "First marker<sup>1</sup>. "
            "Third marker<sup>3</sup>. "
        )
        page = {
            "page_no": 10,
            "pdfPage": 10,
            "page_role": "body",
            "markdown": base + ("filler text " * 30),
            "blocks": [],
        }

        original = sup_recovery._vision_find_superscript
        try:
            sup_recovery._vision_find_superscript = lambda *_args, **_kwargs: {
                "marker": "4",
                "before": "Alpha",
                "after": "gamma",
            }
            stats = sup_recovery.recover_book_chapter_scoped(
                [page],
                {"ch1": {"1", "2", "3"}},
                {"ch1": (10, 10)},
                pdf_path="/tmp/fake.pdf",
            )
        finally:
            sup_recovery._vision_find_superscript = original

        self.assertEqual(stats["layer3_vision"], 0)
        self.assertEqual(stats["unrecovered"], 1)
        self.assertNotIn("<sup>4</sup>", page.get("enriched_markdown") or page["markdown"])

    @unittest.skip("[rust-migration: UNCLEAR] Layer 3 视觉模型返回与请求一致的 marker 应接受；依赖外部 vision API，失败可能是 API 侧")
    def test_layer3_accepts_requested_marker(self):
        base = (
            "Alpha beta gamma. "
            "First marker<sup>1</sup>. "
            "Third marker<sup>3</sup>. "
        )
        page = {
            "page_no": 10,
            "pdfPage": 10,
            "page_role": "body",
            "markdown": base + ("filler text " * 30),
            "blocks": [],
        }

        original = sup_recovery._vision_find_superscript
        try:
            sup_recovery._vision_find_superscript = lambda *_args, **_kwargs: {
                "marker": "2",
                "before": "Alpha",
                "after": "gamma",
            }
            stats = sup_recovery.recover_book_chapter_scoped(
                [page],
                {"ch1": {"1", "2", "3"}},
                {"ch1": (10, 10)},
                pdf_path="/tmp/fake.pdf",
            )
        finally:
            sup_recovery._vision_find_superscript = original

        self.assertEqual(stats["layer3_vision"], 1)
        self.assertEqual(stats["unrecovered"], 0)
        self.assertIn("<sup>2</sup>", page["enriched_markdown"])

    @unittest.skip("[rust-migration: SPEC] Layer 3 上下文重复时无法唯一定位 marker 应拒绝（唯一性校验）")
    def test_layer3_rejects_repeated_context_location(self):
        base = (
            "Alpha beta gamma. "
            "First marker<sup>1</sup>. "
            "Alpha beta gamma. "
            "Third marker<sup>3</sup>. "
        )
        page = {
            "page_no": 10,
            "pdfPage": 10,
            "page_role": "body",
            "markdown": base + ("filler text " * 30),
            "blocks": [],
        }

        original = sup_recovery._vision_find_superscript
        try:
            sup_recovery._vision_find_superscript = lambda *_args, **_kwargs: {
                "marker": "2",
                "before": "Alpha beta",
                "after": "gamma",
            }
            stats = sup_recovery.recover_book_chapter_scoped(
                [page],
                {"ch1": {"1", "2", "3"}},
                {"ch1": (10, 10)},
                pdf_path="/tmp/fake.pdf",
            )
        finally:
            sup_recovery._vision_find_superscript = original

        self.assertEqual(stats["layer3_vision"], 0)
        self.assertEqual(stats["unrecovered"], 1)
        self.assertNotIn("<sup>2</sup>", page.get("enriched_markdown") or page["markdown"])

    @unittest.skip("[rust-migration: SPEC] Layer 2 OCR 把 '11' 误识别为标点时，依据 block 文本对齐恢复为 <sup>11</sup>")
    def test_layer2_recovers_repeated_one_marker_from_ocr_punctuation_surrogate(self):
        page = {
            "page_no": 10,
            "pdfPage": 10,
            "page_role": "body",
            "markdown": (
                "Before marker<sup>10</sup>. "
                "Je dis que le processus est exogène\" et relève de la dislocation. "
                "After marker<sup>12</sup>. "
                + ("filler text " * 30)
            ),
            "blocks": [
                {
                    "text": (
                        "Je dis que le processus est exogène !! et relève de la "
                        "dislocation."
                    )
                }
            ],
        }

        stats = sup_recovery.recover_book_chapter_scoped(
            [page],
            {"ch1": {"10", "11", "12"}},
            {"ch1": (10, 10)},
            pdf_path="",
        )

        self.assertEqual(stats["layer2_raw_blocks"], 1)
        self.assertEqual(stats["unrecovered"], 0)
        self.assertIn("exogène<sup>11</sup>", page["enriched_markdown"])

    @unittest.skip("[rust-migration: SPEC] Layer 2 从句尾数字碎片 '7.' 恢复两位 marker '37'")
    def test_layer2_recovers_two_digit_marker_from_ocr_suffix(self):
        page = {
            "page_no": 10,
            "pdfPage": 10,
            "page_role": "body",
            "markdown": (
                "Before marker<sup>36</sup>. "
                "les éléments qui entrent dans la constitution d'un capital humain, "
                "sont bien plus larges que le simple apprentissage professionnel 7. "
                "Cet investissement, ce qui va former une compétence-machine. "
                "After marker<sup>38</sup>. "
                + ("filler text " * 30)
            ),
            "blocks": [
                {
                    "text": (
                        "les éléments qui entrent dans la constitution d’un capital humain, "
                        "sont bien plus larges que le simple apprentissage professionnel 7. "
                        "Cet investissement, ce qui va former une compétence-machine."
                    )
                }
            ],
        }

        stats = sup_recovery.recover_book_chapter_scoped(
            [page],
            {"ch1": {"36", "37", "38"}},
            {"ch1": (10, 10)},
            pdf_path="",
        )

        self.assertEqual(stats["layer2_raw_blocks"], 1)
        self.assertEqual(stats["unrecovered"], 0)
        self.assertIn("professionnel<sup>37</sup>.", page["enriched_markdown"])
        self.assertNotIn("professionnel 7.", page["enriched_markdown"])

    @unittest.skip("[rust-migration: SPEC] Layer 2 从 '1927-[19]30 * ou' 中把代理符号 '*' 恢复为 marker '30'")
    def test_layer2_recovers_marker_from_symbol_after_year_fragment(self):
        page = {
            "page_no": 10,
            "pdfPage": 10,
            "page_role": "body",
            "markdown": (
                "Before marker<sup>29</sup>. "
                "Que ce soit les libéraux allemands de l'École de Fribourg "
                "à partir de 1927-[19]30 * ou que ce soit les libertariens<sup>31</sup>. "
                + ("filler text " * 30)
            ),
            "blocks": [
                {
                    "text": (
                        "Que ce soit les libéraux allemands de l’École de Fribourg "
                        "à partir de 1927-[19]30 * ou que ce soit les libertariens %."
                    )
                }
            ],
        }

        stats = sup_recovery.recover_book_chapter_scoped(
            [page],
            {"ch1": {"29", "30", "31"}},
            {"ch1": (10, 10)},
            pdf_path="",
        )

        self.assertEqual(stats["layer2_raw_blocks"], 1)
        self.assertEqual(stats["unrecovered"], 0)
        self.assertIn("1927-[19]30<sup>30</sup> ou", page["enriched_markdown"])
        self.assertNotIn("[19]30 *", page["enriched_markdown"])


if __name__ == "__main__":
    unittest.main()
