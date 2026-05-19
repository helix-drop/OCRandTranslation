//! ←→ FNM_RE/modules/book_assemble.py
//! 翻译的函数：
//!   is_adjacent_duplicate_candidate          ←→ _is_adjacent_duplicate_candidate (book_assemble.py:203)
//!   canonicalize_adjacent_duplicate_paragraphs ←→ _canonicalize_adjacent_duplicate_paragraphs (book_assemble.py:214)
//!   apply_semantic_canonicalization          ←→ _apply_semantic_canonicalization (book_assemble.py:342)

use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::Value;

use fnm_core::records::ChapterMarkdownEntry;

use super::garbled_repair::repair_garbled_markdown_blocks;
use crate::export::contract::{is_semantic_duplicate_candidate, looks_like_bibliography_entry};
use crate::export::paragraph_key::normalized_paragraph_key;
use crate::export_audit::helpers::split_body_and_definitions;

static IMAGE_ONLY_PARAGRAPH_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^\s*(?:!\[[^\]]*\]\([^)]+\)|<div[^>]*>\s*<img\b[^>]*>\s*</div>|<img\b[^>]*>)\s*$")
        .unwrap()
});

/// 匹配一个或多个空白行（含空格/制表符），用于段落分割。
/// ←→ Python `re.split(r"\n\s*\n+", body_text)`
static MULTI_BLANK_LINE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\n\s*\n+").unwrap());

/// 判断段落是否为相邻去重候选。
///
/// ←→ Python `_is_adjacent_duplicate_candidate()` (book_assemble.py:203)
pub fn is_adjacent_duplicate_candidate(paragraph: &str) -> bool {
    let normalized = paragraph.trim();
    if normalized.is_empty() {
        return false;
    }
    if IMAGE_ONLY_PARAGRAPH_RE.is_match(normalized) {
        return false;
    }
    // looks_like_bibliography_entry 在 contract.rs 中为私有，复制检查逻辑
    if looks_like_bibliography_entry(normalized) {
        return false;
    }
    is_semantic_duplicate_candidate(normalized)
}

