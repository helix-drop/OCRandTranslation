//! ←→ FNM_RE/shared/title.py
//! 标题规范化与分类工具。

use once_cell::sync::Lazy;
use regex::Regex;
use unicode_normalization::UnicodeNormalization;

static TITLE_KEY_CLEAN_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^0-9a-zà-ÿ]+").unwrap());
static TITLE_PREFIX_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:\d+|[ivxlcdm]+)[\.\)]\s*").unwrap());
static TITLE_LABEL_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:chapter|chapitre|part|section)\b[:\s\-]*").unwrap());

type PatternGroup<'a> = (&'a str, &'a [&'a str]);

static OTHER_TITLE_PATTERNS: Lazy<Vec<PatternGroup>> = Lazy::new(|| {
    vec![
        (
            "contents",
            &[
                r"^contents\b",
                r"^table of contents$",
                r"^table$",
                r"^table des mati[eè]res$",
                r"^sommaire$",
            ][..],
        ),
        (
            "illustrations",
            &[
                r"^illustrations?$",
                r"^list of illustrations$",
                r"^list of figures$",
                r"^liste des illustrations?$",
                r"^liste des figures?$",
                r"^tables and maps$",
                r"^tables$",
                r"^figures and tables$",
                r"^figures$",
            ][..],
        ),
        (
            "bibliography",
            &[
                r"^bibliograph",
                r"^references?$",
                r"^works cited$",
                r"^livres et articles\b",
            ][..],
        ),
        ("index", &[r"^index\b", r"^indices?\b"][..]),
        (
            "appendix",
            &[
                r"^appendix\b",
                r"^appendices$",
                r"^annex",
                r"^glossary$",
                r"^note on sources$",
                r"^sources?$",
                r"^conventions$",
                r"^abbreviations?$",
            ][..],
        ),
        (
            "front_matter",
            &[
                r"^acknowledg",
                r"^remerciement",
                r"^foreword$",
                r"^preface$",
                r"^avant-propos$",
                r"^avertissement$",
                r"^abstract$",
                r"^introduction$",
            ][..],
        ),
    ]
});

/// 规范化标题：压缩连续空白。与 Python `normalize_title` 一致。
pub fn normalize_title(value: &str) -> String {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    let re = Regex::new(r"\s+").unwrap();
    re.replace_all(trimmed, " ").to_string()
}

/// 生成标题的归一化键（用于比对）。NFKD 归一化 + 去重音 + 去非字母数字。
/// 与 Python `normalized_title_key` 一致。
pub fn normalized_title_key(value: &str) -> String {
    let normalized = normalize_title(value).to_lowercase();
    let nfkd: String = normalized.nfkd().collect();
    // 去除 combining marks（重音符号等）
    let folded: String = nfkd.chars().filter(|c| !is_combining_mark(*c)).collect();
    TITLE_KEY_CLEAN_RE.replace_all(&folded, "").to_string()
}

/// 生成章节标题匹配键：去掉 title label/prefix 后再归一。
/// 与 Python `chapter_title_match_key` 一致。
pub fn chapter_title_match_key(value: &str) -> String {
    let normalized = normalize_title(value).to_lowercase();
    let normalized = TITLE_LABEL_RE.replace(&normalized, "").to_string();
    let normalized = TITLE_PREFIX_RE.replace(&normalized, "").to_string();
    TITLE_KEY_CLEAN_RE.replace(&normalized, "").to_string()
}

/// 根据标题文本推断所属 family（contents / illustrations / bibliography / index /
/// appendix / front_matter / body）。
/// 与 Python `guess_title_family` 一致。
pub fn guess_title_family(value: &str, page_no: i64, total_pages: i64) -> &'static str {
    let safe_page_no = page_no.max(1);
    let safe_total_pages = total_pages.max(1);
    let lowered = normalize_title(value).to_lowercase();
    for (family, patterns) in OTHER_TITLE_PATTERNS.iter() {
        for pattern in *patterns {
            if Regex::new(pattern)
                .ok()
                .and_then(|re| re.find(&lowered))
                .is_some()
            {
                return family;
            }
        }
    }
    if safe_page_no <= (12).max(safe_total_pages * 8 / 100) && lowered == "introduction" {
        return "front_matter";
    }
    "body"
}

fn is_combining_mark(c: char) -> bool {
    // Unicode combining marks: U+0300–U+036F, U+1AB0–U+1AFF, U+1DC0–U+1DFF,
    // U+20D0–U+20FF, U+FE20–U+FE2F
    matches!(
        c,
        '\u{0300}'..='\u{036F}'
            | '\u{1AB0}'..='\u{1AFF}'
            | '\u{1DC0}'..='\u{1DFF}'
            | '\u{20D0}'..='\u{20FF}'
            | '\u{FE20}'..='\u{FE2F}'
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_basic() {
        assert_eq!(normalize_title("  Hello   World  "), "Hello World");
        assert_eq!(normalize_title(""), "");
        assert_eq!(normalize_title("Single"), "Single");
    }

    #[test]
    fn normalized_key_removes_accents() {
        let key = normalized_title_key("Préface");
        assert_eq!(key, "preface");
    }

    #[test]
    fn chapter_match_key() {
        let key = chapter_title_match_key("Chapter 1: Introduction");
        assert_eq!(key, "1introduction");
    }

    #[test]
    fn guess_front_matter() {
        assert_eq!(guess_title_family("Introduction", 1, 100), "front_matter");
    }

    #[test]
    fn guess_body() {
        assert_eq!(guess_title_family("The History", 50, 100), "body");
    }
}
