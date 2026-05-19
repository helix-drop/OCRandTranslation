//! ←→ FNM_RE/modules/book_assemble.py
//! 翻译的函数：
//!   reorder_chapters          ←→ _reorder_chapters (book_assemble.py:83)
//!   to_export_chapter_records ←→ _to_export_chapter_records (book_assemble.py:124)

use std::collections::{HashMap, HashSet};

use fnm_core::records::{ChapterMarkdownEntry, ChapterRecord, ExportChapterRecord};

/// 按 TOC 顺序重排章节，去重，返回有序列表 + missing/extra ID 列表。
///
/// ←→ Python `_reorder_chapters()` (book_assemble.py:83)
pub fn reorder_chapters(
    chapter_markdown_set: &[ChapterMarkdownEntry],
    toc_chapters: &[ChapterRecord],
) -> (Vec<ChapterMarkdownEntry>, Vec<String>, Vec<String>) {
    let chapter_by_id: HashMap<&str, &ChapterMarkdownEntry> = chapter_markdown_set
        .iter()
        .filter(|row| !row.chapter_id.trim().is_empty())
        .map(|row| (row.chapter_id.as_str(), row))
        .collect();

    // TOC 中按顺序的 chapter_id（dict.fromkeys 去重）
    let toc_ids: Vec<&str> = toc_chapters
        .iter()
        .filter(|row| !row.chapter_id.trim().is_empty())
        .map(|row| row.chapter_id.as_str())
        .collect::<Vec<&str>>();

    let mut seen_ids: HashSet<&str> = HashSet::new();
    let mut expected_export_ids: Vec<&str> = Vec::new();
    for chapter_id in &toc_ids {
        if seen_ids.insert(chapter_id) && chapter_by_id.contains_key(chapter_id) {
            expected_export_ids.push(chapter_id);
        }
    }

    let mut ordered: Vec<ChapterMarkdownEntry> = Vec::new();
    for chapter_id in &expected_export_ids {
        if let Some(row) = chapter_by_id.get(chapter_id) {
            ordered.push((*row).clone());
        }
    }

    let ordered_id_set: HashSet<&str> = expected_export_ids.iter().copied().collect();
    let leftovers: Vec<ChapterMarkdownEntry> = chapter_markdown_set
        .iter()
        .filter(|row| !ordered_id_set.contains(row.chapter_id.as_str()))
        .cloned()
        .collect();
    ordered.extend(leftovers);

    // 重新编号
    let ordered: Vec<ChapterMarkdownEntry> = ordered
        .into_iter()
        .enumerate()
        .map(|(index, mut row)| {
            row.order = (index + 1) as i64;
            row
        })
        .collect();

    let chapter_id_set: HashSet<&str> = chapter_by_id.keys().copied().collect();
    let missing: Vec<String> = toc_ids
        .iter()
        .filter(|id| !chapter_id_set.contains(*id))
        .map(|s| s.to_string())
        .collect();

    let chapter_ids_from_set: HashSet<&str> = chapter_markdown_set
        .iter()
        .filter(|row| !row.chapter_id.trim().is_empty())
        .map(|row| row.chapter_id.as_str())
        .collect();
    let extra: Vec<String> = chapter_ids_from_set
        .iter()
        .filter(|id| !ordered_id_set.contains(*id))
        .map(|s| s.to_string())
        .collect();

    (ordered, missing, extra)
}

/// 将 ChapterMarkdownEntry 转换为 ExportChapterRecord。
///
/// ←→ Python `_to_export_chapter_records()` (book_assemble.py:124)
pub fn to_export_chapter_records(chapters: &[ChapterMarkdownEntry]) -> Vec<ExportChapterRecord> {
    chapters
        .iter()
        .filter(|row| !row.path.trim().is_empty())
        .map(|row| ExportChapterRecord {
            order: row.order,
            section_id: row.chapter_id.clone(),
            title: if row.title.trim().is_empty() {
                row.chapter_id.clone()
            } else {
                row.title.clone()
            },
            path: row.path.clone(),
            content: row.markdown_text.clone(),
            start_page: row.start_page,
            end_page: row.end_page.max(row.start_page),
            pages: row.pages.iter().filter(|&&p| p > 0).copied().collect(),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reorder_empty() {
        let (ordered, missing, extra) = reorder_chapters(&[], &[]);
        assert!(ordered.is_empty());
        assert!(missing.is_empty());
        assert!(extra.is_empty());
    }

    #[test]
    fn reorder_single_chapter() {
        let entries = vec![ChapterMarkdownEntry {
            order: 0,
            chapter_id: "ch-1".into(),
            title: "Chapter 1".into(),
            path: "ch001.md".into(),
            markdown_text: "text".into(),
            start_page: 1,
            end_page: 10,
            pages: vec![1, 2, 3],
        }];
        let toc = vec![ChapterRecord {
            chapter_id: "ch-1".into(),
            title: "Chapter 1".into(),
            start_page: 1,
            end_page: 10,
            pages: vec![1, 2, 3],
            source: fnm_core::types::ChapterSource::VisualToc,
            boundary_state: fnm_core::types::BoundaryState::Ready,
        }];
        let (ordered, missing, extra) = reorder_chapters(&entries, &toc);
        assert_eq!(ordered.len(), 1);
        assert_eq!(ordered[0].order, 1);
        assert!(missing.is_empty());
        assert!(extra.is_empty());
    }

    #[test]
    fn reorder_missing_chapter() {
        let toc = vec![ChapterRecord {
            chapter_id: "ch-missing".into(),
            title: "Missing".into(),
            start_page: 1,
            end_page: 5,
            pages: vec![],
            source: fnm_core::types::ChapterSource::VisualToc,
            boundary_state: fnm_core::types::BoundaryState::Ready,
        }];
        let (ordered, missing, _extra) = reorder_chapters(&[], &toc);
        assert_eq!(missing.len(), 1);
        assert_eq!(missing[0], "ch-missing");
        assert!(ordered.is_empty());
    }

    #[test]
    fn reorder_extra_chapter() {
        let entries = vec![ChapterMarkdownEntry {
            order: 0,
            chapter_id: "ch-extra".into(),
            title: "Extra".into(),
            path: "ch_extra.md".into(),
            markdown_text: "text".into(),
            start_page: 10,
            end_page: 20,
            pages: vec![],
        }];
        let (_ordered, _missing, extra) = reorder_chapters(&entries, &[]);
        assert_eq!(extra.len(), 1);
        assert_eq!(extra[0], "ch-extra");
    }

    #[test]
    fn to_export_records_basic() {
        let chapters = vec![ChapterMarkdownEntry {
            order: 1,
            chapter_id: "ch-1".into(),
            title: "Chapter 1".into(),
            path: "ch001.md".into(),
            markdown_text: "# Hello".into(),
            start_page: 1,
            end_page: 10,
            pages: vec![1, 2, 3],
        }];
        let records = to_export_chapter_records(&chapters);
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].section_id, "ch-1");
        assert_eq!(records[0].content, "# Hello");
    }

    #[test]
    fn to_export_records_filters_empty_path() {
        let chapters = vec![
            ChapterMarkdownEntry {
                order: 1,
                chapter_id: "ch-1".into(),
                title: "Chapter 1".into(),
                path: "".into(),
                ..Default::default()
            },
            ChapterMarkdownEntry {
                order: 2,
                chapter_id: "ch-2".into(),
                title: "Chapter 2".into(),
                path: "ch002.md".into(),
                ..Default::default()
            },
        ];
        let records = to_export_chapter_records(&chapters);
        assert_eq!(records.len(), 1);
    }
}
