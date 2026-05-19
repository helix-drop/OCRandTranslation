//! Export audit 辅助函数。
//!
//! ←→ Python `FNM_RE/stages/export_audit.py` 中的 13 个 helper 函数

use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashMap;

// ── 正则常量 ──────────────────────────────────────────────────

/// 匹配 [^N] 形式的本地引用
pub static LOCAL_REF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[\^([0-9]+)\]").unwrap());

/// 匹配 [^N]: 形式的定义行
pub static LOCAL_DEF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?m)^\[\^([0-9]+)\]:").unwrap());

/// 匹配 ### 标题
pub static SECTION_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)^###\s+(.+?)\s*$").unwrap());

/// 匹配 Markdown 标题（1-6 级）
pub static HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s{0,3}(#{1,6})\s*(.+?)\s*$").unwrap());

/// 匹配裸方括号注释引用（如 [1], [2a]）
/// 注意：Rust regex 不支持 look-ahead/look-behind，使用简化版本
pub static RAW_BRACKET_NOTE_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\[(\d{1,4}[A-Za-z]?)\]").unwrap());

/// 匹配上标形式的注释引用（如 $^{[1]}$, <sup>1</sup>, ¹）
pub static RAW_SUPERSCRIPT_NOTE_REF_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"\$\s*\^\{\s*\[?(\d{1,4}[A-Za-z]?)\]?\s*\}\s*\$|<sup>\s*\[?(\d{1,4}[A-Za-z]?)\]?\s*</sup>|([⁰¹²³⁴⁵⁶⁷⁸⁹]+)",
    )
    .unwrap()
});

/// 匹配旧版脚注标记 [FN-xxx]
pub static LEGACY_FOOTNOTE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[FN-[^\]]+\]").unwrap());

/// 匹配旧版尾注标记 [^en-xxx]
pub static LEGACY_ENDNOTE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[\^en-[^\]]+\]").unwrap());

/// 匹配旧版 EN 标记 [EN-xxx]
pub static LEGACY_EN_BRACKET_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[EN-[^\]]+\]").unwrap());

/// 匹配旧版模板标记 {{NOTE_REF:xxx}}, {{FN_REF:xxx}}, {{EN_REF:xxx}}
pub static LEGACY_NOTE_TOKEN_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\{\{(?:NOTE_REF|FN_REF|EN_REF):[^}]+\}\}").unwrap());

/// 匹配目录行（如 "Chapter 1 ................ 10"）
pub static TOC_LINE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?im)^\s*.+\.{3,}\s*\d+\s*$").unwrap());

/// 匹配目录标题（如 "Table of Contents", "目录"）
pub static TOC_HEADING_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?im)^\s*(?:table of contents|contents|table des mati[eè]res|sommaire|目录)\b")
        .unwrap()
});

/// 匹配前置内容文本（版权、ISBN 等）
pub static FRONT_MATTER_TEXT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"\b(?:copyright|all rights reserved|printed in|library of congress|isbn|published by|code de la propriété intellectuelle)\b",
    )
    .unwrap()
});

/// 匹配出版社印记
pub static FRONT_MATTER_IMPRINT_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\b(?:gallimard|seuil|routledge introductions?)\b").unwrap());

/// 匹配后置内容文本（参考文献、索引等）
pub static BACK_MATTER_TEXT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"\b(?:bibliograph(?:y|ie)|index(?: des?| historique)?|glossary|works cited|references?)\b",
    )
    .unwrap()
});

/// 匹配行首的原始注释标记
pub static _LEADING_RAW_NOTE_MARKER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"^\s*(?:\[\d{1,4}[A-Za-z]?\]|\(\d{1,4}[A-Za-z]?\)|\d{1,4}[A-Za-z]?[.)]|<sup>\s*\d{1,4}[A-Za-z]?\s*</sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)\s+",
    )
    .unwrap()
});

/// 匹配定义行（包括缩进的续行）
pub static _LOCAL_DEF_LINE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*\[\^[^\]]+\]:").unwrap());

// ── ISSUE_SEVERITY 映射 ──────────────────────────────────────

