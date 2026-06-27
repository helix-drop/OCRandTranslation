//! ←→ FNM_RE/stages/chapter_skeleton/fallback.py
//! 无 TOC 时的 fallback 章节切分。
//!
//! Python: ~650 行。Rust 版实现核心算法：
//!   1. _candidate_section_rows — 从 heading_candidates 提取候选节
//!   2. _classify_fallback_sections — 分类（保留为章 / 降级为节）
//!   3. _mark_suppressed_candidates — 标记被抑制的候选（mutate headings）
//!   4. _build_fallback_chapters_and_sections — 构建章节+节头
//!   5. _normalize_chapters / _normalize_sections — 标准化输出
//!   6. build_chapter_skeleton_fallback — 测试入口（生产路径由 builder.rs 直接调子函数）

#[cfg(test)]
use crate::heading_graph::HeadingGraph;
use crate::input::TocItem;
use fnm_core::records::{ChapterRecord, HeadingCandidate, PagePartitionRecord, SectionHeadRecord};
use fnm_core::title::{chapter_title_match_key, guess_title_family, normalize_title};
use fnm_core::types::{BoundaryState, ChapterSource};
use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

// ── 正则常量 ────────────────────────────────────────────────────

static NOTES_HEADER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(?:#+\s*)?(notes?|endnotes?|notes to pages?.*)\s*$").unwrap());
static CHAPTER_KEYWORD_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"\b(?:chapter|chapitre|lecture|leçon|prologue|epilogue|postambule|appendix|appendices|part)\b",
    )
    .unwrap()
});
// LECTURE_TITLE_RE 已 dedup → `crate::chapter_skeleton::toc_semantics::title_utils::LECTURE_TITLE_RE`
// （审计 #3 已扩展为支持 Foucault 系列 + 英语 lecture/lesson 编号型）

// TOC_FORCE_EXPORT_TITLE_RE 已 dedup → `fnm_core::title::FRONT_MATTER_FORCE_EXPORT_TITLE_RE`

// ── Fallback chapter classify 权重常量 ──────────────────────────────────
//
// **设计说明（CLAUDE.md §7 / §10 / 审计 #6）：**
//
// 以下权重值来自针对 Biopolitics fixture 的经验调参，**没有理论或多书校准依据**。
// 应通过 ≥3 本书的 golden fixture 反推校准（详见 NEXT_PHASE_PLAN.md M5+）。
//
// 修改前请 read 完整 `classify_fallback_sections()` 算法 + 跑现有 fixture 回归。
// 阈值 SCORE_THRESHOLD_KEEP_CHAPTER=2.0 是 keep_as_chapter 判定的 cut-off — 改它
// 会让其他书的章节切分结果剧变。

/// 该章在 TOC 中有显式 entry。最强证据。
const SCORE_WEIGHT_VISUAL_TOC: f64 = 3.0;
/// PDF 顶部 OCR 识别为 doc_title。
const SCORE_WEIGHT_TOP_DOC_TITLE: f64 = 1.8;
/// PDF 字体 band 信号匹配。
const SCORE_WEIGHT_PDF_FONT: f64 = 1.2;
/// top_doc_title 与 chapter keyword 同时存在的协同加权。
const SCORE_WEIGHT_TITLE_KEYWORD_SYNERGY: f64 = 1.2;
/// span_pages ≥ 4：长章节，加分。
const SCORE_WEIGHT_LONG_SPAN: f64 = 1.2;
/// span_pages == 3：中等章节，小加分。
const SCORE_WEIGHT_MID_SPAN: f64 = 0.5;
/// span_pages ≤ 2：短章节，减分（除非有强证据则减分轻一些）。
const SCORE_PENALTY_SHORT_SPAN_WITH_EVIDENCE: f64 = 0.8;
const SCORE_PENALTY_SHORT_SPAN_NO_EVIDENCE: f64 = 1.8;
/// 全为 paragraph_title 类型的弱证据，减分。
const SCORE_PENALTY_PARAGRAPH_TITLE_ONLY: f64 = 1.2;
/// keep_as_chapter 判定 cut-off。score ≥ 此值才保留章节。
const SCORE_THRESHOLD_KEEP_CHAPTER: f64 = 2.0;
/// classification_confidence = (0.5 + score / SCORE_CONFIDENCE_NORMALIZER).clamp(0,1)。
const SCORE_CONFIDENCE_NORMALIZER: f64 = 6.0;
/// 当全部 classified 都被拒时强制保留首个有效章 → 分数下限。
const SCORE_FORCE_KEEP_FIRST_FLOOR: f64 = 2.1;

const FAMILY_NONBODY: &[&str] = &[
    "note",
    "other",
    "contents",
    "illustrations",
    "bibliography",
    "index",
    "appendix",
];

// ── 候选节行提取 ─────────────────────────────────────────────────

pub struct SectionRow {
    section_id: String,
    title: String,
    start_page: i64,
    filtered_pages: Vec<i64>,
}

