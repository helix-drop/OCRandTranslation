//! Audit: 对比 Rust build_note_items 输出与 golden 的逐条差异。
//!
//! 输出 JSON 到 /tmp/audit_note_items/ 目录：
//! - extra_items.json: Rust 有 golden 无（按类型归类）
//! - missing_items.json: Golden 有 Rust 无（按类型归类）
//! - summary.json: 汇总计数
//!
//! 运行：cargo test -p fnm-phase2 audit_note_items -- --nocapture

use fnm_core::records::ChapterRecord;
use fnm_core::types::{BoundaryState, ChapterSource};
use fnm_phase2::build_phase2_structure_sync;
use fnm_phase2::input::{Phase2Config, Phase2Input};
use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::path::Path;

// ── 匹配 key ──────────────────────────────────────────────────

#[derive(Hash, Eq, PartialEq, Clone, Debug, Ord, PartialOrd)]
struct MatchKey {
    page_no: i64,
    note_kind: String,
    marker: String,
}

// ── Golden 结构 ───────────────────────────────────────────────

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
    heading_text: String,
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
    is_reconstructed: bool,
    note_kind: String,
}

// ── 加载工具 ──────────────────────────────────────────────────

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

fn load_golden() -> GoldenFixture {
    let raw = include_str!("fixtures/biopolitics_phase2_golden.json");
    serde_json::from_str(raw).expect("Failed to parse Phase 2 golden fixture")
}

fn build_chapters() -> Vec<ChapterRecord> {
    // 与 biopolitics_phase2_parity.rs 完全一致，确保结果可比
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

// ── 主测试 ────────────────────────────────────────────────────

#[test]
fn audit_note_items_rust_vs_golden() {
    let rust_items = run_rust_pipeline();
    let golden = load_golden();

    let rust_count = rust_items.len();
    let py_count = golden.note_items.len();
    eprintln!("=== Phase 2 note_items 审计 ===");
    eprintln!("Rust: {rust_count} items, Golden: {py_count} items, Diff: {}", {
        if rust_count >= py_count {
            format!("+{}", rust_count - py_count)
        } else {
            format!("-{}", py_count - rust_count)
        }
    });

    // 按 note_kind 分类
    let rust_by_kind = count_by_kind(&rust_items);
    let py_by_kind = count_by_kind_golden(&golden.note_items);
    for kind in ["footnote", "endnote"] {
        let r = rust_by_kind.get(kind).copied().unwrap_or(0);
        let p = py_by_kind.get(kind).copied().unwrap_or(0);
        let diff = if r >= p {
            format!("+{}", r - p)
        } else {
            format!("-{}", p - r)
        };
        eprintln!("  {kind}: Rust={r}, Golden={p}, Diff={diff}");
    }

    // 按 region 分类
    let rust_by_region = count_by_region(&rust_items);
    let py_by_region = count_by_region_golden(&golden.note_items);
    let mut all_region_ids: Vec<&str> = rust_by_region
        .keys()
        .chain(py_by_region.keys())
        .copied()
        .collect();
    all_region_ids.sort();
    all_region_ids.dedup();
    for rid in &all_region_ids {
        let r = rust_by_region.get(rid).copied().unwrap_or(0);
        let p = py_by_region.get(rid).copied().unwrap_or(0);
        if r != p {
            let diff = if r >= p {
                format!("+{}", r - p)
            } else {
                format!("-{}", p - r)
            };
            eprintln!("  {rid}: Rust={r}, Golden={p}, Diff={diff}");
        }
    }

    // 逐条匹配
    let rust_keys: HashSet<MatchKey> = rust_items
        .iter()
        .map(|item| MatchKey {
            page_no: item.page_no,
            note_kind: format!("{:?}", item.note_kind).to_lowercase(),
            marker: item.marker.clone(),
        })
        .collect();

    let py_keys: HashSet<MatchKey> = golden
        .note_items
        .iter()
        .map(|item| MatchKey {
            page_no: item.page_no,
            note_kind: item.note_kind.clone(),
            marker: item.marker.clone(),
        })
        .collect();

    let extra: Vec<&MatchKey> = {
        let mut v: Vec<&MatchKey> = rust_keys.difference(&py_keys).collect();
        v.sort();
        v
    };
    let missing: Vec<&MatchKey> = {
        let mut v: Vec<&MatchKey> = py_keys.difference(&rust_keys).collect();
        v.sort();
        v
    };

    eprintln!("共同匹配: {}", rust_keys.intersection(&py_keys).count());
    eprintln!("Extra (Rust 多): {}", extra.len());
    eprintln!("Missing (Rust 少): {}", missing.len());

    // Extra items 详情
    for key in &extra {
        let detail = find_rust_item(&rust_items, key);
        if let Some(item) = detail {
            eprintln!(
                "  EXTRA page={} kind={:?} marker={} text={:.80} region={}",
                item.page_no,
                item.note_kind,
                item.marker,
                item.text.replace('\n', " "),
                item.region_id,
            );
        }
    }

    // Missing items 详情
    for key in &missing {
        let detail = find_golden_item(&golden.note_items, key);
        if let Some(item) = detail {
            eprintln!(
                "  MISSING page={} kind={} marker={} text={:.80} region={}",
                item.page_no,
                item.note_kind,
                item.marker,
                item.text.replace('\n', " "),
                item.region_id,
            );
        }
    }

    // 输出 JSON
    let out_dir = Path::new("/tmp/audit_note_items");
    let _ = std::fs::create_dir_all(out_dir);

    let extra_list: Vec<serde_json::Value> = extra
        .iter()
        .map(|key| {
            let detail = find_rust_item(&rust_items, key);
            serde_json::json!({
                "page_no": key.page_no,
                "note_kind": key.note_kind,
                "marker": key.marker,
                "text": detail.map(|i| i.text.as_str()).unwrap_or(""),
                "region_id": detail.map(|i| i.region_id.as_str()).unwrap_or(""),
            })
        })
        .collect();
    std::fs::write(
        out_dir.join("extra_items.json"),
        serde_json::to_string_pretty(&extra_list).unwrap(),
    )
    .ok();

    let missing_list: Vec<serde_json::Value> = missing
        .iter()
        .map(|key| {
            let detail = find_golden_item(&golden.note_items, key);
            serde_json::json!({
                "page_no": key.page_no,
                "note_kind": key.note_kind,
                "marker": key.marker,
                "text": detail.map(|i| i.text.as_str()).unwrap_or(""),
                "region_id": detail.map(|i| i.region_id.as_str()).unwrap_or(""),
            })
        })
        .collect();
    std::fs::write(
        out_dir.join("missing_items.json"),
        serde_json::to_string_pretty(&missing_list).unwrap(),
    )
    .ok();

    let summary = serde_json::json!({
        "rust_count": rust_count,
        "golden_count": py_count,
        "diff": if rust_count >= py_count { rust_count - py_count } else { py_count - rust_count },
        "rust_by_kind": rust_by_kind,
        "golden_by_kind": py_by_kind,
        "extra_count": extra.len(),
        "missing_count": missing.len(),
        "matched_count": rust_keys.intersection(&py_keys).count(),
    });
    std::fs::write(
        out_dir.join("summary.json"),
        serde_json::to_string_pretty(&summary).unwrap(),
    )
    .ok();

    eprintln!("\nJSON 输出到 /tmp/audit_note_items/ 目录");
}

// ── 辅助 ──────────────────────────────────────────────────────

fn run_rust_pipeline() -> Vec<fnm_core::records::NoteItemRecord> {
    let pages = load_biopolitics_pages();
    let chapters = build_chapters();
    let phase1_partitions = fnm_phase1::page_partition::build_page_partitions(&pages, None, None);

    let input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &phase1_partitions.partitions,
        phase1_section_heads: &[],
        phase1_heading_candidates: &[],
        raw_pages: &pages,
        pdf_path: None,
        config: Phase2Config::default(),
        post_body_titles: HashSet::new(),
    };

    let output = build_phase2_structure_sync(input).expect("Phase 2 should succeed");
    output.note_items
}

