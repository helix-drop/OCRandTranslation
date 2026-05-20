"""M2.B3: export_audit helpers — body_paragraphs / definition_lines / split_body_and_definitions."""

import json

import fnm_re_rs


def test_body_paragraphs_basic():
    md = "Some body text.\n\nAnother paragraph."
    result = json.loads(fnm_re_rs.body_paragraphs_json(md))
    assert len(result) == 2
    assert "Some body text." in result[0]
    assert "Another paragraph." in result[1]


def test_body_paragraphs_empty():
    result = json.loads(fnm_re_rs.body_paragraphs_json(""))
    assert result == []


def test_body_paragraphs_skips_headings():
    md = "# Chapter Title\n\nBody text."
    result = json.loads(fnm_re_rs.body_paragraphs_json(md))
    assert len(result) == 1
    assert "Body text." in result[0]


def test_body_paragraphs_excludes_defs():
    md = "Body paragraph.\n\n[^1]: A definition."
    result = json.loads(fnm_re_rs.body_paragraphs_json(md))
    assert len(result) == 1
    assert "Body paragraph" in result[0]


def test_definition_lines_basic():
    md = "Body.\n\n[^1]: First definition.\n\n[^2]: Second definition."
    result = json.loads(fnm_re_rs.definition_lines_json(md))
    assert len(result) == 2
    assert "[^1]: First definition." in result[0]
    assert "[^2]: Second definition." in result[1]


def test_definition_lines_empty():
    result = json.loads(fnm_re_rs.definition_lines_json("Body only.\n"))
    assert result == []


def test_split_body_and_definitions():
    md = "Body paragraph.\n\n[^1]: Note text."
    result = json.loads(fnm_re_rs.split_body_and_definitions_json(md))
    assert len(result) == 2
    assert "Body paragraph." in result[0]
    assert "[^1]: Note text." in result[1]


def test_split_no_notes():
    md = "Only body."
    result = json.loads(fnm_re_rs.split_body_and_definitions_json(md))
    assert "Only body." in result[0]
    assert result[1] == ""


def test_indented_definition():
    md = "Body.\n\n[^1]: Multi-line\n    continued.\n\n[^2]: Another."
    result = json.loads(fnm_re_rs.definition_lines_json(md))
    assert len(result) >= 2
    assert any("continued" in line for line in result)
