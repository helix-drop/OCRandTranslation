"""M2.A1: page_translate body-unit 系列 — build_fnm_body_unit_jobs / apply_body_unit_translations / apply_body_unit_entry_result."""

import json

import fnm_re_rs
import pytest


SAMPLE_UNIT = {
    "unit_id": "test-body-001",
    "kind": "body",
    "section_title": "第1章 测试",
    "page_segments": [
        {
            "page_no": 10,
            "paragraphs": [
                {
                    "source_text": "这是第一段正文。",
                    "heading_level": 0,
                    "consumed_by_prev": False,
                },
                {
                    "source_text": "这是第二段正文。",
                    "heading_level": 0,
                    "consumed_by_prev": False,
                },
            ],
        },
        {
            "page_no": 11,
            "paragraphs": [
                {
                    "source_text": "这是第三段正文。",
                    "heading_level": 0,
                    "consumed_by_prev": False,
                },
            ],
        },
    ],
}

SAMPLE_PAGES = [
    {"bookPage": 10, "print_page_label": "10"},
    {"bookPage": 11, "print_page_label": "11"},
]


def test_build_fnm_body_unit_jobs_basic():
    """基本 body unit → 生成 3 个 paragraph job."""
    unit_json = json.dumps(SAMPLE_UNIT)
    pages_json = json.dumps(SAMPLE_PAGES)
    result = json.loads(fnm_re_rs.build_fnm_body_unit_jobs_json(unit_json, pages_json))
    assert isinstance(result, list)
    assert len(result) == 3
    for job in result:
        assert job["content_role"] == "body"
        assert job["para_total"] == 3
        assert isinstance(job["para_idx"], int)
        assert job["text"]


def test_build_fnm_body_unit_jobs_empty_segments():
    """无 page_segments 返回空列表."""
    unit = dict(SAMPLE_UNIT)
    unit["page_segments"] = []
    result = json.loads(fnm_re_rs.build_fnm_body_unit_jobs_json(
        json.dumps(unit), json.dumps(SAMPLE_PAGES),
    ))
    assert result == []


def test_apply_body_unit_translations_basic():
    """译文注入后返回更新后的 segments."""
    translated = ["译文一", "译文二", "译文三"]
    result = json.loads(fnm_re_rs.apply_body_unit_translations_json(
        json.dumps(SAMPLE_UNIT), json.dumps(translated),
    ))
    assert "page_segments" in result
    assert result["translated_text"] == "译文一\n\n译文二\n\n译文三"


def test_apply_body_unit_translations_mismatch():
    """译文数不匹配时返回 error."""
    translated = ["译文一"]
    result = json.loads(fnm_re_rs.apply_body_unit_translations_json(
        json.dumps(SAMPLE_UNIT), json.dumps(translated),
    ))
    assert "error" in result


def test_apply_body_unit_entry_result_basic():
    """流式结果合并后更新段落状态."""
    entry = {
        "_page_entries": [
            {"translation": "译文A", "_status": "done", "_error": ""},
            {"translation": "译文B", "_status": "done", "_error": ""},
            {"translation": "", "_status": "error", "_error": "API超时"},
        ],
    }
    result = json.loads(fnm_re_rs.apply_body_unit_entry_result_json(
        json.dumps(SAMPLE_UNIT), json.dumps(entry), False,
    ))
    assert "failed_locations" in result
    assert len(result["failed_locations"]) == 1  # 第三段失败
    assert result["failed_locations"][0]["status"] == "error"


def test_apply_body_unit_entry_result_apply_only_unresolved():
    """apply_only_unresolved=True 时只覆盖 error 状态的段落."""
    unit_with_status = dict(SAMPLE_UNIT)
    unit_with_status["page_segments"] = [
        {
            "page_no": 10,
            "paragraphs": [
                {
                    "source_text": "已有译文",
                    "translation_status": "done",
                    "translated_text": "原有译文",
                    "consumed_by_prev": False,
                },
                {
                    "source_text": "失败段落",
                    "translation_status": "error",
                    "last_error": "之前的错误",
                    "consumed_by_prev": False,
                },
            ],
        },
    ]
    entry = {
        "_page_entries": [
            {"translation": "新译文", "_status": "done", "_error": ""},
            {"translation": "修复译文", "_status": "done", "_error": ""},
        ],
    }
    result = json.loads(fnm_re_rs.apply_body_unit_entry_result_json(
        json.dumps(unit_with_status), json.dumps(entry), True,
    ))
    segs = result["page_segments"]
    # 第一段状态 done 且 apply_only_unresolved=True → 不覆盖
    assert segs[0]["paragraphs"][0]["translation_status"] == "done"
    assert segs[0]["paragraphs"][0]["translated_text"] == "原有译文"