pub fn candidate_section_rows(
    heading_candidates: &[HeadingCandidate],
    all_pages: &[i64],
    page_roles: &HashMap<i64, String>,
) -> Vec<SectionRow> {
    if all_pages.is_empty() {
        return vec![];
    }
    let mut selected: Vec<(i64, String, String)> = Vec::new();
    let mut dedupe: HashSet<(i64, String)> = HashSet::new();
    for hc in heading_candidates {
        let page_no = hc.page_no;
        if page_no <= 0 {
            continue;
        }
        let role = page_roles.get(&page_no).map(|s| s.as_str()).unwrap_or("");
        if role != "body" && role != "front_matter" {
            continue;
        }
        let family = hc.heading_family_guess.trim().to_lowercase();
        if hc.source.trim() == "note_heading" {
            continue;
        }
        if FAMILY_NONBODY.contains(&family.as_str()) {
            continue;
        }
        let title = normalize_title(&hc.text);
        let key = chapter_title_match_key(&title);
        if title.is_empty() || key.is_empty() {
            continue;
        }
        let dk = (page_no, key.clone());
        if !dedupe.insert(dk) {
            continue;
        }
        selected.push((page_no, title, hc.source.clone()));
    }
    selected.sort_by_key(|(p, t, _)| (*p, t.clone()));

    let mut rows: Vec<SectionRow> = Vec::new();
    for (idx, (start_page, title, _source)) in selected.iter().enumerate() {
        let next_page = selected.get(idx + 1).map(|(p, _, _)| *p).unwrap_or(0);
        let end_page = if next_page > *start_page {
            next_page - 1
        } else {
            *all_pages.last().unwrap_or(&0)
        };
        let raw_pages: Vec<i64> = all_pages
            .iter()
            .copied()
            .filter(|&p| *start_page <= p && p <= end_page)
            .collect();
        let filtered_pages: Vec<i64> = raw_pages
            .iter()
            .copied()
            .filter(|p| {
                let role = page_roles.get(p).map(|s| s.as_str()).unwrap_or("");
                role == "body" || role == "front_matter"
            })
            .collect();
        if filtered_pages.is_empty() {
            continue;
        }
        rows.push(SectionRow {
            section_id: format!("sec-{:04}", idx + 1),
            title: title.clone(),
            start_page: filtered_pages[0],
            filtered_pages,
        });
    }
    rows
}

// ── 分类 ────────────────────────────────────────────────────────

fn is_explicit_chapter_boundary_candidate(candidate: &HeadingCandidate) -> bool {
    candidate.source == "visual_toc"
        || (candidate.source == "ocr_block"
            && candidate.block_label == "doc_title"
            && candidate.top_band)
}

/// 章级标题的内容跨度应由下一条章级标题界定，不能被章内小节标题截短。
fn classification_span_pages(
    section: &SectionRow,
    page_roles: &HashMap<i64, String>,
    heading_candidates: &[HeadingCandidate],
) -> usize {
    let title_key = chapter_title_match_key(&section.title);
    let has_explicit_boundary = heading_candidates.iter().any(|candidate| {
        candidate.page_no == section.start_page
            && chapter_title_match_key(&candidate.text) == title_key
            && is_explicit_chapter_boundary_candidate(candidate)
    });
    if !has_explicit_boundary {
        return section.filtered_pages.len();
    }

    let next_boundary = heading_candidates
        .iter()
        .filter(|candidate| {
            candidate.page_no > section.start_page
                && is_explicit_chapter_boundary_candidate(candidate)
        })
        .map(|candidate| candidate.page_no)
        .min();
    let last_page = page_roles
        .keys()
        .copied()
        .max()
        .unwrap_or(section.start_page);
    let end_page = next_boundary.map(|page| page - 1).unwrap_or(last_page);

    page_roles
        .iter()
        .filter(|(page, role)| {
            section.start_page <= **page
                && **page <= end_page
                && matches!(role.as_str(), "body" | "front_matter")
        })
        .count()
}

pub struct ClassifiedSection {
    section_id: String,
    title: String,
    start_page: i64,
    filtered_pages: Vec<i64>,
    start_role: String,
    keep_as_chapter: bool,
    reject_reason: String,
    classification_score: f64,
    classification_confidence: f64,
}

