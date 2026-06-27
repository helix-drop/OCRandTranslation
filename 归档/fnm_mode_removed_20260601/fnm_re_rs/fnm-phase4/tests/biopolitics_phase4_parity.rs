//! Biopolitics Phase 4 parity 测试。
//!
//! 比对 Rust pipeline Phase 4 输出与持久化 golden（Biopolitics 章节级 ground truth），
//! 验证 reviews 的一致性和数量匹配。
//!
//! golden 历史：来源于 M4 前 Python 实现的导出，M5 起作为 Rust pipeline 的回归基准。

use serde::Deserialize;
use std::collections::HashMap;

use fnm_core::records::*;
use fnm_core::refs;
use fnm_core::types::*;
use fnm_phase4::reviews::build_structure_reviews;
use fnm_phase4::units::build_translation_units;

// ── Golden fixture ────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct Phase4Golden {
    total_pages: i64,
    chapters_count: i64,
    #[allow(dead_code)]
    body_anchors_count: i64,
    #[allow(dead_code)]
    effective_links_count: i64,
    structure_reviews: Vec<serde_json::Value>,
    review_type_counts: HashMap<String, i64>,
    summary_review_type_counts: HashMap<String, i64>,
}

fn load_golden() -> Phase4Golden {
    let data = include_str!("fixtures/biopolitics_phase4_golden.json");
    serde_json::from_str(data).expect("Failed to parse golden fixture")
}

fn make_chapter(
    chapter_id: &str,
    title: &str,
    start: i64,
    end: i64,
    boundary: BoundaryState,
) -> ChapterRecord {
    ChapterRecord {
        chapter_id: chapter_id.to_string(),
        title: title.to_string(),
        start_page: start,
        end_page: end,
        pages: (start..=end).collect(),
        boundary_state: boundary,
        source: ChapterSource::Fallback,
    }
}

// ── Golden contract tests ────────────────────────────────────────

#[test]
fn biopolitics_phase4_golden_loads() {
    let golden = load_golden();
    assert_eq!(golden.total_pages, 370);
    assert_eq!(golden.chapters_count, 12);
}

