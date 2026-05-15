//! ←→ note_regions.py: _is_endnote_candidate_page / _endnote_scope_for_page / _start_reason_for_page
//! endnote 候选页判定 + scope 推断 + start_reason 推断。

use fnm_core::note_marker::first_notes_heading;
use fnm_core::records::ChapterRecord;
use std::collections::HashMap;

use crate::note_regions::chapter_lookup::find_chapter_id;
use fnm_phase1::input::RawPage;

use super::illustration_list::looks_like_illustration_list_page;

fn has_endnote_scan_items(page: &RawPage) -> bool {
    page.note_scan
        .as_ref()
        .and_then(|ns| ns.get("items"))
        .and_then(|v| v.as_array())
        .map(|items| {
            items
                .iter()
                .any(|item| item.get("kind").and_then(|v| v.as_str()) == Some("endnote"))
        })
        .unwrap_or(false)
}

/// 判断页面是否为 endnote 候选页。
/// ←→ Python `_is_endnote_candidate_page`
pub fn is_endnote_candidate_page(
    page_no: i64,
    page_role_by_no: &HashMap<i64, String>,
    page_by_no: &HashMap<i64, &RawPage>,
    first_body_page: i64,
) -> bool {
    let page = match page_by_no.get(&page_no) {
        Some(p) => p,
        None => return false,
    };

    // 插图列表页 → 排除
    if looks_like_illustration_list_page(page_no, page_by_no) {
        return false;
    }

    let page_role = page_role_by_no
        .get(&page_no)
        .map(|s| s.as_str())
        .unwrap_or("");

    // page_role == "note"
    if page_role == "note" {
        if !first_notes_heading(&page.markdown).is_empty() {
            return true;
        }
        let has_items_or_kind = page
            .note_scan
            .as_ref()
            .map(|ns| {
                let has_items = ns
                    .get("items")
                    .and_then(|v| v.as_array())
                    .map(|a| !a.is_empty())
                    .unwrap_or(false);
                let has_kind = ns
                    .get("page_kind")
                    .and_then(|v| v.as_str())
                    .map(|k| !k.is_empty())
                    .unwrap_or(false);
                has_items || has_kind
            })
            .unwrap_or(false);
        return has_items_or_kind;
    }

    // front matter 且无 heading → 排除
    if first_body_page > 0 && page_no < first_body_page {
        return !first_notes_heading(&page.markdown).is_empty();
    }

    // page_role == "other"
    if page_role == "other" {
        return !first_notes_heading(&page.markdown).is_empty();
    }

    // endnote scan items
    if has_endnote_scan_items(page) {
        return true;
    }

    // endnote_collection page_kind（无独立 items 时）
    if page
        .note_scan
        .as_ref()
        .and_then(|ns| ns.get("page_kind"))
        .and_then(|v| v.as_str())
        .map(|k| k == "endnote_collection" || k == "mixed_body_endnotes")
        .unwrap_or(false)
    {
        return true;
    }

    // 有 notes heading
    !first_notes_heading(&page.markdown).is_empty()
}

/// 推断 endnote scope（chapter/book）。
/// ←→ Python `_endnote_scope_for_page`
pub fn endnote_scope_for_page(
    page_no: i64,
    chapters: &[ChapterRecord],
    last_chapter_end_page: i64,
) -> (String, String) {
    // book
    if page_no > last_chapter_end_page {
        return ("book".into(), String::new());
    }
    // chapter
    let chapter_id = find_chapter_id(page_no, chapters);
    if !chapter_id.is_empty() {
        return ("chapter".into(), chapter_id);
    }
    ("book".into(), String::new())
}

/// 推断 region start_reason。
/// ←→ Python `_start_reason_for_page`
pub fn start_reason_for_page(
    page_no: i64,
    page_role_by_no: &HashMap<i64, String>,
    page_by_no: &HashMap<i64, &RawPage>,
) -> String {
    let page = match page_by_no.get(&page_no) {
        Some(p) => p,
        None => return "candidate_page".into(),
    };

    if !first_notes_heading(&page.markdown).is_empty() {
        return "notes_heading".into();
    }
    if has_endnote_scan_items(page) {
        return "endnote_items".into();
    }
    if page_role_by_no.get(&page_no).map(|s| s.as_str()) == Some("note") {
        return "note_partition".into();
    }
    "candidate_page".into()
}
