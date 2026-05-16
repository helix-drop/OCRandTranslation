//! ←→ FNM_RE/stages/paragraph_endnotes.py
//!
//! 段落级尾注检测：
//! 1. 识别尾注候选页（page_role=note / notes heading / note_scan 含 endnote）
//! 2. 排除插图列表页
//! 3. 按连续页分组
//! 4. 逐组解析条目（优先 markdown，回退 note_scan）
//! 5. marker 序列异常处理 + 章节绑定

use fnm_core::note_marker::{first_notes_heading, normalize_note_marker};
use fnm_core::records::{ChapterEndnoteRecord, ChapterRecord, PagePartitionRecord};
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashMap;

// ── 正则 ────────────────────────────────────────────────────────

static ILLUSTRATION_LIST_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:list(?:e)?\s+(?:of\s+)?(?:illustrations?|figures?|plates?)|liste\s+des\s+illustrations?)\b",
    )
    .unwrap()
});

static ENDNOTE_ITEM_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(\d{1,4})(?:\s*[\.、）)\]]\s*|\s+)(.*)").unwrap());

// ── 内部辅助 ────────────────────────────────────────────────────

fn page_markdown_text(page: &RawPage) -> String {
    page.enriched_markdown
        .as_ref()
        .filter(|s| !s.trim().is_empty())
        .cloned()
        .unwrap_or_else(|| page.markdown.clone())
}

fn page_role_map(pages: &[PagePartitionRecord]) -> HashMap<i64, String> {
    pages
        .iter()
        .filter(|p| p.page_no > 0)
        .map(|p| (p.page_no, p.page_role.as_str().to_string()))
        .collect()
}

/// 判断是否为尾注页。
fn is_endnote_page(
    page_no: i64,
    page_role_by_no: &HashMap<i64, String>,
    raw_page_by_no: &HashMap<i64, &RawPage>,
) -> bool {
    let Some(page) = raw_page_by_no.get(&page_no) else {
        return false;
    };
    let role = page_role_by_no.get(&page_no).map_or("", |s| s.as_str());
    if role == "note" {
        return true;
    }
    if role == "other" && !first_notes_heading(&page.markdown).is_empty() {
        return true;
    }
    if has_note_scan_items(page, "endnote") {
        return true;
    }
    if !first_notes_heading(&page.markdown).is_empty() {
        return true;
    }
    false
}

/// 检查 raw_page._note_scan 是否包含指定 kind 的条目。
fn has_note_scan_items(page: &RawPage, kind: &str) -> bool {
    let Some(scan) = &page.note_scan else {
        return false;
    };
    let Some(items) = scan.get("items").and_then(|v| v.as_array()) else {
        return false;
    };
    items
        .iter()
        .any(|item| item.get("kind").and_then(|v| v.as_str()) == Some(kind))
}

/// 排除插图列表页。
fn looks_like_illustration_list_page(
    page_no: i64,
    raw_page_by_no: &HashMap<i64, &RawPage>,
) -> bool {
    let Some(page) = raw_page_by_no.get(&page_no) else {
        return false;
    };
    let md = page.markdown.trim();
    let first_line = md.lines().next().unwrap_or("").trim();
    let stripped = first_line.trim_start_matches('#').trim();
    ILLUSTRATION_LIST_RE.is_match(stripped)
}

fn last_chapter_end_page(chapters: &[ChapterRecord]) -> i64 {
    chapters.iter().map(|c| c.end_page).max().unwrap_or(0)
}

fn is_book_scope(page_no: i64, last_end_page: i64) -> bool {
    page_no > last_end_page
}

/// 从 markdown 文本解析尾注条目（最小实现）。
fn parse_note_items_from_markdown(md: &str) -> Vec<(String, String)> {
    let mut items = Vec::new();
    for line in md.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        if let Some(cap) = ENDNOTE_ITEM_RE.captures(line) {
            let marker = cap.get(1).map_or("", |m| m.as_str()).to_string();
            let text = cap.get(2).map_or("", |m| m.as_str()).trim().to_string();
            let marker = normalize_note_marker(&marker);
            if !marker.is_empty() {
                items.push((marker, text));
            }
        } else if let Some(last) = items.last_mut() {
            // 续行
            last.1.push(' ');
            last.1.push_str(line);
        }
    }
    items
}

/// 解析单个页面的注释条目。
fn parse_items_from_page(page: &RawPage) -> Vec<(String, String, bool)> {
    let md = page_markdown_text(page);
    if !md.is_empty() {
        let items = parse_note_items_from_markdown(&md);
        if !items.is_empty() {
            return items
                .into_iter()
                .map(|(marker, text)| (marker, text, false))
                .collect();
        }
    }

    // 回退到 note_scan
    if let Some(scan) = &page.note_scan {
        if let Some(items) = scan.get("items").and_then(|v| v.as_array()) {
            return items
                .iter()
                .filter_map(|item| {
                    let marker = item.get("marker")?.as_str()?;
                    let text = item.get("text")?.as_str()?;
                    let marker = normalize_note_marker(marker);
                    if marker.is_empty() || text.trim().is_empty() {
                        return None;
                    }
                    let is_reconstructed = item
                        .get("is_reconstructed")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false);
                    Some((marker, text.trim().to_string(), is_reconstructed))
                })
                .collect();
        }
    }

    Vec::new()
}

