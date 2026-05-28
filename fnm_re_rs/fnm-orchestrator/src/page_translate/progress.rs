//! 进度报告。

use fnm_core::db::Repository;
use fnm_core::records::TranslationUnitRecord;
use serde_json::{json, Value};

use super::format::preview_text;
use super::format::{format_unit_label, format_unit_pages};

pub fn build_unit_progress(
    repo: &dyn Repository,
    doc_id: &str,
    snapshot_json: Option<&str>,
    _use_lightweight: bool,
) -> Result<Value, anyhow::Error> {
    let raw_units = repo.list_fnm_translation_units(doc_id)?;
    let units: Vec<(usize, &TranslationUnitRecord)> = raw_units.iter().enumerate().collect();

    let total_units = units.len();
    let done_units = units.iter().filter(|(_, u)| u.status == "done").count();
    let error_unit_indices: Vec<i64> = units
        .iter()
        .filter(|(_, u)| u.status == "error")
        .map(|(i, _)| *i as i64 + 1)
        .collect();
    let error_units = error_unit_indices.len();
    let processed_units = done_units + error_units;
    let pending_units = total_units.saturating_sub(processed_units);

    // Parse snapshot for current_bp
    let current_idx: Option<i64> = snapshot_json.and_then(|s| {
        let v: Value = serde_json::from_str(s).ok()?;
        let candidate = v.get("current_bp")?;
        let n = candidate.as_i64()?;
        if n >= 1 && n <= total_units as i64 {
            Some(n)
        } else {
            None
        }
    });

    let current_unit = current_idx.and_then(|idx| {
        let pos = idx as usize - 1;
        units.get(pos).map(|(_, u)| *u)
    });

    let unit_items: Vec<Value> = units
        .iter()
        .map(|(idx, u)| {
            let unit_idx = *idx as i64 + 1;
            let status = u.status.as_str();
            let preview = preview_text(if u.translated_text.is_empty() {
                &u.source_text
            } else {
                &u.translated_text
            });
            json!({
                "unit_idx": unit_idx,
                "unit_id": u.unit_id,
                "kind": u.kind,
                "label": format_unit_label(u),
                "pages": format_unit_pages(u),
                "status": status,
                "error_msg": u.error_msg,
                "preview": preview,
            })
        })
        .collect();

    Ok(json!({
        "total_units": total_units,
        "done_units": done_units,
        "error_units": error_units,
        "failed_unit_indices": error_unit_indices,
        "processed_units": processed_units,
        "pending_units": pending_units,
        "current_unit_idx": current_idx,
        "current_unit_id": current_unit.map(|u| u.unit_id.as_str()),
        "current_unit_kind": current_unit.map(|u| u.kind.as_str()),
        "current_unit_label": current_unit.map(format_unit_label),
        "current_unit_pages": current_unit.map(format_unit_pages),
        "unit_items": unit_items,
    }))
}

/// ←→ Python `_raw_pages_label()`: 从 pages 列表中查找页面的 print_page_label。
pub(super) fn raw_pages_label(page_no: i64, pages: &[Value]) -> String {
    for p in pages {
        if p.get("bookPage").and_then(|v| v.as_i64()).unwrap_or(0) == page_no {
            if let Some(label) = p.get("print_page_label").and_then(|v| v.as_str()) {
                if !label.is_empty() {
                    return label.to_string();
                }
            }
        }
    }
    page_no.to_string()
}
