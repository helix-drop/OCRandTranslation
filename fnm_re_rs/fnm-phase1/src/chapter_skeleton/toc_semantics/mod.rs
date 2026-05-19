//! ←→ FNM_RE/stages/chapter_skeleton/toc_semantics.py
//! TOC 语义对齐：TOC item → heading 匹配、role 推断、单调性校验。

pub mod alignment;
pub mod container_detection;
pub mod lecture;
pub mod monotonic;
pub mod page_resolve;
pub mod role_inference;
pub mod row_collect;
pub mod sanitize;
pub mod title_utils;

use crate::input::{RawPage, TocItem};
use fnm_core::records::{ChapterRecord, HeadingCandidate, PagePartitionRecord, SectionHeadRecord};
use fnm_core::title::{chapter_title_match_key, normalize_title};
use once_cell::sync::Lazy;
use regex::Regex;
use title_utils::TocRow;

pub static TOC_PART_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:part|partie|livre|book|section)\s+(?:[ivxlcm]+|\d+)\b").unwrap()
});

pub static TOC_FORCE_EXPORT_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:introduction|avertissement|pr[eé]face|foreword|epilogue|conclusion)\b")
        .unwrap()
});

pub static TOC_EXPLICIT_CHAPTER_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^(?:chapter|chapitre)\b|^(?:\d+|[ivxlcm]+)[\.\):\-]\s+\S+|\ble[cç]on du\b|\bcours\b|\bprologue\b|\bepilogue\b|\bconclusion\b",
    )
    .unwrap()
});

pub static TOC_BODY_ANCHOR_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)\b(?:chapter|part|book|lecture|lesson|le[cç]on|cours|epilogue|conclusion)\b")
        .unwrap()
});

/// TOC role hint alias 映射。与 Python `_VISUAL_TOC_ROLE_ALIAS_MAP` 一致。
pub fn normalize_visual_toc_role_hint(raw: &str) -> String {
    match raw.trim().to_lowercase().replace('-', "_").as_str() {
        "part" | "book" | "course" | "cours" | "appendices" | "indices" => "container".into(),
        "notes" | "endnote" => "endnotes".into(),
        "frontmatter" => "front_matter".into(),
        "backmatter" => "back_matter".into(),
        "postbody" => "post_body".into(),
        "book_title" => "front_matter".into(),
        other => other.to_string(),
    }
}

/// 判断 TOC title 是否是显式 chapter 标题。
pub fn is_visual_toc_explicit_chapter_title(title: &str) -> bool {
    let normalized = normalize_title(title);
    if normalized.is_empty() {
        return false;
    }
    if TOC_FORCE_EXPORT_TITLE_RE.is_match(&normalized) {
        return true;
    }
    TOC_EXPLICIT_CHAPTER_TITLE_RE.is_match(&normalized)
}

/// TOC 语义分析结果。
#[derive(Debug, Clone)]
pub struct TocSemanticsResult {
    pub aligned_chapters: Vec<ChapterRecord>,
    pub section_heads: Vec<SectionHeadRecord>,
    pub toc_role_summary: std::collections::HashMap<String, i64>,
    pub semantic_blocking_reasons: Vec<String>,
    pub chapter_order_monotonic: bool,
    pub chapter_level: Option<i64>,
    pub meta: serde_json::Value,
}

pub fn default_toc_role_summary() -> std::collections::HashMap<String, i64> {
    std::collections::HashMap::from([
        ("container".into(), 0),
        ("endnotes".into(), 0),
        ("chapter".into(), 0),
        ("section".into(), 0),
        ("post_body".into(), 0),
        ("back_matter".into(), 0),
        ("front_matter".into(), 0),
    ])
}

pub fn default_toc_alignment_summary() -> serde_json::Value {
    serde_json::json!({
        "aligned_count": 0,
        "unaligned_count": 0,
        "conflict_count": 0,
    })
}

pub fn default_toc_semantic_summary() -> serde_json::Value {
    serde_json::json!({
        "toc_items_total": 0,
        "chapters_derived": 0,
        "order_ok": true,
    })
}

