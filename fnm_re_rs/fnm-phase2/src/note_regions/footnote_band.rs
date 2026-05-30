//! ←→ note_regions.py: _build_footnote_band_regions
//! 脚注 band 区域构建。

use fnm_core::records::{ChapterRecord, NoteRegionRecord};
use fnm_core::types::{RegionScope, RegionSource};
use fnm_phase1::input::RawPage;
use std::collections::HashSet;

/// 检查页面是否有脚注信号。
/// ←→ Python `_build_footnote_band_regions` 检测逻辑
///
/// 两路信号：
/// 1. note_scan.items 有 kind=footnote（强信号，Biopolitics ~16 页）
/// 2. fnBlocks 含编号脚注文本（弱信号，须通过 numbered-marker 守卫——
///    Biopolitics 有 7 页 fnBlocks 是 OCR 误标的正文，不含脚注编号）
fn has_footnote_items(page: &RawPage) -> bool {
    let has_scan_footnote = page
        .note_scan
        .as_ref()
        .and_then(|ns| ns.get("items"))
        .and_then(|v| v.as_array())
        .map(|items| {
            items
                .iter()
                .any(|item| item.get("kind").and_then(|v| v.as_str()) == Some("footnote"))
        })
        .unwrap_or(false);

    let has_valid_fn_blocks = page
        .fn_blocks
        .as_array()
        .map(|arr| {
            arr.iter().any(|block| {
                let text = block.get("text").and_then(|v| v.as_str()).unwrap_or("");
                let trimmed = text.trim();
                if trimmed.is_empty() {
                    return false;
                }
                // 守卫：脚注以标记开头（*、数字、†、‡、§）。
                // 正文误标 fnBlock（如续行、标题）通常以字母或标点起头。
                let first = trimmed.chars().next().unwrap();
                first == '*'
                    || first == '†'
                    || first == '‡'
                    || first == '§'
                    || first.is_ascii_digit()
            })
        })
        .unwrap_or(false);

    has_scan_footnote || has_valid_fn_blocks
}

fn first_footnote_marker(page: &RawPage) -> String {
    page.note_scan
        .as_ref()
        .and_then(|ns| ns.get("items"))
        .and_then(|v| v.as_array())
        .and_then(|items| {
            items
                .iter()
                .find(|item| item.get("kind").and_then(|v| v.as_str()) == Some("footnote"))
                .and_then(|item| {
                    item.get("marker")
                        .and_then(|v| v.as_str().map(String::from))
                })
        })
        .unwrap_or_default()
}

fn split_contiguous_ranges(items: &[i64]) -> Vec<Vec<i64>> {
    if items.is_empty() {
        return vec![];
    }
    let mut sorted: Vec<i64> = items.to_vec();
    sorted.sort_unstable();
    let mut result = Vec::new();
    let mut current = vec![sorted[0]];
    for &item in &sorted[1..] {
        if item - *current.last().unwrap() <= 1 {
            current.push(item);
        } else {
            result.push(current);
            current = vec![item];
        }
    }
    result.push(current);
    result
}

/// 构建脚注 band 区域。
pub fn build_footnote_band_regions(
    chapters: &[ChapterRecord],
    pages: &[RawPage],
) -> (Vec<NoteRegionRecord>, HashSet<String>) {
    build_footnote_band_regions_excluding(chapters, pages, &HashSet::new())
}

/// 构建脚注 band 区域，排除 reclassified pages（这些 fnBlocks 被重分类为 endnote）。
/// ←→ Python `_reclassify_post_body_fnblocks_as_endnote` 调用后的下游消费
pub fn build_footnote_band_regions_excluding(
    chapters: &[ChapterRecord],
    pages: &[RawPage],
    exclude_pages: &HashSet<i64>,
) -> (Vec<NoteRegionRecord>, HashSet<String>) {
    let page_map: std::collections::HashMap<i64, &RawPage> =
        pages.iter().map(|p| (p.book_page, p)).collect();

    let mut regions: Vec<NoteRegionRecord> = Vec::new();
    let mut chapters_with_band: HashSet<String> = HashSet::new();

    for chapter in chapters {
        let footnote_pages: Vec<i64> = chapter
            .pages
            .iter()
            .filter(|&&pn| {
                pn > 0
                    && !exclude_pages.contains(&pn)
                    && page_map.get(&pn).is_some_and(|p| has_footnote_items(p))
            })
            .copied()
            .collect();

        for (run_index, run_pages) in split_contiguous_ranges(&footnote_pages)
            .into_iter()
            .enumerate()
        {
            if run_pages.is_empty() {
                continue;
            }
            let start_page = run_pages[0];
            let end_page = *run_pages.last().unwrap();
            chapters_with_band.insert(chapter.chapter_id.clone());
            let first_marker = page_map
                .get(&start_page)
                .map(|p| first_footnote_marker(p))
                .unwrap_or_default();

            regions.push(NoteRegionRecord {
                region_id: format!("{}-footband-{:02}", chapter.chapter_id, run_index + 1),
                chapter_id: chapter.chapter_id.clone(),
                page_start: start_page,
                page_end: end_page,
                pages: run_pages,
                note_kind: crate::note_kind_resolver::resolve_note_kind(
                    &crate::note_kind_resolver::NoteRegionContext {
                        heading_text: "",
                        has_footnote_band: true,
                        is_post_body_region: false,
                        is_book_scope: false,
                        scan_page_kind: "",
                    },
                )
                .note_kind,
                scope: RegionScope::Chapter,
                source: RegionSource::FootnoteBand,
                heading_text: String::new(),
                start_reason: "footnote_items".into(),
                end_reason: "contiguous_end".into(),
                region_marker_alignment_ok: true,
                region_start_first_source_marker: first_marker,
                region_first_note_item_marker: String::new(),
                review_required: false,
            });
        }
    }

    (regions, chapters_with_band)
}
