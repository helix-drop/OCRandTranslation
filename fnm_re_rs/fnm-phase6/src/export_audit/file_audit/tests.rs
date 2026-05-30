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

#[test]
fn test_chapter_boundary_missing_tail_text_not_reversed() {
    // B1-5: 验证 chapter_boundary_missing_tail 的 issue_summary 文本正序。
    // 旧代码 chars().rev().take(120) 产出倒序字符串。
    // 新代码 chars().skip(n.saturating_sub(120)) 保持正序。
    // 构造一个 >60 字符、不以句号结尾的最后一段，触发 looks_like_missing_tail。
    let long_tail = "This is a very long paragraph that does not end with a period or other sentence terminator and should trigger the missing tail check because it exceeds sixty characters in length";
    assert!(long_tail.len() > 60);
    assert!(!long_tail.ends_with('.'));
    assert!(!long_tail.ends_with('!'));
    assert!(!long_tail.ends_with('?'));

    let content = format!("# Chapter Title\n\nSome body text.\n\n{}", long_tail);
    let chapter_titles = vec!["Chapter Title".to_string()];
    let result = audit_markdown_file(&AuditFileParams {
        path: "ch001.md",
        title: "Chapter Title",
        content: &content,
        chapter_titles: &chapter_titles,
        expected_role: "chapter",
        expected_title: "Chapter Title",
        page_span: &[1, 10],
        manual_toc_titles: None,
        chapter_note_markers: None,
    });

    // 应触发 chapter_boundary_missing_tail
    assert!(
        result
            .issue_codes
            .contains(&"chapter_boundary_missing_tail".to_string()),
        "应触发 missing_tail 检查"
    );

    // issue_summary 中的文本应为正序（不是 chars().rev() 的倒序）
    let summary_text = result
        .issue_summary
        .iter()
        .find(|s| s.contains("chapter_boundary_missing_tail"))
        .expect("应有 missing_tail 的 summary");
    // summary 格式为 "chapter_boundary_missing_tail: <tail_text>"
    let tail_part = summary_text
        .strip_prefix("chapter_boundary_missing_tail: ")
        .expect("summary 应有 prefix");
    // 验证 tail 文本是正序：包含 "terminator" 而非 "rotanimret"
    assert!(
        tail_part.contains("terminator"),
        "tail 文本应为正序（含 'terminator'），实际: {:?}",
        &tail_part[..tail_part.len().min(60)]
    );
    assert!(
        !tail_part.contains("rotanimret"),
        "tail 文本不应为倒序"
    );
}
