//! 重试摘要与失败位置收集。

use fnm_core::db::Repository;
use fnm_core::records::TranslationUnitRecord;
use serde_json::{json, Value};

/// ←→ Python `collect_fnm_unit_failed_locations()` — Value 版（纯 dict）。
pub fn collect_unit_failed_locations_value(unit: &Value) -> Vec<Value> {
    let section_title = unit
        .get("section_title")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let mut locations: Vec<Value> = Vec::new();
    if let Some(segments) = unit.get("page_segments").and_then(|v| v.as_array()) {
        for segment in segments {
            let page_no = segment.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
            let mut visible_idx: i64 = 0;
            if let Some(paragraphs) = segment.get("paragraphs").and_then(|v| v.as_array()) {
                for para in paragraphs {
                    if para
                        .get("consumed_by_prev")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false)
                    {
                        continue;  // consumed_by_prev 段落不计入 visible_idx
                    }
                    let status = para
                        .get("translation_status")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .trim()
                        .to_string();
                    let is_failed = status == "error"
                        || status == "retry_pending"
                        || status == "retrying"
                        || status == "manual_required";
                    let manual_resolved = para
                        .get("manual_resolved")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false);
                    if is_failed && !manual_resolved {
                        locations.push(json!({
                            "unit_id": unit.get("unit_id").and_then(|v| v.as_str()).unwrap_or(""),
                            "section_title": section_title,
                            "page_no": page_no,
                            "para_idx": visible_idx,
                            "error": para.get("last_error").and_then(|v| v.as_str()).unwrap_or(""),
                            "status": status,
                        }));
                    }
                    visible_idx += 1;
                }
            }
        }
    }
    locations
}

/// ←→ Python `list_fnm_units_with_indices()` — DB 驱动。
pub fn list_fnm_units_with_indices(
    repo: &dyn Repository,
    doc_id: &str,
) -> Result<Vec<Value>, anyhow::Error> {
    let units = repo.list_fnm_translation_units(doc_id)?;
    let result: Vec<Value> = units
        .into_iter()
        .enumerate()
        .map(|(idx, unit)| {
            let unit_id = unit.unit_id.clone();
            let kind = unit.kind.clone();
            let section_title = unit.section_title.clone();
            let status = unit.status.clone();
            let source_text = unit.source_text.clone();
            let translated_text = unit.translated_text.clone();
            let page_start = unit.page_start;
            let page_end = unit.page_end;
            let error_msg = unit.error_msg.clone();

            json!({
                "unit_id": unit_id,
                "unit_idx": (idx + 1) as i64,
                "kind": kind,
                "section_title": section_title,
                "status": status,
                "source_text": source_text,
                "translated_text": translated_text,
                "page_start": page_start,
                "page_end": page_end,
                "error_msg": error_msg,
                "page_segments": unit.page_segments,
            })
        })
        .collect();
    Ok(result)
}

/// ←→ Python `sync_fnm_retry_state()` — 返回 retry summary，Python wrapper 处理 translate state 持久化。
pub fn sync_fnm_retry_state(repo: &dyn Repository, doc_id: &str) -> Result<Value, anyhow::Error> {
    build_retry_summary(repo, doc_id)
}

/// ←→ Python `rebuild_fnm_diagnostic_page_entries()` — 从 DB 读取 diagnostic pages BPs。
pub fn rebuild_fnm_diagnostic_page_entries(
    repo: &dyn Repository,
    doc_id: &str,
) -> Result<Vec<i64>, anyhow::Error> {
    let entries = repo.list_fnm_diagnostic_pages(doc_id)?;
    let bps: Vec<i64> = entries.into_iter().map(|e| e._page_bp).collect();
    Ok(bps)
}

/// ←→ Python `collect_fnm_unit_failed_locations()`
fn collect_failed_locations(unit: &TranslationUnitRecord) -> Vec<Value> {
    let section_title = unit.section_title.trim().to_string();
    let mut locations: Vec<Value> = Vec::new();
    for segment in &unit.page_segments {
        let page_no = segment.page_no;
        let mut visible_idx: i64 = 0;
        for para in &segment.paragraphs {
            if para.consumed_by_prev {
                continue;
            }
            let status = para.translation_status.trim();
            let is_failed = status == "error"
                || status == "retry_pending"
                || status == "retrying"
                || status == "manual_required";
            if is_failed && !para.manual_resolved {
                locations.push(json!({
                    "unit_id": unit.unit_id,
                    "section_title": section_title,
                    "page_no": page_no,
                    "para_idx": visible_idx,
                    "error": para.last_error,
                    "status": status,
                }));
            }
            visible_idx += 1;
        }
    }
    locations
}

/// ←→ Python `build_retry_summary()` — 从 translation units 派生失败位置，
/// 不依赖 Python `_load_translate_state`（去掉 snapshot 分支）。
pub fn build_retry_summary(repo: &dyn Repository, doc_id: &str) -> Result<Value, anyhow::Error> {
    let units = repo.list_fnm_translation_units(doc_id)?;

    let mut failed_locations: Vec<Value> = Vec::new();
    let mut manual_required_locations: Vec<Value> = Vec::new();

    for unit in &units {
        if unit.kind != "body" {
            continue;
        }
        for loc in collect_failed_locations(unit) {
            let is_manual = loc.get("status").and_then(|s| s.as_str()) == Some("manual_required");
            if is_manual {
                manual_required_locations.push(loc.clone());
            }
            failed_locations.push(loc);
        }
    }

    let unresolved_count = failed_locations.len() as i64;
    let manual_required_count = manual_required_locations.len() as i64;

    let blocking_export = false; // Python 也硬编码 false（real 模式不阻塞）
    let reason = if manual_required_count > 0 {
        "manual_required"
    } else if unresolved_count > 0 {
        "unresolved"
    } else {
        ""
    };

    let next_failed_location = manual_required_locations
        .first()
        .or_else(|| failed_locations.first())
        .cloned();

    Ok(json!({
        "execution_mode": "test",
        "retry_progress": {
            "retry_round": 0,
            "unresolved_count": unresolved_count,
            "manual_required_count": manual_required_count,
        },
        "failed_locations": failed_locations,
        "manual_required_locations": manual_required_locations,
        "next_failed_location": next_failed_location,
        "blocking_export": blocking_export,
        "blocking_reason": reason,
    }))
}
