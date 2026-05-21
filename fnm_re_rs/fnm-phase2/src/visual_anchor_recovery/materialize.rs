//! ←→ FNM_RE/modules/visual_anchor_recovery.py
//! `_materialize_visual_findings` + `_fuzzy_find_phrase_in_page` 完整 port。
//!
//! 把 VLM 返回的 findings 转为 BodyAnchorRecord，通过 anchor_phrase 模糊匹配
//! 在页面 markdown 中定位（para_index, char_start, char_end）。

use super::parsing::{
    int_to_unicode_superscript, next_visual_anchor_id, sanitize_anchor_phrase,
    simple_substring_similarity,
};
use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::BodyAnchorRecord;
use fnm_core::types::AnchorKind;
use fnm_phase1::input::RawPage;
use serde_json::Value;
use std::collections::{HashMap, HashSet};

const VISUAL_RECOVERY_ANCHOR_CERTAINTY: f64 = 0.65;
const PHRASE_MIN_SIMILARITY: f64 = 0.50;

/// 单章 anchor gap 描述。
#[derive(Debug, Clone)]
pub struct ChapterAnchorGap {
    pub chapter_id: String,
    pub missing_markers: HashSet<i64>,
    pub body_page_range: (i64, i64),
}

/// ←→ Python `_fuzzy_find_phrase_in_page`
/// 在页面 markdown / blocks 中模糊匹配 phrase，返回 (para_index, char_start, char_end)。
pub fn fuzzy_find_phrase_in_page(phrase: &str, page: &RawPage) -> Option<(i64, usize, usize)> {
    let phrase_clean = phrase.trim();
    if phrase_clean.is_empty() {
        return None;
    }
    // 收集文本源
    let mut sources: Vec<(i64, String)> = Vec::new();
    if !page.markdown.is_empty() {
        sources.push((0, page.markdown.clone()));
    }
    if let Some(enriched) = &page.enriched_markdown {
        if !enriched.is_empty() {
            sources.push((0, enriched.clone()));
        }
    }
    // blocks
    let page_val = serde_json::to_value(page).unwrap_or_default();
    if let Some(blocks) = page_val.get("blocks").and_then(|v| v.as_array()) {
        for (idx, block) in blocks.iter().enumerate() {
            if let Some(text) = block.get("text").and_then(|v| v.as_str()) {
                if !text.trim().is_empty() {
                    sources.push((idx as i64, text.to_string()));
                }
            }
        }
    }
    // 模糊匹配
    for (para_idx, text) in &sources {
        let similarity = simple_substring_similarity(phrase_clean, text);
        if similarity < PHRASE_MIN_SIMILARITY {
            continue;
        }
        if let Some((start, end)) = best_window_in_text(text, phrase_clean) {
            return Some((*para_idx, start, end));
        }
    }
    None
}

fn best_window_in_text(text: &str, pattern: &str) -> Option<(usize, usize)> {
    let p_chars: Vec<char> = pattern.chars().collect();
    let t_chars: Vec<char> = text.chars().collect();
    let pw = p_chars.len();
    if pw == 0 || pw > t_chars.len() {
        return None;
    }
    let mut best_dist = pw + 1;
    let mut best_start = 0usize;
    for start in 0..=(t_chars.len() - pw) {
        let dist = (0..pw)
            .filter(|&i| p_chars[i] != t_chars[start + i])
            .count();
        if dist < best_dist {
            best_dist = dist;
            best_start = start;
            if best_dist == 0 {
                break;
            }
        }
    }
    // 转字符位置为字节位置（保持 UTF-8 安全）
    let prefix: String = t_chars.iter().take(best_start).collect();
    let window: String = t_chars.iter().skip(best_start).take(pw).collect();
    let byte_start = prefix.len();
    let byte_end = byte_start + window.len();
    Some((byte_start, byte_end))
}

