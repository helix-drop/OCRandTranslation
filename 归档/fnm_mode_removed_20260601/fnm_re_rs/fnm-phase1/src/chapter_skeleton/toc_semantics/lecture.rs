//! 讲座集特殊处理。←→ Python `_looks_like_lecture_collection` / `_build_lecture_collection_chapter_rows` 等。

use super::title_utils::*;
use fnm_core::records::HeadingCandidate;
use fnm_core::title::{chapter_title_match_key, normalize_title};

/// 判断是否为讲座集（Biopolitics 类型：12 讲 + 课程封面）。
pub fn looks_like_lecture_collection(
    body_rows: &[TocRow],
    heading_candidates: &[HeadingCandidate],
) -> bool {
    let mut lecture_title_keys: std::collections::HashSet<String> =
        std::collections::HashSet::new();

    for row in body_rows {
        if is_lecture_title(&row.title) {
            let key = chapter_title_match_key(&row.title);
            if !key.is_empty() {
                lecture_title_keys.insert(key);
            }
        }
    }
    for candidate in heading_candidates {
        if is_lecture_title(&candidate.text) && candidate.page_no > 0 {
            let key = chapter_title_match_key(&candidate.text);
            if !key.is_empty() {
                lecture_title_keys.insert(key);
            }
        }
    }

    let has_course_cover = body_rows
        .iter()
        .any(|r| is_lecture_collection_excluded(&r.title));

    has_course_cover && lecture_title_keys.len() >= 4
}

