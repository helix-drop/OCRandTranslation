//! TOC row 收集。←→ Python `_collect_visual_toc_rows()`。

use super::title_utils::*;
use crate::input::{RawPage, TocItem};
use fnm_core::records::PagePartitionRecord;
use fnm_core::title::chapter_title_match_key;

/// 收集 TOC rows：从 toc_items 构建带 page_no/role/level 的行列表。
pub fn collect_visual_toc_rows(
    toc_items: &[TocItem],
    pages: &[RawPage],
    page_partitions: &[PagePartitionRecord],
    heading_candidates: &[fnm_core::records::HeadingCandidate],
) -> Vec<TocRow> {
    if toc_items.is_empty() {
        return Vec::new();
    }

    let total_pages = pages.len().max(1) as i64;
    let page_role_by_no: std::collections::HashMap<i64, String> = page_partitions
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str().to_string()))
        .collect();

    let mut rows: Vec<TocRow> = Vec::new();

    for (index, item) in toc_items.iter().enumerate() {
        let title = normalize_visual_toc_item_title(&item.title);
        if title.is_empty() {
            continue;
        }

        // 推断 page_no
        let mut resolved_page = item.target_pdf_page.unwrap_or(0);
        let mut resolved_via_heading = false;

        if resolved_page > 0 {
            let (new_page, via_heading) = resolve_visual_toc_target_page(
                &title,
                resolved_page,
                &page_role_by_no,
                heading_candidates,
            );
            resolved_page = new_page;
            resolved_via_heading = via_heading;
        }
        if resolved_page <= 0 {
            let (new_page, via_heading) = resolve_visual_toc_page_by_heading_only(
                &title,
                &page_role_by_no,
                heading_candidates,
            );
            resolved_page = new_page;
            resolved_via_heading = via_heading;
        }

        let role = page_role_by_no
            .get(&resolved_page)
            .cloned()
            .unwrap_or_default();
        let family = title_family(&title, resolved_page, total_pages);
        let non_body_title = TOC_NON_BODY_TITLE_RE.is_match(&title);
        let role_hint = super::normalize_visual_toc_role_hint(&item.role_hint);

        let mut row = TocRow {
            item_id: item.item_id.clone(),
            title,
            page_no: resolved_page,
            level: visual_toc_level(item),
            page_role: role,
            family,
            non_body_title,
            order: (index + 1) as i64,
            resolved_via_heading,
            unresolved_page: resolved_page <= 0,
            explicit_role_hint: role_hint.clone(),
            role_hint,
            parent_title: normalize_visual_toc_item_title(&item.parent_title),
            body_candidate: item.body_candidate,
            export_candidate: item.export_candidate,
            semantic_role: String::new(),
            source: "visual_toc".into(),
        };

        // 对无 page 的 container/endnotes 等，用子项最小 page 作为合成 page
        if row.page_no <= 0
            && matches!(
                row.role_hint.as_str(),
                "container" | "endnotes" | "post_body" | "back_matter" | "front_matter"
            )
        {
            // 先标记 unresolved，后续 pass 会填充
            row.unresolved_page = true;
        }

        rows.push(row);
    }

    // Pass 2: 为无 page 的 container/endnotes 等填充合成 page
    let child_page_by_parent: std::collections::HashMap<String, i64> = {
        let mut map = std::collections::HashMap::new();
        for row in &rows {
            if row.parent_title.is_empty() || row.page_no <= 0 {
                continue;
            }
            let entry = map.entry(row.parent_title.clone()).or_insert(row.page_no);
            if row.page_no < *entry {
                *entry = row.page_no;
            }
        }
        map
    };

    for row in &mut rows {
        if row.page_no > 0 {
            continue;
        }
        if !matches!(
            row.role_hint.as_str(),
            "container" | "endnotes" | "post_body" | "back_matter" | "front_matter"
        ) {
            continue;
        }
        if let Some(&synthetic_page) = child_page_by_parent.get(&row.title) {
            if synthetic_page > 0 {
                row.page_no = synthetic_page;
                row.page_role = page_role_by_no
                    .get(&synthetic_page)
                    .cloned()
                    .unwrap_or_default();
                row.family = title_family(&row.title, synthetic_page, total_pages);
                row.unresolved_page = false;
            }
        }
    }

    // Sort by (page_no, order)
    rows.sort_by(|a, b| {
        let pa = if a.page_no > 0 {
            a.page_no
        } else {
            1_000_000_000
        };
        let pb = if b.page_no > 0 {
            b.page_no
        } else {
            1_000_000_000
        };
        pa.cmp(&pb).then(a.order.cmp(&b.order))
    });

    rows
}

