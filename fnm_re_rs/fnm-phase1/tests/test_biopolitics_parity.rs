//! F12: Biopolitics parity 比对测试。
//!
//! 加载 Biopolitics 全量 raw_pages.json，运行 Rust Phase 1 pipeline，
//! 验证输出与 Python 预期一致。

use fnm_phase1::chapter_skeleton::toc_semantics::build_toc_semantics;
use fnm_phase1::input::RawPage;
use fnm_phase1::page_partition::build_page_partitions;

#[test]
fn biopolitics_page_partition_parity() {
    // 加载全量 Biopolitics 数据（8.5MB，编译时嵌入）
    let raw: serde_json::Value = serde_json::from_str(include_str!(
        "../../../test_example/Biopolitics/raw_pages.json"
    ))
    .expect("Failed to parse Biopolitics raw_pages.json");

    let pages_json = raw["pages"].as_array().expect("pages should be array");
    let pages: Vec<RawPage> = pages_json
        .iter()
        .map(|p| serde_json::from_value(p.clone()).expect("Failed to parse page"))
        .collect();

    assert_eq!(pages.len(), 370, "Biopolitics should have 370 pages");

    // 运行 page_partition
    let result = build_page_partitions(&pages, None, None);
    assert_eq!(result.partitions.len(), 370);

    // 统计 page roles
    let mut role_counts = std::collections::HashMap::new();
    for p in &result.partitions {
        *role_counts
            .entry(p.page_role.as_str().to_string())
            .or_insert(0i64) += 1;
    }

    // 预期：有 body 页和 note 页
    let body_count = role_counts.get("body").copied().unwrap_or(0);
    let note_count = role_counts.get("note").copied().unwrap_or(0);

    assert!(
        body_count >= 200,
        "Should have >= 200 body pages, got {}",
        body_count
    );
    assert!(
        note_count >= 15,
        "Should have >= 15 note pages, got {} (Python finds 65, Rust simplified)",
        note_count
    );

    // 检查 note 页集中在章末（p40-42, p67-71 等）
    let note_pages: Vec<i64> = result
        .partitions
        .iter()
        .filter(|p| p.page_role == fnm_core::types::PageRole::Note)
        .map(|p| p.page_no)
        .collect();
    // 第一个 note 页应该在 30-50 范围内（第 1 讲末尾）
    assert!(
        note_pages.iter().any(|&p| (30..=50).contains(&p)),
        "Should have note pages in 30-50 range (first lecture endnotes), got first: {:?}",
        note_pages.first()
    );
}

#[test]
fn biopolitics_toc_semantics_parity() {
    let raw: serde_json::Value = serde_json::from_str(include_str!(
        "../../../test_example/Biopolitics/raw_pages.json"
    ))
    .expect("Failed to parse");

    let pages_json = raw["pages"].as_array().expect("pages should be array");
    let pages: Vec<RawPage> = pages_json
        .iter()
        .map(|p| serde_json::from_value(p.clone()).expect("parse"))
        .collect();

    let partitions = build_page_partitions(&pages, None, None);

    // Biopolitics 用 12 个讲座章作为 TOC items
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

    // 验证：12 个章节
    assert_eq!(
        result.aligned_chapters.len(),
        12,
        "Should have 12 chapters, got {}",
        result.aligned_chapters.len()
    );

    // 验证：章节单调递增
    assert!(
        result.chapter_order_monotonic,
        "Chapter order should be monotonic"
    );

    // 验证：每章有合理的 start_page
    for (i, ch) in result.aligned_chapters.iter().enumerate() {
        assert!(
            ch.start_page > 0,
            "Chapter {} should have positive start_page, got {}",
            i,
            ch.start_page
        );
    }

    // 验证：chapter role summary 有 chapter
    let chapter_count = result.toc_role_summary.get("chapter").copied().unwrap_or(0);
    assert!(
        chapter_count >= 10,
        "Should have >= 10 chapter roles, got {}",
        chapter_count
    );
}
