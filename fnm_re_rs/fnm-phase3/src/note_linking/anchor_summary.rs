//! ←→ Python `note_linking.py:_refresh_anchor_summary`

use fnm_core::records::BodyAnchorRecord;
use std::collections::HashMap;

/// Anchor 统计摘要。
#[derive(Debug, Clone, Default)]
pub struct AnchorSummary {
    pub total_count: usize,
    pub explicit_count: usize,
    pub synthetic_count: usize,
    pub kind_counts: HashMap<String, usize>,
    pub uncertain_count: usize,
    pub ocr_repaired_count: usize,
}

/// 刷新 anchor 统计摘要。
///
/// ←→ Python `_refresh_anchor_summary`
pub fn refresh_anchor_summary(anchors: &[BodyAnchorRecord]) -> AnchorSummary {
    let total_count = anchors.len();
    let synthetic_count = anchors.iter().filter(|a| a.synthetic).count();
    let explicit_count = total_count - synthetic_count;

    let mut kind_counts: HashMap<String, usize> = HashMap::new();
    for a in anchors {
        *kind_counts
            .entry(a.anchor_kind.as_str().to_string())
            .or_insert(0) += 1;
    }

    let uncertain_count = anchors
        .iter()
        .filter(|a| a.anchor_kind.as_str() == "unknown" || a.certainty < 1.0)
        .count();

    let ocr_repaired_count = anchors
        .iter()
        .filter(|a| !a.ocr_repaired_from_marker.is_empty())
        .count();

    AnchorSummary {
        total_count,
        explicit_count,
        synthetic_count,
        kind_counts,
        uncertain_count,
        ocr_repaired_count,
    }
}

/// 将 base summary（BodyAnchorSummary 转 Value）与 refresh-computed 字段合并。
///
/// ←→ Python `_refresh_anchor_summary`: `{**dict(base_summary or {}), "total_count": ..., ...}`
///
/// base 中非 computed 的字段（如 `year_like_filtered_count`）保留不变，
/// computed 的 6 个字段覆盖 base 中的同名值（若存在）。
pub fn merge_with_base(
    computed: &AnchorSummary,
    base: Option<serde_json::Value>,
) -> serde_json::Value {
    let mut merged = base.unwrap_or(serde_json::Value::Null);
    if !merged.is_object() {
        merged = serde_json::json!({});
    }
    if let Some(ref mut map) = merged.as_object_mut() {
        map.insert(
            "total_count".to_string(),
            serde_json::Value::Number(computed.total_count.into()),
        );
        map.insert(
            "explicit_count".to_string(),
            serde_json::Value::Number(computed.explicit_count.into()),
        );
        map.insert(
            "synthetic_count".to_string(),
            serde_json::Value::Number(computed.synthetic_count.into()),
        );
        map.insert(
            "kind_counts".to_string(),
            serde_json::json!(computed.kind_counts),
        );
        map.insert(
            "uncertain_count".to_string(),
            serde_json::Value::Number(computed.uncertain_count.into()),
        );
        map.insert(
            "ocr_repaired_count".to_string(),
            serde_json::Value::Number(computed.ocr_repaired_count.into()),
        );
    }
    merged
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::AnchorKind;

    #[test]
    fn test_refresh_anchor_summary() {
        let anchors = vec![
            BodyAnchorRecord {
                anchor_kind: AnchorKind::Footnote,
                synthetic: false,
                certainty: 1.0,
                ocr_repaired_from_marker: String::new(),
                ..Default::default()
            },
            BodyAnchorRecord {
                anchor_kind: AnchorKind::Unknown,
                synthetic: true,
                certainty: 0.4,
                ocr_repaired_from_marker: "12".to_string(),
                ..Default::default()
            },
        ];

        let summary = refresh_anchor_summary(&anchors);
        assert_eq!(summary.total_count, 2);
        assert_eq!(summary.explicit_count, 1);
        assert_eq!(summary.synthetic_count, 1);
        assert_eq!(summary.uncertain_count, 1);
        assert_eq!(summary.ocr_repaired_count, 1);
        assert_eq!(summary.kind_counts.get("footnote").copied().unwrap_or(0), 1);
        assert_eq!(summary.kind_counts.get("unknown").copied().unwrap_or(0), 1);
    }
}
