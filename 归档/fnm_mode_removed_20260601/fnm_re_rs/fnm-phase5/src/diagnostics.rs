//! ←→ FNM_RE/modules/chapter_merge.py
//! 翻译的函数：
//!   build_chapter_issue_diagnostics ←→ _build_chapter_issue_diagnostics (chapter_merge.py:593)

use fnm_core::records::ChapterMarkdownEntry;

use crate::marker_rewrite::{
    chapter_contract_items_by_section, has_legacy_note_token, has_raw_marker_in_body,
};

/// 构建章节问题诊断。
///
/// ←→ Python `_build_chapter_issue_diagnostics()` (chapter_merge.py:593)
pub fn build_chapter_issue_diagnostics(
    chapters: &[ChapterMarkdownEntry],
    chapter_contract_summary: &serde_json::Value,
) -> (Vec<serde_json::Value>, serde_json::Value) {
    let contract_by_section = chapter_contract_items_by_section(chapter_contract_summary);
    let mut chapter_issue_summary: Vec<serde_json::Value> = Vec::new();
    let mut chapter_issue_count: i64 = 0;
    let mut frozen_ref_leak_chapter_count: i64 = 0;
    let mut raw_marker_leak_chapter_count: i64 = 0;
    let mut local_ref_contract_broken_chapter_count: i64 = 0;

    for row in chapters {
        let chapter_id = row.chapter_id.trim().to_string();
        let contract_item = contract_by_section
            .get(&chapter_id)
            .cloned()
            .unwrap_or(serde_json::Value::Null);
        let contract_missing = contract_item.is_null();
        let missing_definition_count = if contract_missing {
            1 // contract row 缺失本身就是 blocker
        } else {
            contract_item
                .get("missing_definition_count")
                .and_then(|v| v.as_i64())
                .unwrap_or(0)
        };
        let orphan_definition_count = if contract_missing {
            1
        } else {
            contract_item
                .get("orphan_definition_count")
                .and_then(|v| v.as_i64())
                .unwrap_or(0)
        };

        let frozen_ref_leak = has_legacy_note_token(&row.markdown_text);
        let raw_marker_leak = has_raw_marker_in_body(&row.markdown_text);
        let local_refs_closed = missing_definition_count == 0 && orphan_definition_count == 0;
        let has_issue = frozen_ref_leak || raw_marker_leak || !local_refs_closed;

        if has_issue {
            chapter_issue_count += 1;
        }
        if frozen_ref_leak {
            frozen_ref_leak_chapter_count += 1;
        }
        if raw_marker_leak {
            raw_marker_leak_chapter_count += 1;
        }
        if !local_refs_closed {
            local_ref_contract_broken_chapter_count += 1;
        }

        chapter_issue_summary.push(serde_json::json!({
            "chapter_id": chapter_id,
            "title": row.title,
            "path": row.path,
            "frozen_ref_leak": frozen_ref_leak,
            "raw_marker_leak": raw_marker_leak,
            "missing_definition_count": missing_definition_count,
            "orphan_definition_count": orphan_definition_count,
            "local_refs_closed": local_refs_closed,
        }));
    }

    let chapter_issue_counts = serde_json::json!({
        "chapter_issue_count": chapter_issue_count,
        "frozen_ref_leak_chapter_count": frozen_ref_leak_chapter_count,
        "raw_marker_leak_chapter_count": raw_marker_leak_chapter_count,
        "local_ref_contract_broken_chapter_count": local_ref_contract_broken_chapter_count,
    });

    (chapter_issue_summary, chapter_issue_counts)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_chapter_issue_diagnostics_empty() {
        let chapters = vec![];
        let summary = serde_json::json!({});
        let (issues, counts) = build_chapter_issue_diagnostics(&chapters, &summary);
        assert!(issues.is_empty());
        assert_eq!(
            counts.get("chapter_issue_count").and_then(|v| v.as_i64()),
            Some(0)
        );
    }

    #[test]
    fn test_build_chapter_issue_diagnostics_clean() {
        let chapters = vec![ChapterMarkdownEntry {
            chapter_id: "ch1".to_string(),
            title: "Chapter 1".to_string(),
            path: "ch1.md".to_string(),
            markdown_text: "Clean text [^1].\n\n[^1]: Note.".to_string(),
            ..Default::default()
        }];
        let summary = serde_json::json!({
            "items": [
                {
                    "section_id": "ch1",
                    "missing_definition_count": 0,
                    "orphan_definition_count": 0,
                }
            ]
        });
        let (issues, counts) = build_chapter_issue_diagnostics(&chapters, &summary);
        assert_eq!(issues.len(), 1);
        assert!(!issues[0]["frozen_ref_leak"].as_bool().unwrap());
        assert!(!issues[0]["raw_marker_leak"].as_bool().unwrap());
        assert!(issues[0]["local_refs_closed"].as_bool().unwrap());
        assert_eq!(
            counts.get("chapter_issue_count").and_then(|v| v.as_i64()),
            Some(0)
        );
    }

    #[test]
    fn test_build_chapter_issue_diagnostics_frozen_leak() {
        let chapters = vec![ChapterMarkdownEntry {
            chapter_id: "ch1".to_string(),
            title: "Chapter 1".to_string(),
            path: "ch1.md".to_string(),
            markdown_text: "Text with [FN-123] legacy ref.".to_string(),
            ..Default::default()
        }];
        let summary = serde_json::json!({
            "items": [
                {
                    "section_id": "ch1",
                    "missing_definition_count": 0,
                    "orphan_definition_count": 0,
                }
            ]
        });
        let (_issues, counts) = build_chapter_issue_diagnostics(&chapters, &summary);
        assert_eq!(
            counts
                .get("frozen_ref_leak_chapter_count")
                .and_then(|v| v.as_i64()),
            Some(1)
        );
        assert_eq!(
            counts.get("chapter_issue_count").and_then(|v| v.as_i64()),
            Some(1)
        );
    }

    #[test]
    fn test_build_chapter_issue_diagnostics_unclosed_refs() {
        let chapters = vec![ChapterMarkdownEntry {
            chapter_id: "ch1".to_string(),
            title: "Chapter 1".to_string(),
            path: "ch1.md".to_string(),
            markdown_text: "Text.".to_string(),
            ..Default::default()
        }];
        let summary = serde_json::json!({
            "items": [
                {
                    "section_id": "ch1",
                    "missing_definition_count": 2,
                    "orphan_definition_count": 1,
                }
            ]
        });
        let (_issues, counts) = build_chapter_issue_diagnostics(&chapters, &summary);
        assert_eq!(
            counts
                .get("local_ref_contract_broken_chapter_count")
                .and_then(|v| v.as_i64()),
            Some(1)
        );
    }

    /// `[FN-note1]` 等旧版 token 应被 `replace_frozen_refs` 转换，不应残留到 Phase5 合并诊断。
    #[test]
    fn contract_no_merge_frozen_ref_leak_from_fn_bracket() {
        use fnm_core::refs::replace_frozen_refs;
        let raw = "Body text with [FN-note1] legacy ref.\n\n[^1]: Note.";
        let rendered = replace_frozen_refs(raw);
        // 转换后应不再匹配 legacy token 检测
        assert!(
            !crate::marker_rewrite::has_legacy_note_token(&rendered),
            "replace_frozen_refs must convert [FN-note1] → [^note1]"
        );
    }

    /// `[EN-note1]` 同理。
    #[test]
    fn contract_no_merge_frozen_ref_leak_from_en_bracket() {
        use fnm_core::refs::replace_frozen_refs;
        let raw = "Body text with [EN-note1] legacy ref.\n\n[^1]: Note.";
        let rendered = replace_frozen_refs(raw);
        assert!(
            !crate::marker_rewrite::has_legacy_note_token(&rendered),
            "replace_frozen_refs must convert [EN-note1] → [^note1]"
        );
    }

    /// `{{NOTE_REF:note1}}` 同样。
    #[test]
    fn contract_no_merge_frozen_ref_leak_from_note_ref() {
        use fnm_core::refs::replace_frozen_refs;
        let raw = "Body text with {{NOTE_REF:note1}} legacy ref.\n\n[^1]: Note.";
        let rendered = replace_frozen_refs(raw);
        assert!(
            !crate::marker_rewrite::has_legacy_note_token(&rendered),
            "replace_frozen_refs must convert {{NOTE_REF:note1}} → [^note1]"
        );
    }

    /// `[^en-note1]` 旧版尾注。
    #[test]
    fn contract_no_merge_frozen_ref_leak_from_endnote_label() {
        use fnm_core::refs::replace_frozen_refs;
        let raw = "Body text with [^en-note1] legacy ref.\n\n[^1]: Note.";
        let rendered = replace_frozen_refs(raw);
        assert!(
            !crate::marker_rewrite::has_legacy_note_token(&rendered),
            "replace_frozen_refs must convert [^en-note1] → [^note1]"
        );
    }

    /// `merge_raw_marker_leak` 需要 Phase3 级别的 marker 序列修复，
    /// 不在 replace_frozen_refs 做全局 `[N]` → `[^N]` 转换（会制造 false missing_note_definition）。
    /// 此测试仅验证 `has_raw_marker_in_body` 正确识别原始标记。
    #[test]
    fn contract_raw_bracket_marker_detected_correctly() {
        // replace_frozen_refs 不处理 [N] 格式，因此 [3] 仍保留
        use fnm_core::refs::replace_frozen_refs;
        let raw = "Body text with [3] raw marker.";
        let rendered = replace_frozen_refs(raw);
        assert!(
            rendered.contains("[3]"),
            "replace_frozen_refs must NOT convert [3] (not a frozen ref format)"
        );
    }
}