/// 问题类型 → 严重程度映射
pub static ISSUE_SEVERITY: Lazy<HashMap<&'static str, &'static str>> = Lazy::new(|| {
    let mut m = HashMap::new();
    m.insert("wrong_title", "blocking");
    m.insert("mid_sentence_opening", "major");
    m.insert("front_matter_leak", "blocking");
    m.insert("back_matter_leak", "major");
    m.insert("toc_residue", "blocking");
    m.insert("raw_note_marker_leak", "blocking");
    m.insert("legacy_note_token_leak", "blocking");
    m.insert("local_note_contract_broken", "blocking");
    m.insert("missing_note_definition", "blocking");
    m.insert("orphan_note_definition", "blocking");
    m.insert("mid_paragraph_heading", "major");
    m.insert("duplicated_heading", "major");
    m.insert("duplicate_paragraph", "major");
    m.insert("chapter_boundary_swallow_next", "blocking");
    m.insert("chapter_boundary_missing_tail", "major");
    m.insert("semantic_role_mismatch", "blocking");
    m.insert("manual_toc_mismatch", "blocking");
    m.insert("toc_organization_mismatch", "blocking");
    m.insert("missing_post_body_export", "blocking");
    m.insert("container_exported_as_chapter", "blocking");
    m.insert("export_depth_too_shallow", "blocking");
    m
});

/// 严重程度排名（用于比较）
pub static _SEVERITY_RANK: Lazy<HashMap<&'static str, i32>> = Lazy::new(|| {
    let mut m = HashMap::new();
    m.insert("blocking", 3);
    m.insert("major", 2);
    m.insert("minor", 1);
    m
});

/// Unicode 上标 → ASCII 数字翻译表
static _UNICODE_SUPERSCRIPT_TRANSLATION: Lazy<HashMap<char, char>> = Lazy::new(|| {
    let mut m = HashMap::new();
    m.insert('⁰', '0');
    m.insert('¹', '1');
    m.insert('²', '2');
    m.insert('³', '3');
    m.insert('⁴', '4');
    m.insert('⁵', '5');
    m.insert('⁶', '6');
    m.insert('⁷', '7');
    m.insert('⁸', '8');
    m.insert('⁹', '9');
    m
});

// ── 基础 helper 函数 ──────────────────────────────────────────

/// 数字优先排序键。
///
/// ←→ Python `_numeric_first_sort_key()` (export_audit.py:80)
pub fn numeric_first_sort_key(value: &str) -> (i32, String) {
    let text = value.trim();
    if text.chars().all(|c| c.is_ascii_digit()) {
        if let Ok(n) = text.parse::<i32>() {
            return (0, n.to_string());
        }
    }
    (1, text.to_string())
}

/// 字母数字键（用于标题比较）。
///
/// ←→ Python `_alphanumeric_key()` (export_audit.py:87)
pub fn alphanumeric_key(text: &str) -> String {
    let lower = text.trim().to_lowercase();
    let mut result = String::new();
    for c in lower.chars() {
        if c.is_ascii_alphanumeric() {
            result.push(c);
        }
    }
    result
}

/// 分离正文和定义块。
///
/// ←→ Python `split_body_and_definitions()` (export_audit.py:91)
pub fn split_body_and_definitions(content: &str) -> (String, String) {
    let mut body_lines: Vec<String> = Vec::new();
    let mut definition_lines: Vec<String> = Vec::new();
    let mut in_definition_block = false;

    for raw_line in content.lines() {
        if LOCAL_DEF_RE.is_match(raw_line) {
            in_definition_block = true;
            definition_lines.push(raw_line.to_string());
            continue;
        }
        if in_definition_block && (raw_line.starts_with("    ") || raw_line.starts_with('\t')) {
            definition_lines.push(raw_line.to_string());
            continue;
        }
        in_definition_block = false;
        body_lines.push(raw_line.to_string());
    }

    (body_lines.join("\n"), definition_lines.join("\n"))
}

