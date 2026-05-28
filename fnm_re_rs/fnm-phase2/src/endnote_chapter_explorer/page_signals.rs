//! 页面信号收集：标题候选加分 + 信号候选收集 + TOC 子条目匹配。
//!
//! ←→ Python `endnote_chapter_explorer.py` 中的 `_yield_page_signal_candidates` / `_toc_page_signal_candidates`

use fnm_core::records::{HeadingCandidate, Phase1Structure};
use fnm_core::text::extract_page_headings;
use fnm_core::title::normalize_title;
use fnm_phase1::input::RawPage;
use serde_json::Value;
use std::collections::{HashMap, HashSet};

use super::matching::{match_toc_subentry_to_chapter, ChapterRow};
use super::numbering::is_generic_notes_title;

/// ←→ Python `_heading_candidate_style_bonus`
pub(super) fn heading_candidate_style_bonus(candidate: &HeadingCandidate) -> f64 {
    let mut bonus: f64 = 0.0;
    if candidate.top_band {
        bonus += 0.08;
    }
    if candidate.heading_level_hint == 1 {
        bonus += 0.08;
    } else if candidate.heading_level_hint >= 2 {
        bonus += 0.04;
    }
    match candidate.font_weight_hint.as_str() {
        "heavy" => bonus += 0.08,
        "bold" => bonus += 0.05,
        _ => {}
    }
    if candidate.align_hint == "center" {
        bonus += 0.05;
    }
    if let Some(h) = candidate.font_height {
        if h >= 24.0 {
            bonus += 0.04;
        } else if h >= 18.0 {
            bonus += 0.02;
        }
    }
    if candidate.source == "pdf_font_band" {
        bonus += 0.04;
    }
    bonus.min(0.28)
}

pub(super) fn heading_candidates_by_page(
    phase1: &Phase1Structure,
) -> HashMap<i64, Vec<HeadingCandidate>> {
    let mut mapped: HashMap<i64, Vec<HeadingCandidate>> = HashMap::new();
    for candidate in &phase1.heading_candidates {
        let page_no = candidate.page_no;
        if page_no <= 0 {
            continue;
        }
        mapped.entry(page_no).or_default().push(candidate.clone());
    }
    for (_pn, list) in mapped.iter_mut() {
        list.sort_by(|a, b| {
            // top_band False 排后；level_hint 大优先；heavy > bold；confidence 大优先
            let key_a = (
                !a.top_band,
                -(a.heading_level_hint),
                if a.font_weight_hint == "heavy" {
                    -1i32
                } else {
                    0
                },
                if a.font_weight_hint == "bold" {
                    -1i32
                } else {
                    0
                },
                -((a.confidence * 1_000.0) as i64),
            );
            let key_b = (
                !b.top_band,
                -(b.heading_level_hint),
                if b.font_weight_hint == "heavy" {
                    -1i32
                } else {
                    0
                },
                if b.font_weight_hint == "bold" {
                    -1i32
                } else {
                    0
                },
                -((b.confidence * 1_000.0) as i64),
            );
            key_a.cmp(&key_b)
        });
    }
    mapped
}

