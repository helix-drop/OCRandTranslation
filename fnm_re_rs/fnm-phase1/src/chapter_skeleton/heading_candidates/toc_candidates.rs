//! ←→ heading_candidates.py: _collect_toc_heading_candidates
//!
//! 从 Visual TOC 条目构建 heading candidates。

use fnm_core::records::HeadingCandidate;
use fnm_core::title::chapter_title_match_key;
use serde_json::Value;
use std::collections::HashMap;

use crate::input::TocItem;

use super::family_guess::heading_family_guess;

/// 从 TOC 条目构建 heading candidates。
/// 与 Python `_collect_toc_heading_candidates` 一致。
pub fn collect_toc_heading_candidates(
    page_rows: &[Value],
    toc_items: Option<&[TocItem]>,
    toc_offset: i64,
    file_idx_map: Option<&HashMap<i64, i64>>,
) -> Vec<HeadingCandidate> {
    let items = match toc_items {
        Some(v) if !v.is_empty() => v,
        _ => return vec![],
    };

    // 构建 page_no → page_role 映射
    let page_role_by_no: HashMap<i64, String> = page_rows
        .iter()
        .filter_map(|row| {
            let pn = row.get("page_no").and_then(|v| v.as_i64())?;
            let pr = row.get("page_role").and_then(|v| v.as_str())?.to_string();
            Some((pn, pr))
        })
        .collect();

    let total_pages = page_rows.len() as i64;

    // 构建 raw_pages 引用（如果 file_idx_map 为空时的 fallback）
    let raw_pages: Option<Vec<Value>> = if file_idx_map.is_none() {
        Some(
            page_rows
                .iter()
                .filter_map(|row| row.get("_page").cloned())
                .collect(),
        )
    } else {
        None
    };

    let mut candidates: Vec<HeadingCandidate> = Vec::new();
    let mut dedupe: HashMap<(i64, String, String, String), usize> = HashMap::new();

    for item in items {
        let title = fnm_core::title::normalize_title(&item.title);
        if title.is_empty() {
            continue;
        }

        let resolved_page =
            resolve_toc_item_page(item, toc_offset, raw_pages.as_deref(), file_idx_map);
        let resolved_page = match resolved_page {
            Some(p) if p > 0 => p,
            _ => continue,
        };

        let page_role = page_role_by_no
            .get(&resolved_page)
            .map(|s| s.as_str())
            .unwrap_or("");

        let family = heading_family_guess(
            &title,
            resolved_page,
            total_pages.max(1),
            page_role,
            "visual_toc",
            "",
            true,
        );

        let candidate = HeadingCandidate {
            heading_id: String::new(),
            page_no: resolved_page,
            text: title.clone(),
            normalized_text: title,
            source: "visual_toc".into(),
            block_label: String::new(),
            top_band: true,
            confidence: 1.0,
            heading_family_guess: family,
            suppressed_as_chapter: false,
            reject_reason: String::new(),
            font_height: None,
            x: None,
            y: None,
            width_estimate: None,
            font_name: String::new(),
            font_weight_hint: "unknown".into(),
            align_hint: "unknown".into(),
            width_ratio: None,
            heading_level_hint: 1,
        };

        let key = (
            candidate.page_no,
            candidate.source.clone(),
            chapter_title_match_key(&candidate.normalized_text),
            candidate.block_label.clone(),
        );
        match dedupe.entry(key) {
            std::collections::hash_map::Entry::Occupied(e) => {
                let idx = *e.get();
                let existing = &candidates[idx];
                if candidate.confidence > existing.confidence
                    || (candidate.top_band && !existing.top_band)
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

    candidates
}

/// 解析 TOC 项的落点页码（简单版）。
/// ←→ Python `web.toc_support.resolve_toc_item_target_pdf_page`
fn resolve_toc_item_page(
    item: &TocItem,
    _toc_offset: i64,
    _raw_pages: Option<&[Value]>,
    _file_idx_map: Option<&HashMap<i64, i64>>,
) -> Option<i64> {
    // TOC item 的 target_pdf_page 是主要落点
    if let Some(tp) = item.target_pdf_page {
        if tp > 0 {
            return Some(tp);
        }
    }
    None
}