/// 提取正文段落列表。
///
/// ←→ Python `body_paragraphs()` (export_audit.py:108)
pub fn body_paragraphs(content: &str) -> Vec<String> {
    let (body_text, _) = split_body_and_definitions(content);
    let mut paragraphs: Vec<String> = Vec::new();

    for chunk in body_text.split("\n\n") {
        let text = chunk.trim();
        if text.is_empty() || text.starts_with('#') {
            continue;
        }
        paragraphs.push(text.to_string());
    }

    paragraphs
}

/// 提取定义行列表。
///
/// ←→ Python `definition_lines()` (export_audit.py:119)
pub fn definition_lines(content: &str) -> Vec<String> {
    let (_, definition) = split_body_and_definitions(content);
    definition
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| line.trim_end().to_string())
        .collect()
}

/// 提取开头几行。
///
/// ←→ Python `_opening_lines()` (export_audit.py:124)
pub fn opening_lines(paragraphs: &[String], limit: usize) -> Vec<String> {
    let mut lines: Vec<String> = Vec::new();
    for paragraph in paragraphs.iter().take(limit) {
        for raw_line in paragraph.lines() {
            let line = raw_line.split_whitespace().collect::<Vec<&str>>().join(" ");
            if !line.is_empty() {
                lines.push(line);
            }
        }
    }
    lines
}

/// 判断是否像连续散文。
///
/// ←→ Python `_looks_like_running_prose()` (export_audit.py:134)
pub fn looks_like_running_prose(paragraph: &str) -> bool {
    let text: String = paragraph
        .split_whitespace()
        .collect::<Vec<&str>>()
        .join(" ");
    if text.len() < 120 {
        return false;
    }
    if text.chars().all(|c| c.is_uppercase() || !c.is_alphabetic()) {
        return false;
    }
    if !Regex::new(r"[.!?。！？]").unwrap().is_match(&text) {
        return false;
    }
    let words: Vec<&str> = Regex::new(r"[0-9A-Za-zÀ-ÿ][0-9A-Za-zÀ-ÿ'\u{2019}\-]*")
        .unwrap()
        .find_iter(&text)
        .map(|m| m.as_str())
        .collect();
    words.len() >= 18
}

/// 判断是否像前置内容开头。
///
/// ←→ Python `_looks_like_front_matter_opening()` (export_audit.py:146)
pub fn looks_like_front_matter_opening(paragraphs: &[String]) -> bool {
    let window: Vec<&str> = paragraphs
        .iter()
        .take(2)
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .collect();
    if window.is_empty() {
        return false;
    }
    let joined = window.join("\n");
    let lines = opening_lines(&window.iter().map(|s| s.to_string()).collect::<Vec<_>>(), 2);
    if lines.is_empty() {
        return false;
    }

    let explicit_meta_lines = lines
        .iter()
        .filter(|line| FRONT_MATTER_TEXT_RE.is_match(line))
        .count();
    let imprint_lines = lines
        .iter()
        .filter(|line| FRONT_MATTER_IMPRINT_RE.is_match(line))
        .count();
    let prose_like_paragraphs = window
        .iter()
        .filter(|p| looks_like_running_prose(p))
        .count();
    let mostly_short_lines =
        lines.iter().filter(|line| line.len() <= 80).count() >= std::cmp::max(2, lines.len() - 1);

    if explicit_meta_lines > 0 {
        return explicit_meta_lines >= 2 || prose_like_paragraphs == 0 || mostly_short_lines;
    }
    if FRONT_MATTER_IMPRINT_RE.is_match(&joined) {
        return prose_like_paragraphs == 0 && (imprint_lines >= 2 || mostly_short_lines);
    }
    false
}

/// 从内容中提取文件标题。
///
/// ←→ Python `_file_title_from_content()` (export_audit.py:165)
pub fn file_title_from_content(content: &str) -> String {
    for raw_line in content.lines() {
        let line = raw_line.trim();
        if line.is_empty() {
            continue;
        }
        if let Some(caps) = HEADING_RE.captures(line) {
            return caps
                .get(2)
                .map(|m| m.as_str().trim().to_string())
                .unwrap_or_default();
        }
        return line.to_string();
    }
    String::new()
}

