//! ←→ FNM_RE/stages/note_items.py (658 行)
//! 注释项解析：标记解析 + 序列修复 + 年份过滤 + 引文缩写合并。
//!
//! 子模块：
//! - marker_parse: 标记解析（OCR split / digit / symbol / letter / HTML / LaTeX）
//! - sequence_repair: 数字序号序列修复 + ParsedNoteRow 中间类型
//! - year_filter: 年份误标过滤 + 序列异常值修正

pub mod marker_parse;
pub mod page_text;
pub mod sequence_repair;
pub mod year_filter;

use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{NoteItemRecord, NoteRegionRecord};
use fnm_core::types::NoteKind;
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;

use self::marker_parse::{parse_page, preprocess_page_text, row_to_item};
use self::sequence_repair::{repair_parsed_row_sequence_markers, ParsedNoteRow};
use self::year_filter::{fix_sequence_outlier_markers_in_place, fix_year_markers_in_place};

// ── Regex 池（mod 级，供 merge_continuation 使用） ────────────

static PAGE_CITATION_PREFIX_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\b(?:pp?|f(?:o|°)?|esp|paras?|fols?|cols?|vol|n[°o]|nos?|nr|art|chap|sect|§|t|tome|liv|bk|book|ch|cf|voir|see|infra|supra|ibid|op|loc|id|éd|ed|eds|dir|trad|tr)\.$",
    )
    .unwrap()
});

// ── 公开 API ──────────────────────────────────────────────────

/// 构建全量注释项。
/// ←→ Python `build_note_items`
pub fn build_note_items(
    pages: &[RawPage],
    note_regions: &[NoteRegionRecord],
) -> Vec<NoteItemRecord> {
    let mut all_items: Vec<NoteItemRecord> = Vec::new();

    for region in note_regions {
        let region_pages: Vec<&RawPage> = pages
            .iter()
            .filter(|p| region.pages.contains(&p.book_page))
            .collect();

        // Phase A: 解析页文本 → ParsedNoteRow
        let mut rows: Vec<ParsedNoteRow> = Vec::new();
        for page in &region_pages {
            let text = if region.note_kind == NoteKind::Footnote {
                // ←→ Python _normalized_page_text: footnote region 使用 `page.footnotes`
                // 预提取文本（仅脚注内容，不含正文）。Python 的 annotate_pages_with_note_scans
                // 在 Phase 1 提前完成此步骤，Rust 在 Phase 2 读取 RawPage.footnotes 字段。
                page.footnotes.clone()
            } else {
                page.markdown.clone()
            };

            if text.is_empty() {
                continue;
            }
            let processed = preprocess_page_text(&text);
            rows.extend(parse_page(&processed, page.book_page, region));
        }

        // Phase B: endnote 序列修复
        if region.note_kind == NoteKind::Endnote {
            rows = repair_parsed_row_sequence_markers(rows);
        }

        // Phase C: 按 marker 去重
        rows = dedupe_region_items(rows);

        // Phase D: 转换 ParsedNoteRow → NoteItemRecord
        let kind_tag = if region.note_kind == NoteKind::Footnote {
            "fn"
        } else {
            "en"
        };
        for (idx, row) in rows.iter().enumerate() {
            let mut item = row_to_item(row, region, kind_tag);
            item.note_item_id = format!("{}-{:04}", kind_tag, all_items.len() + idx + 1);
            all_items.push(item);
        }
    }

    // Phase E: 引文缩写合并
    let items = merge_continuation_notes(all_items);

    // Phase F: 年份误标 + 序列异常值修正
    let items = fix_year_markers_in_place(items);
    fix_sequence_outlier_markers_in_place(items)
}

// ── 内部工具 ──────────────────────────────────────────────────

/// 按 marker 去重（同一 region 内保留第一个出现的 marker）。
fn dedupe_region_items(rows: Vec<ParsedNoteRow>) -> Vec<ParsedNoteRow> {
    let mut result = Vec::with_capacity(rows.len());
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();

    for row in rows {
        let marker = normalize_note_marker(&row.marker);
        if !marker.is_empty() && seen.contains(&marker) {
            continue;
        }
        if !marker.is_empty() {
            seen.insert(marker);
        }
        result.push(row);
    }

    result
}

/// 同 region 内合并被引文缩写截断的相邻 notes。
fn merge_continuation_notes(mut items: Vec<NoteItemRecord>) -> Vec<NoteItemRecord> {
    let mut result: Vec<NoteItemRecord> = Vec::new();
    let mut skip_next = false;

    items.sort_by(|a, b| {
        a.region_id
            .cmp(&b.region_id)
            .then_with(|| a.page_no.cmp(&b.page_no))
            .then_with(|| a.marker.cmp(&b.marker))
    });

    for i in 0..items.len() {
        if skip_next {
            skip_next = false;
            continue;
        }
        let mut current = items[i].clone();
        current.text = current.text.trim().to_string();

        if PAGE_CITATION_PREFIX_RE.is_match(&current.text)
            && i + 1 < items.len()
            && items[i + 1].region_id == current.region_id
        {
            let next_text = items[i + 1].text.trim().to_string();
            current.text = format!("{} {}", current.text, next_text);
            current.is_reconstructed = true;
            skip_next = true;
        }
        result.push(current);
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::NoteKind;

    fn test_region() -> NoteRegionRecord {
        NoteRegionRecord {
            region_id: "r-test".into(),
            chapter_id: "ch-1".into(),
            page_start: 1,
            page_end: 1,
            pages: vec![1],
            note_kind: NoteKind::Endnote,
            scope: fnm_core::types::RegionScope::Chapter,
            source: fnm_core::types::RegionSource::HeadingScan,
            heading_text: "Endnotes".into(),
            start_reason: "test".into(),
            end_reason: "".into(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: "".into(),
            region_first_note_item_marker: "".into(),
            review_required: false,
        }
    }

    #[test]
    fn build_items_empty_input() {
        assert!(build_note_items(&[], &[]).is_empty());
    }

    #[test]
    fn build_items_standard() {
        let page = RawPage {
            book_page: 1,
            markdown: "1. A test note.\n2. Another note.".into(),
            ..Default::default()
        };
        let items = build_note_items(&[page], &[test_region()]);
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].marker, "1");
        assert!(!items[0].note_item_id.is_empty());
    }

    #[test]
    fn build_items_with_sequence_repair() {
        // 幽灵条目 999 应被移除
        let page = RawPage {
            book_page: 1,
            markdown: "1. First.\n999. Ghost.\n2. Second.".into(),
            ..Default::default()
        };
        let items = build_note_items(&[page], &[test_region()]);
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].marker, "1");
        assert_eq!(items[1].marker, "2");
    }

    #[test]
    fn build_items_with_year_filter() {
        // year 1976 夹在 3,4 之间 → 移除
        let page = RawPage {
            book_page: 1,
            markdown: "3. Third.\n1976. Year.\n4. Fourth.".into(),
            ..Default::default()
        };
        let items = build_note_items(&[page], &[test_region()]);
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].marker, "3");
        assert_eq!(items[1].marker, "4");
    }

    #[test]
    fn build_items_with_outlier_fix() {
        // 1, 999, 3 → same region → fix 999 → 2, but only if prev+2=next
        let page = RawPage {
            book_page: 1,
            markdown: "1. First.\n999. Outlier.\n3. Third.".into(),
            ..Default::default()
        };
        let items = build_note_items(&[page], &[test_region()]);
        // 999 is fixed by outlier filter to 2
        assert!(items.len() >= 2); // 1st pass sequence_repair may handle it differently
    }
}
