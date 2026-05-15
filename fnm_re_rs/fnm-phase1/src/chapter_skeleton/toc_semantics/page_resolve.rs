//! 修剪章节起始的 front_matter/noise 页面。←→ Python `_trim_exportable_chapter_pages()`。

use crate::input::RawPage;
use fnm_core::records::PagePartitionRecord;
use fnm_core::text::{extract_page_headings, page_markdown_text};
use fnm_core::title::normalize_title;

use super::title_utils::is_toc_force_export_title;

/// 修剪章节起始的 front_matter/noise 页面。
pub fn trim_exportable_chapter_pages(
    page_numbers: &[i64],
    pages: &[RawPage],
    page_partitions: &[PagePartitionRecord],
) -> Vec<i64> {
    let page_role_by_no: std::collections::HashMap<i64, &str> = page_partitions
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str()))
        .collect();
    let total_pages = pages.len().max(1) as i64;
    let page_by_no: std::collections::HashMap<i64, &RawPage> =
        pages.iter().map(|p| (p.book_page, p)).collect();

    let mut trimmed: Vec<i64> = page_numbers.iter().copied().filter(|&p| p > 0).collect();

    while !trimmed.is_empty() {
        let page_no = trimmed[0];
        let role = page_role_by_no.get(&page_no).copied().unwrap_or("");
        let page = page_by_no.get(&page_no);

        // 将 RawPage 转为 Value 以调用 fnm-core 函数
        let page_value = page.map(|p| serde_json::to_value(p).unwrap_or_default());
        let text = page_value
            .as_ref()
            .map_or_else(String::new, page_markdown_text);
        let headings: Vec<String> = page_value
            .as_ref()
            .map_or_else(Vec::new, extract_page_headings);

        if matches!(role, "noise" | "other") {
            trimmed.remove(0);
            continue;
        }
        if role != "front_matter" {
            break;
        }
        let first_heading = normalize_title(headings.first().map_or("", |s| s.as_str()));
        if !first_heading.is_empty()
            && is_toc_force_export_title(&first_heading)
            && looks_like_prose_after_heading(&text)
        {
            break;
        }
        if looks_like_copyright_front_matter_page(&text, page_no, total_pages) {
            trimmed.remove(0);
            continue;
        }
        if looks_like_course_listing_page(&text, page_no, total_pages) {
            trimmed.remove(0);
            continue;
        }
        if looks_like_title_page(&text, &headings, page_no, total_pages) {
            trimmed.remove(0);
            continue;
        }
        if !looks_like_prose_after_heading(&text) {
            trimmed.remove(0);
            continue;
        }
        break;
    }

    if trimmed.is_empty() {
        page_numbers.iter().copied().filter(|&p| p > 0).collect()
    } else {
        trimmed
    }
}

fn looks_like_prose_after_heading(text: &str) -> bool {
    let mut found_heading = false;
    let mut prose_lines = 0;
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('#') {
            found_heading = true;
            continue;
        }
        if found_heading && !trimmed.is_empty() {
            prose_lines += 1;
            if prose_lines >= 2 {
                return true;
            }
        }
    }
    false
}

fn looks_like_copyright_front_matter_page(text: &str, _page_no: i64, _total_pages: i64) -> bool {
    let lowered = text.to_lowercase();
    lowered.contains("copyright")
        || lowered.contains("all rights reserved")
        || lowered.contains("library of congress")
        || lowered.contains("printed in")
        || lowered.contains("isbn")
        || lowered.contains("©")
        || lowered.contains("code de la propriété intellectuelle")
}

fn looks_like_course_listing_page(text: &str, _page_no: i64, _total_pages: i64) -> bool {
    let lowered = text.to_lowercase();
    lowered.contains("a dissertation")
        || lowered.contains("presented to the faculty")
        || lowered.contains("in candidacy for the degree")
        || lowered.contains("doctor of philosophy")
}

fn looks_like_title_page(
    text: &str,
    headings: &[String],
    _page_no: i64,
    _total_pages: i64,
) -> bool {
    let lines: Vec<&str> = text.lines().collect();
    let non_empty_lines: Vec<&str> = lines
        .iter()
        .filter(|l| !l.trim().is_empty())
        .copied()
        .collect();
    if non_empty_lines.len() <= 5 && !headings.is_empty() {
        let body_lines: Vec<&str> = non_empty_lines
            .iter()
            .filter(|l| !l.trim().starts_with('#'))
            .copied()
            .collect();
        if body_lines.len() <= 2 {
            return true;
        }
    }
    false
}
