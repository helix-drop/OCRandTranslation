//! ←→ FNM_RE/modules/toc_structure.py `_build_page_roles`
//! 为每页分配角色 + chapter_id。

use fnm_core::records::{ChapterRecord, PagePartitionRecord, TocPageRole};

static BACK_MATTER_REASON_HINTS: &[&str] = &[
    "appendix",
    "bibliography",
    "index",
    "illustrations",
    "rear_toc_tail",
    "rear_author_blurb",
    "rear_sparse_other",
];

/// ←→ Python `_build_page_roles`
pub fn build_page_roles(
    partitions: &[PagePartitionRecord],
    chapters: &[ChapterRecord],
    back_matter_start_hint: i64,
) -> Vec<TocPageRole> {
    // 1. 构建 chapter_by_page 映射
    let mut chapter_by_page: std::collections::HashMap<i64, String> =
        std::collections::HashMap::new();
    for chapter in chapters {
        if chapter.chapter_id.is_empty() {
            continue;
        }
        for &page_no in &chapter.pages {
            if page_no > 0 {
                chapter_by_page.insert(page_no, chapter.chapter_id.clone());
            }
        }
        // 按 start-end 范围补齐缺页
        if chapter.start_page > 0 && chapter.end_page >= chapter.start_page {
            for page_no in chapter.start_page..=chapter.end_page {
                chapter_by_page
                    .entry(page_no)
                    .or_insert_with(|| chapter.chapter_id.clone());
            }
        }
    }

    let first_chapter_start = chapters
        .iter()
        .filter(|ch| ch.start_page > 0)
        .map(|ch| ch.start_page)
        .min()
        .unwrap_or(0);

    let total_pages = partitions.len().max(1) as i64;
    let rear_page_role_min_page = (24).max((total_pages as f64 * 0.45) as i64);

    let back_matter_start = if back_matter_start_hint > 0 {
        back_matter_start_hint
    } else {
        partitions
            .iter()
            .filter(|row| {
                let pn = row.page_no;
                let r = row.reason.as_str();
                pn > first_chapter_start
                    && pn >= rear_page_role_min_page
                    && BACK_MATTER_REASON_HINTS.contains(&r)
            })
            .map(|row| row.page_no)
            .min()
            .unwrap_or(0)
    };

    let mut rows: Vec<TocPageRole> = Vec::new();

    for row in partitions {
        let page_no = row.page_no;
        let source_role = row.page_role.as_str().to_string();
        let chapter = chapter_by_page.get(&page_no);

        // 12 条件分支，按优先级
        let (role, chapter_id) = if source_role == "note" {
            ("note".into(), chapter.cloned().unwrap_or_default())
        } else if let Some(ch) = chapter {
            // 章节内的页面 → chapter role
            ("chapter".into(), ch.clone())
        } else if (page_no > 0 && back_matter_start > 0 && page_no >= back_matter_start)
            || (back_matter_start == 0
                && BACK_MATTER_REASON_HINTS.contains(&row.reason.as_str())
                && page_no >= rear_page_role_min_page)
        {
            ("back_matter".into(), String::new())
        } else if source_role == "other"
            || (first_chapter_start > 0 && page_no < first_chapter_start)
            || source_role == "front_matter"
        {
            ("front_matter".into(), String::new())
        } else {
            ("other".into(), String::new())
        };

        rows.push(TocPageRole {
            page_no,
            role,
            source_role,
            reason: row.reason.clone(),
            chapter_id,
        });
    }

    rows.sort_by_key(|a| a.page_no);
    rows
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{BoundaryState, ChapterSource, PageRole};

    #[test]
    fn empty_input() {
        let roles = build_page_roles(&[], &[], 0);
        assert!(roles.is_empty());
    }

    #[test]
    fn chapter_mapping() {
        let ch = ChapterRecord {
            chapter_id: "ch-1".into(),
            title: "Ch 1".into(),
            start_page: 1,
            end_page: 5,
            pages: vec![1, 2, 3, 4, 5],
            source: ChapterSource::VisualToc,
            boundary_state: BoundaryState::Ready,
        };
        let pp = PagePartitionRecord {
            page_no: 3,
            target_pdf_page: 3,
            page_role: PageRole::Body,
            confidence: 1.0,
            reason: "body_page".into(),
            section_hint: String::new(),
            has_note_heading: false,
            note_scan_summary: serde_json::Value::Null,
        };
        let roles = build_page_roles(&[pp], &[ch], 0);
        assert_eq!(roles[0].chapter_id, "ch-1");
        assert_eq!(roles[0].role, "chapter");
    }
}
