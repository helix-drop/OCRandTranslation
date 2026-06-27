//! Evidence 评分。←→ Python `_candidate_evidence_score()` / `_candidate_source_score()` 等。

use fnm_core::records::HeadingCandidate;

/// source 类型优先级打分（heading_graph evidence 体系，**百级量纲**）。
/// ⚠️ 与 `chapter_skeleton/toc_semantics/row_collect.rs` 的同名函数**分值体系不同**
/// （那里是 visual_toc 行评分，十级量纲，相对顺序也不同）——同名巧合、语义各异，
/// **不可合并**（CLAUDE.md §12：分值不同的重复不可盲目统一）。
pub fn candidate_source_score(source: &str, block_label: &str) -> i64 {
    match source {
        "pdf_font_band_composite" => 320,
        "ocr_block" if block_label == "doc_title" => 300,
        "ocr_block" | "pdf_font_band" => 200,
        "markdown_heading" => 180,
        "visual_toc" => 100,
        _ => 0,
    }
}

/// family 打分。
pub fn candidate_family_score(family: &str) -> i64 {
    match family {
        "chapter" | "book" => 18,
        "section" => 10,
        _ => 0,
    }
}

/// 综合 evidence 打分。
pub fn candidate_evidence_score(candidate: &HeadingCandidate) -> i64 {
    let mut score = candidate_source_score(&candidate.source, &candidate.block_label);
    score += candidate_family_score(&candidate.heading_family_guess);
    if candidate.heading_level_hint > 0 {
        score += 10;
    }
    if candidate.top_band {
        score += 8;
    }
    let weight_score = match candidate.font_weight_hint.as_str() {
        "bold" | "heavy" => 6,
        _ => 0,
    };
    score += weight_score;
    let align_score = match candidate.align_hint.as_str() {
        "center" => 4,
        _ => 0,
    };
    score += align_score;
    score += (candidate.confidence * 10.0).round() as i64;
    score
}

/// 判断是否有强 chapter 证据。
pub fn has_strong_chapter_evidence(candidate: &HeadingCandidate) -> bool {
    // composite/doc_title/markdown_heading 直接通过
    if matches!(
        candidate.source.as_str(),
        "pdf_font_band_composite" | "markdown_heading"
    ) {
        return true;
    }
    if candidate.source == "ocr_block" && candidate.block_label == "doc_title" {
        return true;
    }
    // 否则数信号
    let mut signals = 0i64;
    if matches!(candidate.heading_family_guess.as_str(), "chapter" | "book") {
        signals += 1;
    }
    if candidate.top_band {
        signals += 1;
    }
    if candidate.confidence >= 0.7 {
        signals += 1;
    }
    if matches!(candidate.font_weight_hint.as_str(), "bold" | "heavy") {
        signals += 1;
    }
    if candidate.heading_level_hint > 0 {
        signals += 1;
    }
    signals >= 3
}

/// 排序键：(evidence_score, confidence, -page_no)。
pub fn candidate_sort_key(
    candidate: &HeadingCandidate,
    target_page: i64,
    prev_anchor_page: i64,
    next_anchor_page: i64,
) -> (i64, i64, i64, i64) {
    let evidence_score = candidate_evidence_score(candidate);
    let page_no = candidate.page_no;

    // monotonic_ok: page 在 prev 和 next 之间
    let monotonic_ok = if prev_anchor_page > 0 && next_anchor_page > 0 {
        page_no > prev_anchor_page && page_no < next_anchor_page
    } else if prev_anchor_page > 0 {
        page_no > prev_anchor_page
    } else {
        true
    };
    let monotonic_score = if monotonic_ok { 1 } else { 0 };

    let distance = (page_no - target_page).unsigned_abs() as i64;

    (
        monotonic_score,
        evidence_score,
        -distance,
        (candidate.confidence * 100.0).round() as i64,
    )
}
