//! ←→ FNM_RE/stages/note_links.py
//!
//! note_links 编排入口：调用 endnote_links + footnote_links + orphan_anchor 路径。

use fnm_core::records::{
    BodyAnchorRecord, ChapterNoteModeRecord, NoteItemRecord, NoteLinkRecord, NoteRegionRecord,
};
use fnm_core::types::LinkStatus;
use fnm_phase1::input::RawPage;
use std::collections::{HashMap, HashSet};

/// 构建 note links。
///
/// ←→ Python `build_note_links`
///
/// `chapter_note_modes` 用于构建 `review_seed_summary` 中的
/// `boundary_review_required_count`（Python 行 166-168）。
pub fn build_note_links(
    anchors: &mut Vec<BodyAnchorRecord>,
    note_items: &[NoteItemRecord],
    raw_pages: &[RawPage],
    link_serial_start: usize,
    chapter_note_modes: &[ChapterNoteModeRecord],
    note_regions: &[NoteRegionRecord],
) -> (Vec<NoteLinkRecord>, NoteLinkSummary) {
    let page_text_by_no: HashMap<i64, String> = raw_pages
        .iter()
        .map(|p| (p.book_page, p.markdown.clone()))
        .collect();

    let mut used_anchor_ids: HashSet<String> = HashSet::new();

    // 构建 regions_by_id + anchor_count_by_chapter
    let regions_by_id: HashMap<String, &NoteRegionRecord> = note_regions
        .iter()
        .filter_map(|r| {
            let id = r.region_id.trim();
            if id.is_empty() {
                None
            } else {
                Some((id.to_string(), r))
            }
        })
        .collect();
    let mut anchor_count_by_chapter: HashMap<String, usize> = HashMap::new();
    for anchor in anchors.iter() {
        if !anchor.synthetic && !anchor.chapter_id.is_empty() {
            *anchor_count_by_chapter
                .entry(anchor.chapter_id.clone())
                .or_default() += 1;
        }
    }

    // 按 page_no 排序 note_items
    let mut note_items_sorted: Vec<&NoteItemRecord> = note_items.iter().collect();
    note_items_sorted.sort_by_key(|row| (row.page_no, &row.note_item_id));

    // ── 尾注匹配 ──
    let (en_links, _orphan_indexes) = crate::endnote_links::build_endnote_links(
        anchors,
        note_items,
        &mut used_anchor_ids,
        &page_text_by_no,
        link_serial_start,
        &regions_by_id,
        &anchor_count_by_chapter,
    );

    // ── 脚注匹配 ──
    let (fn_links, _fn_serial, _synthetic_serial, ocr_repaired_count) =
        crate::footnote_links::build_footnote_links(
            anchors,
            note_items,
            &mut used_anchor_ids,
            link_serial_start + en_links.len(),
            1,
        );

    let mut links = en_links;
    links.extend(fn_links);

    // ── orphan_anchor 路径 ──
    let orphan_links = build_orphan_anchor_links(anchors, note_items, &used_anchor_ids);
    links.extend(orphan_links);

    // 排序
    links.sort_by(|a, b| a.link_id.cmp(&b.link_id));
    anchors.sort_by(|a, b| {
        a.page_no
            .cmp(&b.page_no)
            .then(a.paragraph_index.cmp(&b.paragraph_index))
            .then(a.char_start.cmp(&b.char_start))
            .then(a.anchor_id.cmp(&b.anchor_id))
    });

    let summary = build_summary(
        &links,
        anchors,
        note_items,
        ocr_repaired_count,
        chapter_note_modes,
    );
    (links, summary)
}

// ── orphan_anchor links ─────────────────────────────────────────

