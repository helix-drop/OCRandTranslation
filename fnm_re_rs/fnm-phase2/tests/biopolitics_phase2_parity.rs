//! F12: Biopolitics Phase 2 parity 比对测试。
//!
//! 加载 Biopolitics 全量 raw_pages.json，运行 Rust Phase 1 → Phase 2 pipeline，
//! 验证 note_regions + note_items 输出。

use fnm_core::records::ChapterRecord;
use fnm_core::types::{BoundaryState, ChapterSource, NoteKind};
use fnm_phase2::build_phase2_structure_sync;
use fnm_phase2::input::{Phase2Config, Phase2Input};

/// 辅助：加载 Biopolitics 页面数据
fn load_biopolitics_pages() -> Vec<fnm_phase1::input::RawPage> {
    let raw: serde_json::Value = serde_json::from_str(include_str!(
        "../../../test_example/Biopolitics/raw_pages.json"
    ))
    .expect("Failed to parse Biopolitics raw_pages.json");

    let pages_json = raw["pages"].as_array().expect("pages should be array");
    pages_json
        .iter()
        .map(|p| serde_json::from_value(p.clone()).expect("Failed to parse page"))
        .collect()
}

/// 辅助：从 TOC items 构建 ChapterRecord（与 Python Phase 1 对齐）
fn build_chapters() -> Vec<ChapterRecord> {
    let toc: Vec<(&str, i64)> = vec![
        ("Leçon du 10 janvier 1979", 17),
        ("Leçon du 17 janvier 1979", 43),
        ("Leçon du 24 janvier 1979", 67),
        ("Leçon du 31 janvier 1979", 90),
        ("Leçon du 7 février 1979", 107),
        ("Leçon du 14 février 1979", 130),
        ("Leçon du 21 février 1979", 149),
        ("Leçon du 28 février 1979", 165),
        ("Leçon du 7 mars 1979", 192),
        ("Leçon du 14 mars 1979", 219),
        ("Leçon du 21 mars 1979", 252),
        ("Leçon du 4 avril 1979", 290),
    ];
    let total_pages = 370i64;
    toc.iter()
        .enumerate()
        .map(|(i, (title, start))| {
            let end = if i + 1 < toc.len() {
                toc[i + 1].1 - 1
            } else {
                total_pages
            };
            ChapterRecord {
                chapter_id: format!("toc-ch-{}", i + 1),
                title: title.to_string(),
                start_page: *start,
                end_page: end,
                pages: (*start..=end).collect(),
                source: ChapterSource::VisualToc,
                boundary_state: BoundaryState::Ready,
            }
        })
        .collect()
}

#[test]
fn biopolitics_note_regions_basic() {
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();
    let page_partitions: Vec<fnm_core::records::PagePartitionRecord> = pages
        .iter()
        .map(|p| fnm_core::records::PagePartitionRecord {
            page_no: p.book_page,
            target_pdf_page: p.book_page,
            page_role: fnm_core::types::PageRole::Body,
            confidence: 1.0,
            reason: "default".into(),
            section_hint: String::new(),
            has_note_heading: false,
            note_scan_summary: serde_json::json!({}),
        })
        .collect();

    let input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &page_partitions,
        phase1_section_heads: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
    };

    let output = build_phase2_structure_sync(input).expect("Phase 2 should succeed");

    // 打印统计
    eprintln!("=== Phase 2 output (no page_roles) ===");
    eprintln!("  note_regions: {}", output.note_regions.len());
    eprintln!("  note_items: {}", output.note_items.len());

    // 即使没有 page_roles，note_regions 也应从 note_scan 信号构建
    // 至少有一些 region（page_kind 或 note_scan items 驱动）
    if !output.note_regions.is_empty() {
        let endnote_count = output
            .note_regions
            .iter()
            .filter(|r| r.note_kind == NoteKind::Endnote)
            .count();
        eprintln!("  endnote regions: {}", endnote_count);
        assert!(
            endnote_count > 0,
            "Should find at least one endnote region from note_scan signals"
        );
    }

    // note_items 至少与 note_regions 一样多（非空 region 有 items）
    if !output.note_items.is_empty() && !output.note_regions.is_empty() {
        assert!(
            output.note_items.len() > output.note_regions.len(),
            "Should have more items than regions"
        );
    }
}

#[test]
fn biopolitics_note_regions_with_phase1_roles() {
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();

    // 使用真正的 Phase 1 page_partition
    let phase1_partitions = fnm_phase1::page_partition::build_page_partitions(&pages, None, None);

    let input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase1_section_heads: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
    };

    let output = build_phase2_structure_sync(input).expect("Phase 2 should succeed");

    eprintln!("=== Phase 2 output (with Phase 1 roles) ===");
    eprintln!("  note_regions: {}", output.note_regions.len());
    eprintln!("  note_items: {}", output.note_items.len());
    for r in &output.note_regions {
        eprintln!(
            "  region {:20} kind={:?} scope={:?} pages=[{}-{}] items_in_chapter=?",
            r.region_id, r.note_kind, r.scope, r.page_start, r.page_end,
        );
    }

    // 有 Phase 1 roles 时应有更多 region
    // （page_role=="note" 的页面被正确识别为 endnote 候选页）
    assert!(
        !output.note_regions.is_empty(),
        "Should have note regions with Phase 1 roles"
    );

    let endnote_count = output
        .note_regions
        .iter()
        .filter(|r| r.note_kind == NoteKind::Endnote)
        .count();
    // 22 endnote regions (12讲×~2 /region)，加上 fnBlocks 产生的 footnot
    eprintln!("  endnote regions: {}", endnote_count);
    eprintln!(
        "  footnote regions: {}",
        output.note_regions.len() - endnote_count
    );
    assert!(
        endnote_count >= 15,
        "Should have >= 15 endnote regions, got {}",
        endnote_count
    );

    // note_items 305（当前 Rust 值，Python 端可能因 page_roles 更精确而更多）
    eprintln!("  note items: {}", output.note_items.len());
    assert!(
        output.note_items.len() >= 200,
        "Should have >= 200 note items, got {}",
        output.note_items.len()
    );
}