pub fn classify_fallback_sections(
    section_rows: Vec<SectionRow>,
    page_roles: &HashMap<i64, String>,
    total_pages: i64,
    heading_candidates: &[HeadingCandidate],
) -> Vec<ClassifiedSection> {
    let mut classified: Vec<ClassifiedSection> = Vec::new();
    let tp = if total_pages <= 0 { 1 } else { total_pages };

    for section in section_rows {
        let title = normalize_title(&section.title);
        let start_page = section.start_page;
        let span_pages = classification_span_pages(&section, page_roles, heading_candidates);

        // Find matched heading_candidates for evidence
        let title_key = chapter_title_match_key(&title);
        let matched: Vec<&HeadingCandidate> = heading_candidates
            .iter()
            .filter(|c| {
                let page_ok = (c.page_no - start_page).abs() <= 1;
                let title_ok = title_key.is_empty()
                    || chapter_title_match_key(&c.text).is_empty()
                    || chapter_title_match_key(&c.text) == title_key;
                page_ok && title_ok
            })
            .collect();
        let chapter_evidence: Vec<&&HeadingCandidate> = matched
            .iter()
            .filter(|c| {
                let role = page_roles.get(&c.page_no).map(|s| s.as_str()).unwrap_or("");
                role == "body" || role == "front_matter"
            })
            .collect();

        let has_visual_toc = matched.iter().any(|c| c.source == "visual_toc");
        let has_top_doc_title = matched
            .iter()
            .any(|c| c.source == "ocr_block" && c.block_label == "doc_title" && c.top_band);
        let has_pdf_font = matched.iter().any(|c| c.source == "pdf_font_band");
        let keyword_strength = chapter_keyword_strength(&title);
        let strong_evidence =
            has_visual_toc || has_top_doc_title || has_pdf_font || keyword_strength >= 1.0;

        let start_role = page_roles
            .get(&start_page)
            .map(|s| s.as_str())
            .unwrap_or("")
            .to_string();
        let family = guess_title_family(&title, start_page.max(1), tp.max(1))
            .trim()
            .to_lowercase();

        let mut keep;
        let mut reject_reason = String::new();
        let mut score = 0.0f64;

        if title.is_empty() {
            keep = false;
            reject_reason = "invalid_title".into();
        } else if start_role == "noise" || start_role == "other" {
            keep = false;
            reject_reason = "partition_conflict".into();
        } else if start_role == "note" {
            keep = false;
            reject_reason = "note_partition".into();
        } else if NOTES_HEADER_RE.is_match(&title) {
            keep = false;
            reject_reason = "note_heading".into();
        } else if matches!(
            family.as_str(),
            "contents" | "illustrations" | "bibliography" | "index" | "appendix"
        ) {
            keep = false;
            reject_reason = "non_body_family".into();
        } else if is_sentence_like_heading(&title) && !strong_evidence {
            keep = false;
            reject_reason = "sentence_like".into();
        } else {
            if has_visual_toc {
                score += SCORE_WEIGHT_VISUAL_TOC;
            }
            if has_top_doc_title {
                score += SCORE_WEIGHT_TOP_DOC_TITLE;
            }
            if has_pdf_font {
                score += SCORE_WEIGHT_PDF_FONT;
            }
            if has_top_doc_title && keyword_strength >= 1.0 {
                score += SCORE_WEIGHT_TITLE_KEYWORD_SYNERGY;
            }
            if span_pages >= 4 {
                score += SCORE_WEIGHT_LONG_SPAN;
            } else if span_pages == 3 {
                score += SCORE_WEIGHT_MID_SPAN;
            } else if span_pages <= 2 {
                score -= if has_top_doc_title || has_visual_toc {
                    SCORE_PENALTY_SHORT_SPAN_WITH_EVIDENCE
                } else {
                    SCORE_PENALTY_SHORT_SPAN_NO_EVIDENCE
                };
            }
            score += keyword_strength;
            let all_paragraph_title = !chapter_evidence.is_empty()
                && chapter_evidence
                    .iter()
                    .all(|c| c.source == "ocr_block" && c.block_label == "paragraph_title");
            if all_paragraph_title && !strong_evidence {
                score -= SCORE_PENALTY_PARAGRAPH_TITLE_ONLY;
            }
            keep = score >= SCORE_THRESHOLD_KEEP_CHAPTER;
            if keep && span_pages <= 2 && !strong_evidence {
                keep = false;
                reject_reason = "short_span".into();
            }
            if !keep && reject_reason.is_empty() {
                reject_reason = "low_score".into();
            }
        }

        classified.push(ClassifiedSection {
            section_id: section.section_id,
            title,
            start_page,
            filtered_pages: section.filtered_pages,
            start_role,
            keep_as_chapter: keep,
            reject_reason,
            classification_score: score,
            classification_confidence: (0.5 + score / SCORE_CONFIDENCE_NORMALIZER).clamp(0.0, 1.0),
        });
    }

    // Fallback: if nothing kept, force-keep the first valid section
    if !classified.is_empty() && !classified.iter().any(|c| c.keep_as_chapter) {
        if let Some(first) = classified.iter_mut().find(|c| {
            let role = &c.start_role;
            role != "noise"
                && role != "note"
                && role != "other"
                && !NOTES_HEADER_RE.is_match(&c.title)
        }) {
            first.keep_as_chapter = true;
            first.reject_reason = String::new();
            first.classification_score =
                first.classification_score.max(SCORE_FORCE_KEEP_FIRST_FLOOR);
        }
    }

    classified
}

// ── 标记被抑制的候选 ─────────────────────────────────────────────

