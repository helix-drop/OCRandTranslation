//! ←→ Python `ref_freeze.py`:
//!   - `_resolve_note_item_owner` (L47)
//!   - `_shift_coords_out_of_note_ref_token` (L69)
//!   - `_inject_token_once` (L86)
//!   - `_clean_skipped_marker` (L276)
//!
//! NOTE_REF token 注入核心算法（7 层候选）。

use fnm_core::records::{BodyAnchorRecord, NoteItemRecord, NoteRegionRecord};
use fnm_core::refs;
use fnm_core::text::char_index_to_byte_index;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::{HashMap, HashSet};

/// ←→ Python `_UNICODE_SUPERSCRIPT_DIGITS` (ref_freeze.py:29)
static UNICODE_SUPERSCRIPT_DIGITS: Lazy<HashMap<char, &str>> = Lazy::new(|| {
    [
        ('\u{2070}', "0"),
        ('\u{00b9}', "1"),
        ('\u{00b2}', "2"),
        ('\u{00b3}', "3"),
        ('\u{2074}', "4"),
        ('\u{2075}', "5"),
        ('\u{2076}', "6"),
        ('\u{2077}', "7"),
        ('\u{2078}', "8"),
        ('\u{2079}', "9"),
    ]
    .iter()
    .copied()
    .collect()
});

/// 解析 note_item 实际所属的 chapter（处理 book-scope 投射）。
///
/// ←→ Python `_resolve_note_item_owner` (ref_freeze.py:47-63)
///
/// Python 版会探测 item.owner_chapter_id / item.chapter_id / region.owner_chapter_id / region.chapter_id，
/// 其中 owner_chapter_id 在 Rust records 中不一定有对应字段，因此这里仅探测 chapter_id。
pub fn resolve_note_item_owner(
    item: &NoteItemRecord,
    region_by_id: &HashMap<String, &NoteRegionRecord>,
    valid_chapter_ids: &HashSet<String>,
) -> (String, String) {
    let item_chapter_id = item.chapter_id.trim().to_string();
    if !item_chapter_id.is_empty() && valid_chapter_ids.contains(&item_chapter_id) {
        return (item_chapter_id, "item.chapter_id".to_string());
    }
    if let Some(region) = region_by_id.get(&item.region_id) {
        let region_chapter_id = region.chapter_id.trim().to_string();
        if !region_chapter_id.is_empty() && valid_chapter_ids.contains(&region_chapter_id) {
            return (region_chapter_id, "region.chapter_id".to_string());
        }
    }
    (String::new(), String::new())
}

/// 把坐标避开已有的 NOTE_REF token 范围。
///
/// ←→ Python `_shift_coords_out_of_note_ref_token` (ref_freeze.py:69-83)
pub fn shift_coords_out_of_note_ref_token(
    payload: &str,
    coord_start: usize,
    coord_end: usize,
) -> (usize, usize) {
    use fnm_core::refs::NOTE_REF_TOKEN_RE;
    for m in NOTE_REF_TOKEN_RE.find_iter(payload) {
        let token_start = m.start();
        let token_end = m.end();
        let overlaps = coord_start < token_end && coord_end > token_start;
        let insertion_inside =
            coord_start == coord_end && token_start < coord_start && coord_start < token_end;
        let starts_inside = token_start < coord_start && coord_start < token_end;
        let ends_inside = token_start < coord_end && coord_end < token_end;
        if overlaps || insertion_inside || starts_inside || ends_inside {
            return (token_end, token_end);
        }
    }
    (coord_start, coord_end)
}

/// 将权威字符索引坐标转换为 Rust UTF-8 字节边界。
///
/// BodyAnchorRecord 坐标合同与 Python 字符串切片语义一致；在 Rust 中直接
/// 按字节切片会把合法的重音或中文位置误判为非法边界。
fn character_range_to_byte_range(
    payload: &str,
    char_start: i64,
    char_end: i64,
) -> Option<(usize, usize)> {
    let start = char_start.max(0) as usize;
    let end = char_end.max(0) as usize;
    if start > end {
        return None;
    }
    Some((
        char_index_to_byte_index(payload, start)?,
        char_index_to_byte_index(payload, end)?,
    ))
}

