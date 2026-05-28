use crate::export_audit::file_audit::{audit_markdown_file, AuditFileParams};

#[test]
fn test_audit_markdown_file_basic() {
    let content = "# Chapter Title\n\nSome body text with [^1] reference.\n\n[^1]: Note text.";
    let chapter_titles = vec!["Chapter Title".to_string()];
    let result = audit_markdown_file(&AuditFileParams {
        path: "ch001.md",
        title: "Chapter Title",
        content,
        chapter_titles: &chapter_titles,
        expected_role: "chapter",
        expected_title: "Chapter Title",
        page_span: &[1, 10],
        manual_toc_titles: None,
        chapter_note_markers: None,
    });
    assert_eq!(result.path, "ch001.md");
    assert!(result.issue_codes.is_empty() || result.severity != "blocking");
}

#[test]
fn test_audit_markdown_file_wrong_title() {
    let content = "# Wrong Title\n\nSome text.";
    let chapter_titles = vec!["Expected Title".to_string()];
    let result = audit_markdown_file(&AuditFileParams {
        path: "ch001.md",
        title: "Wrong Title",
        content,
        chapter_titles: &chapter_titles,
        expected_role: "chapter",
        expected_title: "Expected Title",
        page_span: &[],
        manual_toc_titles: None,
        chapter_note_markers: None,
    });
    assert!(result.issue_codes.contains(&"wrong_title".to_string()));
}

#[test]
fn test_audit_markdown_file_toc_residue() {
    let content = "# Title\n\nTable of Contents\nChapter 1... 10\n\nSome text.";
    let result = audit_markdown_file(&AuditFileParams {
        path: "ch001.md",
        title: "Title",
        content,
        chapter_titles: &[],
        expected_role: "chapter",
        expected_title: "Title",
        page_span: &[],
        manual_toc_titles: None,
        chapter_note_markers: None,
    });
    assert!(result.issue_codes.contains(&"toc_residue".to_string()));
}

#[test]
fn test_audit_markdown_file_index_file() {
    let content = "# Index\n\nEntry 1\nEntry 2";
    let result = audit_markdown_file(&AuditFileParams {
        path: "index.md",
        title: "Index",
        content,
        chapter_titles: &[],
        expected_role: "index_file",
        expected_title: "Index",
        page_span: &[],
        manual_toc_titles: None,
        chapter_note_markers: None,
    });
    assert!(result.issue_codes.is_empty());
    assert_eq!(result.severity, "minor");
}
