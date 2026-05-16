//! ←→ FNM_RE/stages/paragraph_footnotes.py
//!
//! 段落级脚注检测（layout-based）：
//! 1. 逐页检测底部 footnote band
//! 2. 切分条目
//! 3. 跨页合并
//! 4. 挂载到正文段落

use fnm_core::anchor_kind::{patterns, valid_bracket_ref_iter};
use fnm_core::records::{ChapterRecord, PagePartitionRecord, ParagraphFootnoteRecord};
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashMap;

// ── 正则 ────────────────────────────────────────────────────────

static SEPARATOR_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^[-=_]{3,}\s*$").unwrap());

static FOOTNOTE_ITEM_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(\d{1,4})(?:\s*[\.、）)\]]\s*|\s+)(.*)").unwrap());

static SYMBOL_FOOTNOTE_ITEM_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(\*{1,4}|†{1,2}|‡{1,2}|§|¶)\s+(.*)").unwrap());

static HAS_END_PUNCTUATION_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[。.!?？!]\s*$").unwrap());

static STARTS_WITH_NUMBER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*\d{1,4}(?:\s*[\.、）)\]]|\s)").unwrap());

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
    // BRACKET_REF_RE 是弱信号正则——用 valid_bracket_ref_iter 把守卫
    // （前后非数字）与匹配在源头绑死，避免本 caller 假阳性命中日期/文档编号。
    for (_, _, captured_marker) in valid_bracket_ref_iter(line) {
        if captured_marker == marker {
            return true;
        }
    }
    false
}

// ── 内部辅助 ────────────────────────────────────────────────────

fn split_lines(text: &str) -> Vec<String> {
    text.lines()
        .map(|l| l.trim())
        .filter(|l| !l.is_empty())
        .map(String::from)
        .collect()
}

fn page_markdown_text(page: &RawPage) -> String {
    page.enriched_markdown
        .as_ref()
        .filter(|s| !s.trim().is_empty())
        .cloned()
        .unwrap_or_else(|| page.markdown.clone())
}

/// 检测底部 footnote band。
/// Returns: (start_idx, end_idx)，未检测到时返回 (0, 0)。
fn detect_footnote_band(lines: &[String]) -> (usize, usize) {
    if lines.len() < 2 {
        return (0, 0);
    }

    // 1. 找分隔线
    for (i, line) in lines.iter().enumerate() {
        if SEPARATOR_RE.is_match(line) {
            return (i + 1, lines.len());
        }
    }

    // 2. 从底部扫描连续编号行（>=2 个）
    let mut consecutive = 0usize;

    for i in (0..lines.len()).rev() {
        if FOOTNOTE_ITEM_RE.is_match(&lines[i]) {
            consecutive += 1;
            if consecutive >= 2 {
                let mut band_start = i;
                while band_start > 0 {
                    let prev = band_start - 1;
                    if FOOTNOTE_ITEM_RE.is_match(&lines[prev]) {
                        band_start = prev;
                    } else {
                        break;
                    }
                }
                return (band_start, lines.len());
            }
        } else {
            consecutive = 0;
        }
    }

    // 3. 从底部扫描符号型脚注行
    for i in (0..lines.len()).rev() {
        if SYMBOL_FOOTNOTE_ITEM_RE.is_match(&lines[i]) {
            let mut sym_start = i;
            while sym_start > 0 {
                let prev = sym_start - 1;
                if SYMBOL_FOOTNOTE_ITEM_RE.is_match(&lines[prev]) {
                    sym_start = prev;
                } else {
                    break;
                }
            }
            return (sym_start, lines.len());
        }
    }

    (0, 0)
}

#[derive(Debug, Clone)]
struct BandItem {
    marker: String,
    text: String,
    cross_page: bool,
}

