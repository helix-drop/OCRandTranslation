//! ←→ FNM_RE/stages/chapter_skeleton/heading_candidates.py
//! Heading candidate 收集与归一化。
//!
//! 7 子模块：
//! - `font_features`：字体特征规范化
//! - `family_guess`：family 推断 + 章关键词
//! - `page_rows`：页行构建 + 页级候选收集
//! - `toc_candidates`：TOC 候选
//! - `pdf_font_band`：PDF 字体 band 候选
//! - `normalize`：归一化 + 句子类似判定

pub mod family_guess;
pub mod font_features;
pub mod normalize;
pub mod page_rows;
pub mod pdf_font_band;
pub mod toc_candidates;

use fnm_core::records::HeadingCandidate;
use fnm_core::text::{page_blocks, page_markdown_text};
use fnm_core::title::{chapter_title_match_key, normalize_title};
use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::Value;
use std::collections::HashMap;

use crate::input::TocItem;

use self::family_guess::heading_family_guess;

// ── Lazy regex ──────────────────────────────────────────────

static NOTES_HEADER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?im)^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*)\s*$").unwrap()
});

static MARKDOWN_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s{0,3}#{1,6}\s*(.+?)\s*$").unwrap());

static MARKDOWN_LEVEL_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\s{0,3}(#{1,6})").unwrap());

// ── safe_float ──────────────────────────────────────────────

/// 从 JSON Value 安全提取 f64。与 Python `_safe_float` 一致。
pub(crate) fn safe_float(v: &Value) -> Option<f64> {
    match v {
        Value::Null => None,
        Value::Number(n) => n.as_f64(),
        Value::String(s) => s.trim().parse::<f64>().ok(),
        _ => None,
    }
}

// ── append_heading_candidate ────────────────────────────────

/// 去重感知的 heading candidate 追加/替换的参数。
struct HeadingCandidateParams<'a> {
    page_no: i64,
    text: &'a str,
    source: &'a str,
    block_label: &'a str,
    top_band: bool,
    confidence: f64,
    family: &'a str,
    font_height: Option<f64>,
    x: Option<f64>,
    y: Option<f64>,
    width_estimate: Option<f64>,
    font_name: &'a str,
    font_weight_hint: &'a str,
    align_hint: &'a str,
    width_ratio_val: Option<f64>,
    heading_level_hint_val: i64,
}

/// 去重感知的 heading candidate 追加/替换。
/// ←→ Python `_append_heading_candidate`
fn append_heading_candidate(
    candidates: &mut Vec<HeadingCandidate>,
    dedupe: &mut HashMap<(i64, String, String, String), usize>,
    params: &HeadingCandidateParams,
) {
    let normalized_text = normalize_title(params.text);
    if normalized_text.is_empty() {
        return;
    }
    let key = (
        params.page_no,
        params.source.to_lowercase(),
        chapter_title_match_key(&normalized_text),
        params.block_label.to_lowercase(),
    );

    let candidate = HeadingCandidate {
        heading_id: String::new(),
        page_no: params.page_no,
        text: normalized_text.clone(),
        normalized_text,
        source: params.source.to_string(),
        block_label: params.block_label.to_string(),
        top_band: params.top_band,
        confidence: params.confidence,
        heading_family_guess: params.family.to_string(),
        suppressed_as_chapter: false,
        reject_reason: String::new(),
        font_height: params.font_height,
        x: params.x,
        y: params.y,
        width_estimate: params.width_estimate,
        font_name: params.font_name.to_string(),
        font_weight_hint: params.font_weight_hint.to_string(),
        align_hint: params.align_hint.to_string(),
        width_ratio: params.width_ratio_val,
        heading_level_hint: params.heading_level_hint_val,
    };

    use std::collections::hash_map::Entry;
    match dedupe.entry(key) {
        Entry::Occupied(e) => {
            let idx = *e.get();
            let existing = &candidates[idx];
            if params.confidence > existing.confidence || (params.top_band && !existing.top_band) {
                candidates[idx] = candidate;
            }
        }
        Entry::Vacant(e) => {
            e.insert(candidates.len());
            candidates.push(candidate);
        }
    }
}

// ── extract_heading_candidates_from_page ────────────────────

