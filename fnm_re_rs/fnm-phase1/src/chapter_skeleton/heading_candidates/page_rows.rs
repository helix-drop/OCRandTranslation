//! ←→ heading_candidates.py: _build_pdf_page_by_file_idx / _legacy_page_rows / _collect_page_heading_candidates

use fnm_core::records::{HeadingCandidate, PagePartitionRecord};
use serde_json::Value;
use std::collections::HashMap;

use crate::input::RawPage;

use super::extract_heading_candidates_from_page;

/// 从 page 列表构建 fileIdx→bookPage 映射。
/// ←→ Python `_build_pdf_page_by_file_idx`
pub fn build_pdf_page_by_file_idx(pages: &[RawPage]) -> HashMap<i64, i64> {
    let mut map = HashMap::new();
    for page in pages {
        if let Some(fi) = page.file_idx {
            if fi >= 0 && page.book_page > 0 {
                map.insert(fi, page.book_page);
            }
        }
    }
    map
}

/// 从 page_partitions 构建 page_rows（兼容旧路径的可选 _page 引用）。
/// ←→ Python `_legacy_page_rows`
pub fn legacy_page_rows(
    page_partitions: &[PagePartitionRecord],
    pages: Option<&[RawPage]>,
) -> Vec<Value> {
    let page_by_no: HashMap<i64, &RawPage> = if let Some(pages_list) = pages {
        pages_list
            .iter()
            .filter(|p| p.book_page > 0)
            .map(|p| (p.book_page, p))
            .collect()
    } else {
        HashMap::new()
    };

    let mut sorted: Vec<&PagePartitionRecord> = page_partitions.iter().collect();
    sorted.sort_by_key(|r| r.page_no);

    sorted
        .into_iter()
        .map(|row| {
            let mut r = serde_json::json!({
                "page_no": row.page_no,
                "target_pdf_page": row.target_pdf_page,
                "page_role": row.page_role.as_str(),
                "role_confidence": row.confidence,
                "role_reason": row.reason,
                "section_hint": row.section_hint,
                "has_note_heading": row.has_note_heading,
                "note_scan_summary": row.note_scan_summary,
            });
            if let Some(page) = page_by_no.get(&row.page_no) {
                if let Ok(page_val) = serde_json::to_value(page) {
                    r.as_object_mut().unwrap().insert("_page".into(), page_val);
                }
            }
            r
        })
        .collect()
}

/// 遍历 page_rows，从每页提取 heading candidates（跨页去重）。
/// ←→ Python `_collect_page_heading_candidates`
pub fn collect_page_heading_candidates(
    page_rows: &[Value],
    total_pages: i64,
) -> Vec<HeadingCandidate> {
    let mut candidates: Vec<HeadingCandidate> = Vec::new();
    let mut dedupe: HashMap<(i64, String, String, String), usize> = HashMap::new();

    for row in page_rows {
        let page_no = row.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
        if page_no <= 0 {
            continue;
        }
        let page_role = row.get("page_role").and_then(|v| v.as_str()).unwrap_or("");
        let page = row.get("_page").cloned().unwrap_or(Value::Null);
        if page.is_null() {
            continue;
        }

        let page_candidates =
            extract_heading_candidates_from_page(&page, page_no, total_pages, page_role);

        for c in page_candidates {
            let key = (
                c.page_no,
                c.source.clone(),
                fnm_core::title::chapter_title_match_key(&c.normalized_text),
                c.block_label.clone(),
            );
            match dedupe.entry(key) {
                std::collections::hash_map::Entry::Occupied(entry) => {
                    let idx = *entry.get();
                    let existing = &candidates[idx];
                    if c.confidence > existing.confidence || (c.top_band && !existing.top_band) {
                        candidates[idx] = c;
                    }
                }
                std::collections::hash_map::Entry::Vacant(entry) => {
                    entry.insert(candidates.len());
                    candidates.push(c);
                }
            }
        }
    }

    candidates
}
