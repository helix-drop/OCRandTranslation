//! ←→ Python `document/text_processing.py::parse_page_markdown` (L615-843)
//! 及其全部 helper 函数（~25 个）。
//!
//! 单页 markdown 文本 → 段落结构解析（含跨页合并、OCR 修复、heading 检测）。

use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashSet;

use super::re_utils;

// ── 类型定义 ────────────────────────────────────────────────────

/// ←→ Python 合成页面结构（_synthetic_markdown_pages 输出元素）
#[derive(Debug, Clone, Default)]
pub struct SyntheticMarkdownPage {
    pub book_page: i64,
    pub file_idx: i64,
    pub markdown: String,
    pub footnotes: String,
    pub text_source: String,
    pub print_page_label: String,
    /// OCR blocks 数据（用于 fallback 和 heading 注入）
    pub blocks: Vec<PageBlock>,
}

/// ←→ Python 页面 block（OCR 解析产物）
#[derive(Debug, Clone, Default)]
pub struct PageBlock {
    pub text: String,
    pub label: String,
    pub heading_level: i64,
    pub is_meta: bool,
    pub x: Option<f64>,
}

/// ←→ Python `_get_page_note_scan` 返回结构
#[derive(Debug, Clone, Default)]
pub struct PageNoteScan {
    pub page_kind: String,
    pub note_start_line_index: Option<i64>,
    pub section_hints: Vec<String>,
    pub items: Vec<NoteScanItem>,
}

#[derive(Debug, Clone, Default)]
pub struct NoteScanItem {
    pub section_title: String,
    pub text: String,
}

/// ←→ Python `ParsedParagraph`（parse_page_markdown 输出元素）
#[derive(Debug, Clone, Default)]
pub struct ParsedParagraph {
    pub heading_level: i64,
    pub text: String,
    pub cross_page: Option<String>,
    pub consumed_by_prev: bool,
    pub start_bp: i64,
    pub end_bp: i64,
    pub print_page_label: String,
}

/// TOC heading 候选
#[derive(Debug, Clone)]
pub struct TocHeadingCandidate {
    pub title: String,
    pub depth: i64,
}

// ── regex 常量 ──────────────────────────────────────────────────

/// ←→ Python `_ALLCAPS_TITLE_RE`
static ALLCAPS_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^[A-Z\u{00c0}-\u{00d6}\u{00d8}-\u{00de}\s\-,':\u{00ab}\u{00bb}\u{201c}\u{201d}\.!?()]+$").unwrap()
});

/// ←→ Python `_LATEX_FOOTNOTE_MARK_RE` — LaTeX footnote 标记
static LATEX_FOOTNOTE_MARK_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\\textsuperscript\{(\d{1,6})\}").unwrap());

/// ←→ Python `_PLAIN_FOOTNOTE_MARK_RE` — 纯数字脚注引用
static PLAIN_FOOTNOTE_MARK_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\$\s*\^\{\s*(\d{1,6})\s*\}\s*\$").unwrap());

/// ←→ Python `_OBSIDIAN_FOOTNOTE_MARK_RE` — Obsidian 脚注引用 `[^12]`
static OBSIDIAN_FOOTNOTE_MARK_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\[\^(\d{1,6})\]").unwrap());

/// ←→ Python `_SUPERSCRIPT_FOOTNOTE_MARK_RE` — Unicode 上标数字
static SUPERSCRIPT_FOOTNOTE_MARK_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"[\u{2070}\u{00b9}\u{00b2}\u{00b3}\u{2074}\u{2075}\u{2076}\u{2077}\u{2078}\u{2079}]+").unwrap());

/// 上标数字 → 普通数字转换表
fn superscript_to_digit(c: char) -> Option<char> {
    match c {
        '\u{2070}' => Some('0'),
        '\u{00b9}' => Some('1'),
        '\u{00b2}' => Some('2'),
        '\u{00b3}' => Some('3'),
        '\u{2074}' => Some('4'),
        '\u{2075}' => Some('5'),
        '\u{2076}' => Some('6'),
        '\u{2077}' => Some('7'),
        '\u{2078}' => Some('8'),
        '\u{2079}' => Some('9'),
        _ => None,
    }
}

// ── 公共 helper ────────────────────────────────────────────────

/// 按 bookPage 查找页面。
/// ←→ Python `_find_page` (L346)
pub fn find_page<'a>(pages: &'a [SyntheticMarkdownPage], bp: i64) -> Option<&'a SyntheticMarkdownPage> {
    pages.iter().find(|p| p.book_page == bp)
}

