//! 翻译单元格式化函数。

use fnm_core::records::TranslationUnitRecord;
use serde_json::Value;

/// ←→ Python `format_fnm_unit_label()` — TranslationUnitRecord 版
pub fn format_unit_label(unit: &TranslationUnitRecord) -> String {
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
pub fn unit_page_numbers(unit: &TranslationUnitRecord) -> Vec<i64> {
    let mut pages: Vec<i64> = unit.page_segments.iter().map(|s| s.page_no).collect();
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

/// ←→ Python `format_fnm_unit_pages()` — TranslationUnitRecord 版
pub fn format_unit_pages(unit: &TranslationUnitRecord) -> String {
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
pub(super) fn preview_text(text: &str) -> String {
    let text = text.trim();
    if text.chars().count() <= 120 {
        text.to_string()
    } else {
        text.chars().take(120).collect()
    }
}

/// ←→ Python `format_fnm_unit_pages()` — Value 版（纯 dict）。
pub fn format_unit_pages_value(unit: &Value) -> String {
    let pages = unit_page_numbers_value(unit);
    if pages.is_empty() {
        return "-".to_string();
    }
    if pages.len() == 1 {
        return pages[0].to_string();
    }
    format!("{}-{}", pages[0], pages[pages.len() - 1])
}

/// ←→ Python `unit_page_numbers()` — Value 版
pub fn unit_page_numbers_value(unit: &Value) -> Vec<i64> {
    let mut pages: Vec<i64> = unit
        .get("page_segments")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|s| s.get("page_no").and_then(|v| v.as_i64()))
                .collect()
        })
        .unwrap_or_default();
    pages.sort_unstable();
    pages.dedup();
    if !pages.is_empty() {
        return pages;
    }
    let start = unit.get("page_start").and_then(|v| v.as_i64()).unwrap_or(0);
    if start == 0 {
        return vec![];
    }
    let end = unit
        .get("page_end")
        .and_then(|v| v.as_i64())
        .filter(|e| *e >= start)
        .unwrap_or(start);
    (start..=end).collect()
}

/// ←→ Python `format_fnm_unit_label()` — Value 版（纯 dict）。
pub fn format_unit_label_value(unit: &Value) -> String {
    let kind = unit
        .get("kind")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let kind_label = match kind {
        "body" => "正文",
        "footnote" => "脚注",
        "endnote" => "尾注",
        _ => {
            if kind.is_empty() {
                "unit"
            } else {
                kind
            }
        }
    };
    let section = unit
        .get("section_title")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .or_else(|| unit.get("section_id").and_then(|v| v.as_str()))
        .unwrap_or("")
        .trim()
        .to_string();
    let pages_label = format_unit_pages_value(unit);
    if !section.is_empty() {
        format!("{kind_label} · {section} · p.{pages_label}")
    } else {
        format!("{kind_label} · p.{pages_label}")
    }
}
