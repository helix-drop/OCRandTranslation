//! ←→ FNM_RE/stages/export_contract.py
//! 保留函数：
//!   is_semantic_duplicate_candidate   ←→ _is_semantic_duplicate_candidate (export_contract.py:39)
//!   compute_export_semantic_contract  ←→ _compute_export_semantic_contract (export_contract.py:53)
//!
//! 已移除：build_export_chapters（搬至 fnm-phase5/render/merge.rs）
//!          looks_like_bibliography_entry → 内联至 compute_export_semantic_contract

use std::collections::{HashMap, HashSet};

use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::export_constants::{FRONT_MATTER_TITLE_RE, TOC_RESIDUE_RE};
use fnm_core::records::ExportChapterRecord;

static DUPLICATE_CANDIDATE_PUNCT_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"[.!?;:。！？；：]").unwrap());
static BIB_YEAR_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b\d{4}\.?\s*$").unwrap());
static BIB_COLON_YEAR_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r":\s*[^:]{6,},\s*\d{4}\.?\s*$").unwrap());
static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

pub fn is_semantic_duplicate_candidate(text: &str) -> bool {
    let normalized = WHITESPACE_RE.replace_all(text.trim(), " ");
    let normalized = normalized.trim();
    if normalized.is_empty() {
        return false;
    }
    if normalized.starts_with('#') {
        return false;
    }
    if normalized.len() < 80 {
        return false;
    }
    let words: Vec<&str> = normalized.split(' ').filter(|w| !w.is_empty()).collect();
    if words.len() < 12 {
        return false;
    }
    DUPLICATE_CANDIDATE_PUNCT_RE.is_match(normalized)
}

fn looks_like_bibliography_entry(text: &str) -> bool {
    let normalized = WHITESPACE_RE.replace_all(text.trim(), " ");
    let normalized = normalized.trim();
    if normalized.is_empty() {
        return false;
    }
    if !BIB_YEAR_RE.is_match(normalized) {
        return false;
    }
    BIB_COLON_YEAR_RE.is_match(normalized)
}

pub fn compute_export_semantic_contract(
    chapters: &[ExportChapterRecord],
    chapter_files: &HashMap<String, String>,
) -> HashMap<String, bool> {
    let front_matter_leak_detected = chapters
        .iter()
        .any(|ch| FRONT_MATTER_TITLE_RE.is_match(ch.title.trim()));
    let toc_residue_detected = chapter_files
        .values()
        .any(|content| TOC_RESIDUE_RE.is_match(content));

    let mut mid_paragraph_heading_detected = false;
    for content in chapter_files.values() {
        let lines: Vec<&str> = content.lines().collect();
        for (idx, line) in lines.iter().enumerate() {
            let stripped = line.trim();
            if !stripped.starts_with("### ") {
                continue;
            }
            let prev = if idx > 0 { lines[idx - 1].trim() } else { "" };
            if !prev.is_empty() && !prev.starts_with('#') {
                mid_paragraph_heading_detected = true;
                break;
            }
        }
        if mid_paragraph_heading_detected {
            break;
        }
    }

    let mut duplicate_paragraph_detected = false;
    for content in chapter_files.values() {
        let mut seen: HashSet<String> = HashSet::new();
        for paragraph in content.split("\n\n") {
            if !is_semantic_duplicate_candidate(paragraph) {
                continue;
            }
            if looks_like_bibliography_entry(paragraph) {
                continue;
            }
            let key = super::paragraph_key::normalized_paragraph_key(paragraph);
            if key.len() < 60 {
                continue;
            }
            if seen.contains(&key) {
                duplicate_paragraph_detected = true;
                break;
            }
            seen.insert(key);
        }
        if duplicate_paragraph_detected {
            break;
        }
    }

    let export_semantic_contract_ok = !(front_matter_leak_detected
        || toc_residue_detected
        || mid_paragraph_heading_detected
        || duplicate_paragraph_detected);

    let mut result = HashMap::new();
    result.insert(
        "export_semantic_contract_ok".to_string(),
        export_semantic_contract_ok,
    );
    result.insert(
        "front_matter_leak_detected".to_string(),
        front_matter_leak_detected,
    );
    result.insert("toc_residue_detected".to_string(), toc_residue_detected);
    result.insert(
        "mid_paragraph_heading_detected".to_string(),
        mid_paragraph_heading_detected,
    );
    result.insert(
        "duplicate_paragraph_detected".to_string(),
        duplicate_paragraph_detected,
    );
    result
}
