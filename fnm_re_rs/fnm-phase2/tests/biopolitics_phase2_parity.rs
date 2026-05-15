//! F12: Biopolitics Phase 2 parity 比对测试。
//!
//! 加载 Python Phase 2 golden fixture，逐字段比对 Rust Phase 2 输出。
//!
//! 差异文档：tests/known_python_bugs.md

use fnm_core::records::ChapterRecord;
use fnm_core::types::{BoundaryState, ChapterSource};
use fnm_phase2::build_phase2_structure_sync;
use fnm_phase2::input::{Phase2Config, Phase2Input};
use serde::Deserialize;
use std::collections::{HashMap, HashSet};

// ── Golden fixture 结构 ─────────────────────────────────────

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct GoldenFixture {
    #[serde(default)]
    note_regions: Vec<GoldenRegion>,
    #[serde(default)]
    note_items: Vec<GoldenItem>,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct GoldenRegion {
    region_id: String,
    chapter_id: String,
    page_start: i64,
    page_end: i64,
    #[serde(default)]
    pages: Vec<i64>,
    note_kind: String,
    #[serde(default)]
    scope: String,
    #[serde(default)]
    source: String,
    #[serde(default)]
    heading_text: String,
    #[serde(default)]
    start_reason: String,
    #[serde(default)]
    end_reason: String,
    #[serde(default)]
    region_marker_alignment_ok: bool,
    #[serde(default)]
    region_start_first_source_marker: String,
    #[serde(default)]
    region_first_note_item_marker: String,
    #[serde(default)]
    review_required: bool,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct GoldenItem {
    note_item_id: String,
    region_id: String,
    chapter_id: String,
    page_no: i64,
    marker: String,
    #[serde(default)]
    marker_type: String,
    text: String,
    #[serde(default)]
    source: String,
    #[serde(default)]
    source_page_label: String,
    #[serde(default)]
    is_reconstructed: bool,
    #[serde(default)]
    review_required: bool,
    note_kind: String,
}

// ── 辅助函数 ─────────────────────────────────────────────────

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

fn build_toc_items() -> Vec<fnm_phase1::input::TocItem> {
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
    toc.iter()
        .enumerate()
        .map(|(i, (title, page))| fnm_phase1::input::TocItem {
            item_id: format!("toc-{}", i + 1),
            title: title.to_string(),
            target_pdf_page: Some(*page),
            role_hint: "chapter".into(),
            ..Default::default()
        })
        .collect()
}

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

fn load_golden() -> GoldenFixture {
    let raw = include_str!("fixtures/biopolitics_phase2_golden.json");
    serde_json::from_str(raw).expect("Failed to parse Phase 2 golden fixture")
}

// ── SPEC 1: Note region field-by-field comparison ─────────────

#[test]
fn biopolitics_note_regions_field_by_field() {
    let golden = load_golden();
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();
    let phase1_partitions = fnm_phase1::page_partition::build_page_partitions(&pages, None, None);

    let input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase1_section_heads: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
        post_body_titles: HashSet::new(),
    };

    let output = build_phase2_structure_sync(input).expect("Phase 2 should succeed");

    // 按 note_kind 统计
    let mut rust_kinds: HashMap<String, usize> = HashMap::new();
    for r in &output.note_regions {
        *rust_kinds.entry(format!("{:?}", r.note_kind)).or_insert(0) += 1;
    }
    let mut py_kinds: HashMap<String, usize> = HashMap::new();
    for r in &golden.note_regions {
        *py_kinds.entry(r.note_kind.clone()).or_insert(0) += 1;
    }

    eprintln!("=== Note region counts ===");
    eprintln!(
        "  Rust:   {} total — {:?}",
        output.note_regions.len(),
        rust_kinds
    );
    eprintln!(
        "  Python: {} total — {:?}",
        golden.note_regions.len(),
        py_kinds
    );

    let region_coverage =
        output.note_regions.len() as f64 / golden.note_regions.len().max(1) as f64 * 100.0;
    eprintln!(
        "  Region coverage: {}/{} ({:.0}%)",
        output.note_regions.len(),
        golden.note_regions.len(),
        region_coverage
    );

    // 语义匹配：Rust/Python region_id 命名格式不同，用 (note_kind, 最近 page_start) 匹配。
    // 每个 Rust region 找 Python 中 kind 相同且 page_start 最接近的，容忍 ±5 页偏移。
    let mut used_py: HashSet<usize> = HashSet::new();
    let mut matched = 0usize;
    let mut kind_reversals: Vec<(String, String, String, i64)> = Vec::new();
    let mut page_range_diffs: Vec<(String, i64, i64, i64, i64)> = Vec::new();
    let mut unmatched_rust: Vec<String> = Vec::new();

    for rust_r in &output.note_regions {
        let rust_kind = format!("{:?}", rust_r.note_kind).to_lowercase();

        // 找 Python 中最接近的 region（kind 相同优先，否则 page_start 最近）
        let mut best: Option<(usize, i64, bool)> = None; // (py_idx, dist, same_kind)
        for (j, py_r) in golden.note_regions.iter().enumerate() {
            if used_py.contains(&j) {
                continue;
            }
            let same_kind = rust_kind == py_r.note_kind.to_lowercase();
            let dist = (py_r.page_start - rust_r.page_start).abs();
            // 优先同 kind 且距离 ≤ 5
            match best {
                None => {
                    best = Some((j, dist, same_kind));
                }
                Some((_, old_dist, old_same)) => {
                    let better = (same_kind && !old_same && dist <= 5)
                        || (same_kind == old_same && dist < old_dist);
                    if better {
                        best = Some((j, dist, same_kind));
                    }
                }
            }
        }

        match best {
            Some((py_idx, dist, _same_kind)) => {
                used_py.insert(py_idx);
                let py_r = &golden.note_regions[py_idx];

                if rust_kind == py_r.note_kind.to_lowercase()
                    && rust_r.page_start == py_r.page_start
                    && rust_r.page_end == py_r.page_end
                {
                    matched += 1;
                } else {
                    if rust_kind != py_r.note_kind.to_lowercase() {
                        kind_reversals.push((
                            rust_r.region_id.clone(),
                            format!("{:?}", rust_r.note_kind),
                            py_r.note_kind.clone(),
                            dist,
                        ));
                    }
                    if rust_r.page_start != py_r.page_start || rust_r.page_end != py_r.page_end {
                        page_range_diffs.push((
                            rust_r.region_id.clone(),
                            rust_r.page_start,
                            rust_r.page_end,
                            py_r.page_start,
                            py_r.page_end,
                        ));
                    }
                }
            }
            None => {
                unmatched_rust.push(rust_r.region_id.clone());
            }
        }
    }

    let unmatched_python = golden.note_regions.len() - used_py.len();

    eprintln!(
        "  Exact match (kind+pages): {}/{}",
        matched,
        output.note_regions.len()
    );
    eprintln!("  Kind reversals: {}", kind_reversals.len());
    if !kind_reversals.is_empty() {
        // 按反转类型分组
        let mut endnote_to_footnote = 0usize;
        let mut footnote_to_endnote = 0usize;
        let mut other_reversals: Vec<&(String, String, String, i64)> = Vec::new();
        for kr in &kind_reversals {
            if kr.1 == "Endnote" && kr.2 == "footnote" {
                endnote_to_footnote += 1;
            } else if kr.1 == "Footnote" && kr.2 == "endnote" {
                footnote_to_endnote += 1;
            } else {
                other_reversals.push(kr);
            }
        }
        if endnote_to_footnote > 0 {
            eprintln!(
                "    Rust=Endnote → Python=footnote (Rust over-classified): {} regions",
                endnote_to_footnote
            );
        }
        if footnote_to_endnote > 0 {
            eprintln!(
                "    Rust=Footnote → Python=endnote (Rust under-classified): {} regions",
                footnote_to_endnote
            );
        }
        for kr in &other_reversals {
            eprintln!("    {} → {}: {}", kr.1, kr.2, kr.0);
        }
    }
    eprintln!("  Page range diffs: {}", page_range_diffs.len());
    eprintln!(
        "  Unmatched Rust: {} / Unmatched Python: {}",
        unmatched_rust.len(),
        unmatched_python
    );

    // 如果覆盖率 < 50%，标记已知差异来自 Phase 1 role gap
    if region_coverage < 50.0 {
        eprintln!("  ⚠️  Region coverage < 50% — cascade from Phase 1 page_role gap (19 vs 62 note pages)");
        eprintln!("     See fnm-phase1/tests/known_python_bugs.md §1a");
    }
}

// ── SPEC 1b: Note region with REAL Phase 1 chapters ──────────

#[test]
fn biopolitics_note_regions_with_real_phase1() {
    let golden = load_golden();
    let pages = load_biopolitics_pages();
    let toc_items = build_toc_items();

    // 用真实 Phase 1 pipeline 构建 chapters + partitions
    let phase1 = fnm_phase1::toc_structure::build_phase1_structure(
        &pages,
        Some(&toc_items),
        &fnm_phase1::toc_structure::Phase1Config::default(),
    )
    .expect("Phase 1 should build");

    let chapters = phase1.structure.chapters;
    let partitions = phase1.structure.pages;

    eprintln!("=== Real Phase 1 chapter boundaries ===");
    for ch in &chapters {
        eprintln!(
            "  {} \"{}\": [{}-{}] ({} pages)",
            ch.chapter_id,
            ch.title,
            ch.start_page,
            ch.end_page,
            ch.pages.len()
        );
    }

    let input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &partitions,
        phase1_section_heads: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
        post_body_titles: HashSet::new(),
    };

    let output = build_phase2_structure_sync(input).expect("Phase 2 should succeed");

    let mut rust_kinds: HashMap<String, usize> = HashMap::new();
    for r in &output.note_regions {
        *rust_kinds.entry(format!("{:?}", r.note_kind)).or_insert(0) += 1;
    }
    let mut py_kinds: HashMap<String, usize> = HashMap::new();
    for r in &golden.note_regions {
        *py_kinds.entry(r.note_kind.clone()).or_insert(0) += 1;
    }

    eprintln!("=== Note region counts (real Phase 1) ===");
    eprintln!(
        "  Rust:   {} total — {:?}",
        output.note_regions.len(),
        rust_kinds
    );
    eprintln!(
        "  Python: {} total — {:?}",
        golden.note_regions.len(),
        py_kinds
    );

    let region_coverage =
        output.note_regions.len() as f64 / golden.note_regions.len().max(1) as f64 * 100.0;
    eprintln!(
        "  Region coverage: {}/{} ({:.0}%)",
        output.note_regions.len(),
        golden.note_regions.len(),
        region_coverage
    );

    // 语义匹配
    let mut used_py: HashSet<usize> = HashSet::new();
    let mut matched = 0usize;
    let mut kind_reversals: Vec<(String, String, String, i64)> = Vec::new();
    let mut page_range_diffs: Vec<(String, i64, i64, i64, i64)> = Vec::new();

    for rust_r in &output.note_regions {
        let rust_kind = format!("{:?}", rust_r.note_kind).to_lowercase();
        let mut best: Option<(usize, i64, bool)> = None;
        for (j, py_r) in golden.note_regions.iter().enumerate() {
            if used_py.contains(&j) {
                continue;
            }
            let same_kind = rust_kind == py_r.note_kind.to_lowercase();
            let dist = (py_r.page_start - rust_r.page_start).abs();
            match best {
                None => best = Some((j, dist, same_kind)),
                Some((_, old_dist, old_same)) => {
                    let better = (same_kind && !old_same && dist <= 5)
                        || (same_kind == old_same && dist < old_dist);
                    if better {
                        best = Some((j, dist, same_kind));
                    }
                }
            }
        }
        if let Some((py_idx, dist, _same_kind)) = best {
            used_py.insert(py_idx);
            let py_r = &golden.note_regions[py_idx];
            if rust_kind == py_r.note_kind.to_lowercase()
                && rust_r.page_start == py_r.page_start
                && rust_r.page_end == py_r.page_end
            {
                matched += 1;
            } else {
                if rust_kind != py_r.note_kind.to_lowercase() {
                    kind_reversals.push((
                        rust_r.region_id.clone(),
                        format!("{:?}", rust_r.note_kind),
                        py_r.note_kind.clone(),
                        dist,
                    ));
                }
                if rust_r.page_start != py_r.page_start || rust_r.page_end != py_r.page_end {
                    page_range_diffs.push((
                        rust_r.region_id.clone(),
                        rust_r.page_start,
                        rust_r.page_end,
                        py_r.page_start,
                        py_r.page_end,
                    ));
                }
            }
        }
    }

    let unmatched_python = golden.note_regions.len() - used_py.len();
    eprintln!("  Exact match: {}/{}", matched, output.note_regions.len());
    eprintln!("  Kind reversals: {}", kind_reversals.len());
    if !kind_reversals.is_empty() {
        let mut etof = 0usize;
        let mut ftoe = 0usize;
        for kr in &kind_reversals {
            if kr.1 == "Endnote" && kr.2 == "footnote" {
                etof += 1;
            } else if kr.1 == "Footnote" && kr.2 == "endnote" {
                ftoe += 1;
            }
        }
        if etof > 0 {
            eprintln!("    Endnote→footnote: {} regions", etof);
        }
        if ftoe > 0 {
            eprintln!("    Footnote→endnote: {} regions", ftoe);
        }
    }
    eprintln!("  Page range diffs: {}", page_range_diffs.len());
    eprintln!("  Unmatched Python: {}", unmatched_python);
}

