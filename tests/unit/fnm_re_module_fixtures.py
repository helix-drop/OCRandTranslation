from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path("/Users/hao/OCRandTranslation")
TEST_EXAMPLE_DIR = REPO_ROOT / "test_example"


def load_pages(doc_dir: str) -> list[dict]:
    raw_path = TEST_EXAMPLE_DIR / doc_dir / "raw_pages.json"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    return list(payload.get("pages") or [])


def load_auto_visual_toc(doc_dir: str) -> list[dict]:
    toc_path = TEST_EXAMPLE_DIR / doc_dir / "auto_visual_toc.json"
    if not toc_path.exists():
        return []
    payload = json.loads(toc_path.read_text(encoding="utf-8"))
    return list(payload.get("items") or [])

