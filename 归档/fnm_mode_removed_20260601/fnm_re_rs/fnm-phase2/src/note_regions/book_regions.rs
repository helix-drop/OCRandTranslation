//! ←→ note_regions.py: _rebind_book_regions / _chapter_endnote_start_page_map
//! Book-scope region 重绑定 + endnote start page map。

use fnm_core::chapters::nearest_prior_chapter;
use fnm_core::records::{ChapterRecord, HeadingCandidate, NoteRegionRecord};
use fnm_core::types::{NoteKind, RegionScope, RegionSource};
use std::collections::{HashMap, HashSet};

/// 重绑定 book-scope 且缺少有效 chapter_id 的 region 到最近的章。
/// ←→ Python `_rebind_book_regions`
///
/// 注意：仅用 nearest_prior_chapter 兜底，不尝试 heading_candidate 匹配。
/// Python `_rebind_book_regions` 也只有这一步，heading 匹配在 endnote 跨章场景下会
/// 错误匹配下一页章的标题（如 ch-10 的尾注在 ch-11 首页 → 错误绑定到 ch-11），
/// 详见 fnm_re_rs/docs/archive/B2_note_links_parity.md。
pub fn rebind_book_regions(
    regions: Vec<NoteRegionRecord>,
    chapters: &[ChapterRecord],
    _heading_candidates: &[HeadingCandidate],
) -> (Vec<NoteRegionRecord>, usize) {
    let chapter_ids: HashSet<String> = chapters.iter().map(|ch| ch.chapter_id.clone()).collect();

    let mut normalized = Vec::with_capacity(regions.len());
    let mut rebind_count = 0usize;

    for region in regions {
        if region.note_kind != NoteKind::Endnote || region.scope != RegionScope::Book {
            normalized.push(region);
            continue;
        }

        let cid = region.chapter_id.trim();
        if !cid.is_empty() && chapter_ids.contains(cid) {
            normalized.push(region);
            continue;
        }

        // 仅用 nearest_prior_chapter 兜底（不尝试 heading_candidate 匹配——Python
        // _rebind_book_regions 也只有这一步，heading 匹配在 endnote 跨章场景下会
        // 错误匹配下一页章的标题，详见 B2 调查）。
        // ←→ Python `_rebind_book_regions` 行 566
        let rebound = {
            let prior = nearest_prior_chapter(chapters, region.page_start);
            if prior.is_empty() {
                None
            } else {
                Some(prior)
            }
        };

        if let Some(rebound) = rebound {
            if rebound.is_empty() {
                let mut r = region.clone();
                r.review_required = true;
                normalized.push(r);
            } else {
                rebind_count += 1;
                let mut r = region.clone();
                r.chapter_id = rebound;
                r.source = RegionSource::FallbackNearestPrior;
                normalized.push(r);
            }
        } else {
            let mut r = region.clone();
            r.review_required = true;
            normalized.push(r);
        }
    }

    (normalized, rebind_count)
}

/// 构建 chapter → endnote start page 映射。
/// ←→ Python `_chapter_endnote_start_page_map`
pub fn chapter_endnote_start_page_map(regions: &[NoteRegionRecord]) -> HashMap<String, i64> {
    let mut mapping: HashMap<String, i64> = HashMap::new();
    for region in regions {
        if region.note_kind != NoteKind::Endnote || region.scope != RegionScope::Chapter {
            continue;
        }
        let cid = region.chapter_id.trim().to_string();
        if cid.is_empty() {
            continue;
        }
        let start = region.page_start;
        match mapping.get(&cid) {
            Some(&existing) if start < existing => {
                mapping.insert(cid, start);
            }
            None => {
                mapping.insert(cid, start);
            }
            _ => {}
        }
    }
    mapping
}
