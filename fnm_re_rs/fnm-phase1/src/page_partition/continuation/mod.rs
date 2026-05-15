//! 延续性判定模块：front_matter / note / back_matter 的延续页检测。
//! ←→ page_partition.py continuation fix 函数群
//!
//! 这些函数在初始 page_role 判定后修改记录，处理跨页的延续场景。

use fnm_core::records::PagePartitionRecord;
use fnm_core::types::PageRole;

use crate::page_partition::role_heuristics::{
    is_body_entry_page, looks_like_back_matter_continuation_page,
    looks_like_note_continuation_page, seed_back_matter_family, ENDNOTES_HINT_STOP_REASONS,
};

/// 修复 endnotes_start_page 提示后的 front_matter 延续页误判。
/// ←→ Python `_apply_front_matter_continuation_fix`
pub fn apply_front_matter_continuation_fix(
    records: &mut [PagePartitionRecord],
    total_pages: i64,
    page_headings: &std::collections::HashMap<i64, Vec<String>>,
    page_texts: &std::collections::HashMap<i64, String>,
) {
    let early_limit = (20).max((total_pages as f64 * 0.08) as i64);
    let mut in_front_matter_run = false;

    for record in records.iter_mut() {
        if record.page_no <= 0 || record.page_no > early_limit {
            continue;
        }
        if record.page_role == PageRole::FrontMatter {
            in_front_matter_run = true;
            continue;
        }
        if matches!(record.page_role, PageRole::Noise | PageRole::Other) {
            continue;
        }
        let headings = page_headings
            .get(&record.page_no)
            .cloned()
            .unwrap_or_default();
        let text = page_texts.get(&record.page_no).cloned().unwrap_or_default();
        let is_body_entry =
            is_body_entry_page(&text, &headings, record.page_no, total_pages.max(1));
        if record.page_role == PageRole::Body && in_front_matter_run && !is_body_entry {
            record.page_role = PageRole::FrontMatter;
            record.confidence = record.confidence.max(0.78);
            record.reason = "front_matter_continuation".into();
            continue;
        }
        if record.page_role == PageRole::Body && is_body_entry {
            in_front_matter_run = false;
        }
    }
}

/// 将 body 或 front_matter 页修正为 note（如果看起来像 note 延续）。
/// ←→ Python `_apply_note_continuation_fix`
pub fn apply_note_continuation_fix(
    records: &mut [PagePartitionRecord],
    total_pages: i64,
    page_texts: &std::collections::HashMap<i64, String>,
) {
    for record in records.iter_mut() {
        if !matches!(record.page_role, PageRole::Body | PageRole::FrontMatter) {
            continue;
        }
        let text = page_texts.get(&record.page_no).cloned().unwrap_or_default();
        if !looks_like_note_continuation_page(&text, record.page_no, total_pages.max(1)) {
            continue;
        }
        record.page_role = PageRole::Note;
        record.confidence = record.confidence.max(0.90);
        record.reason = "note_continuation".into();
    }
}

/// 将 body/note 页修正为 other（如果看起来像 back matter 延续）。
/// ←→ Python `_apply_back_matter_continuation_fix`
pub fn apply_back_matter_continuation_fix(
    records: &mut [PagePartitionRecord],
    total_pages: i64,
    page_headings: &std::collections::HashMap<i64, Vec<String>>,
    page_texts: &std::collections::HashMap<i64, String>,
) {
    let mut active_family = String::new();
    for record in records.iter_mut() {
        let headings = page_headings
            .get(&record.page_no)
            .cloned()
            .unwrap_or_default();
        let seeded_family = seed_back_matter_family(
            record.page_role.as_str(),
            &record.reason,
            &headings,
            record.page_no,
            total_pages.max(1),
        );
        if !seeded_family.is_empty() {
            active_family = seeded_family;
            continue;
        }
        if active_family.is_empty() {
            continue;
        }
        let text = page_texts.get(&record.page_no).cloned().unwrap_or_default();
        if looks_like_back_matter_continuation_page(
            &text,
            &active_family,
            record.page_no,
            total_pages.max(1),
        ) {
            if record.page_role == PageRole::Note
                && (record.reason != "note_scan_collection" || record.has_note_heading)
            {
                continue;
            }
            record.page_role = PageRole::Other;
            record.confidence = record.confidence.max(0.93);
            record.reason = format!("{}_continuation", active_family);
            continue;
        }
        active_family.clear();
    }
}

/// 应用 endnotes_start_page 提示（与 Python 逻辑一致）。
/// ←→ Python `_apply_endnotes_start_page_hint`
pub fn apply_endnotes_start_page_hint(
    records: &mut [PagePartitionRecord],
    endnotes_start_page: Option<i64>,
) {
    let start_page = match endnotes_start_page {
        Some(sp) if sp > 0 => sp,
        _ => return,
    };
    let mut seen_note_run = false;
    let mut stopped_at_back_matter = false;

    for record in records.iter_mut() {
        if record.page_no < start_page {
            continue;
        }
        if stopped_at_back_matter {
            continue;
        }
        if record.page_role == PageRole::Note {
            seen_note_run = true;
            continue;
        }
        if seen_note_run
            && record.page_role == PageRole::Other
            && ENDNOTES_HINT_STOP_REASONS.contains(&record.reason.as_str())
        {
            stopped_at_back_matter = true;
            continue;
        }
        if matches!(
            record.page_role,
            PageRole::Body | PageRole::Other | PageRole::FrontMatter
        ) {
            record.page_role = PageRole::Note;
            record.confidence = record.confidence.max(0.90);
            record.reason = "endnotes_start_page_hint".into();
            seen_note_run = true;
        }
    }
}
