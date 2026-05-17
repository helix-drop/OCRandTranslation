//! F13: Biopolitics Phase 3 parity 比对测试框架。
//!
//! 注：当前为占位框架——golden fixture 需从 Python `build_note_link_table` 生成。
//! 待 `tools/gen_biopolitics_phase3_golden.py` 产出 golden 后补充逐字段断言。

use fnm_core::records::ChapterRecord;
use fnm_core::types::{BoundaryState, ChapterSource};
use fnm_phase2::input::{Phase2Config, Phase2Input};
use serde::Deserialize;
use std::collections::{HashMap, HashSet};

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
                // Python 端 chapter_id 命名约定：`toc-{item_id}`，而 item_id 已是
                // `toc-ch-N`——双 toc 前缀（见 known_python_bugs §7 chapter_id 命名）。
                chapter_id: format!("toc-toc-ch-{}", i + 1),
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

// ── SPEC: Phase 3 smoke ─────────────────────────────────────────

#[test]
fn biopolitics_phase3_smoke() {
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();
    let phase1_partitions = fnm_phase1::page_partition::build_page_partitions(&pages, None, None);

    let input = fnm_phase3::input::Phase3Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase2_note_regions: &[],
        phase2_note_items: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: fnm_phase3::input::Phase3Config::default(),
        overrides: None,
    };

    let output = fnm_phase3::build_phase3_structure(input).expect("Phase 3 should build");

    // 不变式
    assert!(
        !output.structure.body_anchors.is_empty() || output.structure.note_links.is_empty(),
        "Phase 3 produced empty anchors and links — need Phase 2 upstream data"
    );
}

// ── SPEC 4: Biopolitics contract v2 def/anchor mismatch ────────
// 注：需要真实 Phase 2 数据（note_regions + note_items）才能运行。
// 当前 Phase 2 产物未直接传入 Phase 3，需从 DB 或 golden fixture 加载。

#[test]
#[ignore = "Phase 2 cascade (note_item over-extraction: 619 vs 584), see known_python_bugs.md §7"]
fn spec_biopolitics_contract_v2_def_anchor_mismatch() {
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();

    // 先用 Phase 2 生成 upstream 数据
    let phase1_partitions = fnm_phase1::page_partition::build_page_partitions(&pages, None, None);
    let phase2_input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase1_section_heads: &[],
        phase1_heading_candidates: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
        post_body_titles: HashSet::new(),
    };
    let phase2_output =
        fnm_phase2::build_phase2_structure_sync(phase2_input).expect("Phase 2 should build");

    let input = fnm_phase3::input::Phase3Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase2_note_regions: &phase2_output.note_regions,
        phase2_note_items: &phase2_output.note_items,
        raw_pages: &pages,
        pdf_path: None,
        config: fnm_phase3::input::Phase3Config::default(),
        overrides: None,
    };

    let output = fnm_phase3::build_phase3_structure(input).expect("Phase 3 should build");

    // 断言：contract_v2_def_anchor_mismatch_count == 0
    // 需要统计每章的 endnote marker 去重数 vs anchor 去重数
    let mut chapter_def_markers: std::collections::HashMap<
        String,
        std::collections::HashSet<String>,
    > = std::collections::HashMap::new();
    for item in &phase2_output.note_items {
        if item.note_kind.as_str() == "endnote" {
            chapter_def_markers
                .entry(item.chapter_id.clone())
                .or_default()
                .insert(item.marker.clone());
        }
    }

    let mut chapter_anchor_markers: std::collections::HashMap<
        String,
        std::collections::HashSet<String>,
    > = std::collections::HashMap::new();
    for anchor in &output.structure.body_anchors {
        if anchor.anchor_kind.as_str() == "endnote" {
            chapter_anchor_markers
                .entry(anchor.chapter_id.clone())
                .or_default()
                .insert(anchor.normalized_marker.clone());
        }
    }

    let mut mismatch_total: i64 = 0;
    for (chapter_id, def_set) in &chapter_def_markers {
        let anchor_set = chapter_anchor_markers
            .get(chapter_id)
            .map(|s| s.len())
            .unwrap_or(0);
        let diff = (def_set.len() as i64 - anchor_set as i64).abs();
        if diff > 0 {
            mismatch_total += diff;
        }
    }

    assert_eq!(
        mismatch_total, 0,
        "Biopolitics contract_v2: endnote def count should equal anchor count per chapter"
    );
}

