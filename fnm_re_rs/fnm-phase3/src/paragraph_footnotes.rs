//! ←→ FNM_RE/stages/paragraph_footnotes.py
//!
//! 段落级脚注记录——数据来源从 raw markdown 改为 Phase2 NoteItem。
//! 不再重新扫描 raw markdown 的 footnote band/separator/条目（铁律 §4：
//! 下游不重新构造上游事实）。
//!
//! 保留段落挂载逻辑：根据 item marker 在页面的 body 部分查找段落索引。

use fnm_core::anchor_kind::{patterns, valid_bracket_ref_iter};
use fnm_core::records::{
    ChapterRecord, NoteItemRecord, PagePartitionRecord, ParagraphFootnoteRecord,
};
use fnm_phase1::input::RawPage;
use std::collections::HashMap;

// ── 正文 marker 扫描 ────────────────────────────────────────────
// AGENTS.md §3：复用 fnm-core 的 14 个 anchor_kind::patterns 正则，禁止本地重新定义。

fn footnote_marker_in_body(line: &str, marker: &str) -> bool {
    for cap in patterns::HTML_SUP_RE.captures_iter(line) {
        if let Some(m) = cap.get(1) {
            if m.as_str() == marker {
                return true;
            }
        }
    }
    for cap in patterns::LATEX_SUP_RE.captures_iter(line) {
        if let Some(m) = cap.get(1) {
            if m.as_str() == marker {
                return true;
            }
        }
    }
    for (_, _, captured_marker) in valid_bracket_ref_iter(line) {
        if captured_marker == marker {
            return true;
        }
    }
    false
}

// ── 内部辅助 ────────────────────────────────────────────────────

fn page_markdown_text(page: &RawPage) -> String {
    page.enriched_markdown
        .as_ref()
        .filter(|s| !s.trim().is_empty())
        .cloned()
        .unwrap_or_else(|| page.markdown.clone())
}

/// 在 body 行中查找匹配 marker 的行索引。
fn scan_body_lines_for_marker(body_lines: &[String], marker: &str) -> Option<usize> {
    for (i, line) in body_lines.iter().enumerate() {
        if footnote_marker_in_body(line, marker) {
            return Some(i);
        }
    }
    None
}

/// 将页面 markdown 切分为非空行。
fn split_lines(text: &str) -> Vec<String> {
    text.lines()
        .map(|l| l.trim())
        .filter(|l| !l.is_empty())
        .map(String::from)
        .collect()
}

// ── 主入口 ─────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct ParagraphFootnoteSummary {
    pub total_footnote_items: usize,
    pub anchor_matched: usize,
    pub page_tail: usize,
    pub cross_page_tail: usize,
    pub chapter_count: usize,
    pub chapter_stats: serde_json::Value,
}

