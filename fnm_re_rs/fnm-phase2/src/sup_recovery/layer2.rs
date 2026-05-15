//! Layer 2：OCR raw block 文本对齐。
//! 扫描 OCR blocks，用模糊匹配从 block 文本中恢复丢失的上标 marker。
//!
//! Layer 2 的 OCR symbol surrogate recovery 需要 block 文本对齐算法，
//! 暂未实现。当前返回空让上层走 Layer 3 vision fallback。
//! TODO: 见 FNM_PHASE12_AUDIT.md F8+（留给保真型模型完整翻译 Python 版）
#![allow(dead_code)]

use regex::Regex;

static DIGIT_BOUNDARY_RE: once_cell::sync::Lazy<Regex> =
    once_cell::sync::Lazy::new(|| Regex::new(r"\b(\d{1,4})\b").unwrap());

/// 在 OCR raw text 中寻找与 markers 对齐的候选。
pub fn find_markers_in_ocr_text(
    ocr_text: &str,
    markers: &[String],
) -> anyhow::Result<Vec<(String, String)>> {
    let mut recovered: Vec<(String, String)> = Vec::new();
    let marker_set: std::collections::HashSet<&str> = markers.iter().map(|s| s.as_str()).collect();

    // 扫描数字序列（digit boundary 匹配）
    for caps in DIGIT_BOUNDARY_RE.captures_iter(ocr_text) {
        let candidate = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        if marker_set.contains(candidate) {
            recovered.push((candidate.to_string(), "ocr_aligned".into()));
        }
    }

    // OCR symbol surrogate recovery (stub: block 文本对齐算法暂未实现)
    // 见 FNM_PHASE12_AUDIT.md F8+ — 当前只返回 digit 匹配结果，symbol proxy 留给 layer3 vision
    Ok(recovered)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn find_digit_markers() {
        let markers = vec!["30".into(), "11".into()];
        let found = find_markers_in_ocr_text("text with 30 and 11 markers", &markers).unwrap();
        assert_eq!(found.len(), 2);
    }

    #[test]
    #[ignore = "stub removed, see G2 layer3"]
    fn find_symbol_proxy() {
        let markers = vec!["30".into()];
        let found = find_markers_in_ocr_text("1927-30 * ou", &markers).unwrap();
        assert!(!found.is_empty());
    }
}