/// 合并相邻语义重复段落。
///
/// ←→ Python `_canonicalize_adjacent_duplicate_paragraphs()` (book_assemble.py:214)
pub fn canonicalize_adjacent_duplicate_paragraphs(markdown_text: &str) -> (String, i64) {
    let raw = markdown_text;
    let (body_text, definition_text) = split_body_and_definitions(raw);

    let body_paragraphs: Vec<String> = MULTI_BLANK_LINE_RE
        .split(&body_text)
        .map(|chunk| chunk.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();

    if body_paragraphs.is_empty() {
        return (raw.to_string(), 0);
    }

    let mut kept: Vec<String> = Vec::new();
    let mut collapsed_count: i64 = 0;

    for paragraph in &body_paragraphs {
        let is_dup = kept.last().is_some_and(|last| {
            is_adjacent_duplicate_candidate(paragraph)
                && is_adjacent_duplicate_candidate(last)
                && normalized_paragraph_key(paragraph) == normalized_paragraph_key(last)
        });
        if is_dup {
            collapsed_count += 1;
            continue;
        }
        kept.push(paragraph.clone());
    }

    if collapsed_count <= 0 {
        return (raw.to_string(), 0);
    }

    let mut rebuilt_parts: Vec<String> = Vec::new();
    let rebuilt_body = kept.join("\n\n").trim().to_string();
    if !rebuilt_body.is_empty() {
        rebuilt_parts.push(rebuilt_body);
    }
    let def_block = definition_text.trim().to_string();
    if !def_block.is_empty() {
        rebuilt_parts.push(def_block);
    }
    let canonicalized = rebuilt_parts.join("\n\n").trim().to_string();
    let canonicalized = if canonicalized.is_empty() {
        canonicalized
    } else {
        format!("{}\n", canonicalized)
    };
    (canonicalized, collapsed_count)
}

/// 对所有章节执行乱码修复 + 去重。
///
/// ←→ Python `_apply_semantic_canonicalization()` (book_assemble.py:342)
pub fn apply_semantic_canonicalization(
    ordered_chapters: &[ChapterMarkdownEntry],
) -> (Vec<ChapterMarkdownEntry>, Value) {
    let mut normalized: Vec<ChapterMarkdownEntry> = Vec::new();
    let mut affected_files: Vec<String> = Vec::new();
    let mut collapsed_total: i64 = 0;
    let mut garbled_repair_total: i64 = 0;
    let mut garbled_repair_files: Vec<String> = Vec::new();
    let mut garbled_method_counts: std::collections::HashMap<String, i64> =
        std::collections::HashMap::new();

    for chapter in ordered_chapters {
        let (repaired_markdown, repair_summary) =
            repair_garbled_markdown_blocks(&chapter.markdown_text);
        let (canonical_markdown, collapsed_count) =
            canonicalize_adjacent_duplicate_paragraphs(&repaired_markdown);

        collapsed_total += collapsed_count;
        let repaired_count = repair_summary["repaired_garbled_block_count"]
            .as_i64()
            .unwrap_or(0);
        garbled_repair_total += repaired_count;

        if repaired_count > 0 {
            let file_ref = if chapter.path.trim().is_empty() {
                chapter.chapter_id.clone()
            } else {
                chapter.path.clone()
            };
            garbled_repair_files.push(file_ref);
        }

        if let Some(method_counts) = repair_summary["garbled_repair_method_counts"].as_object() {
            for (method_name, count_val) in method_counts {
                let count = count_val.as_i64().unwrap_or(0);
                *garbled_method_counts
                    .entry(method_name.clone())
                    .or_insert(0) += count;
            }
        }

        if collapsed_count > 0 {
            let file_ref = if chapter.path.trim().is_empty() {
                chapter.chapter_id.clone()
            } else {
                chapter.path.clone()
            };
            affected_files.push(file_ref);
        }

        let chapter_markdown = if repaired_count > 0 || collapsed_count > 0 {
            canonical_markdown
        } else {
            chapter.markdown_text.clone()
        };

        normalized.push(ChapterMarkdownEntry {
            order: chapter.order,
            chapter_id: chapter.chapter_id.clone(),
            title: chapter.title.clone(),
            path: chapter.path.clone(),
            markdown_text: chapter_markdown,
            start_page: chapter.start_page,
            end_page: chapter.end_page,
            pages: chapter.pages.clone(),
        });
    }

    let mut sorted_methods: Vec<String> = garbled_method_counts.keys().cloned().collect();
    sorted_methods.sort();

    let summary = serde_json::json!({
        "canonicalization_applied": collapsed_total > 0,
        "collapsed_duplicate_paragraph_count": collapsed_total,
        "affected_file_count": affected_files.len(),
        "affected_files_preview": affected_files.iter().take(12).cloned().collect::<Vec<_>>(),
        "garbled_block_repair_applied": garbled_repair_total > 0,
        "repaired_garbled_block_count": garbled_repair_total,
        "garbled_repair_file_count": garbled_repair_files.len(),
        "garbled_repair_files_preview": garbled_repair_files.iter().take(12).cloned().collect::<Vec<_>>(),
        "garbled_repair_methods": sorted_methods,
        "garbled_repair_method_counts": garbled_method_counts,
    });

    (normalized, summary)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adjacent_duplicate_short_text() {
        assert!(!is_adjacent_duplicate_candidate("Short text"));
    }

    #[test]
    fn adjacent_duplicate_image_only() {
        assert!(!is_adjacent_duplicate_candidate("![alt](image.png)"));
    }

    #[test]
    fn adjacent_duplicate_long_enough() {
        let text = "This is a sufficiently long paragraph with multiple words and proper punctuation. It should be long enough to qualify as a duplicate candidate.";
        assert!(is_adjacent_duplicate_candidate(text));
    }

    #[test]
    fn canonicalize_no_change() {
        let text = "Paragraph one.\n\nParagraph two.\n\n[^1]: A note.";
        let (result, count) = canonicalize_adjacent_duplicate_paragraphs(text);
        assert_eq!(count, 0);
        assert_eq!(result, text);
    }

    #[test]
    fn canonicalize_removes_adjacent_duplicate() {
        let p = "This is a long paragraph that will be considered for deduplication. It has proper punctuation and enough length to be a valid duplicate candidate.";
        let text = format!("{}\n\n{}\n\n[^1]: Note.", p, p);
        let (_result, count) = canonicalize_adjacent_duplicate_paragraphs(&text);
        assert_eq!(count, 1);
    }

    #[test]
    fn apply_semantic_ok_noop() {
        let chapters = vec![ChapterMarkdownEntry {
            order: 1,
            chapter_id: "ch-1".into(),
            title: "Chapter 1".into(),
            path: "ch001.md".into(),
            markdown_text: "Normal text.\n\n[^1]: Note.".into(),
            start_page: 1,
            end_page: 5,
            pages: vec![1, 2, 3, 4, 5],
        }];
        let (result, summary) = apply_semantic_canonicalization(&chapters);
        assert_eq!(result.len(), 1);
        assert!(!summary["canonicalization_applied"].as_bool().unwrap());
        assert!(!summary["garbled_block_repair_applied"].as_bool().unwrap());
    }
}
