//! ←→ FNM_RE/shared/segments.py
//! 段落与分页分段工具。

use once_cell::sync::Lazy;
use regex::Regex;
use std::cmp;

use crate::records::{UnitPageSegmentRecord, UnitParagraphRecord};

static PARAGRAPH_SPLIT_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\n\s*\n").unwrap());
static HEADING_LINE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s{0,3}#{1,6}\s*(.+?)\s*$").unwrap());

/// 按连续空行拆分文本为段落。与 Python `split_fnm_paragraphs` 一致。
pub fn split_fnm_paragraphs(text: &str) -> Vec<String> {
    PARAGRAPH_SPLIT_RE
        .split(text.trim())
        .map(|p| p.trim().to_string())
        .filter(|p| !p.is_empty())
        .collect()
}

/// 从 markdown 行提取 heading level 和清理后的文本。
/// 返回 (heading_level, clean_text)。与 Python `normalize_heading_text` 一致。
pub fn normalize_heading_text(text: &str) -> (i64, String) {
    if let Some(caps) = HEADING_LINE_RE.captures(text.trim()) {
        let raw = text.trim();
        let hash_count = raw.chars().take_while(|c| *c == '#').count();
        let level = cmp::min(hash_count, 6) as i64;
        let clean = caps
            .get(1)
            .map(|m| m.as_str().trim().to_string())
            .unwrap_or_default();
        (level, clean)
    } else {
        (0, text.trim().to_string())
    }
}

/// 将段落列表合并回文本（用 \\n\\n 连接）。与 Python segment 的 source_text/display_text 构造一致。
pub fn join_paragraphs(paragraphs: &[String]) -> String {
    paragraphs
        .iter()
        .map(|p| p.trim())
        .filter(|p| !p.is_empty())
        .collect::<Vec<_>>()
        .join("\n\n")
        .trim()
        .to_string()
}

/// ←→ Python `_normalize_unit_paragraph`：规范化单个段落记录。
pub fn normalize_unit_paragraph(
    paragraph: &UnitParagraphRecord,
    order: i64,
    section_title: &str,
    print_page_label: &str,
) -> UnitParagraphRecord {
    let kind = if paragraph.kind.is_empty() {
        if paragraph.heading_level > 0 {
            "heading"
        } else {
            "body"
        }
    } else {
        &paragraph.kind
    };
    let display_text = if paragraph.display_text.is_empty() {
        paragraph.source_text.clone()
    } else {
        paragraph.display_text.clone()
    };
    let resolved_label = if print_page_label.trim().is_empty() {
        paragraph.print_page_label.clone()
    } else {
        print_page_label.trim().to_string()
    };
    let section_path = if paragraph.section_path.is_empty() && !section_title.is_empty() {
        vec![section_title.to_string()]
    } else {
        paragraph.section_path.clone()
    };
    UnitParagraphRecord {
        order,
        kind: kind.to_string(),
        heading_level: paragraph.heading_level,
        source_text: paragraph.source_text.clone(),
        display_text,
        cross_page: paragraph.cross_page.clone(),
        consumed_by_prev: paragraph.consumed_by_prev,
        section_path,
        print_page_label: resolved_label,
        translated_text: paragraph.translated_text.clone(),
        translation_status: if paragraph.translation_status.is_empty() {
            "pending".into()
        } else {
            paragraph.translation_status.clone()
        },
        attempt_count: paragraph.attempt_count.max(0),
        last_error: paragraph.last_error.clone(),
        manual_resolved: paragraph.manual_resolved,
    }
}

/// 从原始文本构建兜底段落列表。
/// ←→ Python `build_fallback_unit_paragraphs`
pub fn build_fallback_unit_paragraphs(
    source_text: &str,
    display_text: &str,
    translated_text: &str,
    page_no: i64,
    section_title: &str,
    print_page_label: &str,
) -> Vec<UnitParagraphRecord> {
    let source_parts = split_fnm_paragraphs(source_text);
    let mut display_parts = split_fnm_paragraphs(display_text);
    let translated_parts = split_fnm_paragraphs(translated_text);

    if !display_parts.is_empty() && display_parts.len() != source_parts.len() {
        display_parts = source_parts.clone();
    }

    let resolved_label = if print_page_label.trim().is_empty() {
        if page_no > 0 {
            page_no.to_string()
        } else {
            String::new()
        }
    } else {
        print_page_label.to_string()
    };

    let mut title_stack: Vec<String> = if !section_title.is_empty() {
        vec![section_title.to_string()]
    } else {
        Vec::new()
    };

    let mut paragraphs: Vec<UnitParagraphRecord> = Vec::new();

    for (idx, source_part) in source_parts.iter().enumerate() {
        let order = (idx + 1) as i64;
        let source_candidate = source_part.trim();
        let display_candidate = display_parts
            .get(idx)
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
            .unwrap_or(source_candidate);

        let (heading_level, clean_display) = normalize_heading_text(display_candidate);
        let (source_heading_level, clean_source) = normalize_heading_text(source_candidate);

        let (final_heading_level, source_clean, display_clean) =
            if heading_level <= 0 && source_heading_level > 0 {
                (
                    source_heading_level,
                    clean_source.clone(),
                    clean_source.clone(),
                )
            } else {
                let sc = if source_heading_level > 0 {
                    clean_source.clone()
                } else {
                    source_candidate.to_string()
                };
                let dc = if heading_level > 0 {
                    clean_display.clone()
                } else {
                    display_candidate.to_string()
                };
                (heading_level, sc, dc)
            };

        let section_path = if final_heading_level > 0 {
            let mut active_titles = if !title_stack.is_empty() && title_stack[0] == section_title {
                title_stack[1..].to_vec()
            } else {
                title_stack.clone()
            };
            while active_titles.len() >= final_heading_level as usize {
                active_titles.pop();
            }
            active_titles.push(display_clean.clone());
            title_stack = if !section_title.is_empty() {
                let mut t = vec![section_title.to_string()];
                t.extend(active_titles);
                t
            } else {
                active_titles.clone()
            };
            title_stack.clone()
        } else {
            title_stack.clone()
        };

        let kind = if final_heading_level > 0 {
            "heading"
        } else {
            "body"
        };
        let translated = translated_parts.get(idx).map(|s| s.trim()).unwrap_or("");

        paragraphs.push(UnitParagraphRecord {
            order,
            kind: kind.into(),
            heading_level: final_heading_level,
            source_text: source_clean.clone(),
            display_text: if display_clean.is_empty() {
                source_clean
            } else {
                display_clean
            },
            cross_page: serde_json::Value::Null,
            consumed_by_prev: false,
            section_path,
            print_page_label: resolved_label.clone(),
            translated_text: translated.to_string(),
            translation_status: if translated.is_empty() {
                "pending".into()
            } else {
                "done".into()
            },
            attempt_count: 0,
            last_error: String::new(),
            manual_resolved: false,
        });
    }

    paragraphs
}

