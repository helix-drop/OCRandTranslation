//! 导出辅助函数单元测试（仅保留仍存在于 export/ 模块的函数）。

use std::collections::HashMap;

use fnm_core::records::ExportChapterRecord;

use super::contract::{compute_export_semantic_contract, is_semantic_duplicate_candidate};
use super::markdown_clean::normalize_markdown_content;
use super::paragraph_key::normalized_paragraph_key;

// ── paragraph_key ───────────────────────────────────────────────

#[test]
fn test_normalized_paragraph_key_strips_footnote_refs() {
    let result = normalized_paragraph_key("Some text [^1] with ref [^42].");
    assert_eq!(result, "some text with ref .");
}

#[test]
fn test_normalized_paragraph_key_compresses_whitespace() {
    let result = normalized_paragraph_key("  Hello   World  ");
    assert_eq!(result, "hello world");
}

#[test]
fn test_normalized_paragraph_key_empty() {
    assert_eq!(normalized_paragraph_key(""), "");
    assert_eq!(normalized_paragraph_key("  "), "");
}

// ── markdown_clean ──────────────────────────────────────────────

#[test]
fn test_normalize_markdown_content_empty() {
    assert_eq!(normalize_markdown_content(""), "");
    assert_eq!(normalize_markdown_content("  "), "");
    assert_eq!(normalize_markdown_content("\n  \n"), "");
}

#[test]
fn test_normalize_markdown_content_adds_newline() {
    assert_eq!(normalize_markdown_content("text"), "text\n");
    assert_eq!(normalize_markdown_content("  text  "), "text\n");
}

// ── contract: is_semantic_duplicate_candidate ───────────────────

#[test]
fn test_is_semantic_duplicate_candidate_empty_false() {
    assert!(!is_semantic_duplicate_candidate(""));
}

#[test]
fn test_is_semantic_duplicate_candidate_heading_false() {
    assert!(!is_semantic_duplicate_candidate("### Introduction"));
}

#[test]
fn test_is_semantic_duplicate_candidate_short_text_false() {
    assert!(!is_semantic_duplicate_candidate("Short text."));
}

#[test]
fn test_is_semantic_duplicate_candidate_long_with_punct_true() {
    let text = "This is a sufficiently long paragraph with proper punctuation. It has enough words and ends with a period to qualify as a duplicate candidate.";
    assert!(is_semantic_duplicate_candidate(text));
}

#[test]
fn test_is_semantic_duplicate_candidate_long_no_punct_false() {
    let text = "This is a paragraph that is long but has no actual sentence ending punctuation so it should not be a candidate";
    assert!(!is_semantic_duplicate_candidate(text));
}

// ── contract: compute_export_semantic_contract ──────────────────

#[test]
fn test_compute_export_semantic_contract_clean() {
    let chapter = ExportChapterRecord {
        section_id: "ch1".into(),
        title: "Chapter 1".into(),
        ..Default::default()
    };
    let mut files = HashMap::new();
    files.insert("001-test.md".into(), "Some body text.".into());
    let result = compute_export_semantic_contract(&[chapter], &files);
    assert!(result.get("export_semantic_contract_ok") == Some(&true));
    assert!(result.get("front_matter_leak_detected") == Some(&false));
    assert!(result.get("toc_residue_detected") == Some(&false));
}
