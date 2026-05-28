//! 候选匹配。←→ Python `_best_candidate()` / `_exact_matching_candidates()`。

use fnm_core::records::HeadingCandidate;
use fnm_core::title::chapter_title_match_key;

use super::scoring;

/// 在指定页范围内按 title_key 精确匹配。
pub fn exact_matching_candidates<'a>(
    title_key: &str,
    candidates: &'a [HeadingCandidate],
    start_page: i64,
    end_page: i64,
) -> Vec<&'a HeadingCandidate> {
    candidates
        .iter()
        .filter(|c| {
            c.page_no >= start_page
                && c.page_no <= end_page
                && chapter_title_match_key(&c.text) == title_key
        })
        .collect()
}

/// 选择最优候选。
pub fn best_candidate(
    title_key: &str,
    candidates: &[HeadingCandidate],
    start_page: i64,
    end_page: i64,
    target_page: i64,
    anchor_pages: (i64, i64),
    require_strong: bool,
) -> Option<HeadingCandidate> {
    let mut matched = exact_matching_candidates(title_key, candidates, start_page, end_page);

    if require_strong {
        matched.retain(|c| scoring::has_strong_chapter_evidence(c));
    }

    if matched.is_empty() {
        return None;
    }

    matched.sort_by(|a, b| {
        let ka = scoring::candidate_sort_key(a, target_page, anchor_pages.0, anchor_pages.1);
        let kb = scoring::candidate_sort_key(b, target_page, anchor_pages.0, anchor_pages.1);
        kb.cmp(&ka)
    });

    matched.first().map(|c| (*c).clone())
}

/// 收集非 body 页作为 stop pages。
pub fn body_stop_pages(page_roles: &[(i64, &str)]) -> Vec<i64> {
    page_roles
        .iter()
        .filter(|(_, role)| !matches!(*role, "body" | "front_matter"))
        .map(|(page_no, _)| *page_no)
        .collect()
}

/// 找 after_page 之后的第一个 stop page。
pub fn next_stop_page(stop_pages: &[i64], after_page: i64) -> i64 {
    stop_pages
        .iter()
        .find(|&&p| p > after_page)
        .copied()
        .unwrap_or(0)
}

/// 判断候选是否为 section 样式。
pub fn is_section_style_candidate(candidate: &HeadingCandidate) -> bool {
    candidate.heading_family_guess == "section"
        || (candidate.heading_level_hint >= 2
            && !matches!(candidate.heading_family_guess.as_str(), "chapter" | "book"))
}

/// 判断候选是否为 anchor 候选（在 body 区、source 不是 visual_toc）。
pub fn is_anchor_candidate(candidate: &HeadingCandidate, page_roles: &[(i64, &str)]) -> bool {
    let page_role = page_roles
        .iter()
        .find(|(p, _)| *p == candidate.page_no)
        .map(|(_, r)| *r)
        .unwrap_or("");
    if matches!(page_role, "note" | "other" | "noise") {
        return false;
    }
    candidate.source != "visual_toc"
}
