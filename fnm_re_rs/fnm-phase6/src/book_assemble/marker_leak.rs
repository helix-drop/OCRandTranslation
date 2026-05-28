//! ←→ FNM_RE/modules/book_assemble.py
//!
//! 底层 helper 函数的集成测试。
//! `has_book_level_raw_marker_leak` 已不在生产代码中使用，实际检测由
//! `audit_logic::compute_semantic_gates` 通过 `structure_reviews` 完成。

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use crate::export_audit::helpers::{
        definition_has_raw_note_marker, iter_raw_note_marker_hits,
        iter_raw_superscript_note_marker_hits, split_body_and_definitions, LOCAL_DEF_RE,
        LOCAL_REF_RE,
    };

    /// 检测全书级的原始注释标记泄漏（测试专用）。
    fn has_book_level_raw_marker_leak(
        chapter_files: &std::collections::HashMap<String, String>,
    ) -> bool {
        for content in chapter_files.values() {
            let (body_text, definition_text) = split_body_and_definitions(content);

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

    #[test]
    fn no_leak_empty_files() {
        let files = std::collections::HashMap::new();
        assert!(!has_book_level_raw_marker_leak(&files));
    }

    #[test]
    fn no_leak_clean_content() {
        let mut files = std::collections::HashMap::new();
        files.insert(
            "ch001.md".to_string(),
            "Clean body text with [^1] reference.\n\n[^1]: Clean definition.".to_string(),
        );
        assert!(!has_book_level_raw_marker_leak(&files));
    }

    #[test]
    fn no_leak_with_raw_bracket_no_allowed_markers() {
        let mut files = std::collections::HashMap::new();
        files.insert(
            "ch001.md".to_string(),
            "Text with [1] raw marker but no footnote system.\n".to_string(),
        );
        assert!(!has_book_level_raw_marker_leak(&files));
    }

    #[test]
    fn leak_with_raw_bracket() {
        let mut files = std::collections::HashMap::new();
        files.insert(
            "ch001.md".to_string(),
            "Text with [^1] reference and also [1] raw same marker.\n\n[^1]: Definition of note 1.\n"
                .to_string(),
        );
        assert!(has_book_level_raw_marker_leak(&files));
    }
}