/// 判断是否像句子中间开头。
///
/// ←→ Python `_looks_like_mid_sentence_opening()` (export_audit.py:177)
pub fn looks_like_mid_sentence_opening(paragraph: &str) -> bool {
    let text = paragraph.trim();
    if text.is_empty() {
        return false;
    }
    if text.starts_with("[^")
        || text.starts_with('(')
        || text.starts_with('[')
        || text.starts_with('"')
        || text.starts_with('\u{201C}')
        || text.starts_with('\u{00AB}')
    {
        return false;
    }
    if Regex::new(r"^[a-zà-ÿ]").unwrap().is_match(text) {
        return true;
    }
    if text.starts_with("and ")
        || text.starts_with("or ")
        || text.starts_with("but ")
        || text.starts_with("et ")
        || text.starts_with("ou ")
        || text.starts_with("mais ")
    {
        return true;
    }
    false
}

/// 判断是否像缺失尾部。
///
/// ←→ Python `_looks_like_missing_tail()` (export_audit.py:190)
pub fn looks_like_missing_tail(paragraph: &str) -> bool {
    let text = Regex::new(r"\[\^[0-9]+\]")
        .unwrap()
        .replace_all(paragraph, "")
        .trim()
        .to_string();
    if text.len() < 60 {
        return false;
    }
    // 简化版 bibliography 检测
    if Regex::new(r"\b\d{4}\b").unwrap().is_match(&text) && text.contains("pp.") {
        return false;
    }
    let text = Regex::new(r"\s*\(\s*fin du m(?:s|anuscrit)\.?\s*\)\s*$")
        .unwrap()
        .replace_all(&text, "")
        .trim()
        .to_string();
    let text = Regex::new(r"\s*\*\s*$")
        .unwrap()
        .replace_all(&text, "")
        .trim()
        .to_string();
    !text.ends_with('.')
        && !text.ends_with('!')
        && !text.ends_with('?')
        && !text.ends_with('。')
        && !text.ends_with('！')
        && !text.ends_with('？')
        && !text.ends_with('"')
        && !text.ends_with('"')
        && !text.ends_with('\u{00BB}')
}

/// 检测段落中间的标题。
///
/// ←→ Python `_detect_mid_paragraph_heading()` (export_audit.py:201)
pub fn detect_mid_paragraph_heading(body_text: &str) -> bool {
    let lines: Vec<&str> = body_text.lines().collect();
    for (idx, line) in lines.iter().enumerate() {
        let stripped = line.trim();
        if !stripped.starts_with("### ") {
            continue;
        }
        let prev = if idx > 0 { lines[idx - 1].trim() } else { "" };
        if !prev.is_empty() && !prev.starts_with('#') {
            return true;
        }
    }
    false
}

/// 统计重复标题数量。
///
/// ←→ Python `_duplicate_heading_count()` (export_audit.py:213)
pub fn duplicate_heading_count(body_text: &str) -> usize {
    let mut counts: HashMap<String, usize> = HashMap::new();
    for caps in SECTION_HEADING_RE.captures_iter(body_text) {
        let title: String = caps
            .get(1)
            .map(|m| {
                m.as_str()
                    .split_whitespace()
                    .collect::<Vec<&str>>()
                    .join(" ")
                    .trim()
                    .to_lowercase()
            })
            .unwrap_or_default();
        if title.is_empty() {
            continue;
        }
        *counts.entry(title).or_insert(0) += 1;
    }
    counts.values().filter(|&&c| c > 1).map(|c| c - 1).sum()
}

/// 统计重复段落数量。
///
/// ←→ Python `_duplicate_paragraph_count()` (export_audit.py:223)
pub fn duplicate_paragraph_count(paragraphs: &[String]) -> usize {
    let footnote_ref_re = Regex::new(r"\[\^[0-9]+\]").unwrap();
    let mut counts: HashMap<String, usize> = HashMap::new();
    for paragraph in paragraphs {
        let normalized = footnote_ref_re
            .replace_all(paragraph, "")
            .split_whitespace()
            .collect::<Vec<&str>>()
            .join(" ")
            .to_lowercase();
        let normalized = normalized.trim().to_string();
        if normalized.len() < 60 {
            continue;
        }
        *counts.entry(normalized).or_insert(0) += 1;
    }
    counts.values().filter(|&&c| c > 1).map(|c| c - 1).sum()
}

