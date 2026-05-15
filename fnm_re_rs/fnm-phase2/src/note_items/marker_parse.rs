//! ←→ note_items.py: parse_page + make_item + 全部 marker 解析 regex
//! 注释标记解析：全量 marker 类型 + OCR split 重建。

use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{NoteItemRecord, NoteRegionRecord};
use once_cell::sync::Lazy;
use regex::Regex;

use super::sequence_repair::ParsedNoteRow;

// ── Regex 池 ──────────────────────────────────────────────────

/// 字母型 marker: "a text" / "b text"
static LETTER_BODY_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^([a-zA-Z])\s{1,3}(\S.*)$").unwrap());

/// 单个字母判定
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

// ── 解析逻辑 ──────────────────────────────────────────────────

/// 解析单页 markdown 文本，提取所有注释项。
pub(crate) fn parse_page(
    text: &str,
    page_no: i64,
    _region: &NoteRegionRecord,
) -> Vec<ParsedNoteRow> {
    let mut rows = Vec::new();

    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        // 1. OCR split marker FIRST: "1 2 body" → marker="12", reconstructed
        if let Some(caps) = OCR_SPLIT_NOTE_DEF_RE.captures(trimmed) {
            let token = caps.name("token").map(|m| m.as_str()).unwrap_or("");
            let has_sep = token.contains(' ')
                || token.contains(',')
                || token.contains('.')
                || token.contains('-');
            if has_sep {
                let body = caps
                    .name("body")
                    .map(|m| m.as_str().trim().to_string())
                    .unwrap_or_default();
                let marker = normalize_note_marker(token);
                if !marker.is_empty() && !body.is_empty() {
                    rows.push(ParsedNoteRow {
                        page_no,
                        marker,
                        text: body,
                        is_reconstructed: true,
                        source: "note_scan".into(),
                    });
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
                .map(|m| m.as_str())
                .unwrap_or("");
            let body = caps
                .name("body")
                .map(|m| m.as_str().trim().to_string())
                .unwrap_or_default();
            if !marker.is_empty() && !body.is_empty() {
                rows.push(ParsedNoteRow {
                    page_no,
                    marker: marker.into(),
                    text: body,
                    is_reconstructed: false,
                    source: "markdown".into(),
                });
            }
            continue;
        }

        // 3. Symbol markers: *, **, †, ‡, §, ¶
        if let Some(caps) = SYMBOL_NOTE_DEF_RE.captures(trimmed) {
            let marker = caps.get(1).map(|m| m.as_str()).unwrap_or("");
            let body = caps
                .name("body")
                .map(|m| m.as_str().trim().to_string())
                .unwrap_or_default();
            if !marker.is_empty() && !body.is_empty() {
                rows.push(ParsedNoteRow {
                    page_no,
                    marker: marker.into(),
                    text: body,
                    is_reconstructed: false,
                    source: "markdown".into(),
                });
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
                rows.push(ParsedNoteRow {
                    page_no,
                    marker: m.into(),
                    text: body,
                    is_reconstructed: false,
                    source: "markdown".into(),
                });
            }
            continue;
        }

        // 5. HTML sup: <sup>5</sup>text
        if let Some(caps) = HTML_SUP_RE.captures(trimmed) {
            let marker = caps.get(1).map(|m| m.as_str()).unwrap_or("");
            let rest = HTML_SUP_RE.replace(trimmed, "").trim().to_string();
            if !marker.is_empty() && rest.len() > 2 {
                rows.push(ParsedNoteRow {
                    page_no,
                    marker: marker.into(),
                    text: rest,
                    is_reconstructed: false,
                    source: "markdown".into(),
                });
            }
            continue;
        }

        // 6. LaTeX sup: $^{5}$text
        if let Some(caps) = LATEX_SUP_RE.captures(trimmed) {
            let marker = caps.get(1).map(|m| m.as_str()).unwrap_or("");
            let rest = LATEX_SUP_RE.replace(trimmed, "").trim().to_string();
            if !marker.is_empty() && rest.len() > 2 {
                rows.push(ParsedNoteRow {
                    page_no,
                    marker: marker.into(),
                    text: rest,
                    is_reconstructed: false,
                    source: "markdown".into(),
                });
            }
            continue;
        }
    }

    rows
}

/// 将 ParsedNoteRow 转换为 NoteItemRecord。
pub(crate) fn row_to_item(
    row: &ParsedNoteRow,
    region: &NoteRegionRecord,
    note_kind: &str,
) -> NoteItemRecord {
    let marker_type = if row.marker.chars().all(|c| c.is_ascii_digit()) {
        "num"
    } else if row.marker.chars().all(|c| c.is_alphabetic()) && row.marker.len() == 1 {
        "letter"
    } else {
        "sym"
    };

    // 构造 item_id：fn 和 en 各自独立序列
    // 注意：最终的 item_id 会在 mod.rs 中重新分配（全局序列）
    let item_id = format!(
        "{}-{}-p{}-{}",
        region.region_id, note_kind, row.page_no, row.marker
    );

    NoteItemRecord {
        note_item_id: item_id,
        region_id: region.region_id.clone(),
        chapter_id: region.chapter_id.clone(),
        page_no: row.page_no,
        marker: row.marker.clone(),
        marker_type: marker_type.into(),
        text: row.text.clone(),
        source: row.source.clone(),
        source_page_label: format!("p{}", row.page_no),
        is_reconstructed: row.is_reconstructed,
        review_required: false,
        note_kind: region.note_kind,
    }
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
    fn parse_standard_marker() {
        let rows = parse_page("1. A test note.\n2. Another note.", 1, &test_region());
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].marker, "1");
    }

    #[test]
    fn parse_bracket_marker() {
        let rows = parse_page("[1] First note.\n[2] Second note.", 1, &test_region());
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].marker, "1");
    }

    #[test]
    fn ocr_split_marker_reconstructed() {
        let rows = parse_page(
            "1 2 This is a split note.\n3. Next note.",
            1,
            &test_region(),
        );
        let split: Vec<&ParsedNoteRow> = rows.iter().filter(|r| r.is_reconstructed).collect();
        assert_eq!(split.len(), 1);
        assert_eq!(split[0].marker, "12");
    }

    #[test]
    fn symbol_marker() {
        let rows = parse_page("* First footnote.\n** Second.", 1, &test_region());
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].marker, "*");
    }

    #[test]
    fn html_sup_marker() {
        let rows = parse_page("<sup>1</sup> Note with html sup.", 1, &test_region());
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].marker, "1");
    }

    #[test]
    fn empty_text_no_items() {
        let rows = parse_page("", 1, &test_region());
        assert!(rows.is_empty());
    }

    #[test]
    fn letter_marker() {
        let rows = parse_page(
            "a First letter note.\nb Second letter note.",
            1,
            &test_region(),
        );
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].marker, "a");
    }

    #[test]
    fn latex_sup_marker() {
        let rows = parse_page("$^{5}$ Note with latex sup.", 1, &test_region());
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].marker, "5");
    }
}
