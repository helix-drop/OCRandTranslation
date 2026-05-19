//! ←→ FNM_RE/modules/book_assemble.py
//! 翻译的函数：
//!   has_book_level_raw_marker_leak  ←→ _has_book_level_raw_marker_leak (book_assemble.py:174)

use std::collections::HashSet;

use fnm_core::records::ExportAuditFileRecord;
use fnm_phase2::chapter_split::structure_model::BookStructureModel;

use crate::export_audit::helpers::{
    definition_has_raw_note_marker, iter_raw_note_marker_hits,
    iter_raw_superscript_note_marker_hits, split_body_and_definitions, LOCAL_DEF_RE, LOCAL_REF_RE,
};

/// 检测全书级的原始注释标记泄漏。
///
/// ←→ Python `_has_book_level_raw_marker_leak()` (book_assemble.py:174)
pub fn has_book_level_raw_marker_leak(
    chapter_files: &std::collections::HashMap<String, String>,
    book_structure_model: Option<&BookStructureModel>,
) -> bool {
    // 从 OCRProfile 收集已知可忽略的 marker
    let known_cleared: HashSet<String> = book_structure_model
        .and_then(|m| {
            if m.ocr_profile.placeholder {
                None
            } else {
                Some(m.ocr_profile.unrecovered_marker_ids.clone())
            }
        })
        .unwrap_or_default()
        .into_iter()
        .collect();

    for content in chapter_files.values() {
        let (body_text, definition_text) = split_body_and_definitions(content);

        // 收集已允许的 marker
        let mut allowed_markers: HashSet<String> = HashSet::new();

        for caps in LOCAL_REF_RE.captures_iter(&body_text) {
            if let Some(m) = caps.get(1) {
                allowed_markers.insert(m.as_str().to_string());
            }
        }
        for caps in LOCAL_DEF_RE.captures_iter(content) {
            if let Some(m) = caps.get(1) {
                allowed_markers.insert(m.as_str().to_string());
            }
        }

        allowed_markers.extend(known_cleared.iter().cloned());

        // Python: if not allowed_markers: continue —— 无已知标记时跳过该文件
        // （没有 [^N] 引用/定义的文件中，[N] 裸括号可能是列表编号/日期，不应视为泄漏）
        if allowed_markers.is_empty() {
            continue;
        }

        let allowed_ref: Option<&HashSet<String>> = Some(&allowed_markers);

        if !iter_raw_note_marker_hits(&body_text, allowed_ref).is_empty() {
            return true;
        }
        if !iter_raw_superscript_note_marker_hits(&body_text, allowed_ref).is_empty() {
            return true;
        }
        if definition_has_raw_note_marker(&definition_text, allowed_ref) {
            return true;
        }
    }

    false
}

/// 从审计报告中检查 raw_note_marker_leak 问题。
pub fn has_leak_issues_in_report(file_reports: &[ExportAuditFileRecord]) -> bool {
    file_reports.iter().any(|file_row| {
        file_row
            .issue_codes
            .iter()
            .any(|code| code == "raw_note_marker_leak" || code == "legacy_note_token_leak")
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_leak_empty_files() {
        let files = std::collections::HashMap::new();
        assert!(!has_book_level_raw_marker_leak(&files, None));
    }

    #[test]
    fn no_leak_clean_content() {
        let mut files = std::collections::HashMap::new();
        files.insert(
            "ch001.md".to_string(),
            "Clean body text with [^1] reference.\n\n[^1]: Clean definition.".to_string(),
        );
        assert!(!has_book_level_raw_marker_leak(&files, None));
    }

    #[test]
    fn no_leak_with_raw_bracket_no_allowed_markers() {
        let mut files = std::collections::HashMap::new();
        // 无 [^N] 引用/定义时，裸 [N] 可能是列表编号/日期，不检测泄漏
        files.insert(
            "ch001.md".to_string(),
            "Text with [1] raw marker but no footnote system.\n".to_string(),
        );
        assert!(!has_book_level_raw_marker_leak(&files, None));
    }

    #[test]
    fn leak_with_raw_bracket() {
        let mut files = std::collections::HashMap::new();
        // 有 [^1] 引用和定义，但正文中仍出现裸 [1]（同一标记数）——这是泄漏
        files.insert(
            "ch001.md".to_string(),
            "Text with [^1] reference and also [1] raw same marker.\n\n[^1]: Definition of note 1.\n".to_string(),
        );
        assert!(has_book_level_raw_marker_leak(&files, None));
    }
}
