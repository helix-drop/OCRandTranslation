//! ←→ FNM_RE/stages/note_items.py
//! 多源页文本归一化 + 章共享页切分 + section title fuzzy 匹配。
//!
//! Python 端这些 helper 让 build_note_items 在面对以下情况时仍能正确切出区段：
//!
//! 1. 多章共享同一物理页（章末 + 下章首页 + endnote heading 都在一页）
//! 2. OCR 截断的 section_title（用 fuzzy 前缀匹配兜底）
//! 3. footnote/endnote/PDF 多源文本（先 page_text_map → footnotes → markdown → pdf_text）

use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{ChapterRecord, NoteRegionRecord};
use fnm_core::text::page_markdown_text;
use fnm_core::title::chapter_title_match_key;
use fnm_core::types::NoteKind;
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::{HashMap, HashSet};

static MARKDOWN_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s{0,3}#{1,6}\s*(.+?)\s*$").unwrap());

// ── section title key ───────────────────────────────────────────

/// ←→ Python `_section_title_key`
pub fn section_title_key(value: &str) -> String {
    let text = value.trim();
    if text.is_empty() {
        return String::new();
    }
    let cleaned = MARKDOWN_HEADING_RE
        .captures(text)
        .and_then(|c| c.get(1))
        .map(|m| m.as_str().trim().to_string())
        .unwrap_or_else(|| text.to_string());
    chapter_title_match_key(&cleaned)
}

// ── chapter title 索引 ──────────────────────────────────────────

/// ←→ Python `_chapter_title_by_id`
pub fn chapter_title_by_id(chapters: &[ChapterRecord]) -> HashMap<String, String> {
    chapters
        .iter()
        .filter(|ch| !ch.chapter_id.is_empty())
        .map(|ch| (ch.chapter_id.clone(), ch.title.trim().to_string()))
        .collect()
}

/// ←→ Python `_region_title_keys`
pub fn region_title_keys(
    region: &NoteRegionRecord,
    chapter_title_by_id: &HashMap<String, String>,
) -> HashSet<String> {
    let mut keys: HashSet<String> = HashSet::new();
    let k1 = section_title_key(&region.heading_text);
    if !k1.is_empty() {
        keys.insert(k1);
    }
    if let Some(title) = chapter_title_by_id.get(&region.chapter_id) {
        let k2 = section_title_key(title);
        if !k2.is_empty() {
            keys.insert(k2);
        }
    }
    keys
}

/// ←→ Python `_all_chapter_title_keys`
pub fn all_chapter_title_keys(chapter_title_by_id: &HashMap<String, String>) -> HashSet<String> {
    chapter_title_by_id
        .values()
        .map(|t| section_title_key(t))
        .filter(|k| !k.is_empty())
        .collect()
}

// ── fuzzy title key match ───────────────────────────────────────

static LEADING_DIGIT_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\d+").unwrap());

/// ←→ Python `_title_key_matches`
/// 4 种匹配策略：完全相等 / 目标移除前导数字后相等 / 候选 ≥6 字符且 line 以候选起始 /
/// line ≥12 字符且候选以 line 起始。
pub fn title_key_matches(line_key: &str, target_key: &str) -> bool {
    if line_key.is_empty() || target_key.is_empty() {
        return false;
    }
    let stripped = LEADING_DIGIT_RE.replace(target_key, "").to_string();
    let candidates: Vec<&str> = vec![target_key, stripped.as_str()];
    for candidate in candidates {
        if candidate.is_empty() {
            continue;
        }
        if line_key == candidate {
            return true;
        }
        if candidate.chars().count() >= 6 && line_key.starts_with(candidate) {
            return true;
        }
        if line_key.chars().count() >= 12 && candidate.starts_with(line_key) {
            return true;
        }
    }
    false
}

// ── markdown heading index 扫描 ──────────────────────────────────

