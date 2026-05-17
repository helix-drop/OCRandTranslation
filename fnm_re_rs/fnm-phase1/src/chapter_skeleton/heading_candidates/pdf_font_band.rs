//! ←→ heading_candidates.py: _collect_pdf_font_band_candidates / _extract_candidates_from_pdf_pages
//!
//! PDF 字体项 ranking 与 heading candidate 生成。

use fnm_core::records::HeadingCandidate;
use fnm_core::title::normalize_title;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

use super::family_guess::heading_family_guess;
use super::font_features::{
    align_hint, heading_level_hint, normalize_font_weight_hint, width_ratio,
};
use super::safe_float;

/// PDF font band 候选收集入口。
/// ←→ Python `_collect_pdf_font_band_candidates`
///
/// 调用底层 PDFIUM 提取字体项，经 `extract_candidates_from_pdf_pages` 筛选排名后返回。
/// 若 PDF 不存在或 PDFIUM 不可用则返回空列表。
pub fn collect_pdf_font_band_candidates(
    page_rows: &[Value],
    _heading_candidates: &[HeadingCandidate],
    pdf_path: &str,
    _toc_items: Option<&[crate::input::TocItem]>,
    _toc_offset: i64,
    file_idx_map: Option<&HashMap<i64, i64>>,
    _doc_id: &str,
) -> Vec<HeadingCandidate> {
    if pdf_path.is_empty() {
        return vec![];
    }

    // 构建 file_idx_to_page_no（fileIdx → bookPage）
    let file_idx_to_page_no: HashMap<i64, i64> = match file_idx_map {
        Some(m) => m.clone(),
        None => {
            // 从 page_rows 中 fallback 构建
            let mut m = HashMap::new();
            for row in page_rows {
                if let (Some(file_idx), Some(page_no)) = (
                    row.get("file_idx").and_then(|v| v.as_i64()),
                    row.get("page_no").and_then(|v| v.as_i64()),
                ) {
                    if file_idx >= 0 {
                        m.insert(file_idx, page_no);
                    }
                }
            }
            m
        }
    };

    if file_idx_to_page_no.is_empty() {
        return vec![];
    }

    // 确定 candidate_pages（所有 page_row 的 page_no）
    let candidate_pages: HashSet<i64> = page_rows
        .iter()
        .filter_map(|r| r.get("page_no").and_then(|v| v.as_i64()))
        .filter(|&pn| pn > 0)
        .collect();

    let total_pages = page_rows.len().max(1) as i64;

    // page_role_by_no
    let page_role_by_no: HashMap<i64, String> = page_rows
        .iter()
        .filter_map(|r| {
            let pn = r.get("page_no").and_then(|v| v.as_i64())?;
            let role = r
                .get("page_role")
                .and_then(|v| v.as_str())
                .unwrap_or("body");
            Some((pn, role.to_string()))
        })
        .collect();

    // 确定要提取的 PDF 页索引
    let page_indices: Vec<i64> = file_idx_to_page_no.keys().copied().collect();

    // 调用 PDF 字体提取
    let font_candidates =
        match crate::chapter_skeleton::pdf_font::extract_font_candidates(pdf_path, &page_indices) {
            Ok(c) => c,
            Err(_) => return vec![],
        };

    if font_candidates.is_empty() {
        return vec![];
    }

    // 将 FontCandidate 转换为 extract_candidates_from_pdf_pages 期望的 Value 格式
    let mut pdf_pages: Vec<Value> = Vec::new();
    for (file_idx, items) in &font_candidates {
        let vals: Vec<Value> = items
            .iter()
            .map(|fc| {
                json!({
                    "str": fc.text,
                    "x": fc.x,
                    "y": fc.y,
                    "w": fc.width,
                    "h": fc.height,
                    "font_name": fc.font_name,
                    "font_weight_hint": if fc.is_bold { "bold" } else { "regular" },
                })
            })
            .collect();
        pdf_pages.push(json!({
            "pageIdx": file_idx,
            "pdfW": 0.0,
            "pdfH": 0.0,
            "items": vals,
        }));
    }

    extract_candidates_from_pdf_pages(
        &pdf_pages,
        &candidate_pages,
        &file_idx_to_page_no,
        &page_role_by_no,
        total_pages,
    )
}