/// ←→ Python `_get_page_note_scan` (L354)
pub fn get_page_note_scan(_page: &SyntheticMarkdownPage) -> PageNoteScan {
    // Python 版从 page["_note_scan"] 读取；Rust 端页面 note_scan
    // 数据由调用方传入或从 raw_pages.json 单独加载。当前返回空。
    PageNoteScan::default()
}

/// ←→ Python `_page_print_label` (L361)
pub fn page_print_label(page: Option<&SyntheticMarkdownPage>) -> String {
    match page {
        Some(p) if !p.print_page_label.is_empty() => p.print_page_label.clone(),
        _ => String::new(),
    }
}

/// ←→ Python `_segment_print_label` (L380)
pub fn segment_print_label(pages: &[SyntheticMarkdownPage], start_bp: i64, end_bp: i64) -> String {
    let start_label = page_print_label(find_page(pages, start_bp));
    if start_label.is_empty() {
        return String::new();
    }
    let end_label = page_print_label(find_page(pages, end_bp));
    if end_label.is_empty() || end_label == start_label {
        return start_label;
    }
    format!("{}-{}", start_label, end_label)
}

/// 将多种脚注引用标记标准化为 `[12]`。
/// ←→ Python `normalize_latex_footnote_markers` (L189)
pub fn normalize_latex_footnote_markers(text: &str) -> String {
    let raw = text.trim();
    if raw.is_empty() {
        return String::new();
    }
    let normalized = LATEX_FOOTNOTE_MARK_RE.replace_all(raw, r"[$1]");
    let normalized = PLAIN_FOOTNOTE_MARK_RE.replace_all(&normalized, r"[$1]");
    let normalized = OBSIDIAN_FOOTNOTE_MARK_RE.replace_all(&normalized, r"[$1]");

    SUPERSCRIPT_FOOTNOTE_MARK_RE
        .replace_all(&normalized, |caps: &regex::Captures| {
            let digits: String = caps[0]
                .chars()
                .filter_map(superscript_to_digit)
                .collect();
            if digits.chars().all(|c| c.is_ascii_digit()) {
                format!("[{}]", digits)
            } else {
                caps[0].to_string()
            }
        })
        .to_string()
}

/// 检测全大写标题，返回 heading_level（0=不是标题）。
/// ←→ Python `_looks_like_allcaps_title` (L27)
pub fn looks_like_allcaps_title(txt: &str) -> i64 {
    let clean = txt.trim();
    if clean.len() < 3 || clean.len() > 120 {
        return 0;
    }
    if !ALLCAPS_TITLE_RE.is_match(clean) {
        return 0;
    }
    // 排除含中文的行
    if Regex::new(r"[\u{4e00}-\u{9fff}\u{3000}-\u{303f}]").unwrap().is_match(clean) {
        return 0;
    }
    if Regex::new(r"^[\W\d\s]+$").unwrap().is_match(clean) {
        return 0;
    }
    let letters = clean.chars().filter(|c| c.is_alphabetic()).count();
    if (letters as f64) / (clean.len() as f64).max(1.0) < 0.6 {
        return 0;
    }
    let words: Vec<&str> = clean
        .split_whitespace()
        .filter(|w| w.len() > 1 && w.chars().all(|c| c.is_alphabetic()))
        .collect();
    if words.len() < 2 {
        return 0;
    }
    if re_utils::has_explicit_sentence_end(clean) && clean.len() > 60 {
        return 0;
    }
    3
}

/// ←→ Python `_normalize_heading_key` (L392)
pub fn normalize_heading_key(text: &str) -> String {
    let folded = text.to_lowercase();
    // NFKD 近似：去重音符号
    let ascii: String = folded
        .chars()
        .filter_map(|c| {
            if c.is_ascii_alphanumeric() {
                Some(c)
            } else if "àâäéèêëïîôùûüÿçœæ".contains(c) {
                // 法语字符映射到基础 ASCII
                match c {
                    'à' | 'â' | 'ä' => Some('a'),
                    'é' | 'è' | 'ê' | 'ë' => Some('e'),
                    'ï' | 'î' => Some('i'),
                    'ô' => Some('o'),
                    'ù' | 'û' | 'ü' => Some('u'),
                    'ÿ' => Some('y'),
                    'ç' => Some('c'),
                    'œ' => Some('o'),
                    'æ' => Some('a'),
                    _ => None,
                }
            } else {
                None
            }
        })
        .collect();
    Regex::new(r"[^a-z0-9]+").unwrap().replace_all(&ascii, "").to_string()
}

