//! ←→ FNM_RE/stages/note_items.py (658 行) + shared/notes.py 纯函数
//! 注释项解析：全量 marker 类型 + OCR split 重建 + inline break + 引文缩写处理。
//! 覆盖 F3 全部需求。

use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{NoteItemRecord, NoteRegionRecord};
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashSet;

// ── Regex 池 ──────────────────────────────────────────────────

/// 字母型 marker: "a text" / "b text"
static LETTER_BODY_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^([a-zA-Z])\s{1,3}(\S.*)$").unwrap());

/// 单个字母判定：直接用 chars().count()==1 + is_alphabetic() 检查，比 Regex 快。
fn is_single_letter(s: &str) -> bool {
    let mut chars = s.chars();
    chars.next().map(|c| c.is_alphabetic()).unwrap_or(false) && chars.next().is_none()
}

static NOTE_DEF_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"^\s*(?:\[(?P<bracket>\d{1,4})\]|(?P<num>\d{1,4})[\.;:,\)\]]|(?P<loose>\d{1,4})\s{1,3})\s*(?P<body>\S.*)$",
    )
    .unwrap()
});

static OCR_SPLIT_NOTE_DEF_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^\s*(?P<token>(?:\d[\s,\.\-]*){2,4})(?:[\.;:,\)\]:-]|\s{1,3})(?P<body>\S.*)$")
        .unwrap()
});

static SYMBOL_NOTE_DEF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(\*{1,4}|†{1,2}|‡{1,2}|§|¶)\s+(?P<body>\S.*)$").unwrap());

static HTML_SUP_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)<sup>\s*(\d{1,4})\s*</sup>").unwrap());

static LATEX_SUP_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\$\s*\^\{(\d{1,4})\}\s*\$").unwrap());

static PAGE_CITATION_PREFIX_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\b(?:pp?|f(?:o|°)?|esp|paras?|fols?|cols?|vol|n[°o]|nos?|nr|art|chap|sect|§|t|tome|liv|bk|book|ch|cf|voir|see|infra|supra|ibid|op|loc|id|éd|ed|eds|dir|trad|tr)\.$",
    )
    .unwrap()
});

// ── 公开 API ──────────────────────────────────────────────────

pub fn build_note_items(
    pages: &[RawPage],
    note_regions: &[NoteRegionRecord],
) -> Vec<NoteItemRecord> {
    let mut items = Vec::new();

    let region_page_set: HashSet<i64> = note_regions.iter().flat_map(|r| r.pages.clone()).collect();

    for region in note_regions {
        let region_pages: Vec<&RawPage> = pages
            .iter()
            .filter(|p| {
                region.pages.contains(&p.book_page) && region_page_set.contains(&p.book_page)
            })
            .collect();

        for page in region_pages {
            let text = &page.markdown;
            if text.is_empty() {
                continue;
            }
            items.extend(parse_page(text, page.book_page, region));
        }
    }

    merge_continuation_notes(items)
}

fn parse_page(text: &str, page_no: i64, region: &NoteRegionRecord) -> Vec<NoteItemRecord> {
    let mut items = Vec::new();

    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        // 1. OCR split marker FIRST: "1 2 body" → marker="12", reconstructed
        // Must be checked before standard pattern (which would greedily match "1" alone)
        if let Some(caps) = OCR_SPLIT_NOTE_DEF_RE.captures(trimmed) {
            let token = caps
                .name("token")
                .map(|m| m.as_str().to_string())
                .unwrap_or_default();
            // only trigger if the token actually contains separator chars
            let has_sep = token.contains(' ')
                || token.contains(',')
                || token.contains('.')
                || token.contains('-');
            if has_sep {
                let body = caps
                    .name("body")
                    .map(|m| m.as_str().trim().to_string())
                    .unwrap_or_default();
                let marker = normalize_note_marker(&token);
                if !marker.is_empty() && !body.is_empty() {
                    items.push(make_item(region, page_no, &marker, &body, true));
                }
                continue;
            }
        }

        // 2. Standard digit markers: "1. body" / "[1] body" / "1 body"
        if let Some(caps) = NOTE_DEF_RE.captures(trimmed) {
            let marker = caps
                .name("bracket")
                .or_else(|| caps.name("num"))
                .or_else(|| caps.name("loose"))
                .map(|m| m.as_str().to_string())
                .unwrap_or_default();
            let body = caps
                .name("body")
                .map(|m| m.as_str().trim().to_string())
                .unwrap_or_default();
            if !marker.is_empty() && !body.is_empty() {
                items.push(make_item(region, page_no, &marker, &body, false));
            }
            continue;
        }

        // 3. Symbol markers: *, **, †, ‡, §, ¶
        if let Some(caps) = SYMBOL_NOTE_DEF_RE.captures(trimmed) {
            let marker = caps
                .get(1)
                .map(|m| m.as_str().to_string())
                .unwrap_or_default();
            let body = caps
                .name("body")
                .map(|m| m.as_str().trim().to_string())
                .unwrap_or_default();
            if !marker.is_empty() && !body.is_empty() {
                items.push(make_item(region, page_no, &marker, &body, false));
            }
            continue;
        }

        // 4. Letter markers: a, b, c
        if let Some(caps) = LETTER_BODY_RE.captures(trimmed) {
            let m = caps.get(1).map(|c| c.as_str()).unwrap_or("");
            let body = caps
                .get(2)
                .map(|c| c.as_str().trim().to_string())
                .unwrap_or_default();
            if is_single_letter(m) && !body.is_empty() {
                items.push(make_item(region, page_no, m, &body, false));
            }
            continue;
        }

        // 5. HTML sup: <sup>5</sup>text
        if let Some(caps) = HTML_SUP_RE.captures(trimmed) {
            let marker = caps
                .get(1)
                .map(|m| m.as_str().to_string())
                .unwrap_or_default();
            let rest = HTML_SUP_RE.replace(trimmed, "").trim().to_string();
            if !marker.is_empty() && rest.len() > 2 {
                items.push(make_item(region, page_no, &marker, &rest, false));
            }
            continue;
        }

        // 6. LaTeX sup: $^{5}$text
        if let Some(caps) = LATEX_SUP_RE.captures(trimmed) {
            let marker = caps
                .get(1)
                .map(|m| m.as_str().to_string())
                .unwrap_or_default();
            let rest = LATEX_SUP_RE.replace(trimmed, "").trim().to_string();
            if !marker.is_empty() && rest.len() > 2 {
                items.push(make_item(region, page_no, &marker, &rest, false));
            }
            continue;
        }
    }

    items
}

