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

    let result = build_toc_semantics(&toc, &[], &pages, &[], &[], None);
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

    let result = build_toc_semantics(&toc, &[], &pages, &[], &[], None);
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

    let result = build_toc_semantics(&toc, &[], &pages, &[], &[], None);
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

    let result = build_toc_semantics(&toc, &[], &pages, &[], &[], None);
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
    let result = build_toc_semantics(&[], &[], &[], &[], &[], None);
    assert!(result.aligned_chapters.is_empty());
    assert!(result.chapter_order_monotonic);
    assert!(result.semantic_blocking_reasons.is_empty());
}

// ── SPEC 8: build_toc_semantics with single chapter ──────────────────────────

#[test]
fn spec_toc_semantics_single_chapter() {
    let pages = vec![make_page(1, "# Chapter One\nBody text.")];
    let toc = vec![make_toc_item("1", "Chapter One", 1, "chapter")];

    let result = build_toc_semantics(&toc, &[], &pages, &[], &[], None);
    assert_eq!(result.aligned_chapters.len(), 1);
    assert_eq!(result.aligned_chapters[0].title, "Chapter One");
    assert!(result.chapter_order_monotonic);
}

// ── SPEC 9: biopolitics_toc_gate — 12 章 + post_body 为空 ─────────

#[test]
fn spec_biopolitics_toc_gate() {
    use fnm_phase1::toc_structure::{build_phase1_structure, Phase1Config};
    let pages: Vec<RawPage> = (1..=60)
        .map(|i| {
            let md = if i == 1 {
                "# Title Page".into()
            } else if i % 5 == 0 {
                format!("## Chapter {}\nBody text page {}.", i / 5, i)
            } else {
                format!("Body text page {}.", i)
            };
            RawPage {
                book_page: i,
                markdown: md,
                ..Default::default()
            }
        })
        .collect();
    // 12 chapters + container + endnotes = 14 TOC items
    let mut toc: Vec<TocItem> = (1..=12)
        .map(|i| TocItem {
            item_id: format!("toc-ch-{}", i),
            title: format!("Chapter {}", i),
            level: 1,
            target_pdf_page: Some(i * 5),
            role_hint: "chapter".into(),
            export_candidate: Some(true),
            ..Default::default()
        })
        .collect();
    toc.push(TocItem {
        item_id: "toc-notes".into(),
        title: "Notes".into(),
        level: 1,
        role_hint: "endnotes".into(),
        export_candidate: Some(false),
        ..Default::default()
    });

    let config = Phase1Config::default();
    let output = build_phase1_structure(&pages, Some(&toc), &config).unwrap();

    assert!(
        output.gate_report.hard.values().all(|&v| v),
        "all hard gates should pass"
    );
    let chapters: Vec<_> = output
        .structure
        .chapters
        .iter()
        .filter(|c| c.source == fnm_core::types::ChapterSource::VisualToc)
        .collect();
    assert_eq!(chapters.len(), 12, "should have 12 visual-toc chapters");
    // 所有 chapter 都应该是 visual_toc 或 fallback，没有 post_body 等价物
    let non_standard: Vec<_> = output
        .structure
        .chapters
        .iter()
        .filter(|c| {
            c.source != fnm_core::types::ChapterSource::VisualToc
                && c.source != fnm_core::types::ChapterSource::Fallback
        })
        .collect();
    assert!(
        non_standard.is_empty(),
        "all chapters should be standard source types"
    );
}

// ── SPEC 10: manual_override_recorded ──────────────────────────

