//! _note_scan 结构化解析：从 RawPage.note_scan.items 读取已由 PDF fnBlocks
//! 预处理过的结构化注释条目，替代纯文本正则解析。
//!
//! ←→ Python `scan_items_by_kind` / `_raw_scan_items_by_kind` / `_parse_items_from_structured_scan`

use fnm_core::note_marker::normalize_note_marker;
use fnm_phase1::input::RawPage;

/// 从 page.note_scan.items 中过滤指定 kind 的条目，返回简单键值列表。
/// ←→ Python `scan_items_by_kind`
pub fn scan_items_by_kind(page: &RawPage, kind: &str) -> Vec<ScanItem> {
    let Some(scan) = &page.note_scan else {
        return vec![];
    };
    let Some(items) = scan.get("items").and_then(|v| v.as_array()) else {
        return vec![];
    };

    let target_kind = kind.trim().to_lowercase();
    let mut result: Vec<ScanItem> = vec![];

    for item in items {
        let item_kind = item
            .get("kind")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_lowercase();
        if item_kind != target_kind {
            continue;
        }
        let marker = item
            .get("marker")
            .or_else(|| item.get("number"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let text = item
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        let marker = normalize_note_marker(marker);
        if marker.is_empty() && text.is_empty() {
            continue;
        }
        result.push(ScanItem {
            marker,
            text: text.to_string(),
            is_reconstructed: item
                .get("is_reconstructed")
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
            source: "note_scan".into(),
            section_title: item
                .get("section_title")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string(),
        });
    }
    result
}

/// 只返回指定 kind 的条目（不含 section_title），供序列修复后使用。
/// ←→ Python `_parse_items_from_structured_scan`
pub fn parse_items_from_structured_scan(page: &RawPage, kind: &str) -> Vec<ScanItem> {
    scan_items_by_kind(page, kind)
}

/// 含 section_title 的扫描条目，供共享页过滤。
/// ←→ Python `_raw_scan_items_by_kind`
pub fn raw_scan_items_by_kind(page: &RawPage, kind: &str) -> Vec<ScanItem> {
    scan_items_by_kind(page, kind)
}

#[derive(Debug, Clone)]
pub struct ScanItem {
    pub marker: String,
    pub text: String,
    pub is_reconstructed: bool,
    pub source: String,
    pub section_title: String,
}
