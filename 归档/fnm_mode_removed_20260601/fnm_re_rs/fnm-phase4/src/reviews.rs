//! ←→ Python `FNM_RE/stages/reviews.py`（~210 行）
//!
//! 结构复核生成：遍历 chapters + body_anchors + effective_links，
//! 生成 9 类 StructureReviewRecord。

use fnm_core::records::{
    BodyAnchorRecord, ChapterRecord, FrozenRefEntry, NoteLinkRecord, Phase3Summary,
    StructureReviewRecord,
};
use fnm_core::types::{AnchorKind, BoundaryState, LinkStatus, NoteKind};
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::{HashMap, HashSet};

// ── 常量 ──────────────────────────────────────────────────────

/// ←→ Python `_REVIEW_TYPE_WHITELIST` (reviews.py:11-21)
const REVIEW_TYPE_WHITELIST: &[&str] = &[
    "boundary_review_required",
    "uncertain_anchor",
    "footnote_orphan_note",
    "footnote_orphan_anchor",
    "endnote_orphan_note",
    "endnote_orphan_anchor",
    "ambiguous",
    "toc_alignment_review_required",
    "toc_semantic_review_required",
    "freeze_matched_ref_not_injected",
];

/// ←→ Python `_WARNING_REVIEW_TYPES` (reviews.py:22)
const WARNING_REVIEW_TYPES: &[&str] = &["ambiguous", "uncertain_anchor"];

/// ←→ Python `_REVIEW_ID_SANITIZE_RE` (reviews.py:23)
static REVIEW_ID_SANITIZE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^0-9a-zA-Z]+").unwrap());

// ── 辅助函数 ──────────────────────────────────────────────────────

/// ←→ Python `_sanitize_review_token` (reviews.py:26-29)
fn sanitize_review_token(value: &str) -> String {
    let token = REVIEW_ID_SANITIZE_RE.replace_all(value, "-").to_string();
    let token = token.trim_matches('-').to_string();
    if token.is_empty() {
        "na".to_string()
    } else {
        token
    }
}

/// ←→ Python `_make_review_id` (reviews.py:32-46)
fn make_review_id(
    review_type: &str,
    chapter_id: &str,
    page_start: i64,
    page_end: i64,
    target_id: &str,
) -> String {
    format!(
        "review-{}-{}-{}-{}-{}",
        sanitize_review_token(review_type),
        sanitize_review_token(chapter_id),
        page_start,
        page_end,
        sanitize_review_token(target_id)
    )
}

