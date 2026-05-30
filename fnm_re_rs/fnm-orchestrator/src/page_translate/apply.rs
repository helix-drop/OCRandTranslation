//! 翻译结果注入。

use serde_json::{json, Value};

/// ←→ Python `apply_body_unit_translations()`: 将译文注入 body unit 的 segments。
///
/// 段落数不匹配时返回 `Err`（P2-6）。
pub fn apply_body_unit_translations(
    unit: &Value,
    translated_paragraphs: &[Value],
) -> Result<Value, anyhow::Error> {
    let translated: Vec<String> = translated_paragraphs
        .iter()
        .map(|v| v.as_str().unwrap_or("").trim().to_string())
        .collect();

    let mut cursor: usize = 0;
    let mut total_parts: usize = 0;
    let mut updated_segments: Vec<Value> = Vec::new();

    if let Some(segments) = unit.get("page_segments").and_then(|v| v.as_array()) {
        for segment in segments {
            let paragraphs: Vec<&Value> = segment
                .get("paragraphs")
                .and_then(|v| v.as_array())
                .map(|a| {
                    a.iter()
                        .filter(|p| {
                            !p.get("consumed_by_prev")
                                .and_then(|v| v.as_bool())
                                .unwrap_or(false)
                        })
                        .collect()
                })
                .unwrap_or_default();

            total_parts += paragraphs.len();
            let next_cursor = cursor + paragraphs.len();
            if next_cursor > translated.len() {
                return Err(anyhow::anyhow!("FNM body unit 段落数与译文数不一致"));
            }
            let translated_parts: Vec<String> = translated[cursor..next_cursor].to_vec();
            cursor = next_cursor;

            let mut updated_paragraphs: Vec<Value> = Vec::new();
            let mut trans_iter = translated_parts.iter();
            if let Some(orig_paragraphs) = segment.get("paragraphs").and_then(|v| v.as_array()) {
                for para in orig_paragraphs {
                    let mut p = para.clone();
                    if p.get("consumed_by_prev")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false)
                    {
                        p["translated_text"] = json!("");
                    } else {
                        p["translated_text"] = json!(trans_iter.next().unwrap_or(&String::new()));
                    }
                    updated_paragraphs.push(p);
                }
            }

            let mut seg: Value = segment.clone();
            seg["paragraphs"] = json!(updated_paragraphs);
            seg["translated_parts"] = json!(translated_parts);
            seg["translated_text"] = json!(translated_parts.join("\n\n"));
            updated_segments.push(seg);
        }
    }

    if cursor != translated.len() || cursor != total_parts {
        return Err(anyhow::anyhow!("FNM body unit 段落数与译文数不一致"));
    }

    Ok(json!({
        "translated_text": translated.join("\n\n"),
        "page_segments": updated_segments,
    }))
}

static UNRESOLVED_STATUSES: [&str; 4] = ["error", "retry_pending", "retrying", "manual_required"];