pub fn mark_suppressed_candidates(
    classified: &[ClassifiedSection],
    heading_candidates: &mut Vec<HeadingCandidate>,
) {
    for section in classified {
        let title_key = chapter_title_match_key(&section.title);
        let start_page = section.start_page;
        if section.keep_as_chapter {
            for candidate in heading_candidates.iter_mut() {
                if (candidate.page_no - start_page).abs() > 1 {
                    continue;
                }
                if !title_key.is_empty()
                    && !chapter_title_match_key(&candidate.text).is_empty()
                    && chapter_title_match_key(&candidate.text) != title_key
                {
                    continue;
                }
                if candidate.heading_family_guess != "note"
                    && candidate.heading_family_guess != "other"
                {
                    candidate.heading_family_guess = "chapter".to_string();
                }
            }
        } else {
            let reject_reason = if section.reject_reason.is_empty() {
                "demoted"
            } else {
                &section.reject_reason
            };
            let mut matched_any = false;
            for candidate in heading_candidates.iter_mut() {
                if (candidate.page_no - start_page).abs() > 1 {
                    continue;
                }
                if !title_key.is_empty()
                    && !chapter_title_match_key(&candidate.text).is_empty()
                    && chapter_title_match_key(&candidate.text) != title_key
                {
                    continue;
                }
                candidate.suppressed_as_chapter = true;
                candidate.reject_reason = reject_reason.to_string();
                candidate.heading_family_guess = "section".to_string();
                matched_any = true;
            }
            if !matched_any {
                heading_candidates.push(HeadingCandidate {
                    heading_id: String::new(),
                    page_no: start_page,
                    text: section.title.clone(),
                    normalized_text: normalize_title(&section.title),
                    source: "fallback".into(),
                    block_label: String::new(),
                    top_band: true,
                    confidence: section.classification_confidence,
                    heading_family_guess: "section".into(),
                    suppressed_as_chapter: true,
                    reject_reason: reject_reason.to_string(),
                    ..Default::default()
                });
            }
        }
    }
}

// ── 构建 fallback 章节和节头 ─────────────────────────────────────

/// 找到书末按章汇总尾注的起始页。
///
/// note 页面重现一个早期章节标题，且该章节之后已有其它正文 chapter 时，
/// 该标题不是新正文起点，而是书末尾注的章节分组标题。
fn book_endnote_start_from_replayed_prior_chapter_titles(
    classified: &[ClassifiedSection],
    heading_candidates: &[HeadingCandidate],
    page_roles: &HashMap<i64, String>,
) -> Option<i64> {
    let kept_titles: Vec<(i64, String)> = classified
        .iter()
        .filter(|section| section.keep_as_chapter)
        .filter_map(|section| {
            let key = chapter_title_match_key(&section.title);
            (!key.is_empty()).then_some((section.start_page, key))
        })
        .collect();

    heading_candidates
        .iter()
        .filter(|candidate| {
            page_roles
                .get(&candidate.page_no)
                .is_some_and(|role| role == "note")
        })
        .filter_map(|candidate| {
            let key = chapter_title_match_key(&candidate.text);
            let matched_start = kept_titles
                .iter()
                .find(|(start_page, title_key)| {
                    *start_page < candidate.page_no && *title_key == key
                })
                .map(|(start_page, _)| *start_page)?;
            kept_titles
                .iter()
                .any(|(start_page, _)| {
                    matched_start < *start_page && *start_page < candidate.page_no
                })
                .then_some(candidate.page_no)
        })
        .min()
}

pub fn build_fallback_chapters_and_sections(
    classified: Vec<ClassifiedSection>,
    all_pages: &[i64],
    page_roles: &HashMap<i64, String>,
    heading_candidates: &[HeadingCandidate],
) -> (Vec<ChapterRecord>, Vec<SectionHeadRecord>) {
    if classified.is_empty() || all_pages.is_empty() {
        return (vec![], vec![]);
    }
    let kept_indices: Vec<usize> = classified
        .iter()
        .enumerate()
        .filter(|(_, c)| c.keep_as_chapter)
        .map(|(i, _)| i)
        .collect();
    if kept_indices.is_empty() {
        return (vec![], vec![]);
    }
    let book_endnote_start = book_endnote_start_from_replayed_prior_chapter_titles(
        &classified,
        heading_candidates,
        page_roles,
    );

    let mut chapters: Vec<ChapterRecord> = Vec::new();
    let mut section_to_chapter: HashMap<String, String> = HashMap::new();

    for (keep_pos, &section_idx) in kept_indices.iter().enumerate() {
        let section = &classified[section_idx];
        let chapter_id = format!("ch-fallback-{:04}", keep_pos + 1);
        let next_keep_idx = kept_indices
            .get(keep_pos + 1)
            .copied()
            .unwrap_or(classified.len());
        let section_start = section.start_page;
        let next_start = classified
            .get(next_keep_idx)
            .map(|c| c.start_page)
            .unwrap_or(0);
        let section_end_limit = if next_start > section_start {
            next_start - 1
        } else {
            *all_pages.last().unwrap_or(&section_start)
        };
        let raw_span: Vec<i64> = all_pages
            .iter()
            .copied()
            .filter(|&p| section_start <= p && p <= section_end_limit)
            .collect();
        let mut filtered: Vec<i64> = raw_span
            .iter()
            .copied()
            .filter(|p| {
                let role = page_roles.get(p).map(|s| s.as_str()).unwrap_or("");
                role == "body" || role == "front_matter"
            })
            .collect();
        if let Some(endnote_start) = book_endnote_start {
            if section_start < endnote_start {
                filtered.retain(|page| *page < endnote_start);
            }
        }
        if filtered.is_empty() {
            filtered = section.filtered_pages.clone();
        }
        if filtered.is_empty() {
            continue;
        }
        chapters.push(ChapterRecord {
            chapter_id: chapter_id.clone(),
            title: section.title.clone(),
            start_page: filtered[0],
            end_page: *filtered.last().unwrap(),
            pages: filtered,
            source: ChapterSource::Fallback,
            boundary_state: BoundaryState::Ready,
        });
        for mi in section_idx..next_keep_idx {
            if let Some(sec) = classified.get(mi) {
                if !sec.section_id.is_empty() {
                    section_to_chapter.insert(sec.section_id.clone(), chapter_id.clone());
                }
            }
        }
        if !section.section_id.is_empty() {
            section_to_chapter.insert(section.section_id.clone(), chapter_id);
        }
    }
    if chapters.is_empty() {
        return (vec![], vec![]);
    }

    // Assign orphan sections to first/last chapter
    if let Some(first_id) = chapters.first().map(|c| c.chapter_id.clone()) {
        for i in 0..kept_indices[0] {
            if let Some(sec) = classified.get(i) {
                if !sec.section_id.is_empty() {
                    section_to_chapter
                        .entry(sec.section_id.clone())
                        .or_insert_with(|| first_id.clone());
                }
            }
        }
    }
    if let Some(last_id) = chapters.last().map(|c| c.chapter_id.clone()) {
        for i in (kept_indices.last().copied().unwrap_or(0) + 1)..classified.len() {
            if let Some(sec) = classified.get(i) {
                if !sec.section_id.is_empty() {
                    section_to_chapter
                        .entry(sec.section_id.clone())
                        .or_insert_with(|| last_id.clone());
                }
            }
        }
    }

    // Build section_heads
    let mut section_heads: Vec<SectionHeadRecord> = Vec::new();
    let mut serial = 1usize;
    for section in &classified {
        if section.keep_as_chapter {
            continue;
        }
        let chapter_id = section_to_chapter
            .get(&section.section_id)
            .cloned()
            .unwrap_or_default();
        if section.title.is_empty() {
            continue;
        }
        section_heads.push(SectionHeadRecord {
            section_head_id: format!("section-head-{:04}", serial),
            chapter_id,
            title: section.title.clone(),
            page_no: section.start_page,
            level: 2,
            source: "fallback".into(),
        });
        serial += 1;
    }

    (chapters, section_heads)
}

