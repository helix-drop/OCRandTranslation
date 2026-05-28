//! body unit → 段级翻译任务构建。

use serde_json::{json, Value};

use super::progress::raw_pages_label;

/// ←→ Python `build_fnm_body_unit_jobs()`: 从 body unit 构建段级翻译任务。
pub fn build_fnm_body_unit_jobs(unit: &Value, pages: &[Value]) -> Value {
    let section_title = unit
        .get("section_title")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    let mut paragraph_rows: Vec<Value> = Vec::new();

    if let Some(segments) = unit.get("page_segments").and_then(|v| v.as_array()) {
        for segment in segments {
            let page_no = segment.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
            if page_no <= 0 {
                continue;
            }
            let raw_label = raw_pages_label(page_no, pages);
            let display_label = if raw_label == page_no.to_string() {
                raw_label.clone()
            } else {
                format!("[{}]", raw_label)
            };

            if let Some(paragraphs) = segment.get("paragraphs").and_then(|v| v.as_array()) {
                for para in paragraphs {
                    let text = para
                        .get("source_text")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .trim()
                        .to_string();
                    if text.is_empty()
                        || para
                            .get("consumed_by_prev")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false)
                    {
                        continue;
                    }
                    let section_path: Vec<Value> = para
                        .get("section_path")
                        .and_then(|v| v.as_array())
                        .map(|a| {
                            if a.is_empty() && !section_title.is_empty() {
                                vec![json!(section_title)]
                            } else {
                                a.to_vec()
                            }
                        })
                        .unwrap_or_else(|| {
                            if section_title.is_empty() {
                                vec![]
                            } else {
                                vec![json!(section_title)]
                            }
                        });

                    paragraph_rows.push(json!({
                        "page_no": page_no,
                        "text": text,
                        "heading_level": para.get("heading_level").and_then(|v| v.as_i64()).unwrap_or(0),
                        "cross_page": para.get("cross_page"),
                        "print_page_label": raw_label,
                        "print_page_display": display_label,
                        "section_path": section_path,
                    }));
                }
            }
        }
    }

    let count = paragraph_rows.len();
    let mut jobs: Vec<Value> = Vec::with_capacity(count);
    for idx in 0..count {
        let row = &paragraph_rows[idx];
        let prev_text = if idx > 0 {
            paragraph_rows[idx - 1]
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string()
        } else {
            String::new()
        };
        let next_text = if idx + 1 < count {
            paragraph_rows[idx + 1]
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string()
        } else {
            String::new()
        };
        let heading_level = row
            .get("heading_level")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let prev_context = if heading_level > 0 {
            String::new()
        } else {
            let chars: Vec<char> = prev_text.chars().collect();
            let start = if chars.len() > 200 {
                chars.len() - 200
            } else {
                0
            };
            chars[start..].iter().collect()
        };
        let next_context = if heading_level > 0 {
            String::new()
        } else {
            next_text.chars().take(200).collect()
        };

        jobs.push(json!({
            "para_idx": idx,
            "para_total": count,
            "source_idx": idx,
            "bp": row.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0),
            "heading_level": heading_level,
            "text": row.get("text").and_then(|v| v.as_str()).unwrap_or(""),
            "cross_page": row.get("cross_page"),
            "start_bp": row.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0),
            "end_bp": row.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0),
            "print_page_label": row.get("print_page_label").and_then(|v| v.as_str()).unwrap_or(""),
            "print_page_display": row.get("print_page_display").and_then(|v| v.as_str()).unwrap_or(""),
            "bboxes": [],
            "footnotes": "",
            "prev_context": prev_context,
            "next_context": next_context,
            "section_path": row.get("section_path").cloned().unwrap_or(json!([])),
            "content_role": "body",
            "note_kind": "",
            "note_marker": "",
            "note_number": Value::Null,
            "note_section_title": "",
            "note_confidence": 0.0,
        }));
    }

    json!(jobs)
}
