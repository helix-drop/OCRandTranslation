//! ←→ FNM_RE/stages/_link_utils.py
//!
//! note_links 共享工具：anchor 搜索、候选合并、link 构造。

use fnm_core::records::BodyAnchorRecord;
use fnm_core::types::{AnchorKind, LinkResolver, LinkStatus, NoteKind};
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashSet;

// ── 章节类型判断 ─────────────────────────────────────────────────

/// ←→ Python `_is_fallback_chapter_id`
pub fn is_fallback_chapter_id(chapter_id: &str) -> bool {
    chapter_id.trim().starts_with("ch-fallback-")
}

/// ←→ Python `_is_toc_chapter_id`
pub fn is_toc_chapter_id(chapter_id: &str) -> bool {
    chapter_id.trim().starts_with("toc-ch-")
}

/// ←→ Python `_within_footnote_window`
pub fn within_footnote_window(anchor_page: i64, note_page: i64, max_distance: i64) -> bool {
    (anchor_page - note_page).abs() <= max_distance
}

// ── 候选 anchor 搜索 ────────────────────────────────────────────

/// 过滤条件，用于减少 `link_candidate_anchors` 参数数量。
#[derive(Clone, Copy)]
pub struct CandidateFilter<'a> {
    pub chapter_id: &'a str,
    pub marker: &'a str,
    pub expected_kinds: &'a [AnchorKind],
    pub used_anchor_ids: &'a HashSet<String>,
    pub page_no: Option<i64>,
    pub footnote_window: bool,
    pub include_synthetic: bool,
    pub allow_cross_chapter: bool,
}

/// 查找与给定 note_item 匹配的候选 anchors。
///
/// ←→ Python `link_candidate_anchors`
pub fn link_candidate_anchors<'a>(
    anchors: &'a [BodyAnchorRecord],
    filter: &CandidateFilter<'_>,
) -> Vec<&'a BodyAnchorRecord> {
    let normalized_marker = filter.marker.trim();
    let expected: HashSet<&str> = filter.expected_kinds.iter().map(|k| k.as_str()).collect();

    let mut candidates: Vec<&BodyAnchorRecord> = anchors
        .iter()
        .filter(|anchor| {
            if !filter.allow_cross_chapter && anchor.chapter_id != filter.chapter_id {
                return false;
            }
            if !filter.include_synthetic && anchor.synthetic {
                return false;
            }
            if filter.used_anchor_ids.contains(&anchor.anchor_id) {
                return false;
            }
            if anchor.normalized_marker.trim() != normalized_marker {
                return false;
            }
            if !expected.contains(anchor.anchor_kind.as_str()) {
                return false;
            }
            if filter.footnote_window {
                if let Some(pn) = filter.page_no {
                    if !within_footnote_window(anchor.page_no, pn, 1) {
                        return false;
                    }
                }
            }
            true
        })
        .collect();

    candidates.sort_by_key(|row| {
        let dist = match filter.page_no {
            Some(pn) => (row.page_no - pn).abs(),
            None => 0,
        };
        (dist, row.page_no, row.paragraph_index, row.char_start)
    });
    candidates
}

// ── 冗余候选折叠 ─────────────────────────────────────────────────

/// 折叠同一页上文本内容冗余的候选。
///
/// ←→ Python `_collapse_redundant_candidates`
pub fn collapse_redundant_candidates(candidates: Vec<&BodyAnchorRecord>) -> Vec<&BodyAnchorRecord> {
    if candidates.len() <= 1 {
        return candidates;
    }

    let mut kept: Vec<&BodyAnchorRecord> = Vec::new();
    for candidate in &candidates {
        let candidate_text = normalized_text(&candidate.source_text);
        let mut redundant = false;
        for other in &candidates {
            if other.anchor_id == candidate.anchor_id {
                continue;
            }
            if other.page_no != candidate.page_no {
                continue;
            }
            let other_text = normalized_text(&other.source_text);
            if candidate_text.is_empty() || other_text.is_empty() {
                continue;
            }
            if other_text == candidate_text && preference_key(other) < preference_key(candidate) {
                redundant = true;
                break;
            }
            if other_text.len() >= candidate_text.len() {
                continue;
            }
            if candidate_text.contains(&other_text) {
                redundant = true;
                break;
            }
        }
        if !redundant {
            kept.push(*candidate);
        }
    }
    if kept.is_empty() {
        candidates
    } else {
        kept
    }
}

// ── 最近唯一候选 ─────────────────────────────────────────────────

/// 在多个候选中找距离目标页最近且唯一的那个。
///
/// ←→ Python `_nearest_unique_candidate`
pub fn nearest_unique_candidate<'a>(
    candidates: &[&'a BodyAnchorRecord],
    target_page: i64,
) -> Option<&'a BodyAnchorRecord> {
    if candidates.is_empty() {
        return None;
    }
    if candidates.len() == 1 {
        return Some(candidates[0]);
    }
    let min_distance = candidates
        .iter()
        .map(|row| (row.page_no - target_page).abs())
        .min()
        .unwrap_or(0);
    let nearest: Vec<_> = candidates
        .iter()
        .filter(|row| (row.page_no - target_page).abs() == min_distance)
        .copied()
        .collect();
    if nearest.len() == 1 {
        Some(nearest[0])
    } else {
        None
    }
}

// ── Link 构造 ──────────────────────────────────────────────────

/// 构造 NoteLinkRecord 所需的参数。
pub struct NewLinkParams<'a> {
    pub serial: usize,
    pub chapter_id: &'a str,
    pub region_id: &'a str,
    pub note_item_id: &'a str,
    pub anchor_id: &'a str,
    pub status: LinkStatus,
    pub resolver: LinkResolver,
    pub confidence: f64,
    pub note_kind: NoteKind,
    pub marker: &'a str,
    pub page_no_start: i64,
    pub page_no_end: i64,
}

/// 构造 NoteLinkRecord。
///
/// ←→ Python `link_new_link`
pub fn link_new_link(params: &NewLinkParams<'_>) -> fnm_core::records::NoteLinkRecord {
    fnm_core::records::NoteLinkRecord {
        link_id: format!("link-{0:05}", params.serial),
        chapter_id: params.chapter_id.to_string(),
        region_id: params.region_id.to_string(),
        note_item_id: params.note_item_id.to_string(),
        anchor_id: params.anchor_id.to_string(),
        status: params.status,
        resolver: params.resolver,
        confidence: params.confidence,
        note_kind: params.note_kind,
        marker: params.marker.to_string(),
        page_no_start: params.page_no_start,
        page_no_end: params.page_no_end,
    }
}

// ── 内部辅助 ────────────────────────────────────────────────────

static HTML_TAG_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"<[^>]+>").unwrap());

fn normalized_text(text: &str) -> String {
    let mut s = HTML_TAG_RE.replace_all(text, " ").to_string();
    s = s.replace("&nbsp;", " ");
    s.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim()
        .to_string()
}

fn preference_key(row: &BodyAnchorRecord) -> (usize, usize, i32, i64, i64, i64) {
    let source = &row.source;
    (
        normalized_text(&row.source_text).len(),
        row.source_text.len(),
        if source.starts_with("ocr_block") {
            0
        } else {
            1
        },
        0,
        row.paragraph_index,
        row.char_start,
    )
}
