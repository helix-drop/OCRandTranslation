//! Layer 1：markdown 直接匹配（无需 PDF）。
//! 扫描 markdown 中的 `<sup>N</sup>` / `[N]` / Unicode 上标，与 chapter_markers 对齐。
//!
//! 复用 fnm-core 常量：HTML_SUP_RE / FOOTNOTE_REF_RE / UNICODE_SUP_RE + normalize_note_marker。

use fnm_core::anchor_kind::patterns::{FOOTNOTE_REF_RE, HTML_SUP_RE, UNICODE_SUP_RE};
use fnm_core::note_marker::normalize_note_marker;
use std::collections::HashSet;

/// 在 markdown 文本中查找与 markers 匹配的上标标记。
pub fn find_markers_in_markdown(markdown: &str, markers: &[String]) -> Vec<String> {
    let marker_set: HashSet<&str> = markers.iter().map(|s| s.as_str()).collect();
    let mut found: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();

    // 匹配 `<sup>N</sup>` 模式（复用 fnm-core 常量）
    for caps in HTML_SUP_RE.captures_iter(markdown) {
        let marker = caps
            .get(1)
            .map(|m| m.as_str().to_string())
            .unwrap_or_default();
        if marker_set.contains(marker.as_str()) && seen.insert(marker.clone()) {
            found.push(marker);
        }
    }

    // 匹配 `[^N]` 模式（复用 fnm-core 常量）
    for caps in FOOTNOTE_REF_RE.captures_iter(markdown) {
        let marker = caps
            .get(1)
            .map(|m| m.as_str().to_string())
            .unwrap_or_default();
        if marker_set.contains(marker.as_str()) && seen.insert(marker.clone()) {
            found.push(marker);
        }
    }

    // 匹配 Unicode 上标（复用 fnm-core UNICODE_SUP_RE + normalize_note_marker）
    for cap in UNICODE_SUP_RE.find_iter(markdown) {
        let normalized = normalize_note_marker(cap.as_str());
        if !normalized.is_empty()
            && marker_set.contains(normalized.as_str())
            && seen.insert(normalized.clone())
        {
            found.push(normalized);
        }
    }

    found
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn find_sup_tag() {
        let markers = vec!["1".into(), "2".into()];
        let found = find_markers_in_markdown("Some text<sup>1</sup> and <sup>2</sup>", &markers);
        assert_eq!(found.len(), 2);
    }

    #[test]
    fn find_ref_bracket() {
        let markers = vec!["3".into()];
        let found = find_markers_in_markdown("Reference[^3] here.", &markers);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0], "3");
    }
}
