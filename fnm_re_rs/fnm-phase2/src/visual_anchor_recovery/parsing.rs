//! ←→ FNM_RE/modules/visual_anchor_recovery.py
//! VLM 响应解析 + anchor_phrase 清洗 + 子串相似度 + roman/superscript 工具。
//!
//! 这些是 Python 端的辅助函数，被 `_materialize_visual_findings` 用于将
//! VLM 返回的 findings 转为 BodyAnchorRecord。

use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::Value;

// ── 系统 prompt（完整 Python 原文）─────────────────────────────

pub const VISUAL_RECOVERY_SYSTEM_PROMPT: &str = "\
You are an expert at reading printed book pages. Your task is to locate \
superscript reference markers (endnote markers) in scanned book page images.

The book uses superscript numbers (like ⁸ or ¹⁰) in the body text to mark \
endnote references. OCR has failed to recognize these superscripts — they \
may look like regular numbers, symbols, or be missing entirely in the OCR output.

For each missing marker in the list:
1. Scan the page images for a superscript number matching that marker
2. Identify the word or short phrase (3-15 characters) immediately BEFORE the superscript
   IMPORTANT: the anchor_phrase MUST NOT include the superscript itself or text after it.
   For example, if the text is \"intelligibilité⁸ de ce processus\", the phrase is \"intelligibilité\".
3. Note the page number where you found it
4. Record the superscript in its original Unicode form (e.g. \"⁸\", \"¹⁰\", \"¹⁷\")

Return ONLY a JSON array of found markers. Each entry:
- \"marker\": integer marker number
- \"page_no\": the printed book page number as an INTEGER (e.g. 49, 127). Do NOT use Roman numerals.
- \"anchor_phrase\": ONLY the text BEFORE the superscript, 3-15 characters, no superscript digits
- \"source_marker\": superscript in Unicode form (e.g. \"⁸\", \"¹⁰\")

Only report markers you can clearly identify as superscript reference numbers. \
If you cannot find a marker, omit it from the output. \
Do not guess. Do not include explanations.";

// ── User prompt builder ────────────────────────────────────────

/// ←→ Python `_build_visual_recovery_user_prompt`
pub fn build_visual_recovery_user_prompt(
    missing_markers: &[i64],
    page_start: i64,
    page_end: i64,
) -> String {
    let markers_str = missing_markers
        .iter()
        .map(|m| m.to_string())
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "Find these missing endnote superscript markers in the body text: [{markers_str}].\n\
         Page range: {page_start} to {page_end}.\n\
         Return a JSON array. Format: [{{\"marker\": 8, \"page_no\": 49, \
         \"anchor_phrase\": \"intelligibilité\", \"source_marker\": \"⁸\"}}]"
    )
}

// ── 罗马数字 ─────────────────────────────────────────────────────

static ROMAN_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$").unwrap()
});

const ROMAN_VALUES: &[(&str, i64)] = &[
    ("M", 1000),
    ("CM", 900),
    ("D", 500),
    ("CD", 400),
    ("C", 100),
    ("XC", 90),
    ("L", 50),
    ("XL", 40),
    ("X", 10),
    ("IX", 9),
    ("V", 5),
    ("IV", 4),
    ("I", 1),
];

/// ←→ Python `_roman_to_int`
pub fn roman_to_int(s: &str) -> i64 {
    let upper = s.trim().to_uppercase();
    if upper.is_empty() || !ROMAN_RE.is_match(&upper) {
        return 0;
    }
    let upper_bytes = upper.as_bytes();
    let mut result = 0i64;
    let mut idx = 0usize;
    for &(symbol, value) in ROMAN_VALUES {
        let sym_bytes = symbol.as_bytes();
        while idx + sym_bytes.len() <= upper_bytes.len()
            && &upper_bytes[idx..idx + sym_bytes.len()] == sym_bytes
        {
            result += value;
            idx += sym_bytes.len();
        }
    }
    result
}

// ── 上标 ─────────────────────────────────────────────────────────

