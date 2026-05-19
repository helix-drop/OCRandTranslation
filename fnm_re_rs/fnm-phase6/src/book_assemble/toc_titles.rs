//! ←→ FNM_RE/modules/book_assemble.py
//! 翻译的函数：
//!   toc_titles_and_summary  ←→ _toc_titles_and_summary (book_assemble.py:47)

use std::collections::HashSet;

use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::records::{ChapterRecord, TocNode};

/// 对单空格、标点前的空格做归一化。←→ Python `_summary_title_key()` (shared/text.py:108)
fn summary_title_key(value: &str) -> String {
    static WS_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());
    static PUNCT_WS_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+([?!:;,])").unwrap());

    let text = WS_RE.replace_all(value.trim(), " ");
    let text = PUNCT_WS_RE.replace_all(&text, "$1");
    text.to_lowercase()
}

/// 提取 TOC 标题摘要与角色统计。
///
/// ←→ Python `_toc_titles_and_summary()` (book_assemble.py:47)
pub fn toc_titles_and_summary(
    _toc_tree: &[TocNode],
    toc_chapters: &[ChapterRecord],
    container_titles: &[String],
    post_body_titles: &[String],
    back_matter_titles: &[String],
) -> (Vec<String>, Vec<String>, Vec<String>, serde_json::Value) {
    // container_titles 已有从 phase1.summary 传入
    let mut container_filtered: Vec<String> = container_titles
        .iter()
        .filter(|t| !t.trim().is_empty())
        .cloned()
        .collect();

    // post_body_titles 已有从 phase1.summary 传入
    let post_body_filtered: Vec<String> = post_body_titles
        .iter()
        .filter(|t| !t.trim().is_empty())
        .cloned()
        .collect();

    let back_matter_filtered: Vec<String> = back_matter_titles
        .iter()
        .filter(|t| !t.trim().is_empty())
        .cloned()
        .collect();

    // 构建已导出章节的 title_key 集合，用于过滤 container_titles
    // Python: role in {"chapter", "post_body"} —— 排除 back_matter/front_matter
    let back_matter_title_set: HashSet<&str> =
        back_matter_filtered.iter().map(|s| s.as_str()).collect();
    let mut exported_title_keys: HashSet<String> = toc_chapters
        .iter()
        .filter(|row| !back_matter_title_set.contains(row.title.as_str()))
        .map(|row| summary_title_key(&row.title))
        .filter(|k| !k.is_empty())
        .collect();
    // 同时纳入 post_body 标题
    for t in &post_body_filtered {
        let key = summary_title_key(t);
        if !key.is_empty() {
            exported_title_keys.insert(key);
        }
    }

    if !exported_title_keys.is_empty() {
        container_filtered.retain(|title| {
            let key = summary_title_key(title);
            !exported_title_keys.contains(&key)
        });
    }

    // 角色统计：chapter 计数排除 back_matter 条目
    let chapter_count: usize = toc_chapters
        .iter()
        .filter(|row| !back_matter_title_set.contains(row.title.as_str()))
        .count();
    let back_matter_count = back_matter_filtered.len();

    let toc_role_summary = serde_json::json!({
        "container": container_filtered.len(),
        "chapter": chapter_count,
        "post_body": post_body_filtered.len(),
        "back_matter": back_matter_count,
    });

    (
        container_filtered,
        post_body_filtered,
        back_matter_filtered,
        toc_role_summary,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn summary_title_key_basic() {
        let key = summary_title_key("  Hello   World  ");
        assert_eq!(key, "hello world");
    }

    #[test]
    fn summary_title_key_punct() {
        let key = summary_title_key("Hello , World !");
        assert_eq!(key, "hello, world!");
    }

    #[test]
    fn toc_titles_empty() {
        let (container, post_body, back_matter, role_summary) =
            toc_titles_and_summary(&[], &[], &[], &[], &[]);
        assert!(container.is_empty());
        assert!(post_body.is_empty());
        assert!(back_matter.is_empty());
        assert_eq!(role_summary["chapter"], 0);
    }

    #[test]
    fn toc_titles_container_dedup() {
        let chapters = vec![ChapterRecord {
            chapter_id: "ch-1".into(),
            title: "Introduction".into(),
            start_page: 1,
            end_page: 1,
            pages: vec![],
            source: fnm_core::types::ChapterSource::VisualToc,
            boundary_state: fnm_core::types::BoundaryState::Ready,
        }];
        let container = vec!["Introduction".to_string(), "Another Container".to_string()];
        let (filtered, _, _, role_summary) =
            toc_titles_and_summary(&[], &chapters, &container, &[], &[]);
        // "Introduction" 已被导出章节占用，应从 container 中移除
        assert_eq!(filtered.len(), 1);
        assert_eq!(filtered[0], "Another Container");
    }

    #[test]
    fn toc_titles_role_count() {
        let mk_ch = |id: &str, title: &str| ChapterRecord {
            chapter_id: id.to_string(),
            title: title.to_string(),
            start_page: 1,
            end_page: 1,
            pages: vec![],
            source: fnm_core::types::ChapterSource::VisualToc,
            boundary_state: fnm_core::types::BoundaryState::Ready,
        };
        let chapters = vec![mk_ch("ch-1", "Chapter 1"), mk_ch("ch-2", "Chapter 2")];
        let (_, _, _, role_summary) =
            toc_titles_and_summary(&[], &chapters, &[], &[], &["Index".to_string()]);
        assert_eq!(role_summary["chapter"], 2);
        assert_eq!(role_summary["back_matter"], 1);
    }
}