/// 从 PDF 字体提取结果中筛选 heading candidates（纯计算）。
/// ←→ Python `_extract_candidates_from_pdf_pages`
///
/// `pdf_pages`: 从 `extract_pdf_text` 得到的页面列表（Value dict），每个含 items。
/// `candidate_pages`: 限定只从这些 page_no 中提取。
/// `file_idx_to_page_no`: file_idx → bookPage 映射。
/// `page_role_by_no`: page_no → role 映射。
/// `total_pages`: 全书总页数。
pub fn extract_candidates_from_pdf_pages(
    pdf_pages: &[Value],
    candidate_pages: &HashSet<i64>,
    file_idx_to_page_no: &HashMap<i64, i64>,
    page_role_by_no: &HashMap<i64, String>,
    total_pages: i64,
) -> Vec<HeadingCandidate> {
    let mut candidates: Vec<HeadingCandidate> = Vec::new();
    let mut dedupe: HashMap<(i64, String, String, String), usize> = HashMap::new();

    for page in pdf_pages {
        let file_idx = page.get("pageIdx").and_then(|v| v.as_i64()).unwrap_or(-1);
        let page_no = match file_idx_to_page_no.get(&file_idx) {
            Some(&pn) if pn > 0 && candidate_pages.contains(&pn) => pn,
            _ => continue,
        };

        let pdf_w = page.get("pdfW").and_then(safe_float).unwrap_or(0.0);
        let pdf_h = page.get("pdfH").and_then(safe_float).unwrap_or(0.0);

        let items_raw: Vec<Value> = page
            .get("items")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();

        if items_raw.is_empty() {
            continue;
        }

        // 按 (y, -h) 排序
        let mut items = items_raw;
        items.sort_by(|a, b| {
            let ay = a.get("y").and_then(safe_float).unwrap_or(1e9);
            let by = b.get("y").and_then(safe_float).unwrap_or(1e9);
            match ay.partial_cmp(&by).unwrap_or(std::cmp::Ordering::Equal) {
                std::cmp::Ordering::Equal => {
                    let ah = a.get("h").and_then(safe_float).unwrap_or(0.0);
                    let bh = b.get("h").and_then(safe_float).unwrap_or(0.0);
                    bh.partial_cmp(&ah).unwrap_or(std::cmp::Ordering::Equal)
                }
                other => other,
            }
        });

        let top_limit = if pdf_h > 0.0 { pdf_h * 0.28 } else { 240.0 };
        let mid_limit = if pdf_h > 0.0 { pdf_h * 0.55 } else { 520.0 };

        fn safe_y(v: &Value) -> f64 {
            v.get("y").and_then(safe_float).unwrap_or(1e9)
        }

        let top_items: Vec<&Value> = items
            .iter()
            .take(80)
            .filter(|item| {
                let y = safe_y(item);
                y <= top_limit
                    && !normalize_title(item.get("str").and_then(|v| v.as_str()).unwrap_or(""))
                        .is_empty()
                    && normalize_title(item.get("str").and_then(|v| v.as_str()).unwrap_or("")).len()
                        <= 160
            })
            .collect();

        let mid_items: Vec<&Value> = items
            .iter()
            .take(120)
            .filter(|item| {
                let y = safe_y(item);
                y > top_limit
                    && y <= mid_limit
                    && !normalize_title(item.get("str").and_then(|v| v.as_str()).unwrap_or(""))
                        .is_empty()
                    && normalize_title(item.get("str").and_then(|v| v.as_str()).unwrap_or("")).len()
                        <= 160
                    && matches!(
                        normalize_font_weight_hint(
                            item.get("font_weight_hint")
                                .and_then(|v| v.as_str())
                                .unwrap_or("")
                        ),
                        "bold" | "heavy"
                    )
            })
            .collect();

        // 评分排序
        fn rank_item(item: &Value, top_band: bool) -> (f64, f64, f64) {
            let text = normalize_title(item.get("str").and_then(|v| v.as_str()).unwrap_or(""));
            let fwh = normalize_font_weight_hint(
                item.get("font_weight_hint")
                    .and_then(|v| v.as_str())
                    .unwrap_or(""),
            );
            let ah = align_hint(
                item.get("x").and_then(safe_float),
                item.get("w").and_then(safe_float),
                item.get("pdfW").and_then(safe_float).unwrap_or(1000.0),
            );
            let weight_score = match fwh {
                "heavy" => 2.0,
                "bold" => 1.2,
                "regular" => 0.4,
                _ => 0.0,
            };
            let length_penalty = (text.len().max(48) - 48) as f64 * 0.03;
            let length_penalty = length_penalty.clamp(0.0, 2.4);
            let center_bonus = if ah == "center" { 0.8 } else { 0.0 };
            let top_bonus = if top_band { 0.9 } else { 0.0 };
            (
                weight_score + center_bonus + top_bonus - length_penalty,
                -(item.get("y").and_then(safe_float).unwrap_or(0.0)),
                -(text.len() as f64),
            )
        }

        // 选 top 3 top-items + top 2 mid-items
        let mut selected: Vec<(&Value, bool)> = Vec::new();
        let mut top_sorted: Vec<&Value> = top_items;
        top_sorted.sort_by(|a, b| rank_item(a, true).partial_cmp(&rank_item(b, true)).unwrap());
        for item in top_sorted.into_iter().rev().take(3) {
            selected.push((item, true));
        }

        let mut mid_sorted: Vec<&Value> = mid_items;
        mid_sorted.sort_by(|a, b| {
            rank_item(a, false)
                .partial_cmp(&rank_item(b, false))
                .unwrap()
        });
        for item in mid_sorted.into_iter().rev().take(2) {
            selected.push((item, false));
        }

        for (item, top_band) in selected {
            let text = normalize_title(item.get("str").and_then(|v| v.as_str()).unwrap_or(""));
            if text.is_empty() {
                continue;
            }
            let font_height = item.get("h").and_then(safe_float).unwrap_or(0.0);
            let font_name = item
                .get("font_name")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let fwh = normalize_font_weight_hint(
                item.get("font_weight_hint")
                    .and_then(|v| v.as_str())
                    .unwrap_or(""),
            );
            let ah = align_hint(
                item.get("x").and_then(safe_float),
                item.get("w").and_then(safe_float),
                pdf_w,
            );
            let item_x = item.get("x").and_then(safe_float);
            let item_w = item.get("w").and_then(safe_float);
            let item_y = item.get("y").and_then(safe_float);

            let mut confidence = 0.52;
            if top_band {
                confidence += 0.12;
            }
            if fwh == "bold" || fwh == "heavy" {
                confidence += 0.12;
            }
            if ah == "center" {
                confidence += 0.08;
            }

            let page_role = page_role_by_no
                .get(&page_no)
                .map(|s| s.as_str())
                .unwrap_or("");

            let family = heading_family_guess(
                &text,
                page_no,
                total_pages.max(1),
                page_role,
                "pdf_font_band",
                "",
                top_band,
            );

            let candidate = HeadingCandidate {
                heading_id: String::new(),
                page_no,
                text: text.clone(),
                normalized_text: text,
                source: "pdf_font_band".into(),
                block_label: String::new(),
                top_band,
                confidence,
                heading_family_guess: family,
                suppressed_as_chapter: false,
                reject_reason: String::new(),
                font_height: Some(font_height),
                x: item_x,
                y: item_y,
                width_estimate: item_w,
                font_name,
                font_weight_hint: fwh.into(),
                align_hint: ah.into(),
                width_ratio: width_ratio(item_w, pdf_w),
                heading_level_hint: heading_level_hint("pdf_font_band", "", top_band, 0),
            };

            let key = (
                candidate.page_no,
                candidate.source.clone(),
                fnm_core::title::chapter_title_match_key(&candidate.normalized_text),
                candidate.block_label.clone(),
            );
            match dedupe.entry(key) {
                std::collections::hash_map::Entry::Occupied(e) => {
                    let idx = *e.get();
                    if candidate.confidence > candidates[idx].confidence
                        || (candidate.top_band && !candidates[idx].top_band)
                    {
                        candidates[idx] = candidate;
                    }
                }
                std::collections::hash_map::Entry::Vacant(e) => {
                    e.insert(candidates.len());
                    candidates.push(candidate);
                }
            }
        }
    }

    candidates
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn extract_empty_pages() {
        let result = extract_candidates_from_pdf_pages(
            &[],
            &HashSet::new(),
            &HashMap::new(),
            &HashMap::new(),
            0,
        );
        assert!(result.is_empty());
    }

    #[test]
    fn extract_with_no_candidate_pages() {
        let pages = vec![json!({
            "pageIdx": 1,
            "pdfW": 600.0,
            "pdfH": 800.0,
            "items": [{"str": "Chapter 1", "y": 50.0, "x": 100.0, "height": 18.0, "width": 80.0, "font": "Times-Bold"}]
        })];
        let result = extract_candidates_from_pdf_pages(
            &pages,
            &HashSet::new(),
            &HashMap::new(),
            &HashMap::new(),
            100,
        );
        assert!(
            result.is_empty(),
            "no candidate pages should yield no candidates"
        );
    }

    #[test]
    fn collect_empty_pdf_path() {
        let result = collect_pdf_font_band_candidates(&[], &[], "", None, 0, None, "");
        assert!(result.is_empty());
    }
}