/// 为讲座集构建章节行。
pub fn build_lecture_collection_chapter_rows(
    body_rows: &[TocRow],
    heading_candidates: &[HeadingCandidate],
    page_role_by_no: &std::collections::HashMap<i64, String>,
    chapter_level: i64,
) -> Vec<TocRow> {
    // 收集讲座行
    let mut lecture_rows: Vec<TocRow> = Vec::new();
    for row in body_rows {
        if row.page_no <= 0 {
            continue;
        }
        let (title, had_suffix) = normalize_lecture_title_and_suffix(&row.title);
        if !is_lecture_title(&title) {
            continue;
        }
        if is_lecture_collection_excluded(&title) {
            continue;
        }
        let mut normalized = row.clone();
        normalized.title = preferred_lecture_heading_title(&title, row.page_no, heading_candidates);
        normalized.source = format!("lecture:{}", had_suffix as u8);
        lecture_rows.push(normalized);
    }

    // 按 title_key 去重，保留 rank 最高的
    let mut selected_by_title: std::collections::HashMap<String, TocRow> =
        std::collections::HashMap::new();
    for row in lecture_rows {
        let title_key = chapter_title_match_key(&row.title);
        if title_key.is_empty() {
            continue;
        }
        let rank = lecture_row_rank(&row);
        match selected_by_title.entry(title_key) {
            std::collections::hash_map::Entry::Vacant(e) => {
                e.insert(row);
            }
            std::collections::hash_map::Entry::Occupied(mut e) => {
                if rank > lecture_row_rank(e.get()) {
                    e.insert(row);
                }
            }
        }
    }

    let mut lecture_rows: Vec<TocRow> = selected_by_title.into_values().collect();
    lecture_rows.sort_by(|a, b| {
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

    // 从 heading_candidates 补充缺失的讲座标题
    let seen_title_keys: std::collections::HashSet<String> = lecture_rows
        .iter()
        .map(|r| chapter_title_match_key(&r.title))
        .filter(|k| !k.is_empty())
        .collect();
    let mut seen_row_keys: std::collections::HashSet<(i64, String)> = lecture_rows
        .iter()
        .map(|r| visual_toc_row_key(r.page_no, &r.title))
        .collect();

    let mut supplemental: Vec<TocRow> = Vec::new();
    for candidate in heading_candidates {
        let page_no = candidate.page_no;
        if page_no <= 0 {
            continue;
        }
        let title = normalize_lecture_title(&candidate.text);
        if title.is_empty() || !is_lecture_title(&title) {
            continue;
        }
        if !matches!(
            candidate.source.as_str(),
            "ocr_block" | "markdown_heading" | "pdf_font_band"
        ) {
            continue;
        }
        if !matches!(candidate.heading_family_guess.as_str(), "chapter" | "book") {
            continue;
        }
        if is_lecture_collection_excluded(&title) {
            continue;
        }
        let page_role = page_role_by_no.get(&page_no).map_or("", |s| s.as_str());
        if !matches!(page_role, "body" | "front_matter") {
            continue;
        }
        let title_key = chapter_title_match_key(&title);
        if title_key.is_empty() || seen_title_keys.contains(&title_key) {
            continue;
        }
        let row = TocRow {
            item_id: format!(
                "lecture-heading-{:04}-{}",
                page_no,
                &title_key.chars().take(24).collect::<String>()
            ),
            title,
            page_no,
            level: chapter_level,
            order: 1_000_000 + page_no,
            family: "body".into(),
            page_role: page_role.to_string(),
            non_body_title: false,
            resolved_via_heading: true,
            semantic_role: "chapter".into(),
            ..Default::default()
        };
        let key = visual_toc_row_key(row.page_no, &row.title);
        if seen_row_keys.contains(&key) {
            continue;
        }
        seen_row_keys.insert(key);
        supplemental.push(row);
    }

    let mut result = lecture_rows;
    result.extend(supplemental);
    dedupe_visual_toc_rows(&mut result);
    result
}

/// 讲座集边界页。
pub fn lecture_collection_boundary_pages(
    body_rows: &[TocRow],
    heading_candidates: &[HeadingCandidate],
    page_role_by_no: &std::collections::HashMap<i64, String>,
) -> std::collections::HashSet<i64> {
    let mut pages = std::collections::HashSet::new();
    for row in body_rows {
        if row.page_no > 0 && is_lecture_collection_boundary(&row.title) {
            pages.insert(row.page_no);
        }
    }
    for candidate in heading_candidates {
        let title = normalize_title(&candidate.text);
        if candidate.page_no > 0 && is_lecture_collection_boundary(&title) {
            let page_role = page_role_by_no
                .get(&candidate.page_no)
                .map_or("", |s| s.as_str());
            if matches!(page_role, "body" | "front_matter") {
                pages.insert(candidate.page_no);
            }
        }
    }
    pages
}

fn lecture_row_rank(row: &TocRow) -> (i64, i64, i64) {
    let title_penalty = if row.source.starts_with("lecture:1") {
        0
    } else {
        1
    };
    let resolved_score = if row.resolved_via_heading { 1 } else { 0 };
    let page_role_score = match row.page_role.as_str() {
        "body" => 2,
        "front_matter" => 1,
        _ => 0,
    };
    (title_penalty, resolved_score, page_role_score)
}

fn preferred_lecture_heading_title(
    title: &str,
    page_no: i64,
    heading_candidates: &[HeadingCandidate],
) -> String {
    let normalized_title = normalize_lecture_title(title);
    let fallback_title = if is_lecture_title(&normalized_title) {
        normalized_title.to_uppercase()
    } else {
        normalized_title.clone()
    };
    let title_key = chapter_title_match_key(&normalized_title);
    if page_no <= 0 || title_key.is_empty() {
        return fallback_title;
    }

    let mut candidates: Vec<(i64, String)> = Vec::new();
    for candidate in heading_candidates {
        if candidate.page_no != page_no {
            continue;
        }
        let candidate_text = normalize_lecture_title(&candidate.text);
        if candidate_text.is_empty() {
            continue;
        }
        if chapter_title_match_key(&candidate_text) != title_key {
            continue;
        }
        if !is_lecture_title(&candidate_text) {
            continue;
        }
        let mut score = 0i64;
        match candidate.source.as_str() {
            "ocr_block" if candidate.block_label == "doc_title" => score += 40,
            "markdown_heading" => score += 30,
            "pdf_font_band" => score += 20,
            _ => continue,
        }
        if candidate.top_band {
            score += 10;
        }
        if candidate.heading_family_guess == "chapter" {
            score += 8;
        }
        score += (candidate.confidence * 10.0).round() as i64;
        candidates.push((score, candidate_text));
    }

    if candidates.is_empty() {
        return fallback_title;
    }
    candidates.sort_by(|a, b| b.cmp(a));
    normalize_lecture_title(&candidates[0].1)
}
