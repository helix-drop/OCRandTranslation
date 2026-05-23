//! `body_anchors` — body anchor 检测模块。
//!
//! ←→ Python: FNM_RE/stages/body_anchors.py + FNM_RE/shared/anchors.py

pub mod chapter_marker_sets;
pub mod context_guard;
pub mod gap_recovery;
pub mod pattern_scan;

use fnm_core::{
    anchor_kind::resolve_anchor_kind,
    records::{
        BodyAnchorRecord, ChapterRecord, NoteItemRecord, NoteRegionRecord, PagePartitionRecord,
    },
    types::AnchorKind,
};
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::{HashMap, HashSet};

// 与 Python `_NOTE_DEFINITION_LINE_RE` 对应：过滤 note 定义行。
static NOTE_DEFINITION_LINE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:\[\d{1,4}\]|\d{1,4}[\.\)\]]|\d{1,4}\s{1,3}|<sup>\s*\d{1,4}\s*</sup>|\$\s*\^\{\d{1,4}\}\s*\$|\^\{\d{1,4}\}|[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,4})\s*\S+").unwrap()
});

/// BodyAnchor 模块级摘要。
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct BodyAnchorSummary {
    pub total_count: usize,
    pub explicit_count: usize,
    pub synthetic_count: usize,
    pub kind_counts: HashMap<String, usize>,
    pub uncertain_count: usize,
    pub ocr_repaired_count: usize,
    pub year_like_filtered_count: usize,
    /// 需 LLM 二次验证的 bare_digit 候选数（原丢弃，现记录）。
    pub llm_candidate_count: usize,
}

/// 构建 body anchors。
///
/// ←→ Python `FNM_RE/stages/body_anchors.py:build_body_anchors`
pub fn build_body_anchors(
    chapters: &[ChapterRecord],
    pages: &[PagePartitionRecord],
    note_regions: &[NoteRegionRecord],
    note_items: &[NoteItemRecord],
    raw_pages: &[RawPage],
) -> (Vec<BodyAnchorRecord>, BodyAnchorSummary) {
    let page_text_by_no: HashMap<i64, String> = raw_pages
        .iter()
        .map(|p| {
            let text = p
                .enriched_markdown
                .as_ref()
                .filter(|s| !s.trim().is_empty())
                .unwrap_or(&p.markdown)
                .clone();
            (p.book_page, text)
        })
        .collect();

    let page_role_by_no: HashMap<i64, String> = pages
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str().to_string()))
        .collect();

    let footnote_band_pages = chapter_marker_sets::footnote_band_page_keys(note_regions);
    let chapter_marker_range = chapter_marker_sets::build_chapter_marker_range(note_items);
    let chapter_endnote_markers =
        chapter_marker_sets::build_chapter_endnote_marker_set(note_regions, note_items);
    let chapter_note_items = chapter_marker_sets::build_chapter_note_items_set(note_items);

    let mut anchors: Vec<BodyAnchorRecord> = Vec::new();
    let mut seen: HashSet<(String, String, String, i64, i64, i64, i64)> = HashSet::new();
    let mut seen_bare: HashSet<(String, String, String, i64)> = HashSet::new();
    let mut anchor_counter: usize = 0;
    let mut year_like_filtered_total: usize = 0;

    let body_anchor_roles: HashSet<&str> = [
        "body",
        "chapter",
        "front_matter",
        "back_matter",
        "post_body",
        "",
    ]
    .iter()
    .copied()
    .collect();

    // 按 page_no 排序遍历
    let mut sorted_pages: Vec<i64> = page_text_by_no.keys().copied().collect();
    sorted_pages.sort();

    for page_no in sorted_pages {
        let role = page_role_by_no
            .get(&page_no)
            .map(|s| s.as_str())
            .unwrap_or("");
        if !body_anchor_roles.contains(role) {
            continue;
        }
        let text = page_text_by_no
            .get(&page_no)
            .map(|s| s.as_str())
            .unwrap_or("");
        if text.trim().is_empty() {
            continue;
        }

        // 查找 page_no 对应的 chapter_id
        let chapter_id = find_chapter_id_for_page(chapters, page_no);
        if chapter_id.is_empty() {
            continue;
        }

        let (marker_min, marker_max) = chapter_marker_range
            .get(&chapter_id)
            .copied()
            .unwrap_or((0, 0));
        let is_footnote_page = footnote_band_pages.contains(&(chapter_id.clone(), page_no));

        let text = filter_note_definition_lines(text);
        let (refs, year_like_filtered) = pattern_scan::scan_anchor_markers(&text);
        year_like_filtered_total += year_like_filtered;

        for r#ref in refs {
            let pattern = r#ref.pattern.as_str();
            let marker = r#ref.normalized_marker.as_str();
            if marker.is_empty() {
                continue;
            }
            if !marker_in_expected_range(marker, pattern, marker_min, marker_max, is_footnote_page)
            {
                continue;
            }

            // 去重 key
            if pattern == "bare_digit" {
                let key = (
                    pattern.to_string(),
                    marker.to_string(),
                    chapter_id.clone(),
                    page_no,
                );
                if !seen_bare.insert(key) {
                    continue;
                }
            } else {
                let key = (
                    pattern.to_string(),
                    marker.to_string(),
                    chapter_id.clone(),
                    page_no,
                    0i64,
                    r#ref.char_start as i64,
                    r#ref.char_end as i64,
                );
                if !seen.insert(key) {
                    continue;
                }
            }

            anchor_counter += 1;
            let anchor_id = format!("anchor-{anchor_counter:05}");
            let ch_endnote_set = chapter_endnote_markers.get(&chapter_id);
            let anchor_kind =
                resolve_anchor_kind(is_footnote_page, marker, ch_endnote_set, pattern);

            anchors.push(BodyAnchorRecord {
                anchor_id,
                chapter_id: chapter_id.clone(),
                page_no,
                paragraph_index: 0,
                char_start: r#ref.char_start as i64,
                char_end: r#ref.char_end as i64,
                source_marker: r#ref.source_marker.clone(),
                normalized_marker: marker.to_string(),
                anchor_kind,
                certainty: r#ref.certainty,
                source_text: text.to_string(),
                source: format!("markdown:{pattern}"),
                synthetic: false,
                ocr_repaired_from_marker: String::new(),
            });
        }
    }

    // bare_digit 正向门
    let (mut anchors, llm_candidates) =
        context_guard::positive_gate_bare_digit(&anchors, &chapter_note_items);
    let llm_candidate_count = llm_candidates.len();

    // gap recovery：传入每章的页面范围，确保 recovery 不跨章（铁律 §4）。
    let chapter_pages: HashMap<String, HashSet<i64>> = chapters
        .iter()
        .map(|ch| {
            let pages: HashSet<i64> = ch.pages.iter().copied().collect();
            (ch.chapter_id.clone(), pages)
        })
        .collect();
    let mut seen_gap: HashSet<(String, String, i64)> = HashSet::new();
    gap_recovery::recover_expected_gap_bare_digit_anchors(
        &mut anchors,
        note_items,
        &page_text_by_no,
        &chapter_endnote_markers,
        &mut seen_gap,
        &mut anchor_counter,
        &chapter_pages,
    );
    gap_recovery::recover_expected_gap_symbol_anchors(
        &mut anchors,
        note_items,
        &page_text_by_no,
        &mut seen_gap,
        &mut anchor_counter,
        &chapter_pages,
    );

    let summary = build_summary(&anchors, year_like_filtered_total, llm_candidate_count);
    (anchors, summary)
}

