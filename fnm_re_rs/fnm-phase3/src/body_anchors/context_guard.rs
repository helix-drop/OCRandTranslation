//! ←→ FNM_RE/stages/body_anchors.py:_positive_gate_bare_digit +
//!       FNM_RE/shared/anchors.py:_is_bare_digit_marker_context
//!
//! bare_digit 正向门：三层守卫 + LLM 二次验证回调。

use fnm_core::records::BodyAnchorRecord;
use fnm_core::text::char_index_to_byte_index;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::{HashMap, HashSet};

// ── 预过滤正则 ──────────────────────────────────────────────────

static BARE_DIGIT_LEFT_WORD_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"([A-Za-zàâäéèêëïîôöùûüÿçœÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇŒ]+)\s*$").unwrap());

// 结构性前缀黑名单（只排除必定为噪声的候选）
static BARE_DIGIT_STRUCTURAL_PREFIX: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    let mut s = HashSet::new();
    s.insert("p");
    s.insert("pp");
    s.insert("vol");
    s.insert("fig");
    s.insert("no");
    s.insert("n");
    s.insert("chap");
    s.insert("chapter");
    s.insert("section");
    s.insert("sect");
    s.insert("page");
    s.insert("pages");
    s.insert("line");
    s.insert("lines");
    s.insert("note");
    s.insert("notes");
    s.insert("part");
    s.insert("thesis");
    s.insert("problem");
    s.insert("table");
    s.insert("tableau");
    s.insert("article");
    s.insert("act");
    s.insert("scene");
    s
});

static BARE_DIGIT_VALID_SENTENCE_END: Lazy<HashSet<char>> = Lazy::new(|| {
    let mut s = HashSet::new();
    s.insert('.');
    s.insert(';');
    s.insert(':');
    s.insert('!');
    s.insert('?');
    s.insert(',');
    s.insert('—');
    s.insert('–');
    s.insert('-');
    s
});

// ── 预过滤：_is_bare_digit_marker_context ──────────────────────

/// 段落级廉价预过滤——只排除必定为噪声的候选。
///
/// ←→ Python `FNM_RE/shared/anchors.py:_is_bare_digit_marker_context`
///
/// 守卫 1：左侧必须有 >=3 字符的词（排除 "p 5"、"de 68"）。
/// 守卫 2：左侧词是结构性前缀（"thesis"、"page"、"chapter"）-> 拒绝。
/// 守卫 3：右侧标点后紧跟数字 -> 列表/日期/千分位 -> 拒绝。
pub fn is_bare_digit_marker_context(content: &str, digit_start: usize, digit_end: usize) -> bool {
    // 防御：digit_start/digit_end 越界或非字符边界时 graceful 返回 ""（不 panic）。
    // 当前唯一调用方（pattern_scan）传 regex 字节位置，正常路径与原切片等价。
    let left = content.get(..digit_start).unwrap_or("").trim_end();
    if let Some(word_caps) = BARE_DIGIT_LEFT_WORD_RE.captures(left) {
        let word = word_caps.get(1).unwrap().as_str().to_lowercase();
        if word.len() < 3 {
            return false;
        }
        if BARE_DIGIT_STRUCTURAL_PREFIX.contains(word.as_str()) {
            return false;
        }
    } else {
        return false;
    }

    let right = content.get(digit_end..).unwrap_or("").trim_start();
    let punctuation: &str = ",.;:)]}»\"\u{201D}\u{2019}";
    for c in right.chars() {
        if punctuation.contains(c) {
            continue;
        }
        if c.is_ascii_digit() {
            return false;
        }
        break;
    }

    true
}

// ── 正向门：_positive_gate_bare_digit ───────────────────────────

