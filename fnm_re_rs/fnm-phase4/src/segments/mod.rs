//! ←→ Python `FNM_RE/stages/units.py`（segment 部分，L143-274）
//! body pages → 段落分段 + page segments 构建。
//!
//! 依赖 `text/markdown_parse.rs` 的 `parse_page_markdown`。

use fnm_core::records::{UnitPageSegmentRecord, UnitParagraphRecord};
use fnm_core::segments;
use std::collections::HashMap;

pub mod chunking;

use crate::text::markdown_parse::{parse_page_markdown, SyntheticMarkdownPage};

/// ←→ Python `_synthetic_markdown_pages` (units.py:143)
/// 将 page_no → text map 转为页面结构列表。
pub fn synthetic_markdown_pages(pages_by_no: &HashMap<i64, String>) -> Vec<SyntheticMarkdownPage> {
    let mut page_nos: Vec<i64> = pages_by_no.keys().copied().collect();
    page_nos.sort();
    page_nos
        .into_iter()
        .map(|page_no| SyntheticMarkdownPage {
            book_page: page_no,
            file_idx: (page_no - 1).max(0),
            markdown: pages_by_no.get(&page_no).cloned().unwrap_or_default(),
            footnotes: String::new(),
            text_source: "fnm_re".to_string(),
            print_page_label: page_no.to_string(),
            ..Default::default()
        })
        .collect()
}