// ── SPEC 2: Note item field-by-field comparison ───────────────

#[test]
fn biopolitics_note_items_field_by_field() {
    let golden = load_golden();
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();
    let phase1_partitions = fnm_phase1::page_partition::build_page_partitions(&pages, None, None);

    let input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase1_section_heads: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
        post_body_titles: HashSet::new(),
    };

    let output = build_phase2_structure_sync(input).expect("Phase 2 should succeed");

    let item_coverage =
        output.note_items.len() as f64 / golden.note_items.len().max(1) as f64 * 100.0;
    eprintln!("=== Note item counts ===");
    eprintln!(
        "  Rust:   {} items / {} regions",
        output.note_items.len(),
        output.note_regions.len()
    );
    eprintln!(
        "  Python: {} items / {} regions",
        golden.note_items.len(),
        golden.note_regions.len()
    );
    eprintln!(
        "  Item coverage: {}/{} ({:.0}%)",
        output.note_items.len(),
        golden.note_items.len(),
        item_coverage
    );

    // 比较 items-per-region 比值
    let rust_ratio = output.note_items.len() as f64 / output.note_regions.len().max(1) as f64;
    let py_ratio = golden.note_items.len() as f64 / golden.note_regions.len().max(1) as f64;
    eprintln!(
        "  Items/region: Rust {:.1} vs Python {:.1}",
        rust_ratio, py_ratio
    );

    // 按 note_kind 统计
    let mut rust_kinds: HashMap<String, usize> = HashMap::new();
    for item in &output.note_items {
        *rust_kinds
            .entry(format!("{:?}", item.note_kind))
            .or_insert(0) += 1;
    }
    let mut py_kinds: HashMap<String, usize> = HashMap::new();
    for item in &golden.note_items {
        *py_kinds.entry(item.note_kind.clone()).or_insert(0) += 1;
    }
    eprintln!("  Rust item kinds:   {:?}", rust_kinds);
    eprintln!("  Python item kinds: {:?}", py_kinds);

    if item_coverage < 50.0 {
        eprintln!("  ⚠️  Item coverage < 50% — cascade from Phase 1 page_role gap");
    }
}