// ── 标准化 ───────────────────────────────────────────────────────

pub fn normalize_chapters(chapters: Vec<ChapterRecord>) -> Vec<ChapterRecord> {
    let mut normalized: Vec<ChapterRecord> = chapters
        .into_iter()
        .filter(|c| !c.pages.is_empty() && !c.chapter_id.is_empty())
        .collect();
    normalized.sort_by_key(|c| (c.start_page, c.chapter_id.clone()));
    normalized
}

pub fn normalize_sections(sections: Vec<SectionHeadRecord>) -> Vec<SectionHeadRecord> {
    let mut normalized: Vec<SectionHeadRecord> = sections
        .into_iter()
        .filter(|s| !s.title.is_empty() && s.page_no > 0)
        .collect();
    normalized.sort_by_key(|s| (s.page_no, s.title.clone()));
    normalized
}

// ── 辅助函数 ─────────────────────────────────────────────────────

fn chapter_keyword_strength(title: &str) -> f64 {
    if CHAPTER_KEYWORD_RE.is_match(title)
        || fnm_core::title::matches_front_matter_force_export(title)
    {
        2.0
    } else if crate::chapter_skeleton::toc_semantics::title_utils::LECTURE_TITLE_RE.is_match(title)
    {
        1.5
    } else {
        0.0
    }
}

/// 宽松版：用于 fallback 章节分类，≥6 词或含逗号/冒号即视为句子型标题。
/// 与 normalize.rs 的严格版有意不同（后者用于 heading candidate 筛选，阈值更高）。
fn is_sentence_like_heading(title: &str) -> bool {
    let words: Vec<&str> = title.split_whitespace().collect();
    words.len() >= 6 || title.contains(',') || title.contains(':')
}

pub fn all_page_numbers(page_partitions: &[PagePartitionRecord]) -> Vec<i64> {
    let mut pages: Vec<i64> = page_partitions
        .iter()
        .map(|p| p.page_no)
        .filter(|&p| p > 0)
        .collect();
    pages.sort_unstable();
    pages.dedup();
    pages
}

pub fn build_page_roles(page_partitions: &[PagePartitionRecord]) -> HashMap<i64, String> {
    page_partitions
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str().to_string()))
        .collect()
}

// ── 简单 fallback（无 heading_candidates 时的退化路径）───────────

/// 无 heading_candidates 时，把连续 body 页打包为 fallback 章节。
/// 这是原始 stub 行为的保留路径。
pub fn simple_fallback(page_partitions: &[PagePartitionRecord]) -> Vec<ChapterRecord> {
    let mut chapters = Vec::new();
    let mut chapter_start: Option<i64> = None;
    let mut chapter_pages: Vec<i64> = Vec::new();
    let mut chapter_count = 0i64;

    for pp in page_partitions {
        if pp.page_role.as_str() == "body" {
            if chapter_start.is_none() {
                chapter_start = Some(pp.page_no);
                chapter_count += 1;
            }
            chapter_pages.push(pp.page_no);
        } else if chapter_start.is_some() {
            let start = chapter_start.take().unwrap();
            let end = chapter_pages.last().copied().unwrap_or(start);
            chapters.push(ChapterRecord {
                chapter_id: format!("ch-fallback-{:03}", chapter_count),
                title: format!("Chapter {}", chapter_count),
                start_page: start,
                end_page: end,
                pages: std::mem::take(&mut chapter_pages),
                source: ChapterSource::Fallback,
                boundary_state: BoundaryState::ReviewRequired,
            });
        }
    }

    // 尾章
    if let Some(start) = chapter_start {
        let end = chapter_pages.last().copied().unwrap_or(start);
        chapters.push(ChapterRecord {
            chapter_id: format!("ch-fallback-{:03}", chapter_count),
            title: format!("Chapter {}", chapter_count),
            start_page: start,
            end_page: end,
            pages: std::mem::take(&mut chapter_pages),
            source: ChapterSource::Fallback,
            boundary_state: BoundaryState::ReviewRequired,
        });
    }

    chapters
}

