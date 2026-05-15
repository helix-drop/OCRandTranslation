//! ←→ FNM_RE/stages/chapter_skeleton/heading_candidates.py (827 行)
//! Heading candidate 收集与归一：OCR block 扫描 + font 特征 + family 推断。
//! 覆盖 F4 核心需求（family 推断 + reject 启发式 + top_band 判定）。

use fnm_core::records::HeadingCandidate;
use fnm_core::text::extract_page_headings;
use fnm_core::title::{guess_title_family, normalize_title};
use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::Value;

static TOC_NON_BODY_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:contents?|table(?:\s+of\s+contents)?|table des mati[eè]res|sommaire|illustrations?|list of illustrations|liste des illustrations|tables and maps|figures and tables|bibliograph(?:y|ie)?|references?|works cited|index|indices?|appendix|appendices|annex(?:es)?|glossary|note on sources|sources?|conventions|abbreviations?|list of abbreviations|liste des abr[eé]viations|acknowledg(?:e)?ments?|remerciements?|notes?(?:\s+to\b.*)?|endnotes?|back matter)\b"
    ).unwrap()
});

static TOC_PART_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:part|partie|livre|book|section)\s+(?:[ivxlcm]+|\d+)\b").unwrap()
});

static CHAPTER_KEYWORD_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)\b(?:chapter|chapitre|lecture|leçon|prologue|epilogue|postambule|appendix|appendices|part)\b").unwrap()
});

static MAIN_NUMBERED_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^(?:chapter\s+)?(?:\d+|[IVXLCMivxlcm]+)[\.\):\-]?\s+\S+").unwrap()
});

/// 从页面提取 heading candidates（扩展版，含 family 推断 + reject 启发式）。
pub fn extract_heading_candidates_from_page(
    page: &Value,
    page_no: i64,
    total_pages: i64,
    page_role: &str,
) -> Vec<HeadingCandidate> {
    let headings = extract_page_headings(page);
    let mut candidates = Vec::new();
    let body_roles = ["body", "front_matter"];

    for (i, h) in headings.iter().enumerate() {
        let normalized = normalize_title(h);
        if normalized.is_empty() {
            continue;
        }

        let family = infer_heading_family(&normalized, page_no, total_pages);

        // reject: 非 body/front_matter 页不产生 heading candidate
        let suppressed = !body_roles.contains(&page_role);

        let reject_reason = if is_non_body_title(&normalized) {
            "non_body_family"
        } else if suppressed {
            "partition_conflict"
        } else {
            ""
        };

        candidates.push(HeadingCandidate {
            heading_id: format!("hc-{}-{:03}", page_no, i + 1),
            page_no,
            text: h.clone(),
            normalized_text: normalized,
            source: "ocr_block".into(),
            block_label: "doc_title".into(),
            top_band: page_no <= 3,
            font_height: None,
            x: None,
            y: None,
            width_estimate: None,
            confidence: if family == "chapter" { 0.85 } else { 0.70 },
            heading_family_guess: family.to_string(),
            suppressed_as_chapter: suppressed,
            reject_reason: reject_reason.to_string(),
            font_name: String::new(),
            font_weight_hint: "unknown".into(),
            align_hint: "unknown".into(),
            width_ratio: None,
            heading_level_hint: if family == "chapter" { 1 } else { 2 },
        });
    }

    candidates
}

/// 推断 heading 的 family（chapter / section / note / other / unknown）。
fn infer_heading_family(title: &str, page_no: i64, total_pages: i64) -> &'static str {
    if TOC_NON_BODY_TITLE_RE.is_match(title) {
        return "other";
    }
    if TOC_PART_TITLE_RE.is_match(title) {
        return "chapter";
    }
    if CHAPTER_KEYWORD_RE.is_match(title) {
        return "chapter";
    }
    if MAIN_NUMBERED_TITLE_RE.is_match(title) {
        return "chapter";
    }
    // fallback: use guess_title_family from fnm-core
    let g = guess_title_family(title, page_no, total_pages);
    match g {
        "front_matter" => "front_matter",
        "body" => "section",
        "chapter" => "chapter",
        _ => "section",
    }
}

/// 判断标题是否为非正文内容（目录/插图/参考文献/索引等）。
fn is_non_body_title(title: &str) -> bool {
    TOC_NON_BODY_TITLE_RE.is_match(title)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn chapter_heading_family() {
        let page = json!({"markdown": "# Chapter 1: Introduction"});
        let candidates = extract_heading_candidates_from_page(&page, 1, 100, "body");
        assert_eq!(candidates.len(), 1);
        assert_eq!(candidates[0].heading_family_guess, "chapter");
    }

    #[test]
    fn non_body_title_rejected() {
        let page = json!({"markdown": "# Table of Contents"});
        let candidates = extract_heading_candidates_from_page(&page, 2, 100, "body");
        assert_eq!(candidates[0].heading_family_guess, "other");
    }

    #[test]
    fn non_body_page_suppressed() {
        let page = json!({"markdown": "# Chapter 1"});
        let candidates = extract_heading_candidates_from_page(&page, 4, 100, "note");
        assert!(candidates[0].suppressed_as_chapter);
        assert_eq!(candidates[0].reject_reason, "partition_conflict");
    }

    #[test]
    fn part_title_is_chapter() {
        let page = json!({"markdown": "# Part I"});
        let candidates = extract_heading_candidates_from_page(&page, 1, 100, "body");
        assert_eq!(candidates[0].heading_family_guess, "chapter");
    }
}