/// ←→ Python `_int_to_unicode_superscript`
pub fn int_to_unicode_superscript(n: i64) -> String {
    if n < 0 {
        return n.to_string();
    }
    let digits = n.to_string();
    digits
        .chars()
        .map(|c| match c {
            '0' => '\u{2070}',
            '1' => '\u{00B9}',
            '2' => '\u{00B2}',
            '3' => '\u{00B3}',
            '4' => '\u{2074}',
            '5' => '\u{2075}',
            '6' => '\u{2076}',
            '7' => '\u{2077}',
            '8' => '\u{2078}',
            '9' => '\u{2079}',
            _ => c,
        })
        .collect()
}

const SUPERSCRIPT_CHARS: &[char] = &[
    '\u{2070}', '\u{00B9}', '\u{00B2}', '\u{00B3}', '\u{2074}', '\u{2075}', '\u{2076}', '\u{2077}',
    '\u{2078}', '\u{2079}',
];

/// ←→ Python `_sanitize_anchor_phrase`
pub fn sanitize_anchor_phrase(raw: &str) -> String {
    if raw.is_empty() {
        return String::new();
    }
    let mut cleaned: String = raw
        .replace(['\n', '\r'], " ")
        .chars()
        .filter(|c| !SUPERSCRIPT_CHARS.contains(c))
        .collect();
    // 折叠空格
    cleaned = cleaned.split_whitespace().collect::<Vec<_>>().join(" ");
    cleaned.trim().to_string()
}

// ── 子串相似度 ──────────────────────────────────────────────────

/// ←→ Python `_simple_substring_similarity`
/// 滑窗对齐计算最大匹配字符数 / pattern 长度。
pub fn simple_substring_similarity(pattern: &str, text: &str) -> f64 {
    let p_chars: Vec<char> = pattern.chars().collect();
    let t_chars: Vec<char> = text.chars().collect();
    let pw = p_chars.len();
    let tw = t_chars.len();
    if pw == 0 || tw == 0 || pw > tw {
        return 0.0;
    }
    let mut best = 0usize;
    for start in 0..=(tw - pw) {
        let matches = (0..pw)
            .filter(|&i| p_chars[i] == t_chars[start + i])
            .count();
        if matches > best {
            best = matches;
            if best == pw {
                break;
            }
        }
    }
    if pw == 0 {
        0.0
    } else {
        best as f64 / pw as f64
    }
}

/// ←→ Python `_best_window_location`
/// 在 text 中找与 pattern 最相似的滑动窗口位置，返回 (start, end)。
pub fn best_window_location(text: &str, pattern: &str) -> Option<(usize, usize)> {
    let t_chars: Vec<char> = text.chars().collect();
    let p_chars: Vec<char> = pattern.chars().collect();
    let pw = p_chars.len();
    if pw == 0 || pw > t_chars.len() {
        return None;
    }
    let mut best_dist = pw + 1;
    let mut best_start = 0usize;
    for start in 0..=(t_chars.len() - pw) {
        let dist = (0..pw)
            .filter(|&i| p_chars[i] != t_chars[start + i])
            .count();
        if dist < best_dist {
            best_dist = dist;
            best_start = start;
            if best_dist == 0 {
                break;
            }
        }
    }
    Some((best_start, best_start + pw))
}

// ── 采样页范围 ──────────────────────────────────────────────────

/// ←→ Python `_sample_page_range`
pub fn sample_page_range(page_min: i64, page_max: i64, max_images: usize) -> Vec<i64> {
    if page_min <= 0 || page_max < page_min || max_images == 0 {
        return Vec::new();
    }
    let span = (page_max - page_min + 1) as usize;
    if span <= max_images {
        return (page_min..=page_max).collect();
    }
    let step = (page_max - page_min) as f64 / max_images as f64;
    (0..max_images)
        .map(|i| page_min + (i as f64 * step) as i64)
        .collect()
}

// ── VLM 响应解析 ────────────────────────────────────────────────

static JSON_ARRAY_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?s)\[\s*\{.*?\}\s*\]").unwrap());

static FENCED_CODE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?s)```(?:json)?\s*(.*?)\s*```").unwrap());

