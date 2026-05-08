import unittest
from types import SimpleNamespace
from unittest.mock import patch

from FNM_RE.modules import sup_recovery


class SupRecoveryTest(unittest.TestCase):
    def test_layer3_cache_is_scoped_by_target_marker(self):
        sup_recovery._LAYER3_CACHE.clear()
        sup_recovery._LAYER3_CACHE[("vision", "/tmp/fake.pdf", 248)] = [
            {"marker": "38", "before": "migration", "after": "Parce"}
        ]
        calls = {"open": 0}
        original_open = sup_recovery._fitz.open
        try:
            def fake_open(*_args, **_kwargs):
                calls["open"] += 1
                raise RuntimeError("stop before real render")

            sup_recovery._fitz.open = fake_open
            self.assertIsNone(
                sup_recovery._vision_find_superscript("/tmp/fake.pdf", 248, 37)
            )
        finally:
            sup_recovery._fitz.open = original_open
            sup_recovery._LAYER3_CACHE.clear()

        self.assertEqual(calls["open"], 1)

    def test_layer3_vision_request_has_timeout(self):
        sup_recovery._LAYER3_CACHE.clear()
        captured: dict = {}
        init_captured: dict = {}

        class FakePix:
            def tobytes(self, _fmt):
                return b"image"

        class FakePage:
            rect = SimpleNamespace(x0=0, y0=0, x1=100, y1=100)

            def get_pixmap(self, **_kwargs):
                return FakePix()

        class FakeDoc:
            def __getitem__(self, _index):
                return FakePage()

            def close(self):
                pass

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

        original_open = sup_recovery._fitz.open
        try:
            sup_recovery._fitz.open = lambda *_args, **_kwargs: FakeDoc()
            with patch("persistence.storage.resolve_visual_model_spec", return_value=spec):
                with patch("openai.OpenAI", FakeOpenAI):
                    result = sup_recovery._vision_find_superscript(
                        "/tmp/fake.pdf", 248, 37
                    )
        finally:
            sup_recovery._fitz.open = original_open
            sup_recovery._LAYER3_CACHE.clear()

        self.assertEqual(result["marker"], "37")
        self.assertIn("timeout", init_captured)
        self.assertEqual(init_captured.get("max_retries"), 0)
        self.assertIn("timeout", captured)
        self.assertGreater(captured["timeout"], 0)

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