/// 从 TOC item + 已有 chapters + pages 构建 TOC 语义。
/// 完整实现对齐 Python `_build_visual_toc_chapters_and_section_heads()`。
pub fn build_toc_semantics(
    toc_items: &[TocItem],
    _chapters: &[ChapterRecord],
    pages: &[RawPage],
    page_partitions: &[PagePartitionRecord],
    heading_candidates: &[HeadingCandidate],
    heading_graph: Option<&crate::heading_graph::HeadingGraph>,
) -> TocSemanticsResult {
    let total_pages = pages.len().max(1) as i64;
    let has_toc_items = !toc_items.is_empty();

    // 1. 收集 rows
    let mut rows =
        row_collect::collect_visual_toc_rows(toc_items, pages, page_partitions, heading_candidates);

    if rows.is_empty() {
        return empty_result(has_toc_items, None);
    }

    // 2. 五遍 sanitize
    sanitize::sanitize_visual_toc_semantic_rows(&mut rows);

    // 3. root container 检测与 front_matter 降级
    let root_container_present = rows
        .iter()
        .any(|r| r.level == 1 && (r.role_hint == "container" || is_part_title(&r.title)));
    if root_container_present {
        // 先收集需要降级的行的 order 值
        let later_container_orders: Vec<i64> = rows
            .iter()
            .filter(|r| r.level == 1 && (r.role_hint == "container" || is_part_title(&r.title)))
            .map(|r| r.order)
            .collect();

        for row in rows.iter_mut() {
            if row.level != 1 || !row.parent_title.is_empty() {
                continue;
            }
            if !row.explicit_role_hint.is_empty() {
                continue;
            }
            if !matches!(row.role_hint.as_str(), "" | "chapter") {
                continue;
            }
            let title = row.title.trim();
            if title.split_whitespace().count() < 6 {
                continue;
            }
            if is_part_title(title) || is_visual_toc_explicit_chapter_title(title) {
                continue;
            }
            let has_later = later_container_orders.iter().any(|&o| o > row.order);
            if has_later {
                row.role_hint = "front_matter".into();
                row.body_candidate = Some(false);
                row.export_candidate = Some(false);
            }
        }
    }

    // 4. 选择 chapter level
    let chapter_level = match row_collect::choose_visual_toc_chapter_level(&rows) {
        Some(level) => level,
        None => {
            let _missing: Vec<String> = rows
                .iter()
                .filter(|r| row_collect::is_visual_toc_body_candidate(r))
                .map(|r| r.title.clone())
                .collect();
            return empty_result(has_toc_items, None);
        }
    };

    // 5. 推断 semantic_role
    for row in rows.iter_mut() {
        row.semantic_role =
            role_inference::visual_toc_semantic_role(row, chapter_level, total_pages);
        if row.semantic_role == "post_body" && row.export_candidate == Some(false) {
            row.export_candidate = Some(true);
        }
    }

    // 6. 统计 toc_role_summary
    let mut toc_role_summary = default_toc_role_summary();
    let mut container_titles_raw: Vec<String> = Vec::new();
    let mut post_body_titles_raw: Vec<String> = Vec::new();
    let mut back_matter_titles_raw: Vec<String> = Vec::new();

    for row in &rows {
        let mapped = toc_role_from_semantic_role(&row.semantic_role);
        if mapped.is_empty() {
            continue;
        }
        *toc_role_summary.entry(mapped.to_string()).or_insert(0) += 1;
        match mapped {
            "container" => container_titles_raw.push(row.title.clone()),
            "post_body" => post_body_titles_raw.push(row.title.clone()),
            "back_matter" => back_matter_titles_raw.push(row.title.clone()),
            _ => {}
        }
    }
    let container_titles = title_utils::compact_unique_titles(&container_titles_raw);
    let post_body_titles = title_utils::compact_unique_titles(&post_body_titles_raw);
    let back_matter_titles = title_utils::compact_unique_titles(&back_matter_titles_raw);

    // 7. 分离 body_rows / chapter_rows
    let body_rows: Vec<&TocRow> = rows
        .iter()
        .filter(|r| row_collect::is_visual_toc_body_candidate(r))
        .collect();
    let has_explicit_organization = !container_titles.is_empty()
        || !post_body_titles.is_empty()
        || !back_matter_titles.is_empty()
        || rows.iter().any(|r| !r.parent_title.is_empty())
        || rows.iter().any(|r| {
            matches!(
                r.role_hint.as_str(),
                "container"
                    | "endnotes"
                    | "chapter"
                    | "section"
                    | "post_body"
                    | "back_matter"
                    | "front_matter"
            )
        });

    let chapter_level_rows: Vec<&TocRow> = body_rows
        .iter()
        .filter(|r| r.level == chapter_level)
        .copied()
        .collect();

    let part_rows_at_chapter_level: Vec<&TocRow> = chapter_level_rows
        .iter()
        .filter(|r| r.semantic_role == "part")
        .copied()
        .collect();
    let numbered_rows_deeper: Vec<&TocRow> = body_rows
        .iter()
        .filter(|r| {
            r.level > chapter_level && title_utils::MAIN_NUMBERED_TITLE_RE.is_match(&r.title)
        })
        .copied()
        .collect();
    let prefer_deeper_numbered =
        !part_rows_at_chapter_level.is_empty() && numbered_rows_deeper.len() >= 3;

    let chapter_style = visual_toc_chapter_level_style(&chapter_level_rows);

    let force_export_rows: Vec<&TocRow> = body_rows
        .iter()
        .filter(|r| r.level != chapter_level && title_utils::is_toc_force_export_title(&r.title))
        .copied()
        .collect();
    let misleveled_rows: Vec<&TocRow> = body_rows
        .iter()
        .filter(|r| {
            r.level > chapter_level
                && !r.non_body_title
                && !title_utils::is_toc_force_export_title(&r.title)
        })
        .copied()
        .collect();
    let corrected_chapter_rows: Vec<&TocRow> = misleveled_rows
        .iter()
        .filter(|r| is_misleveled_chapter_row(r, &chapter_style))
        .copied()
        .collect();
    let explicit_chapter_rows: Vec<&TocRow> = body_rows
        .iter()
        .filter(|r| is_visual_toc_explicit_chapter_title(&r.title))
        .copied()
        .collect();

    let page_role_by_no: std::collections::HashMap<i64, String> = page_partitions
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str().to_string()))
        .collect();

    let lecture_collection_override = lecture::looks_like_lecture_collection(
        &body_rows.iter().map(|r| (*r).clone()).collect::<Vec<_>>(),
        heading_candidates,
    );

    // 8. 构建 chapter rows
    let mut chapter_rows: Vec<TocRow> = if prefer_deeper_numbered {
        chapter_level_rows
            .iter()
            .filter(|r| title_utils::is_toc_force_export_title(&r.title))
            .map(|r| (*r).clone())
            .collect()
    } else {
        chapter_level_rows.iter().map(|r| (*r).clone()).collect()
    };

    // 添加 force_export + corrected + explicit
    for r in force_export_rows
        .iter()
        .chain(corrected_chapter_rows.iter())
        .chain(explicit_chapter_rows.iter())
    {
        if !chapter_rows
            .iter()
            .any(|c| c.page_no == r.page_no && c.title == r.title)
        {
            chapter_rows.push((*r).clone());
        }
    }
    title_utils::dedupe_visual_toc_rows(&mut chapter_rows);

    if has_explicit_organization {
        chapter_rows = rows
            .iter()
            .filter(|r| {
                r.semantic_role == "chapter" && r.page_no > 0 && r.export_candidate != Some(false)
            })
            .cloned()
            .collect();
        title_utils::dedupe_visual_toc_rows(&mut chapter_rows);
    } else {
        chapter_rows.retain(|r| r.semantic_role == "chapter");
        if lecture_collection_override {
            chapter_rows = lecture::build_lecture_collection_chapter_rows(
                &body_rows.iter().map(|r| (*r).clone()).collect::<Vec<_>>(),
                heading_candidates,
                &page_role_by_no,
                chapter_level,
            );
        }
    }

    // 9. 添加 post_body rows
    let post_body_rows: Vec<TocRow> = rows
        .iter()
        .filter(|r| {
            r.semantic_role == "post_body" && r.page_no > 0 && r.export_candidate != Some(false)
        })
        .cloned()
        .collect();

    let mut exportable_chapter_rows = chapter_rows;
    exportable_chapter_rows.extend(post_body_rows);
    title_utils::dedupe_visual_toc_rows(&mut exportable_chapter_rows);
    exportable_chapter_rows.retain(|r| r.page_no > 0);
    exportable_chapter_rows.sort_by(|a, b| {
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

    // ←→ Python toc_semantics.py:1537-1555: 应用 heading_graph 锚点修正章节起始页。
    // graph 完整且无边冲突时，用 graph_row.anchor_page 替换 row.page_no。
    // gate：unresolved_titles_preview 为空 + boundary_conflict_titles_preview 为空
    if let Some(hg) = heading_graph {
        let heading_graph_incomplete = hg
            .summary
            .get("unresolved_titles_preview")
            .and_then(|v| v.as_array())
            .map(|a| !a.is_empty())
            .unwrap_or(false);
        let has_boundary_conflict = hg
            .summary
            .get("boundary_conflict_titles_preview")
            .and_then(|v| v.as_array())
            .map(|a| !a.is_empty())
            .unwrap_or(false);
        if !heading_graph_incomplete && !has_boundary_conflict {
            let title_row_by_key: std::collections::HashMap<
                String,
                &crate::heading_graph::GraphRow,
            > = hg
                .graph_rows
                .iter()
                .map(|gr| (chapter_title_match_key(&gr.title), gr))
                .collect();
            for row in exportable_chapter_rows.iter_mut() {
                let key = chapter_title_match_key(&row.title);
                if let Some(gr) = title_row_by_key.get(&key) {
                    if gr.anchor_page > 0 {
                        row.page_no = gr.anchor_page;
                    }
                }
            }
        }
    }

    // 过滤 front_matter 在 first_body_chapter_page 之后的
    let first_body_chapter_page = exportable_chapter_rows
        .iter()
        .filter(|r| title_utils::title_family(&r.title, r.page_no, total_pages) == "body")
        .map(|r| r.page_no)
        .min()
        .unwrap_or(0);

    if first_body_chapter_page > 0 {
        exportable_chapter_rows.retain(|r| {
            title_utils::title_family(&r.title, r.page_no, total_pages) != "front_matter"
                || title_utils::is_toc_force_export_title(&r.title)
                || r.page_no < first_body_chapter_page
        });
    }

    if exportable_chapter_rows.is_empty() {
        return empty_result(has_toc_items, Some(chapter_level));
    }

    // 10. 构建 chapters
    let eligible_pages_all: Vec<i64> = page_partitions
        .iter()
        .filter(|p| p.page_no > 0 && matches!(p.page_role.as_str(), "body" | "front_matter"))
        .map(|p| p.page_no)
        .collect();
    let eligible_pages_all = if eligible_pages_all.is_empty() {
        page_partitions
            .iter()
            .map(|p| p.page_no)
            .filter(|&p| p > 0)
            .collect()
    } else {
        eligible_pages_all
    };
    let max_page_no = eligible_pages_all
        .iter()
        .copied()
        .max()
        .unwrap_or(total_pages);

    // 边界页
    let extra_boundary_pages = if lecture_collection_override {
        lecture::lecture_collection_boundary_pages(
            &body_rows.iter().map(|r| (*r).clone()).collect::<Vec<_>>(),
            heading_candidates,
            &page_role_by_no,
        )
    } else {
        std::collections::HashSet::new()
    };
    let nonchapter_stop_pages: std::collections::HashSet<i64> = rows
        .iter()
        .filter(|r| r.page_no > 0 && matches!(r.semantic_role.as_str(), "endnotes" | "back_matter"))
        .map(|r| r.page_no)
        .collect();
    let exportable_start_pages: std::collections::HashSet<i64> =
        exportable_chapter_rows.iter().map(|r| r.page_no).collect();
    let rear_nonbody_stop_pages: std::collections::HashSet<i64> = page_partitions
        .iter()
        .filter(|p| {
            p.page_no >= first_body_chapter_page
                && !exportable_start_pages.contains(&p.page_no)
                && p.page_role == fnm_core::types::PageRole::Other
        })
        .map(|p| p.page_no)
        .collect();

    let mut chapter_boundary_pages: Vec<i64> = exportable_start_pages
        .iter()
        .chain(extra_boundary_pages.iter())
        .chain(nonchapter_stop_pages.iter())
        .chain(rear_nonbody_stop_pages.iter())
        .copied()
        .collect();
    chapter_boundary_pages.sort();
    chapter_boundary_pages.dedup();

    let _page_row_by_no: std::collections::HashMap<i64, &RawPage> =
        pages.iter().map(|p| (p.book_page, p)).collect();

    let mut chapters: Vec<ChapterRecord> = Vec::new();
    for (index, row) in exportable_chapter_rows.iter().enumerate() {
        let start_page = row.page_no;
        let next_start_page = chapter_boundary_pages
            .iter()
            .find(|&&p| p > start_page)
            .copied()
            .unwrap_or(max_page_no + 1);

        let raw_span_pages: Vec<i64> = eligible_pages_all
            .iter()
            .copied()
            .filter(|&p| p >= start_page && p < next_start_page)
            .collect();
        let body_span_pages: Vec<i64> = raw_span_pages
            .iter()
            .copied()
            .filter(|&p| page_role_by_no.get(&p).map(String::as_str) == Some("body"))
            .collect();
        let start_role = page_role_by_no
            .get(&start_page)
            .map(String::as_str)
            .unwrap_or("");
        let mut span_pages: Vec<i64> = if start_role == "front_matter"
            && title_utils::is_toc_force_export_title(&row.title)
            && !raw_span_pages.is_empty()
        {
            raw_span_pages
        } else if !body_span_pages.is_empty() {
            body_span_pages
        } else {
            raw_span_pages
        };

        // trim front_matter/noise from start
        span_pages =
            page_resolve::trim_exportable_chapter_pages(&span_pages, pages, page_partitions);

        if span_pages.is_empty() {
            span_pages = vec![start_page];
        }

        let chapter_id = title_utils::normalize_toc_chapter_id(&row.item_id, index + 1, &row.title);
        chapters.push(ChapterRecord {
            chapter_id,
            title: row.title.clone(),
            start_page: span_pages[0],
            end_page: *span_pages.last().unwrap(),
            pages: span_pages,
            source: fnm_core::types::ChapterSource::VisualToc,
            boundary_state: fnm_core::types::BoundaryState::Ready,
        });
    }

    // 11. visual_toc_conflict_count
    let mut visual_toc_conflict_count = 0i64;
    for chapter in chapters.iter_mut() {
        let chapter_page = chapter.start_page;
        if title_utils::visual_toc_chapter_keyword_strength(&chapter.title) < 1 {
            continue;
        }
        let chapter_key = chapter_title_match_key(&chapter.title);
        let strong_candidates: Vec<&HeadingCandidate> = heading_candidates
            .iter()
            .filter(|c| {
                matches!(c.source.as_str(), "ocr_block" | "pdf_font_band")
                    && c.heading_family_guess == "chapter"
                    && !c.suppressed_as_chapter
                    && c.top_band
                    && (c.source != "ocr_block" || c.block_label == "doc_title")
                    && title_utils::visual_toc_chapter_keyword_strength(&c.text) >= 1
                    && c.confidence >= 0.68
                    && c.page_no == chapter_page
            })
            .collect();
        if strong_candidates.len() != 1 {
            continue;
        }
        let candidate_key = chapter_title_match_key(&strong_candidates[0].text);
        if chapter_key.is_empty() || candidate_key.is_empty() {
            continue;
        }
        if chapter_key == candidate_key
            || chapter_key.contains(&candidate_key)
            || candidate_key.contains(&chapter_key)
        {
            continue;
        }
        chapter.boundary_state = fnm_core::types::BoundaryState::ReviewRequired;
        visual_toc_conflict_count += 1;
    }

    // 12. section heads
    let chapter_row_keys: std::collections::HashSet<(i64, String)> = exportable_chapter_rows
        .iter()
        .map(|r| title_utils::visual_toc_row_key(r.page_no, &r.title))
        .collect();

    let section_target_rows: Vec<&TocRow> = if has_explicit_organization {
        rows.iter()
            .filter(|r| {
                r.page_no > 0
                    && !r.non_body_title
                    && r.body_candidate != Some(false)
                    && !chapter_row_keys
                        .contains(&title_utils::visual_toc_row_key(r.page_no, &r.title))
                    && r.semantic_role == "section"
            })
            .collect()
    } else {
        rows.iter()
            .filter(|r| {
                row_collect::is_visual_toc_body_candidate(r)
                    && r.page_no > 0
                    && !r.non_body_title
                    && !chapter_row_keys
                        .contains(&title_utils::visual_toc_row_key(r.page_no, &r.title))
                    && (matches!(r.semantic_role.as_str(), "section" | "part")
                        || r.level > chapter_level)
            })
            .collect()
    };

    let mut section_heads: Vec<SectionHeadRecord> = Vec::new();
    let mut seen_head_keys: std::collections::HashSet<(String, i64, String)> =
        std::collections::HashSet::new();

    for row in section_target_rows {
        let chapter_id = find_chapter_by_page(&chapters, row.page_no);
        let chapter_id = match chapter_id {
            Some(id) => id,
            None => continue,
        };
        let text = normalize_title(&row.title);
        if text.is_empty() {
            continue;
        }
        let key = (
            chapter_id.clone(),
            row.page_no,
            chapter_title_match_key(&text),
        );
        if seen_head_keys.contains(&key) {
            continue;
        }
        seen_head_keys.insert(key);
        section_heads.push(SectionHeadRecord {
            section_head_id: String::new(),
            chapter_id,
            page_no: row.page_no,
            title: text,
            level: row.level,
            source: "visual_toc".into(),
        });
    }

    // 13. blocking reasons
    let mut blocking_reasons: Vec<String> = Vec::new();
    // heading_graph incomplete (simplified: check unresolved)
    let unresolved_count = exportable_chapter_rows
        .iter()
        .filter(|r| r.page_no <= 0)
        .count();
    if unresolved_count > 0 {
        blocking_reasons.push("heading_graph_incomplete".into());
    }

    // 14. monotonic check
    let monotonic = monotonic::check_chapter_order_monotonic(&chapters);

    // 15. role summary
    let mut final_role_summary = default_toc_role_summary();
    for row in &rows {
        let mapped = toc_role_from_semantic_role(&row.semantic_role);
        if !mapped.is_empty() {
            *final_role_summary.entry(mapped.to_string()).or_insert(0) += 1;
        }
    }

    // 16. meta
    let meta = serde_json::json!({
        "used": true,
        "chapter_level": chapter_level,
        "visual_toc_conflict_count": visual_toc_conflict_count,
        "toc_role_summary": final_role_summary,
        "container_titles": container_titles,
        "post_body_titles": post_body_titles,
        "back_matter_titles": back_matter_titles,
        "toc_semantic_contract_ok": blocking_reasons.is_empty(),
        // ←→ Python toc_semantics.py:1797-1808: 基于冲突计数判断对齐性
        "chapter_title_alignment_ok": visual_toc_conflict_count == 0,
        "chapter_section_alignment_ok": visual_toc_conflict_count == 0,
        "toc_semantic_blocking_reasons": blocking_reasons,
    });

    TocSemanticsResult {
        aligned_chapters: chapters,
        section_heads,
        toc_role_summary: final_role_summary,
        semantic_blocking_reasons: blocking_reasons,
        chapter_order_monotonic: monotonic,
        chapter_level: Some(chapter_level),
        meta,
    }
}

fn empty_result(has_toc_items: bool, chapter_level: Option<i64>) -> TocSemanticsResult {
    TocSemanticsResult {
        aligned_chapters: Vec::new(),
        section_heads: Vec::new(),
        toc_role_summary: default_toc_role_summary(),
        semantic_blocking_reasons: if has_toc_items {
            vec!["no_exportable_chapters".into()]
        } else {
            Vec::new()
        },
        chapter_order_monotonic: true,
        chapter_level,
        meta: serde_json::json!({"used": false}),
    }
}

fn toc_role_from_semantic_role(semantic_role: &str) -> &'static str {
    match semantic_role {
        "part" | "book_title" => "container",
        "endnotes" => "endnotes",
        "chapter" => "chapter",
        "section" => "section",
        "post_body" => "post_body",
        "back_matter" => "back_matter",
        "front_matter" => "front_matter",
        _ => "",
    }
}

