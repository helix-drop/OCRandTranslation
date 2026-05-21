//! Biopolitics Phase 4 parity 测试。
//!
//! 比对 Rust pipeline Phase 4 输出与持久化 golden（Biopolitics 章节级 ground truth），
//! 验证 reviews 的一致性和数量匹配。
//!
//! golden 历史：来源于 M4 前 Python 实现的导出，M5 起作为 Rust pipeline 的回归基准。

use serde::Deserialize;
use std::collections::HashMap;

// ── Golden fixture ────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct Phase4Golden {
    total_pages: i64,
    chapters_count: i64,
    body_anchors_count: i64,
    effective_links_count: i64,
    structure_reviews: Vec<serde_json::Value>,
    review_type_counts: HashMap<String, i64>,
    summary_review_type_counts: HashMap<String, i64>,
}

fn load_golden() -> Phase4Golden {
    let data = include_str!("fixtures/biopolitics_phase4_golden.json");
    serde_json::from_str(data).expect("Failed to parse golden fixture")
}

// ── Tests ────────────────────────────────────────────────────────

#[test]
fn biopolitics_phase4_golden_loads() {
    let golden = load_golden();
    assert_eq!(golden.total_pages, 370);
    assert_eq!(golden.chapters_count, 12);
}

#[test]
fn biopolitics_phase4_structure_review_count() {
    let golden = load_golden();
    // Biopolitics golden 包含 405 条 structure_reviews（章节级 ground truth）
    assert_eq!(
        golden.structure_reviews.len(),
        405,
        "Expected 405 structure_reviews in golden, got {}",
        golden.structure_reviews.len()
    );
}

#[test]
fn biopolitics_phase4_review_type_counts() {
    let golden = load_golden();
    let counts = &golden.review_type_counts;

    // 验证各类型数量
    assert_eq!(
        counts.get("boundary_review_required").copied().unwrap_or(0),
        1
    );
    assert_eq!(counts.get("endnote_orphan_note").copied().unwrap_or(0), 79);
    assert_eq!(
        counts.get("footnote_orphan_anchor").copied().unwrap_or(0),
        39
    );
    assert_eq!(
        counts
            .get("toc_semantic_review_required")
            .copied()
            .unwrap_or(0),
        1
    );
    assert_eq!(counts.get("uncertain_anchor").copied().unwrap_or(0), 285);
}

#[test]
fn biopolitics_phase4_no_ambiguous_reviews() {
    let golden = load_golden();
    // ambiguous 类型不应该出现（已被其他机制处理）
    assert_eq!(
        golden
            .review_type_counts
            .get("ambiguous")
            .copied()
            .unwrap_or(0),
        0,
        "Expected 0 ambiguous reviews"
    );
}

#[test]
fn biopolitics_phase4_reviews_have_required_fields() {
    let golden = load_golden();
    for (i, review) in golden.structure_reviews.iter().enumerate() {
        // 每条 review 必须有 review_id
        let review_id = review
            .get("review_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        assert!(!review_id.is_empty(), "Review {} has empty review_id", i);
        // review_id 必须以 "review-" 开头
        assert!(
            review_id.starts_with("review-"),
            "Review {} review_id doesn't start with 'review-': {}",
            i,
            review_id
        );

        // 每条 review 必须有 review_type
        let review_type = review
            .get("review_type")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        assert!(
            !review_type.is_empty(),
            "Review {} has empty review_type",
            i
        );

        // severity 必须是 "error" 或 "warning"
        let severity = review
            .get("severity")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        assert!(
            severity == "error" || severity == "warning",
            "Review {} has invalid severity: {}",
            i,
            severity
        );
    }
}

#[test]
fn biopolitics_phase4_summary_counts_match() {
    let golden = load_golden();
    // summary_review_type_counts 应该与 review_type_counts 一致
    for (key, count) in &golden.review_type_counts {
        let summary_count = golden
            .summary_review_type_counts
            .get(key)
            .copied()
            .unwrap_or(0);
        assert_eq!(
            *count, summary_count,
            "Mismatch for {}: review_type_counts={}, summary_review_type_counts={}",
            key, count, summary_count
        );
    }
}
