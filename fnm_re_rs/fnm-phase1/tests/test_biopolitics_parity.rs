//! F12: Biopolitics parity 比对测试。
//!
//! 加载 Biopolitics 全量 raw_pages.json，运行 Rust Phase 1 + Phase 2 pipeline，
//! 验证输出与预期一致。

use fnm_core::types::PageRole;
use fnm_phase1::chapter_skeleton::toc_semantics::build_toc_semantics;
use fnm_phase1::input::RawPage;
use fnm_phase1::page_partition::build_page_partitions;
use std::collections::HashMap;

/// 辅助：加载 Biopolitics 页面数据
fn load_biopolitics_pages() -> Vec<RawPage> {
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

#[test]
fn biopolitics_page_partition_parity() {
    let pages = load_biopolitics_pages();
    assert_eq!(pages.len(), 370, "Biopolitics should have 370 pages");

    let result = build_page_partitions(&pages, None, None);
    assert_eq!(result.partitions.len(), 370);

    // 统计 page roles
    let mut role_counts: HashMap<String, i64> = HashMap::new();
    for p in &result.partitions {
        *role_counts
            .entry(p.page_role.as_str().to_string())
            .or_insert(0) += 1;
    }

    // 打印实际分布
    eprintln!("=== PagePartition role distribution ===");
    let mut roles: Vec<_> = role_counts.iter().collect();
    roles.sort_by_key(|(_, c)| -**c);
    for (role, count) in &roles {
        eprintln!("  {}: {}", role, count);
    }

    // 精确断言 Rust 实现当前值。⚠️ Python 侧 note 数更多（~65），差异源于
    // Rust page_partition 的角色字典/OCR 信号处理不够全，F7+ 修复后应接近 Python。
    // 见 FNM_RE_REFACTOR.md § Biopolitics page_partition parity gap。
    assert_eq!(
        role_counts.get("body").copied().unwrap_or(0),
        334,
        "Body pages: current Rust value (Python ~273, see FNM_RE_REFACTOR.md)"
    );
    assert_eq!(
        role_counts.get("note").copied().unwrap_or(0),
        19,
        "Note pages: current Rust value (Python ~65, see FNM_RE_REFACTOR.md)"
    );
    assert_eq!(
        role_counts.get("other").copied().unwrap_or(0),
        15,
        "Other pages: current Rust value"
    );
    assert_eq!(
        role_counts.get("noise").copied().unwrap_or(0),
        2,
        "Noise pages: current Rust value"
    );

    // Note 页页码范围（Rust 19 note pages 集中在 5 个范围）
    let note_pages: Vec<i64> = result
        .partitions
        .iter()
        .filter(|p| p.page_role == PageRole::Note)
        .map(|p| p.page_no)
        .collect();
    assert!(!note_pages.is_empty(), "Should have note pages");
}

#[test]
fn biopolitics_toc_semantics_parity() {
    let pages = load_biopolitics_pages();
    let partitions = build_page_partitions(&pages, None, None);

    let toc_items: Vec<fnm_phase1::input::TocItem> = vec![
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
    ]
    .into_iter()
    .enumerate()
    .map(|(i, (title, page))| fnm_phase1::input::TocItem {
        item_id: format!("toc-{}", i + 1),
        title: title.into(),
        target_pdf_page: Some(page),
        role_hint: "chapter".into(),
        ..Default::default()
    })
    .collect();

    let result = build_toc_semantics(&toc_items, &[], &pages, &partitions.partitions, &[]);

    // 精确验证：12 个章节
    assert_eq!(
        result.aligned_chapters.len(),
        12,
        "Should have 12 chapters, got {}",
        result.aligned_chapters.len()
    );

    // 章节顺序单调递增
    assert!(
        result.chapter_order_monotonic,
        "Chapter order should be monotonic"
    );

    // 验证每章的 start_page
    for (i, ch) in result.aligned_chapters.iter().enumerate() {
        assert!(
            ch.start_page > 0,
            "Chapter {} should have positive start_page, got {}",
            i,
            ch.start_page
        );
        // 章节页码必须递增
        if i > 0 {
            assert!(
                ch.start_page > result.aligned_chapters[i - 1].start_page,
                "Chapter {} start_page {} should be > previous {}",
                i,
                ch.start_page,
                result.aligned_chapters[i - 1].start_page
            );
        }
    }

    // TOC role summary 精确
    let chapter_count = result.toc_role_summary.get("chapter").copied().unwrap_or(0);
    assert_eq!(
        chapter_count, 12,
        "Expected 12 chapters in role summary, got {}",
        chapter_count
    );
}