/// 检查是否包含其他章节标题。
///
/// ←→ Python `_contains_other_chapter_heading()` (export_audit.py:233)
pub fn contains_other_chapter_heading(
    content: &str,
    title: &str,
    chapter_titles: &[String],
) -> bool {
    let current_key = alphanumeric_key(title);
    let ordered_titles: Vec<&str> = chapter_titles
        .iter()
        .filter(|t| !alphanumeric_key(t).is_empty())
        .map(|s| s.as_str())
        .collect();
    let current_index = ordered_titles
        .iter()
        .position(|t| alphanumeric_key(t) == current_key);

    match current_index {
        Some(idx) if idx < ordered_titles.len() - 1 => {
            let next_title_key = alphanumeric_key(ordered_titles[idx + 1]);
            if next_title_key.is_empty() {
                return false;
            }
            for raw_line in content.lines() {
                let line = raw_line.trim();
                if line.is_empty() {
                    continue;
                }
                if let Some(caps) = HEADING_RE.captures(line) {
                    let key = alphanumeric_key(caps.get(2).map(|m| m.as_str()).unwrap_or(""));
                    if key == next_title_key {
                        return true;
                    }
                }
            }
            false
        }
        _ => false,
    }
}

/// 迭代原始注释标记命中。
///
/// ←→ Python `_iter_raw_note_marker_hits()` (export_audit.py:266)
pub fn iter_raw_note_marker_hits(
    text: &str,
    allowed_markers: Option<&std::collections::HashSet<String>>,
) -> Vec<String> {
    let mut hits: Vec<String> = Vec::new();
    let allowed: Option<std::collections::HashSet<String>> = allowed_markers.map(|s| {
        s.iter()
            .map(|v| alphanumeric_key(v))
            .filter(|k| !k.is_empty())
            .collect()
    });

    for caps in RAW_BRACKET_NOTE_REF_RE.captures_iter(text) {
        let marker = caps
            .get(1)
            .map(|m| m.as_str().trim().to_string())
            .unwrap_or_default();
        if marker.is_empty() {
            continue;
        }
        let marker_key = alphanumeric_key(&marker);
        if let Some(ref allowed_set) = allowed {
            if !allowed_set.contains(&marker_key) {
                continue;
            }
        }
        hits.push(marker);
    }
    hits
}

/// 迭代上标形式的注释标记命中。
///
/// ←→ Python `_iter_raw_superscript_note_marker_hits()` (export_audit.py:291)
pub fn iter_raw_superscript_note_marker_hits(
    text: &str,
    allowed_markers: Option<&std::collections::HashSet<String>>,
) -> Vec<String> {
    let mut hits: Vec<String> = Vec::new();
    let allowed: Option<std::collections::HashSet<String>> = allowed_markers.map(|s| {
        s.iter()
            .map(|v| alphanumeric_key(v))
            .filter(|k| !k.is_empty())
            .collect()
    });

    for caps in RAW_SUPERSCRIPT_NOTE_REF_RE.captures_iter(text) {
        let mut marker = caps
            .get(1)
            .or_else(|| caps.get(2))
            .map(|m| m.as_str().trim().to_string())
            .unwrap_or_default();
        if marker.is_empty() {
            marker = caps
                .get(3)
                .map(|m| {
                    m.as_str()
                        .chars()
                        .map(|c| {
                            _UNICODE_SUPERSCRIPT_TRANSLATION
                                .get(&c)
                                .copied()
                                .unwrap_or(c)
                        })
                        .collect::<String>()
                        .trim()
                        .to_string()
                })
                .unwrap_or_default();
        }
        if marker.is_empty() {
            continue;
        }
        let marker_key = alphanumeric_key(&marker);
        if let Some(ref allowed_set) = allowed {
            if !allowed_set.contains(&marker_key) {
                continue;
            }
        }
        hits.push(marker);
    }
    hits
}

