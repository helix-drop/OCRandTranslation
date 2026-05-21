import json

import fnm_re_rs


def test_pipeline_biopolitics_12_chapters(biopolitics_db):
    loaded = json.loads(fnm_re_rs.load_doc_structure_json(biopolitics_db, "biopolitics-seed", False))
    chapters = loaded.get("chapters", [])
    assert len(chapters) == 12, f"expected 12 chapters, got {len(chapters)}"


def test_pipeline_chapters_have_titles(biopolitics_db):
    loaded = json.loads(fnm_re_rs.load_doc_structure_json(biopolitics_db, "biopolitics-seed", False))
    chapters = loaded.get("chapters", [])
    for ch in chapters:
        assert ch.get("title"), f"chapter {ch['chapter_id']} missing title"


def test_pipeline_phase2_note_regions_exist(biopolitics_db):
    loaded = json.loads(fnm_re_rs.load_doc_structure_json(biopolitics_db, "biopolitics-seed", False))
    regions = loaded.get("note_regions", [])
    assert len(regions) > 0, "expected at least one note region"


def test_pipeline_phase3_note_links_exist(biopolitics_db):
    loaded = json.loads(fnm_re_rs.load_doc_structure_json(biopolitics_db, "biopolitics-seed", False))
    links = loaded.get("effective_note_links", [])
    assert len(links) > 0, "expected at least one note link"