fn count_by_kind(items: &[fnm_core::records::NoteItemRecord]) -> HashMap<String, usize> {
    let mut m = HashMap::new();
    for item in items {
        let kind = format!("{:?}", item.note_kind).to_lowercase();
        *m.entry(kind).or_insert(0) += 1;
    }
    m
}

fn count_by_kind_golden(items: &[GoldenItem]) -> HashMap<String, usize> {
    let mut m = HashMap::new();
    for item in items {
        *m.entry(item.note_kind.clone()).or_insert(0) += 1;
    }
    m
}

fn count_by_region(items: &[fnm_core::records::NoteItemRecord]) -> HashMap<&str, usize> {
    let mut m = HashMap::new();
    for item in items {
        *m.entry(item.region_id.as_str()).or_insert(0) += 1;
    }
    m
}

fn count_by_region_golden(items: &[GoldenItem]) -> HashMap<&str, usize> {
    let mut m = HashMap::new();
    for item in items {
        *m.entry(item.region_id.as_str()).or_insert(0) += 1;
    }
    m
}

fn find_rust_item<'a>(
    items: &'a [fnm_core::records::NoteItemRecord],
    key: &MatchKey,
) -> Option<&'a fnm_core::records::NoteItemRecord> {
    items.iter().find(|item| {
        item.page_no == key.page_no
            && format!("{:?}", item.note_kind).to_lowercase() == key.note_kind
            && item.marker == key.marker
    })
}

fn find_golden_item<'a>(items: &'a [GoldenItem], key: &MatchKey) -> Option<&'a GoldenItem> {
    items.iter().find(|item| {
        item.page_no == key.page_no && item.note_kind == key.note_kind && item.marker == key.marker
    })
}
