//! 数值解析：罗马数字、英文词形、章节号提取。
//!
//! ←→ Python `endnote_chapter_explorer.py` 中的 `_number_token_to_int` / `_extract_number_info`

use fnm_core::title::normalize_title;
use once_cell::sync::Lazy;
use regex::Regex;

static CHAPTER_NUMBER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:chapter|chapitre)\s+(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[ivxlcdm]+|\d+)\b(?:[\s:.\-]+(.*))?$"
    ).unwrap()
});

static LEADING_NUMBER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[ivxlcdm]+|\d+)[\.\)]?(?:\s+|$)(.*)$"
    ).unwrap()
});

pub(super) static GENERIC_NOTES_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*|注释|脚注|尾注)\s*$")
        .unwrap()
});

pub(super) static NAMED_NOTES_TARGET_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*notes?\s+to\s+(.+?)\s*$").unwrap());

fn word_number(token: &str) -> Option<i64> {
    match token.to_lowercase().as_str() {
        "one" => Some(1),
        "two" => Some(2),
        "three" => Some(3),
        "four" => Some(4),
        "five" => Some(5),
        "six" => Some(6),
        "seven" => Some(7),
        "eight" => Some(8),
        "nine" => Some(9),
        "ten" => Some(10),
        "eleven" => Some(11),
        "twelve" => Some(12),
        _ => None,
    }
}

/// 罗马数字 → 整数。
pub fn roman_to_int(s: &str) -> i64 {
    let s = s.trim().to_uppercase();
    let mut total: i64 = 0;
    let mut previous: i64 = 0;
    for c in s.chars().rev() {
        let value = match c {
            'I' => 1,
            'V' => 5,
            'X' => 10,
            'L' => 50,
            'C' => 100,
            'D' => 500,
            'M' => 1000,
            _ => return 0,
        };
        if value < previous {
            total -= value;
        } else {
            total += value;
            previous = value;
        }
    }
    total
}

/// 解析数字/罗马/词形 token。
/// ←→ Python `_number_token_to_int`
pub fn number_token_to_int(token: &str) -> i64 {
    let raw = token.trim();
    if raw.is_empty() {
        return 0;
    }
    if let Ok(v) = raw.parse::<i64>() {
        return v;
    }
    if let Some(v) = word_number(raw) {
        return v;
    }
    roman_to_int(raw)
}

/// 从 chapter title 提取 (number_value, remainder)。
/// ←→ Python `_extract_number_info`
pub fn extract_number_info(text: &str) -> (i64, String) {
    let normalized = normalize_title(text);
    if normalized.is_empty() {
        return (0, String::new());
    }
    if let Some(caps) = CHAPTER_NUMBER_RE.captures(&normalized) {
        let num_str = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        let remainder = caps.get(2).map(|m| m.as_str()).unwrap_or("");
        return (number_token_to_int(num_str), normalize_title(remainder));
    }
    if let Some(caps) = LEADING_NUMBER_RE.captures(&normalized) {
        let num_str = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        let remainder = caps.get(2).map(|m| m.as_str()).unwrap_or("");
        return (number_token_to_int(num_str), normalize_title(remainder));
    }
    (0, normalized)
}

pub(super) fn is_generic_notes_title(text: &str) -> bool {
    GENERIC_NOTES_TITLE_RE.is_match(&normalize_title(text))
}

// ── SequenceMatcher.ratio() 等价实现 ─────────────────────────────

/// LCS-based similarity ratio：返回 `2.0 * lcs_len / (a_len + b_len)`，
/// 等价于 Python `difflib.SequenceMatcher(None, a, b).ratio()` 在两短串场景下的输出。
pub fn sequence_matcher_ratio(a: &str, b: &str) -> f64 {
    let a_chars: Vec<char> = a.chars().collect();
    let b_chars: Vec<char> = b.chars().collect();
    let a_len = a_chars.len();
    let b_len = b_chars.len();
    if a_len == 0 && b_len == 0 {
        return 1.0;
    }
    if a_len == 0 || b_len == 0 {
        return 0.0;
    }
    // DP LCS
    let mut prev = vec![0usize; b_len + 1];
    let mut cur = vec![0usize; b_len + 1];
    for i in 1..=a_len {
        for j in 1..=b_len {
            cur[j] = if a_chars[i - 1] == b_chars[j - 1] {
                prev[j - 1] + 1
            } else {
                prev[j].max(cur[j - 1])
            };
        }
        std::mem::swap(&mut prev, &mut cur);
        cur.iter_mut().for_each(|v| *v = 0);
    }
    let lcs = prev[b_len];
    2.0 * lcs as f64 / (a_len + b_len) as f64
}