/// ←→ Python `_append_review` (reviews.py:49-81)
fn append_review(
    reviews: &mut Vec<StructureReviewRecord>,
    review_type: &str,
    chapter_id: &str,
    page_start: i64,
    page_end: i64,
    payload: serde_json::Value,
) {
    if !REVIEW_TYPE_WHITELIST.contains(&review_type) {
        return;
    }
    let target_id = payload
        .get("anchor_id")
        .or_else(|| payload.get("note_item_id"))
        .or_else(|| payload.get("link_id"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let target_id = if target_id.is_empty() {
        format!("{}-{}", page_start, page_end)
    } else {
        target_id
    };
    let severity = if WARNING_REVIEW_TYPES.contains(&review_type) {
        "warning"
    } else {
        "error"
    };
    reviews.push(StructureReviewRecord {
        review_id: make_review_id(review_type, chapter_id, page_start, page_end, &target_id),
        review_type: review_type.to_string(),
        chapter_id: chapter_id.to_string(),
        page_start,
        page_end,
        severity: severity.to_string(),
        payload,
    });
}

// ── 主函数 ──────────────────────────────────────────────────────

/// ←→ Python `build_structure_reviews` (reviews.py:84-209)
///
/// 构建结构复核记录。
///
/// # 参数
///
/// - `chapters` — 章节列表（用于 boundary_review_required）
/// - `body_anchors` — 正文锚点列表（用于 uncertain_anchor）
/// - `effective_note_links` — 有效链接列表（用于 orphan/ambiguous）
/// - `summary` — Phase3Summary（用于 toc_alignment/toc_semantic）
/// - `ignored_link_override_count` — 忽略的链接覆盖数
/// - `invalid_override_count` — 无效覆盖数
/// - `freeze_error_rows` — freeze 阶段注入失败条目列表
///
/// # 返回
///
/// `(Vec<StructureReviewRecord>, serde_json::Value)` — 去重排序后的 reviews + summary
pub fn build_structure_reviews(
    chapters: &[ChapterRecord],
    body_anchors: &[BodyAnchorRecord],
    effective_note_links: &[NoteLinkRecord],
    summary: &Phase3Summary,
    ignored_link_override_count: usize,
    invalid_override_count: usize,
    freeze_error_rows: &[FrozenRefEntry],
) -> (Vec<StructureReviewRecord>, serde_json::Value) {
    build_structure_reviews_with_policy(
        chapters,
        body_anchors,
        effective_note_links,
        SummaryReviewPolicy {
            summary,
            emit_upstream_gate_reviews: true,
        },
        ignored_link_override_count,
        invalid_override_count,
        freeze_error_rows,
    )
}

pub(crate) fn build_structure_reviews_without_upstream_gate_reviews(
    chapters: &[ChapterRecord],
    body_anchors: &[BodyAnchorRecord],
    effective_note_links: &[NoteLinkRecord],
    summary: &Phase3Summary,
    ignored_link_override_count: usize,
    invalid_override_count: usize,
    freeze_error_rows: &[FrozenRefEntry],
) -> (Vec<StructureReviewRecord>, serde_json::Value) {
    build_structure_reviews_with_policy(
        chapters,
        body_anchors,
        effective_note_links,
        SummaryReviewPolicy {
            summary,
            emit_upstream_gate_reviews: false,
        },
        ignored_link_override_count,
        invalid_override_count,
        freeze_error_rows,
    )
}

struct SummaryReviewPolicy<'a> {
    summary: &'a Phase3Summary,
    emit_upstream_gate_reviews: bool,
}

fn build_structure_reviews_with_policy(
    chapters: &[ChapterRecord],
    body_anchors: &[BodyAnchorRecord],
    effective_note_links: &[NoteLinkRecord],
    summary_policy: SummaryReviewPolicy<'_>,
    ignored_link_override_count: usize,
    invalid_override_count: usize,
    freeze_error_rows: &[FrozenRefEntry],
) -> (Vec<StructureReviewRecord>, serde_json::Value) {
    let summary = summary_policy.summary;
    let mut reviews: Vec<StructureReviewRecord> = Vec::new();

    // 1. boundary_review_required
    for chapter in chapters {
        if chapter.boundary_state != BoundaryState::ReviewRequired {
            continue;
        }
        append_review(
            &mut reviews,
            "boundary_review_required",
            &chapter.chapter_id,
            chapter.start_page,
            if chapter.end_page > 0 {
                chapter.end_page
            } else {
                chapter.start_page
            },
            serde_json::json!({"reason": "chapter_boundary_conflict"}),
        );
    }

    // 2. uncertain_anchor
    for anchor in body_anchors {
        if anchor.anchor_kind != AnchorKind::Unknown && anchor.certainty >= 1.0 {
            continue;
        }
        append_review(
            &mut reviews,
            "uncertain_anchor",
            &anchor.chapter_id,
            anchor.page_no,
            anchor.page_no,
            serde_json::json!({
                "anchor_id": anchor.anchor_id,
                "marker": anchor.normalized_marker,
                "certainty": anchor.certainty,
                "synthetic": anchor.synthetic,
            }),
        );
    }

    // 3-7. orphan/ambiguous
    for link in effective_note_links {
        if link.status == LinkStatus::Ignored {
            continue;
        }
        let review_type = match link.status {
            LinkStatus::OrphanNote => match link.note_kind {
                NoteKind::Footnote => "footnote_orphan_note",
                NoteKind::Endnote => "endnote_orphan_note",
                NoteKind::Unknown => "unknown_orphan_note",
            },
            LinkStatus::OrphanAnchor => match link.note_kind {
                NoteKind::Footnote => "footnote_orphan_anchor",
                NoteKind::Endnote => "endnote_orphan_anchor",
                NoteKind::Unknown => "unknown_orphan_anchor",
            },
            LinkStatus::Ambiguous => "ambiguous",
            _ => continue,
        };
        append_review(
            &mut reviews,
            review_type,
            &link.chapter_id,
            link.page_no_start,
            if link.page_no_end > 0 {
                link.page_no_end
            } else {
                link.page_no_start
            },
            serde_json::json!({
                "link_id": link.link_id,
                "note_item_id": link.note_item_id,
                "anchor_id": link.anchor_id,
                "note_kind": link.note_kind.as_str(),
                "marker": link.marker,
            }),
        );
    }

    // 8. toc_alignment_review_required
    if summary_policy.emit_upstream_gate_reviews
        && (!summary.toc.chapter_title_alignment_ok || !summary.toc.chapter_section_alignment_ok)
    {
        append_review(
            &mut reviews,
            "toc_alignment_review_required",
            "",
            0,
            0,
            serde_json::json!({
                "chapter_title_alignment_ok": summary.toc.chapter_title_alignment_ok,
                "chapter_section_alignment_ok": summary.toc.chapter_section_alignment_ok,
                "toc_alignment_summary": summary.toc.toc_alignment_summary,
            }),
        );
    }

    // 9. toc_semantic_review_required
    if summary_policy.emit_upstream_gate_reviews && !summary.toc.toc_semantic_contract_ok {
        append_review(
            &mut reviews,
            "toc_semantic_review_required",
            "",
            0,
            0,
            serde_json::json!({
                "toc_semantic_contract_ok": summary.toc.toc_semantic_contract_ok,
                "toc_semantic_summary": summary.toc.toc_semantic_summary,
                "toc_semantic_blocking_reasons": summary.toc.toc_semantic_blocking_reasons,
            }),
        );
    }

    // 10. freeze_matched_ref_not_injected
    //     matched link 因坐标/锚点/页面缺失等错误导致注入失败时产生 blocker
    for entry in freeze_error_rows {
        append_review(
            &mut reviews,
            "freeze_matched_ref_not_injected",
            &entry.chapter_id,
            entry.page_no,
            entry.page_no,
            serde_json::json!({
                "link_id": entry.link_id,
                "anchor_id": entry.anchor_id,
                "note_item_id": entry.note_item_id,
                "reason": entry.reason,
                "skip_category": entry.skip_category,
                "target_ref": entry.target_ref,
            }),
        );
    }

    // 去重
    let mut seen_ids: HashSet<String> = HashSet::new();
    let mut deduped: Vec<StructureReviewRecord> = Vec::new();
    for review in reviews {
        if seen_ids.contains(&review.review_id) {
            continue;
        }
        seen_ids.insert(review.review_id.clone());
        deduped.push(review);
    }

    // 排序
    deduped.sort_by(|a, b| {
        a.review_type
            .cmp(&b.review_type)
            .then(a.chapter_id.cmp(&b.chapter_id))
            .then(a.page_start.cmp(&b.page_start))
            .then(a.page_end.cmp(&b.page_end))
            .then(a.review_id.cmp(&b.review_id))
    });

    // 统计
    let mut review_type_counts: HashMap<String, i64> = HashMap::new();
    let mut error_count = 0;
    let mut warning_count = 0;
    for review in &deduped {
        *review_type_counts
            .entry(review.review_type.clone())
            .or_default() += 1;
        if review.severity == "error" {
            error_count += 1;
        } else if review.severity == "warning" {
            warning_count += 1;
        }
    }

    let summary = serde_json::json!({
        "review_type_counts": review_type_counts,
        "error_count": error_count,
        "warning_count": warning_count,
        "ignored_link_override_count": ignored_link_override_count,
        "invalid_override_count": invalid_override_count,
        "freeze_error_count": freeze_error_rows.len(),
    });

    (deduped, summary)
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::SummaryTocBase;
    use fnm_core::types::ChapterSource;

    fn make_chapter(chapter_id: &str, boundary_state: BoundaryState) -> ChapterRecord {
        ChapterRecord {
            chapter_id: chapter_id.to_string(),
            title: format!("Chapter {}", chapter_id),
            start_page: 10,
            end_page: 20,
            pages: vec![],
            boundary_state,
            source: ChapterSource::Fallback,
        }
    }

    fn make_anchor(
        anchor_id: &str,
        chapter_id: &str,
        page_no: i64,
        anchor_kind: AnchorKind,
        certainty: f64,
    ) -> BodyAnchorRecord {
        BodyAnchorRecord {
            anchor_id: anchor_id.to_string(),
            chapter_id: chapter_id.to_string(),
            page_no,
            anchor_kind,
            certainty,
            ..Default::default()
        }
    }

    fn make_link(
        link_id: &str,
        chapter_id: &str,
        status: LinkStatus,
        note_kind: NoteKind,
    ) -> NoteLinkRecord {
        NoteLinkRecord {
            link_id: link_id.to_string(),
            chapter_id: chapter_id.to_string(),
            status,
            note_kind,
            marker: "1".to_string(),
            page_no_start: 10,
            page_no_end: 10,
            ..Default::default()
        }
    }

    fn default_summary() -> Phase3Summary {
        Phase3Summary {
            toc: SummaryTocBase {
                chapter_title_alignment_ok: true,
                chapter_section_alignment_ok: true,
                toc_semantic_contract_ok: true,
                ..Default::default()
            },
            ..Default::default()
        }
    }

    fn default_freeze_error_rows() -> Vec<FrozenRefEntry> {
        Vec::new()
    }

    #[test]
    fn test_boundary_review_required() {
        let chapters = vec![make_chapter("ch1", BoundaryState::ReviewRequired)];
        let (reviews, _) = build_structure_reviews(
            &chapters,
            &[],
            &[],
            &default_summary(),
            0,
            0,
            &default_freeze_error_rows(),
        );
        assert_eq!(reviews.len(), 1);
        assert_eq!(reviews[0].review_type, "boundary_review_required");
    }

    #[test]
    fn test_uncertain_anchor_unknown_kind() {
        let anchors = vec![make_anchor("a1", "ch1", 10, AnchorKind::Unknown, 1.0)];
        let (reviews, _) = build_structure_reviews(
            &[],
            &anchors,
            &[],
            &default_summary(),
            0,
            0,
            &default_freeze_error_rows(),
        );
        assert_eq!(reviews.len(), 1);
        assert_eq!(reviews[0].review_type, "uncertain_anchor");
    }

    #[test]
    fn test_uncertain_anchor_low_certainty() {
        let anchors = vec![make_anchor("a1", "ch1", 10, AnchorKind::Footnote, 0.5)];
        let (reviews, _) = build_structure_reviews(
            &[],
            &anchors,
            &[],
            &default_summary(),
            0,
            0,
            &default_freeze_error_rows(),
        );
        assert_eq!(reviews.len(), 1);
        assert_eq!(reviews[0].review_type, "uncertain_anchor");
    }

    #[test]
    fn test_footnote_orphan_note() {
        let links = vec![make_link(
            "l1",
            "ch1",
            LinkStatus::OrphanNote,
            NoteKind::Footnote,
        )];
        let (reviews, _) = build_structure_reviews(
            &[],
            &[],
            &links,
            &default_summary(),
            0,
            0,
            &default_freeze_error_rows(),
        );
        assert_eq!(reviews.len(), 1);
        assert_eq!(reviews[0].review_type, "footnote_orphan_note");
    }

    #[test]
    fn test_endnote_orphan_anchor() {
        let links = vec![make_link(
            "l1",
            "ch1",
            LinkStatus::OrphanAnchor,
            NoteKind::Endnote,
        )];
        let (reviews, _) = build_structure_reviews(
            &[],
            &[],
            &links,
            &default_summary(),
            0,
            0,
            &default_freeze_error_rows(),
        );
        assert_eq!(reviews.len(), 1);
        assert_eq!(reviews[0].review_type, "endnote_orphan_anchor");
    }

    #[test]
    fn test_ambiguous() {
        let links = vec![make_link(
            "l1",
            "ch1",
            LinkStatus::Ambiguous,
            NoteKind::Footnote,
        )];
        let (reviews, _) = build_structure_reviews(
            &[],
            &[],
            &links,
            &default_summary(),
            0,
            0,
            &default_freeze_error_rows(),
        );
        assert_eq!(reviews.len(), 1);
        assert_eq!(reviews[0].review_type, "ambiguous");
        assert_eq!(reviews[0].severity, "warning");
    }

    #[test]
    fn test_ignored_link_skipped() {
        let links = vec![make_link(
            "l1",
            "ch1",
            LinkStatus::Ignored,
            NoteKind::Footnote,
        )];
        let (reviews, _) = build_structure_reviews(
            &[],
            &[],
            &links,
            &default_summary(),
            0,
            0,
            &default_freeze_error_rows(),
        );
        assert!(reviews.is_empty());
    }

    #[test]
    fn test_toc_alignment_review_required() {
        let mut summary = default_summary();
        summary.toc.chapter_title_alignment_ok = false;
        let (reviews, _) =
            build_structure_reviews(&[], &[], &[], &summary, 0, 0, &default_freeze_error_rows());
        assert_eq!(reviews.len(), 1);
        assert_eq!(reviews[0].review_type, "toc_alignment_review_required");
    }

    #[test]
    fn test_toc_semantic_review_required() {
        let mut summary = default_summary();
        summary.toc.toc_semantic_contract_ok = false;
        let (reviews, _) =
            build_structure_reviews(&[], &[], &[], &summary, 0, 0, &default_freeze_error_rows());
        assert_eq!(reviews.len(), 1);
        assert_eq!(reviews[0].review_type, "toc_semantic_review_required");
    }

    #[test]
    fn test_dedup() {
        let links = vec![
            make_link("l1", "ch1", LinkStatus::OrphanNote, NoteKind::Footnote),
            make_link("l1", "ch1", LinkStatus::OrphanNote, NoteKind::Footnote), // 重复
        ];
        let (reviews, _) = build_structure_reviews(
            &[],
            &[],
            &links,
            &default_summary(),
            0,
            0,
            &default_freeze_error_rows(),
        );
        assert_eq!(reviews.len(), 1);
    }

    #[test]
    fn test_sort_order() {
        let chapters = vec![make_chapter("ch2", BoundaryState::ReviewRequired)];
        let links = vec![make_link(
            "l1",
            "ch1",
            LinkStatus::OrphanNote,
            NoteKind::Footnote,
        )];
        let (reviews, _) = build_structure_reviews(
            &chapters,
            &[],
            &links,
            &default_summary(),
            0,
            0,
            &default_freeze_error_rows(),
        );
        assert_eq!(reviews.len(), 2);
        // boundary_review_required < footnote_orphan_note (按 review_type 排序)
        assert_eq!(reviews[0].review_type, "boundary_review_required");
        assert_eq!(reviews[1].review_type, "footnote_orphan_note");
    }

    #[test]
    fn test_summary_counts() {
        let chapters = vec![make_chapter("ch1", BoundaryState::ReviewRequired)];
        let links = vec![make_link(
            "l1",
            "ch1",
            LinkStatus::Ambiguous,
            NoteKind::Footnote,
        )];
        let (_, summary) = build_structure_reviews(
            &chapters,
            &[],
            &links,
            &default_summary(),
            0,
            0,
            &default_freeze_error_rows(),
        );
        assert_eq!(summary["error_count"], 1);
        assert_eq!(summary["warning_count"], 1);
    }

    #[test]
    fn test_freeze_error_generates_review() {
        let freeze_errors = vec![FrozenRefEntry {
            link_id: "l1".to_string(),
            chapter_id: "ch1".to_string(),
            anchor_id: "a1".to_string(),
            note_item_id: "n1".to_string(),
            target_ref: "{{NOTE_REF:n1}}".to_string(),
            decision: "skipped".to_string(),
            reason: "token_not_found".to_string(),
            skip_category: "ceiling_skip".to_string(),
            page_no: 10,
        }];
        let (reviews, _) =
            build_structure_reviews(&[], &[], &[], &default_summary(), 0, 0, &freeze_errors);
        assert_eq!(reviews.len(), 1);
        assert_eq!(reviews[0].review_type, "freeze_matched_ref_not_injected");
        assert_eq!(reviews[0].severity, "error");
        assert_eq!(reviews[0].chapter_id, "ch1");
        assert_eq!(reviews[0].page_start, 10);
    }
}
