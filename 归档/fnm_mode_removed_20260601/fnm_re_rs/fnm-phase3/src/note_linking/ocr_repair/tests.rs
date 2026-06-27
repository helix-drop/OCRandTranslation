//! `ocr_repair` 模块单测——拆自原 `ocr_repair.rs` 内 `#[cfg(test)] mod tests`。

use super::*;
use fnm_core::records::{BodyAnchorRecord, NoteItemRecord, NoteLinkRecord};
use fnm_core::types::{AnchorKind, LinkResolver, LinkStatus, NoteKind};

fn make_anchor(
    id: &str,
    chapter: &str,
    page: i64,
    marker: &str,
    synthetic: bool,
) -> BodyAnchorRecord {
    BodyAnchorRecord {
        anchor_id: id.to_string(),
        chapter_id: chapter.to_string(),
        page_no: page,
        paragraph_index: 0,
        char_start: 0,
        char_end: 0,
        source_marker: marker.to_string(),
        normalized_marker: marker.to_string(),
        anchor_kind: AnchorKind::Footnote,
        certainty: 1.0,
        source_text: String::new(),
        source: String::new(),
        synthetic,
        ocr_repaired_from_marker: String::new(),
    }
}

struct LinkArgs<'a> {
    id: &'a str,
    chapter: &'a str,
    status: LinkStatus,
    resolver: LinkResolver,
    note_kind: NoteKind,
    anchor_id: &'a str,
    marker: &'a str,
    page: i64,
}

fn make_link(args: LinkArgs<'_>) -> NoteLinkRecord {
    NoteLinkRecord {
        link_id: args.id.to_string(),
        chapter_id: args.chapter.to_string(),
        region_id: String::new(),
        note_item_id: String::new(),
        anchor_id: args.anchor_id.to_string(),
        status: args.status,
        resolver: args.resolver,
        confidence: 1.0,
        note_kind: args.note_kind,
        marker: args.marker.to_string(),
        page_no_start: args.page,
        page_no_end: 0,
    }
}

#[test]
fn test_empty_input() {
    let anchors: Vec<BodyAnchorRecord> = Vec::new();
    let links: Vec<NoteLinkRecord> = Vec::new();
    let items: Vec<NoteItemRecord> = Vec::new();
    let (ra, rl, summary) = repair_explicit_footnote_anchor_ocr_variants(&anchors, &links, &items);
    assert!(ra.is_empty());
    assert!(rl.is_empty());
    assert_eq!(summary.get("explicit_anchor_rebind_count"), Some(&0));
    assert_eq!(summary.get("ignored_orphan_anchor_count"), Some(&0));
    assert_eq!(summary.get("ambiguous_followup_match_count"), Some(&0));
    assert_eq!(summary.get("ambiguous_followup_rebind_count"), Some(&0));
    assert_eq!(
        summary.get("cross_chapter_same_page_rebind_count"),
        Some(&0)
    );
}

#[test]
fn test_loop1_orphan_anchor_rebind() {
    let anchors = vec![
        make_anchor("anc-explicit", "ch-1", 10, "1", false),
        make_anchor("synthetic-footnote-1", "ch-1", 10, "1", true),
    ];
    let links = vec![
        make_link(LinkArgs {
            id: "link-orphan",
            chapter: "ch-1",
            status: LinkStatus::OrphanAnchor,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Footnote,
            anchor_id: "anc-explicit",
            marker: "1",
            page: 10,
        }),
        make_link(LinkArgs {
            id: "link-matched",
            chapter: "ch-1",
            status: LinkStatus::Matched,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Footnote,
            anchor_id: "synthetic-footnote-1",
            marker: "l",
            page: 10,
        }),
    ];
    let items = vec![NoteItemRecord {
        note_item_id: "ni-1".to_string(),
        page_no: 10,
        marker: "1".to_string(),
        chapter_id: "ch-1".to_string(),
        note_kind: NoteKind::Footnote,
        ..Default::default()
    }];
    // link-matched needs note_item_id that maps to items
    let mut links_with_item = links;
    links_with_item[1].note_item_id = "ni-1".to_string();
    let (_ra, rl, summary) =
        repair_explicit_footnote_anchor_ocr_variants(&anchors, &links_with_item, &items);
    assert_eq!(summary.get("explicit_anchor_rebind_count"), Some(&1));
    assert_eq!(summary.get("ignored_orphan_anchor_count"), Some(&1));
    // orphan link → ignored, matched link → rebound to explicit anchor
    let orphan_link = rl.iter().find(|l| l.link_id == "link-orphan").unwrap();
    assert_eq!(orphan_link.status, LinkStatus::Ignored);
    let matched_link = rl.iter().find(|l| l.link_id == "link-matched").unwrap();
    assert_eq!(matched_link.anchor_id, "anc-explicit");
    assert_eq!(matched_link.resolver, LinkResolver::Repair);
}