fn build_orphan_anchor_links(
    anchors: &[BodyAnchorRecord],
    note_items: &[NoteItemRecord],
    used_anchor_ids: &HashSet<String>,
) -> Vec<NoteLinkRecord> {
    let mut note_item_marker_keys: HashSet<(String, String, String)> = HashSet::new();
    let mut note_kind_with_markers: HashSet<(String, String)> = HashSet::new();
    let mut note_kind_marker_ranges: HashMap<(String, String), (i64, i64)> = HashMap::new();

    for item in note_items {
        let normalized_marker = item.marker.trim();
        if normalized_marker.is_empty() {
            continue;
        }
        let note_kind = item.note_kind.as_str();
        if !matches!(note_kind, "footnote" | "endnote") {
            continue;
        }
        let chapter_id = item.chapter_id.trim();
        if chapter_id.is_empty() {
            continue;
        }
        note_item_marker_keys.insert((
            chapter_id.to_string(),
            note_kind.to_string(),
            normalized_marker.to_string(),
        ));
        if let Ok(marker_int) = normalized_marker.parse::<i64>() {
            let key = (chapter_id.to_string(), note_kind.to_string());
            note_kind_with_markers.insert(key.clone());
            let entry = note_kind_marker_ranges
                .entry(key)
                .or_insert((marker_int, marker_int));
            entry.0 = entry.0.min(marker_int);
            entry.1 = entry.1.max(marker_int);
        }
    }

    let mut orphan_links: Vec<NoteLinkRecord> = Vec::new();
    // 已作为 orphan_anchor 入池的 marker 去重，防止同一 marker 的多个 anchor 都入池
    let mut used_marker_keys: HashSet<(String, String, String)> = HashSet::new();
    let mut link_serial = 1usize; // 临时序列号，由调用方重新编号

    for anchor in anchors {
        if anchor.synthetic || used_anchor_ids.contains(&anchor.anchor_id) {
            continue;
        }
        let normalized_marker = anchor.normalized_marker.trim();
        if normalized_marker.is_empty() {
            continue;
        }
        let inferred_kind = match anchor.anchor_kind.as_str() {
            "footnote" => "footnote",
            "endnote" => "endnote",
            _ => "unknown",
        };
        let chapter_id = anchor.chapter_id.trim();
        let mkey = (
            chapter_id.to_string(),
            inferred_kind.to_string(),
            normalized_marker.to_string(),
        );
        if note_item_marker_keys.contains(&mkey) || used_marker_keys.contains(&mkey) {
            continue;
        }
        let chapter_key = (chapter_id.to_string(), inferred_kind.to_string());
        if crate::link_utils::is_fallback_chapter_id(chapter_id)
            && !note_kind_with_markers.contains(&chapter_key)
        {
            continue;
        }
        if let Ok(marker_int) = normalized_marker.parse::<i64>() {
            if let Some(&(min_v, max_v)) = note_kind_marker_ranges.get(&chapter_key) {
                if crate::link_utils::is_toc_chapter_id(chapter_id)
                    && (marker_int < min_v || marker_int > max_v)
                {
                    continue;
                }
            }
        }
        used_marker_keys.insert(mkey);
        orphan_links.push(crate::link_utils::link_new_link(
            &crate::link_utils::NewLinkParams {
                serial: link_serial,
                chapter_id,
                region_id: "",
                note_item_id: "",
                anchor_id: &anchor.anchor_id,
                status: LinkStatus::OrphanAnchor,
                resolver: fnm_core::types::LinkResolver::Rule,
                confidence: 0.0,
                note_kind: if inferred_kind == "footnote" {
                    fnm_core::types::NoteKind::Footnote
                } else {
                    fnm_core::types::NoteKind::Endnote
                },
                marker: normalized_marker,
                page_no_start: anchor.page_no,
                page_no_end: anchor.page_no,
            },
        ));
        link_serial += 1;
    }
    orphan_links
}

// ── Summary ────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct ReviewSeedSummary {
    pub boundary_review_required_count: usize,
    pub uncertain_anchor_ids: Vec<String>,
    pub orphan_link_ids: Vec<String>,
    pub ambiguous_link_ids: Vec<String>,
    pub synthetic_anchor_ids: Vec<String>,
}

#[derive(Debug, Clone, Default)]
pub struct NoteLinkSummary {
    pub matched: usize,
    pub footnote_orphan_note: usize,
    pub footnote_orphan_anchor: usize,
    pub endnote_orphan_note: usize,
    pub endnote_orphan_anchor: usize,
    pub unknown_orphan: usize,
    pub ambiguous: usize,
    pub ignored: usize,
    pub fallback_count: usize,
    pub repair_count: usize,
    pub synthetic_added_count: usize,
    pub ocr_repaired_count: usize,
    /// ←→ Python `review_seed_summary`（note_linking.py 行 165-178）
    pub review_seed: ReviewSeedSummary,
}

fn build_summary(
    links: &[NoteLinkRecord],
    anchors: &[BodyAnchorRecord],
    _note_items: &[NoteItemRecord],
    ocr_repaired_count: usize,
    chapter_note_modes: &[ChapterNoteModeRecord],
) -> NoteLinkSummary {
    let mut summary = NoteLinkSummary::default();
    for link in links {
        match (link.note_kind.as_str(), link.status.as_str()) {
            (_, "matched") => summary.matched += 1,
            ("footnote", "orphan_note") => summary.footnote_orphan_note += 1,
            ("footnote", "orphan_anchor") => summary.footnote_orphan_anchor += 1,
            ("endnote", "orphan_note") => summary.endnote_orphan_note += 1,
            ("endnote", "orphan_anchor") => summary.endnote_orphan_anchor += 1,
            ("unknown", "orphan_note") | ("unknown", "orphan_anchor") => {
                summary.unknown_orphan += 1
            }
            (_, "ambiguous") => summary.ambiguous += 1,
            (_, "ignored") => summary.ignored += 1,
            _ => {}
        }
        if link.resolver.as_str() == "fallback" {
            summary.fallback_count += 1;
        }
        if link.resolver.as_str() == "repair" {
            summary.repair_count += 1;
        }
    }
    summary.ocr_repaired_count = ocr_repaired_count;
    summary.synthetic_added_count = anchors
        .iter()
        .filter(|a| a.synthetic && a.source == "synthetic")
        .count();

    // ←→ Python 行 165-178：review_seed_summary
    summary.review_seed = ReviewSeedSummary {
        boundary_review_required_count: chapter_note_modes
            .iter()
            .filter(|m| m.note_mode.as_str() == "review_required")
            .count(),
        uncertain_anchor_ids: anchors
            .iter()
            .filter(|a| a.anchor_kind.as_str() == "unknown" || a.certainty < 1.0)
            .map(|a| a.anchor_id.clone())
            .collect(),
        orphan_link_ids: links
            .iter()
            .filter(|l| l.status == LinkStatus::OrphanNote || l.status == LinkStatus::OrphanAnchor)
            .map(|l| l.link_id.clone())
            .collect(),
        ambiguous_link_ids: links
            .iter()
            .filter(|l| l.status == LinkStatus::Ambiguous)
            .map(|l| l.link_id.clone())
            .collect(),
        synthetic_anchor_ids: anchors
            .iter()
            .filter(|a| a.synthetic)
            .map(|a| a.anchor_id.clone())
            .collect(),
    };
    summary
}
