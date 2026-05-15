//! bare digit 验证结果解析。
//! ←→ FNM_RE/modules/llm_bare_digit_verify.py 中的过滤逻辑

use crate::llm_bare_digit_verify::llm_client::BareDigitVerifyResult;

/// 从全量验证结果中分出接受和拒绝的候选。
pub struct VerifiedResults {
    pub accepted: Vec<BareDigitVerifyResult>,
    pub rejected: Vec<BareDigitVerifyResult>,
}

/// 按阈值分流验证结果。
///
/// 接受条件：is_superscript == true && confidence >= min_confidence
pub fn split_results(results: Vec<BareDigitVerifyResult>, min_confidence: f64) -> VerifiedResults {
    let mut accepted = Vec::new();
    let mut rejected = Vec::new();

    for r in results {
        if r.is_superscript && r.confidence >= min_confidence {
            accepted.push(r);
        } else {
            rejected.push(r);
        }
    }

    VerifiedResults { accepted, rejected }
}

/// 汇总统计。
pub fn build_result_summary(results: &VerifiedResults) -> serde_json::Value {
    serde_json::json!({
        "total_verified": results.accepted.len() + results.rejected.len(),
        "accepted": results.accepted.len(),
        "rejected": results.rejected.len(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_result(is_sup: bool, conf: f64) -> BareDigitVerifyResult {
        BareDigitVerifyResult {
            anchor_id: "test".into(),
            page_no: 1,
            marker: "1".into(),
            is_superscript: is_sup,
            confidence: conf,
        }
    }

    #[test]
    fn high_confidence_accepted() {
        let results = vec![make_result(true, 0.9)];
        let split = split_results(results, 0.5);
        assert_eq!(split.accepted.len(), 1);
        assert!(split.rejected.is_empty());
    }

    #[test]
    fn low_confidence_rejected() {
        let results = vec![make_result(true, 0.3)];
        let split = split_results(results, 0.5);
        assert!(split.accepted.is_empty());
        assert_eq!(split.rejected.len(), 1);
    }

    #[test]
    fn false_superscript_rejected() {
        let results = vec![make_result(false, 0.9)];
        let split = split_results(results, 0.5);
        assert!(split.accepted.is_empty());
        assert_eq!(split.rejected.len(), 1);
    }

    #[test]
    fn summary_counts() {
        let results = vec![make_result(true, 0.9), make_result(false, 0.9)];
        let split = split_results(results, 0.5);
        let summary = build_result_summary(&split);
        assert_eq!(summary["total_verified"], 2);
        assert_eq!(summary["accepted"], 1);
        assert_eq!(summary["rejected"], 1);
    }
}