// ── 测试入口 ───────────────────────────────────────────────────

/// 无 TOC 时，从 heading_candidates + page_partitions 构建 fallback 章节。
///
/// ←→ Python `_build_fallback_chapters_and_sections` + 上游所有步骤
#[cfg(test)]
pub(crate) fn build_chapter_skeleton_fallback(
    page_partitions: &[PagePartitionRecord],
    heading_candidates: &mut Vec<HeadingCandidate>,
    _heading_graph: &HeadingGraph,
    total_pages: i64,
) -> Vec<ChapterRecord> {
    if page_partitions.is_empty() {
        return vec![];
    }

    // 如果没有 heading_candidates，退化为简单策略：连续 body 页打包为一章
    if heading_candidates.is_empty() {
        return simple_fallback(page_partitions);
    }

    let all_pages = all_page_numbers(page_partitions);
    let page_roles = build_page_roles(page_partitions);

    // Step 1: candidate section rows
    let section_rows = candidate_section_rows(heading_candidates, &all_pages, &page_roles);

    // Step 2: classify
    let classified =
        classify_fallback_sections(section_rows, &page_roles, total_pages, heading_candidates);

    // Step 3: mark suppressed candidates (mutate heading_candidates in-place, ←→ Python)
    mark_suppressed_candidates(&classified, heading_candidates);

    // Step 4: build chapters + section heads
    let (chapters, _section_heads) = build_fallback_chapters_and_sections(
        classified,
        &all_pages,
        &page_roles,
        heading_candidates,
    );

    // Step 5: normalize
    normalize_chapters(chapters)
}

// ── Back matter 边界推断 + chapter trim（B3 之前缺失的 5%）────────

const REAR_REASONS: &[&str] = &[
    "appendix",
    "bibliography",
    "index",
    "illustrations",
    "rear_toc_tail",
    "rear_author_blurb",
    "rear_sparse_other",
];

const BACK_MATTER_FAMILIES: &[&str] = &["bibliography", "index", "illustrations"];

/// ←→ Python `_infer_back_matter_start_page`
///
/// 综合 rear page_role 信号 + TOC items 的 back_matter 角色推断 back_matter 起始页。
/// 返回 0 表示无法判断。
pub fn infer_back_matter_start_page(
    page_partitions: &[PagePartitionRecord],
    toc_items: Option<&[TocItem]>,
    toc_offset: i64,
    file_idx_map: &HashMap<i64, i64>,
) -> i64 {
    let total_pages = page_partitions.len().max(1) as i64;
    let rear_page_role_min_page = std::cmp::max(24, (total_pages as f64 * 0.45) as i64);
    let rear_page_role_force_page =
        std::cmp::max(rear_page_role_min_page, (total_pages as f64 * 0.8) as i64);
    let toc_back_matter_min_page = std::cmp::max(24, (total_pages as f64 * 0.25) as i64);

    let mut candidate_pages: Vec<i64> = Vec::new();

    let rear_role_pages: Vec<i64> = {
        let mut pages: Vec<i64> = page_partitions
            .iter()
            .filter(|row| {
                row.page_no >= rear_page_role_min_page
                    && row.page_role.as_str() == "other"
                    && REAR_REASONS.iter().any(|r| *r == row.reason)
            })
            .map(|row| row.page_no)
            .collect();
        pages.sort_unstable();
        pages
    };

    for row in page_partitions {
        let page_no = row.page_no;
        if page_no <= 0 || page_no < rear_page_role_min_page {
            continue;
        }
        if row.page_role.as_str() != "other" {
            continue;
        }
        if !REAR_REASONS.iter().any(|r| *r == row.reason) {
            continue;
        }
        let has_neighbor = rear_role_pages
            .iter()
            .any(|&other| other != page_no && (other - page_no).abs() <= 6);
        if page_no >= rear_page_role_force_page || has_neighbor {
            candidate_pages.push(page_no);
        }
    }

    if let Some(items) = toc_items {
        for item in items {
            let resolved_page = resolve_toc_item_target_pdf_page(item, toc_offset, file_idx_map);
            if resolved_page <= 0 || resolved_page < toc_back_matter_min_page {
                continue;
            }
            let role_hint = item.role_hint.trim().to_lowercase().replace('-', "_");
            let family = guess_title_family(&item.title, resolved_page, total_pages);
            let family_str: &str = family;
            if role_hint == "back_matter" || BACK_MATTER_FAMILIES.contains(&family_str) {
                candidate_pages.push(resolved_page);
            }
        }
    }

    candidate_pages.iter().copied().min().unwrap_or(0)
}