/// 按 7 层候选顺序注入 `{{NOTE_REF:{note_id}}}` token。
///
/// ←→ Python `_inject_token_once` (ref_freeze.py:86-157)
///
/// Returns: (updated_text, injected)
pub fn inject_token_once(
    text: &str,
    anchor: &BodyAnchorRecord,
    marker: &str,
    note_id: &str,
) -> (String, bool) {
    let payload = text;
    if payload.is_empty() {
        return (payload.to_string(), false);
    }

    let token = refs::frozen_note_ref(note_id);
    if token.is_empty() {
        return (payload.to_string(), false);
    }

    // 0. token 已存在
    if payload.contains(&token) {
        return (payload.to_string(), true);
    }

    let normalized_marker = marker.trim().to_string();
    let source_marker = anchor.source_marker.trim().to_string();
    let anchor_source = anchor.source.trim().to_string();

    if let Some((coord_start, coord_end)) =
        character_range_to_byte_range(payload, anchor.char_start, anchor.char_end)
    {
        let (cs, ce) = shift_coords_out_of_note_ref_token(payload, coord_start, coord_end);

        // 1. llm source → 在 char_end 插入
        if anchor_source == "llm" && ce >= cs && ce > 0 && payload.is_char_boundary(ce) {
            let result = format!("{}{}{}", &payload[..ce], token, &payload[ce..]);
            return (result, true);
        }

        // 2. visual_repair source → 在 char_start 前插入
        if anchor_source == "visual_repair" && cs > 0 && payload.is_char_boundary(cs) {
            let result = format!("{}{}{}", &payload[..cs], token, &payload[cs..]);
            return (result, true);
        }

        // 3. 坐标区间包含 source_marker 或 normalized_marker → 替换
        if ce > cs && payload.is_char_boundary(cs) && payload.is_char_boundary(ce) {
            let coord_slice = &payload[cs..ce];
            if (!source_marker.is_empty() && coord_slice.contains(&source_marker))
                || (!normalized_marker.is_empty() && coord_slice.contains(&normalized_marker))
            {
                let result = format!("{}{}{}", &payload[..cs], token, &payload[ce..]);
                return (result, true);
            }
        }
    }

    // 4. 字符串候选顺序
    let mut candidates: Vec<String> = Vec::new();
    candidates.push(format!("[{}]", normalized_marker));
    if !source_marker.is_empty() && !source_marker.chars().all(|c| c.is_ascii_digit()) {
        candidates.insert(0, source_marker.clone());
    }
    // Unicode 上标变体
    if normalized_marker.chars().all(|c| c.is_ascii_digit()) {
        let uni_sup: String = normalized_marker
            .chars()
            .map(|d| {
                UNICODE_SUPERSCRIPT_DIGITS
                    .iter()
                    .find_map(|(&k, &v)| if v == d.to_string() { Some(k) } else { None })
                    .unwrap_or(d)
            })
            .collect();
        if uni_sup != normalized_marker {
            candidates.push(uni_sup);
        }
    }

    for candidate in &candidates {
        if candidate.is_empty() {
            continue;
        }
        if let Some(pos) = payload.find(candidate.as_str()) {
            let result = format!(
                "{}{}{}",
                &payload[..pos],
                token,
                &payload[pos + candidate.len()..]
            );
            return (result, true);
        }
    }

    // 5. llm / visual_repair → 在 source_text 后追加
    if anchor_source == "llm" || anchor_source == "visual_repair" {
        let phrase = anchor.source_text.trim().to_string();
        if !phrase.is_empty() {
            if let Some(pos) = payload.find(&phrase) {
                let result = format!(
                    "{}{}{}",
                    &payload[..pos + phrase.len()],
                    token,
                    &payload[pos + phrase.len()..]
                );
                return (result, true);
            }
        }
    }

    // 6. Regex fallback: `[ \s*(?:\^)?\s*{marker}\s* ]`
    if !normalized_marker.is_empty() {
        let pattern = format!(r"\[\s*(?:\^)?\s*{}\s*\]", regex::escape(&normalized_marker));
        if let Ok(re) = Regex::new(&pattern) {
            if let Some(m) = re.find(payload) {
                let result = format!("{}{}{}", &payload[..m.start()], token, &payload[m.end()..]);
                return (result, true);
            }
        }
    }

    // 7. 词边界 fallback: `\b{marker}\b`
    if !normalized_marker.is_empty() {
        let pattern = format!(r"\b{}\b", regex::escape(&normalized_marker));
        if let Ok(re) = Regex::new(&pattern) {
            if let Some(m) = re.find(payload) {
                let result = format!("{}{}{}", &payload[..m.start()], token, &payload[m.end()..]);
                return (result, true);
            }
        }
    }

    (payload.to_string(), false)
}