/// ←→ Python `_heading_titles_match` (L398)
pub fn heading_titles_match(lhs: &str, rhs: &str) -> bool {
    let left = normalize_heading_key(lhs);
    let right = normalize_heading_key(rhs);
    if left.is_empty() || right.is_empty() {
        return false;
    }
    if left == right {
        return true;
    }
    if left.contains(&right) || right.contains(&left) {
        return left.len().min(right.len()) >= 16;
    }
    // SequenceMatcher ratio 简化版：用较长公共前缀/平均长度近似
    let min_len = left.len().min(right.len());
    let max_len = left.len().max(right.len());
    let common = left.chars().zip(right.chars()).take_while(|(a, b)| a == b).count();
    (common as f64) / (max_len as f64) >= 0.72 && min_len >= 8
}

/// ←→ Python `_looks_like_colon_section_title` (L846)
pub fn looks_like_colon_section_title(text: &str) -> bool {
    let t = text.trim();
    if !(8..=160).contains(&t.len()) {
        return false;
    }
    if t.ends_with('.') || t.ends_with('!') || t.ends_with('?') {
        return false;
    }
    if t.matches(':').count() != 1 {
        return false;
    }
    let parts: Vec<&str> = t.splitn(2, ':').collect();
    let left = parts[0].trim();
    let right = parts[1].trim();
    if left.split_whitespace().count() < 2 || right.split_whitespace().count() < 1 {
        return false;
    }
    left.starts_with(|c: char| c.is_uppercase()) && right.starts_with(|c: char| c.is_uppercase())
}

/// ←→ Python `_looks_like_block_heading_candidate` (L445)
pub fn looks_like_block_heading_candidate(text: &str) -> bool {
    let clean = Regex::new(r"\s+")
        .unwrap()
        .replace_all(&normalize_latex_footnote_markers(text), " ")
        .trim()
        .to_string();
    let probe = Regex::new(r"^\d+[\.\)]\s*")
        .unwrap()
        .replace(&clean, "")
        .to_string();
    if !(8..=120).contains(&probe.len()) {
        return false;
    }
    if probe.ends_with('.') || probe.ends_with('!') || probe.ends_with('?') {
        return false;
    }
    if probe.matches(':').count() > 1 {
        return false;
    }
    if probe.matches(',').count() > 1 || probe.contains(';') {
        return false;
    }
    if probe.split_whitespace().count() > 18 {
        return false;
    }
    let letters = probe.chars().filter(|c| c.is_alphabetic()).count();
    if (letters as f64) / (probe.len() as f64).max(1.0) < 0.55 {
        return false;
    }
    let first_char = probe.chars().next().unwrap();
    if !(first_char.is_uppercase() || clean.starts_with(|c: char| c.is_ascii_digit())) {
        return false;
    }
    true
}

/// ←→ Python `_inject_block_heading_candidates` (L466)
pub fn inject_block_heading_candidates(
    page: &SyntheticMarkdownPage,
    segments: Vec<ParsedParagraph>,
    bp: i64,
) -> Vec<ParsedParagraph> {
    let blocks = &page.blocks;
    if blocks.is_empty() {
        return segments;
    }

    let existing_texts: Vec<String> = segments.iter().map(|s| s.text.trim().to_string()).collect();

    let mut candidates: Vec<(usize, String)> = Vec::new();
    for (idx, block) in blocks.iter().enumerate() {
        if block.label != "paragraph_title" {
            continue;
        }
        let title = Regex::new(r"\s+")
            .unwrap()
            .replace_all(&normalize_latex_footnote_markers(&block.text), " ")
            .trim()
            .to_string();
        if !looks_like_block_heading_candidate(&title) {
            continue;
        }
        if existing_texts.iter().any(|e| heading_titles_match(&title, e)) {
            continue;
        }

        let mut anchor_text = String::new();
        for next_block in blocks[idx + 1..].iter() {
            if next_block.label == "paragraph_title" {
                continue;
            }
            anchor_text = Regex::new(r"\s+")
                .unwrap()
                .replace_all(&normalize_latex_footnote_markers(&next_block.text), " ")
                .trim()
                .to_string();
            if anchor_text.len() >= 20 {
                break;
            }
            anchor_text.clear();
        }

        let insert_at = if !anchor_text.is_empty() {
            let anchor_key = &normalize_heading_key(&anchor_text.chars().take(80).collect::<String>())[..40.min(normalize_heading_key(&anchor_text.chars().take(80).collect::<String>()).len())];
            segments
                .iter()
                .position(|seg| {
                    !anchor_key.is_empty()
                        && normalize_heading_key(&seg.text).contains(anchor_key)
                })
                .unwrap_or(segments.len())
        } else {
            segments.len()
        };

        candidates.push((insert_at, title));
    }

    if candidates.is_empty() {
        return segments;
    }

    candidates.sort_by_key(|(pos, _)| *pos);
    let mut expanded = segments;
    let mut offset = 0;
    for (insert_at, title) in candidates {
        expanded.insert(
            insert_at + offset,
            ParsedParagraph {
                heading_level: 2,
                text: title,
                start_bp: bp,
                end_bp: bp,
                ..Default::default()
            },
        );
        offset += 1;
    }
    expanded
}