/// bare_digit 正向证据 gate。
///
/// ←→ Python `FNM_RE/stages/body_anchors.py:_positive_gate_bare_digit`
///
/// 返回：(通过的 anchors, LLM 验证通过的 anchors)
pub fn positive_gate_bare_digit(
    anchors: &[BodyAnchorRecord],
    chapter_note_items: &HashMap<String, HashSet<i64>>,
) -> (Vec<BodyAnchorRecord>, Vec<BodyAnchorRecord>) {
    let mut non_bare: Vec<BodyAnchorRecord> = Vec::new();
    let mut bare_candidates: Vec<&BodyAnchorRecord> = Vec::new();

    for anchor in anchors {
        if anchor.source.ends_with(":bare_digit") {
            bare_candidates.push(anchor);
        } else {
            non_bare.push(anchor.clone());
        }
    }

    if bare_candidates.is_empty() {
        return (anchors.to_vec(), Vec::new());
    }

    // 每章已由非 bare_digit anchor 覆盖的 marker
    let mut covered_by_chapter: HashMap<String, HashSet<i64>> = HashMap::new();
    for anchor in &non_bare {
        if let Ok(val) = anchor.normalized_marker.parse::<i64>() {
            covered_by_chapter
                .entry(anchor.chapter_id.clone())
                .or_default()
                .insert(val);
        }
    }

    // 每章 bare_digit 候选的 marker 计数
    let mut bare_count_by_chapter: HashMap<String, HashMap<i64, usize>> = HashMap::new();
    for anchor in &bare_candidates {
        if let Ok(val) = anchor.normalized_marker.parse::<i64>() {
            *bare_count_by_chapter
                .entry(anchor.chapter_id.clone())
                .or_default()
                .entry(val)
                .or_insert(0) += 1;
        }
    }

    let mut accepted_bare: Vec<BodyAnchorRecord> = Vec::new();
    let mut llm_candidates: Vec<BodyAnchorRecord> = Vec::new();

    for anchor in bare_candidates {
        let chapter_id = &anchor.chapter_id;
        let Ok(marker_val) = anchor.normalized_marker.parse::<i64>() else {
            continue;
        };

        // 条件 1：marker 必须在 chapter_note_items 集合中
        let note_items_set = match chapter_note_items.get(chapter_id) {
            Some(s) => s,
            None => continue,
        };
        if !note_items_set.contains(&marker_val) {
            continue;
        }

        // 条件 2：不能已由非 bare 的同名 marker 覆盖
        if covered_by_chapter
            .get(chapter_id)
            .map(|s| s.contains(&marker_val))
            .unwrap_or(false)
        {
            continue;
        }

        // 条件 3：同一 marker 出现 >2 次 -> 送 LLM
        let count = bare_count_by_chapter
            .get(chapter_id)
            .and_then(|m| m.get(&marker_val))
            .copied()
            .unwrap_or(0);
        if count > 2 {
            llm_candidates.push((*anchor).clone());
            continue;
        }

        // 条件 4：false positive 上下文 -> 送 LLM
        if is_bare_digit_false_positive_context(anchor) {
            llm_candidates.push((*anchor).clone());
            continue;
        }

        accepted_bare.push((*anchor).clone());
    }

    // 注：LLM 验证回调由上层注入（bare_digit_verifier），此处只收集候选。
    // 返回的第二个 vec 是 "需要 LLM 验证的候选"，由调用方决定是否送 LLM。
    let mut result = non_bare;
    result.extend(accepted_bare);
    (result, llm_candidates)
}

// ── false positive 上下文判断 ───────────────────────────────────

/// ←→ Python `FNM_RE/stages/body_anchors.py:_is_bare_digit_false_positive_context`
pub fn is_bare_digit_false_positive_context(anchor: &BodyAnchorRecord) -> bool {
    let source_text = anchor.source_text.trim();
    if source_text.is_empty() {
        return false;
    }
    let char_end = anchor.char_end as usize;
    if char_end >= source_text.chars().count() {
        return false;
    }
    let Some(byte_end) = char_index_to_byte_index(source_text, char_end) else {
        return false;
    };
    let remainder = &source_text[byte_end..];
    if remainder.trim().is_empty() {
        return false;
    }
    let next_char = remainder.trim_start().chars().next().unwrap_or('\0');
    !BARE_DIGIT_VALID_SENTENCE_END.contains(&next_char)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 加固守卫：越界 / 非字符边界索引不再 panic（加固前 `content[..i]` 会 panic）。
    #[test]
    fn bare_digit_context_tolerates_bad_indices() {
        let content = "见 thesis 中文 5"; // 含多字节字符（"见" = 3 字节）
        let n = content.len();
        // 各种异常索引都不应 panic（仅验证不崩溃，返回值不重要）：
        let _ = is_bare_digit_marker_context(content, n + 5, n + 10); // 双越界
        let _ = is_bare_digit_marker_context(content, 1, 2); // 非字符边界（"见"内部）
        let _ = is_bare_digit_marker_context(content, 0, n); // 边界值
    }
}