/// ←→ Python `_matching_markdown_heading_indices`
/// 返回 (current_region_indices, any_chapter_indices)。
pub fn matching_markdown_heading_indices(
    text: &str,
    target_keys: &HashSet<String>,
    all_title_keys: &HashSet<String>,
) -> (Vec<usize>, Vec<usize>) {
    let mut current: Vec<usize> = Vec::new();
    let mut any_chapter: Vec<usize> = Vec::new();
    for (idx, line) in text.lines().enumerate() {
        if !MARKDOWN_HEADING_RE.is_match(line) {
            continue;
        }
        let line_key = section_title_key(line);
        if line_key.is_empty() {
            continue;
        }
        if target_keys
            .iter()
            .any(|tk| title_key_matches(&line_key, tk))
        {
            current.push(idx);
        }
        if all_title_keys
            .iter()
            .any(|tk| title_key_matches(&line_key, tk))
        {
            any_chapter.push(idx);
        }
    }
    (current, any_chapter)
}

// ── 共享页文本切分 ──────────────────────────────────────────────

/// ←→ Python `_split_shared_page_text_for_region`
/// 返回 (sliced_text, did_split)。
pub fn split_shared_page_text_for_region(
    text: &str,
    region: &NoteRegionRecord,
    chapter_title_by_id: &HashMap<String, String>,
) -> (String, bool) {
    let lines: Vec<&str> = text.lines().collect();
    if lines.is_empty() {
        return (String::new(), false);
    }
    let target_keys = region_title_keys(region, chapter_title_by_id);
    let all_title_keys = all_chapter_title_keys(chapter_title_by_id);
    if target_keys.is_empty() || all_title_keys.is_empty() {
        return (text.to_string(), false);
    }
    let (current_indices, any_indices) =
        matching_markdown_heading_indices(text, &target_keys, &all_title_keys);
    if let Some(&first_current) = current_indices.first() {
        return (lines[first_current..].join("\n").trim().to_string(), true);
    }
    if let Some(&first_any) = any_indices.first() {
        return (lines[..first_any].join("\n").trim().to_string(), true);
    }
    (text.to_string(), false)
}

// ── 多源文本归一化 ─────────────────────────────────────────────

/// ←→ Python `_normalized_page_text`
/// 优先级：page_text_map → footnotes（footnote kind）→ markdown → pdf_text。
/// 返回 (text, source_label)。
pub fn normalized_page_text(
    page_no: i64,
    note_kind: NoteKind,
    page: Option<&RawPage>,
    page_text_map: &HashMap<i64, String>,
    pdf_text_by_page: &HashMap<i64, String>,
) -> (String, String) {
    if let Some(mapped) = page_text_map.get(&page_no) {
        let t = mapped.trim().to_string();
        if !t.is_empty() {
            return (t, "page_text_map".into());
        }
    }
    if note_kind == NoteKind::Footnote {
        if let Some(p) = page {
            let footnotes = p.footnotes.trim();
            if !footnotes.is_empty() {
                return (footnotes.to_string(), "footnotes".into());
            }
        }
    }
    if let Some(p) = page {
        let md = page_markdown_text(&p.pruned_result);
        if !md.trim().is_empty() {
            // 当 pruned_result 没有 markdown 时降级到顶层 markdown 字段
            return (md, "markdown".into());
        }
        if !p.markdown.trim().is_empty() {
            return (p.markdown.clone(), "markdown".into());
        }
    }
    if let Some(pdf) = pdf_text_by_page.get(&page_no) {
        let t = pdf.trim().to_string();
        if !t.is_empty() {
            return (t, "pdf_text".into());
        }
    }
    (String::new(), String::new())
}

// ── 行级 marker 序列工具 ───────────────────────────────────────

/// ←→ Python `_last_numeric_marker_value`
pub fn last_numeric_marker_value(markers: &[String], default: Option<i64>) -> Option<i64> {
    let mut current = default;
    for marker in markers {
        let normalized = normalize_note_marker(marker);
        if let Ok(v) = normalized.parse::<i64>() {
            current = Some(v);
        }
    }
    current
}

