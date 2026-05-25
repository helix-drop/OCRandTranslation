//! ←→ FNM_RE/shared/anchors.py:_scan_inline_refs + scan_anchor_markers
//!
//! 11 个正则模式扫描正文中的 body anchor 候选，做重叠去重 + 年份过滤。

use fnm_core::anchor_kind::{is_bracket_ref_valid, looks_like_year_marker, patterns};
use fnm_core::note_marker::normalize_note_marker;
use fnm_core::text::byte_index_to_char_index;
use once_cell::sync::Lazy;
use std::collections::HashMap;

use super::context_guard::is_bare_digit_marker_context;

// ── 确定性映射 ──────────────────────────────────────────────────

static REF_PATTERN_CERTAINTY: Lazy<HashMap<&'static str, f64>> = Lazy::new(|| {
    let mut m = HashMap::new();
    m.insert("footnote_ref", 1.0);
    m.insert("latex", 1.0);
    m.insert("html", 1.0);
    m.insert("html_symbol_sup", 1.0);
    m.insert("bracket", 1.0);
    m.insert("broken_left_bracket", 0.85);
    m.insert("unicode", 1.0);
    m.insert("plain", 0.4);
    m.insert("latex_symbol_sup", 1.0);
    m.insert("apostrophe_sup", 0.55);
    m.insert("trailing_symbol", 0.9);
    m.insert("bare_digit", 0.6);
    m
});

fn pattern_certainty(kind: &str) -> f64 {
    REF_PATTERN_CERTAINTY.get(kind).copied().unwrap_or(0.4)
}

// ── 优先级映射（越低越优先）────────────────────────────────────

static REF_PATTERN_PRIORITY: Lazy<HashMap<&'static str, i32>> = Lazy::new(|| {
    let mut m = HashMap::new();
    m.insert("footnote_ref", 0);
    m.insert("latex", 0);
    m.insert("latex_symbol_sup", 0);
    m.insert("html_symbol_sup", 0);
    m.insert("plain", 1);
    m.insert("html", 2);
    m.insert("unicode", 3);
    m.insert("apostrophe_sup", 3);
    m.insert("bracket", 4);
    m.insert("broken_left_bracket", 4);
    m.insert("trailing_symbol", 5);
    m.insert("bare_digit", 6);
    m
});

fn pattern_priority(kind: &str) -> i32 {
    REF_PATTERN_PRIORITY.get(kind).copied().unwrap_or(99)
}

// ── RawAnchor ───────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct RawAnchor {
    pub source_marker: String,
    pub normalized_marker: String,
    pub char_start: usize,
    pub char_end: usize,
    pub pattern: String,
    pub certainty: f64,
}

// ── scan_inline_refs ────────────────────────────────────────────

/// 扫描文本中所有 inline reference markers（不去重、不过滤年份）。
///
/// ←→ Python `_scan_inline_refs(text)`
pub fn scan_inline_refs(text: &str) -> Vec<RawAnchor> {
    let mut refs: Vec<RawAnchor> = Vec::new();

    // 模式 1: footnote_ref [^N]
    for caps in patterns::FOOTNOTE_REF_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "footnote_ref"));
        }
    }

    // 模式 2: latex $^{N}$
    for caps in patterns::LATEX_SUP_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "latex"));
        }
    }

    // 模式 3: latex_symbol_sup $^{*}$
    for caps in patterns::LATEX_SYMBOL_SUP_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "latex_symbol_sup"));
        }
    }

    // 模式 4: html_symbol_sup <sup>*</sup>
    for caps in patterns::HTML_SYMBOL_SUP_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "html_symbol_sup"));
        }
    }

    // 模式 5: plain ^{N}
    for caps in patterns::PLAIN_SUP_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "plain"));
        }
    }

    // 模式 6: html <sup>N</sup>
    for caps in patterns::HTML_SUP_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "html"));
        }
    }

    // 模式 7: bracket [N]
    for caps in patterns::BRACKET_REF_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if !is_bracket_ref_valid(text, m.start(), m.end()) {
            continue;
        }
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "bracket"));
        }
    }

    // 模式 8: broken_left_bracket word[N.
    for caps in patterns::BROKEN_LEFT_BRACKET_REF_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "broken_left_bracket"));
        }
    }

    // 模式 9: apostrophe_sup 'N
    for caps in patterns::APOSTROPHE_SUP_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "apostrophe_sup"));
        }
    }

    // 模式 10: trailing_symbol after bracket ]
    for caps in patterns::TRAILING_SYMBOL_AFTER_BRACKET_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "trailing_symbol"));
        }
    }

    // 模式 11: trailing_symbol after quote »
    for caps in patterns::TRAILING_SYMBOL_AFTER_QUOTE_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        if let Some(marker) = extract_marker(&caps, 1) {
            refs.push(build_raw_anchor(text, m, &marker, "trailing_symbol"));
        }
    }

    // 模式 12: unicode 上标 ⁰¹²³...
    for caps in patterns::UNICODE_SUP_RE.captures_iter(text) {
        let m = caps.get(0).unwrap();
        let raw = m.as_str();
        let marker = normalize_note_marker(raw);
        if !marker.is_empty() {
            refs.push(RawAnchor {
                source_marker: raw.to_string(),
                normalized_marker: marker,
                char_start: byte_index_to_char_index(text, m.start()).expect("regex boundary"),
                char_end: byte_index_to_char_index(text, m.end()).expect("regex boundary"),
                pattern: "unicode".to_string(),
                certainty: pattern_certainty("unicode"),
            });
        }
    }

    // 模式 13: bare_digit（优先级最低）
    // ←→ Python `_scan_inline_refs`：匹配后立即用 `_is_bare_digit_marker_context` 过滤
    for caps in patterns::BARE_DIGIT_RE.captures_iter(text) {
        let digit_match = caps.get(1).unwrap();
        let digit_start = digit_match.start();
        let digit_end = digit_match.end();
        if !is_bare_digit_marker_context(text, digit_start, digit_end) {
            continue;
        }
        let marker = normalize_note_marker(digit_match.as_str());
        if marker.is_empty() {
            continue;
        }
        refs.push(RawAnchor {
            source_marker: digit_match.as_str().to_string(),
            normalized_marker: marker,
            char_start: byte_index_to_char_index(text, digit_start).expect("regex boundary"),
            char_end: byte_index_to_char_index(text, digit_end).expect("regex boundary"),
            pattern: "bare_digit".to_string(),
            certainty: pattern_certainty("bare_digit"),
        });
    }

    refs.sort_by_key(|r| (r.char_start, r.char_end));
    refs
}