#[test]
fn test_loop2_ambiguous_followup() {
    let anchors = vec![
        make_anchor("anc-a", "ch-1", 10, "1", false),
        make_anchor("anc-b", "ch-1", 10, "1", false),
        make_anchor("synthetic-footnote-1", "ch-1", 10, "1", true),
    ];
    let links = vec![
        make_link(LinkArgs {
            id: "link-ambiguous",
            chapter: "ch-1",
            status: LinkStatus::Ambiguous,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Footnote,
            anchor_id: "",
            marker: "1",
            page: 10,
        }),
        make_link(LinkArgs {
            id: "link-followup",
            chapter: "ch-1",
            status: LinkStatus::Matched,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Footnote,
            anchor_id: "synthetic-footnote-1",
            marker: "l",
            page: 10,
        }),
    ];
    let items: Vec<NoteItemRecord> = Vec::new();
    let (_ra, rl, summary) = repair_explicit_footnote_anchor_ocr_variants(&anchors, &links, &items);
    assert_eq!(summary.get("ambiguous_followup_match_count"), Some(&1));
    assert_eq!(summary.get("ambiguous_followup_rebind_count"), Some(&1));
    // ambiguous → matched (bound to first explicit anchor)
    let ambiguous_link = rl.iter().find(|l| l.link_id == "link-ambiguous").unwrap();
    assert_eq!(ambiguous_link.status, LinkStatus::Matched);
    assert_eq!(ambiguous_link.anchor_id, "anc-a");
    // followup → rebound to second explicit anchor
    let followup_link = rl.iter().find(|l| l.link_id == "link-followup").unwrap();
    assert_eq!(followup_link.anchor_id, "anc-b");
    assert_eq!(followup_link.resolver, LinkResolver::Repair);
}

#[test]
fn test_loop3_cross_chapter_same_page_rebind() {
    // 测试：跨章 case 不应被修（章守卫），即使同页同 marker
    let anchors = vec![
        make_anchor("anc-explicit", "ch-2", 10, "1", false),
        make_anchor("synthetic-footnote-1", "ch-1", 10, "1", true),
    ];
    let links = vec![
        make_link(LinkArgs {
            id: "link-matched",
            chapter: "ch-1",
            status: LinkStatus::Matched,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Footnote,
            anchor_id: "synthetic-footnote-1",
            marker: "1",
            page: 10,
        }),
        make_link(LinkArgs {
            id: "link-orphan",
            chapter: "ch-2",
            status: LinkStatus::OrphanAnchor,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Footnote,
            anchor_id: "anc-explicit",
            marker: "1",
            page: 10,
        }),
    ];
    let items: Vec<NoteItemRecord> = Vec::new();
    let (_ra, rl, summary) = repair_explicit_footnote_anchor_ocr_variants(&anchors, &links, &items);
    // 跨章守卫阻止重绑定
    assert_eq!(
        summary.get("cross_chapter_same_page_rebind_count"),
        Some(&0)
    );
    // synthetic link 保持原状
    let matched_link = rl.iter().find(|l| l.link_id == "link-matched").unwrap();
    assert_eq!(matched_link.anchor_id, "synthetic-footnote-1");
    assert_eq!(matched_link.resolver, LinkResolver::Rule);
    // orphan link 保持原状
    let orphan_link = rl.iter().find(|l| l.link_id == "link-orphan").unwrap();
    assert_eq!(orphan_link.status, LinkStatus::OrphanAnchor);
}

#[test]
fn test_loop3_same_chapter_rebind() {
    // 测试：同章同页同 marker 的重绑定仍正常工作
    let anchors = vec![
        make_anchor("anc-explicit", "ch-1", 10, "1", false),
        make_anchor("synthetic-footnote-1", "ch-1", 10, "1", true),
    ];
    let links = vec![
        make_link(LinkArgs {
            id: "link-matched",
            chapter: "ch-1",
            status: LinkStatus::Matched,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Footnote,
            anchor_id: "synthetic-footnote-1",
            marker: "1",
            page: 10,
        }),
        make_link(LinkArgs {
            id: "link-orphan",
            chapter: "ch-1",
            status: LinkStatus::OrphanAnchor,
            resolver: LinkResolver::Rule,
            note_kind: NoteKind::Footnote,
            anchor_id: "anc-explicit",
            marker: "1",
            page: 10,
        }),
    ];
    let items: Vec<NoteItemRecord> = Vec::new();
    let (_ra, rl, summary) = repair_explicit_footnote_anchor_ocr_variants(&anchors, &links, &items);
    assert_eq!(
        summary.get("cross_chapter_same_page_rebind_count"),
        Some(&1)
    );
    // synthetic link → rebound to explicit anchor
    let matched_link = rl.iter().find(|l| l.link_id == "link-matched").unwrap();
    assert_eq!(matched_link.anchor_id, "anc-explicit");
    assert_eq!(matched_link.resolver, LinkResolver::Repair);
    // orphan link → ignored
    let orphan_link = rl.iter().find(|l| l.link_id == "link-orphan").unwrap();
    assert_eq!(orphan_link.status, LinkStatus::Ignored);
}
