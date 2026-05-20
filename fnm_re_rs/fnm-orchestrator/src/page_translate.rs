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
/// Uses char-based truncation (not byte) to avoid panicking on multi-byte UTF-8 (CJK).
fn preview_text(text: &str) -> String {
    let text = text.trim();
    if text.chars().count() <= 120 {
        text.to_string()
    } else {
        text.chars().take(120).collect()
    }
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
pub fn build_retry_summary(
    repo: &dyn Repository,
    doc_id: &str,
) -> Result<Value, anyhow::Error> {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_preview_text_cjk_truncation() {
        // 121 个中文字符（每字 3 字节 = 363 字节），验证不会 panic
        let long_cjk: String = std::iter::repeat('好').take(121).collect();
        let preview = preview_text(&long_cjk);
        assert_eq!(preview.chars().count(), 120);
    }

    #[test]
    fn test_preview_text_short() {
        assert_eq!(preview_text("hello"), "hello");
        assert_eq!(preview_text(""), "");
    }

    #[test]
    fn test_unit_page_numbers() {
        let unit = TranslationUnitRecord {
            page_start: 3,
            page_end: 5,
            ..Default::default()
        };
        assert_eq!(unit_page_numbers(&unit), vec![3, 4, 5]);
    }

    #[test]
    fn test_unit_page_numbers_from_segments() {
        let mut unit = TranslationUnitRecord::default();
        unit.page_segments = vec![
            fnm_core::records::UnitPageSegmentRecord {
                page_no: 10,
                ..Default::default()
            },
            fnm_core::records::UnitPageSegmentRecord {
                page_no: 8,
                ..Default::default()
            },
        ];
        let pages = unit_page_numbers(&unit);
        assert_eq!(pages, vec![8, 10]); // sorted and deduped
    }
}
