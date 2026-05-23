//! ←→ FNM_RE/modules/sup_recovery.py `_layer2_raw_blocks` + 4 surrogate generators
//!
//! OCR block 文本中找回丢失的上标 marker（4 种模式：direct_digit / ocr_surrogate /
//! ocr_suffix / ocr_symbol_after_year）。修复 UTF-8 byte-boundary panic
//! （Python 用 `[A-Za-zÀ-ÿ]` 支持法语；本模块使用 char-aware 切片避免切割多字节字符）。

use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashSet;

/// Layer 2 恢复结果。
#[derive(Debug, Clone)]
pub struct Layer2Recovery {
    pub marker: String,
}

/// ←→ Python `_ocr_surrogate_for_marker`：全 1 的 marker 用 `!{n,}` 匹配。
fn ocr_surrogate_for_marker(marker: &str) -> String {
    let m = marker.trim();
    if m.len() < 2 || m.chars().any(|c| c != '1') {
        return String::new();
    }
    format!("!{{{},}}", m.len())
}

/// ←→ Python `_ocr_suffix_surrogate_for_marker`：2 位不同数字 marker 取末位。
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

/// ←→ Python `_ocr_symbol_surrogate_for_marker`：2 位数字 marker 用 `*#%?` 替代。
fn ocr_symbol_surrogate_for_marker(marker: &str) -> &'static str {
    let m = marker.trim();
    if m.len() == 2 && m.chars().all(|c| c.is_ascii_digit()) {
        r"[*#%?]{1,2}"
    } else {
        ""
    }
}

// ── 主入口 ───────────────────────────────────────────────────────

/// 在 block 文本中搜索缺失的 markers。←→ Python `_layer2_raw_blocks` 4 种模式。
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
        if block_text.chars().count() < 3 {
            continue;
        }

        // ── 模式 1: direct digit match ──
        // ←→ Python: `([A-Za-zÀ-ÿ])({m})([•·\s,;:\.\)])`
        for m in &sorted {
            if seen.contains(m.as_str()) || !m.chars().all(|c| c.is_ascii_digit()) {
                continue;
            }
            let escaped = regex::escape(m);
            // Rust regex 不支持 `À-ÿ` 直接 unicode 范围，用 `[A-Za-zÀ-ÿ]` 等价模式：
            // 启用 unicode 后 `[[:alpha:]]` 覆盖更广（包含拉丁补充字母）。
            let pattern_str = format!(
                r"((?:[A-Za-z]|[\u{{00C0}}-\u{{00FF}}]))({})([\u{{2022}}\u{{00B7}}\s,;:.\)])",
                escaped
            );
            if let Ok(re) = Regex::new(&pattern_str) {
                if let Some(caps) = re.captures(block_text) {
                    if caps.get(0).is_some() {
                        seen.insert(m.clone());
                        results.push(Layer2Recovery { marker: m.clone() });
                    }
                }
            }
        }

        // ── 模式 2: OCR "!" surrogate ──
        // ←→ Python: `(?P<before>[A-Za-zÀ-ÿ])\s*(?P<surrogate>!{n,})(?=\s+[A-Za-zÀ-ÿ])`
        for m in &sorted {
            if seen.contains(m.as_str()) {
                continue;
            }
            let surrogate = ocr_surrogate_for_marker(m);
            if surrogate.is_empty() {
                continue;
            }
            let pattern_str = format!(
                r"(?P<before>(?:[A-Za-z]|[\u{{00C0}}-\u{{00FF}}]))\s*(?P<surrogate>{})(?:\s+(?:[A-Za-z]|[\u{{00C0}}-\u{{00FF}}]))",
                surrogate
            );
            if let Ok(re) = Regex::new(&pattern_str) {
                if let Some(caps) = re.captures(block_text) {
                    if caps.name("surrogate").is_some() {
                        seen.insert(m.clone());
                        results.push(Layer2Recovery { marker: m.clone() });
                    }
                }
            }
        }

        // ── 模式 3: OCR suffix surrogate ──
        // ←→ Python: `(?P<word>[A-Za-zÀ-ÿ]{3,})\s+(?P<suffix>{s})(?P<trail>[•·,;:\.\)\]])`
        for m in &sorted {
            if seen.contains(m.as_str()) {
                continue;
            }
            let suffix = ocr_suffix_surrogate_for_marker(m);
            if suffix.is_empty() {
                continue;
            }
            let pattern_str = format!(
                r"(?P<word>(?:[A-Za-z]|[\u{{00C0}}-\u{{00FF}}]){{3,}})\s+(?P<suffix>{})(?P<trail>[\u{{2022}}\u{{00B7}},;:.\)\]])",
                regex::escape(&suffix)
            );
            if let Ok(re) = Regex::new(&pattern_str) {
                for caps in re.captures_iter(block_text) {
                    if caps.name("suffix").is_some() {
                        seen.insert(m.clone());
                        results.push(Layer2Recovery { marker: m.clone() });
                        break;
                    }
                }
            }
        }

        // ── 模式 4: OCR symbol after year ──
        // ←→ Python: `(?P<year>(?:\[\d{2}\]|(?:1[5-9]|20)\d{0,2}){m})\s+(?P<symbol>{sym})(?=\s+[A-Za-zÀ-ÿ])`
        for m in &sorted {
            if seen.contains(m.as_str()) || !m.chars().all(|c| c.is_ascii_digit()) {
                continue;
            }
            let symbol = ocr_symbol_surrogate_for_marker(m);
            if symbol.is_empty() {
                continue;
            }
            let escaped_m = regex::escape(m);
            let pattern_str = format!(
                r"(?P<year>(?:\[\d{{2}}\]|(?:1[5-9]|20)\d{{0,2}}){})\s+(?P<symbol>{})(?:\s+(?:[A-Za-z]|[\u{{00C0}}-\u{{00FF}}]))",
                escaped_m, symbol
            );
            if let Ok(re) = Regex::new(&pattern_str) {
                for caps in re.captures_iter(block_text) {
                    if caps.name("symbol").is_some() {
                        seen.insert(m.clone());
                        results.push(Layer2Recovery { marker: m.clone() });
                        break;
                    }
                }
            }
        }
    }

    results
}