fn make_item(
    region: &NoteRegionRecord,
    page_no: i64,
    marker: &str,
    body: &str,
    is_reconstructed: bool,
) -> NoteItemRecord {
    let item_id = format!("{}-p{}-{}", region.region_id, page_no, marker);
    let marker_type = if marker.chars().all(|c| c.is_ascii_digit()) {
        "num"
    } else {
        "sym"
    };
    NoteItemRecord {
        note_item_id: item_id,
        region_id: region.region_id.clone(),
        chapter_id: region.chapter_id.clone(),
        page_no,
        marker: marker.to_string(),
        marker_type: marker_type.into(),
        text: body.to_string(),
        source: "note_scan".into(),
        source_page_label: page_no.to_string(),
        is_reconstructed,
        review_required: false,
        note_kind: region.note_kind,
    }
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

    fn test_region() -> NoteRegionRecord {
        NoteRegionRecord {
            region_id: "r-test".into(),
            chapter_id: "ch-1".into(),
            page_start: 1,
            page_end: 1,
            pages: vec![1],
            note_kind: fnm_core::types::NoteKind::Endnote,
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
    fn parse_standard_marker() {
        let page = RawPage {
            book_page: 1,
            markdown: "1. A test note.\n2. Another note.".into(),
            ..Default::default()
        };
        let items = build_note_items(&[page], &[test_region()]);
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].marker, "1");
    }

    #[test]
    fn parse_bracket_marker() {
        let page = RawPage {
            book_page: 1,
            markdown: "[1] First note.\n[2] Second note.".into(),
            ..Default::default()
        };
        let items = build_note_items(&[page], &[test_region()]);
        assert_eq!(items.len(), 2);
    }

    #[test]
    fn ocr_split_marker_reconstructed() {
        // SPEC: test_ocr_split_marker_can_be_reconstructed
        let page = RawPage {
            book_page: 1,
            markdown: "1 2 This is a split note.\n3. Next note.".into(),
            ..Default::default()
        };
        let items = build_note_items(&[page], &[test_region()]);
        let split_item = items.iter().find(|i| i.is_reconstructed);
        assert!(
            split_item.is_some(),
            "OCR split marker should be reconstructed"
        );
        let split = split_item.unwrap();
        assert_eq!(split.marker, "12");
    }

    #[test]
    fn symbol_marker() {
        let page = RawPage {
            book_page: 1,
            markdown: "* First footnote.\n** Second.".into(),
            ..Default::default()
        };
        let items = build_note_items(&[page], &[test_region()]);
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].marker, "*");
    }

    #[test]
    fn html_sup_marker() {
        let page = RawPage {
            book_page: 1,
            markdown: "<sup>1</sup> Note with html sup.".into(),
            ..Default::default()
        };
        let items = build_note_items(&[page], &[test_region()]);
        assert!(!items.is_empty());
    }

    #[test]
    fn empty_no_items() {
        assert!(build_note_items(&[], &[]).is_empty());
    }
}
