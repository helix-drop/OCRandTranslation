//! ←→ Python `FNM_RE/modules/llm_repair.py::locate_anchor_phrase_in_body`（行 418-468）。
//!
//! Tier 1 fuzzy anchor synthesis：当正文里找不到结构化 anchor 时，让 LLM 给出正文里的
//! 唯一短语片段，再用 rapidfuzz partial_ratio 在本章正文里模糊定位，落地为一个真实坐标的 anchor。
//!
//! # 与 Python 对齐
//!
//! Python 用 `rapidfuzz.fuzz.partial_ratio_alignment`：给定 needle 和 haystack，
//! 返回 (score, src_start, src_end, dest_start, dest_end)。
//!
//! Rust 端 rapidfuzz 0.5.0 不暴露 partial_ratio_alignment，
//! 这里基于 `rapidfuzz::distance::indel::normalized_similarity`（与 Python 的 ratio 同算法）
//! 实现等价 sliding-window partial_ratio。

use rapidfuzz::distance::indel;
use serde::{Deserialize, Serialize};

use crate::constants::{FUZZY_AMBIGUITY_MARGIN, FUZZY_SCORE_THRESHOLD};

/// ←→ Python `locate_anchor_phrase_in_body` 返回的 dict 字段
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FuzzyHit {
    pub hit: bool,
    pub score: f64,
    pub char_start: i64,
    pub char_end: i64,
    pub matched_text: String,
    pub ambiguous: bool,
}

impl FuzzyHit {
    fn empty() -> Self {
        FuzzyHit {
            hit: false,
            score: 0.0,
            char_start: -1,
            char_end: -1,
            matched_text: String::new(),
            ambiguous: false,
        }
    }
}

/// ←→ Python `locate_anchor_phrase_in_body` (llm_repair.py:418-468)
///
/// 在正文里用 rapidfuzz partial_ratio 模糊定位 anchor 短语。
///
/// 字段语义与 Python 一致：
/// - `hit`：是否达到 `FUZZY_SCORE_THRESHOLD`
/// - `score`：partial_ratio 分数（0-100）
/// - `char_start / char_end`：命中区间在 body 内的**字符**偏移（不是 byte）
/// - `matched_text`：body[char_start..char_end]
/// - `ambiguous`：把主命中替换为空格后再扫一次，若次命中 ≥ max(threshold, primary - margin) 则歧义
pub fn locate_anchor_phrase_in_body(body_text: &str, phrase: &str) -> FuzzyHit {
    let needle = phrase.trim();
    if body_text.is_empty() || needle.is_empty() {
        return FuzzyHit::empty();
    }
    let body_chars: Vec<char> = body_text.chars().collect();
    if body_chars.is_empty() {
        return FuzzyHit::empty();
    }

    let Some(primary) = partial_ratio_alignment(needle, &body_chars) else {
        return FuzzyHit::empty();
    };
    let matched_text: String = body_chars[primary.dest_start..primary.dest_end]
        .iter()
        .collect();

    let mut ambiguous = false;
    if primary.score >= FUZZY_SCORE_THRESHOLD {
        let mut masked = body_chars.clone();
        for c in masked
            .iter_mut()
            .take(primary.dest_end)
            .skip(primary.dest_start)
        {
            *c = ' ';
        }
        if let Some(secondary) = partial_ratio_alignment(needle, &masked) {
            let threshold = FUZZY_SCORE_THRESHOLD.max(primary.score - FUZZY_AMBIGUITY_MARGIN);
            if secondary.score >= threshold {
                ambiguous = true;
            }
        }
    }

    FuzzyHit {
        hit: primary.score >= FUZZY_SCORE_THRESHOLD,
        score: primary.score,
        char_start: primary.dest_start as i64,
        char_end: primary.dest_end as i64,
        matched_text,
        ambiguous,
    }
}

struct PartialAlignment {
    score: f64,
    dest_start: usize,
    dest_end: usize,
}