// ── scan_anchor_markers（去重 + 过滤年份）───────────────────────

/// 扫描 anchor markers，做重叠去重 + 年份过滤。
///
/// ←→ Python `scan_anchor_markers(text)`
///
/// 返回：(去重后的 anchors, 被过滤的年份-like marker 数量)
pub fn scan_anchor_markers(text: &str) -> (Vec<RawAnchor>, usize) {
    let mut deduped: Vec<RawAnchor> = Vec::new();
    let mut year_like_filtered = 0usize;

    for candidate in scan_inline_refs(text) {
        let normalized = normalize_note_marker(&candidate.normalized_marker);
        if normalized.is_empty() {
            continue;
        }
        if looks_like_year_marker(&normalized) {
            year_like_filtered += 1;
            continue;
        }

        let mut replaced = false;
        for existing in deduped.iter_mut() {
            if existing.normalized_marker == normalized && overlap(existing, &candidate) {
                *existing = preferred(existing.clone(), candidate.clone());
                replaced = true;
                break;
            }
        }
        if !replaced {
            let mut c = candidate;
            c.normalized_marker = normalized;
            deduped.push(c);
        }
    }

    deduped.sort_by_key(|r| (r.char_start, r.char_end));
    (deduped, year_like_filtered)
}

// ── 内部辅助 ────────────────────────────────────────────────────

fn extract_marker(caps: &regex::Captures<'_>, group_idx: usize) -> Option<String> {
    let raw = caps.get(group_idx)?.as_str();
    let normalized = normalize_note_marker(raw);
    if normalized.is_empty() {
        None
    } else {
        Some(normalized)
    }
}

fn build_raw_anchor(text: &str, m: regex::Match, marker: &str, kind: &str) -> RawAnchor {
    RawAnchor {
        source_marker: m.as_str().trim().to_string(),
        normalized_marker: marker.to_string(),
        char_start: byte_index_to_char_index(text, m.start()).expect("regex boundary"),
        char_end: byte_index_to_char_index(text, m.end()).expect("regex boundary"),
        pattern: kind.to_string(),
        certainty: pattern_certainty(kind),
    }
}

fn overlap(left: &RawAnchor, right: &RawAnchor) -> bool {
    !(left.char_end <= right.char_start || right.char_end <= left.char_start)
}

fn preferred(left: RawAnchor, right: RawAnchor) -> RawAnchor {
    let left_p = pattern_priority(&left.pattern);
    let right_p = pattern_priority(&right.pattern);
    if right_p < left_p {
        return right;
    }
    if right_p > left_p {
        return left;
    }
    let left_span = left.char_end - left.char_start;
    let right_span = right.char_end - right.char_start;
    if right_span > left_span {
        right
    } else {
        left
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inline_ref_offsets_follow_python_character_indices() {
        let refs = scan_inline_refs("économie¹⁶");
        let anchor = refs
            .iter()
            .find(|row| row.source_marker == "¹⁶")
            .expect("unicode marker");
        assert_eq!(anchor.char_start, 8);
        assert_eq!(anchor.char_end, 10);
    }
}
