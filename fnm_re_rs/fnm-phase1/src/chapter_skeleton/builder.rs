//! ←→ FNM_RE/stages/chapter_skeleton/builder.py
//! 章节边界构建器。

use crate::input::{RawPage, TocItem};
use fnm_core::records::{ChapterRecord, HeadingCandidate, PagePartitionRecord};
use fnm_core::title::{chapter_title_match_key, guess_title_family, normalize_title};
use fnm_core::types::{BoundaryState, ChapterSource, PageRole};
use once_cell::sync::Lazy;
use regex::Regex;

static TOC_FORCE_EXPORT_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^\s*(?:introduction|avertissement|pr[eé]face|foreword|epilogue|conclusion)\b")
        .unwrap()
});

#[derive(Debug, Clone)]
pub struct ChapterSkeleton {
    pub chapters: Vec<ChapterRecord>,
    pub heading_candidates: Vec<HeadingCandidate>,
    pub diagnostics: serde_json::Value,
}

/// 从 TOC items + page_partitions 构建章节骨架。
pub fn build_chapter_skeleton(
    pages: &[RawPage],
    toc_items: Option<&[TocItem]>,
    page_partitions: &[PagePartitionRecord],
    heading_graph: &crate::heading_graph::HeadingGraph,
    mut heading_candidates: Vec<HeadingCandidate>,
) -> ChapterSkeleton {
    let total_pages = pages.len() as i64;

    let (chapters, source) = if let Some(items) = toc_items {
        if items.is_empty() {
            (vec![], "fallback")
        } else {
            // ←→ Python _resolve_visual_toc_target_page: 全局搜索 heading candidates，
            // 按 chapter_title_match_key 匹配 TOC title，将目标页替换为 heading 实际位置。
            let page_roles: std::collections::HashMap<i64, PageRole> = page_partitions
                .iter()
                .map(|p| (p.page_no, p.page_role))
                .collect();

            let mut chs: Vec<ChapterRecord> = items
                .iter()
                .filter(|item| item.export_candidate.unwrap_or(true))
                .enumerate()
                .map(|(i, item)| {
                    let target = item.target_pdf_page.unwrap_or(1);
                    let start_page = resolve_visual_toc_target_page(
                        &item.title,
                        target,
                        &page_roles,
                        &heading_candidates,
                    );
                    // ←→ Python `_build_visual_toc_chapters`：chapter_id 用
                    // `toc-{item_id}` 而非硬编码 `toc-ch-{i+1}`，对齐 Python 命名
                    // 约定（item_id 已含 `toc-ch-N` 时会出现 `toc-toc-ch-N`，
                    // 这是 Python 端历史命名导致，Rust 必须 byte-equal 复制）。
                    let chapter_id = if !item.item_id.trim().is_empty() {
                        format!("toc-{}", item.item_id.trim())
                    } else {
                        format!("toc-toc-ch-{}", i + 1)
                    };
                    ChapterRecord {
                        chapter_id,
                        title: item.title.clone(),
                        start_page,
                        end_page: 0,
                        pages: vec![],
                        source: ChapterSource::VisualToc,
                        boundary_state: BoundaryState::Ready,
                    }
                })
                .collect();

            // 按起始页排序（heading_graph 可能重排章顺序）
            chs.sort_by_key(|ch| ch.start_page);
            // 注：排序后**不**重新生成 chapter_id——保留 toc-item_id 命名
            // （原 `toc-ch-{i+1}` 是按位置编号，与 Python `toc-{item_id}` 不一致）。

            // fill end_page
            for i in 0..chs.len() {
                let next_start = if i + 1 < chs.len() {
                    chs[i + 1].start_page
                } else {
                    total_pages + 1
                };
                chs[i].end_page = next_start - 1;
                chs[i].pages = (chs[i].start_page..=chs[i].end_page).collect();
            }

            // ←→ Python _trim_chapter_rows: 修剪章节页范围（仅保留 body/front_matter，
            // 并在 back_matter 起点之后截断）。
            let back_matter_start =
                infer_back_matter_start_page(page_partitions, items, total_pages);
            let mut trimmed: Vec<ChapterRecord> = Vec::new();

            for ch in &chs {
                let _title_key = chapter_title_match_key(&ch.title);
                let is_force_export =
                    TOC_FORCE_EXPORT_TITLE_RE.is_match(&normalize_title(&ch.title));
                let mut filtered_pages: Vec<i64> = ch
                    .pages
                    .iter()
                    .filter(|&&p| {
                        page_roles
                            .get(&p)
                            .is_some_and(|r| matches!(r, PageRole::Body | PageRole::FrontMatter))
                    })
                    .copied()
                    .collect();
                // Python: 有 back_matter 起点时截断非强制导出的章
                if back_matter_start > 0 && !is_force_export {
                    filtered_pages.retain(|&p| p < back_matter_start);
                }
                if filtered_pages.is_empty() {
                    continue;
                }
                let mut trimmed_ch = ch.clone();
                trimmed_ch.start_page = filtered_pages[0];
                trimmed_ch.end_page = *filtered_pages.last().unwrap();
                trimmed_ch.pages = filtered_pages;
                trimmed.push(trimmed_ch);
            }
            (trimmed, "visual_toc")
        }
    } else {
        (vec![], "fallback")
    };

    let chapters = if chapters.is_empty() {
        crate::chapter_skeleton::fallback::build_chapter_skeleton_fallback(
            page_partitions,
            &mut heading_candidates,
            heading_graph,
            total_pages,
        )
    } else {
        chapters
    };

    ChapterSkeleton {
        chapters,
        heading_candidates,
        diagnostics: serde_json::json!({
            "source": source,
            "total_pages": total_pages,
        }),
    }
}

