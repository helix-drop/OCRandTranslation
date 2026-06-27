"""M2.A2: page_translate unit-listing 系列 — 6 个函数."""

import json

import fnm_re_rs
import pytest

SAMPLE_UNIT = {
    "unit_id": "test-unit-001",
    "kind": "body",
    "section_title": "第1章 测试",
    "page_segments": [
        {"page_no": 10},
        {"page_no": 12},
    ],
    "page_start": 10,
    "page_end": 12,
}


def test_format_fnm_unit_label():
    """format_fnm_unit_label 返回格式化标签."""
    label = fnm_re_rs.format_fnm_unit_label_json(json.dumps(SAMPLE_UNIT))
    assert "正文" in label
    assert "第1章" in label


def test_format_fnm_unit_label_empty_section():
    """无 section_title 时不包含 section."""
    unit = dict(SAMPLE_UNIT)
    unit["section_title"] = ""
    label = fnm_re_rs.format_fnm_unit_label_json(json.dumps(unit))
    assert "正文" in label
    assert "第1章" not in label


def test_format_fnm_unit_pages():
    """format_fnm_unit_pages 返回页码范围."""
    pages = fnm_re_rs.format_fnm_unit_pages_json(json.dumps(SAMPLE_UNIT))
    assert pages == "10-12"


def test_format_fnm_unit_pages_single():
    """单页时返回单数字."""
    unit = dict(SAMPLE_UNIT)
    unit["page_segments"] = [{"page_no": 10}]
    pages = fnm_re_rs.format_fnm_unit_pages_json(json.dumps(unit))
    assert pages == "10"


def test_collect_failed_locations_empty():
    """无失败段落返回空列表."""
    unit = {
        "unit_id": "test-unit",
        "page_segments": [
            {
                "page_no": 10,
                "paragraphs": [
                    {"source_text": "OK", "translation_status": "done", "consumed_by_prev": False},
                ],
            },
        ],
    }
    result = json.loads(fnm_re_rs.collect_fnm_unit_failed_locations_json(json.dumps(unit)))
    assert result == []


def test_collect_failed_locations_has_errors():
    """有 error 段落时返回失败位置."""
    unit = {
        "unit_id": "test-unit",
        "section_title": "第1章",
        "page_segments": [
            {
                "page_no": 10,
                "paragraphs": [
                    {"source_text": "失败", "translation_status": "error", "last_error": "API错误", "consumed_by_prev": False},
                    {"source_text": "OK", "translation_status": "done", "consumed_by_prev": False},
                ],
            },
        ],
    }
    result = json.loads(fnm_re_rs.collect_fnm_unit_failed_locations_json(json.dumps(unit)))
    assert len(result) == 1
    assert result[0]["status"] == "error"
    assert result[0]["para_idx"] == 0