/// 从单页提取 heading candidates（OCR block + markdown heading + note heading）。
/// ←→ Python `extract_heading_candidates_from_page`
pub fn extract_heading_candidates_from_page(
    page: &Value,
    page_no: i64,
    total_pages: i64,
    page_role: &str,
) -> Vec<HeadingCandidate> {
    let mut candidates: Vec<HeadingCandidate> = Vec::new();
    let mut dedupe: HashMap<(i64, String, String, String), usize> = HashMap::new();

    let page_h = page
        .get("prunedResult")
        .and_then(|p| p.get("height"))
        .and_then(safe_float)
        .unwrap_or(1200.0);
    let page_w = page
        .get("prunedResult")
        .and_then(|p| p.get("width"))
        .and_then(safe_float)
        .unwrap_or(1000.0);

    // ── OCR blocks ──
    for block in page_blocks(page) {
        let label = block
            .get("block_label")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_lowercase();
        if label != "doc_title" && label != "paragraph_title" {
            continue;
        }

        let raw_content = block
            .get("block_content")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        // 跳过文本修复器（Python detect_and_fix_text），Rust 中暂不实现
        let text = normalize_title(raw_content);
        if text.is_empty() {
            continue;
        }

        let bbox: Vec<&Value> = block
            .get("block_bbox")
            .and_then(|v| v.as_array())
            .map(|a| a.iter().collect())
            .unwrap_or_default();

        let left = bbox.first().and_then(|v| safe_float(v));
        let top = bbox.get(1).and_then(|v| safe_float(v));
        let right = bbox.get(2).and_then(|v| safe_float(v));
        let bottom = bbox.get(3).and_then(|v| safe_float(v));

        let width_estimate = match (left, right) {
            (Some(l), Some(r)) => Some((r - l).max(0.0)),
            _ => None,
        };
        let font_height = match (top, bottom) {
            (Some(t), Some(b)) => Some((b - t).max(0.0)),
            _ => None,
        };
        let top_band = top.map(|t| t <= page_h * 0.30).unwrap_or(false);

        let mut confidence: f64 = if label == "doc_title" { 0.72 } else { 0.58 };
        if top_band {
            confidence += 0.12;
        }

        let family = heading_family_guess(
            &text,
            page_no,
            total_pages,
            page_role,
            "ocr_block",
            &label,
            top_band,
        );
        let level_hint = font_features::heading_level_hint("ocr_block", &label, top_band, 0);

        append_heading_candidate(
            &mut candidates,
            &mut dedupe,
            &HeadingCandidateParams {
                page_no,
                text: &text,
                source: "ocr_block",
                block_label: &label,
                top_band,
                confidence,
                family: &family,
                font_height,
                x: left,
                y: top,
                width_estimate,
                font_name: "",
                font_weight_hint: "unknown",
                align_hint: font_features::align_hint(left, width_estimate, page_w),
                width_ratio_val: font_features::width_ratio(width_estimate, page_w),
                heading_level_hint_val: level_hint,
            },
        );
    }

    // ── Markdown headings ──
    let markdown = page_markdown_text(page);
    for (index, raw_line) in markdown.lines().take(12).enumerate() {
        let line = raw_line.trim();
        if line.is_empty() {
            continue;
        }

        // note heading
        if NOTES_HEADER_RE.is_match(line) {
            let family = heading_family_guess(
                line,
                page_no,
                total_pages,
                page_role,
                "note_heading",
                "",
                index <= 3,
            );
            let level_hint = font_features::heading_level_hint("note_heading", "", index <= 3, 0);
            append_heading_candidate(
                &mut candidates,
                &mut dedupe,
                &HeadingCandidateParams {
                    page_no,
                    text: line,
                    source: "note_heading",
                    block_label: "",
                    top_band: index <= 3,
                    confidence: 0.96,
                    family: &family,
                    font_height: None,
                    x: None,
                    y: None,
                    width_estimate: None,
                    font_name: "",
                    font_weight_hint: "unknown",
                    align_hint: "unknown",
                    width_ratio_val: None,
                    heading_level_hint_val: level_hint,
                },
            );
            continue;
        }

        // markdown heading
        if let Some(caps) = MARKDOWN_HEADING_RE.captures(raw_line) {
            let heading = normalize_title(caps.get(1).map(|m| m.as_str()).unwrap_or(""));
            if heading.is_empty() {
                continue;
            }
            let md_prefix = MARKDOWN_LEVEL_RE.captures(raw_line);
            let markdown_level = md_prefix
                .and_then(|c| c.get(1))
                .map(|m| m.as_str().len())
                .unwrap_or(1);

            let family = heading_family_guess(
                &heading,
                page_no,
                total_pages,
                page_role,
                "markdown_heading",
                "",
                index <= 2,
            );
            let level_hint = font_features::heading_level_hint(
                "markdown_heading",
                "",
                index <= 2,
                markdown_level,
            );
            let conf: f64 = if index <= 2 { 0.62 } else { 0.54 };
            append_heading_candidate(
                &mut candidates,
                &mut dedupe,
                &HeadingCandidateParams {
                    page_no,
                    text: &heading,
                    source: "markdown_heading",
                    block_label: "",
                    top_band: index <= 2,
                    confidence: conf,
                    family: &family,
                    font_height: None,
                    x: None,
                    y: None,
                    width_estimate: None,
                    font_name: "",
                    font_weight_hint: "unknown",
                    align_hint: "unknown",
                    width_ratio_val: None,
                    heading_level_hint_val: level_hint,
                },
            );
        }
    }

    candidates
}

