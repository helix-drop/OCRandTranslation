//! ←→ FNM_RE/stages/section_heads.py
//! 节标题归属：从 heading_candidates 和 fallback_sections 构建 SectionHeadRecord。

use fnm_core::chapters::chapter_id_for_page;
use fnm_core::records::{ChapterRecord, HeadingCandidate, PagePartitionRecord, SectionHeadRecord};
use fnm_core::title::{chapter_title_match_key, normalize_title};
use std::collections::{HashMap, HashSet};

/// 前导编号前缀剥离正则（章/节编号等）。
static LEADING_NUMBER_PREFIX_RE: once_cell::sync::Lazy<regex::Regex> =
    once_cell::sync::Lazy::new(|| {
        regex::Regex::new(r"(?i)^\s*(?:\d+|[ivxlcdm]+)[\.\):\-–—]?\s+").unwrap()
    });

const SECTION_TITLE_MIN_WORDS: usize = 3;
const SECTION_TITLE_MIN_CHARS: usize = 18;
const OPENING_QUOTES: &[char] = &[
    '"', '\'', '"', '"', '\'', '\'', '«', '»', '‹', '›', '「', '」', '『', '』',
];

fn section_title_starts_like_heading(title: &str) -> bool {
    let stripped = normalize_title(title)
        .trim_start_matches(|c: char| OPENING_QUOTES.contains(&c))
        .to_string();
    let first_alpha = stripped.chars().find(|c| c.is_alphabetic());
    first_alpha.map_or(true, |c| c.is_uppercase())
}

fn section_title_is_plausible(title: &str) -> bool {
    let normalized = normalize_title(title);
    if normalized.is_empty() {
        return false;
    }
    let words: Vec<&str> = normalized.split_whitespace().collect();
    if words.len() == 1 && normalized.len() < 12 {
        return false;
    }
    if !section_title_starts_like_heading(&normalized) {
        return false;
    }
    if words.len() < SECTION_TITLE_MIN_WORDS && normalized.len() < SECTION_TITLE_MIN_CHARS {
        return section_title_starts_like_heading(&normalized);
    }
    true
}

fn chapter_title_keys(chapters: &[ChapterRecord]) -> HashMap<String, HashSet<String>> {
    let mut map = HashMap::new();
    for ch in chapters {
        let mut keys = HashSet::new();
        let title = normalize_title(&ch.title);
        keys.insert(chapter_title_match_key(&title));
        let stripped = LEADING_NUMBER_PREFIX_RE.replace(&title, "").to_string();
        if stripped != title {
            keys.insert(chapter_title_match_key(&stripped));
        }
        map.insert(ch.chapter_id.clone(), keys);
    }
    map
}

pub fn build_section_heads(
    chapters: &[ChapterRecord],
    heading_candidates: &[HeadingCandidate],
    page_partitions: &[PagePartitionRecord],
    fallback_sections: Option<&[serde_json::Value]>,
) -> (Vec<SectionHeadRecord>, serde_json::Value) {
    let mut ordered_chapters = chapters.to_vec();
    ordered_chapters.sort_by(|a, b| {
        a.start_page
            .cmp(&b.start_page)
            .then_with(|| a.chapter_id.cmp(&b.chapter_id))
    });

    let _chapter_title_key_map = chapter_title_keys(&ordered_chapters);

    let page_role_map: HashMap<i64, String> = page_partitions
        .iter()
        .map(|pp| (pp.page_no, pp.page_role.as_str().to_string()))
        .collect();

    let mut seen: HashSet<(String, i64, String)> = HashSet::new();
    let mut merged_rows: Vec<SectionHeadInput> = Vec::new();

    // fallback sections
    if let Some(fallback) = fallback_sections {
        for row in fallback {
            let title = normalize_title(
                row.get("title")
                    .or(row.get("text"))
                    .and_then(|v| v.as_str())
                    .unwrap_or(""),
            );
            let page_no = row
                .get("page_no")
                .or(row.get("start_page"))
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            let chapter_id = row
                .get("chapter_id")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| chapter_id_for_page(&ordered_chapters, page_no));
            if title.is_empty() || page_no <= 0 || chapter_id.is_empty() {
                continue;
            }
            if !section_title_is_plausible(&title) {
                continue;
            }
            let key = (chapter_id.clone(), page_no, chapter_title_match_key(&title));
            if seen.contains(&key) {
                continue;
            }
            seen.insert(key);
            merged_rows.push(SectionHeadInput {
                chapter_id,
                title,
                page_no,
                level: row
                    .get("level")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(2)
                    .max(1),
                source: row
                    .get("source")
                    .and_then(|v| v.as_str())
                    .unwrap_or("fallback")
                    .to_string(),
            });
        }
    }

    // heading candidates
    for candidate in heading_candidates {
        let text = normalize_title(if !candidate.normalized_text.is_empty() {
            &candidate.normalized_text
        } else {
            &candidate.text
        });
        if !section_title_is_plausible(&text) {
            continue;
        }
        if candidate.heading_family_guess != "section" && !candidate.suppressed_as_chapter {
            continue;
        }
        let page_no = candidate.page_no;
        if page_no <= 0
            || !matches!(
                page_role_map.get(&page_no).map(|s| s.as_str()),
                Some("body") | Some("front_matter")
            )
        {
            continue;
        }
        let chapter_id = chapter_id_for_page(&ordered_chapters, page_no);
        if chapter_id.is_empty() {
            continue;
        }
        let key = (chapter_id.clone(), page_no, chapter_title_match_key(&text));
        if seen.contains(&key) {
            continue;
        }
        seen.insert(key);
        merged_rows.push(SectionHeadInput {
            chapter_id,
            title: text,
            page_no,
            level: 2,
            source: candidate.source.clone(),
        });
    }

    merged_rows.sort_by(|a, b| {
        let a_start = ordered_chapters
            .iter()
            .find(|ch| ch.chapter_id == a.chapter_id)
            .map(|ch| ch.start_page)
            .unwrap_or(i64::MAX);
        let b_start = ordered_chapters
            .iter()
            .find(|ch| ch.chapter_id == b.chapter_id)
            .map(|ch| ch.start_page)
            .unwrap_or(i64::MAX);
        a_start
            .cmp(&b_start)
            .then_with(|| a.page_no.cmp(&b.page_no))
            .then_with(|| a.title.cmp(&b.title))
    });

    let section_heads: Vec<SectionHeadRecord> = merged_rows
        .iter()
        .enumerate()
        .map(|(i, row)| SectionHeadRecord {
            section_head_id: format!("section-head-{:04}", i + 1),
            chapter_id: row.chapter_id.clone(),
            title: row.title.clone(),
            page_no: row.page_no,
            level: row.level,
            source: row.source.clone(),
        })
        .collect();

    let summary = serde_json::json!({
        "total_section_heads": section_heads.len(),
    });

    (section_heads, summary)
}

struct SectionHeadInput {
    chapter_id: String,
    title: String,
    page_no: i64,
    level: i64,
    source: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plausible_heading() {
        assert!(section_title_is_plausible("The Origins of Biopolitics"));
        assert!(!section_title_is_plausible(""));
        assert!(!section_title_is_plausible("a"));
    }

    #[test]
    fn empty_chapters_no_heads() {
        let (heads, _) = build_section_heads(&[], &[], &[], None);
        assert!(heads.is_empty());
    }
}
