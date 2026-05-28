//! 测试模块。

use crate::page_translate::apply::{apply_body_unit_entry_result, apply_body_unit_translations};
use crate::page_translate::format::{
    format_unit_label_value, format_unit_pages_value, preview_text, unit_page_numbers,
    unit_page_numbers_value,
};
use crate::page_translate::jobs_builder::build_fnm_body_unit_jobs;
use crate::page_translate::retry::collect_unit_failed_locations_value;
use fnm_core::records::TranslationUnitRecord;
use serde_json::json;

#[test]
fn test_preview_text_cjk_truncation() {
    let long_cjk: String = "好".repeat(121);
    let preview = preview_text(&long_cjk);
    assert_eq!(preview.chars().count(), 120);
}

#[test]
fn test_preview_text_short() {
    assert_eq!(preview_text("hello"), "hello");
    assert_eq!(preview_text(""), "");
}

#[test]
fn test_unit_page_numbers() {
    let unit = TranslationUnitRecord {
        page_start: 3,
        page_end: 5,
        ..Default::default()
    };
    assert_eq!(unit_page_numbers(&unit), vec![3, 4, 5]);
}

#[test]
fn test_unit_page_numbers_from_segments() {
    let unit = TranslationUnitRecord {
        page_segments: vec![
            fnm_core::records::UnitPageSegmentRecord {
                page_no: 10,
                ..Default::default()
            },
            fnm_core::records::UnitPageSegmentRecord {
                page_no: 8,
                ..Default::default()
            },
        ],
        ..Default::default()
    };
    let pages = unit_page_numbers(&unit);
    assert_eq!(pages, vec![8, 10]);
}

#[test]
fn test_format_unit_label_body() {
    let unit = json!({
        "kind": "body",
        "section_title": "Leçon 1",
        "page_segments": [{"page_no": 10}]
    });
    let label = format_unit_label_value(&unit);
    assert!(label.contains("正文"));
    assert!(label.contains("Leçon 1"));
    assert!(label.contains("10"));
}

#[test]
fn test_format_unit_label_footnote() {
    let unit = json!({
        "kind": "footnote",
        "page_start": 5,
        "page_end": 5
    });
    let label = format_unit_label_value(&unit);
    assert!(label.contains("脚注"));
    assert!(label.contains("5"));
}

#[test]
fn test_format_unit_label_empty_kind() {
    let unit = json!({"page_start": 1, "page_end": 1});
    let label = format_unit_label_value(&unit);
    assert!(label.contains("unit"));
}

#[test]
fn test_format_unit_pages_empty() {
    let unit = json!({});
    assert_eq!(format_unit_pages_value(&unit), "-");
}

#[test]
fn test_format_unit_pages_single() {
    let unit = json!({"page_segments": [{"page_no": 42}]});
    assert_eq!(format_unit_pages_value(&unit), "42");
}

#[test]
fn test_format_unit_pages_range() {
    let unit = json!({
        "page_segments": [{"page_no": 3}, {"page_no": 7}]
    });
    assert_eq!(format_unit_pages_value(&unit), "3-7");
}

#[test]
fn test_unit_page_numbers_value_empty() {
    let unit = json!({});
    let pages = unit_page_numbers_value(&unit);
    assert!(pages.is_empty());
}

#[test]
fn test_unit_page_numbers_value_segments() {
    let unit = json!({"page_segments": [{"page_no": 5}, {"page_no": 3}]});
    let pages = unit_page_numbers_value(&unit);
    assert_eq!(pages, vec![3, 5]);
}

#[test]
fn test_collect_unit_failed_locations_empty() {
    let unit = json!({
        "page_segments": [{
            "page_no": 1,
            "paragraphs": [{"visible_idx": 0, "source_text": "hello", "translation_status": "done"}]
        }]
    });
    let failed = collect_unit_failed_locations_value(&unit);
    assert!(failed.is_empty());
}

#[test]
fn test_collect_unit_failed_locations_with_error() {
    let unit = json!({
        "section_title": "Ch1",
        "page_segments": [{
            "page_no": 1,
            "paragraphs": [{
                "visible_idx": 0,
                "source_text": "hello",
                "translation_status": "error"
            }]
        }]
    });
    let failed = collect_unit_failed_locations_value(&unit);
    assert_eq!(failed.len(), 1);
    assert_eq!(failed[0]["page_no"], 1);
}

#[test]
fn test_build_fnm_body_unit_jobs_basic() {
    let unit = json!({
        "kind": "body",
        "page_segments": [{
            "page_no": 10,
            "paragraphs": [{
                "source_text": "Bonjour le monde.",
                "section_path": []
            }]
        }]
    });
    let pages = vec![json!({"bookPage": 10, "markdown": "Bonjour le monde."})];
    let result = build_fnm_body_unit_jobs(&unit, &pages);
    let jobs = result.as_array().unwrap();
    assert!(!jobs.is_empty());
    assert!(jobs[0]["text"].as_str().unwrap().contains("Bonjour"));
}

#[test]
fn test_apply_body_unit_translations_mismatch() {
    let unit = json!({
        "page_segments": [{
            "page_no": 1,
            "paragraphs": [{"source_text": "A", "section_path": []}]
        }]
    });
    let result = apply_body_unit_translations(&unit, &[json!("T1"), json!("T2")]);
    assert!(result.is_err());
}

#[test]
fn test_apply_body_unit_entry_result_basic() {
    let unit = json!({
        "page_segments": [{
            "page_no": 1,
            "paragraphs": [{
                "source_text": "Bonjour.",
                "section_path": [],
                "translation_status": ""
            }]
        }]
    });
    let entry = json!({
        "_page_entries": [{"translation": "Hello.", "_status": "done"}]
    });
    let result = apply_body_unit_entry_result(&unit, &entry, false);
    assert!(result.get("error").is_none());
    let segs = result["page_segments"].as_array().unwrap();
    let paras = segs[0]["paragraphs"].as_array().unwrap();
    assert_eq!(paras[0]["translated_text"].as_str().unwrap(), "Hello.");
}