/// ←→ Python `_parse_visual_findings`
pub fn parse_visual_findings(raw_text: &str) -> Vec<Value> {
    if raw_text.is_empty() {
        return Vec::new();
    }
    let text = FENCED_CODE_RE
        .captures(raw_text)
        .and_then(|c| c.get(1))
        .map(|m| m.as_str().to_string())
        .unwrap_or_else(|| raw_text.to_string());
    let arr_match = match JSON_ARRAY_RE.find(&text) {
        Some(m) => m.as_str(),
        None => return Vec::new(),
    };
    let parsed: Value = match serde_json::from_str(arr_match) {
        Ok(v) => v,
        Err(_) => return Vec::new(),
    };
    parsed
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|item| item.is_object())
        .collect()
}

// ── Visual anchor ID 生成 ──────────────────────────────────────

static VISUAL_ANCHOR_SERIAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// ←→ Python `_next_visual_anchor_id`
pub fn next_visual_anchor_id() -> String {
    let n = VISUAL_ANCHOR_SERIAL.fetch_add(1, std::sync::atomic::Ordering::SeqCst) + 1;
    format!("visual-{:05}", n)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roman_to_int_basic() {
        assert_eq!(roman_to_int("I"), 1);
        assert_eq!(roman_to_int("IX"), 9);
        assert_eq!(roman_to_int("XLII"), 42);
        assert_eq!(roman_to_int("MCMXCIV"), 1994);
    }

    #[test]
    fn roman_to_int_invalid() {
        assert_eq!(roman_to_int(""), 0);
        assert_eq!(roman_to_int("abc"), 0);
        assert_eq!(roman_to_int("IIII"), 0); // 不合法的罗马形式
    }

    #[test]
    fn int_to_superscript() {
        assert_eq!(int_to_unicode_superscript(0), "⁰");
        assert_eq!(int_to_unicode_superscript(8), "⁸");
        assert_eq!(int_to_unicode_superscript(10), "¹⁰");
        assert_eq!(int_to_unicode_superscript(127), "¹²⁷");
    }

    #[test]
    fn sanitize_strips_superscripts_and_newlines() {
        let result = sanitize_anchor_phrase("intelligibilité⁸\n\n  de");
        assert_eq!(result, "intelligibilité de");
    }

    #[test]
    fn substring_similarity_exact() {
        assert_eq!(simple_substring_similarity("abc", "xabcy"), 1.0);
    }

    #[test]
    fn substring_similarity_partial() {
        let r = simple_substring_similarity("abc", "axc");
        assert!((r - 2.0 / 3.0).abs() < 1e-9 || r >= 2.0 / 3.0);
    }

    #[test]
    fn best_window_finds_exact() {
        let loc = best_window_location("the quick brown fox", "quick").unwrap();
        assert_eq!(&"the quick brown fox"[loc.0..loc.1], "quick");
    }

    #[test]
    fn sample_page_range_dense() {
        assert_eq!(sample_page_range(10, 12, 5), vec![10, 11, 12]);
    }

    #[test]
    fn sample_page_range_sparse() {
        let samples = sample_page_range(1, 100, 5);
        assert_eq!(samples.len(), 5);
        assert!(samples[0] >= 1 && *samples.last().unwrap() <= 100);
    }

    #[test]
    fn parse_findings_extracts_json() {
        let raw = r#"```json
        [{"marker": 8, "page_no": 49, "anchor_phrase": "intel", "source_marker": "⁸"}]
        ```"#;
        let findings = parse_visual_findings(raw);
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0]["marker"], 8);
    }

    #[test]
    fn parse_findings_plain_array() {
        let raw = r#"[{"marker": 8, "page_no": 49}]"#;
        let findings = parse_visual_findings(raw);
        assert_eq!(findings.len(), 1);
    }

    #[test]
    fn parse_findings_no_array() {
        assert!(parse_visual_findings("no JSON here").is_empty());
    }

    #[test]
    fn build_prompt_includes_markers() {
        let prompt = build_visual_recovery_user_prompt(&[8, 12, 17], 49, 60);
        assert!(prompt.contains("[8, 12, 17]"));
        assert!(prompt.contains("49 to 60"));
    }

    #[test]
    fn visual_anchor_id_increments() {
        let a = next_visual_anchor_id();
        let b = next_visual_anchor_id();
        assert_ne!(a, b);
        assert!(a.starts_with("visual-"));
    }
}