// ── 内部辅助 ────────────────────────────────────────────────────

fn find_chapter_id_for_page(chapters: &[ChapterRecord], page_no: i64) -> String {
    chapters
        .iter()
        .find(|ch| ch.pages.contains(&page_no))
        .map(|ch| ch.chapter_id.clone())
        .unwrap_or_default()
}

fn marker_in_expected_range(
    normalized_marker: &str,
    pattern: &str,
    marker_min: i64,
    marker_max: i64,
    has_page_footnote_band: bool,
) -> bool {
    if has_page_footnote_band {
        return true;
    }
    if marker_max <= 0 {
        return true;
    }
    let marker_val: i64 = match normalized_marker.parse() {
        Ok(v) => v,
        Err(_) => return true,
    };
    let strong_patterns = [
        "latex",
        "latex_symbol_sup",
        "plain",
        "html",
        "unicode",
        "footnote_ref",
        "apostrophe_sup",
    ];
    if strong_patterns.contains(&pattern) {
        return true;
    }
    if pattern == "bare_digit" {
        return marker_min <= marker_val && marker_val <= marker_max;
    }
    let tolerance = (marker_max as f64 * 0.03).max(3.0) as i64;
    marker_min <= marker_val && marker_val <= marker_max + tolerance
}

fn filter_note_definition_lines(text: &str) -> String {
    text.lines()
        .filter(|line| !NOTE_DEFINITION_LINE_RE.is_match(line.trim()))
        .collect::<Vec<_>>()
        .join("\n")
}

fn build_summary(
    anchors: &[BodyAnchorRecord],
    year_like_filtered: usize,
    llm_candidate_count: usize,
) -> BodyAnchorSummary {
    let mut kind_counts: HashMap<String, usize> = HashMap::new();
    let mut explicit_count = 0usize;
    let mut synthetic_count = 0usize;
    let mut uncertain_count = 0usize;
    let mut ocr_repaired_count = 0usize;

    for anchor in anchors {
        let kind = anchor.anchor_kind.as_str();
        *kind_counts.entry(kind.to_string()).or_insert(0) += 1;
        if !anchor.synthetic {
            explicit_count += 1;
        } else {
            synthetic_count += 1;
        }
        if anchor.anchor_kind == AnchorKind::Unknown || anchor.certainty < 1.0 {
            uncertain_count += 1;
        }
        if !anchor.ocr_repaired_from_marker.trim().is_empty() {
            ocr_repaired_count += 1;
        }
    }

    BodyAnchorSummary {
        total_count: anchors.len(),
        explicit_count,
        synthetic_count,
        kind_counts,
        uncertain_count,
        ocr_repaired_count,
        year_like_filtered_count: year_like_filtered,
        llm_candidate_count,
    }
}
