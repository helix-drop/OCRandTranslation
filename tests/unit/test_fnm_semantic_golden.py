from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.fnm_semantic_golden import (
    attach_reference_page_evidence,
    build_manifest,
    compare_manifest_to_db,
    compare_paragraph_sequences,
    iter_manifest_chapters,
    parse_markdown_paragraphs,
    write_manifest,
)


def test_manifest_keeps_traceable_source_text_from_real_template(tmp_path: Path) -> None:
    template = tmp_path / "real_golden_template"
    template.mkdir()
    (template / "001-Chapter.md").write_text(
        "## Lecon ecole\n\nCorps cite[^1].\n\n## NOTES\n\n[^1]: Definition.",
        encoding="utf-8",
    )

    manifest = build_manifest("Book", template)

    assert manifest["source"]["dir"] == "real_golden_template"
    paragraph = manifest["chapters"][0]["paragraphs"][1]
    definition = manifest["chapters"][0]["paragraphs"][3]
    assert paragraph["refs"] == ["1"]
    assert paragraph["source_text"] == "Corps cite[^1]."
    assert paragraph["source_file"] == "001-Chapter.md"
    assert paragraph["paragraph_ordinal"] == 1
    assert definition["definitions"] == ["1"]
    assert definition["source_text"] == "[^1]: Definition."


def test_paragraph_comparison_accepts_accent_normalization() -> None:
    expected = parse_markdown_paragraphs("## LEÇON\n\nL'école est réglée.")
    actual = parse_markdown_paragraphs("## LECON\n\nL'ecole est reglee.")

    result = compare_paragraph_sequences(expected, actual)

    assert result["ok"] is True


def test_paragraph_comparison_rejects_text_or_order_difference() -> None:
    expected = parse_markdown_paragraphs("## Chapter\n\nFirst.\n\nSecond.")
    actual = parse_markdown_paragraphs("## Chapter\n\nSecond.\n\nFirst.")

    result = compare_paragraph_sequences(expected, actual)

    assert result["ok"] is False
    assert result["text_mismatches"]
    assert result["text_mismatches"][0]["expected_text"] == "First."
    assert result["text_mismatches"][0]["actual_text"] == "Second."


def test_ref_relocation_is_allowed_only_to_last_paragraph_on_same_page() -> None:
    expected = parse_markdown_paragraphs(
        "Alpha[^7].\n\nOmega.",
        page_numbers=[18, 18],
    )
    relocated = parse_markdown_paragraphs(
        "Alpha.\n\nOmega.[^7]",
        page_numbers=[18, 18],
    )
    wrong_page = parse_markdown_paragraphs(
        "Alpha.\n\nOmega.[^7]",
        page_numbers=[18, 19],
    )

    assert compare_paragraph_sequences(expected, relocated)["ok"] is True
    assert compare_paragraph_sequences(expected, wrong_page)["ok"] is False


def test_ref_relocation_without_page_evidence_is_not_allowed() -> None:
    expected = parse_markdown_paragraphs("Alpha[^7].\n\nOmega.")
    relocated = parse_markdown_paragraphs("Alpha.\n\nOmega.[^7]")

    result = compare_paragraph_sequences(expected, relocated)

    assert result["ok"] is False
    assert result["reference_mismatches"]


def test_raw_page_context_adds_traceable_reference_page_evidence() -> None:
    paragraphs = parse_markdown_paragraphs(
        "Long surrounding sentence that is uniquely visible in the source page before reference[^7] and continues after it."
    )
    raw_pages = [
        (
            18,
            "Long surrounding sentence that is uniquely visible in the source page before reference and continues after it.",
        )
    ]

    attach_reference_page_evidence(paragraphs, raw_pages)

    assert paragraphs[0]["ref_pages"] == [
        {"marker": "7", "page_no": 18, "method": "raw_pages_context_unique"}
    ]


def test_manifest_write_publishes_complete_jsonl_without_temp_residue(tmp_path: Path) -> None:
    template = tmp_path / "real_golden_template"
    template.mkdir()
    (template / "001-Chapter.md").write_text("## Chapter\n\nBody.", encoding="utf-8")
    output = tmp_path / "semantic_golden_v1.jsonl"

    write_manifest("Book", template, output)
    chapters = list(iter_manifest_chapters(output))

    assert len(chapters) == 1
    assert chapters[0][0]["paragraph_count"] == 2
    assert not output.with_suffix(".jsonl.tmp").exists()


