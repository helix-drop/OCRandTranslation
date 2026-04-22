#!/usr/bin/env python3
"""test_example 样本清单测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from example_manifest import load_example_manifest, select_example_books


class ExampleManifestTest(unittest.TestCase):
    def _write_manifest(self, root: Path) -> Path:
        path = root / "example_manifest.json"
        payload = {
            "books": [
                {
                    "slug": "BookA",
                    "folder": "FolderA",
                    "group": "baseline",
                    "doc_name": "a.pdf",
                    "source_pdf_path": "/tmp/a.pdf",
                    "doc_id": "aaa111",
                    "include_in_default_batch": True,
                    "expected_page_count": 10,
                },
                {
                    "slug": "BookB",
                    "folder": "FolderB",
                    "group": "extension",
                    "doc_name": "b.pdf",
                    "source_pdf_path": "/tmp/b.pdf",
                    "doc_id": "bbb222",
                    "include_in_default_batch": True,
                    "expected_page_count": 20,
                },
                {
                    "slug": "BookC",
                    "folder": "FolderC",
                    "group": "extension",
                    "doc_name": "c.pdf",
                    "source_pdf_path": "/tmp/c.pdf",
                    "doc_id": "ccc333",
                    "include_in_default_batch": False,
                    "expected_page_count": 30,
                },
            ]
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_load_example_manifest_returns_dataclasses(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_manifest(Path(tmp_dir))
            books = load_example_manifest(path)
            self.assertEqual([book.slug for book in books], ["BookA", "BookB", "BookC"])
            self.assertEqual(books[1].group, "extension")
            self.assertEqual(books[2].expected_page_count, 30)

    def test_select_example_books_defaults_to_default_batch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_manifest(Path(tmp_dir))
            books = select_example_books(manifest_path=path)
            self.assertEqual([book.slug for book in books], ["BookA", "BookB"])

    def test_select_example_books_supports_group_and_slug(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_manifest(Path(tmp_dir))
            ext_books = select_example_books(manifest_path=path, group="extension", include_all=True)
            self.assertEqual([book.slug for book in ext_books], ["BookB", "BookC"])

            one_book = select_example_books(manifest_path=path, slug="BookC", include_all=True)
            self.assertEqual([book.slug for book in one_book], ["BookC"])


if __name__ == "__main__":
    unittest.main()