// ── Marker 已存在检测 ───────────────────────────────────────────

static MARKER_EXISTS_RE_CACHE: Lazy<std::sync::Mutex<std::collections::HashMap<String, Regex>>> =
    Lazy::new(|| std::sync::Mutex::new(std::collections::HashMap::new()));

/// ←→ Python `_has_marker`：检测 markdown 中是否已有 marker 的显式上标格式。
pub fn has_marker(markdown: &str, marker: &str) -> bool {
    let esc = regex::escape(marker);
    let pattern = format!(
        r"<sup>\s*{esc}\s*</sup>|\$\s*\^\{{\s*{esc}\s*\}}\s*\$|\[\^{esc}\]",
        esc = esc
    );
    let mut cache = MARKER_EXISTS_RE_CACHE.lock().unwrap();
    let re = cache
        .entry(pattern.clone())
        .or_insert_with(|| Regex::new(&pattern).unwrap());
    re.is_match(markdown)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ocr_surrogate_double_one() {
        assert_eq!(ocr_surrogate_for_marker("11"), "!{2,}");
        assert_eq!(ocr_surrogate_for_marker("111"), "!{3,}");
        assert_eq!(ocr_surrogate_for_marker("12"), "");
    }

    #[test]
    fn suffix_surrogate() {
        assert_eq!(ocr_suffix_surrogate_for_marker("12"), "2");
        assert_eq!(ocr_suffix_surrogate_for_marker("11"), "");
        assert_eq!(ocr_suffix_surrogate_for_marker("123"), "");
    }

    #[test]
    fn utf8_safe_does_not_panic_on_french() {
        // 复现修复前的 panic：法语 `ç` 字符 + 40 字节窗口
        let text = "2. Robert Walpole, premier Comte d'Orford (1676-1745), \
            leader du parti whig, qui exerça les fonctions de « Premier ministre » \
            (First Lord of the Treasury et Chancellor of the Exchequer) de 1720 à 1742; \
            il gouverna avec pragmatisme, usant de la corruption pour controler le Parlement.";
        let markers = vec!["2".into()];
        // 不允许 panic
        let _ = find_markers_in_blocks(&[text.to_string()], &markers);
    }

    #[test]
    fn has_marker_detects_html_sup() {
        assert!(has_marker("text <sup>5</sup> more", "5"));
        assert!(has_marker("text $^{5}$ more", "5"));
        assert!(has_marker("text [^5] more", "5"));
        assert!(!has_marker("text 5 more", "5"));
    }
}