// ── shared page rows 过滤 ──────────────────────────────────────

/// ←→ Python `_filter_shared_page_rows_for_region`
/// rows = Vec<(section_title, ...)>，返回属于本 region 的子集。
pub fn filter_shared_page_rows_for_region<T, F>(
    rows: Vec<T>,
    region: &NoteRegionRecord,
    chapter_title_by_id: &HashMap<String, String>,
    section_title_of: F,
) -> Vec<T>
where
    F: Fn(&T) -> String,
{
    let section_keys: HashSet<String> = rows
        .iter()
        .map(|r| section_title_key(&section_title_of(r)))
        .filter(|k| !k.is_empty())
        .collect();
    if section_keys.is_empty() {
        return rows;
    }
    let target_keys = region_title_keys(region, chapter_title_by_id);
    let matched_keys: HashSet<String> = section_keys
        .iter()
        .filter(|sk| target_keys.iter().any(|tk| title_key_matches(sk, tk)))
        .cloned()
        .collect();
    if !matched_keys.is_empty() {
        rows.into_iter()
            .filter(|r| matched_keys.contains(&section_title_key(&section_title_of(r))))
            .collect()
    } else {
        // 没匹配 → 只保留无 section_title 的行
        rows.into_iter()
            .filter(|r| section_title_key(&section_title_of(r)).is_empty())
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{NoteKind, RegionScope, RegionSource};

    #[test]
    fn section_key_strips_heading_markup() {
        assert_eq!(
            section_title_key("## Chapter One"),
            chapter_title_match_key("Chapter One")
        );
    }

    #[test]
    fn title_key_match_exact() {
        assert!(title_key_matches("foo", "foo"));
    }

    #[test]
    fn title_key_match_prefix_long_candidate() {
        assert!(title_key_matches("longchaptertitle", "longchapter"));
    }

    #[test]
    fn title_key_match_no_overlap() {
        assert!(!title_key_matches("abc", "xyz"));
    }

    #[test]
    fn last_numeric_marker_basic() {
        let v =
            last_numeric_marker_value(&["1".into(), "2".into(), "abc".into(), "5".into()], None);
        assert_eq!(v, Some(5));
    }

    #[test]
    fn shared_page_split_current_region() {
        let text = "intro line\n## Chapter Two\n1. note text";
        let mut chapters: HashMap<String, String> = HashMap::new();
        chapters.insert("ch-1".into(), "Chapter One".into());
        chapters.insert("ch-2".into(), "Chapter Two".into());
        let region = NoteRegionRecord {
            region_id: "r-1".into(),
            chapter_id: "ch-2".into(),
            page_start: 1,
            page_end: 1,
            pages: vec![1],
            note_kind: NoteKind::Endnote,
            scope: RegionScope::Chapter,
            source: RegionSource::HeadingScan,
            heading_text: "Chapter Two".into(),
            start_reason: String::new(),
            end_reason: String::new(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: String::new(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        };
        let (sliced, did) = split_shared_page_text_for_region(text, &region, &chapters);
        assert!(did);
        assert!(sliced.starts_with("## Chapter Two"));
    }

    #[test]
    fn normalized_text_prefers_page_text_map() {
        let mut map: HashMap<i64, String> = HashMap::new();
        map.insert(1, "mapped text".into());
        let (t, src) = normalized_page_text(1, NoteKind::Footnote, None, &map, &HashMap::new());
        assert_eq!(t, "mapped text");
        assert_eq!(src, "page_text_map");
    }

    #[test]
    fn normalized_text_falls_back_to_footnotes_for_footnote_kind() {
        let page = RawPage {
            book_page: 1,
            footnotes: "1. footnote text".into(),
            ..Default::default()
        };
        let (t, src) = normalized_page_text(
            1,
            NoteKind::Footnote,
            Some(&page),
            &HashMap::new(),
            &HashMap::new(),
        );
        assert_eq!(t, "1. footnote text");
        assert_eq!(src, "footnotes");
    }
}