/// ←→ Python `rapidfuzz.fuzz.partial_ratio_alignment` 的等价实现。
///
/// 算法（与 Python rapidfuzz 一致）：
/// 1. needle = phrase（chars），haystack = body（chars）
/// 2. 若 needle 比 haystack 长，无法滑动，直接对全串计算 indel similarity
/// 3. 否则在 haystack 上滑动长度为 `len(needle)` 的窗口（步长 1），
///    对每个窗口计算 normalized_similarity（与 Python ratio 同算法），
///    返回最高分窗口
///
/// 注：Python rapidfuzz 用 LCSseq 优化扫描跳步；此简化版用线性扫描，
/// 对 FNM_RE 场景下 needle ≤ 12 词、body ≤ 章节长度（典型 < 50KB），
/// 复杂度可接受（< 10ms / 章）。
fn partial_ratio_alignment(needle: &str, haystack: &[char]) -> Option<PartialAlignment> {
    let needle_chars: Vec<char> = needle.chars().collect();
    if needle_chars.is_empty() || haystack.is_empty() {
        return None;
    }
    if needle_chars.len() >= haystack.len() {
        let score =
            indel::normalized_similarity(needle_chars.iter().copied(), haystack.iter().copied())
                * 100.0;
        return Some(PartialAlignment {
            score,
            dest_start: 0,
            dest_end: haystack.len(),
        });
    }

    let window_len = needle_chars.len();
    let mut best = PartialAlignment {
        score: 0.0,
        dest_start: 0,
        dest_end: window_len,
    };
    let last_start = haystack.len() - window_len;
    for start in 0..=last_start {
        let end = start + window_len;
        let window = &haystack[start..end];
        let score =
            indel::normalized_similarity(needle_chars.iter().copied(), window.iter().copied())
                * 100.0;
        if score > best.score {
            best = PartialAlignment {
                score,
                dest_start: start,
                dest_end: end,
            };
            if score >= 100.0 {
                break;
            }
        }
    }
    Some(best)
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_body_or_phrase() {
        let hit = locate_anchor_phrase_in_body("", "phrase");
        assert!(!hit.hit);
        assert_eq!(hit.char_start, -1);

        let hit = locate_anchor_phrase_in_body("body text", "   ");
        assert!(!hit.hit);
    }

    #[test]
    fn test_exact_match() {
        let body = "the quick brown fox jumps over the lazy dog";
        let hit = locate_anchor_phrase_in_body(body, "brown fox jumps");
        assert!(hit.hit);
        assert_eq!(hit.score, 100.0);
        assert_eq!(hit.matched_text, "brown fox jumps");
        assert_eq!(hit.char_start, 10);
        assert_eq!(hit.char_end, 25);
    }

    #[test]
    fn test_near_match_above_threshold() {
        let body = "the quick brown fox jumps over the lazy dog";
        // 1 char insertion 仍 > 88
        let hit = locate_anchor_phrase_in_body(body, "brown fxx jumps");
        assert!(hit.hit);
        assert!(hit.score >= FUZZY_SCORE_THRESHOLD);
        assert!(hit.score < 100.0);
    }

    #[test]
    fn test_no_match_below_threshold() {
        let body = "the quick brown fox jumps over the lazy dog";
        let hit = locate_anchor_phrase_in_body(body, "xyzzy plover");
        assert!(!hit.hit);
        assert!(hit.score < FUZZY_SCORE_THRESHOLD);
    }

    #[test]
    fn test_ambiguous_two_matches() {
        // 同一短语出现 2 次
        let body = "foo bar baz qux foo bar baz qux end";
        let hit = locate_anchor_phrase_in_body(body, "foo bar baz");
        assert!(hit.hit);
        assert!(hit.ambiguous, "expected ambiguous for duplicated phrase");
    }

    #[test]
    fn test_unambiguous_single_match() {
        let body = "alpha beta gamma delta epsilon zeta eta theta";
        let hit = locate_anchor_phrase_in_body(body, "delta epsilon zeta");
        assert!(hit.hit);
        assert!(!hit.ambiguous);
    }

    #[test]
    fn test_char_offsets_are_char_not_byte() {
        let body = "中文上下文 brown fox jumps 后面";
        let hit = locate_anchor_phrase_in_body(body, "brown fox jumps");
        assert!(hit.hit);
        assert_eq!(hit.matched_text, "brown fox jumps");
        // char_start 应该是字符索引 6（"中文上下文 " 5 字符 + 1 空格），不是 byte
        assert_eq!(hit.char_start, 6);
    }
}