/// 用 heading_candidates 修正 TOC item 的 target page。
fn resolve_visual_toc_target_page(
    title: &str,
    resolved_page: i64,
    page_role_by_no: &std::collections::HashMap<i64, String>,
    heading_candidates: &[fnm_core::records::HeadingCandidate],
) -> (i64, bool) {
    let title_key = chapter_title_match_key(title);
    if title_key.is_empty() {
        return (resolved_page, false);
    }

    let mut candidates: Vec<(i64, i64, i64, i64)> = Vec::new(); // (score, -distance, -page_no, page_no)
    let mut current_has_exact_heading = false;

    for candidate in heading_candidates {
        let page_no = candidate.page_no;
        if page_no <= 0 {
            continue;
        }
        let candidate_key = chapter_title_match_key(&candidate.text);
        if candidate_key != title_key {
            continue;
        }
        if page_no == resolved_page && candidate.source != "visual_toc" {
            current_has_exact_heading = true;
        }
        let page_role = page_role_by_no.get(&page_no).map_or("", |s| s.as_str());
        if matches!(page_role, "note" | "other" | "noise") {
            continue;
        }
        let mut score = 0i64;
        match page_role {
            "body" => score += 300,
            "front_matter" => score += 120,
            _ => {}
        }
        score += candidate_source_score(&candidate.source, &candidate.block_label);
        score += candidate_family_score(&candidate.heading_family_guess);
        if candidate.top_band {
            score += 8;
        }
        score += (candidate.confidence * 10.0).round() as i64;
        let distance = (page_no - resolved_page).unsigned_abs() as i64;
        candidates.push((score, -distance, -page_no, page_no));
    }

    if candidates.is_empty() {
        return (resolved_page, false);
    }
    candidates.sort_by(|a, b| b.cmp(a));
    let best_page = candidates[0].3;

    let current_role = page_role_by_no
        .get(&resolved_page)
        .map_or("", |s| s.as_str());
    let best_role = page_role_by_no.get(&best_page).map_or("", |s| s.as_str());

    let should_replace = matches!(current_role, "noise" | "other" | "note")
        || (!current_has_exact_heading && best_page != resolved_page)
        || (best_role == "body" && current_role != "body")
        || (current_role == "front_matter" && best_role == "body" && is_body_anchor_title(title));

    if should_replace && best_page != resolved_page {
        return (best_page, true);
    }
    (resolved_page, false)
}

/// 无 resolved_page 时，纯靠 heading_candidates 定位。
fn resolve_visual_toc_page_by_heading_only(
    title: &str,
    page_role_by_no: &std::collections::HashMap<i64, String>,
    heading_candidates: &[fnm_core::records::HeadingCandidate],
) -> (i64, bool) {
    let title_key = chapter_title_match_key(title);
    if title_key.is_empty() {
        return (0, false);
    }

    let mut candidates: Vec<(i64, i64, i64)> = Vec::new(); // (score, -page_no, page_no)

    for candidate in heading_candidates {
        let page_no = candidate.page_no;
        if page_no <= 0 {
            continue;
        }
        let candidate_key = chapter_title_match_key(&candidate.text);
        if candidate_key != title_key {
            continue;
        }
        let page_role = page_role_by_no.get(&page_no).map_or("", |s| s.as_str());
        if matches!(page_role, "note" | "other" | "noise") {
            continue;
        }
        let mut score = 0i64;
        match page_role {
            "body" => score += 300,
            "front_matter" => score += 120,
            _ => {}
        }
        score += candidate_source_score(&candidate.source, &candidate.block_label);
        score += candidate_family_score(&candidate.heading_family_guess);
        if candidate.top_band {
            score += 8;
        }
        score += (candidate.confidence * 10.0).round() as i64;
        candidates.push((score, -page_no, page_no));
    }

    if candidates.is_empty() {
        return (0, false);
    }
    candidates.sort_by(|a, b| b.cmp(a));
    (candidates[0].2, true)
}

/// source 评分（visual_toc 行体系，**十级量纲**）。
/// ⚠️ 与 `heading_graph/scoring.rs` 的同名 pub 函数**分值不同**，不可合并（§12）。
fn candidate_source_score(source: &str, block_label: &str) -> i64 {
    match source {
        "ocr_block" if block_label == "doc_title" => 36,
        "markdown_heading" => 30,
        "pdf_font_band" => 24,
        "pdf_font_band_composite" => 32,
        "visual_toc" => 10,
        _ => 0,
    }
}

fn candidate_family_score(family: &str) -> i64 {
    match family {
        "chapter" | "book" => 18,
        "section" => 10,
        _ => 0,
    }
}

fn is_body_anchor_title(title: &str) -> bool {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(
            r"(?i)\b(?:chapter|part|book|lecture|lesson|le[cç]on|cours|epilogue|conclusion)\b",
        )
        .unwrap()
    });
    RE.is_match(title)
}

/// 选择 chapter level（从 body candidates 中选）。
pub fn choose_visual_toc_chapter_level(rows: &[TocRow]) -> Option<i64> {
    let candidates: Vec<&TocRow> = rows
        .iter()
        .filter(|r| is_visual_toc_body_candidate(r))
        .collect();
    if candidates.is_empty() {
        return None;
    }
    let mut levels: Vec<i64> = candidates
        .iter()
        .map(|r| r.level)
        .filter(|&l| l > 0)
        .collect();
    levels.sort();
    levels.dedup();
    if levels.is_empty() {
        return None;
    }
    let mut chapter_level = levels[0];
    let base_count = candidates
        .iter()
        .filter(|r| r.level == chapter_level)
        .count();
    if base_count <= 2 {
        for &level in &levels[1..] {
            let level_count = candidates.iter().filter(|r| r.level == level).count();
            if level_count >= 3 {
                chapter_level = level;
                break;
            }
        }
    }
    Some(chapter_level)
}

/// 判断 row 是否是 body candidate。
pub fn is_visual_toc_body_candidate(row: &TocRow) -> bool {
    if let Some(bc) = row.body_candidate {
        return bc;
    }
    if row.non_body_title {
        return false;
    }
    if matches!(
        row.role_hint.as_str(),
        "container" | "endnotes" | "post_body" | "back_matter" | "front_matter"
    ) {
        return false;
    }
    if TOC_EXCLUDED_FAMILIES.contains(&row.family.as_str()) {
        return false;
    }
    if row.page_role == "body" {
        return true;
    }
    if row.page_role == "front_matter" && is_toc_force_export_title(&row.title) {
        return true;
    }
    if is_body_anchor_title(&row.title) {
        return true;
    }
    row.resolved_via_heading
}
