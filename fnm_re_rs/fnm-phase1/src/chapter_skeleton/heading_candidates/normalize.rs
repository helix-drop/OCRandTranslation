//! ←→ heading_candidates.py: _is_sentence_like_heading / _normalize_heading_candidates
//!
//! Candidate 归一化与句子类似判定。

use fnm_core::records::HeadingCandidate;
use fnm_core::title::normalize_title;

/// 判断标题是否像句子（用于 reject 启发式）。
/// ←→ Python `_is_sentence_like_heading`
pub fn is_sentence_like_heading(title: &str) -> bool {
    let text = normalize_title(title);
    let words: Vec<&str> = text.split_whitespace().filter(|w| !w.is_empty()).collect();
    if words.len() < 8 {
        return false;
    }
    if text.contains(';')
        || text.contains('.')
        || text.contains(':')
        || text.contains('?')
        || text.contains('!')
    {
        return true;
    }
    let lower_words = words
        .iter()
        .filter(|w| w.starts_with(|c: char| c.is_lowercase()))
        .count();
    lower_words >= std::cmp::max(3, words.len() / 2)
}

/// 规范化 heading candidates：排序 + heading_id 分配。
/// 与 Python `_normalize_heading_candidates` 一致。
pub fn normalize_heading_candidates(
    mut candidates: Vec<HeadingCandidate>,
) -> Vec<HeadingCandidate> {
    candidates.sort_by(|a, b| {
        a.page_no
            .cmp(&b.page_no)
            .then_with(|| a.source.cmp(&b.source))
            .then_with(|| a.text.cmp(&b.text))
    });
    for (i, c) in candidates.iter_mut().enumerate() {
        if c.heading_id.is_empty() {
            c.heading_id = format!("hd-{:05}", i + 1);
        }
    }
    candidates
}

/// 从 `HeadingCandidate` 列表构建 page_no → 角色映射。
pub fn role_by_no(candidates: &[HeadingCandidate]) -> std::collections::HashMap<i64, String> {
    let mut map: std::collections::HashMap<i64, String> = std::collections::HashMap::new();
    for c in candidates {
        if !c.heading_family_guess.is_empty() {
            map.entry(c.page_no)
                .or_insert_with(|| c.heading_family_guess.clone());
        }
    }
    map
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sentence_like_short() {
        assert!(!is_sentence_like_heading("Chapter 1"));
    }

    #[test]
    fn sentence_like_long_with_period() {
        assert!(is_sentence_like_heading(
            "This is a very long heading that contains a period. And more"
        ));
    }

    #[test]
    fn sentence_like_many_lower_words() {
        assert!(is_sentence_like_heading(
            "the quick brown fox jumps over the lazy dog near the river"
        ));
    }

    #[test]
    fn normalize_empty() {
        let result = normalize_heading_candidates(vec![]);
        assert!(result.is_empty());
    }

    #[test]
    fn normalize_sorts_and_assigns_ids() {
        let c2 = HeadingCandidate {
            page_no: 2,
            source: "ocr_block".into(),
            text: "Chapter 2".into(),
            ..Default::default()
        };
        let c1 = HeadingCandidate {
            page_no: 1,
            source: "ocr_block".into(),
            text: "Chapter 1".into(),
            ..Default::default()
        };
        let result = normalize_heading_candidates(vec![c2, c1]);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].page_no, 1);
        assert_eq!(result[0].heading_id, "hd-00001");
        assert_eq!(result[1].heading_id, "hd-00002");
    }

    #[test]
    fn normalize_preserves_existing_id() {
        let c = HeadingCandidate {
            heading_id: "custom-001".into(),
            page_no: 1,
            source: "ocr_block".into(),
            text: "Chapter 1".into(),
            ..Default::default()
        };
        let result = normalize_heading_candidates(vec![c]);
        assert_eq!(result[0].heading_id, "custom-001");
    }
}
