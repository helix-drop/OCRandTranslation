//! ←→ note_regions.py: _promote_post_body_regions / _reclassify_post_body_fnblocks_as_endnote
//! 章后隐式尾注晋升 + post_body fnBlock 重分类。

use fnm_core::note_marker::first_notes_heading;
use fnm_core::records::{ChapterRecord, NoteRegionRecord};
use fnm_core::types::{NoteKind, RegionScope, RegionSource};
use fnm_phase1::input::RawPage;
use std::collections::{HashMap, HashSet};

/// 将最后一章之后的 chapter-scope region 提升为 book-scope。
/// ←→ Python `_promote_post_body_regions`
pub fn promote_post_body_regions(
    regions: Vec<NoteRegionRecord>,
    chapters: &[ChapterRecord],
) -> (Vec<NoteRegionRecord>, usize) {
    if chapters.is_empty() {
        return (regions, 0);
    }

    // 计算 body chapters 的 last_chapter_end_page
    let mut sorted: Vec<&ChapterRecord> = chapters.iter().collect();
    sorted.sort_by_key(|ch| ch.end_page);
    let end_pages: Vec<i64> = sorted
        .iter()
        .map(|ch| ch.end_page)
        .filter(|&p| p > 0)
        .collect();
    let cut_idx = if end_pages.len() >= 3 {
        let gaps: Vec<(i64, usize)> = end_pages
            .windows(2)
            .enumerate()
            .map(|(i, w)| (w[1] - w[0], i))
            .collect();
        let (max_gap, gap_idx) = gaps
            .iter()
            .max_by_key(|(gap, _)| *gap)
            .copied()
            .unwrap_or((0, 0));
        if max_gap > 30 {
            gap_idx + 1
        } else {
            end_pages.len()
        }
    } else {
        end_pages.len()
    };
    let body_chapters = &sorted[..cut_idx.min(sorted.len())];
    let last_chapter_end_page = body_chapters
        .iter()
        .map(|ch| ch.end_page)
        .max()
        .unwrap_or(0);

    let mut promoted = 0usize;
    let mut normalized = Vec::with_capacity(regions.len());

    for region in regions {
        if region.note_kind != NoteKind::Endnote {
            normalized.push(region);
            continue;
        }
        if region.page_start > last_chapter_end_page && region.scope != RegionScope::Book {
            promoted += 1;
            let mut r = region.clone();
            r.scope = RegionScope::Book;
            r.chapter_id = String::new();
            r.source = RegionSource::ContinuationMerge;
            normalized.push(r);
        } else {
            normalized.push(region);
        }
    }

    (normalized, promoted)
}

/// 将 post_body 章节中 fnBlocks 来源的连续编号 footnote 重分类为 endnote。
/// ←→ Python `_reclassify_post_body_fnblocks_as_endnote`
///
/// 返回值：被重分类的页号集合。下游 footnote_band 应跳过这些页面的 fnBlocks，
/// endnote_candidate 应把它们当 endnote candidate。
pub fn reclassify_post_body_fnblocks(
    chapters: &[ChapterRecord],
    page_role_by_no: &mut HashMap<i64, String>,
    page_by_no: &HashMap<i64, &RawPage>,
    post_body_titles: &HashSet<String>,
) -> HashSet<i64> {
    let mut reclassified_pages: HashSet<i64> = HashSet::new();
    if !page_role_by_no.values().any(|v| v == "note") {
        return reclassified_pages;
    }
    if post_body_titles.is_empty() {
        return reclassified_pages;
    }

    let mut post_body_chapter_ids: Vec<(String, i64)> = Vec::new();
    for ch in chapters {
        if post_body_titles.contains(&ch.title.to_lowercase()) {
            post_body_chapter_ids.push((ch.chapter_id.clone(), ch.start_page));
        }
    }
    if post_body_chapter_ids.is_empty() {
        return reclassified_pages;
    }

    for (chapter_id, chap_start) in &post_body_chapter_ids {
        let chap_end = chapters
            .iter()
            .filter(|ch| &ch.chapter_id == chapter_id)
            .map(|ch| ch.end_page)
            .max()
            .unwrap_or(*chap_start);

        // 收集 fnBlocks items per page
        let mut page_fn_items: HashMap<i64, Vec<serde_json::Value>> = HashMap::new();
        for (&pn, page) in page_by_no {
            if pn < *chap_start || pn > chap_end {
                continue;
            }
            let note_scan = match &page.note_scan {
                Some(ns) => ns,
                None => continue,
            };
            let scan_items = match note_scan.get("items").and_then(|v| v.as_array()) {
                Some(a) => a,
                None => continue,
            };
            let mut fn_items: Vec<serde_json::Value> = Vec::new();
            for item in scan_items {
                let source = item.get("source").and_then(|v| v.as_str()).unwrap_or("");
                if source != "fnBlocks" {
                    continue;
                }
                let marker = item
                    .get("marker")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim_matches(' ')
                    .trim_matches('.');
                if marker.parse::<i64>().is_ok() {
                    fn_items.push(item.clone());
                }
            }
            if !fn_items.is_empty() {
                page_fn_items.insert(pn, fn_items);
            }
        }

        if page_fn_items.is_empty() {
            continue;
        }

        // Build bands
        let mut sorted_pages: Vec<i64> = page_fn_items.keys().copied().collect();
        sorted_pages.sort_unstable();
        let mut bands: Vec<Vec<i64>> = Vec::new();
        let mut current_band: Vec<i64> = vec![sorted_pages[0]];
        for &pn in &sorted_pages[1..] {
            if pn - *current_band.last().unwrap() <= 1 {
                current_band.push(pn);
            } else {
                bands.push(current_band);
                current_band = vec![pn];
            }
        }
        bands.push(current_band);

        for band in &bands {
            if band.len() < 2 {
                continue;
            }
            // G0: band 全是 note-only pages
            let band_is_note_only = band.iter().all(|&pn| {
                page_role_by_no.get(&pn).map(|s| s.as_str()) == Some("note")
                    || page_by_no
                        .get(&pn)
                        .map(|p| !first_notes_heading(&p.markdown).is_empty())
                        .unwrap_or(false)
            });
            if !band_is_note_only {
                continue;
            }

            // G3: numeric marker items >= 3
            let all_items: Vec<i64> = band
                .iter()
                .filter_map(|pn| page_fn_items.get(pn))
                .flat_map(|items| {
                    items.iter().filter_map(|item| {
                        item.get("marker")
                            .and_then(|v| v.as_str())
                            .and_then(|m| m.trim_matches(' ').trim_matches('.').parse::<i64>().ok())
                    })
                })
                .collect();

            if all_items.len() < 3 {
                continue;
            }

            // G4: numeric markers form a continuous sequence
            let mut numbers: Vec<i64> = all_items;
            numbers.sort_unstable();
            let expected: Vec<i64> = (numbers[0]..numbers[0] + numbers.len() as i64).collect();
            if numbers != expected {
                continue;
            }

            // ←→ Python: 标记 band 内所有页为 has_reclassified_endnotes
            for &pn in band {
                reclassified_pages.insert(pn);
            }
        }
    }

    reclassified_pages
}