/// ←→ Python `_materialize_visual_findings`
pub fn materialize_visual_findings(
    findings: &[Value],
    gap: &ChapterAnchorGap,
    page_by_no: &HashMap<i64, &RawPage>,
    candidate_pages: &[i64],
) -> (Vec<BodyAnchorRecord>, MaterializationSummary) {
    let mut anchors: Vec<BodyAnchorRecord> = Vec::new();
    let mut seen_markers: HashSet<i64> = HashSet::new();
    let mut found = 0usize;
    let mut mapped = 0usize;
    let mut match_failed = 0usize;

    let allowed_pages: Vec<i64> = candidate_pages.iter().copied().filter(|&p| p > 0).collect();

    for item in findings {
        let marker = item
            .get("marker")
            .and_then(|v| v.as_i64())
            .unwrap_or_else(|| {
                item.get("marker")
                    .and_then(|v| v.as_str())
                    .and_then(|s| s.parse::<i64>().ok())
                    .unwrap_or(0)
            });
        if marker <= 0 || !gap.missing_markers.contains(&marker) || seen_markers.contains(&marker) {
            continue;
        }
        seen_markers.insert(marker);
        found += 1;

        let anchor_phrase = sanitize_anchor_phrase(
            item.get("anchor_phrase")
                .and_then(|v| v.as_str())
                .unwrap_or(""),
        );
        let mut source_marker = item
            .get("source_marker")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if source_marker.is_empty() {
            source_marker = int_to_unicode_superscript(marker);
        }

        let page_no = item.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);

        let mut search_pages: Vec<i64> = Vec::new();
        if page_no > 0 && (allowed_pages.is_empty() || allowed_pages.contains(&page_no)) {
            search_pages.push(page_no);
        }
        for &cp in &allowed_pages {
            if !search_pages.contains(&cp) {
                search_pages.push(cp);
            }
        }
        if search_pages.is_empty() && gap.body_page_range.0 > 0 {
            search_pages.push(gap.body_page_range.0);
        }

        let mut para_index: i64 = 0;
        let mut char_start: usize = 0;
        let mut char_end: usize = 0;
        let mut resolved_page_no = if page_no > 0 { page_no } else { 0 };

        if anchor_phrase.is_empty() {
            match_failed += 1;
            continue;
        }

        let mut located = false;
        for &sp in &search_pages {
            if let Some(page) = page_by_no.get(&sp) {
                if let Some((pidx, cs, ce)) = fuzzy_find_phrase_in_page(&anchor_phrase, page) {
                    para_index = pidx;
                    char_start = ce; // anchor 位于 phrase 之后
                    char_end = char_start + source_marker.len();
                    resolved_page_no = sp;
                    mapped += 1;
                    let _ = cs;
                    located = true;
                    break;
                }
            }
        }
        if !located {
            match_failed += 1;
            continue;
        }

        let normalized_marker = normalize_note_marker(&marker.to_string());
        anchors.push(BodyAnchorRecord {
            anchor_id: next_visual_anchor_id(),
            chapter_id: gap.chapter_id.clone(),
            page_no: if resolved_page_no > 0 {
                resolved_page_no
            } else {
                gap.body_page_range.0
            },
            paragraph_index: para_index,
            char_start: char_start as i64,
            char_end: char_end as i64,
            source_marker,
            normalized_marker,
            anchor_kind: AnchorKind::Endnote,
            certainty: VISUAL_RECOVERY_ANCHOR_CERTAINTY,
            source_text: anchor_phrase,
            source: "visual_repair".into(),
            synthetic: false,
            ocr_repaired_from_marker: String::new(),
        });
    }

    let summary = MaterializationSummary {
        found,
        mapped,
        match_failed,
        total_anchors: anchors.len(),
    };
    (anchors, summary)
}

#[derive(Debug, Clone, Default)]
pub struct MaterializationSummary {
    pub found: usize,
    pub mapped: usize,
    pub match_failed: usize,
    pub total_anchors: usize,
}

impl MaterializationSummary {
    pub fn to_json(&self) -> Value {
        serde_json::json!({
            "found": self.found,
            "mapped": self.mapped,
            "match_failed": self.match_failed,
            "total_anchors": self.total_anchors,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn make_page(book_page: i64, markdown: &str) -> RawPage {
        RawPage {
            book_page,
            markdown: markdown.into(),
            ..Default::default()
        }
    }

    #[test]
    fn fuzzy_find_returns_position() {
        let page = make_page(10, "intelligibilité de ce processus");
        let result = fuzzy_find_phrase_in_page("intelligibilité", &page);
        assert!(result.is_some());
        let (pidx, cs, ce) = result.unwrap();
        assert_eq!(pidx, 0);
        assert!(ce > cs);
    }

    #[test]
    fn fuzzy_find_empty_phrase_returns_none() {
        let page = make_page(10, "text");
        assert!(fuzzy_find_phrase_in_page("", &page).is_none());
    }

    #[test]
    fn materialize_skips_unwanted_markers() {
        let pages: HashMap<i64, &RawPage> = HashMap::new();
        let mut missing = HashSet::new();
        missing.insert(8i64);
        let gap = ChapterAnchorGap {
            chapter_id: "ch-1".into(),
            missing_markers: missing,
            body_page_range: (10, 20),
        };
        let findings = vec![json!({
            "marker": 99,
            "page_no": 15,
            "anchor_phrase": "phrase",
            "source_marker": "⁹⁹"
        })];
        let (anchors, summary) = materialize_visual_findings(&findings, &gap, &pages, &[]);
        assert!(anchors.is_empty());
        assert_eq!(summary.found, 0);
    }

    #[test]
    fn materialize_locates_phrase_and_creates_anchor() {
        let page = make_page(15, "the intelligibilité of the process");
        let mut pages: HashMap<i64, &RawPage> = HashMap::new();
        pages.insert(15, &page);
        let mut missing = HashSet::new();
        missing.insert(8i64);
        let gap = ChapterAnchorGap {
            chapter_id: "ch-1".into(),
            missing_markers: missing,
            body_page_range: (10, 20),
        };
        let findings = vec![json!({
            "marker": 8,
            "page_no": 15,
            "anchor_phrase": "intelligibilité",
            "source_marker": "⁸"
        })];
        let (anchors, summary) = materialize_visual_findings(&findings, &gap, &pages, &[15]);
        assert_eq!(anchors.len(), 1);
        assert_eq!(summary.found, 1);
        assert_eq!(summary.mapped, 1);
        assert_eq!(anchors[0].chapter_id, "ch-1");
        assert_eq!(anchors[0].normalized_marker, "8");
        assert_eq!(anchors[0].source, "visual_repair");
        assert_eq!(anchors[0].anchor_kind, AnchorKind::Endnote);
    }

    #[test]
    fn materialize_missing_phrase_counts_as_failure() {
        let page = make_page(15, "no match here");
        let mut pages: HashMap<i64, &RawPage> = HashMap::new();
        pages.insert(15, &page);
        let mut missing = HashSet::new();
        missing.insert(8i64);
        let gap = ChapterAnchorGap {
            chapter_id: "ch-1".into(),
            missing_markers: missing,
            body_page_range: (10, 20),
        };
        let findings = vec![json!({
            "marker": 8,
            "page_no": 15,
            "anchor_phrase": "intelligibilité",
        })];
        let (anchors, summary) = materialize_visual_findings(&findings, &gap, &pages, &[15]);
        assert!(anchors.is_empty());
        assert_eq!(summary.match_failed, 1);
    }
}