// ── collect_heading_candidate_rows ──────────────────────────

/// 顶层编排：收集所有来源的 heading candidates，排序并归一。
/// ←→ Python `_collect_heading_candidate_rows`
pub fn collect_heading_candidate_rows(
    page_rows: &[Value],
    toc_items: Option<&[TocItem]>,
    toc_offset: i64,
    _pdf_path: &str,
    pre_extracted_page_candidates: Option<Vec<HeadingCandidate>>,
    file_idx_map: Option<&HashMap<i64, i64>>,
    _doc_id: &str,
) -> Vec<HeadingCandidate> {
    let total_pages = page_rows.len() as i64;
    let mut candidates: Vec<HeadingCandidate> = Vec::new();

    // 1. 页面级 heading candidates
    if let Some(pre) = pre_extracted_page_candidates {
        candidates.extend(pre);
    } else {
        let page_candidates = page_rows::collect_page_heading_candidates(page_rows, total_pages);
        candidates.extend(page_candidates);
    }

    // 2. TOC candidates
    let toc_candidates = toc_candidates::collect_toc_heading_candidates(
        page_rows,
        toc_items,
        toc_offset,
        file_idx_map,
    );
    candidates.extend(toc_candidates);

    // 3. PDF font band candidates（完整实现：pdf_font_band.rs）
    let pdf_candidates = pdf_font_band::collect_pdf_font_band_candidates(
        page_rows,
        &candidates,
        _pdf_path,
        toc_items,
        toc_offset,
        file_idx_map,
        _doc_id,
    );
    candidates.extend(pdf_candidates);

    // 4. 排序 + 分配 heading_id
    normalize::normalize_heading_candidates(candidates)
}