/// ←→ Python `_extract_note_page_heading_lines` (L518)
pub fn extract_note_page_heading_lines(
    _note_scan: &PageNoteScan,
    raw_note_lines: &[String],
) -> Vec<String> {
    let mut headings: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();

    let mut add = |line: &str| {
        let stripped = normalize_latex_footnote_markers(line).trim().to_string();
        if stripped.is_empty() {
            return;
        }
        let (hl, clean) = re_utils::extract_heading_level(&stripped);
        if hl <= 0 {
            return;
        }
        let normalized = format!("{} {}", "#".repeat(hl as usize), clean);
        if seen.insert(normalized.clone()) {
            headings.push(normalized);
        }
    };

    for line in raw_note_lines {
        add(line);
    }
    headings
}

/// ←→ Python `_prepare_markdown_for_note_page` (L546)
pub fn prepare_markdown_for_note_page(md: &str, note_scan: &PageNoteScan) -> String {
    if note_scan.note_start_line_index.is_none()
        || (note_scan.page_kind != "endnote_collection"
            && note_scan.page_kind != "mixed_body_endnotes")
    {
        return md.trim().to_string();
    }
    let raw_lines: Vec<String> = md.lines().map(|l| l.to_string()).collect();
    let start_idx = note_scan.note_start_line_index.unwrap_or(0).max(0) as usize;
    let mut kept_lines: Vec<String> = if note_scan.page_kind == "mixed_body_endnotes" {
        raw_lines[..start_idx.min(raw_lines.len())].to_vec()
    } else {
        Vec::new()
    };
    let heading_lines =
        extract_note_page_heading_lines(note_scan, &raw_lines[start_idx.min(raw_lines.len())..]);
    if !kept_lines.is_empty()
        && !heading_lines.is_empty()
        && kept_lines.last().map_or(false, |l| !l.trim().is_empty())
    {
        kept_lines.push(String::new());
    }
    kept_lines.extend(heading_lines);
    kept_lines.join("\n").trim().to_string()
}

/// ←→ Python `_parse_md_lines_to_segments` (L568)
pub fn parse_md_lines_to_segments(lines: &[String], bp: i64) -> Vec<ParsedParagraph> {
    #[derive(Debug)]
    enum LineItem {
        Blank,
        Heading { level: i64, text: String },
        Text(String),
    }

    let mut items: Vec<LineItem> = Vec::new();
    for line in lines {
        let stripped = normalize_latex_footnote_markers(line);
        if stripped.is_empty() {
            items.push(LineItem::Blank);
            continue;
        }
        if re_utils::is_meta_line(&stripped) {
            continue;
        }
        let (hl, clean) = re_utils::extract_heading_level(&stripped);
        if hl > 0 {
            items.push(LineItem::Heading {
                level: hl,
                text: clean,
            });
        } else {
            items.push(LineItem::Text(stripped));
        }
    }

    let mut segments: Vec<ParsedParagraph> = Vec::new();
    let mut buf: Vec<String> = Vec::new();

    let flush = |buf: &mut Vec<String>, segments: &mut Vec<ParsedParagraph>, bp: i64| {
        if !buf.is_empty() {
            let combined = buf.join(" ");
            if combined.trim().len() > 1 {
                segments.push(ParsedParagraph {
                    heading_level: 0,
                    text: combined.trim().to_string(),
                    start_bp: bp,
                    end_bp: bp,
                    ..Default::default()
                });
            }
            buf.clear();
        }
    };

    for item in items {
        match item {
            LineItem::Heading { level, text } => {
                flush(&mut buf, &mut segments, bp);
                segments.push(ParsedParagraph {
                    heading_level: level,
                    text,
                    start_bp: bp,
                    end_bp: bp,
                    ..Default::default()
                });
            }
            LineItem::Text(t) => {
                buf.push(t);
            }
            LineItem::Blank => {
                flush(&mut buf, &mut segments, bp);
            }
        }
    }
    flush(&mut buf, &mut segments, bp);
    segments
}

