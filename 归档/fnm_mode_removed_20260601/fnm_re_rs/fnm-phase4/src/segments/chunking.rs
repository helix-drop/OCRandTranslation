//! ←→ Python `FNM_RE/stages/units.py`（chunking 部分，L277-383）
//! 段落去重 + 贪心切块算法。

use fnm_core::records::{UnitPageSegmentRecord, UnitParagraphRecord};
use once_cell::sync::Lazy;
use regex::Regex;

/// ←→ Python `_REF_TOKEN_FOR_DEDUPE_RE` (units.py:36)
static REF_TOKEN_FOR_DEDUPE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\{\{(?:NOTE|FN|EN)_REF:[^}]+\}\}|\[\^[^\]]+\]").unwrap());

/// ←→ Python `_paragraph_content_dedupe_key` (units.py:299-303)
pub fn paragraph_content_dedupe_key(text: &str) -> String {
    let normalized = REF_TOKEN_FOR_DEDUPE_RE.replace_all(text, " ");
    let normalized = Regex::new(r"<[^>]+>")
        .unwrap()
        .replace_all(&normalized, " ");
    let normalized = Regex::new(r"\s+")
        .unwrap()
        .replace_all(&normalized, " ")
        .trim()
        .to_lowercase();
    normalized
}

/// ←→ Python `_chunk_visible_paragraphs` (units.py:277-296)
pub fn chunk_visible_paragraphs(
    segment: &UnitPageSegmentRecord,
    current_parts: &[String],
) -> Vec<UnitParagraphRecord> {
    let prior_text = {
        let last_two: Vec<&str> = current_parts
            .iter()
            .rev()
            .take(2)
            .map(|s| s.as_str())
            .collect();
        last_two.join("\n\n")
    };
    let prior_key = paragraph_content_dedupe_key(&prior_text);

    let mut paragraphs: Vec<UnitParagraphRecord> = Vec::new();
    for paragraph in &segment.paragraphs {
        let source_text = paragraph.source_text.trim().to_string();
        if !paragraph.consumed_by_prev {
            paragraphs.push(paragraph.clone());
            continue;
        }
        if !source_text.contains("{{NOTE_REF:") {
            continue;
        }
        let source_key = paragraph_content_dedupe_key(&source_text);
        if !source_key.is_empty() && !prior_key.is_empty() && prior_key.contains(&source_key) {
            continue;
        }
        let mut un_consumed = paragraph.clone();
        un_consumed.consumed_by_prev = false;
        paragraphs.push(un_consumed);
    }
    paragraphs
}

