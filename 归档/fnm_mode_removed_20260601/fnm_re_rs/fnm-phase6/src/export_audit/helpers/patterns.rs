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
pub(crate) static _UNICODE_SUPERSCRIPT_TRANSLATION: Lazy<HashMap<char, char>> = Lazy::new(|| {
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
