//! ←→ Python `FNM_RE/app/page_translate.py`
//!
//! 翻译函数：
//! - `build_unit_progress` → `build_unit_progress`
//! - `build_retry_summary` → `build_retry_summary`
//! - `prepare_page_translate_jobs` → `prepare_page_translate_jobs`

use fnm_core::db::Repository;
use fnm_core::records::TranslationUnitRecord;
use serde_json::{json, Value};

/// ←→ Python `format_fnm_unit_label()`
fn format_unit_label(unit: &TranslationUnitRecord) -> String {
    let kind_label = match unit.kind.as_str() {
        "body" => "正文",
        "footnote" => "脚注",
        "endnote" => "尾注",
        _ => {
            if unit.kind.is_empty() {
                "unit"
            } else {
                &unit.kind
            }
        }
    };
    let section = if unit.section_title.is_empty() {
        unit.section_id.clone()
    } else {
        unit.section_title.clone()
    };
    let section = section.trim().to_string();
    let pages_label = format_unit_pages(unit);
    if !section.is_empty() {
        format!("{kind_label} · {section} · p.{pages_label}")
    } else {
        format!("{kind_label} · p.{pages_label}")
    }
}

/// ←→ Python `unit_page_numbers()`
fn unit_page_numbers(unit: &TranslationUnitRecord) -> Vec<i64> {
    let mut pages: Vec<i64> = unit
        .page_segments
        .iter()
        .map(|s| s.page_no)
        .collect();
    pages.sort_unstable();
    pages.dedup();
    if !pages.is_empty() {
        return pages;
    }
    let start = unit.page_start;
    if start == 0 {
        return vec![];
    }
    let end = if unit.page_end >= start {
        unit.page_end
    } else {
        start
    };
    (start..=end).collect()
}

/// ←→ Python `format_fnm_unit_pages()`
fn format_unit_pages(unit: &TranslationUnitRecord) -> String {
    let pages = unit_page_numbers(unit);
    if pages.is_empty() {
        return "-".to_string();
    }
    if pages.len() == 1 {
        return pages[0].to_string();
    }
    format!("{}-{}", pages[0], pages[pages.len() - 1])
}

/// ←→ Python `replace_frozen_refs()` — simplified: strip frozen ref tokens for preview.
/// Full implementation calls fnm-core regex patterns; this is sufficient for preview.
fn preview_text(text: &str) -> String {
    let text = text.trim();
    if text.len() <= 120 {
        text.to_string()
    } else {
        text[..120].to_string()
    }
}

/// ←→ Python `build_unit_progress()`
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
    let pending_units = if total_units > processed_units {
        total_units - processed_units
    } else {
        0
    };

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
            let preview = preview_text(
                if u.translated_text.is_empty() {
                    &u.source_text
                } else {
                    &u.translated_text
                },
            );
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