#[test]
fn spec_manual_override_recorded() {
    use fnm_phase1::input::ManualPageOverride;
    use fnm_phase1::toc_structure::{build_phase1_structure, Phase1Config};
    use std::collections::HashMap;

    let pages = vec![
        RawPage {
            book_page: 1,
            markdown: "Copyright page.".into(),
            ..Default::default()
        },
        RawPage {
            book_page: 2,
            markdown: "# Chapter One\nBody text.".into(),
            ..Default::default()
        },
    ];
    let toc = vec![TocItem {
        item_id: "toc-1".into(),
        title: "Chapter One".into(),
        level: 1,
        target_pdf_page: Some(2),
        role_hint: "chapter".into(),
        ..Default::default()
    }];
    let mut overrides: HashMap<String, ManualPageOverride> = HashMap::new();
    overrides.insert(
        "1".into(),
        ManualPageOverride {
            page_role: Some("front_matter".into()),
            ..Default::default()
        },
    );

    let config = Phase1Config {
        manual_page_overrides: Some(overrides),
        ..Phase1Config::default()
    };
    let output = build_phase1_structure(&pages, Some(&toc), &config).unwrap();

    assert!(
        !output.overrides_used.is_empty(),
        "overrides should be recorded"
    );
    assert!(
        output
            .overrides_used
            .iter()
            .any(|r| r.kind == "page_override"),
        "at least one override should have kind=page_override"
    );
}

// ── SPEC 11: visual_toc_export_candidate_default ────────────────

#[test]
fn spec_visual_toc_export_candidate_default() {
    use fnm_phase1::toc_structure::{build_phase1_structure, Phase1Config};

    // 30 body pages + 3 level-1 TOC items, none declare export_candidate
    let pages: Vec<RawPage> = (1..=30)
        .map(|i| {
            let md = match i {
                5 => "# Chapter One\nBody text.".into(),
                15 => "# Chapter Two\nBody text.".into(),
                25 => "# Chapter Three\nBody text.".into(),
                _ => format!("Body text page {}.", i),
            };
            RawPage {
                book_page: i,
                markdown: md,
                ..Default::default()
            }
        })
        .collect();
    let toc = vec![
        TocItem {
            item_id: "toc-1".into(),
            title: "Chapter One".into(),
            level: 1,
            target_pdf_page: Some(5),
            role_hint: "chapter".into(),
            export_candidate: None, // ← 关键：不设 export_candidate
            ..Default::default()
        },
        TocItem {
            item_id: "toc-2".into(),
            title: "Chapter Two".into(),
            level: 1,
            target_pdf_page: Some(15),
            role_hint: "chapter".into(),
            export_candidate: None,
            ..Default::default()
        },
        TocItem {
            item_id: "toc-3".into(),
            title: "Chapter Three".into(),
            level: 1,
            target_pdf_page: Some(25),
            role_hint: "chapter".into(),
            export_candidate: None,
            ..Default::default()
        },
    ];

    let config = Phase1Config::default();
    let output = build_phase1_structure(&pages, Some(&toc), &config).unwrap();

    let summary = output
        .diagnostics
        .get("chapter_source_summary")
        .and_then(|v| v.as_object())
        .expect("chapter_source_summary should exist in diagnostics");
    assert_eq!(
        summary.get("source").and_then(|v| v.as_str()),
        Some("visual_toc"),
        "source should be visual_toc, got {:?}",
        summary.get("source")
    );
    let vt_count = summary
        .get("visual_toc_chapter_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    assert!(
        vt_count >= 3,
        "visual_toc_chapter_count should be >= 3, got {}",
        vt_count
    );
}

// ── SPEC 12: endnotes_start_page 传递 ──────────────────────────

#[test]
fn spec_endnotes_start_page_applied() {
    use fnm_phase1::toc_structure::{build_phase1_structure, Phase1Config};

    let pages: Vec<RawPage> = (1..=10)
        .map(|i| RawPage {
            book_page: i,
            markdown: format!("Body text page {}.", i),
            ..Default::default()
        })
        .collect();
    let config = Phase1Config {
        endnotes_start_page: Some(8),
        ..Phase1Config::default()
    };
    let output = build_phase1_structure(&pages, None, &config).unwrap();
    assert_eq!(output.structure.pages.len(), 10);
    let page_8 = output.structure.pages.iter().find(|p| p.page_no == 8);
    assert!(page_8.is_some(), "page 8 should exist in partitions");
}
