//! ←→ FNM_RE/modules/sup_recovery.py `_layer2_raw_blocks` + 3 surrogate generators
//! OCR block 文本中找回丢失的上标 marker（5 种模式）。

use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashSet;

/// Layer 2 恢复结果。
#[derive(Debug, Clone)]
pub struct Layer2Recovery {
    pub marker: String,
    pub before: String,
    pub after: String,
    pub found_in: String, // text block source
    pub mode: String,     // "direct_digit" | "ocr_surrogate" | "ocr_suffix" |  "ocr_symbol_after_year"
}

/// ←→ Python `_ocr_surrogate_for_marker`：全 1 的 marker 用 `!{n}` 匹配
fn ocr_surrogate_for_marker(marker: &str) -> String {
    let m = marker.trim();
    if m.len() < 2 || m.chars().any(|c| c != '1') {
        return String::new();
    }
    format!("!{{{}}}", m.len())
}

/// ←→ Python `_ocr_suffix_surrogate_for_marker`：2 位不同数字 marker 取末位
fn ocr_suffix_surrogate_for_marker(marker: &str) -> String {
    let m = marker.trim();
    if m.len() != 2 || !m.chars().all(|c| c.is_ascii_digit()) {
        return String::new();
    }
    let mut chars = m.chars();
    let a = chars.next().unwrap();
    let b = chars.next().unwrap();
    if a == b {
        return String::new();
    }
    b.to_string()
}

/// 在 block 文本中搜索缺失的 markers。←→ Python `_layer2_raw_blocks` 5 种模式。
pub fn find_markers_in_blocks(
    blocks_texts: &[String],
    missing_markers: &[String],
) -> Vec<Layer2Recovery> {
    let mut results: Vec<Layer2Recovery> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();

    // 按 marker 长度降序排列（Python: sorted(missing, key=lambda x: -len(x))）
    let mut sorted = missing_markers.to_vec();
    sorted.sort_by(|a, b| b.len().cmp(&a.len()));

    for block_text in blocks_texts {
        if block_text.len() < 3 {
            continue;
        }

        // ── 模式 1: direct digit match ──
        for m in &sorted {
            if seen.contains(m.as_str()) || !m.chars().all(|c| c.is_ascii_digit()) {
                continue;
            }
            let escaped = regex::escape(m);
            // bullet chars: U+2022 (bullet), U+00B7 (middle dot)
            let pattern_str = format!("([A-Za-z])({})([\u{2022}\u{00B7}\\s,;:.\\)])", escaped);
            if let Ok(re) = Regex::new(&pattern_str) {
                if let Some(caps) = re.captures(block_text) {
                    let full = caps.get(0).map(|x| x.as_str()).unwrap_or("");
                    let pos = block_text.find(full).unwrap_or(0);
                    let before = &block_text[0.max(pos as i64 - 30) as usize..pos + 1];
                    let after_end = pos + full.len() - 1;
                    let after = &block_text[after_end..(after_end + 40).min(block_text.len())];
                    seen.insert(m.clone());
                    results.push(Layer2Recovery {
                        marker: m.clone(),
                        before: before.to_string(),
                        after: after.to_string(),
                        found_in: block_text[..40.min(block_text.len())].to_string(),
                        mode: "direct_digit".into(),
                    });
                }
            }
        }

        // ── 模式 2: OCR "!" surrogate ──
        for m in &sorted {
            if seen.contains(m.as_str()) {
                continue;
            }
            let surrogate = ocr_surrogate_for_marker(m);
            if surrogate.is_empty() {
                continue;
            }
            let pattern_str = format!(
                r"(?P<before>[A-Za-z])\s*(?P<surrogate>{})(?=\s+[A-Za-z])",
                surrogate
            );
            if let Ok(re) = Regex::new(&pattern_str) {
                if let Some(caps) = re.captures(block_text) {
                    if let Some(sur_match) = caps.name("surrogate") {
                        let pos = sur_match.start();
                        let before = &block_text[0.max(pos as i64 - 40) as usize..pos];
                        let after_start = sur_match.end();
                        let after = &block_text
                            [after_start..(after_start + 40).min(block_text.len())];
                        seen.insert(m.clone());
                        results.push(Layer2Recovery {
                            marker: m.clone(),
                            before: before.trim_end().to_string(),
                            after: after.to_string(),
                            found_in: block_text[..40.min(block_text.len())].to_string(),
                            mode: "ocr_surrogate".into(),
                        });
                    }
                }
            }
        }

        // ── 模式 3: OCR suffix surrogate ──
        for m in &sorted {
            if seen.contains(m.as_str()) {
                continue;
            }
            let suffix = ocr_suffix_surrogate_for_marker(m);
            if suffix.is_empty() {
                continue;
            }
            let pattern_str = format!(
                r"(?P<word>[A-Za-z]{{3,}})\s+(?P<suffix>{})(?P<trail>[•·,;:\.\)\]])",
                regex::escape(&suffix)
            );
            if let Ok(re) = Regex::new(&pattern_str) {
                if let Some(caps) = re.captures(block_text) {
                    if let Some(suf_match) = caps.name("suffix") {
                        let pos = suf_match.start();
                        let before = &block_text[0.max(pos as i64 - 40) as usize..pos];
                        let after_start = suf_match.end();
                        let after =
                            &block_text[after_start..(after_start + 40).min(block_text.len())];
                        seen.insert(m.clone());
                        results.push(Layer2Recovery {
                            marker: m.clone(),
                            before: before.trim_end().to_string(),
                            after: after.to_string(),
                            found_in: block_text[..40.min(block_text.len())].to_string(),
                            mode: "ocr_suffix".into(),
                        });
                    }
                }
            }
        }

        // ── 模式 4: OCR symbol after year ──
        for m in &sorted {
            if seen.contains(m.as_str()) || !m.chars().all(|c| c.is_ascii_digit()) {
                continue;
            }
            let escaped_m = regex::escape(m);
            // marker 长度为 2 位数字时尝试 symbol surrogate
            if m.len() != 2 {
                continue;
            }
            let pattern_str = format!(
                r"(?P<year>(?:\[\d{{2}}\]|(?:1[5-9]|20)\d{{0,2}}){})\s+(?P<symbol>[*#%?]{{1,2}})(?=\s+[A-Za-z])",
                escaped_m
            );
            if let Ok(re) = Regex::new(&pattern_str) {
                if let Some(caps) = re.captures(block_text) {
                    if let Some(sym_match) = caps.name("symbol") {
                        let pos = sym_match.start();
                        let before = &block_text[0.max(pos as i64 - 50) as usize..pos];
                        let after_start = sym_match.end();
                        let after =
                            &block_text[after_start..(after_start + 50).min(block_text.len())];
                        seen.insert(m.clone());
                        results.push(Layer2Recovery {
                            marker: m.clone(),
                            before: before.trim_end().to_string(),
                            after: after.to_string(),
                            found_in: block_text[..40.min(block_text.len())].to_string(),
                            mode: "ocr_symbol_after_year".into(),
                        });
                    }
                }
            }
        }
    }

    results
}