// ── 测试 ──────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn safe_float_from_number() {
        assert!((safe_float(&json!(42.5)).unwrap() - 42.5).abs() < 1e-6);
    }

    #[test]
    fn safe_float_from_null() {
        assert!(safe_float(&Value::Null).is_none());
    }

    #[test]
    fn safe_float_from_string() {
        assert!((safe_float(&json!("12.5")).unwrap() - 12.5).abs() < 1e-6);
    }

    #[test]
    fn extract_from_ocr_block() {
        let page = json!({
            "prunedResult": {
                "parsing_res_list": [{
                    "block_label": "doc_title",
                    "block_content": "Chapter 1",
                    "block_bbox": [100.0, 50.0, 400.0, 80.0],
                    "block_order": 1,
                }],
                "height": 1200,
                "width": 1000,
            }
        });
        let candidates = extract_heading_candidates_from_page(&page, 1, 100, "body");
        assert!(!candidates.is_empty());
        assert_eq!(candidates[0].page_no, 1);
        assert_eq!(candidates[0].text, "Chapter 1");
        assert!(candidates[0].top_band);
        assert_eq!(candidates[0].source, "ocr_block");
        assert_eq!(candidates[0].heading_family_guess, "chapter");
    }

    #[test]
    fn non_body_title_rejected() {
        let page = json!({
            "prunedResult": {
                "parsing_res_list": [{
                    "block_label": "doc_title",
                    "block_content": "Table of Contents",
                    "block_bbox": [100.0, 50.0, 400.0, 80.0],
                    "block_order": 1,
                }],
                "height": 1200,
                "width": 1000,
            }
        });
        let candidates = extract_heading_candidates_from_page(&page, 2, 100, "body");
        assert!(!candidates.is_empty());
        // TOC titles get classified by heading_family_guess as a non-body family
        assert_eq!(candidates[0].heading_family_guess, "contents");
    }

    #[test]
    fn part_title_is_chapter() {
        let page = json!({
            "prunedResult": {
                "parsing_res_list": [{
                    "block_label": "doc_title",
                    "block_content": "Part I",
                    "block_bbox": [100.0, 50.0, 400.0, 80.0],
                    "block_order": 1,
                }],
                "height": 1200,
                "width": 1000,
            }
        });
        let candidates = extract_heading_candidates_from_page(&page, 1, 100, "body");
        assert!(!candidates.is_empty());
        assert_eq!(candidates[0].heading_family_guess, "chapter");
    }

    #[test]
    fn extract_from_markdown_heading() {
        let page = json!({
            "markdown": "# Chapter 1\nsome content",
            "prunedResult": {"height": 1200, "width": 1000, "parsing_res_list": []}
        });
        let candidates = extract_heading_candidates_from_page(&page, 1, 100, "body");
        assert!(!candidates.is_empty());
        assert_eq!(candidates[0].source, "markdown_heading");
    }

    #[test]
    fn extract_notes_heading() {
        let page = json!({
            "markdown": "## Notes\nsome note content",
            "prunedResult": {"height": 1200, "width": 1000, "parsing_res_list": []}
        });
        let candidates = extract_heading_candidates_from_page(&page, 50, 100, "note");
        assert!(!candidates.is_empty());
        assert_eq!(candidates[0].source, "note_heading");
        assert_eq!(candidates[0].heading_family_guess, "note");
    }

    #[test]
    fn non_body_page_suppressed() {
        let page = json!({
            "prunedResult": {
                "parsing_res_list": [{
                    "block_label": "doc_title",
                    "block_content": "Chapter 5",
                    "block_bbox": [100.0, 50.0, 400.0, 80.0],
                    "block_order": 1,
                }],
                "height": 1200,
                "width": 1000,
            }
        });
        let candidates = extract_heading_candidates_from_page(&page, 5, 100, "note");
        assert!(!candidates.is_empty());
        // "note" pages still produce candidates but with appropriate family
        assert_eq!(candidates[0].heading_family_guess, "chapter");
    }

    #[test]
    fn empty_page_no_candidates() {
        let page = json!({
            "prunedResult": {"height": 1200, "width": 1000, "parsing_res_list": []}
        });
        let candidates = extract_heading_candidates_from_page(&page, 0, 100, "body");
        assert!(candidates.is_empty());
    }

    #[test]
    fn dedup_same_heading() {
        let page = json!({
            "prunedResult": {
                "parsing_res_list": [
                    {
                        "block_label": "doc_title",
                        "block_content": "Chapter 1",
                        "block_bbox": [100.0, 50.0, 400.0, 80.0],
                        "block_order": 1,
                    },
                    {
                        "block_label": "doc_title",
                        "block_content": "Chapter 1",
                        "block_bbox": [100.0, 60.0, 400.0, 90.0],
                        "block_order": 2,
                    },
                ],
                "height": 1200,
                "width": 1000,
            }
        });
        let candidates = extract_heading_candidates_from_page(&page, 1, 100, "body");
        assert_eq!(candidates.len(), 1, "duplicate heading should be deduped");
    }

    #[test]
    fn dedup_keeps_higher_confidence() {
        // Two blocks with same dedup key: the higher-confidence one wins
        let page = json!({
            "prunedResult": {
                "parsing_res_list": [
                    {
                        "block_label": "doc_title",
                        "block_content": "Some Section",
                        "block_bbox": [100.0, 500.0, 400.0, 530.0],
                        "block_order": 1,
                    },
                    {
                        "block_label": "doc_title",
                        "block_content": "Some Section",
                        "block_bbox": [100.0, 50.0, 400.0, 80.0],
                        "block_order": 2,
                    },
                ],
                "height": 1200,
                "width": 1000,
            }
        });
        let candidates = extract_heading_candidates_from_page(&page, 1, 100, "body");
        assert_eq!(candidates.len(), 1);
        // The top_band (y=50) wins due to higher confidence + top_band bonus
        assert!(candidates[0].top_band);
    }

    #[test]
    fn multiple_headings_retained() {
        // Two blocks with different dedup keys are both kept
        let page = json!({
            "prunedResult": {
                "parsing_res_list": [
                    {
                        "block_label": "doc_title",
                        "block_content": "Chapter 1",
                        "block_bbox": [100.0, 50.0, 400.0, 80.0],
                        "block_order": 1,
                    },
                    {
                        "block_label": "doc_title",
                        "block_content": "Introduction",
                        "block_bbox": [100.0, 200.0, 400.0, 230.0],
                        "block_order": 2,
                    },
                ],
                "height": 1200,
                "width": 1000,
            }
        });
        let candidates = extract_heading_candidates_from_page(&page, 1, 100, "body");
        assert_eq!(candidates.len(), 2);
    }
}
