from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path("/Users/hao/OCRandTranslation")
TEST_EXAMPLE_DIR = REPO_ROOT / "test_example"
_SAMPLE_DOC_IDS = {
    "Biopolitics": "0d285c0800db",
    "Germany_Madness": "67356d1f7d9a",
    "Heidegger_en_France": "a5d9a08d6871",
    "Mad_Act": "bd05138cd773",
    "Napoleon": "5df1d3d7f9c1",
    "Neuropsychoanalysis_in_Practice": "e7f8a1b6c2d3",
    "Neuropsychoanalysis_Introduction": "a3c9e1f7b284",
}


def load_pages(doc_dir: str) -> list[dict]:
    raw_path = TEST_EXAMPLE_DIR / doc_dir / "raw_pages.json"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    return list(payload.get("pages") or [])


def _load_doc_auto_visual_toc_bundle(doc_id: str) -> dict:
    toc_path = REPO_ROOT / "local_data" / "user_data" / "data" / "documents" / doc_id / "auto_visual_toc_bundle.json"
    if not toc_path.exists():
        return {}
    payload = json.loads(toc_path.read_text(encoding="utf-8"))
    return dict(payload or {}) if isinstance(payload, dict) else {}


def load_auto_visual_toc(doc_dir: str) -> list[dict]:
    toc_path = TEST_EXAMPLE_DIR / doc_dir / "auto_visual_toc.json"
    if not toc_path.exists():
        doc_id = _SAMPLE_DOC_IDS.get(doc_dir)
        if doc_id:
            bundle = _load_doc_auto_visual_toc_bundle(doc_id)
            return list(bundle.get("items") or []) if isinstance(bundle, dict) else []
        return []
    payload = json.loads(toc_path.read_text(encoding="utf-8"))
    return list(payload.get("items") or [])