def test_db_comparison_failure_keeps_expected_text_and_db_trace(tmp_path: Path) -> None:
    template = tmp_path / "real_golden_template"
    template.mkdir()
    (template / "001-Chapter.md").write_text("## Chapter\n\nExpected body.", encoding="utf-8")
    manifest = tmp_path / "semantic_golden_v1.jsonl"
    write_manifest("Book", template, manifest)
    db_path = tmp_path / "doc.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE fnm_export_chapters (
            section_id TEXT, order_idx INTEGER, title TEXT, path TEXT,
            content TEXT, start_page INTEGER, end_page INTEGER, pages_json TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO fnm_export_chapters VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("ch-1", 1, "Chapter", "chapters/001-Chapter.md", "## Chapter\n\nBroken body.", 4, 5, "[4,5]"),
    )
    connection.commit()
    connection.close()

    report = compare_manifest_to_db(manifest, db_path, "export")
    mismatch = report["chapters"][0]["text_mismatches"][0]

    assert report["ok"] is False
    assert mismatch["expected_text"] == "Expected body."
    assert mismatch["actual_text"] == "Broken body."
    assert mismatch["actual_trace"]["table"] == "fnm_export_chapters"
    assert mismatch["actual_trace"]["section_id"] == "ch-1"


def test_db_comparison_accepts_translation_placeholder_without_claiming_text_match(tmp_path: Path) -> None:
    template = tmp_path / "real_golden_template"
    template.mkdir()
    (template / "001-Chapter.md").write_text("## Chapter\n\nExpected body.", encoding="utf-8")
    manifest = tmp_path / "semantic_golden_v1.jsonl"
    write_manifest("Book", template, manifest)
    db_path = tmp_path / "doc.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE fnm_export_chapters (
            section_id TEXT, order_idx INTEGER, title TEXT, path TEXT,
            content TEXT, start_page INTEGER, end_page INTEGER, pages_json TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO fnm_export_chapters VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("ch-1", 1, "Chapter", "chapters/001-Chapter.md", "## Chapter\n\n[待翻译]", 4, 5, "[4,5]"),
    )
    connection.commit()
    connection.close()

    report = compare_manifest_to_db(manifest, db_path, "export")
    chapter = report["chapters"][0]

    assert report["ok"] is True
    assert chapter["ok"] is True
    assert chapter["comparison_status"] == "accepted_translation_placeholder"
    assert chapter["text_comparison_performed"] is False
    assert "text_mismatches" not in chapter


def test_db_comparison_accepts_placeholder_with_emitted_note_definitions(tmp_path: Path) -> None:
    template = tmp_path / "real_golden_template"
    template.mkdir()
    (template / "001-Chapter.md").write_text(
        "## Chapter\n\nExpected body[^1].\n\n## NOTES\n\n[^1]: Note.",
        encoding="utf-8",
    )
    manifest = tmp_path / "semantic_golden_v1.jsonl"
    write_manifest("Book", template, manifest)
    db_path = tmp_path / "doc.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE fnm_export_chapters (
            section_id TEXT, order_idx INTEGER, title TEXT, path TEXT,
            content TEXT, start_page INTEGER, end_page INTEGER, pages_json TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO fnm_export_chapters VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "ch-1",
            1,
            "Chapter",
            "chapters/001-Chapter.md",
            "## Chapter\n\n[待翻译]\n\n## NOTES\n\n[^1]: Note.",
            4,
            5,
            "[4,5]",
        ),
    )
    connection.commit()
    connection.close()

    report = compare_manifest_to_db(manifest, db_path, "export")

    assert report["ok"] is True
    assert report["chapters"][0]["comparison_status"] == "accepted_translation_placeholder"


def test_missing_chapter_does_not_steal_later_exact_title_match(tmp_path: Path) -> None:
    template = tmp_path / "real_golden_template"
    template.mkdir()
    (template / "001-LECON DU 21 MARS 1979.md").write_text(
        "## LECON DU 21 MARS 1979\n\nExpected.",
        encoding="utf-8",
    )
    (template / "002-LECON DU 28 MARS 1979.md").write_text(
        "## LECON DU 28 MARS 1979\n\nExpected.",
        encoding="utf-8",
    )
    manifest = tmp_path / "semantic_golden_v1.jsonl"
    write_manifest("Book", template, manifest)
    db_path = tmp_path / "doc.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE fnm_export_chapters (
            section_id TEXT, order_idx INTEGER, title TEXT, path TEXT,
            content TEXT, start_page INTEGER, end_page INTEGER, pages_json TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO fnm_export_chapters VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "ch-28",
            1,
            "LECON DU 28 MARS 1979",
            "chapters/LECON DU 28 MARS 1979.md",
            "## LECON DU 28 MARS 1979\n\n[待翻译]",
            1,
            1,
            "[1]",
        ),
    )
    connection.commit()
    connection.close()

    report = compare_manifest_to_db(manifest, db_path, "export")

    assert report["chapters"][0]["missing_actual_chapter"] is True
    assert report["chapters"][1]["actual_section_id"] == "ch-28"
