use std::collections::{HashMap, HashSet};

use fnm_core::records::SectionHeadRecord;

pub fn is_exportable_section_head(head: &SectionHeadRecord) -> bool {
    !head.title.trim().is_empty()
        && !head.source.trim().is_empty()
        && head.page_no > 0
        && head.level >= 0
}

pub fn build_section_heads_by_page(
    chapter_id: &str,
    section_heads: &[SectionHeadRecord],
    chapter_pages_set: &HashSet<i64>,
) -> HashMap<i64, Vec<String>> {
    let mut payload: HashMap<i64, Vec<String>> = HashMap::new();
    for head in section_heads {
        if head.chapter_id != chapter_id {
            continue;
        }
        if !is_exportable_section_head(head) {
            continue;
        }
        if !chapter_pages_set.is_empty() && !chapter_pages_set.contains(&head.page_no) {
            continue;
        }
        let title = head.title.trim().to_string();
        if title.is_empty() {
            continue;
        }
        payload.entry(head.page_no).or_default().push(title);
    }
    for titles in payload.values_mut() {
        titles.sort();
        titles.dedup();
    }
    payload
}
