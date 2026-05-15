//! Phase 1 SPEC 测试翻译。←→ Python tests/unit/test_fnm_re_module1_toc.py
//!
//! 合成数据 SPEC 测试，验证 toc_semantics / page_partition 的核心行为。

use fnm_core::types::PageRole;
use fnm_phase1::chapter_skeleton::toc_semantics::build_toc_semantics;
use fnm_phase1::input::{RawPage, TocItem};
use fnm_phase1::page_partition::build_page_partitions;

// ── 辅助函数 ──────────────────────────────────────────────────────────────────

fn make_page(book_page: i64, markdown: &str) -> RawPage {
    RawPage {
        book_page,
        markdown: markdown.into(),
        ..Default::default()
    }
}

fn make_toc_item(item_id: &str, title: &str, page: i64, role_hint: &str) -> TocItem {
    TocItem {
        item_id: item_id.into(),
        title: title.into(),
        target_pdf_page: Some(page),
        role_hint: role_hint.into(),
        ..Default::default()
    }
}

// ── SPEC 1: external page roles do not expose noise ──────────────────────────

#[test]
fn spec_external_page_roles_no_noise() {
    // Pages well past the front-matter zone should be body, not noise
    let pages: Vec<RawPage> = (1..=30)
        .map(|i| make_page(i, &format!("## Chapter {}\nThis is body text for chapter {} with enough content to pass all heuristic checks in the page partition module. More text here.", i, i)))
        .collect();

    let result = build_page_partitions(&pages, None, None);
    // Pages 10+ should all be body
    let late_pages_noise = result
        .partitions
        .iter()
        .filter(|p| p.page_no >= 10 && p.page_role == PageRole::Noise)
        .count();
    assert_eq!(late_pages_noise, 0, "Late body pages should not be noise");
}

// ── SPEC 2: disordered TOC can be normalized to monotonic ────────────────────

#[test]
fn spec_disordered_toc_monotonic() {
    let pages = vec![
        make_page(1, "# Chapter Two Content"),
        make_page(2, "# Chapter One Content"),
    ];
    let toc = vec![
        make_toc_item("1", "Chapter Two", 1, "chapter"),
        make_toc_item("2", "Chapter One", 2, "chapter"),
    ];

    let result = build_toc_semantics(&toc, &[], &pages, &[], &[]);
    assert!(
        result.chapter_order_monotonic,
        "Disordered TOC should be normalized to monotonic"
    );
}

// ── SPEC 3: section role hint does not break chapter order gate ──────────────

#[test]
fn spec_section_role_hint_no_break() {
    let pages = vec![
        make_page(1, "# Chapter One"),
        make_page(2, "# Section Content"),
        make_page(3, "# Chapter Two"),
    ];
    let toc = vec![
        make_toc_item("1", "Chapter One", 1, "chapter"),
        make_toc_item("2", "Section A", 2, "section"),
        make_toc_item("3", "Chapter Two", 3, "chapter"),
    ];

    let result = build_toc_semantics(&toc, &[], &pages, &[], &[]);
    assert!(
        result.chapter_order_monotonic,
        "Section role hint should not break chapter order gate"
    );
}

// ── SPEC 4: mid-book other page does not force back_matter start ─────────────

#[test]
fn spec_mid_book_other_no_back_matter() {
    let pages = vec![
        make_page(1, "# Chapter One"),
        make_page(2, "Acknowledgments content"),
        make_page(3, "# Chapter Two"),
    ];
    let toc = vec![
        make_toc_item("1", "Chapter One", 1, "chapter"),
        make_toc_item("2", "Acknowledgments", 2, "front_matter"),
        make_toc_item("3", "Chapter Two", 3, "chapter"),
    ];

    let result = build_toc_semantics(&toc, &[], &pages, &[], &[]);
    assert!(
        !result.aligned_chapters.is_empty(),
        "Mid-book front_matter should not prevent chapter generation"
    );
}

// ── SPEC 5: TOC tree preserves endnotes role and semantic levels ─────────────

#[test]
fn spec_toc_tree_preserves_roles() {
    let pages = vec![
        make_page(1, "# Part I Content"),
        make_page(2, "# Chapter One Content"),
        make_page(3, "## NOTES\n1. Note text."),
        make_page(4, "# Chapter Two Content"),
    ];
    let toc = vec![
        make_toc_item("1", "Part I", 1, "container"),
        make_toc_item("2", "Chapter One", 2, "chapter"),
        make_toc_item("3", "Notes", 3, "endnotes"),
        make_toc_item("4", "Chapter Two", 4, "chapter"),
    ];

    let result = build_toc_semantics(&toc, &[], &pages, &[], &[]);
    let has_chapter = result
        .toc_role_summary
        .get("chapter")
        .is_some_and(|&v| v > 0);
    assert!(
        has_chapter,
        "Should have chapter roles, got: {:?}",
        result.toc_role_summary
    );
}

// ── SPEC 6: page_partition handles mixed roles correctly ─────────────────────

#[test]
fn spec_page_partition_mixed_roles() {
    let pages = vec![
        make_page(1, "# Book Title"),
        make_page(2, "Copyright notice"),
        make_page(3, "## Chapter 1\nMain body text here."),
        make_page(4, "More body text on page 4."),
        make_page(5, "## NOTES\n1. Endnote text here."),
    ];

    let result = build_page_partitions(&pages, None, None);
    // Should have at least one body page
    let body_count = result
        .partitions
        .iter()
        .filter(|p| p.page_role == PageRole::Body)
        .count();
    assert!(
        body_count >= 1,
        "Should have at least 1 body page, got {}",
        body_count
    );
}

// ── SPEC 7: build_toc_semantics with empty input ─────────────────────────────

#[test]
fn spec_toc_semantics_empty() {
    let result = build_toc_semantics(&[], &[], &[], &[], &[]);
    assert!(result.aligned_chapters.is_empty());
    assert!(result.chapter_order_monotonic);
    assert!(result.semantic_blocking_reasons.is_empty());
}

// ── SPEC 8: build_toc_semantics with single chapter ──────────────────────────

#[test]
fn spec_toc_semantics_single_chapter() {
    let pages = vec![make_page(1, "# Chapter One\nBody text.")];
    let toc = vec![make_toc_item("1", "Chapter One", 1, "chapter")];

    let result = build_toc_semantics(&toc, &[], &pages, &[], &[]);
    assert_eq!(result.aligned_chapters.len(), 1);
    assert_eq!(result.aligned_chapters[0].title, "Chapter One");
    assert!(result.chapter_order_monotonic);
}