// ── Golden fixture ─────────────────────────────────────────────

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct Phase3GoldenFixture {
    body_anchors: Vec<GoldenAnchor>,
    note_links: Vec<GoldenLink>,
    effective_links: Vec<GoldenLink>,
    chapter_link_contracts: Vec<GoldenContract>,
    #[serde(default)]
    anchor_summary: serde_json::Value,
    #[serde(default)]
    link_summary: serde_json::Value,
    #[serde(default)]
    evidence: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct GoldenAnchor {
    anchor_id: String,
    chapter_id: String,
    page_no: i64,
    #[serde(default)]
    paragraph_index: i64,
    #[serde(default)]
    char_start: i64,
    #[serde(default)]
    char_end: i64,
    source_marker: String,
    normalized_marker: String,
    anchor_kind: String,
    #[serde(default)]
    certainty: f64,
    #[serde(default)]
    source_text: String,
    #[serde(default)]
    source: String,
    #[serde(default)]
    synthetic: bool,
    #[serde(default)]
    ocr_repaired_from_marker: String,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct GoldenLink {
    link_id: String,
    chapter_id: String,
    #[serde(default)]
    region_id: String,
    note_item_id: String,
    anchor_id: String,
    status: String,
    resolver: String,
    #[serde(default)]
    confidence: f64,
    note_kind: String,
    marker: String,
    #[serde(default)]
    page_no_start: i64,
    #[serde(default)]
    page_no_end: i64,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct GoldenContract {
    chapter_id: String,
    #[serde(default)]
    requires_endnote_contract: bool,
    #[serde(default)]
    first_marker_is_one: bool,
    #[serde(default)]
    endnotes_all_matched: bool,
    #[serde(default)]
    no_ambiguous_left: bool,
    #[serde(default)]
    has_marker_gap: bool,
    #[serde(default)]
    def_anchor_mismatch: bool,
    #[serde(default)]
    def_count: i64,
    #[serde(default)]
    anchor_total: i64,
}

fn load_phase3_golden() -> Phase3GoldenFixture {
    let raw = include_str!("fixtures/biopolitics_phase3_golden.json");
    serde_json::from_str(raw).expect("Failed to parse Phase 3 golden fixture")
}

fn run_biopolitics_phase3_with_phase2() -> fnm_phase3::output::Phase3Output {
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();
    let phase1_partitions = fnm_phase1::page_partition::build_page_partitions(&pages, None, None);
    let phase2_input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase1_section_heads: &[],
        phase1_heading_candidates: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
        post_body_titles: HashSet::new(),
    };
    let phase2_output =
        fnm_phase2::build_phase2_structure_sync(phase2_input).expect("Phase 2 should build");
    let phase3_input = fnm_phase3::input::Phase3Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase2_note_regions: &phase2_output.note_regions,
        phase2_note_items: &phase2_output.note_items,
        raw_pages: &pages,
        pdf_path: None,
        config: fnm_phase3::input::Phase3Config::default(),
        overrides: None,
    };
    fnm_phase3::build_phase3_structure(phase3_input).expect("Phase 3 should build")
}

// ── 严格 parity（暂 #[ignore]：等 Phase 2 cascade 修复后启用） ───
//
// 当前 Phase 2 note_items over-extraction（Rust 619 vs Python 584，详见
// known_python_bugs.md §7）会让 Phase 3 多产 ~123 个 body_anchor。
// 在上游修复前，byte-equal 跑不通，但断言本身必须是 byte-equal——
// 不允许用 coverage 阈值或 eprintln 掩盖（AGENTS.md 铁律 §7）。
//
// 修复 Phase 2 cascade 后，直接 `cargo test ... -- --ignored` 验真。

const PHASE2_CASCADE_IGNORE: &str =
    "Phase 2 note_item over-extraction (619 vs 584) propagates to Phase 3; \
     see known_python_bugs.md §7. Run with --ignored after Phase 2 fix.";

// ── SPEC: Body anchor field-by-field parity ────────────────────

#[test]
#[ignore = "Phase 2 cascade — see known_python_bugs.md §7"]
fn biopolitics_phase3_body_anchors_parity() {
    let _ = PHASE2_CASCADE_IGNORE;
    let golden = load_phase3_golden();
    let output = run_biopolitics_phase3_with_phase2();
    let rust_anchors = &output.structure.body_anchors;

    assert_eq!(
        rust_anchors.len(),
        golden.body_anchors.len(),
        "body_anchor count mismatch: rust={} python={}",
        rust_anchors.len(),
        golden.body_anchors.len()
    );
    for (i, (rust, gold)) in rust_anchors
        .iter()
        .zip(golden.body_anchors.iter())
        .enumerate()
    {
        assert_eq!(rust.anchor_id, gold.anchor_id, "anchor[{i}].anchor_id");
        assert_eq!(rust.chapter_id, gold.chapter_id, "anchor[{i}].chapter_id");
        assert_eq!(rust.page_no, gold.page_no, "anchor[{i}].page_no");
        assert_eq!(
            rust.paragraph_index, gold.paragraph_index,
            "anchor[{i}].paragraph_index"
        );
        assert_eq!(rust.char_start, gold.char_start, "anchor[{i}].char_start");
        assert_eq!(rust.char_end, gold.char_end, "anchor[{i}].char_end");
        assert_eq!(
            rust.source_marker, gold.source_marker,
            "anchor[{i}].source_marker"
        );
        assert_eq!(
            rust.normalized_marker, gold.normalized_marker,
            "anchor[{i}].normalized_marker"
        );
        assert_eq!(
            rust.anchor_kind.as_str(),
            gold.anchor_kind,
            "anchor[{i}].anchor_kind"
        );
        assert!(
            (rust.certainty - gold.certainty).abs() < 1e-9,
            "anchor[{i}].certainty: rust={} python={}",
            rust.certainty,
            gold.certainty
        );
        assert_eq!(rust.synthetic, gold.synthetic, "anchor[{i}].synthetic");
        assert_eq!(
            rust.ocr_repaired_from_marker, gold.ocr_repaired_from_marker,
            "anchor[{i}].ocr_repaired_from_marker"
        );
    }
}

// ── SPEC: Note link field-by-field parity ──────────────────────

#[test]
#[ignore = "Phase 2 cascade — see known_python_bugs.md §7"]
fn biopolitics_phase3_note_links_parity() {
    let golden = load_phase3_golden();
    let output = run_biopolitics_phase3_with_phase2();
    let rust_links = &output.structure.note_links;

    assert_eq!(
        rust_links.len(),
        golden.note_links.len(),
        "note_link count mismatch: rust={} python={}",
        rust_links.len(),
        golden.note_links.len()
    );
    for (i, (rust, gold)) in rust_links.iter().zip(golden.note_links.iter()).enumerate() {
        assert_eq!(rust.link_id, gold.link_id, "link[{i}].link_id");
        assert_eq!(rust.chapter_id, gold.chapter_id, "link[{i}].chapter_id");
        assert_eq!(rust.region_id, gold.region_id, "link[{i}].region_id");
        assert_eq!(
            rust.note_item_id, gold.note_item_id,
            "link[{i}].note_item_id"
        );
        assert_eq!(rust.anchor_id, gold.anchor_id, "link[{i}].anchor_id");
        assert_eq!(rust.status.as_str(), gold.status, "link[{i}].status");
        assert_eq!(rust.resolver.as_str(), gold.resolver, "link[{i}].resolver");
        assert_eq!(
            rust.note_kind.as_str(),
            gold.note_kind,
            "link[{i}].note_kind"
        );
        assert_eq!(rust.marker, gold.marker, "link[{i}].marker");
        assert_eq!(
            rust.page_no_start, gold.page_no_start,
            "link[{i}].page_no_start"
        );
        assert_eq!(rust.page_no_end, gold.page_no_end, "link[{i}].page_no_end");
    }
}

// ── SPEC: Chapter link contract parity ─────────────────────────

#[test]
#[ignore = "Phase 2 cascade — see known_python_bugs.md §7"]
fn biopolitics_phase3_chapter_contracts_parity() {
    let golden = load_phase3_golden();
    let output = run_biopolitics_phase3_with_phase2();
    let rust_contracts = &output.note_link_table.chapter_link_contracts;

    assert_eq!(
        rust_contracts.len(),
        golden.chapter_link_contracts.len(),
        "contract count mismatch"
    );
    for (i, (rust, gold)) in rust_contracts
        .iter()
        .zip(golden.chapter_link_contracts.iter())
        .enumerate()
    {
        assert_eq!(rust.chapter_id, gold.chapter_id, "contract[{i}].chapter_id");
        assert_eq!(
            rust.requires_endnote_contract, gold.requires_endnote_contract,
            "contract[{i}].requires_endnote_contract"
        );
        assert_eq!(
            rust.first_marker_is_one, gold.first_marker_is_one,
            "contract[{i}].first_marker_is_one"
        );
        assert_eq!(
            rust.endnotes_all_matched, gold.endnotes_all_matched,
            "contract[{i}].endnotes_all_matched"
        );
        assert_eq!(
            rust.no_ambiguous_left, gold.no_ambiguous_left,
            "contract[{i}].no_ambiguous_left"
        );
        assert_eq!(
            rust.has_marker_gap, gold.has_marker_gap,
            "contract[{i}].has_marker_gap"
        );
        assert_eq!(
            rust.def_anchor_mismatch, gold.def_anchor_mismatch,
            "contract[{i}].def_anchor_mismatch"
        );
        assert_eq!(rust.def_count, gold.def_count, "contract[{i}].def_count");
        assert_eq!(
            rust.anchor_total, gold.anchor_total,
            "contract[{i}].anchor_total"
        );
    }
}

// ── SPEC: Phase 3 summary parity (anchor_summary key fields) ──

#[test]
#[ignore = "Phase 2 cascade — see known_python_bugs.md §7"]
fn biopolitics_phase3_summary_parity() {
    let golden = load_phase3_golden();
    let output = run_biopolitics_phase3_with_phase2();

    let rust_summary = output
        .evidence
        .get("anchor_summary")
        .expect("anchor_summary missing from evidence");
    let gold_summary = &golden.anchor_summary;

    let rust_total = rust_summary
        .get("total_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(-1);
    let gold_total = gold_summary
        .get("total_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(-2);
    assert_eq!(rust_total, gold_total, "anchor_summary.total_count");

    let rust_synth = rust_summary
        .get("synthetic_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(-1);
    let gold_synth = gold_summary
        .get("synthetic_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(-2);
    assert_eq!(rust_synth, gold_synth, "anchor_summary.synthetic_count");

    let rust_ocr = rust_summary
        .get("ocr_repaired_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(-1);
    let gold_ocr = gold_summary
        .get("ocr_repaired_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(-2);
    assert_eq!(rust_ocr, gold_ocr, "anchor_summary.ocr_repaired_count");
}

// ── Shape smoke（始终启用）─────────────────────────────────────
//
// 不是 parity，仅作 sanity check：确认 Phase 3 不会输出空或爆炸数量。
// 阈值故意放宽：±50%，因为 Phase 2 cascade 当前会让 Rust 多 18% 左右。
// **不要**把这个测试改名带 "parity"——它不是 parity，是 shape。

#[test]
fn biopolitics_phase3_count_shape_smoke() {
    let golden = load_phase3_golden();
    let output = run_biopolitics_phase3_with_phase2();
    let rust_anchors = output.structure.body_anchors.len();
    let rust_links = output.structure.note_links.len();
    let gold_anchors = golden.body_anchors.len();
    let gold_links = golden.note_links.len();

    eprintln!(
        "shape: anchors rust={rust_anchors} python={gold_anchors} ({:.0}%), \
         links rust={rust_links} python={gold_links} ({:.0}%)",
        rust_anchors as f64 / gold_anchors.max(1) as f64 * 100.0,
        rust_links as f64 / gold_links.max(1) as f64 * 100.0,
    );

    assert!(rust_anchors > 0, "Phase 3 produced 0 body_anchors");
    assert!(rust_links > 0, "Phase 3 produced 0 note_links");
    let anchor_ratio = rust_anchors as f64 / gold_anchors.max(1) as f64;
    let link_ratio = rust_links as f64 / gold_links.max(1) as f64;
    assert!(
        (0.5..=1.5).contains(&anchor_ratio),
        "body_anchor count ratio {anchor_ratio:.2} outside sanity window (0.5..1.5)"
    );
    assert!(
        (0.5..=1.5).contains(&link_ratio),
        "note_link count ratio {link_ratio:.2} outside sanity window (0.5..1.5)"
    );
}