/// 将连续页码分组。
fn split_contiguous_ranges(values: &[i64]) -> Vec<Vec<i64>> {
    if values.is_empty() {
        return Vec::new();
    }
    let mut sorted: Vec<i64> = values.to_vec();
    sorted.sort_unstable();

    let mut runs: Vec<Vec<i64>> = Vec::new();
    let mut current = vec![sorted[0]];

    for &v in &sorted[1..] {
        if v == current.last().copied().unwrap_or(0) + 1 {
            current.push(v);
        } else {
            runs.push(current);
            current = vec![v];
        }
    }
    if !current.is_empty() {
        runs.push(current);
    }
    runs
}

/// 查找页码归属的章节。
fn chapter_id_for_page(chapters: &[ChapterRecord], page_no: i64) -> Option<String> {
    // 1. 精确匹配 chapter.pages 列表
    for ch in chapters {
        if ch.pages.contains(&page_no) {
            return Some(ch.chapter_id.clone());
        }
    }
    // 2. 区间匹配 start_page <= page_no <= end_page
    for ch in chapters {
        if ch.start_page <= page_no && page_no <= ch.end_page {
            return Some(ch.chapter_id.clone());
        }
    }
    // 3. 最近前置章节（page_no >= start_page 的最大 start_page）
    let mut best = None;
    let mut best_start = i64::MIN;
    for ch in chapters {
        if ch.start_page <= page_no && ch.start_page > best_start {
            best_start = ch.start_page;
            best = Some(ch.chapter_id.clone());
        }
    }
    best
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
/// ←→ Python `build_paragraph_endnotes`
pub fn build_paragraph_endnotes(
    chapters: &[ChapterRecord],
    pages: &[PagePartitionRecord],
    raw_pages: &[RawPage],
    doc_id: &str,
) -> (Vec<ChapterEndnoteRecord>, ParagraphEndnoteSummary) {
    let page_role_by_no = page_role_map(pages);
    let raw_page_by_no: HashMap<i64, &RawPage> =
        raw_pages.iter().map(|p| (p.book_page, p)).collect();

    let last_end = last_chapter_end_page(chapters);
    let mut sorted_page_nos: Vec<i64> =
        pages.iter().map(|p| p.page_no).filter(|&p| p > 0).collect();
    sorted_page_nos.sort_unstable();

    // Pass 1: 识别尾注候选页
    let mut endnote_page_nos: Vec<i64> = Vec::new();
    for pn in &sorted_page_nos {
        if !is_endnote_page(*pn, &page_role_by_no, &raw_page_by_no) {
            continue;
        }
        if looks_like_illustration_list_page(*pn, &raw_page_by_no) {
            continue;
        }
        endnote_page_nos.push(*pn);
    }

    // Pass 2: 按连续页分组
    let group_runs = split_contiguous_ranges(&endnote_page_nos);

    // Pass 3: 对每组分组合并解析
    let mut all_records: Vec<ChapterEndnoteRecord> = Vec::new();
    let mut chapter_stats: HashMap<String, serde_json::Map<String, serde_json::Value>> =
        HashMap::new();

    for run in group_runs {
        let midpoint = run[run.len() / 2];
        let is_book = is_book_scope(midpoint, last_end);
        let chapter_id = if is_book {
            chapter_id_for_page(chapters, run[0])
        } else {
            chapter_id_for_page(chapters, midpoint)
        };

        let Some(target_chapter) = chapter_id else {
            continue;
        };

        let mut ordinal = 0usize;
        let mut last_marker_value: Option<i64> = None;
        let mut used_items: Vec<(String, String, bool)> = Vec::new();

        for pn in &run {
            let Some(page) = raw_page_by_no.get(pn) else {
                continue;
            };
            let parsed = parse_items_from_page(page);
            for (marker, text, is_reconstructed) in parsed {
                let mv: i64 = marker.parse().unwrap_or(0);
                if mv > 0 && last_marker_value.is_some() && mv < last_marker_value.unwrap_or(0) - 5
                {
                    // marker 大幅回退
                    if mv != 1 && mv != 2 && mv != 3 {
                        continue;
                    }
                    // 序列重置：重置 last_marker_value 让后续条目从新起点继续
                    // 但当前值只用于后续条目的比较，这里直接更新为 mv - 1
                    // 使得下一个条目的 mv > last_marker_value - 5 判断成立
                }
                ordinal += 1;
                last_marker_value = Some(mv);
                used_items.push((marker, text, is_reconstructed));
            }
        }

        if used_items.is_empty() {
            continue;
        }

        let source_page = run[0];

        for (idx, (marker, text, is_reconstructed)) in used_items.into_iter().enumerate() {
            all_records.push(ChapterEndnoteRecord {
                doc_id: doc_id.to_string(),
                chapter_id: target_chapter.clone(),
                ordinal: (idx + 1) as i64,
                marker,
                numbering_scheme: "per_chapter".to_string(),
                text,
                source_page_no: source_page,
                is_reconstructed,
                review_required: false,
            });
        }

        let stats = chapter_stats.entry(target_chapter.clone()).or_default();
        let current_page_count = stats
            .get("endnote_page_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        stats.insert(
            "endnote_page_count".to_string(),
            serde_json::Value::Number((current_page_count + run.len() as i64).into()),
        );
        let current_item_count = stats
            .get("endnote_item_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        stats.insert(
            "endnote_item_count".to_string(),
            serde_json::Value::Number((current_item_count + ordinal as i64).into()),
        );
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