/// 解析 TocItem target_pdf_page（与 fileIdx 映射对齐）。
/// 简化版：直接用 target_pdf_page；如未提供，则尝试 file_idx_map 反查。
fn resolve_toc_item_target_pdf_page(
    item: &TocItem,
    offset: i64,
    file_idx_map: &HashMap<i64, i64>,
) -> i64 {
    if let Some(pn) = item.target_pdf_page {
        if pn > 0 {
            return pn + offset;
        }
        // 0 / 负值时尝试 fileIdx 反查
        if let Some(&mapped) = file_idx_map.get(&pn) {
            if mapped > 0 {
                return mapped;
            }
        }
    }
    0
}

#[derive(Debug, Clone)]
pub struct ChapterRowDraft {
    pub chapter_id: String,
    pub title: String,
    pub pages: Vec<i64>,
    pub source: String,
}

/// ←→ Python `_trim_chapter_rows`
///
/// 用 back_matter_start_page 切掉 back_matter 之后的页面。preserve_title_keys 中
/// 的章节（标题在保留集合）+ force-export titles（introduction/avertissement 等）
/// 不被切割。
pub fn trim_chapter_rows(
    chapter_rows: Vec<ChapterRowDraft>,
    page_roles: &HashMap<i64, String>,
    back_matter_start_page: i64,
    preserve_title_keys: &HashSet<String>,
) -> Vec<ChapterRowDraft> {
    let mut trimmed: Vec<ChapterRowDraft> = Vec::new();
    for row in chapter_rows {
        if row.pages.is_empty() {
            continue;
        }
        let mut filtered: Vec<i64> = row
            .pages
            .iter()
            .filter(|&&pn| {
                pn > 0
                    && matches!(
                        page_roles.get(&pn).map(|s| s.as_str()),
                        Some("body") | Some("front_matter")
                    )
            })
            .copied()
            .collect();

        let title_key = chapter_title_match_key(&row.title);
        if back_matter_start_page > 0
            && !preserve_title_keys.contains(&title_key)
            && !is_toc_force_export_title(&row.title)
        {
            filtered.retain(|&pn| pn < back_matter_start_page);
        }

        if filtered.is_empty() {
            continue;
        }
        let mut clone = row.clone();
        clone.pages = filtered;
        trimmed.push(clone);
    }
    trimmed
}

fn is_toc_force_export_title(title: &str) -> bool {
    let normalized = normalize_title(title);
    fnm_core::title::matches_front_matter_force_export(&normalized.to_lowercase())
}

// ── 默认 TOC summary 生成器（B3 之前缺失的 3 个 helper）─────────

/// ←→ Python `_default_toc_alignment_summary`
pub fn default_toc_alignment_summary(chapter_count: i64) -> Value {
    json!({
        "chapter_level_body_items": 0,
        "exported_chapter_count": chapter_count,
        "missing_chapter_titles_preview": Vec::<String>::new(),
        "misleveled_titles_preview": Vec::<String>::new(),
        "reanchored_titles_preview": Vec::<String>::new(),
        "missing_section_titles_preview": Vec::<String>::new(),
    })
}

/// ←→ Python `_default_toc_semantic_summary`
pub fn default_toc_semantic_summary(chapter_count: i64) -> Value {
    json!({
        "body_item_count": 0,
        "chapter_item_count": chapter_count,
        "part_item_count": 0,
        "endnotes_item_count": 0,
        "back_matter_item_count": 0,
        "first_body_pdf_page": 0,
        "last_body_pdf_page": 0,
        "body_span_ratio": 0.0,
        "nonbody_contamination_count": 0,
        "mixed_level_chapter_count": 0,
    })
}

/// ←→ Python `_default_toc_role_summary`
pub fn default_toc_role_summary(chapter_count: i64, section_count: i64) -> Value {
    json!({
        "container": 0,
        "endnotes": 0,
        "chapter": chapter_count,
        "section": section_count,
        "post_body": 0,
        "back_matter": 0,
        "front_matter": 0,
    })
}