/// ←→ Python `_chunk_body_page_segments` (units.py:306-383)
///
/// 贪心切块算法：按 `max_body_chars` 预算累积段落文本，超预算时 flush 出一个 chunk。
pub fn chunk_body_page_segments(
    page_segments: &[UnitPageSegmentRecord],
    max_body_chars: i64,
) -> Vec<serde_json::Value> {
    let mut chunks: Vec<serde_json::Value> = Vec::new();
    let mut current_parts: Vec<String> = Vec::new();
    let mut current_start: Option<i64> = None;
    let mut current_end: Option<i64> = None;
    let mut current_chars: i64 = 0;
    let mut current_page_segments: Vec<UnitPageSegmentRecord> = Vec::new();
    let mut pending_page_meta: Vec<UnitPageSegmentRecord> = Vec::new();

    fn flush(
        chunks: &mut Vec<serde_json::Value>,
        current_parts: &mut Vec<String>,
        current_start: &mut Option<i64>,
        current_end: &mut Option<i64>,
        current_chars: &mut i64,
        current_page_segments: &mut Vec<UnitPageSegmentRecord>,
        pending_page_meta: &mut Vec<UnitPageSegmentRecord>,
    ) {
        if current_parts.is_empty() {
            return;
        }
        chunks.push(serde_json::json!({
            "page_start": current_start.unwrap_or(0),
            "page_end": current_end.unwrap_or(0),
            "source_text": current_parts.join("\n\n"),
            "char_count": *current_chars,
            "page_segments": serde_json::to_value(&*current_page_segments).unwrap_or_default(),
        }));
        current_parts.clear();
        *current_start = None;
        *current_end = None;
        *current_chars = 0;
        current_page_segments.clear();
        pending_page_meta.clear();
    }

    for segment in page_segments {
        let page_no = segment.page_no;
        let visible_paragraphs = chunk_visible_paragraphs(segment, &current_parts);
        let segment_source: String = visible_paragraphs
            .iter()
            .map(|p| p.source_text.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join("\n\n")
            .trim()
            .to_string();
        let _segment_display: String = visible_paragraphs
            .iter()
            .map(|p| {
                if p.display_text.trim().is_empty() {
                    p.source_text.trim().to_string()
                } else {
                    p.display_text.trim().to_string()
                }
            })
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join("\n\n")
            .trim()
            .to_string();

        let normalized_segment = UnitPageSegmentRecord {
            page_no,
            paragraph_count: visible_paragraphs.len() as i64,
            source_text: String::new(),
            display_text: String::new(),
            paragraphs: visible_paragraphs,
        };

        if page_no <= 0 {
            continue;
        }

        if segment_source.is_empty() {
            if current_start.is_none() {
                pending_page_meta.push(normalized_segment);
            } else {
                current_page_segments.push(normalized_segment);
            }
            continue;
        }

        let separator: i64 = if current_parts.is_empty() { 0 } else { 2 };
        let projected = current_chars + separator + segment_source.len() as i64;
        if !current_parts.is_empty() && projected > max_body_chars {
            flush(
                &mut chunks,
                &mut current_parts,
                &mut current_start,
                &mut current_end,
                &mut current_chars,
                &mut current_page_segments,
                &mut pending_page_meta,
            );
        }

        if current_start.is_none() {
            current_start = Some(page_no);
            if !pending_page_meta.is_empty() {
                current_page_segments.append(&mut pending_page_meta);
            }
        }
        current_end = Some(page_no);

        if !current_parts.is_empty() {
            current_chars += 2;
        }
        let source_len = segment_source.len() as i64;
        current_parts.push(segment_source);
        current_chars += source_len;
        current_page_segments.push(normalized_segment);
    }

    flush(
        &mut chunks,
        &mut current_parts,
        &mut current_start,
        &mut current_end,
        &mut current_chars,
        &mut current_page_segments,
        &mut pending_page_meta,
    );

    chunks
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_para(source: &str, consumed: bool) -> UnitParagraphRecord {
        UnitParagraphRecord {
            order: 1,
            kind: "body".to_string(),
            source_text: source.to_string(),
            consumed_by_prev: consumed,
            ..Default::default()
        }
    }

    fn make_segment(page_no: i64, paragraphs: Vec<UnitParagraphRecord>) -> UnitPageSegmentRecord {
        let count = paragraphs.iter().filter(|p| !p.consumed_by_prev).count() as i64;
        UnitPageSegmentRecord {
            page_no,
            paragraph_count: count,
            paragraphs,
            ..Default::default()
        }
    }

    #[test]
    fn test_paragraph_content_dedupe_key_basic() {
        let key = paragraph_content_dedupe_key("Hello {{NOTE_REF:abc}} world");
        assert!(!key.contains("NOTE_REF"));
        assert!(key.contains("hello"));
    }

    #[test]
    fn test_chunk_visible_paragraphs_consumed_skipped() {
        let seg = make_segment(
            1,
            vec![
                make_para("visible para", false),
                make_para("consumed without NOTE_REF", true),
                make_para("consumed with {{NOTE_REF:1}}", true),
            ],
        );
        let result = chunk_visible_paragraphs(&seg, &[]);
        // visible para + 只有含 NOTE_REF 的 consumed 才保留
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_chunk_body_page_segments_single() {
        let seg = make_segment(1, vec![make_para("short text", false)]);
        let chunks = chunk_body_page_segments(&[seg], 6000);
        assert_eq!(chunks.len(), 1);
        let chunk = &chunks[0];
        assert_eq!(chunk["page_start"], 1);
        assert!(chunk["source_text"]
            .as_str()
            .unwrap()
            .contains("short text"));
    }

    #[test]
    fn test_chunk_body_page_segments_split() {
        let seg1 = make_segment(1, vec![make_para(&"x".repeat(3000), false)]);
        let seg2 = make_segment(2, vec![make_para(&"y".repeat(4000), false)]);
        // max_body_chars = 6000, seg1 3000 + seg2 4000 = 7000 > 6000 → split
        let chunks = chunk_body_page_segments(&[seg1, seg2], 6000);
        assert!(chunks.len() >= 2);
    }

    #[test]
    fn test_chunk_body_page_segments_empty_source() {
        let seg = make_segment(2, vec![]);
        let chunks = chunk_body_page_segments(&[seg], 6000);
        // 空 source 不产生 chunk
        assert!(chunks.is_empty());
    }

    #[test]
    fn test_chunk_body_page_segments_zero_page() {
        let seg = make_segment(0, vec![make_para("zero page", false)]);
        let chunks = chunk_body_page_segments(&[seg], 6000);
        assert!(chunks.is_empty());
    }
}