/// ←→ Python `_yield_page_signal_candidates`
pub(super) fn yield_page_signal_candidates(
    page_no: i64,
    page: Option<&RawPage>,
    hcbp: &HashMap<i64, Vec<HeadingCandidate>>,
) -> Vec<(String, String, f64)> {
    let mut yielded: Vec<(String, String, f64)> = Vec::new();
    let mut seen: HashSet<(String, String)> = HashSet::new();

    let push = |yielded: &mut Vec<(String, String, f64)>,
                seen: &mut HashSet<(String, String)>,
                title: &str,
                source: &str,
                bonus: f64| {
        let normalized = normalize_title(title);
        if normalized.is_empty() || is_generic_notes_title(&normalized) {
            return;
        }
        let key = (source.to_string(), normalized.to_lowercase());
        if seen.contains(&key) {
            return;
        }
        seen.insert(key);
        yielded.push((normalized, source.to_string(), bonus));
    };

    // 1. note_scan items endnote section_title
    if let Some(p) = page {
        if let Some(ns) = &p.note_scan {
            if let Some(items) = ns.get("items").and_then(|v| v.as_array()) {
                for item in items {
                    let kind = item
                        .get("kind")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .trim()
                        .to_lowercase();
                    if kind != "endnote" {
                        continue;
                    }
                    let st = item
                        .get("section_title")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    push(&mut yielded, &mut seen, st, "note_section_title", 0.38);
                }
            }
            if let Some(hints) = ns.get("section_hints").and_then(|v| v.as_array()) {
                for hint in hints {
                    if let Some(s) = hint.as_str() {
                        push(&mut yielded, &mut seen, s, "note_section_hint", 0.30);
                    }
                }
            }
        }

        // page_heading from prunedResult
        let headings = extract_page_headings(&p.pruned_result);
        for heading in &headings {
            push(&mut yielded, &mut seen, heading, "page_heading", 0.26);
        }
    }

    // 4. heading_candidates_by_page
    if let Some(candidates) = hcbp.get(&page_no) {
        for candidate in candidates {
            if candidate.suppressed_as_chapter {
                continue;
            }
            let reject = candidate.reject_reason.trim();
            if !reject.is_empty() && reject != "section_candidate" {
                continue;
            }
            push(
                &mut yielded,
                &mut seen,
                &candidate.text,
                "heading_candidate",
                0.22 + heading_candidate_style_bonus(candidate),
            );
        }
    }

    yielded
}

// ── TOC subentry hints ──────────────────────────────────────────

fn toc_subentries_for_page(page_no: i64, endnote_explorer_hints: Option<&Value>) -> Vec<Value> {
    let hints = match endnote_explorer_hints {
        Some(v) => v,
        None => return Vec::new(),
    };
    let endnotes_summary = hints
        .get("endnotes_summary")
        .cloned()
        .unwrap_or(Value::Null);
    let present = endnotes_summary
        .get("present")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    if !present {
        return Vec::new();
    }
    let container_start = hints
        .get("container_start_page_hint")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    if container_start > 0 && page_no < container_start {
        return Vec::new();
    }
    let raw_subentries = hints
        .get("toc_subentries")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut subentries: Vec<Value> = raw_subentries
        .into_iter()
        .filter(|row| {
            row.get("printed_page")
                .and_then(|v| v.as_i64())
                .unwrap_or(0)
                > 0
        })
        .collect();
    if subentries.is_empty() {
        return Vec::new();
    }
    subentries.sort_by_key(|row| {
        (
            row.get("printed_page")
                .and_then(|v| v.as_i64())
                .unwrap_or(0),
            row.get("visual_order")
                .and_then(|v| v.as_i64())
                .unwrap_or(0),
        )
    });
    let mut active_index: i64 = -1;
    for (idx, row) in subentries.iter().enumerate() {
        let pp = row
            .get("printed_page")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        if pp <= page_no {
            active_index = idx as i64;
        } else {
            break;
        }
    }
    if active_index < 0 {
        return Vec::new();
    }
    let active_printed_page = subentries[active_index as usize]
        .get("printed_page")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    subentries
        .into_iter()
        .filter(|row| {
            row.get("printed_page")
                .and_then(|v| v.as_i64())
                .unwrap_or(0)
                == active_printed_page
        })
        .collect()
}

use super::matching::PageChapterSignal;

pub(super) fn toc_page_signal_candidates(
    page_no: i64,
    chapters: &[ChapterRow],
    endnote_explorer_hints: Option<&Value>,
) -> Vec<PageChapterSignal> {
    let mut ranked: Vec<PageChapterSignal> = Vec::new();
    for subentry in toc_subentries_for_page(page_no, endnote_explorer_hints) {
        if let Some(matched) = match_toc_subentry_to_chapter(&subentry, chapters) {
            let signal_title =
                normalize_title(subentry.get("title").and_then(|v| v.as_str()).unwrap_or(""));
            ranked.push(PageChapterSignal {
                page_no,
                chapter_id: matched.0,
                chapter_title: matched.1,
                signal_title,
                source: "toc_subentry".into(),
                score: matched.2,
            });
        }
    }
    ranked
}