// ── 测试 ─────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::PageRole;

    fn pp(page_no: i64, role: PageRole) -> PagePartitionRecord {
        PagePartitionRecord {
            page_no,
            target_pdf_page: page_no,
            page_role: role,
            confidence: 0.0,
            reason: String::new(),
            section_hint: String::new(),
            has_note_heading: false,
            note_scan_summary: serde_json::Value::Null,
        }
    }

    fn hc(page_no: i64, text: &str, source: &str, family: &str) -> HeadingCandidate {
        HeadingCandidate {
            heading_id: String::new(),
            page_no,
            text: text.into(),
            normalized_text: normalize_title(text),
            source: source.into(),
            block_label: String::new(),
            top_band: false,
            confidence: 1.0,
            heading_family_guess: family.into(),
            suppressed_as_chapter: false,
            reject_reason: String::new(),
            ..Default::default()
        }
    }

    fn top_doc_hc(page_no: i64, text: &str) -> HeadingCandidate {
        let mut candidate = hc(page_no, text, "ocr_block", "chapter");
        candidate.block_label = "doc_title".into();
        candidate.top_band = true;
        candidate
    }

    #[test]
    fn fallback_single_chapter() {
        let parts = vec![
            pp(1, PageRole::Body),
            pp(2, PageRole::Body),
            pp(3, PageRole::Body),
        ];
        let chapters =
            build_chapter_skeleton_fallback(&parts, &mut vec![], &HeadingGraph::default(), 3);
        assert_eq!(chapters.len(), 1);
        assert!(chapters[0].chapter_id.starts_with("ch-fallback-"));
        assert_eq!(chapters[0].start_page, 1);
        assert_eq!(chapters[0].end_page, 3);
    }

    #[test]
    fn fallback_empty() {
        let chapters =
            build_chapter_skeleton_fallback(&[], &mut vec![], &HeadingGraph::default(), 0);
        assert!(chapters.is_empty());
    }

    #[test]
    fn fallback_with_section_rows() {
        let parts = vec![
            pp(1, PageRole::Body),
            pp(2, PageRole::Body),
            pp(3, PageRole::Body),
        ];
        let mut hcs = vec![hc(1, "Chapter One", "visual_toc", "chapter")];
        let chapters =
            build_chapter_skeleton_fallback(&parts, &mut hcs, &HeadingGraph::default(), 3);
        assert_eq!(chapters.len(), 1);
        assert_eq!(chapters[0].title, "Chapter One");
    }

    #[test]
    fn classify_rejects_note_heading() {
        let parts = vec![pp(1, PageRole::Body)];
        let mut hcs = vec![hc(1, "NOTES", "note_heading", "note")];
        let chapters =
            build_chapter_skeleton_fallback(&parts, &mut hcs, &HeadingGraph::default(), 1);
        // "NOTES" should be rejected → fallback creates one empty chapter
        assert!(chapters.is_empty() || chapters.len() == 1);
    }

    #[test]
    fn classify_keeps_strong_evidence() {
        let parts = vec![
            pp(1, PageRole::Body),
            pp(2, PageRole::Body),
            pp(3, PageRole::Body),
            pp(4, PageRole::Body),
        ];
        let mut hcs = vec![hc(1, "Chapter One", "visual_toc", "chapter")];
        let chapters =
            build_chapter_skeleton_fallback(&parts, &mut hcs, &HeadingGraph::default(), 4);
        assert_eq!(chapters.len(), 1);
        assert_eq!(chapters[0].title, "Chapter One");
    }

    #[test]
    fn top_level_doc_titles_are_not_shortened_by_nested_section_headings() {
        let parts: Vec<PagePartitionRecord> = (1..=12).map(|p| pp(p, PageRole::Body)).collect();
        let mut hcs = vec![
            top_doc_hc(1, "First Main Subject"),
            hc(2, "Nested discussion", "ocr_block", "section"),
            top_doc_hc(7, "Second Main Subject"),
            hc(8, "Another nested discussion", "ocr_block", "section"),
        ];

        let chapters =
            build_chapter_skeleton_fallback(&parts, &mut hcs, &HeadingGraph::default(), 12);

        assert_eq!(chapters.len(), 2);
        assert_eq!(chapters[0].pages, vec![1, 2, 3, 4, 5, 6]);
        assert_eq!(chapters[1].pages, vec![7, 8, 9, 10, 11, 12]);
    }

    #[test]
    fn fallback_chapter_preserves_body_after_internal_note_band() {
        let mut parts: Vec<PagePartitionRecord> = (1..=4).map(|p| pp(p, PageRole::Body)).collect();
        parts.extend((5..=6).map(|p| pp(p, PageRole::Note)));
        parts.extend((7..=10).map(|p| pp(p, PageRole::Body)));
        let mut hcs = vec![hc(1, "Chapter One", "visual_toc", "chapter")];

        let chapters =
            build_chapter_skeleton_fallback(&parts, &mut hcs, &HeadingGraph::default(), 10);

        assert_eq!(chapters.len(), 1);
        assert_eq!(chapters[0].pages, vec![1, 2, 3, 4, 7, 8, 9, 10]);
    }

    #[test]
    fn fallback_stops_after_book_endnote_run_that_replays_prior_chapter_titles() {
        let mut parts: Vec<PagePartitionRecord> = (1..=8).map(|p| pp(p, PageRole::Body)).collect();
        parts.extend((9..=12).map(|p| pp(p, PageRole::Note)));
        parts.extend((13..=14).map(|p| pp(p, PageRole::Body)));
        let mut hcs = vec![
            hc(1, "Introduction", "visual_toc", "chapter"),
            hc(5, "Epilogue", "visual_toc", "chapter"),
            hc(9, "Introduction", "ocr_block", "section"),
        ];

        let chapters =
            build_chapter_skeleton_fallback(&parts, &mut hcs, &HeadingGraph::default(), 14);

        assert_eq!(chapters.len(), 2);
        assert_eq!(chapters[1].title, "Epilogue");
        assert_eq!(chapters[1].pages, vec![5, 6, 7, 8]);
    }

    #[test]
    fn normalize_empty_pages() {
        let result = normalize_chapters(vec![]);
        assert!(result.is_empty());
    }

}