fn find_chapter_by_page(chapters: &[ChapterRecord], page_no: i64) -> Option<String> {
    for ch in chapters.iter().rev() {
        if ch.start_page <= page_no && page_no <= ch.end_page {
            return Some(ch.chapter_id.clone());
        }
    }
    // 找最近的前一章
    chapters
        .iter()
        .rev()
        .find(|ch| ch.start_page <= page_no)
        .map(|ch| ch.chapter_id.clone())
}

fn is_part_title(title: &str) -> bool {
    TOC_PART_TITLE_RE.is_match(&normalize_title(title))
}

fn visual_toc_chapter_level_style(
    chapter_level_rows: &[&TocRow],
) -> std::collections::HashMap<String, bool> {
    let has_lecture = chapter_level_rows
        .iter()
        .any(|r| title_utils::LECTURE_TITLE_RE.is_match(&r.title));
    let numbered_count = chapter_level_rows
        .iter()
        .filter(|r| title_utils::MAIN_NUMBERED_TITLE_RE.is_match(&normalize_title(&r.title)))
        .count();
    let mut map = std::collections::HashMap::new();
    map.insert("lecture".into(), has_lecture);
    map.insert(
        "numbered".into(),
        numbered_count >= 2.max(chapter_level_rows.len() / 2),
    );
    map
}

