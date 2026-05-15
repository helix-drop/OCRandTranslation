//! TOC item ↔ heading fuzzy 对齐。

use crate::chapter_skeleton::toc_semantics::{TOC_BODY_ANCHOR_TITLE_RE, TOC_PART_TITLE_RE};
use fnm_core::records::ChapterRecord;
use fnm_core::title::chapter_title_match_key;
use std::collections::HashMap;

/// 用 chapter_title_match_key 做 TOC ↔ chapter 对齐。
pub fn align_toc_to_chapters(
    toc_titles: &[String],
    chapters: &[ChapterRecord],
) -> HashMap<usize, String> {
    let mut result = HashMap::new();
    let chapter_keys: Vec<(String, &ChapterRecord)> = chapters
        .iter()
        .map(|ch| (chapter_title_match_key(&ch.title), ch))
        .collect();

    for (i, toc_title) in toc_titles.iter().enumerate() {
        let key = chapter_title_match_key(toc_title);
        for (ch_key, ch) in &chapter_keys {
            if key == *ch_key {
                result.insert(i, ch.chapter_id.clone());
                break;
            }
        }
    }
    result
}

/// 判断 TOC item 是否是 body anchor（章节起始点）。
pub fn is_body_anchor_title(title: &str) -> bool {
    TOC_BODY_ANCHOR_TITLE_RE.is_match(title)
}

/// 判断 TOC item 是否是 part/container（Part I / Book II 等）。
pub fn is_part_title(title: &str) -> bool {
    TOC_PART_TITLE_RE.is_match(title)
}
