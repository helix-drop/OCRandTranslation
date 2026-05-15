//! 检测每章 marker 缺口：已知 markers 集合 - 已找到的 anchors 集合。
//! ←→ Python `_detect_chapter_marker_gaps()`

use fnm_core::records::BodyAnchorRecord;
use std::collections::HashSet;

/// 一个候选缺口：某章的某个 marker 在 body 中未找到对应 anchor。
#[derive(Debug, Clone)]
pub struct GapCandidate {
    pub chapter_id: String,
    pub marker: String,
    pub expected_page_range: (i64, i64),
    pub context_pages: Vec<i64>,
}

/// 检测每章 marker 缺口。
pub fn detect_chapter_marker_gaps(
    chapter_id: &str,
    expected_markers: &HashSet<String>,
    found_anchors: &[BodyAnchorRecord],
    chapter_start_page: i64,
    chapter_end_page: i64,
) -> Vec<GapCandidate> {
    let found: HashSet<&str> = found_anchors
        .iter()
        .map(|a| a.normalized_marker.as_str())
        .collect();

    let mut gaps: Vec<GapCandidate> = Vec::new();

    for marker in expected_markers {
        if !found.contains(marker.as_str()) {
            let context_pages: Vec<i64> = {
                let mut p: Vec<i64> = found_anchors
                    .iter()
                    .filter(|a| a.normalized_marker == *marker)
                    .map(|a| a.page_no)
                    .collect();
                p.sort();
                p.dedup();
                p
            };

            gaps.push(GapCandidate {
                chapter_id: chapter_id.into(),
                marker: marker.clone(),
                expected_page_range: (chapter_start_page, chapter_end_page),
                context_pages,
            });
        }
    }

    gaps
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::AnchorKind;

    fn make_anchor(marker: &str, page: i64) -> BodyAnchorRecord {
        BodyAnchorRecord {
            anchor_id: format!("a-{}", marker),
            chapter_id: "ch-1".into(),
            page_no: page,
            paragraph_index: 1,
            char_start: 0,
            char_end: 1,
            source_marker: marker.into(),
            normalized_marker: marker.into(),
            anchor_kind: AnchorKind::Footnote,
            certainty: 1.0,
            source_text: String::new(),
            source: "test".into(),
            synthetic: false,
            ocr_repaired_from_marker: String::new(),
        }
    }

    #[test]
    fn no_gaps_when_all_found() {
        let expected: HashSet<String> = ["1", "2", "3"].into_iter().map(String::from).collect();
        let anchors = vec![
            make_anchor("1", 10),
            make_anchor("2", 10),
            make_anchor("3", 11),
        ];
        let gaps = detect_chapter_marker_gaps("ch-1", &expected, &anchors, 1, 20);
        assert!(gaps.is_empty());
    }

    #[test]
    fn detects_missing_marker() {
        let expected: HashSet<String> = ["1", "2", "3"].into_iter().map(String::from).collect();
        let anchors = vec![make_anchor("1", 10)];
        let gaps = detect_chapter_marker_gaps("ch-1", &expected, &anchors, 1, 20);
        assert_eq!(gaps.len(), 2);
        assert!(gaps.iter().any(|g| g.marker == "2"));
        assert!(gaps.iter().any(|g| g.marker == "3"));
    }

    #[test]
    fn empty_expected_no_gaps() {
        let expected: HashSet<String> = HashSet::new();
        let gaps = detect_chapter_marker_gaps("ch-1", &expected, &[], 1, 20);
        assert!(gaps.is_empty());
    }
}
