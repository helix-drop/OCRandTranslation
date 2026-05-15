//! 把 LLM 接受的 marker 构建为 anchor override。
//! ←→ Python `_build_visual_anchor_override()`

use crate::visual_anchor_recovery::vision_client::VisionVerifyResult;
use serde_json::json;

/// 构建单个 anchor override（serde_json::Value，对应 fnm_review_overrides_v2 记录）。
///
/// Override 格式：
/// ```json
/// {"scope": "anchor", "target_id": "ch-1-p5-30", "payload": {"action": "synthetic_accept", "page_no": 5, "marker": "30", "confidence": 0.9}}
/// ```
pub fn build_anchor_override(
    chapter_id: &str,
    page_no: i64,
    marker: &str,
    confidence: f64,
) -> serde_json::Value {
    let target_id = format!("{}-p{}-{}", chapter_id, page_no, marker);
    json!({
        "scope": "anchor",
        "target_id": target_id,
        "payload": {
            "action": "synthetic_accept",
            "page_no": page_no,
            "marker": marker,
            "confidence": confidence,
            "source": "visual_anchor_recovery",
        }
    })
}

/// 批量构建 overrides（只接受已确认的候选）。
pub fn build_overrides_from_results(
    results: &[VisionVerifyResult],
    chapter_id: &str,
) -> Vec<serde_json::Value> {
    results
        .iter()
        .filter(|r| r.accepted)
        .map(|r| build_anchor_override(chapter_id, r.page_no, &r.marker, r.confidence))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_override_has_correct_scope() {
        let ov = build_anchor_override("ch-1", 5, "30", 0.9);
        assert_eq!(ov["scope"], "anchor");
        assert_eq!(ov["target_id"], "ch-1-p5-30");
        assert_eq!(ov["payload"]["action"], "synthetic_accept");
    }

    #[test]
    fn build_overrides_filters_rejected() {
        let results = vec![
            VisionVerifyResult {
                page_no: 5,
                marker: "30".into(),
                accepted: true,
                confidence: 0.9,
                reason: "found".into(),
            },
            VisionVerifyResult {
                page_no: 6,
                marker: "31".into(),
                accepted: false,
                confidence: 0.0,
                reason: "not found".into(),
            },
        ];
        let overrides = build_overrides_from_results(&results, "ch-1");
        assert_eq!(overrides.len(), 1);
        assert_eq!(overrides[0]["target_id"], "ch-1-p5-30");
    }

    #[test]
    fn empty_results_no_overrides() {
        let overrides = build_overrides_from_results(&[], "ch-1");
        assert!(overrides.is_empty());
    }
}
