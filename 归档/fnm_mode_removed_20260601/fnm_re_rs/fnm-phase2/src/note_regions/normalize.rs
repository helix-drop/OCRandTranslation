//! ←→ note_regions.py: _normalize_region_ids
//! Region ID 规范化（按 page_start/page_end/note_kind/scope/chapter_id 排序后重新编号）。

use fnm_core::records::NoteRegionRecord;
use fnm_core::types::{NoteKind, RegionScope};

/// 规范化 region_id 为统一格式。
/// ←→ Python `_normalize_region_ids`
pub fn normalize_region_ids(mut regions: Vec<NoteRegionRecord>) -> Vec<NoteRegionRecord> {
    regions.sort_by_key(|r| {
        (
            r.page_start,
            r.page_end,
            r.note_kind.as_str().to_string(),
            r.scope.as_str().to_string(),
            r.chapter_id.clone(),
        )
    });

    let mut normalized = Vec::with_capacity(regions.len());
    for (index, region) in regions.into_iter().enumerate() {
        let note_tag = if region.note_kind == NoteKind::Footnote {
            "fn"
        } else {
            "en"
        };
        let scope_tag = if region.scope == RegionScope::Chapter {
            "ch"
        } else {
            "bk"
        };
        let chapter_tag = region.chapter_id.replace(' ', "-");

        normalized.push(NoteRegionRecord {
            region_id: format!(
                "nr-{}-{}-{:04}-{}",
                note_tag,
                scope_tag,
                index + 1,
                chapter_tag
            ),
            ..region
        });
    }

    normalized
}
