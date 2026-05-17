//! ←→ FNM_RE/shared/ref_rewriter.py
//! 注释引用重写工具：NOTE_REF → 本地编号 label。

use crate::export_constants::{
    unicode_superscript_to_ascii, ANY_NOTE_REF_RE, CORRUPTED_NOTE_REF_RE,
};
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::{HashMap, HashSet};

static STAR_MARKER_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\*{1,4}$").unwrap());

/// 生成 marker 的规范化 key。与 Python `_marker_key` 一致。
pub fn marker_key(raw: &str) -> String {
    let normalized: String = raw
        .trim()
        .chars()
        .map(unicode_superscript_to_ascii)
        .collect();
    let normalized = normalized.to_lowercase();
    if STAR_MARKER_RE.is_match(&normalized) {
        return normalized;
    }
    let cleaned: String = normalized
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .collect();
    if cleaned.starts_with("en")
        && cleaned.len() > 2
        && cleaned[2..].chars().all(|c| c.is_ascii_digit())
    {
        return cleaned[2..].to_string();
    }
    cleaned
}

/// 生成 marker 的所有 alias。与 Python `_marker_aliases` 一致。
pub fn marker_aliases(raw: &str) -> HashSet<String> {
    let key = marker_key(raw);
    if key.is_empty() {
        return HashSet::new();
    }
    let mut aliases = HashSet::new();
    aliases.insert(key.clone());
    let trimmed = key.trim_start_matches('0').to_string();
    if !trimmed.is_empty() {
        aliases.insert(trimmed);
    }
    if let Some(stripped) = key.strip_prefix("en") {
        aliases.insert(stripped.to_string());
    }
    aliases.into_iter().filter(|t| !t.is_empty()).collect()
}

/// 规范化 endnote id（保证 `en-` 前缀）。
#[allow(dead_code)]
fn normalize_endnote_note_id(note_id: &str) -> String {
    let token = note_id.trim();
    if token.is_empty() {
        return String::new();
    }
    if token.to_lowercase().starts_with("en-") {
        token.to_string()
    } else {
        format!("en-{}", token)
    }
}

/// 解析 note_id（尝试匹配 note_text_by_id 中的 key）。
/// 与 Python `_resolve_note_id` 一致。
pub fn resolve_note_id(note_id: &str, note_text_by_id: &HashMap<String, String>) -> String {
    let token = note_id.trim();
    if token.is_empty() {
        return String::new();
    }
    if note_text_by_id.contains_key(token) {
        return token.to_string();
    }
    if token.to_lowercase().starts_with("en-") {
        let stripped = &token[3..];
        if note_text_by_id.contains_key(stripped) {
            return stripped.to_string();
        }
    } else {
        let endnote = format!("en-{}", token);
        if note_text_by_id.contains_key(&endnote) {
            return endnote;
        }
    }
    String::new()
}

/// 解析 note_kind。与 Python `_resolve_note_kind` 一致。
pub fn resolve_note_kind(note_id: &str, note_kind_by_id: &HashMap<String, String>) -> String {
    if let Some(kind) = note_kind_by_id.get(note_id) {
        let k = kind.trim().to_lowercase();
        if k == "endnote" || k == "footnote" {
            return k;
        }
    }
    let normalized = note_id.trim();
    if let Some(stripped) = normalized.strip_prefix("en-") {
        if let Some(kind) = note_kind_by_id.get(stripped) {
            let k = kind.trim().to_lowercase();
            if k == "endnote" || k == "footnote" {
                return k;
            }
        }
    } else if !normalized.is_empty() {
        let prefixed = format!("en-{}", normalized);
        if let Some(kind) = note_kind_by_id.get(&prefixed) {
            let k = kind.trim().to_lowercase();
            if k == "endnote" || k == "footnote" {
                return k;
            }
        }
    }
    String::new()
}

/// 从 marker_note_sequences 消费一个 note_id。
/// 与 Python `_consume_marker_note_id` 一致。
pub fn consume_marker_note_id(
    marker: &str,
    marker_note_sequences: &HashMap<String, Vec<String>>,
    marker_usage_index: &mut HashMap<String, usize>,
) -> String {
    let normalized = marker_key(marker);
    if normalized.is_empty() {
        return String::new();
    }
    let index = *marker_usage_index.get(&normalized).unwrap_or(&0);
    // 只取需要的元素，不 clone 整个 Vec
    let result = marker_note_sequences
        .get(&normalized)
        .and_then(|candidates| candidates.get(index))
        .cloned()
        .unwrap_or_default();
    if !result.is_empty() {
        marker_usage_index.insert(normalized, index + 1);
    }
    result
}