/// 从 band 行解析脚注条目。
fn parse_band_lines(lines: &[String]) -> Vec<BandItem> {
    let mut items: Vec<BandItem> = Vec::new();
    for line in lines {
        if let Some(cap) = FOOTNOTE_ITEM_RE.captures(line) {
            let marker = cap.get(1).map_or("", |m| m.as_str()).to_string();
            let text = cap.get(2).map_or("", |m| m.as_str()).trim().to_string();
            items.push(BandItem {
                marker,
                text,
                cross_page: false,
            });
        } else if let Some(cap) = SYMBOL_FOOTNOTE_ITEM_RE.captures(line) {
            let marker = cap.get(1).map_or("", |m| m.as_str()).to_string();
            let text = cap.get(2).map_or("", |m| m.as_str()).trim().to_string();
            items.push(BandItem {
                marker,
                text,
                cross_page: false,
            });
        } else if let Some(last) = items.last_mut() {
            // 续到上一条
            if !last.text.is_empty() {
                last.text.push(' ');
            }
            last.text.push_str(line);
        }
        // 首行无编号/符号 → 忽略（不生成 preamble，保持简洁）
    }
    items
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
/// ←→ Python `build_paragraph_footnotes`
pub fn build_paragraph_footnotes(
    chapters: &[ChapterRecord],
    pages: &[PagePartitionRecord],
    raw_pages: &[RawPage],
    doc_id: &str,
) -> (Vec<ParagraphFootnoteRecord>, ParagraphFootnoteSummary) {
    let raw_page_by_no: HashMap<i64, &RawPage> =
        raw_pages.iter().map(|p| (p.book_page, p)).collect();
    let page_role_by_no: HashMap<i64, &str> = pages
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str()))
        .collect();

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

        // Pass 1：逐页检测 band 并解析条目
        let mut page_items: Vec<Vec<BandItem>> = Vec::new();
        for bp in &body_page_nos {
            let md = raw_page_by_no
                .get(bp)
                .map(|p| page_markdown_text(p))
                .unwrap_or_default();
            if md.is_empty() {
                page_items.push(Vec::new());
                continue;
            }
            let lines = split_lines(&md);
            let (band_start, band_end) = detect_footnote_band(&lines);
            if band_start == 0 && band_end == 0 || band_start >= band_end {
                page_items.push(Vec::new());
                continue;
            }
            let items = parse_band_lines(&lines[band_start..band_end]);
            page_items.push(items);
        }

        // Pass 2：跨页合并
        for i in 0..page_items.len().saturating_sub(1) {
            let next_idx = i + 1;
            if page_items[next_idx].is_empty() {
                continue;
            }

            // 标准跨页规则：上页末条无结束标点 + 下页首条无编号开头
            if !page_items[i].is_empty() && !page_items[next_idx].is_empty() {
                let last_prev = page_items[i].last().unwrap().clone();
                let first_curr = page_items[next_idx][0].clone();
                let last_text = &last_prev.text;
                let first_text = format!("{} {}", first_curr.marker, first_curr.text);
                if !HAS_END_PUNCTUATION_RE.is_match(last_text)
                    && !STARTS_WITH_NUMBER_RE.is_match(&first_text)
                {
                    if let Some(prev) = page_items[i].last_mut() {
                        prev.text.push(' ');
                        prev.text.push_str(&first_curr.text);
                        prev.cross_page = true;
                    }
                    page_items[next_idx].remove(0);
                }
            }
        }

        // Pass 3：挂载到段落
        for (page_idx, bp) in body_page_nos.iter().enumerate() {
            let items = &page_items[page_idx];
            if items.is_empty() {
                continue;
            }

            let md = raw_page_by_no
                .get(bp)
                .map(|p| page_markdown_text(p))
                .unwrap_or_default();
            if md.is_empty() {
                continue;
            }

            let lines = split_lines(&md);
            let (band_start, _band_end) = detect_footnote_band(&lines);
            let body_lines = if band_start > 0 && band_start < lines.len() {
                &lines[..band_start]
            } else {
                &lines[..]
            };

            for item in items {
                let (attachment_kind, para_idx) = if item.cross_page {
                    ("cross_page_tail", body_lines.len().saturating_sub(1))
                } else {
                    match scan_body_lines_for_marker(body_lines, &item.marker) {
                        Some(idx) => ("anchor_matched", idx),
                        None => ("page_tail", body_lines.len().saturating_sub(1)),
                    }
                };

                all_records.push(ParagraphFootnoteRecord {
                    doc_id: doc_id.to_string(),
                    chapter_id: chapter_id.clone(),
                    page_no: *bp,
                    paragraph_index: para_idx as i64,
                    attachment_kind: attachment_kind.to_string(),
                    source_marker: item.marker.clone(),
                    text: item.text.clone(),
                });
            }
        }

        let footnote_item_count: usize = page_items.iter().map(|items| items.len()).sum();
        let cross_page_count: usize = page_items
            .iter()
            .flat_map(|items| items.iter())
            .filter(|item| item.cross_page)
            .count();

        let mut stats = serde_json::Map::new();
        stats.insert(
            "body_page_count".to_string(),
            serde_json::Value::Number(body_page_nos.len().into()),
        );
        stats.insert(
            "footnote_item_count".to_string(),
            serde_json::Value::Number(footnote_item_count.into()),
        );
        stats.insert(
            "cross_page_count".to_string(),
            serde_json::Value::Number(cross_page_count.into()),
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
