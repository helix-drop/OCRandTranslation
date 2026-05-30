//! 单文件导出审计。
//!
//! ←→ Python `FNM_RE/stages/export_audit.py` 中的 `audit_markdown_file()` (line 349)

use std::collections::HashSet;

use fnm_core::records::ExportAuditFileRecord;

use super::helpers::*;

/// 审计单个 Markdown 文件的参数。
pub struct AuditFileParams<'a> {
    pub path: &'a str,
    pub title: &'a str,
    pub content: &'a str,
    pub chapter_titles: &'a [String],
    pub expected_role: &'a str,
    pub expected_title: &'a str,
    pub page_span: &'a [i64],
    pub manual_toc_titles: Option<&'a [String]>,
    pub chapter_note_markers: Option<&'a HashSet<String>>,
}

/// 审计单个 Markdown 文件。
///
/// ←→ Python `audit_markdown_file()` (export_audit.py:349)
pub fn audit_markdown_file(params: &AuditFileParams) -> ExportAuditFileRecord {
    let raw_text = params.content;
    let (body_text, definition_text) = split_body_and_definitions(raw_text);
    let paragraphs = body_paragraphs(raw_text);
    let definitions = definition_lines(raw_text);

    let mut refs: Vec<String> = LOCAL_REF_RE
        .captures_iter(&body_text)
        .filter_map(|caps| caps.get(1).map(|m| m.as_str().to_string()))
        .collect();
    refs.sort_by_key(|a| numeric_first_sort_key(a));
    refs.dedup();

    let mut defs: Vec<String> = LOCAL_DEF_RE
        .captures_iter(raw_text)
        .filter_map(|caps| caps.get(1).map(|m| m.as_str().to_string()))
        .collect();
    defs.sort_by_key(|a| numeric_first_sort_key(a));
    defs.dedup();

    let file_title = file_title_from_content(raw_text);
    let mut issue_codes: Vec<String> = Vec::new();
    let mut issue_summary: Vec<String> = Vec::new();
    let normalized_role = params.expected_role.trim();

    // index_file 快速返回
    if normalized_role == "index_file" {
        return ExportAuditFileRecord {
            path: params.path.to_string(),
            title: if !params.expected_title.is_empty() {
                params.expected_title.to_string()
            } else if !params.title.is_empty() {
                params.title.to_string()
            } else {
                file_title
            },
            page_span: params.page_span.to_vec(),
            issue_codes: vec![],
            issue_summary: vec![],
            severity: "minor".to_string(),
            sample_opening: paragraphs
                .first()
                .map(|p| p.chars().take(280).collect())
                .unwrap_or_default(),
            sample_mid: paragraphs
                .get(paragraphs.len() / 2)
                .map(|p| p.chars().take(280).collect())
                .unwrap_or_default(),
            sample_tail: paragraphs
                .last()
                .map(|p| p.chars().take(280).collect())
                .unwrap_or_default(),
            footnote_endnote_summary: serde_json::json!({
                "body_ref_count": refs.len(),
                "definition_count": defs.len(),
                "missing_definition_markers": [],
                "orphan_definition_markers": [],
                "raw_note_marker_count": 0,
                "legacy_token_count": 0,
                "definition_lines_preview": definitions.iter().take(6).collect::<Vec<_>>(),
            }),
            ..Default::default()
        };
    }

    // 标题检查
    if !params.expected_title.is_empty()
        && alphanumeric_key(&file_title) != alphanumeric_key(params.expected_title)
    {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "wrong_title",
            &format!("{} != {}", file_title, params.expected_title),
        );
    }

    // 语义角色检查
    if normalized_role == "container" || normalized_role == "back_matter" {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "semantic_role_mismatch",
            normalized_role,
        );
    }

    // 手动目录检查
    if let Some(titles) = params.manual_toc_titles {
        let manual_keys: HashSet<String> = titles
            .iter()
            .map(|t| alphanumeric_key(t))
            .filter(|k| !k.is_empty())
            .collect();
        let expected_key = alphanumeric_key(params.expected_title);
        if !expected_key.is_empty() && !manual_keys.contains(&expected_key) {
            add_issue(
                &mut issue_codes,
                &mut issue_summary,
                "manual_toc_mismatch",
                params.expected_title,
            );
        }
    }

    // 句子中间开头检查
    if let Some(first) = paragraphs.first() {
        if looks_like_mid_sentence_opening(first) {
            add_issue(
                &mut issue_codes,
                &mut issue_summary,
                "mid_sentence_opening",
                &first.chars().take(120).collect::<String>(),
            );
        }
    }

    // 前置内容泄露检查
    if normalized_role == "chapter" && looks_like_front_matter_opening(&paragraphs) {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "front_matter_leak",
            &paragraphs
                .first()
                .map(|p| p.chars().take(120).collect::<String>())
                .unwrap_or_default(),
        );
    }

    // 后置内容泄露检查
    let first_two: String = paragraphs
        .iter()
        .take(2)
        .map(|s| s.as_str())
        .collect::<Vec<_>>()
        .join("\n");
    if BACK_MATTER_TEXT_RE.is_match(&first_two) && normalized_role == "chapter" {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "back_matter_leak",
            &paragraphs
                .first()
                .map(|p| p.chars().take(120).collect::<String>())
                .unwrap_or_default(),
        );
    }

    // 目录残留检查
    if TOC_HEADING_RE.is_match(raw_text) || TOC_LINE_RE.is_match(raw_text) {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "toc_residue",
            "detected",
        );
    }

    // 原始注释标记泄露检查
    let raw_note_hits = iter_raw_note_marker_hits(&body_text, params.chapter_note_markers);
    let raw_superscript_hits =
        iter_raw_superscript_note_marker_hits(&body_text, params.chapter_note_markers);
    let definition_raw_note_leak =
        definition_has_raw_note_marker(&definition_text, params.chapter_note_markers);

    if !raw_note_hits.is_empty() || !raw_superscript_hits.is_empty() || definition_raw_note_leak {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "raw_note_marker_leak",
            "detected",
        );
    }

    // 旧版标记泄露检查
    if LEGACY_FOOTNOTE_RE.is_match(raw_text)
        || LEGACY_ENDNOTE_RE.is_match(raw_text)
        || LEGACY_EN_BRACKET_RE.is_match(raw_text)
        || LEGACY_NOTE_TOKEN_RE.is_match(raw_text)
    {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "legacy_note_token_leak",
            "detected",
        );
    }

    // 注释定义完整性检查
    let ref_set: HashSet<&str> = refs.iter().map(|s| s.as_str()).collect();
    let def_set: HashSet<&str> = defs.iter().map(|s| s.as_str()).collect();
    let mut missing_defs: Vec<String> = ref_set
        .difference(&def_set)
        .map(|s| s.to_string())
        .collect();
    missing_defs.sort_by_key(|a| numeric_first_sort_key(a));

    let mut orphan_defs: Vec<String> = def_set
        .difference(&ref_set)
        .map(|s| s.to_string())
        .collect();
    orphan_defs.sort_by_key(|a| numeric_first_sort_key(a));

    if !missing_defs.is_empty() {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "missing_note_definition",
            &missing_defs
                .iter()
                .take(8)
                .cloned()
                .collect::<Vec<_>>()
                .join(","),
        );
    }
    if !orphan_defs.is_empty() {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "orphan_note_definition",
            &orphan_defs
                .iter()
                .take(8)
                .cloned()
                .collect::<Vec<_>>()
                .join(","),
        );
    }
    if !missing_defs.is_empty() || !orphan_defs.is_empty() {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "local_note_contract_broken",
            "refs_defs_mismatch",
        );
    }

    // 段落中间标题检查
    if detect_mid_paragraph_heading(&body_text) {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "mid_paragraph_heading",
            "detected",
        );
    }

    // 重复标题检查
    if duplicate_heading_count(&body_text) > 0 {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "duplicated_heading",
            "detected",
        );
    }

    // 重复段落检查
    if duplicate_paragraph_count(&paragraphs) > 0 {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "duplicate_paragraph",
            "detected",
        );
    }

    // 章节边界检查
    let effective_title = if !params.expected_title.is_empty() {
        params.expected_title
    } else if !params.title.is_empty() {
        params.title
    } else {
        &file_title
    };
    if contains_other_chapter_heading(raw_text, effective_title, params.chapter_titles) {
        add_issue(
            &mut issue_codes,
            &mut issue_summary,
            "chapter_boundary_swallow_next",
            "detected",
        );
    }

    // 缺失尾部检查
    if let Some(last) = paragraphs.last() {
        if looks_like_missing_tail(last) {
            add_issue(
                &mut issue_codes,
                &mut issue_summary,
                "chapter_boundary_missing_tail",
                &{
                    let n = last.chars().count();
                    last.chars().skip(n.saturating_sub(120)).collect::<String>()
                },
            );
        }
    }

    // 计算严重程度
    let mut severity = "minor".to_string();
    for code in &issue_codes {
        let code_severity = ISSUE_SEVERITY.get(code.as_str()).unwrap_or(&"minor");
        let current_rank = _SEVERITY_RANK.get(severity.as_str()).unwrap_or(&1);
        let code_rank = _SEVERITY_RANK.get(code_severity).unwrap_or(&1);
        if code_rank > current_rank {
            severity = code_severity.to_string();
        }
    }

    ExportAuditFileRecord {
        path: params.path.to_string(),
        title: if !params.expected_title.is_empty() {
            params.expected_title.to_string()
        } else if !params.title.is_empty() {
            params.title.to_string()
        } else {
            file_title
        },
        page_span: params.page_span.to_vec(),
        issue_codes: issue_codes.clone(),
        issue_summary: issue_summary.clone(),
        severity: if issue_codes.is_empty() {
            "minor".to_string()
        } else {
            severity
        },
        sample_opening: paragraphs
            .first()
            .map(|p| p.chars().take(280).collect())
            .unwrap_or_default(),
        sample_mid: paragraphs
            .get(paragraphs.len() / 2)
            .map(|p| p.chars().take(280).collect())
            .unwrap_or_default(),
        sample_tail: paragraphs
            .last()
            .map(|p| p.chars().take(280).collect())
            .unwrap_or_default(),
        footnote_endnote_summary: serde_json::json!({
            "body_ref_count": refs.len(),
            "definition_count": defs.len(),
            "missing_definition_markers": missing_defs.iter().take(8).collect::<Vec<_>>(),
            "orphan_definition_markers": orphan_defs.iter().take(8).collect::<Vec<_>>(),
            "raw_note_marker_count": raw_note_hits.len() + raw_superscript_hits.len() + if definition_raw_note_leak { 1 } else { 0 },
            "legacy_token_count": LEGACY_FOOTNOTE_RE.find_iter(raw_text).count()
                + LEGACY_ENDNOTE_RE.find_iter(raw_text).count()
                + LEGACY_EN_BRACKET_RE.find_iter(raw_text).count()
                + LEGACY_NOTE_TOKEN_RE.find_iter(raw_text).count(),
            "definition_lines_preview": definitions.iter().take(6).collect::<Vec<_>>(),
        }),
        ..Default::default()
    }
}

#[cfg(test)]
mod tests;
