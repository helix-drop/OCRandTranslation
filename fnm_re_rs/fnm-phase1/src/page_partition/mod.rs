//! ←→ FNM_RE/stages/page_partition.py
//! 页面角色判定入口 + build_page_partitions / build_page_partitions_streaming。

pub mod role_heuristics;
pub mod role_resolver;

use crate::input::{ManualPageOverride, RawPage};
use fnm_core::records::PagePartitionRecord;
use fnm_core::text::{first_section_hint, has_note_heading, note_scan_summary};
use fnm_core::types::PageRole;
use role_resolver::{resolve_page_role, PageScanContext};
use std::collections::HashMap;

pub use role_heuristics::summarize_page_partitions;

/// 构建页面分区，同时预提取 heading candidates 和 fileIdx→bookPage 映射。
pub fn build_page_partitions(
    pages: &[RawPage],
    page_overrides: Option<&HashMap<String, ManualPageOverride>>,
    endnotes_start_page: Option<i64>,
) -> PagePartitionResult {
    let total_pages = pages.len() as i64;
    let mut records: Vec<PagePartitionRecord> = Vec::with_capacity(pages.len());
    let mut file_idx_map: HashMap<i64, i64> = HashMap::new();
    let mut page_info_cache: HashMap<i64, PageInfo> = HashMap::new();

    for page in pages {
        let page_no = page.book_page;
        if page_no <= 0 {
            continue;
        }
        let note_scan_value = page.note_scan.clone().unwrap_or_default();
        let headings = fnm_core::text::extract_page_headings(&page.pruned_result);
        let text_buf = fnm_core::text::page_markdown_text(&page.pruned_result);

        let ctx = PageScanContext {
            page_no,
            total_pages: total_pages.max(1),
            text: &text_buf,
            note_scan: &note_scan_value,
            headings: &headings,
        };
        let matched = resolve_page_role(&ctx);
        let reason = matched.reason.clone();
        let role_str = matched.role.as_str().to_string();

        records.push(PagePartitionRecord {
            page_no,
            target_pdf_page: page_no,
            page_role: matched.role,
            confidence: matched.confidence,
            reason,
            section_hint: first_section_hint(&page.pruned_result, Some(&note_scan_value)),
            has_note_heading: has_note_heading(&page.pruned_result),
            note_scan_summary: note_scan_summary(&note_scan_value),
        });

        if let Some(fi) = page.file_idx {
            if fi >= 0 {
                file_idx_map.insert(fi, page_no);
            }
        }
        page_info_cache.insert(
            page_no,
            PageInfo {
                markdown: text_buf,
                headings,
                page_role: role_str,
                role_reason: matched.reason,
            },
        );
    }

    records.sort_by_key(|r| r.page_no);

    // 应用 manual overrides
    if let Some(overrides) = page_overrides {
        apply_manual_overrides(&mut records, overrides);
    }

    // 应用 endnotes_start_page_hint
    if let Some(start_page) = endnotes_start_page {
        apply_endnotes_start_page_hint(&mut records, start_page);
    }

    let _synthetic = build_synthetic_page_by_no(&page_info_cache);

    PagePartitionResult {
        partitions: records,
        pre_extracted_page_candidates: vec![],
        file_idx_map,
        page_texts: HashMap::new(),
    }
}

/// 应用手工 page override。
fn apply_manual_overrides(
    records: &mut [PagePartitionRecord],
    overrides: &HashMap<String, ManualPageOverride>,
) {
    for record in records.iter_mut() {
        let key = record.page_no.to_string();
        if let Some(ov) = overrides.get(&key) {
            if let Some(ref role_str) = ov.page_role {
                if let Ok(role) = role_str.parse() {
                    record.page_role = role;
                    record.confidence = 1.0;
                    record.reason = "manual_override".into();
                }
            }
        }
    }
}

/// 应用 endnotes_start_page 提示：从 start 往后，非 note 页改为 note。
fn apply_endnotes_start_page_hint(records: &mut [PagePartitionRecord], start_page: i64) {
    if start_page <= 0 {
        return;
    }
    let mut seen_note = false;
    for record in records.iter_mut() {
        if record.page_no < start_page {
            continue;
        }
        if record.page_role.as_str() == "note" {
            seen_note = true;
            continue;
        }
        if seen_note
            && record.page_role.as_str() == "other"
            && matches!(
                record.reason.as_str(),
                "rear_toc_tail"
                    | "rear_author_blurb"
                    | "rear_sparse_other"
                    | "bibliography"
                    | "index"
                    | "illustrations"
            )
        {
            break;
        }
        if matches!(record.page_role.as_str(), "body" | "other" | "front_matter") {
            record.page_role = PageRole::Note;
            record.confidence = record.confidence.max(0.90);
            record.reason = "endnotes_start_page_hint".into();
            seen_note = true;
        }
    }
}

#[derive(Debug, Clone)]
pub struct PageInfo {
    pub markdown: String,
    pub headings: Vec<String>,
    pub page_role: String,
    pub role_reason: String,
}

fn build_synthetic_page_by_no(
    cache: &HashMap<i64, PageInfo>,
) -> HashMap<i64, serde_json::Map<String, serde_json::Value>> {
    let mut result = HashMap::new();
    for (page_no, info) in cache {
        let mut page = serde_json::Map::new();
        page.insert(
            "markdown".into(),
            serde_json::Value::String(info.markdown.clone()),
        );
        if !info.headings.is_empty() {
            let parsing_res_list: Vec<serde_json::Value> = info
                .headings
                .iter()
                .map(|h| serde_json::json!({"block_label": "doc_title", "block_content": h}))
                .collect();
            page.insert(
                "prunedResult".into(),
                serde_json::json!({
                    "parsing_res_list": parsing_res_list,
                    "height": 1200,
                    "width": 1000,
                }),
            );
        }
        let mut row = serde_json::Map::new();
        row.insert("_page".into(), serde_json::Value::Object(page));
        row.insert(
            "page_no".into(),
            serde_json::Value::Number((*page_no).into()),
        );
        row.insert(
            "page_role".into(),
            serde_json::Value::String(info.page_role.clone()),
        );
        row.insert(
            "section_hint".into(),
            serde_json::Value::String(info.headings.first().cloned().unwrap_or_default()),
        );
        row.insert("has_note_heading".into(), serde_json::Value::Bool(false));
        result.insert(*page_no, row);
    }
    result
}

#[derive(Debug, Clone)]
pub struct PagePartitionResult {
    pub partitions: Vec<PagePartitionRecord>,
    pub pre_extracted_page_candidates: Vec<i64>,
    pub file_idx_map: HashMap<i64, i64>,
    pub page_texts: HashMap<i64, String>,
}