#[test]
fn biopolitics_phase4_structure_review_count() {
    let golden = load_golden();
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
        let review_id = review
            .get("review_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        assert!(!review_id.is_empty(), "Review {} has empty review_id", i);
        assert!(
            review_id.starts_with("review-"),
            "Review {} review_id doesn't start with 'review-': {}",
            i,
            review_id
        );
        let review_type = review
            .get("review_type")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        assert!(
            !review_type.is_empty(),
            "Review {} has empty review_type",
            i
        );
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

// ── Real Phase4 输出测试 ──────────────────────────────────────────
//
// 运行 build_translation_units / build_structure_reviews 的完整 Rust 实现，
// 验证对真实数据的输出结构。

#[test]
fn biopolitics_phase4_real_translation_units() {
    // 构造 Biopolitics 式的 frozen units（12 章 body + note units）
    let mut body_units: Vec<FrozenUnit> = Vec::new();
    for i in 1..=12 {
        body_units.push(FrozenUnit {
            unit_id: format!("body-ch{:02}-0001", i),
            kind: "body".into(),
            owner_kind: "chapter".into(),
            owner_id: format!("ch{:02}", i),
            section_id: format!("ch{:02}", i),
            section_title: format!("Chapter {}", i),
            section_start_page: (i - 1) * 30 + 1,
            section_end_page: i * 30,
            page_start: (i - 1) * 30 + 1,
            page_end: i * 30,
            char_count: 200,
            source_text: format!(
                "Chapter {} body text with {} ref.",
                i,
                refs::frozen_note_ref(&format!("ref{}", i))
            ),
            ..Default::default()
        });
    }

    let note_units: Vec<FrozenUnit> = vec![
        FrozenUnit {
            unit_id: "footnote-ch01-f001".into(),
            kind: "footnote".into(),
            note_id: "f001".into(),
            owner_id: "r1".into(),
            owner_kind: "note_region".into(),
            section_id: "ch01".into(),
            source_text: "A footnote.".into(),
            page_start: 5,
            page_end: 5,
            target_ref: "{{NOTE_REF:f001}}".into(),
            ..Default::default()
        },
        FrozenUnit {
            unit_id: "endnote-ch01-e001".into(),
            kind: "endnote".into(),
            note_id: "e001".into(),
            owner_id: "r2".into(),
            owner_kind: "note_region".into(),
            section_id: "ch01".into(),
            source_text: "An endnote.".into(),
            page_start: 30,
            page_end: 30,
            target_ref: "{{NOTE_REF:e001}}".into(),
            ..Default::default()
        },
    ];

    let frozen_units = FrozenUnits {
        body_units,
        note_units,
        ..Default::default()
    };

    let (units, summary) = build_translation_units(&frozen_units);

    // 12 body + 2 note = 14 total
    assert_eq!(units.len(), 14);
    let body_count = units.iter().filter(|u| u.kind == "body").count();
    let note_count = units.iter().filter(|u| u.kind != "body").count();
    assert_eq!(body_count, 12);
    assert_eq!(note_count, 2);

    // NOTE_REF token 未修改（body unit 的 source_text 含 token，note unit 在 target_ref）
    assert!(units[0].source_text.contains("{{NOTE_REF:ref1}}"));
    let body_with_token: Vec<_> = units
        .iter()
        .filter(|u| u.source_text.contains("{{NOTE_REF:"))
        .collect();
    assert_eq!(body_with_token.len(), 12);
    // note units 的 target_ref 保留
    let fn_note = units.iter().find(|u| u.note_id == "f001").unwrap();
    assert_eq!(fn_note.target_ref, "{{NOTE_REF:f001}}");
    let en_note = units.iter().find(|u| u.note_id == "e001").unwrap();
    assert_eq!(en_note.target_ref, "{{NOTE_REF:e001}}");

    // summary 字段
    let s = summary.get("unit_planning_summary").unwrap();
    assert_eq!(s["body_unit_count"].as_i64(), Some(12));
    assert_eq!(s["note_unit_count"].as_i64(), Some(2));
    assert_eq!(s["frozen_body_unit_count"].as_i64(), Some(12));
    assert_eq!(s["frozen_note_unit_count"].as_i64(), Some(2));
}

#[test]
fn biopolitics_phase4_real_structure_reviews() {
    // 模拟 Biopolitics 式 review 产生条件
    let chapters = vec![
        make_chapter("ch01", "Introduction", 1, 30, BoundaryState::Ready),
        make_chapter("ch02", "Chapter 2", 31, 60, BoundaryState::ReviewRequired),
        make_chapter("ch03", "Chapter 3", 61, 90, BoundaryState::Ready),
    ];

    let anchors: Vec<BodyAnchorRecord> = (0..5)
        .map(|i| BodyAnchorRecord {
            anchor_id: format!("a{:03}", i),
            chapter_id: "ch01".into(),
            source_marker: format!("{}", i + 1),
            normalized_marker: format!("{}", i + 1),
            anchor_kind: AnchorKind::Unknown,
            source: "rule".into(),
            char_start: i * 10,
            char_end: i * 10 + 1,
            source_text: format!("ref {}", i + 1),
            page_no: i + 1,
            ..Default::default()
        })
        .collect();

    let links: Vec<NoteLinkRecord> = vec![
        NoteLinkRecord {
            link_id: "l001".into(),
            chapter_id: "ch01".into(),
            region_id: "r1".into(),
            note_item_id: "n001".into(),
            anchor_id: "a001".into(),
            status: LinkStatus::OrphanNote,
            note_kind: NoteKind::Endnote,
            marker: "1".into(),
            page_no_start: 5,
            page_no_end: 5,
            ..Default::default()
        },
        NoteLinkRecord {
            link_id: "l002".into(),
            chapter_id: "ch02".into(),
            region_id: "r1".into(),
            note_item_id: "n002".into(),
            anchor_id: "".into(),
            status: LinkStatus::OrphanAnchor,
            note_kind: NoteKind::Footnote,
            marker: "2".into(),
            page_no_start: 35,
            page_no_end: 35,
            ..Default::default()
        },
        NoteLinkRecord {
            link_id: "l003".into(),
            chapter_id: "ch03".into(),
            region_id: "r2".into(),
            note_item_id: "n003".into(),
            anchor_id: "a003".into(),
            status: LinkStatus::Matched,
            note_kind: NoteKind::Footnote,
            marker: "3".into(),
            page_no_start: 65,
            page_no_end: 65,
            ..Default::default()
        },
    ];

    let freeze_errors = vec![FrozenRefEntry {
        link_id: "l003".into(),
        chapter_id: "ch03".into(),
        anchor_id: "a003".into(),
        note_item_id: "n003".into(),
        target_ref: "{{NOTE_REF:n003}}".into(),
        decision: "skipped".into(),
        reason: "token_not_found".into(),
        skip_category: "ceiling_skip".into(),
        page_no: 65,
    }];

    let summary = Phase3Summary {
        toc: SummaryTocBase {
            chapter_title_alignment_ok: false,
            chapter_section_alignment_ok: true,
            toc_semantic_contract_ok: true,
            ..Default::default()
        },
        ..Default::default()
    };

    let (reviews, _summary) =
        build_structure_reviews(&chapters, &anchors, &links, &summary, 0, 0, &freeze_errors);

    // 期望：
    //   - 1 boundary_review_required (ch02)
    //   - 5 uncertain_anchor (ch01)
    //   - 1 endnote_orphan_note (l001)
    //   - 1 footnote_orphan_anchor (l002)
    //   - 1 toc_alignment_review_required (title_alignment_ok=false)
    //   - 1 freeze_matched_ref_not_injected (l003)
    // 总计: 10
    assert_eq!(reviews.len(), 10);

    let mut type_counts: HashMap<&str, usize> = HashMap::new();
    for r in &reviews {
        *type_counts.entry(&r.review_type).or_default() += 1;
    }

    assert_eq!(type_counts.get("boundary_review_required"), Some(&1));
    assert_eq!(type_counts.get("uncertain_anchor"), Some(&5));
    assert_eq!(type_counts.get("endnote_orphan_note"), Some(&1));
    assert_eq!(type_counts.get("footnote_orphan_anchor"), Some(&1));
    assert_eq!(type_counts.get("toc_alignment_review_required"), Some(&1));
    assert_eq!(type_counts.get("freeze_matched_ref_not_injected"), Some(&1));

    // freeze blocker 的 payload 包含定位证据
    let freeze_review = reviews
        .iter()
        .find(|r| r.review_type == "freeze_matched_ref_not_injected")
        .unwrap();
    assert_eq!(freeze_review.payload["link_id"].as_str(), Some("l003"));
    assert_eq!(
        freeze_review.payload["skip_category"].as_str(),
        Some("ceiling_skip")
    );
    assert_eq!(freeze_review.severity, "error");
}