/// 带失败原因的注入结果，供 Phase 4 将坐标损坏升级为 blocker。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InjectionOutcome {
    pub text: String,
    pub injected: bool,
    pub reason: String,
}

/// 对 [`inject_token_once`] 的可诊断入口。
///
/// 坐标超出字符范围意味着上游 anchor 坐标不可用；当文本 fallback 同样
/// 不能注入时，Phase 4 必须保留原文并生成错误复核记录。
///
/// ←→ Python `_inject_token_once` 的 Phase 4 合同强化。
pub fn inject_token_once_with_reason(
    text: &str,
    anchor: &BodyAnchorRecord,
    marker: &str,
    note_id: &str,
) -> InjectionOutcome {
    let has_coordinate = anchor.char_start > 0 || anchor.char_end > 0;
    let coordinate_valid =
        character_range_to_byte_range(text, anchor.char_start, anchor.char_end).is_some();
    let (updated_text, injected) = inject_token_once(text, anchor, marker, note_id);
    InjectionOutcome {
        text: updated_text,
        injected,
        reason: if injected {
            String::new()
        } else if has_coordinate && !coordinate_valid {
            "coordinate_out_of_range".to_string()
        } else {
            "token_not_found".to_string()
        },
    }
}

/// 清理 skipped marker 的 raw 标记（`[N]` 和 `<sup>N</sup>` 格式）。
///
/// ←→ Python `_clean_skipped_marker` (ref_freeze.py:276-285)
pub fn clean_skipped_marker(text: &str, marker: &str) -> String {
    let mut payload = text.to_string();
    let m = marker.trim();
    if m.is_empty() {
        return payload;
    }
    // [N] 格式（排除 ^[N]: 定义行）
    let bracket = format!("[{}]", m);
    // 简单字符串替换：不要在 ^[N]: 后面
    let mut start = 0;
    while let Some(pos) = payload[start..].find(&bracket) {
        let abs_pos = start + pos;
        // 检查前面不是 ^
        let after_start = abs_pos + bracket.len();
        if (abs_pos > 0 && payload.as_bytes()[abs_pos - 1] == b'^')
            || (after_start < payload.len() && payload.as_bytes()[after_start] == b':')
        {
            start = abs_pos + 1;
            continue;
        }
        payload.replace_range(abs_pos..abs_pos + bracket.len(), "");
        start = abs_pos;
    }
    // <sup>N</sup> 格式
    let pattern_sup = format!(r"<sup>\s*{}\s*</sup>", regex::escape(m));
    if let Ok(re) = Regex::new(&pattern_sup) {
        payload = re.replace_all(&payload, "").to_string();
    }
    payload
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_anchor(
        char_start: i64,
        char_end: i64,
        source: &str,
        source_marker: &str,
        source_text: &str,
        synthetic: bool,
    ) -> BodyAnchorRecord {
        BodyAnchorRecord {
            anchor_id: "a1".into(),
            chapter_id: "ch1".into(),
            page_no: 1,
            char_start,
            char_end,
            source_marker: source_marker.into(),
            normalized_marker: source_marker.into(),
            source: source.into(),
            source_text: source_text.into(),
            synthetic,
            ..Default::default()
        }
    }

    #[test]
    fn test_resolve_note_item_owner_direct() {
        let item = NoteItemRecord {
            note_item_id: "n1".into(),
            chapter_id: "ch1".into(),
            ..Default::default()
        };
        let region_by_id = HashMap::new();
        let valid: HashSet<String> = ["ch1".into()].into();
        let (ch, src) = resolve_note_item_owner(&item, &region_by_id, &valid);
        assert_eq!(ch, "ch1");
        assert!(src.contains("chapter_id"));
    }

    #[test]
    fn test_shift_coords_no_token() {
        let (cs, ce) = shift_coords_out_of_note_ref_token("hello world", 2, 5);
        assert_eq!(cs, 2);
        assert_eq!(ce, 5);
    }

    #[test]
    fn test_shift_coords_inside_token() {
        let text = "before {{NOTE_REF:abc}} after";
        // 坐标在 token 内，应被移到 token 末尾
        let (cs, _ce) = shift_coords_out_of_note_ref_token(text, 10, 12);
        // 移到 token 后（25 = "before " (7) + "{{NOTE_REF:abc}}" (18)）
        // token "{{NOTE_REF:abc}}" 结束于位置 23 (7+16 chars)
        assert!(
            cs >= 23,
            "expected coord to shift past token end, got {}",
            cs
        );
    }

    #[test]
    fn test_inject_token_once_bracket_marker() {
        let anchor = make_anchor(0, 0, "", "[7]", "", false);
        let (result, injected) = inject_token_once("text [7] more", &anchor, "7", "n1");
        assert!(injected);
        assert!(result.contains("{{NOTE_REF:n1}}"));
    }

    #[test]
    fn test_inject_token_once_already_present() {
        let anchor = make_anchor(0, 0, "", "", "", false);
        let (result, injected) = inject_token_once("text {{NOTE_REF:n1}}", &anchor, "7", "n1");
        assert!(injected);
        assert_eq!(result, "text {{NOTE_REF:n1}}");
    }

    #[test]
    fn test_inject_token_once_llm_source() {
        let anchor = make_anchor(0, 5, "llm", "", "hello", false);
        let (result, injected) = inject_token_once("hello world", &anchor, "", "n1");
        assert!(injected);
        assert!(result.contains("{{NOTE_REF:n1}}"));
    }

    #[test]
    fn test_inject_token_once_visual_repair() {
        let anchor = make_anchor(6, 0, "visual_repair", "", "world", false);
        let (result, injected) = inject_token_once("hello world", &anchor, "", "n1");
        assert!(injected);
        assert!(result.contains("{{NOTE_REF:n1}}"));
    }

    #[test]
    fn test_inject_token_once_coord_slice() {
        let anchor = make_anchor(0, 5, "", "[7]", "", false);
        let (result, injected) = inject_token_once("xx[7]yy", &anchor, "7", "n1");
        assert!(injected);
        assert!(result.contains("{{NOTE_REF:n1}}"));
    }

    #[test]
    fn test_inject_token_once_word_boundary() {
        let anchor = make_anchor(0, 0, "", "7", "", false);
        let (result, injected) = inject_token_once("text 7 more", &anchor, "7", "n1");
        assert!(injected);
        assert!(result.contains("{{NOTE_REF:n1}}"));
    }

    #[test]
    fn test_clean_skipped_marker_bracket() {
        let result = clean_skipped_marker("text [7] more", "7");
        // [7] 应被清理（注意：清理后残留空格分隔）
        assert!(!result.contains("[7]"), "got: {}", result);
    }

    #[test]
    fn test_clean_skipped_marker_sup() {
        let result = clean_skipped_marker("text <sup>7</sup> more", "7");
        assert!(!result.contains("<sup>"));
    }

    #[test]
    fn test_inject_token_once_non_ascii_non_boundary_does_not_panic() {
        // 上游坐标按 Unicode 字符计数；合法范围但无 marker 时应返回 false。
        let anchor = make_anchor(2, 5, "", "x", "", false);
        let (result, injected) = inject_token_once("中文abc", &anchor, "x", "n1");
        assert!(!injected);
        assert_eq!(result, "中文abc");
    }

    #[test]
    fn test_inject_token_once_reports_coordinate_out_of_range_reason() {
        let anchor = make_anchor(8, 9, "", "x", "", false);
        let outcome = inject_token_once_with_reason("中文abc", &anchor, "x", "n1");
        assert!(!outcome.injected);
        assert_eq!(outcome.reason, "coordinate_out_of_range");
        assert_eq!(outcome.text, "中文abc");
    }

    #[test]
    fn test_inject_token_once_uses_character_offsets_for_non_ascii_text() {
        let anchor = make_anchor(2, 5, "", "abc", "", false);
        let (result, injected) = inject_token_once("中文abc", &anchor, "abc", "n1");
        assert!(injected);
        assert_eq!(result, "中文{{NOTE_REF:n1}}");
    }

    #[test]
    fn test_inject_token_once_accented_text_valid_boundary() {
        // 法语重音文本，合法边界坐标注入
        let anchor = make_anchor(2, 3, "", "[1]", "", false);
        let (result, injected) = inject_token_once("hé [1] world", &anchor, "1", "n1");
        assert!(injected);
        assert!(result.contains("{{NOTE_REF:n1}}"));
    }

    #[test]
    fn test_inject_token_once_coord_at_boundary_non_ascii() {
        let anchor = make_anchor(0, 4, "", "[1]", "", false); // "café" 是 5 字节
        let (result, injected) = inject_token_once("café [1] text", &anchor, "1", "n1");
        assert!(injected);
        assert!(result.contains("{{NOTE_REF:n1}}"));
    }
}