/// 构建段落级脚注记录。
///
/// 数据来源：Phase2 NoteItem（note_kind=footnote）。不再重新解析 raw markdown。
///
/// ←→ Python `build_paragraph_footnotes`
pub fn build_paragraph_footnotes(
    chapters: &[ChapterRecord],
    pages: &[PagePartitionRecord],
    raw_pages: &[RawPage],
    note_items: &[NoteItemRecord],
    doc_id: &str,
) -> (Vec<ParagraphFootnoteRecord>, ParagraphFootnoteSummary) {
    let raw_page_by_no: HashMap<i64, &RawPage> =
        raw_pages.iter().map(|p| (p.book_page, p)).collect();
    let page_role_by_no: HashMap<i64, &str> = pages
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str()))
        .collect();

    // 按 (chapter_id, page_no) 分组 Phase2 footnote items
    let mut fn_items_by_page: HashMap<(String, i64), Vec<&NoteItemRecord>> = HashMap::new();
    for item in note_items {
        if item.note_kind.as_str() != "footnote" {
            continue;
        }
        fn_items_by_page
            .entry((item.chapter_id.clone(), item.page_no))
            .or_default()
            .push(item);
    }

    let mut all_records: Vec<ParagraphFootnoteRecord> = Vec::new();
    let mut chapter_stats: HashMap<String, serde_json::Map<String, serde_json::Value>> =
        HashMap::new();

    for chapter in chapters {
        let chapter_id = &chapter.chapter_id;
        let chapter_page_set: std::collections::HashSet<i64> =
            chapter.pages.iter().copied().filter(|&p| p > 0).collect();

        // body 页：page_role=body 且在 chapter.pages 中
        let mut body_page_nos: Vec<i64> = raw_pages
            .iter()
            .filter(|p| {
                chapter_page_set.contains(&p.book_page)
                    && page_role_by_no.get(&p.book_page).copied().unwrap_or("") == "body"
            })
            .map(|p| p.book_page)
            .collect();
        body_page_nos.sort();

        if body_page_nos.is_empty() {
            continue;
        }

        // 按页挂载 footnote items
        let mut fn_page_records: Vec<ParagraphFootnoteRecord> = Vec::new();
        for bp in &body_page_nos {
            let page_fn_items = match fn_items_by_page.get(&(chapter_id.clone(), *bp)) {
                Some(items) => items,
                None => continue,
            };

            let md = raw_page_by_no
                .get(bp)
                .map(|p| page_markdown_text(p))
                .unwrap_or_default();
            if md.is_empty() {
                continue;
            }

            let lines = split_lines(&md);
            // 找分隔线位置（如果有），仅用于切出 body 部分
            // 不再从中解析条目——条目来自 Phase2 NoteItem
            let band_start = lines
                .iter()
                .position(|l| l.chars().all(|c| c == '-' || c == '=' || c == '_') && l.len() >= 3);

            let body_lines: &[String] = match band_start {
                Some(idx) if idx > 0 && idx < lines.len() => &lines[..idx],
                _ => &lines[..],
            };

            for item in page_fn_items {
                let para_idx = match scan_body_lines_for_marker(body_lines, &item.marker) {
                    Some(idx) => {
                        fn_page_records.push(ParagraphFootnoteRecord {
                            doc_id: doc_id.to_string(),
                            chapter_id: chapter_id.clone(),
                            page_no: *bp,
                            paragraph_index: idx as i64,
                            attachment_kind: "anchor_matched".to_string(),
                            source_marker: item.marker.clone(),
                            text: item.text.clone(),
                        });
                        continue;
                    }
                    None => body_lines.len().saturating_sub(1) as i64,
                };
                fn_page_records.push(ParagraphFootnoteRecord {
                    doc_id: doc_id.to_string(),
                    chapter_id: chapter_id.clone(),
                    page_no: *bp,
                    paragraph_index: para_idx,
                    attachment_kind: "page_tail".to_string(),
                    source_marker: item.marker.clone(),
                    text: item.text.clone(),
                });
            }
        }

        let item_count = fn_page_records.len();

        all_records.extend(fn_page_records);

        let mut stats = serde_json::Map::new();
        stats.insert(
            "body_page_count".to_string(),
            serde_json::Value::Number(body_page_nos.len().into()),
        );
        stats.insert(
            "footnote_item_count".to_string(),
            serde_json::Value::Number(item_count.into()),
        );
        chapter_stats.insert(chapter_id.clone(), stats);
    }

    let total_items = all_records.len();
    let anchor_matched = all_records
        .iter()
        .filter(|r| r.attachment_kind == "anchor_matched")
        .count();
    let page_tail = all_records
        .iter()
        .filter(|r| r.attachment_kind == "page_tail")
        .count();
    let cross_tail = all_records
        .iter()
        .filter(|r| r.attachment_kind == "cross_page_tail")
        .count();

    let summary = ParagraphFootnoteSummary {
        total_footnote_items: total_items,
        anchor_matched,
        page_tail,
        cross_page_tail: cross_tail,
        chapter_count: chapter_stats.len(),
        chapter_stats: serde_json::Value::Object(
            chapter_stats
                .into_iter()
                .map(|(k, v)| (k, serde_json::Value::Object(v)))
                .collect(),
        ),
    };

    (all_records, summary)
}
