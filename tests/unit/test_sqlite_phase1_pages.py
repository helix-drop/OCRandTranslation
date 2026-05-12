from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from FNM_RE.stages.page_partition import build_page_partitions
from persistence.sqlite_store import SQLiteRepository


class SQLitePhase1PageLoaderTest(unittest.TestCase):
    def test_phase1_loader_keeps_ocr_headings_without_full_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = SQLiteRepository(str(Path(tmpdir) / "phase1-pages.db"))
            doc_id = "phase1-doc"
            repo.upsert_document(doc_id, "Phase 1 loader", page_count=1, entry_count=1)
            repo.replace_pages(
                doc_id,
                [
                    {
                        "bookPage": 1,
                        "fileIdx": 0,
                        "imgW": 800,
                        "imgH": 1000,
                        "markdown": "Opening prose without markdown heading.",
                        "footnotes": "1. A page footnote.",
                        "textSource": "ocr",
                        "fnBlocks": [{"text": "1. A page footnote.", "bbox": [10, 900, 700, 960]}],
                        "prunedResult": {
                            "height": 1000,
                            "width": 800,
                            "parsing_res_list": [
                                {
                                    "block_label": "doc_title",
                                    "block_content": "Chapter One",
                                    "block_bbox": [80, 100, 600, 150],
                                    "block_order": 1,
                                },
                                {
                                    "block_label": "text",
                                    "block_content": "This heavy body OCR block is not needed by Phase 1.",
                                    "block_bbox": [80, 200, 600, 240],
                                    "block_order": 2,
                                },
                                {
                                    "block_label": "paragraph_title",
                                    "block_content": "A Section",
                                    "block_bbox": [80, 260, 600, 300],
                                    "block_order": 3,
                                },
                            ],
                        },
                    }
                ],
            )

            pages = repo.load_pages_phase1(doc_id)

            self.assertEqual(len(pages), 1)
            self.assertEqual(pages[0]["fnBlocks"][0]["text"], "1. A page footnote.")
            blocks = pages[0]["prunedResult"]["parsing_res_list"]
            self.assertEqual([block["block_label"] for block in blocks], ["doc_title", "paragraph_title"])

            _records, candidates, _file_idx_map = build_page_partitions(pages)
            self.assertTrue(
                any(
                    row.get("source") == "ocr_block" and row.get("text") == "Chapter One"
                    for row in candidates
                )
            )


if __name__ == "__main__":
    unittest.main()
