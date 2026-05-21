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

// ── 补充 Python `shared/notes.py` regex ──────────────────────

/// ←→ Python `_INLINE_NOTE_BREAK_RE`：修复行内注释放置的断点。
/// 匹配 `]. 1` 模式，其中 `]` 前的文本和后续数字可能被误分。
// Rust regex 不支持 lookahead。将 Python 的 (?=digits) 改为捕获 digits 本身。
static INLINE_NOTE_BREAK_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?P<prefix>[\.\]\)»\u{201d}])(?P<gap>\s+)(?P<digits>(?:\d[\s,\.\-]*){1,4}[\.,\)\]])",
    )
    .unwrap()
});

/// ←→ Python `_INLINE_FOLLOWUP_TOKEN_RE`：行内跟随标记（避免被误分为新 note）。
static INLINE_FOLLOWUP_TOKEN_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?:\s*[,;:·•]+\s*|\s+)(?P<token>\d(?:[ ,\.\-]{0,2}\d){0,3})(?:[\.,\)\]]|\s{1,3})")
        .unwrap()
});

/// 预处理页面文本，修复 inline break 等。←→ Python `_normalized_page_text` 预处理部分。
pub(crate) fn preprocess_page_text(text: &str) -> String {
    // Python `_replace_inline_note_break`: 在 prefix（句末标点）和 digits 之间插入换行
    INLINE_NOTE_BREAK_RE
        .replace_all(text, |caps: &regex::Captures| {
            let prefix = caps.name("prefix").map(|m| m.as_str()).unwrap_or("");
            let digits = caps.name("digits").map(|m| m.as_str()).unwrap_or("");
            format!("{}\n{}", prefix, digits)
        })
        .to_string()
}

/// 在 parse 后：对已识别的 ParsedNoteRow 应用 followup token 去重。
#[allow(dead_code)]
pub(crate) fn dedupe_followup_tokens(rows: &[ParsedNoteRow]) -> Vec<ParsedNoteRow> {
    let mut result: Vec<ParsedNoteRow> = Vec::new();
    for row in rows {
        // 检查 marker 是否属于 followup token（跟在正文内的编号引用）
        if INLINE_FOLLOWUP_TOKEN_RE.is_match(&row.marker) {
            // 合并到前一 note，不生成独立条目
            if let Some(last) = result.last_mut() {
                last.text = format!("{} {}", last.text, row.text);
            }
            continue;
        }
        result.push(row.clone());
    }
    result
}

// ── Embedded note definition regex ─────────────────────────

/// ←→ Python `_EMBEDDED_NOTE_DEF_RE`：捕获行内注释放置的 marker。
/// 匹配有至少 20 个前导字符后跟数字 marker 的行。
static EMBEDDED_NOTE_DEF_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^(?P<prefix>.{20,}?)\s+(?P<token>\d{1,4})(?P<body>\s+\S.*)$").unwrap()
});

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

        // 1. OCR split marker: "1 2 body" → marker="12", reconstructed.
        // ←→ Python `_parse_note_definition_line`: checks both OCR split AND standard match,
        // and prefers standard if the standard marker is followed by another digit
        // (e.g., "25 1. body" should give marker="25" not OCR-collapsed "251").
        if let Some(split_caps) = OCR_SPLIT_NOTE_DEF_RE.captures(trimmed) {
            let token = split_caps.name("token").map(|m| m.as_str()).unwrap_or("");
            let has_sep = token.contains(' ')
                || token.contains(',')
                || token.contains('.')
                || token.contains('-');
            if has_sep {
                let collapsed = normalize_note_marker(token);
                // Check if standard match also fires and prefers standard.
                let prefer_standard = NOTE_DEF_RE.captures(trimmed).is_some_and(|std_caps| {
                    let std_raw = std_caps
                        .name("bracket")
                        .or_else(|| std_caps.name("num"))
                        .or_else(|| std_caps.name("loose"))
                        .map(|m| m.as_str())
                        .unwrap_or("");
                    let std_marker = normalize_note_marker(std_raw);
                    std_marker != collapsed && !std_marker.is_empty()
                });
                if !prefer_standard {
                    let body = split_caps
                        .name("body")
                        .map(|m| m.as_str().trim().to_string())
                        .unwrap_or_default();
                    if !collapsed.is_empty() && !body.is_empty() {
                        rows.push(ParsedNoteRow {
                            page_no,
                            marker: collapsed,
                            text: body,
                            is_reconstructed: true,
                            source: "note_scan".into(),
                        });
                    }
                    continue;
                }
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

        // 7. Embedded note definition: at least 20 leading chars, then number marker.
        // ←→ Python `_EMBEDDED_NOTE_DEF_RE`
        if let Some(caps) = EMBEDDED_NOTE_DEF_RE.captures(trimmed) {
            let token = caps.name("token").map(|m| m.as_str()).unwrap_or("");
            let body = caps.name("body").map(|m| m.as_str().trim()).unwrap_or("");
            if !token.is_empty() && !body.is_empty() {
                rows.push(ParsedNoteRow {
                    page_no,
                    marker: token.into(),
                    text: body.to_string(),
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
        projection_mode: None,
        owner_chapter_id: None,
        source_marker: None,
        normalized_marker: None,
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
    fn ocr_split_prefers_standard_when_followed_by_digit() {
        // ←→ Python `_parse_note_definition_line`：当 standard match 的 marker
        // 后跟另一数字时（如 "1 2 body"），优先使用 standard marker="1"，
        // 而非 OCR 合并的 "12"。
        let rows = parse_page(
            "1 2 This is a split note.\n3. Next note.",
            1,
            &test_region(),
        );
        let split: Vec<&ParsedNoteRow> = rows.iter().filter(|r| r.is_reconstructed).collect();
        // "1 2" → standard marker "1"（后跟 "2"），不做 OCR 合并
        assert_eq!(split.len(), 0);
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].marker, "1");
        assert_eq!(rows[1].marker, "3");
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