/// 分配本地 endnote 引用编号。
/// 与 Python `_local_endnote_ref_number` 一致。
pub fn local_endnote_ref_number(
    note_id: &str,
    note_kind_by_id: &HashMap<String, String>,
    local_ref_numbers: &mut HashMap<String, i64>,
    ordered_note_ids: &mut Vec<String>,
    note_marker_by_id: Option<&HashMap<String, String>>,
) -> Option<i64> {
    let kind = resolve_note_kind(note_id, note_kind_by_id);
    if kind == "footnote" {
        return None;
    }
    if let Some(&num) = local_ref_numbers.get(note_id) {
        return Some(num);
    }
    if let Some(marker_map) = note_marker_by_id {
        if let Some(original) = marker_map.get(note_id) {
            if original.chars().all(|c| c.is_ascii_digit()) {
                if let Ok(candidate) = original.parse::<i64>() {
                    if candidate > 0 && !local_ref_numbers.values().any(|&v| v == candidate) {
                        local_ref_numbers.insert(note_id.to_string(), candidate);
                        ordered_note_ids.push(note_id.to_string());
                        return Some(candidate);
                    }
                }
            } else if kind == "endnote" {
                return None;
            }
        }
    }
    // ←→ Python: while 循环跳过已被占用的编号，防止编号序列空洞
    let mut next_num = local_ref_numbers.values().max().copied().unwrap_or(0) + 1;
    while local_ref_numbers.values().any(|&v| v == next_num) {
        next_num += 1;
    }
    local_ref_numbers.insert(note_id.to_string(), next_num);
    ordered_note_ids.push(note_id.to_string());
    Some(next_num)
}

/// 替换文本中的 NOTE_REF 等 token 为本地编号 `[^N]`。
/// 与 Python `replace_note_refs_with_local_labels` 一致（简化版）。
pub fn replace_note_refs_with_local_labels(
    text: &str,
    note_text_by_id: &HashMap<String, String>,
    note_kind_by_id: &HashMap<String, String>,
    local_ref_numbers: &mut HashMap<String, i64>,
    ordered_note_ids: &mut Vec<String>,
    mut footnote_ids_seen: Option<&mut Vec<String>>,
    note_marker_by_id: Option<&HashMap<String, String>>,
) -> String {
    let text = CORRUPTED_NOTE_REF_RE.replace_all(text, "{{NOTE_REF:$1}}");

    ANY_NOTE_REF_RE
        .replace_all(&text, |caps: &regex::Captures| {
            let note_id = caps.get(1).or(caps.get(2)).or(caps.get(3)).or(caps.get(4));
            let note_id = match note_id {
                Some(m) => m.as_str().trim().to_string(),
                None => return caps.get(0).unwrap().as_str().to_string(),
            };
            if note_id.is_empty() {
                return caps.get(0).unwrap().as_str().to_string();
            }

            let resolved = resolve_note_id(&note_id, note_text_by_id);
            if resolved.is_empty() {
                return caps.get(0).unwrap().as_str().to_string();
            }
            let ref_num = local_endnote_ref_number(
                &resolved,
                note_kind_by_id,
                local_ref_numbers,
                ordered_note_ids,
                note_marker_by_id,
            );
            match ref_num {
                Some(n) => format!("[^{}]", n),
                None => {
                    if let Some(ref mut ids) = footnote_ids_seen {
                        if !ids.contains(&resolved) {
                            ids.push(resolved.clone());
                        }
                    }
                    "*".to_string()
                }
            }
        })
        .to_string()
}

/// 替换 `[N]` 格式的原始端末引用为本地编号 `[^N]`。
/// ←→ Python `replace_raw_bracket_refs_with_local_labels`
pub fn replace_raw_bracket_refs_with_local_labels(
    text: &str,
    marker_note_sequences: &HashMap<String, Vec<String>>,
    marker_usage_index: &mut HashMap<String, usize>,
    note_kind_by_id: &HashMap<String, String>,
    local_ref_numbers: &mut HashMap<String, i64>,
    ordered_note_ids: &mut Vec<String>,
    mut footnote_ids_seen: Option<&mut Vec<String>>,
    note_marker_by_id: Option<&HashMap<String, String>>,
) -> String {
    use crate::export_constants::RAW_BRACKET_NOTE_REF_RE;
    RAW_BRACKET_NOTE_REF_RE
        .replace_all(text, |caps: &regex::Captures| {
            // ←→ Python `(?<!\d)...(?!\d)`：手动检查前后字符不是数字
            let full_match = caps.get(0).map(|m| (m.start(), m.end()));
            if let Some((start, end)) = full_match {
                let before = text[..start].chars().last();
                if before.map_or(false, |c| c.is_ascii_digit()) {
                    return caps.get(0).unwrap().as_str().to_string();
                }
                let after = text[end..].chars().next();
                if after.map_or(false, |c| c.is_ascii_digit()) {
                    return caps.get(0).unwrap().as_str().to_string();
                }
            }
            let marker = caps.get(1).map(|m| m.as_str()).unwrap_or("");
            let note_id = consume_marker_note_id(marker, marker_note_sequences, marker_usage_index);
            if note_id.is_empty() {
                return caps.get(0).map(|m| m.as_str().to_string()).unwrap_or_default();
            }
            let ref_num = local_endnote_ref_number(
                &note_id,
                note_kind_by_id,
                local_ref_numbers,
                ordered_note_ids,
                note_marker_by_id,
            );
            match ref_num {
                Some(n) => format!("[^{}]", n),
                None => {
                    if let Some(ref mut ids) = footnote_ids_seen {
                        if !ids.contains(&note_id) {
                            ids.push(note_id);
                        }
                    }
                    "*".to_string()
                }
            }
        })
        .to_string()
}