// ── 旧 API 兼容 ──────────────────────────────────────────────────

/// 在单一 OCR text 中寻找数字 markers（简化旧接口）。
pub fn find_markers_in_ocr_text(
    ocr_text: &str,
    markers: &[String],
) -> anyhow::Result<Vec<(String, String)>> {
    let marker_set: HashSet<&str> = markers.iter().map(|s| s.as_str()).collect();
    let mut recovered: Vec<(String, String)> = Vec::new();
    for caps in DIGIT_BOUNDARY_RE.captures_iter(ocr_text) {
        let candidate = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        if marker_set.contains(candidate) {
            recovered.push((candidate.to_string(), "ocr_aligned".into()));
        }
    }
    Ok(recovered)
}

static DIGIT_BOUNDARY_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\b(\d{1,4})\b").unwrap());

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
    fn ocr_surrogate_double_one() {
        assert_eq!(ocr_surrogate_for_marker("11"), "!{2}");
        assert_eq!(ocr_surrogate_for_marker("111"), "!{3}");
        assert_eq!(ocr_surrogate_for_marker("12"), "");
    }

    #[test]
    fn suffix_surrogate() {
        assert_eq!(ocr_suffix_surrogate_for_marker("12"), "2");
        assert_eq!(ocr_suffix_surrogate_for_marker("11"), ""); // 重复数字
        assert_eq!(ocr_suffix_surrogate_for_marker("123"), ""); // 不是 2 位
    }
}