/// ←→ Python `_parse_single_page_md` (L865)
pub fn parse_single_page_md(
    _pg: Option<&SyntheticMarkdownPage>,
    md: &str,
    bp: i64,
) -> Vec<ParsedParagraph> {
    if md.is_empty() {
        return Vec::new();
    }
    let lines: Vec<String> = md.lines().map(|l| l.to_string()).collect();
    parse_md_lines_to_segments(&lines, bp)
        .into_iter()
        .map(|s| ParsedParagraph {
            heading_level: s.heading_level,
            text: s.text,
            ..Default::default()
        })
        .collect()
}

/// ←→ Python `_fallback_blocks_to_paragraphs` (L914)
pub fn fallback_blocks_to_paragraphs(page: &SyntheticMarkdownPage, bp: i64) -> Vec<ParsedParagraph> {
    let mut raw: Vec<ParsedParagraph> = Vec::new();
    for block in &page.blocks {
        let txt = normalize_latex_footnote_markers(&block.text);
        if txt.len() < 2 {
            continue;
        }
        if block.is_meta {
            continue;
        }
        let mut hl = block.heading_level;
        let label = &block.label;

        if hl == 0 && label == "doc_title" {
            hl = 1;
        } else if hl == 0 && label == "paragraph_title" {
            hl = 2;
        }

        let lines: Vec<&str> = txt.lines().collect();
        let clean_lines: Vec<&str> = lines
            .iter()
            .filter(|l| !l.trim().is_empty() && !re_utils::is_meta_line(l.trim()))
            .copied()
            .collect();
        let clean_text = clean_lines
            .iter()
            .map(|l| l.trim())
            .collect::<Vec<_>>()
            .join(" ")
            .trim()
            .to_string();
        if clean_text.is_empty() {
            continue;
        }

        let (real_hl, clean) = re_utils::extract_heading_level(&clean_text);
        let final_hl = if real_hl > 0 { real_hl } else { hl };

        raw.push(ParsedParagraph {
            heading_level: final_hl,
            text: clean,
            start_bp: bp,
            end_bp: bp,
            ..Default::default()
        });
    }

    let mut merged: Vec<ParsedParagraph> = Vec::new();
    for seg in raw {
        let hl = seg.heading_level;
        let txt = &seg.text;
        let is_short = hl == 0
            && txt.len() < 60
            && !Regex::new(r"[.;!?\u{3002}\u{ff1b}\u{ff01}\u{ff1f}]$")
                .unwrap()
                .is_match(txt.trim());
        let is_paren = hl == 0 && Regex::new(r"^\([^)]+\)$").unwrap().is_match(txt.trim());

        if (is_short || is_paren) && !merged.is_empty() {
            let prev = merged.last_mut().unwrap();
            if prev.heading_level > 0 {
                prev.text = format!("{}\n{}", prev.text, txt);
            } else {
                prev.text = format!("{} {}", prev.text, txt);
            }
        } else {
            merged.push(ParsedParagraph {
                heading_level: hl,
                text: txt.clone(),
                start_bp: bp,
                end_bp: bp,
                ..Default::default()
            });
        }
    }
    merged
}

/// ←→ Python `_visible_paragraphs` (L564)
pub fn visible_paragraphs(paragraphs: &[ParsedParagraph]) -> Vec<ParsedParagraph> {
    paragraphs
        .iter()
        .filter(|p| !p.consumed_by_prev)
        .cloned()
        .collect()
}

// ── 主入口 ──────────────────────────────────────────────────────