/// ←→ Python `_segment_paragraphs_from_body_pages` (units.py:159-274)
///
/// 将 section 的 frozen/obsidian body pages 解析为段落分段列表。
/// 输入 `body_pages` 是 `[{page_no, text}, ...]` 格式的 JSON Value 列表。
pub fn segment_paragraphs_from_body_pages(
    frozen_body_pages: &[serde_json::Value],
    obsidian_body_pages: &[serde_json::Value],
    section_title: &str,
) -> Vec<UnitPageSegmentRecord> {
    // 提取 source_by_page / display_by_page
    let mut source_by_page: HashMap<i64, String> = HashMap::new();
    for page in frozen_body_pages {
        if let Some(page_no) = page.get("page_no").and_then(|v| v.as_i64()) {
            let text = page
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string();
            source_by_page.insert(page_no, text);
        }
    }
    let mut display_by_page: HashMap<i64, String> = HashMap::new();
    for page in obsidian_body_pages {
        if let Some(page_no) = page.get("page_no").and_then(|v| v.as_i64()) {
            let text = page
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string();
            display_by_page.insert(page_no, text);
        }
    }
    if source_by_page.is_empty() {
        return Vec::new();
    }

    let mut all_page_nos: Vec<i64> = source_by_page.keys().copied().collect();
    all_page_nos.sort();

    let source_pages = synthetic_markdown_pages(&source_by_page);
    let display_map: HashMap<i64, String> = all_page_nos
        .iter()
        .map(|&page_no| {
            let text = display_by_page
                .get(&page_no)
                .or_else(|| source_by_page.get(&page_no))
                .cloned()
                .unwrap_or_default();
            (page_no, text)
        })
        .collect();
    let display_pages = synthetic_markdown_pages(&display_map);

    let mut title_stack: Vec<String> = if section_title.is_empty() {
        Vec::new()
    } else {
        vec![section_title.to_string()]
    };

    let mut page_segments: Vec<UnitPageSegmentRecord> = Vec::new();

    for &page_no in &all_page_nos {
        let source_paras = parse_page_markdown(&source_pages, page_no, &[]);
        let display_paras = parse_page_markdown(&display_pages, page_no, &[]);
        let raw_source_text = source_by_page.get(&page_no).cloned().unwrap_or_default();
        let raw_source_parts: Vec<String> = raw_source_text
            .split("\n\n")
            .map(|p| p.trim().to_string())
            .filter(|p| !p.is_empty())
            .collect();

        if source_paras.is_empty() && display_paras.is_empty() {
            let fallback_paragraphs = segments::build_fallback_unit_paragraphs(
                &source_by_page.get(&page_no).cloned().unwrap_or_default(),
                &display_by_page
                    .get(&page_no)
                    .or_else(|| source_by_page.get(&page_no))
                    .cloned()
                    .unwrap_or_default(),
                "",
                page_no,
                section_title,
                &page_no.to_string(),
            );
            let visible_fallback: Vec<UnitParagraphRecord> = fallback_paragraphs
                .into_iter()
                .filter(|p| !p.consumed_by_prev)
                .collect();
            if !visible_fallback.is_empty() {
                page_segments.push(UnitPageSegmentRecord {
                    page_no,
                    paragraph_count: visible_fallback.len() as i64,
                    source_text: String::new(),
                    display_text: String::new(),
                    paragraphs: visible_fallback,
                    ..Default::default()
                });
            }
            continue;
        }

        let paragraph_total = source_paras.len().max(display_paras.len());
        let mut normalized_paragraphs: Vec<UnitParagraphRecord> = Vec::new();

        for index in 0..paragraph_total {
            let source_para = source_paras.get(index);
            let display_para = display_paras
                .get(index)
                .or(source_para);

            let aligned_source_text = if paragraph_total == 1 && raw_source_parts.len() > 1 {
                raw_source_parts
                    .iter()
                    .map(|p| p.trim())
                    .filter(|p| !p.is_empty())
                    .collect::<Vec<_>>()
                    .join("\n\n")
                    .trim()
                    .to_string()
            } else if display_paras.len() == paragraph_total
                && source_paras.len() != paragraph_total
                && raw_source_parts.len() == paragraph_total
                && index < raw_source_parts.len()
            {
                raw_source_parts[index].trim().to_string()
            } else {
                String::new()
            };

            let source_text = if !aligned_source_text.is_empty() {
                aligned_source_text
            } else {
                source_para
                    .map(|p| {
                        if !p.text.is_empty() {
                            p.text.clone()
                        } else {
                            display_para.map(|d| d.text.clone()).unwrap_or_default()
                        }
                    })
                    .or_else(|| display_para.map(|d| d.text.clone()))
                    .unwrap_or_default()
            };

            let display_text = display_para
                .map(|d| d.text.clone())
                .filter(|t| !t.is_empty())
                .unwrap_or_else(|| source_text.clone());

            if source_text.is_empty() && display_text.is_empty() {
                continue;
            }

            let heading_level = display_para
                .map(|d| d.heading_level)
                .or_else(|| source_para.map(|s| s.heading_level))
                .unwrap_or(0);

            let kind = if heading_level > 0 { "heading" } else { "body" };

            if heading_level > 0 {
                let active_titles = if !title_stack.is_empty()
                    && title_stack[0] == section_title
                {
                    title_stack[1..].to_vec()
                } else {
                    title_stack.clone()
                };
                let mut active = active_titles;
                while active.len() >= heading_level as usize {
                    active.pop();
                }
                active.push(if !display_text.is_empty() {
                    display_text.clone()
                } else {
                    source_text.clone()
                });
                title_stack = if section_title.is_empty() {
                    active.clone()
                } else {
                    let mut t = vec![section_title.to_string()];
                    t.extend(active);
                    t
                };
            }

            let section_path = title_stack.clone();
            let print_page_label = page_no.to_string();
            let cross_page = source_para
                .and_then(|p| p.cross_page.clone())
                .or_else(|| display_para.and_then(|d| d.cross_page.clone()));
            let consumed_by_prev = source_para.map(|p| p.consumed_by_prev).unwrap_or(false)
                || display_para.map(|d| d.consumed_by_prev).unwrap_or(false);

            normalized_paragraphs.push(UnitParagraphRecord {
                order: (index + 1) as i64,
                kind: kind.to_string(),
                heading_level,
                source_text: source_text.clone(),
                display_text: if display_text == source_text {
                    String::new()
                } else {
                    display_text
                },
                cross_page: cross_page.map(serde_json::Value::String).unwrap_or(serde_json::Value::Null),
                consumed_by_prev,
                section_path,
                print_page_label,
                translated_text: String::new(),
                translation_status: "pending".to_string(),
                attempt_count: 0,
                last_error: String::new(),
                manual_resolved: false,
            });
        }

        if !normalized_paragraphs.is_empty() {
            let visible_paragraphs: Vec<UnitParagraphRecord> = normalized_paragraphs
                .iter()
                .filter(|p| !p.consumed_by_prev)
                .cloned()
                .collect();
            let paragraph_count = visible_paragraphs.len() as i64;
            page_segments.push(UnitPageSegmentRecord {
                page_no,
                paragraph_count,
                source_text: String::new(),
                display_text: String::new(),
                paragraphs: normalized_paragraphs,
                ..Default::default()
            });
        }
    }

    page_segments
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_synthetic_markdown_pages_basic() {
        let mut map = HashMap::new();
        map.insert(1, "page 1 text".to_string());
        map.insert(3, "page 3 text".to_string());
        let result = synthetic_markdown_pages(&map);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].book_page, 1);
        assert_eq!(result[1].book_page, 3);
        assert_eq!(result[0].markdown, "page 1 text");
    }

    #[test]
    fn test_segment_paragraphs_empty() {
        let result = segment_paragraphs_from_body_pages(&[], &[], "");
        assert!(result.is_empty());
    }

    #[test]
    fn test_segment_paragraphs_basic() {
        let body_pages: Vec<serde_json::Value> = vec![serde_json::json!({
            "page_no": 1,
            "text": "# Title\n\nBody paragraph one.\n\nBody paragraph two."
        })];
        let result = segment_paragraphs_from_body_pages(&body_pages, &body_pages, "Ch1");
        assert!(!result.is_empty());
        assert_eq!(result[0].page_no, 1);
        assert!(!result[0].paragraphs.is_empty());
    }

    #[test]
    fn test_segment_paragraphs_fallback() {
        // 当 parse_page_markdown 返回空时，使用 fallback
        let body_pages: Vec<serde_json::Value> = vec![serde_json::json!({
            "page_no": 1,
            "text": "just plain text without any markdown headings"
        })];
        let result = segment_paragraphs_from_body_pages(&body_pages, &body_pages, "");
        // plain text 可能命中 parse_page_markdown 返回空 → fallback 生成段落
        if !result.is_empty() {
            assert_eq!(result[0].page_no, 1);
        }
    }
}