/// 替换 `<sup>N</sup>` 格式的原始上标引用为本地编号 `[^N]`。
/// ←→ Python `replace_raw_superscript_refs_with_local_labels`
pub fn replace_raw_superscript_refs_with_local_labels(
    text: &str,
    marker_note_sequences: &HashMap<String, Vec<String>>,
    marker_usage_index: &mut HashMap<String, usize>,
    note_kind_by_id: &HashMap<String, String>,
    local_ref_numbers: &mut HashMap<String, i64>,
    ordered_note_ids: &mut Vec<String>,
    mut footnote_ids_seen: Option<&mut Vec<String>>,
    note_marker_by_id: Option<&HashMap<String, String>>,
) -> String {
    use crate::export_constants::RAW_SUPERSCRIPT_NOTE_REF_RE;
    RAW_SUPERSCRIPT_NOTE_REF_RE
        .replace_all(text, |caps: &regex::Captures| {
            let marker = caps
                .get(1)
                .or_else(|| caps.get(2))
                .or_else(|| caps.get(3))
                .or_else(|| caps.get(4))
                .map(|m| m.as_str())
                .unwrap_or("");
            let note_id = consume_marker_note_id(marker, marker_note_sequences, marker_usage_index);
            if note_id.is_empty() {
                return caps.get(0).map(|m| m.as_str().to_string()).unwrap_or_default();
            }
            let ref_num = local_endnote_ref_number(
                &note_id,
                note_kind_by_id,
                local_ref_numbers,
                ordered_note_ids,
                note_marker_by_id,
            );
            match ref_num {
                Some(n) => format!("[^{}]", n),
                None => {
                    if let Some(ref mut ids) = footnote_ids_seen {
                        if !ids.contains(&note_id) {
                            ids.push(note_id);
                        }
                    }
                    "*".to_string()
                }
            }
        })
        .to_string()
}

/// 替换 Unicode 上标（⁰¹²³⁴⁵⁶⁷⁸⁹）格式的原始引用为本地编号 `[^N]`。
/// ←→ Python `replace_raw_unicode_superscript_refs_with_local_labels`
pub fn replace_raw_unicode_superscript_refs_with_local_labels(
    text: &str,
    marker_note_sequences: &HashMap<String, Vec<String>>,
    marker_usage_index: &mut HashMap<String, usize>,
    note_kind_by_id: &HashMap<String, String>,
    local_ref_numbers: &mut HashMap<String, i64>,
    ordered_note_ids: &mut Vec<String>,
    mut footnote_ids_seen: Option<&mut Vec<String>>,
    note_marker_by_id: Option<&HashMap<String, String>>,
) -> String {
    use crate::export_constants::{unicode_superscript_to_ascii, RAW_UNICODE_SUPERSCRIPT_NOTE_REF_RE};
    RAW_UNICODE_SUPERSCRIPT_NOTE_REF_RE
        .replace_all(text, |caps: &regex::Captures| {
            let raw = caps.get(1).map(|m| m.as_str()).unwrap_or("");
            let marker: String = raw.chars().map(unicode_superscript_to_ascii).collect();
            let note_id = consume_marker_note_id(&marker, marker_note_sequences, marker_usage_index);
            if note_id.is_empty() {
                return caps.get(0).map(|m| m.as_str().to_string()).unwrap_or_default();
            }
            let ref_num = local_endnote_ref_number(
                &note_id,
                note_kind_by_id,
                local_ref_numbers,
                ordered_note_ids,
                note_marker_by_id,
            );
            match ref_num {
                Some(n) => format!("[^{}]", n),
                None => {
                    if let Some(ref mut ids) = footnote_ids_seen {
                        if !ids.contains(&note_id) {
                            ids.push(note_id);
                        }
                    }
                    "*".to_string()
                }
            }
        })
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn marker_key_digit() {
        assert_eq!(marker_key("1"), "1");
        assert_eq!(marker_key("01"), "01");
    }

    #[test]
    fn marker_key_symbol() {
        assert_eq!(marker_key("*"), "*");
        assert_eq!(marker_key("**"), "**");
    }

    #[test]
    fn marker_key_en_prefix() {
        assert_eq!(marker_key("en-5"), "5");
    }

    #[test]
    fn resolve_note_id_found() {
        let mut map = HashMap::new();
        map.insert("fn-1".into(), "text".into());
        assert_eq!(resolve_note_id("fn-1", &map), "fn-1");
    }

    #[test]
    fn resolve_note_id_not_found() {
        let map = HashMap::new();
        assert_eq!(resolve_note_id("fn-99", &map), "");
    }

    #[test]
    fn local_endnote_new() {
        let kind_map = HashMap::from([("en-1".into(), "endnote".into())]);
        let mut ref_nums = HashMap::new();
        let mut ordered = Vec::new();
        let result = local_endnote_ref_number("en-1", &kind_map, &mut ref_nums, &mut ordered, None);
        assert_eq!(result, Some(1));
    }
}