/// 检查定义文本中是否有原始注释标记。
///
/// ←→ Python `_definition_has_raw_note_marker()` (export_audit.py:318)
pub fn definition_has_raw_note_marker(
    definition_text: &str,
    _allowed_markers: Option<&std::collections::HashSet<String>>,
) -> bool {
    if definition_text.trim().is_empty() {
        return false;
    }
    for line in definition_text.lines() {
        let stripped = line.trim();
        if stripped.is_empty() {
            continue;
        }
        if _LOCAL_DEF_LINE_RE.is_match(stripped) {
            continue;
        }
        if _LEADING_RAW_NOTE_MARKER_RE.is_match(stripped) {
            return true;
        }
    }
    false
}

/// 添加问题到列表。
///
/// ←→ Python `_add_issue()` (export_audit.py:342)
pub fn add_issue(
    issue_codes: &mut Vec<String>,
    issue_summary: &mut Vec<String>,
    code: &str,
    detail: &str,
) {
    if issue_codes.contains(&code.to_string()) {
        return;
    }
    issue_codes.push(code.to_string());
    if detail.is_empty() {
        issue_summary.push(code.to_string());
    } else {
        issue_summary.push(format!("{}: {}", code, detail));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_numeric_first_sort_key() {
        assert_eq!(numeric_first_sort_key("123"), (0, "123".to_string()));
        assert_eq!(numeric_first_sort_key("abc"), (1, "abc".to_string()));
        assert_eq!(numeric_first_sort_key(""), (1, "".to_string()));
    }

    #[test]
    fn test_alphanumeric_key() {
        assert_eq!(alphanumeric_key("Hello World!"), "helloworld");
        assert_eq!(alphanumeric_key("Chapter 1"), "chapter1");
        assert_eq!(alphanumeric_key(""), "");
    }

    #[test]
    fn test_split_body_and_definitions() {
        let content = "Body line 1\n\n[^1]: Definition 1\n[^2]: Definition 2";
        let (body, defs) = split_body_and_definitions(content);
        assert!(body.contains("Body line 1"));
        assert!(defs.contains("[^1]: Definition 1"));
    }

    #[test]
    fn test_body_paragraphs() {
        let content = "Paragraph 1\n\nParagraph 2\n\n[^1]: Definition";
        let paragraphs = body_paragraphs(content);
        assert_eq!(paragraphs.len(), 2);
        assert_eq!(paragraphs[0], "Paragraph 1");
        assert_eq!(paragraphs[1], "Paragraph 2");
    }

    #[test]
    fn test_looks_like_running_prose() {
        let long_prose = "This is a long paragraph that contains enough words and sentences to be considered running prose. It has more than 120 characters and multiple words that form coherent sentences.";
        assert!(looks_like_running_prose(long_prose));
        assert!(!looks_like_running_prose("Short text"));
    }

    #[test]
    fn test_file_title_from_content() {
        assert_eq!(file_title_from_content("# My Title\nContent"), "My Title");
        assert_eq!(file_title_from_content("Just content"), "Just content");
        assert_eq!(file_title_from_content(""), "");
    }

    #[test]
    fn test_detect_mid_paragraph_heading() {
        assert!(detect_mid_paragraph_heading(
            "Some text\n### Heading\nMore text"
        ));
        assert!(!detect_mid_paragraph_heading("### Heading\nMore text"));
    }

    #[test]
    fn test_duplicate_heading_count() {
        assert_eq!(duplicate_heading_count("### Title\n### Title"), 1);
        assert_eq!(duplicate_heading_count("### Title 1\n### Title 2"), 0);
    }

    #[test]
    fn test_add_issue() {
        let mut codes = Vec::new();
        let mut summary = Vec::new();
        add_issue(&mut codes, &mut summary, "test_code", "detail");
        assert_eq!(codes.len(), 1);
        assert_eq!(summary.len(), 1);
        // 不重复添加
        add_issue(&mut codes, &mut summary, "test_code", "other");
        assert_eq!(codes.len(), 1);
    }
}