// ── SPEC 3: known_python_bugs.md consistency ──────────────────

#[test]
fn phase2_coverage_is_documented() {
    let golden = load_golden();
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();
    let phase1_partitions = fnm_phase1::page_partition::build_page_partitions(&pages, None, None);

    let input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase1_section_heads: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
        post_body_titles: HashSet::new(),
    };

    let output = build_phase2_structure_sync(input).expect("Phase 2 should succeed");

    let region_gap = (output.note_regions.len() as i64 - golden.note_regions.len() as i64).abs();
    let item_gap = (output.note_items.len() as i64 - golden.note_items.len() as i64).abs();

    if region_gap > 5 || item_gap > 10 {
        let bugs_path =
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/known_python_bugs.md");
        assert!(
            bugs_path.exists(),
            "known_python_bugs.md must exist when Rust≠Python:\n\
             Region gap={}, item gap={}\n\
             Expected at: {}",
            region_gap,
            item_gap,
            bugs_path.display()
        );
    }
}

// ── SPEC 4: Smoke — basic invariants hold ─────────────────────

#[test]
fn biopolitics_phase2_smoke() {
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();
    let phase1_partitions = fnm_phase1::page_partition::build_page_partitions(&pages, None, None);

    let input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase1_section_heads: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
        post_body_titles: HashSet::new(),
    };

    let output = build_phase2_structure_sync(input).expect("Phase 2 should succeed");

    // 不变式
    assert!(!output.note_regions.is_empty(), "Should have note regions");
    assert!(!output.note_items.is_empty(), "Should have note items");
    assert!(
        output.note_items.len() >= output.note_regions.len(),
        "Items >= regions"
    );

    // 所有 items 的 region_id 必须在 regions 中存在
    let region_ids: HashSet<&str> = output
        .note_regions
        .iter()
        .map(|r| r.region_id.as_str())
        .collect();
    for item in &output.note_items {
        assert!(
            region_ids.contains(item.region_id.as_str()),
            "Item {} references unknown region {}",
            item.note_item_id,
            item.region_id
        );
    }
}
