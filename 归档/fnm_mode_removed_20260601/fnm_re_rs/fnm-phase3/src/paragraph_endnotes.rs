//! ←→ FNM_RE/stages/paragraph_endnotes.py
//!
//! 段落级尾注记录——数据来源从 raw markdown 改为 Phase2 NoteItem。
//! 不再用 page_role 重新推断尾注页（铁律 §4：下游不重新构造上游事实）。
//! 不再重新解析 raw markdown 的 ENDNOTE_ITEM_RE 或 note_scan 回退。
//!
//! 保留章节绑定和 ordinal 编排逻辑。

use fnm_core::records::{ChapterEndnoteRecord, ChapterRecord, NoteItemRecord, PagePartitionRecord};
use fnm_phase1::input::RawPage;
use std::collections::HashMap;

// ── 内部辅助 ────────────────────────────────────────────────────

/// 按 (chapter_id, page_no) 分组 Phase2 endnote NoteItems，
/// 合并为 ChapterEndnoteRecord（带 ordinal 编号）。
fn group_by_chapter(
    note_items: &[NoteItemRecord],
    _chapters: &[ChapterRecord],
) -> HashMap<String, Vec<ChapterEndnoteRecord>> {
    let mut by_chapter: HashMap<String, Vec<(i64, &NoteItemRecord)>> = HashMap::new();
    for item in note_items {
        if item.note_kind.as_str() != "endnote" {
            continue;
        }
        by_chapter
            .entry(item.chapter_id.clone())
            .or_default()
            .push((item.page_no, item));
    }

    let mut result: HashMap<String, Vec<ChapterEndnoteRecord>> = HashMap::new();
    for (chapter_id, mut items) in by_chapter {
        items.sort_by(|(p1, i1), (p2, i2)| p1.cmp(p2).then(i1.marker.cmp(&i2.marker)));
        let source_page = items.first().map(|(p, _)| *p).unwrap_or(0);

        let records: Vec<ChapterEndnoteRecord> = items
            .into_iter()
            .enumerate()
            .map(|(idx, (_, item))| ChapterEndnoteRecord {
                doc_id: String::new(),
                chapter_id: chapter_id.clone(),
                ordinal: (idx + 1) as i64,
                marker: item.marker.clone(),
                numbering_scheme: "per_chapter".to_string(),
                text: item.text.clone(),
                source_page_no: source_page,
                is_reconstructed: item.is_reconstructed,
                review_required: item.review_required,
            })
            .collect();

        result.insert(chapter_id, records);
    }

    result
}

// ── 主入口 ─────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct ParagraphEndnoteSummary {
    pub total_endnote_items: usize,
    pub chapter_count: usize,
    pub reconstructed_count: usize,
    pub chapter_stats: serde_json::Value,
}

/// 构建段落级尾注记录。
///
/// 数据来源：Phase2 NoteItem（note_kind=endnote）。不再重新解析 raw markdown
/// 或 page_role（铁律 §4：下游不重新构造上游事实）。
///
/// ←→ Python `build_paragraph_endnotes`
pub fn build_paragraph_endnotes(
    chapters: &[ChapterRecord],
    _pages: &[PagePartitionRecord],
    _raw_pages: &[RawPage],
    note_items: &[NoteItemRecord],
    doc_id: &str,
) -> (Vec<ChapterEndnoteRecord>, ParagraphEndnoteSummary) {
    let by_chapter = group_by_chapter(note_items, chapters);

    let mut all_records: Vec<ChapterEndnoteRecord> = Vec::new();
    let mut chapter_stats: HashMap<String, serde_json::Map<String, serde_json::Value>> =
        HashMap::new();

    for (chapter_id, mut records) in by_chapter {
        let item_count = records.len();
        for r in &mut records {
            r.doc_id = doc_id.to_string();
        }
        all_records.extend(records);

        let mut stats = serde_json::Map::new();
        stats.insert(
            "endnote_page_count".to_string(),
            serde_json::Value::Number(serde_json::Number::from(1)), // 最小估计：来自 Phase2 数据源
        );
        stats.insert(
            "endnote_item_count".to_string(),
            serde_json::Value::Number(serde_json::Number::from(item_count as i64)),
        );
        chapter_stats.insert(chapter_id, stats);
    }

    let total_items = all_records.len();
    let reconstructed_count = all_records.iter().filter(|r| r.is_reconstructed).count();

    let summary = ParagraphEndnoteSummary {
        total_endnote_items: total_items,
        chapter_count: chapter_stats.len(),
        reconstructed_count,
        chapter_stats: serde_json::Value::Object(
            chapter_stats
                .into_iter()
                .map(|(k, v)| (k, serde_json::Value::Object(v)))
                .collect(),
        ),
    };

    (all_records, summary)
}