/// 将单条流式翻译结果应用到段落。
///
/// 返回 `(updated_para, translated_text, failed_location)`。
fn apply_single_paragraph_entry(
    p: &mut Value,
    page_entry: &Value,
    apply_only_unresolved: bool,
    unit_id: &str,
    section_title: &str,
    page_no: i64,
    visible_idx: i64,
) -> (String, Option<Value>) {
    let current_status = p
        .get("translation_status")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let should_apply = !apply_only_unresolved
        || current_status.is_empty()
        || UNRESOLVED_STATUSES.contains(&current_status.as_str());

    if should_apply {
        let translated_text = page_entry
            .get("translation")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let error_text = page_entry
            .get("_error")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let entry_status = page_entry
            .get("_status")
            .and_then(|v| v.as_str())
            .unwrap_or("done")
            .trim()
            .to_lowercase();

        let attempt = p
            .get("attempt_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            .max(0)
            + 1;
        p["attempt_count"] = json!(attempt);
        let manual_resolved = p
            .get("manual_resolved")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        p["manual_resolved"] = json!(manual_resolved);

        if entry_status == "done"
            && !translated_text.is_empty()
            && !translated_text.starts_with("[翻译失败:")
        {
            p["translated_text"] = json!(translated_text);
            p["translation_status"] = json!(if manual_resolved {
                "manual_resolved"
            } else {
                "done"
            });
            p["last_error"] = json!("");
        } else {
            p["translated_text"] = json!("");
            p["translation_status"] = json!("error");
            p["last_error"] = json!(if !error_text.is_empty() {
                error_text
            } else {
                translated_text
            });
        }
    }

    let final_text = p
        .get("translated_text")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    let para_status = p
        .get("translation_status")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let manual_resolved = p
        .get("manual_resolved")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let failed = if UNRESOLVED_STATUSES.contains(&para_status.as_str()) && !manual_resolved {
        Some(json!({
            "unit_id": unit_id,
            "section_title": section_title,
            "page_no": page_no,
            "para_idx": visible_idx,
            "error": p.get("last_error").and_then(|v| v.as_str()).unwrap_or(""),
            "status": para_status,
        }))
    } else {
        None
    };

    (final_text, failed)
}

/// ←→ Python `apply_body_unit_entry_result()`: 将流式翻译结果合并到 unit。
pub fn apply_body_unit_entry_result(
    unit: &Value,
    entry: &Value,
    apply_only_unresolved: bool,
) -> Value {
    let page_entries: Vec<Value> = entry
        .get("_page_entries")
        .and_then(|v| v.as_array())
        .map(|a| a.to_vec())
        .unwrap_or_default();

    let section_title = unit
        .get("section_title")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let unit_id = unit
        .get("unit_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    let mut updated_segments: Vec<Value> = Vec::new();
    let mut failed_locations: Vec<Value> = Vec::new();
    let mut visible_translated_parts: Vec<String> = Vec::new();
    let mut cursor: usize = 0;

    if let Some(segments) = unit.get("page_segments").and_then(|v| v.as_array()) {
        for segment in segments {
            let mut seg: Value = segment.clone();
            let page_no = segment.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
            let mut updated_paragraphs: Vec<Value> = Vec::new();
            let mut seg_translated_parts: Vec<String> = Vec::new();
            let mut visible_idx: i64 = 0;

            if let Some(paragraphs) = segment.get("paragraphs").and_then(|v| v.as_array()) {
                for para in paragraphs {
                    let mut p = para.clone();
                    if p.get("consumed_by_prev")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false)
                    {
                        p["translated_text"] = json!("");
                        updated_paragraphs.push(p);
                        continue;
                    }
                    if cursor >= page_entries.len() {
                        return json!({"error": "FNM body unit 段落数与流式结果不一致"});
                    }
                    let page_entry = page_entries[cursor].clone();
                    cursor += 1;

                    let (final_text, failed) = apply_single_paragraph_entry(
                        &mut p,
                        &page_entry,
                        apply_only_unresolved,
                        &unit_id,
                        &section_title,
                        page_no,
                        visible_idx,
                    );
                    if !final_text.is_empty() {
                        seg_translated_parts.push(final_text.clone());
                        visible_translated_parts.push(final_text);
                    }
                    if let Some(loc) = failed {
                        failed_locations.push(loc);
                    }

                    updated_paragraphs.push(p);
                    visible_idx += 1;
                }
            }

            seg["paragraphs"] = json!(updated_paragraphs);
            seg["translated_parts"] = json!(seg_translated_parts);
            seg["translated_text"] = json!(seg_translated_parts.join("\n\n"));
            updated_segments.push(seg);
        }
    }

    if cursor != page_entries.len() {
        return json!({"error": "FNM body unit 段落数与流式结果不一致"});
    }

    json!({
        "translated_text": visible_translated_parts.join("\n\n"),
        "page_segments": updated_segments,
        "failed_locations": failed_locations,
    })
}
