//! `endnote_repair` 模块单测——拆自原 `endnote_repair.rs` 内 `#[cfg(test)] mod tests`。

use super::*;
use fnm_core::records::{BodyAnchorRecord, NoteLinkRecord};
use fnm_core::types::{AnchorKind, LinkResolver, LinkStatus, NoteKind};
use std::collections::HashMap;

struct LinkArgs<'a> {
    link_id: &'a str,
    chapter_id: &'a str,
    note_item_id: &'a str,
    anchor_id: &'a str,
    status: LinkStatus,
    resolver: LinkResolver,
    note_kind: NoteKind,
    marker: &'a str,
    page_no_start: i64,
}

fn make_link(args: LinkArgs<'_>) -> NoteLinkRecord {
    NoteLinkRecord {
        link_id: args.link_id.to_string(),
        chapter_id: args.chapter_id.to_string(),
        region_id: String::new(),
        note_item_id: args.note_item_id.to_string(),
        anchor_id: args.anchor_id.to_string(),
        status: args.status,
        resolver: args.resolver,
        confidence: 0.8,
        note_kind: args.note_kind,
        marker: args.marker.to_string(),
        page_no_start: args.page_no_start,
        page_no_end: args.page_no_start,
    }
}

fn make_anchor(
    anchor_id: &str,
    chapter_id: &str,
    page_no: i64,
    normalized_marker: &str,
    anchor_kind: AnchorKind,
    synthetic: bool,
) -> BodyAnchorRecord {
    BodyAnchorRecord {
        anchor_id: anchor_id.to_string(),
        chapter_id: chapter_id.to_string(),
        page_no,
        paragraph_index: 0,
        char_start: 0,
        char_end: 0,
        source_marker: normalized_marker.to_string(),
        normalized_marker: normalized_marker.to_string(),
        anchor_kind,
        certainty: 0.9,
        source_text: String::new(),
        source: String::new(),
        synthetic,
        ocr_repaired_from_marker: String::new(),
    }
}

#[test]
fn test_project_priority() {
    assert_eq!(project_priority("book_projected"), 3);
    assert_eq!(project_priority("book_marker_projected"), 2);
    assert_eq!(project_priority("book_fallback_projected"), 1);
    assert_eq!(project_priority("native"), 0);
    assert_eq!(project_priority(""), 0);
    assert_eq!(project_priority("  BOOK_PROJECTED  "), 3);
}

#[test]
fn test_repair_simple_exact_match() {
    let mut anchors = vec![make_anchor(
        "a-1",
        "ch-1",
        10,
        "5",
        AnchorKind::Endnote,
        false,
    )];
    let links = vec![make_link(LinkArgs {
        link_id: "l-1",
        chapter_id: "ch-1",
        note_item_id: "ni-1",
        anchor_id: "",
        status: LinkStatus::OrphanNote,
        resolver: LinkResolver::Rule,
        note_kind: NoteKind::Endnote,
        marker: "5",
        page_no_start: 10,
    })];
    let meta = HashMap::new();
    let (repaired, summary) = repair_endnote_links_for_contract(&links, &mut anchors, &meta);
    assert_eq!(repaired[0].status, LinkStatus::Matched);
    assert_eq!(repaired[0].resolver, LinkResolver::Repair);
    assert_eq!(repaired[0].anchor_id, "a-1");
    assert!(summary.contains_key("contract_repair_matched_count"));
}

#[test]
fn test_suppress_endnote_residual_orphans_no_footnote() {
    let links = vec![
        make_link(LinkArgs {
            link_id: "l-1",
            chapter_id: "ch-1",
            note_item_id: "ni-1",
            anchor_id: "",
            status: LinkStatus::OrphanNote,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Endnote,
            marker: "5",
            page_no_start: 10,
        }),
        make_link(LinkArgs {
            link_id: "l-2",
            chapter_id: "ch-1",
            note_item_id: "",
            anchor_id: "a-2",
            status: LinkStatus::OrphanAnchor,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Endnote,
            marker: "6",
            page_no_start: 12,
        }),
    ];
    let (updated, summary) = suppress_endnote_residual_orphans(&links);
    assert_eq!(updated[0].status, LinkStatus::Ignored);
    assert_eq!(updated[1].status, LinkStatus::Ignored);
    assert_eq!(summary["suppressed_orphan_note_count"], 1);
    assert_eq!(summary["suppressed_orphan_anchor_count"], 1);
}

#[test]
fn test_suppress_endnote_residual_orphans_has_footnote() {
    let links = vec![
        make_link(LinkArgs {
            link_id: "l-1",
            chapter_id: "ch-1",
            note_item_id: "ni-1",
            anchor_id: "a-1",
            status: LinkStatus::Matched,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Footnote,
            marker: "1",
            page_no_start: 5,
        }),
        make_link(LinkArgs {
            link_id: "l-2",
            chapter_id: "ch-1",
            note_item_id: "ni-2",
            anchor_id: "",
            status: LinkStatus::OrphanNote,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Endnote,
            marker: "5",
            page_no_start: 10,
        }),
    ];
    let (updated, summary) = suppress_endnote_residual_orphans(&links);
    // 有 footnote 时不抑制
    assert_eq!(updated[1].status, LinkStatus::OrphanNote);
    assert_eq!(summary["suppressed_orphan_note_count"], 0);
}

#[test]
fn test_repair_skips_footnote_links() {
    let mut anchors = vec![make_anchor(
        "a-1",
        "ch-1",
        10,
        "1",
        AnchorKind::Footnote,
        false,
    )];
    let links = vec![make_link(LinkArgs {
        link_id: "l-1",
        chapter_id: "ch-1",
        note_item_id: "ni-1",
        anchor_id: "",
        status: LinkStatus::OrphanNote,
        resolver: LinkResolver::Rule,
        note_kind: NoteKind::Footnote,
        marker: "1",
        page_no_start: 10,
    })];
    let meta = HashMap::new();
    let (repaired, _) = repair_endnote_links_for_contract(&links, &mut anchors, &meta);
    // footnote link 不被 repair 处理
    assert_eq!(repaired[0].status, LinkStatus::OrphanNote);
    assert_eq!(repaired[0].resolver, LinkResolver::Rule);
}

#[test]
fn test_repair_orphan_anchor_fallback() {
    // orphan_note 通过 fallback 配对 orphan_anchor
    let mut anchors = vec![make_anchor(
        "a-1",
        "ch-1",
        10,
        "5",
        AnchorKind::Endnote,
        false,
    )];
    let links = vec![
        make_link(LinkArgs {
            link_id: "l-1",
            chapter_id: "ch-1",
            note_item_id: "ni-1",
            anchor_id: "",
            status: LinkStatus::OrphanNote,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Endnote,
            marker: "5",
            page_no_start: 10,
        }),
        make_link(LinkArgs {
            link_id: "l-2",
            chapter_id: "ch-1",
            note_item_id: "",
            anchor_id: "a-1",
            status: LinkStatus::OrphanAnchor,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Endnote,
            marker: "5",
            page_no_start: 10,
        }),
    ];
    let meta = HashMap::new();
    let (repaired, _summary) = repair_endnote_links_for_contract(&links, &mut anchors, &meta);
    // 第 1 段精确匹配应该已处理——但这里 anchor 被 orphan_anchor link 占了
    // 第 2 段 fallback 配对应该接管
    let note_link = repaired.iter().find(|l| l.note_item_id == "ni-1").unwrap();
    assert_eq!(note_link.status, LinkStatus::Matched);
}