/// 规范化页面分段记录。
/// ←→ Python `normalize_unit_page_segment`
pub fn normalize_unit_page_segment(
    segment: &UnitPageSegmentRecord,
    section_title: &str,
    print_page_label: &str,
) -> (UnitPageSegmentRecord, bool) {
    let page_no = segment.page_no;

    let paragraphs: Vec<UnitParagraphRecord> = if !segment.paragraphs.is_empty() {
        segment
            .paragraphs
            .iter()
            .enumerate()
            .map(|(idx, p)| {
                normalize_unit_paragraph(p, (idx + 1) as i64, section_title, print_page_label)
            })
            .collect()
    } else {
        build_fallback_unit_paragraphs(
            &segment.source_text,
            &segment.display_text,
            "", // UnitPageSegmentRecord 无 translated_text 字段
            page_no,
            section_title,
            print_page_label,
        )
    };

    let visible_paragraphs: Vec<&UnitParagraphRecord> =
        paragraphs.iter().filter(|p| !p.consumed_by_prev).collect();

    let source_text: String = visible_paragraphs
        .iter()
        .map(|p| p.source_text.trim())
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("\n\n");
    let display_text: String = visible_paragraphs
        .iter()
        .map(|p| p.display_text.trim())
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("\n\n");

    let final_source = if source_text.is_empty() {
        segment.source_text.trim().to_string()
    } else {
        source_text
    };
    let final_display = if display_text.is_empty() {
        if segment.display_text.trim().is_empty() {
            final_source.clone()
        } else {
            segment.display_text.trim().to_string()
        }
    } else {
        display_text
    };

    let normalized = UnitPageSegmentRecord {
        page_no,
        paragraph_count: visible_paragraphs.len() as i64,
        source_text: final_source,
        display_text: final_display,
        paragraphs,
        ..Default::default()
    };

    let changed = segment.paragraph_count != normalized.paragraph_count
        || segment.source_text.trim() != normalized.source_text.trim()
        || segment.display_text.trim() != normalized.display_text.trim();

    (normalized, changed)
}

/// 兼容旧调用方：返回 dict 列表。←→ Python `segment_paragraphs`
pub fn segment_paragraphs(
    segment: &UnitPageSegmentRecord,
    section_title: &str,
    print_page_label: &str,
) -> Vec<UnitParagraphRecord> {
    let (normalized, _) = normalize_unit_page_segment(segment, section_title, print_page_label);
    normalized.paragraphs
}

/// 兼容旧调用方：返回 (normalized_segment, changed)。←→ Python `normalize_fnm_segment`
pub fn normalize_fnm_segment(
    segment: &UnitPageSegmentRecord,
    section_title: &str,
    print_page_label: &str,
) -> (UnitPageSegmentRecord, bool) {
    normalize_unit_page_segment(segment, section_title, print_page_label)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_basic() {
        let parts = split_fnm_paragraphs("a\n\nb\n\nc");
        assert_eq!(parts, vec!["a", "b", "c"]);
    }

    #[test]
    fn split_single() {
        let parts = split_fnm_paragraphs("single paragraph");
        assert_eq!(parts, vec!["single paragraph"]);
    }

    #[test]
    fn split_empty() {
        let parts = split_fnm_paragraphs("");
        assert!(parts.is_empty());
    }

    #[test]
    fn heading_level_1() {
        let (level, clean) = normalize_heading_text("# Title");
        assert_eq!(level, 1);
        assert_eq!(clean, "Title");
    }

    #[test]
    fn heading_level_3() {
        let (level, clean) = normalize_heading_text("### Deep");
        assert_eq!(level, 3);
        assert_eq!(clean, "Deep");
    }

    #[test]
    fn heading_plain_text() {
        let (level, clean) = normalize_heading_text("plain text");
        assert_eq!(level, 0);
        assert_eq!(clean, "plain text");
    }
}