/// 逐页解析 markdown 文本，返回段落结构。
///
/// ←→ Python `document/text_processing.py::parse_page_markdown` (L615-843)
///
/// 完整 5 步流程：
/// 1. 页面定位 + markdown 预处理（note 页过滤）
/// 2. 行级解析（`_parse_md_lines_to_segments`）
/// 3. 智能合并（标题合并、OCR 断裂、短碎片）
/// 4. 跨页检测（cont_prev / cont_next / cont_both / merged_next 链）
/// 5. 跨页段落处理（consumed_by_prev 标记）
pub fn parse_page_markdown(
    pages: &[SyntheticMarkdownPage],
    bp: i64,
    toc_heading_candidates: &[TocHeadingCandidate],
) -> Vec<ParsedParagraph> {
    // Step 1: 页面定位
    let cur = match find_page(pages, bp) {
        Some(p) => p,
        None => return Vec::new(),
    };

    let md = cur.markdown.trim().to_string();
    if md.is_empty() {
        return fallback_blocks_to_paragraphs(cur, bp);
    }

    let note_scan = get_page_note_scan(cur);
    let prepared_md = prepare_markdown_for_note_page(&md, &note_scan);
    if prepared_md.is_empty() {
        return Vec::new();
    }

    // 前后页 markdown（用于跨页检测）
    let prev_page = find_page(pages, bp - 1);
    let next_page = find_page(pages, bp + 1);
    let prev_raw_md = prev_page.map_or(String::new(), |p| p.markdown.trim().to_string());
    let next_raw_md = next_page.map_or(String::new(), |p| p.markdown.trim().to_string());
    let prev_note_scan = prev_page.map(|p| get_page_note_scan(p)).unwrap_or_default();
    let next_note_scan = next_page.map(|p| get_page_note_scan(p)).unwrap_or_default();
    let prev_md = prepare_markdown_for_note_page(&prev_raw_md, &prev_note_scan);
    let next_md = prepare_markdown_for_note_page(&next_raw_md, &next_note_scan);

    // Step 2: 行级解析
    let lines: Vec<String> = prepared_md.lines().map(|l| l.to_string()).collect();
    let raw_segments = parse_md_lines_to_segments(&lines, bp);
    if raw_segments.is_empty() {
        return fallback_blocks_to_paragraphs(cur, bp);
    }

    // Step 3: 智能合并
    let is_ocr_line_break = |prev_text: &str, cur_text: &str| -> bool {
        let pt = prev_text.trim_end();
        let ct = cur_text.trim_start();
        if pt.is_empty() || ct.is_empty() {
            return false;
        }
        if pt.ends_with('-') {
            return true;
        }
        if !re_utils::has_explicit_sentence_end(pt) && ct.starts_with(|c: char| c.is_lowercase()) {
            return true;
        }
        if pt.ends_with(',') {
            return true;
        }
        false
    };

    let mut merged: Vec<ParsedParagraph> = Vec::new();
    for seg in raw_segments {
        let mut hl = seg.heading_level;
        let txt = seg.text;

        let effective_hl = if hl == 0 {
            looks_like_allcaps_title(&txt)
        } else {
            hl
        };
        if effective_hl > 0 {
            hl = effective_hl;
        }

        // 连续标题合并
        if hl > 0 && !merged.is_empty() && merged.last().unwrap().heading_level > 0 {
            let prev_hl = merged.last().unwrap().heading_level;
            let prev_txt = merged.last().unwrap().text.clone();
            let should_merge = if prev_hl == hl
                && ALLCAPS_TITLE_RE.is_match(prev_txt.trim())
                && ALLCAPS_TITLE_RE.is_match(txt.trim())
            {
                true
            } else if prev_hl == hl
                && Regex::new(r"^[IVXLC]+$").unwrap().is_match(prev_txt.trim())
            {
                true
            } else if txt.trim().len() <= 3 {
                let last = merged.last_mut().unwrap();
                last.text = format!("{} {}", prev_txt, txt);
                continue;
            } else if txt.trim().starts_with(|c: char| c.is_lowercase()) {
                true
            } else {
                false
            };

            if should_merge {
                let last = merged.last_mut().unwrap();
                last.text = format!("{} {}", prev_txt, txt);
                last.heading_level = prev_hl.min(hl);
                continue;
            }
        }

        // OCR 行间断裂合并
        if hl == 0 && !merged.is_empty() && merged.last().unwrap().heading_level == 0 {
            let prev_text = merged.last().unwrap().text.clone();
            if is_ocr_line_break(&prev_text, &txt) {
                let last = merged.last_mut().unwrap();
                if prev_text.trim_end().ends_with('-') {
                    last.text = format!(
                        "{}{}",
                        prev_text.trim_end().trim_end_matches('-'),
                        txt.trim_start()
                    );
                } else {
                    last.text = format!("{} {}", prev_text, txt);
                }
                continue;
            }
        }

        // 短碎片合并
        let mut is_short = hl == 0
            && txt.len() < 60
            && !re_utils::has_explicit_sentence_end(txt.trim());
        if hl == 0 && Regex::new(r"^\([^)]+\)$").unwrap().is_match(txt.trim()) {
            is_short = true;
        }

        if is_short && !merged.is_empty() {
            let last = merged.last_mut().unwrap();
            if last.heading_level > 0 {
                last.text = format!("{}\n{}", last.text, txt);
            } else {
                last.text = format!("{} {}", last.text, txt);
            }
        } else if is_short && merged.is_empty() {
            merged.push(ParsedParagraph {
                heading_level: 0,
                text: txt.clone(),
                start_bp: bp,
                end_bp: bp,
                ..Default::default()
            });
        } else {
            merged.push(ParsedParagraph {
                heading_level: hl,
                text: txt.clone(),
                start_bp: bp,
                end_bp: bp,
                ..Default::default()
            });
        }
    }

    // 注入 block heading candidates
    let merged = inject_block_heading_candidates(cur, merged, bp);

    // TOC heading 匹配：如果首段无 heading，尝试用 TOC 补
    let mut merged = merged;
    if !merged.is_empty() && merged[0].heading_level == 0 {
        for toc_item in toc_heading_candidates {
            if heading_titles_match(&merged[0].text, &toc_item.title) {
                merged[0].heading_level = 1.max(6.min(toc_item.depth + 1));
                if toc_item.title.len() >= merged[0].text.trim().len() {
                    merged[0].text = toc_item.title.clone();
                }
                break;
            }
        }
    }

    // Step 4: 跨页检测
    let prev_single = parse_single_page_md(prev_page, &prev_md, bp - 1);
    let next_single = parse_single_page_md(next_page, &next_md, bp + 1);

    let is_joinable_cross_page =
        |pg: Option<&SyntheticMarkdownPage>, para: &ParsedParagraph| -> bool {
            if para.heading_level > 0 {
                return false;
            }
            let text = para.text.trim();
            if text.is_empty() {
                return false;
            }
            if looks_like_allcaps_title(text) > 0 {
                return false;
            }
            if looks_like_colon_section_title(text) {
                return false;
            }
            match pg {
                Some(p) => {
                    get_page_note_scan(p).page_kind != "endnote_collection"
                }
                None => false,
            }
        };

    let is_cross_page_continuation =
        |prev_text: &str, next_para: &ParsedParagraph, next_pg: Option<&SyntheticMarkdownPage>| {
            if !is_joinable_cross_page(next_pg, next_para) {
                return false;
            }
            re_utils::is_mid_sentence_continuation(
                prev_text,
                &next_para.text,
                true,
            )
        };

    let mut result: Vec<ParsedParagraph> = Vec::new();
    for (i, seg) in merged.iter().enumerate() {
        let hl = seg.heading_level;
        let txt = &seg.text;
        let mut cross_page: Option<String> = None;

        if i == 0 && hl == 0 {
            if let Some(prev_last) = prev_single.last() {
                if is_joinable_cross_page(prev_page, seg)
                    && is_cross_page_continuation(&prev_last.text, seg, Some(cur))
                {
                    cross_page = Some("cont_prev".to_string());
                }
            }
        }
        if i == merged.len() - 1 && hl == 0 {
            if let Some(next_first) = next_single.first() {
                if is_cross_page_continuation(txt, next_first, next_page) {
                    cross_page = if cross_page.as_deref() == Some("cont_prev") {
                        Some("cont_both".to_string())
                    } else {
                        Some("cont_next".to_string())
                    };
                }
            }
        }

        result.push(ParsedParagraph {
            heading_level: hl,
            text: txt.clone(),
            cross_page,
            consumed_by_prev: false,
            start_bp: seg.start_bp,
            end_bp: seg.end_bp,
            ..Default::default()
        });
    }

    // Step 5: 跨页段落处理
    // cont_prev → consumed_by_prev
    if !result.is_empty() && result[0].cross_page.as_deref() == Some("cont_prev")
        || result[0].cross_page.as_deref() == Some("cont_both")
    {
        let prev_absorbs_current = if result.len() > 1 {
            true
        } else if let Some(prev_last) = prev_single.last() {
            is_cross_page_continuation(&prev_last.text, &result[0], Some(cur))
        } else {
            false
        };
        if prev_absorbs_current {
            result[0].consumed_by_prev = true;
        } else {
            result[0].cross_page = None;
        }
    }

    // cont_next / merged_next 链式扫描
    if !result.is_empty() && result.last().unwrap().cross_page.as_deref() == Some("cont_next") {
        let mut chain_texts: Vec<String> = Vec::new();
        let mut scan_bp = bp + 1;
        let mut scan_pg = next_page;
        let mut scan_md = next_md.clone();
        let mut last_merged_bp = result.last().unwrap().end_bp;
        let mut current_tail = result.last().unwrap().text.clone();

        while let Some(pg) = scan_pg {
            if scan_md.is_empty() {
                break;
            }
            let scan_paras = parse_single_page_md(Some(pg), &scan_md, scan_bp);
            if scan_paras.is_empty() {
                break;
            }
            let first_para = &scan_paras[0];
            if !is_cross_page_continuation(&current_tail, first_para, Some(pg)) {
                break;
            }
            chain_texts.push(first_para.text.clone());
            last_merged_bp = pg.book_page;
            current_tail = first_para.text.clone();
            scan_bp = pg.book_page + 1;
            scan_pg = find_page(pages, scan_bp);
            let next_raw = scan_pg.map_or(String::new(), |p| p.markdown.trim().to_string());
            let next_ns = scan_pg.map(|p| get_page_note_scan(p)).unwrap_or_default();
            scan_md = prepare_markdown_for_note_page(&next_raw, &next_ns);
        }

        if !chain_texts.is_empty() {
            let last = result.last_mut().unwrap();
            last.text = format!("{} {}", last.text, chain_texts.join(" "));
            last.cross_page = Some("merged_next".to_string());
            last.end_bp = last_merged_bp;
        }
    }

    // printPageLabel
    for item in result.iter_mut() {
        let start = item.start_bp;
        let end = item.end_bp.max(start);
        item.print_page_label = segment_print_label(pages, start, end);
    }

    result
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_page(book_page: i64, markdown: &str) -> SyntheticMarkdownPage {
        SyntheticMarkdownPage {
            book_page,
            markdown: markdown.to_string(),
            print_page_label: book_page.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn test_find_page_found() {
        let pages = vec![make_page(1, "a"), make_page(2, "b")];
        assert!(find_page(&pages, 1).is_some());
        assert!(find_page(&pages, 3).is_none());
    }

    #[test]
    fn test_normalize_latex_footnote_markers_textsuperscript() {
        let result = normalize_latex_footnote_markers(r"\textsuperscript{12}");
        assert_eq!(result, "[12]");
    }

    #[test]
    fn test_normalize_latex_footnote_markers_plain() {
        let result = normalize_latex_footnote_markers("$ ^{12} $");
        assert_eq!(result, "[12]");
    }

    #[test]
    fn test_looks_like_allcaps_title_valid() {
        assert_eq!(looks_like_allcaps_title("THE BIRTH OF BIOPOLITICS"), 3);
    }

    #[test]
    fn test_looks_like_allcaps_title_not() {
        assert_eq!(looks_like_allcaps_title("This is just normal text"), 0);
    }

    #[test]
    fn test_heading_titles_match_exact() {
        assert!(heading_titles_match("Introduction", "Introduction"));
    }

    #[test]
    fn test_heading_titles_match_substring() {
        // "introduction" contained in "introduction generale" has len 12, need >= 16 for match
        assert!(!heading_titles_match("Introduction", "Introduction Generale"));
    }

    #[test]
    fn test_looks_like_colon_section_valid() {
        assert!(looks_like_colon_section_title(
            "Self-Contained Persons: The Odd Trio"
        ));
    }

    #[test]
    fn test_looks_like_colon_section_short() {
        assert!(!looks_like_colon_section_title("A: B"));
    }

    #[test]
    fn test_parse_md_lines_basic() {
        let lines: Vec<String> = vec![
            "# Title".to_string(),
            String::new(),
            "Body text line 1".to_string(),
            "Body text line 2".to_string(),
        ];
        let result = parse_md_lines_to_segments(&lines, 1);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].heading_level, 1);
        assert_eq!(result[1].heading_level, 0);
    }

    #[test]
    fn test_parse_page_markdown_basic() {
        let pages = vec![make_page(1, "# Hello\n\nWorld text.")];
        let result = parse_page_markdown(&pages, 1, &[]);
        assert!(!result.is_empty());
        assert_eq!(result[0].heading_level, 1);
        assert_eq!(result[0].text, "Hello");
    }

    #[test]
    fn test_parse_page_markdown_empty() {
        let result = parse_page_markdown(&[], 1, &[]);
        assert!(result.is_empty());
    }

    #[test]
    fn test_fallback_blocks_to_paragraphs_basic() {
        let page = SyntheticMarkdownPage {
            book_page: 1,
            blocks: vec![PageBlock {
                text: "Sample block text".to_string(),
                heading_level: 0,
                ..Default::default()
            }],
            ..Default::default()
        };
        let result = fallback_blocks_to_paragraphs(&page, 1);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].text, "Sample block text");
    }

    #[test]
    fn test_prepare_markdown_for_note_page_no_note() {
        let md = "# Title\n\nBody text";
        let result = prepare_markdown_for_note_page(md, &PageNoteScan::default());
        assert_eq!(result, md);
    }

    #[test]
    fn test_segment_print_label_same() {
        let pages = vec![make_page(1, "a"), make_page(2, "b")];
        let label = segment_print_label(&pages, 1, 1);
        assert_eq!(label, "1");
    }

    #[test]
    fn test_segment_print_label_range() {
        let pages = vec![make_page(1, "a"), make_page(5, "b")];
        let label = segment_print_label(&pages, 1, 5);
        assert_eq!(label, "1-5");
    }
}