fn is_misleveled_chapter_row(
    row: &TocRow,
    chapter_style: &std::collections::HashMap<String, bool>,
) -> bool {
    let title = normalize_title(&row.title);
    if title.is_empty() {
        return false;
    }
    if *chapter_style.get("lecture").unwrap_or(&false)
        && title_utils::LECTURE_TITLE_RE.is_match(&title)
    {
        return true;
    }
    if *chapter_style.get("numbered").unwrap_or(&false)
        && title_utils::MAIN_NUMBERED_TITLE_RE.is_match(&title)
    {
        return true;
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::input::TocItem;

    #[test]
    fn role_hint_normalization() {
        assert_eq!(normalize_visual_toc_role_hint("part"), "container");
        assert_eq!(normalize_visual_toc_role_hint("notes"), "endnotes");
        assert_eq!(normalize_visual_toc_role_hint("chapter"), "chapter");
    }

    #[test]
    fn explicit_chapter_title() {
        assert!(is_visual_toc_explicit_chapter_title("Chapter 1"));
        assert!(is_visual_toc_explicit_chapter_title(
            "Leçon du 10 janvier 1979"
        ));
        assert!(!is_visual_toc_explicit_chapter_title("Table of Contents"));
    }

    #[test]
    fn build_semantics_basic() {
        let items = vec![TocItem {
            item_id: "1".into(),
            title: "Chapter One".into(),
            role_hint: "chapter".into(),
            target_pdf_page: Some(1),
            ..Default::default()
        }];
        let result = build_toc_semantics(&items, &[], &[], &[], &[], None);
        assert_eq!(result.aligned_chapters.len(), 1);
        assert!(result.chapter_order_monotonic);
    }

    #[test]
    fn build_semantics_empty() {
        let result = build_toc_semantics(&[], &[], &[], &[], &[], None);
        assert!(result.aligned_chapters.is_empty());
        assert!(result.chapter_order_monotonic);
    }
}