/// 推断 back matter 起始页。
/// ←→ Python `_infer_back_matter_start_page`
fn infer_back_matter_start_page(
    page_partitions: &[PagePartitionRecord],
    toc_items: &[TocItem],
    total_pages: i64,
) -> i64 {
    let rear_min_page = (24).max((total_pages as f64 * 0.45) as i64);
    let rear_force_page = (rear_min_page).max((total_pages as f64 * 0.8) as i64);
    let toc_back_matter_min = (24).max((total_pages as f64 * 0.25) as i64);

    let rear_reasons: &[&str] = &[
        "appendix",
        "bibliography",
        "index",
        "illustrations",
        "rear_toc_tail",
        "rear_author_blurb",
        "rear_sparse_other",
    ];

    // 收集尾部的 "other" 页（rear role pages）
    let rear_role_pages: Vec<i64> = page_partitions
        .iter()
        .filter(|p| {
            p.page_no >= rear_min_page
                && p.page_role == PageRole::Other
                && rear_reasons.contains(&p.reason.as_str())
        })
        .map(|p| p.page_no)
        .collect();

    let mut candidate_pages: Vec<i64> = Vec::new();
    for p in page_partitions {
        if p.page_no < rear_min_page {
            continue;
        }
        if p.page_role != PageRole::Other {
            continue;
        }
        if !rear_reasons.contains(&p.reason.as_str()) {
            continue;
        }
        let has_neighbor = rear_role_pages
            .iter()
            .any(|&other| other != p.page_no && (other - p.page_no).abs() <= 6);
        if p.page_no >= rear_force_page || has_neighbor {
            candidate_pages.push(p.page_no);
        }
    }

    // TOC back_matter items
    for item in toc_items {
        let resolved = item.target_pdf_page.unwrap_or(0);
        if resolved <= 0 || resolved < toc_back_matter_min {
            continue;
        }
        let role = item.role_hint.trim().to_lowercase().replace('-', "_");
        let family = guess_title_family(&item.title, resolved, total_pages);
        if role == "back_matter" || matches!(family, "bibliography" | "index" | "illustrations") {
            candidate_pages.push(resolved);
        }
    }

    candidate_pages.into_iter().min().unwrap_or(0)
}

/// 全局搜索 heading candidates，用 chapter_title_match_key 匹配 TOC title，
/// 返回最佳候选的 page_no。←→ Python `_resolve_visual_toc_target_page`
fn resolve_visual_toc_target_page(
    title: &str,
    target_page: i64,
    page_roles: &std::collections::HashMap<i64, PageRole>,
    heading_candidates: &[HeadingCandidate],
) -> i64 {
    let title_key = chapter_title_match_key(title);
    if title_key.is_empty() {
        return target_page;
    }

    // (score, -distance, -page_no, page_no)
    let mut scored: Vec<(i64, i64, i64, i64)> = Vec::new();
    let mut current_has_exact_heading = false;

    for c in heading_candidates {
        if c.page_no <= 0 {
            continue;
        }
        if chapter_title_match_key(&c.text) != title_key {
            continue;
        }
        if c.page_no == target_page && c.source != "visual_toc" {
            current_has_exact_heading = true;
        }
        let role = page_roles
            .get(&c.page_no)
            .copied()
            .unwrap_or(PageRole::Body);
        if matches!(role, PageRole::Note | PageRole::Other | PageRole::Noise) {
            continue;
        }

        let mut score: i64 = 0;
        match role {
            PageRole::Body => score += 300,
            PageRole::FrontMatter => score += 120,
            _ => {}
        }
        match c.source.as_str() {
            "ocr_block" if c.block_label == "doc_title" => score += 36,
            "markdown_heading" => score += 30,
            "pdf_font_band" => score += 24,
            "visual_toc" => score += 10,
            _ => {}
        }
        match c.heading_family_guess.as_str() {
            "chapter" | "book" => score += 18,
            "section" => score += 10,
            _ => {}
        }
        if c.top_band {
            score += 8;
        }
        score += (c.confidence * 10.0).round() as i64;
        let distance = (c.page_no - target_page).abs();
        scored.push((score, -distance, -c.page_no, c.page_no));
    }

    if scored.is_empty() {
        return target_page;
    }

    scored.sort_by(|a, b| b.cmp(a)); // descending

    let best_page = scored[0].3;
    let current_role = page_roles
        .get(&target_page)
        .copied()
        .unwrap_or(PageRole::Body);
    let best_role = page_roles
        .get(&best_page)
        .copied()
        .unwrap_or(PageRole::Body);

    let should_replace = matches!(
        current_role,
        PageRole::Noise | PageRole::Other | PageRole::Note
    ) || (!current_has_exact_heading && best_page != target_page)
        || (best_role == PageRole::Body && current_role != PageRole::Body)
        || (current_role == PageRole::FrontMatter
            && best_role == PageRole::Body
            && is_toc_body_anchor_title(title));

    if should_replace && best_page != target_page {
        best_page
    } else {
        target_page
    }
}

/// ←→ Python `_is_toc_body_anchor_title`: lecture titles 等应锚定到 body 页。
fn is_toc_body_anchor_title(title: &str) -> bool {
    static LECTURE_ANCHOR_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"(?i)\b(?:le[cç]on|chapter|chapitre|cours)\b").unwrap());
    LECTURE_ANCHOR_RE.is_match(&normalize_title(title))
}
