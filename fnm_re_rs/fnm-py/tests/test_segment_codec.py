"""M2.B1: segment_codec — serialize/deserialize_segments round-trip."""

import json

import fnm_re_rs


def test_serialize_segments_basic():
    segments = [
        {
            "page_no": 1,
            "paragraphs": [
                {
                    "order": 1, "kind": "body", "heading_level": 0,
                    "source_text": "hello world", "display_text": "hello world",
                    "consumed_by_prev": False,
                }
            ],
        }
    ]
    result = json.loads(fnm_re_rs.serialize_segments_json(json.dumps(segments)))
    assert len(result) == 1
    assert result[0]["p"] == 1
    assert "ps" in result[0]
    assert result[0]["ps"][0]["s"] == "hello world"


def test_deserialize_segments_basic():
    compressed = [
        {"p": 1, "ps": [{"o": 1, "k": "body", "s": "hello world"}]}
    ]
    result = json.loads(fnm_re_rs.deserialize_segments_to_dicts_json(json.dumps(compressed)))
    assert len(result) == 1
    assert result[0]["page_no"] == 1
    assert result[0]["paragraph_count"] == 1
    assert result[0]["source_text"] == "hello world"


def test_roundtrip():
    original = [
        {
            "page_no": 5,
            "paragraphs": [
                {
                    "order": 1, "kind": "heading", "heading_level": 2,
                    "source_text": "Title", "display_text": "Title",
                    "consumed_by_prev": False,
                }
            ],
        }
    ]
    compressed = json.loads(fnm_re_rs.serialize_segments_json(json.dumps(original)))
    restored = json.loads(fnm_re_rs.deserialize_segments_to_dicts_json(json.dumps(compressed)))
    assert restored[0]["page_no"] == original[0]["page_no"]
    assert restored[0]["paragraphs"][0]["kind"] == original[0]["paragraphs"][0]["kind"]
    assert restored[0]["paragraphs"][0]["source_text"] == original[0]["paragraphs"][0]["source_text"]


def test_empty_input():
    result = json.loads(fnm_re_rs.serialize_segments_json(json.dumps([])))
    assert result == []

    result2 = json.loads(fnm_re_rs.deserialize_segments_to_dicts_json(json.dumps([])))
    assert result2 == []


def test_old_format_compat():
    old_format = [
        {
            "page_no": 3, "paragraph_count": 1,
            "source_text": "old text", "display_text": "old text",
            "paragraphs": [
                {"order": 1, "source_text": "old text", "display_text": "old text"}
            ],
        }
    ]
    result = json.loads(fnm_re_rs.deserialize_segments_to_dicts_json(json.dumps(old_format)))
    assert result[0]["page_no"] == 3
    assert result[0]["source_text"] == "old text"
