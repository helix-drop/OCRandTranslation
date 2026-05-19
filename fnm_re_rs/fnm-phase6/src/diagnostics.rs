//! Diagnostic 投影。
//!
//! ←→ Python `FNM_RE/stages/diagnostics.py` (336 行 / 10 函数)

use std::collections::HashMap;

use fnm_core::records::{
    ChapterRecord, DiagnosticEntryRecord, DiagnosticNoteRecord, DiagnosticPageRecord,
    NoteRegionRecord, Phase4Structure, TranslationUnitRecord, UnitPageSegmentRecord,
    UnitParagraphRecord,
};
use fnm_core::refs::{extract_note_refs, replace_frozen_refs, EndnoteMode};

/// 错误翻译状态集合
static _ERROR_TRANSLATION_STATUSES: &[&str] =
    &["error", "retry_pending", "retrying", "manual_required"];

/// 已完成翻译状态集合
static _DONE_UNIT_STATUSES: &[&str] = &["done", "done_manual"];

/// 从 pages 提取 {bookPage: printPageLabel} 轻量映射。
///
/// ←→ Python `build_print_page_map()` (diagnostics.py:24)
pub fn build_print_page_map(pages: &[serde_json::Value]) -> HashMap<i64, String> {
    let mut result = HashMap::new();
    for page in pages {
        let bp = page.get("bookPage").and_then(|v| v.as_i64()).unwrap_or(0);
        if bp <= 0 {
            continue;
        }
        let label = page
            .get("printPageLabel")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let label = if label.is_empty() {
            page.get("printPage")
                .and_then(|v| v.as_i64())
                .filter(|&pp| pp > 0)
                .map(|pp| pp.to_string())
                .unwrap_or_else(|| bp.to_string())
        } else {
            label
        };
        result.insert(bp, label);
    }
    result
}

/// 获取原始打印页标签。
///
/// ←→ Python `_raw_print_page_label()` (diagnostics.py:42)
pub fn raw_print_page_label(page_no: i64, print_pages: &HashMap<i64, String>) -> String {
    print_pages
        .get(&page_no)
        .cloned()
        .unwrap_or_else(|| page_no.to_string())
}

/// 获取显示用的页码标签。
///
/// ←→ Python `_display_pages_label()` (diagnostics.py:63)
pub fn display_pages_label(page_no: i64, print_pages: &HashMap<i64, String>) -> String {
    let raw = raw_print_page_label(page_no, print_pages);
    if raw.is_empty() {
        return String::new();
    }
    if raw.starts_with("原书 p.") {
        raw
    } else {
        format!("原书 p.{}", raw)
    }
}

/// 从任意格式转换为 UnitPageSegmentRecord。
///
/// ←→ Python `_segment_from_any()` (diagnostics.py:70)
pub fn segment_from_any(payload: &serde_json::Value) -> UnitPageSegmentRecord {
    // 如果已经是 UnitPageSegmentRecord 类型（通过 serde_json 转换）
    if let Ok(segment) = serde_json::from_value::<UnitPageSegmentRecord>(payload.clone()) {
        return segment;
    }

    // 否则手动构建
    let paragraphs: Vec<UnitParagraphRecord> = payload
        .get("paragraphs")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .enumerate()
                .map(|(idx, row)| {
                    if let Ok(p) = serde_json::from_value::<UnitParagraphRecord>(row.clone()) {
                        return p;
                    }
                    UnitParagraphRecord {
                        order: row
                            .get("order")
                            .and_then(|v| v.as_i64())
                            .unwrap_or(idx as i64 + 1),
                        kind: row
                            .get("kind")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                        heading_level: row
                            .get("heading_level")
                            .and_then(|v| v.as_i64())
                            .unwrap_or(0),
                        source_text: row
                            .get("source_text")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                        display_text: row
                            .get("display_text")
                            .and_then(|v| v.as_str())
                            .or_else(|| row.get("source_text").and_then(|v| v.as_str()))
                            .unwrap_or("")
                            .to_string(),
                        cross_page: row
                            .get("cross_page")
                            .cloned()
                            .unwrap_or(serde_json::Value::Null),
                        consumed_by_prev: row
                            .get("consumed_by_prev")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false),
                        section_path: row
                            .get("section_path")
                            .and_then(|v| v.as_array())
                            .map(|arr| {
                                arr.iter()
                                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                                    .collect()
                            })
                            .unwrap_or_default(),
                        print_page_label: row
                            .get("print_page_label")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                        translated_text: row
                            .get("translated_text")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                        translation_status: row
                            .get("translation_status")
                            .and_then(|v| v.as_str())
                            .unwrap_or("pending")
                            .to_string(),
                        attempt_count: row
                            .get("attempt_count")
                            .and_then(|v| v.as_i64())
                            .unwrap_or(0)
                            .max(0),
                        last_error: row
                            .get("last_error")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                        manual_resolved: row
                            .get("manual_resolved")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false),
                    }
                })
                .collect()
        })
        .unwrap_or_default();

    UnitPageSegmentRecord {
        page_no: payload.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0),
        paragraph_count: payload
            .get("paragraph_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        source_text: payload
            .get("source_text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        display_text: payload
            .get("display_text")
            .and_then(|v| v.as_str())
            .or_else(|| payload.get("source_text").and_then(|v| v.as_str()))
            .unwrap_or("")
            .to_string(),
        paragraphs,
    }
}

/// 获取段落的翻译状态。
///
/// ←→ Python `_entry_status()` (diagnostics.py:105)
pub fn entry_status(paragraph: &UnitParagraphRecord) -> String {
    let status = paragraph.translation_status.trim();
    if _ERROR_TRANSLATION_STATUSES.contains(&status) {
        return "error".to_string();
    }
    if !paragraph.translated_text.trim().is_empty() {
        return "done".to_string();
    }
    "pending".to_string()
}

/// 构建诊断条目。
///
/// ←→ Python `_build_diagnostic_entry()` (diagnostics.py:114)
pub fn build_diagnostic_entry(
    page_no: i64,
    paragraph: &UnitParagraphRecord,
    print_pages: &HashMap<i64, String>,
) -> DiagnosticEntryRecord {
    let source_text = {
        let display = paragraph.display_text.trim();
        if !display.is_empty() {
            display.to_string()
        } else {
            paragraph.source_text.trim().to_string()
        }
    };
    let translated_text = paragraph.translated_text.trim().to_string();
    let translation_status = if !paragraph.translation_status.trim().is_empty() {
        paragraph.translation_status.trim().to_string()
    } else if !translated_text.is_empty() {
        "done".to_string()
    } else {
        "pending".to_string()
    };

    let entry_text = if !translated_text.is_empty() {
        replace_frozen_refs(&translated_text, EndnoteMode::Legacy)
    } else {
        replace_frozen_refs(&source_text, EndnoteMode::Legacy)
    };

    let mut refs: Vec<serde_json::Value> = Vec::new();
    let mut seen_refs: std::collections::HashSet<(String, String)> =
        std::collections::HashSet::new();

    for candidate in &[
        &paragraph.source_text,
        &paragraph.display_text,
        &paragraph.translated_text,
        &source_text,
        &translated_text,
    ] {
        for ref_item in extract_note_refs(candidate) {
            let key = (ref_item.kind.as_str().to_string(), ref_item.note_id.clone());
            if seen_refs.contains(&key) {
                continue;
            }
            seen_refs.insert(key.clone());
            refs.push(serde_json::json!({
                "kind": key.0,
                "note_id": key.1,
            }));
        }
    }

    DiagnosticEntryRecord {
        original: replace_frozen_refs(&source_text, EndnoteMode::Legacy),
        translation: entry_text.clone(),
        footnotes: String::new(),
        footnotes_translation: String::new(),
        heading_level: paragraph.heading_level,
        pages: display_pages_label(page_no, print_pages),
        _start_bp: page_no,
        _end_bp: page_no,
        _print_page_label: raw_print_page_label(page_no, print_pages),
        _status: entry_status(paragraph),
        _error: paragraph.last_error.clone(),
        _translation_source: if paragraph.manual_resolved {
            "manual".to_string()
        } else if !translated_text.is_empty() {
            "model".to_string()
        } else {
            "source".to_string()
        },
        _machine_translation: if !translated_text.is_empty() {
            entry_text.clone()
        } else {
            String::new()
        },
        _manual_translation: if paragraph.manual_resolved {
            entry_text.clone()
        } else {
            String::new()
        },
        _cross_page: paragraph.cross_page.clone(),
        _section_path: paragraph.section_path.clone(),
        _fnm_refs: refs,
        _note_kind: String::new(),
        _note_marker: String::new(),
        _note_number: None,
        _note_section_title: String::new(),
        _note_confidence: 0.0,
        _translation_status: translation_status,
        _attempt_count: paragraph.attempt_count.max(0),
        _manual_resolved: paragraph.manual_resolved,
    }
}

/// 构建 note_id → TranslationUnitRecord 映射。
///
/// ←→ Python `_note_unit_by_note_id()` (diagnostics.py:170)
pub fn note_unit_by_note_id(
    translation_units: &[TranslationUnitRecord],
) -> HashMap<String, &TranslationUnitRecord> {
    let mut payload = HashMap::new();
    for unit in translation_units {
        if unit.kind != "footnote" && unit.kind != "endnote" {
            continue;
        }
        let note_id = unit.note_id.trim().to_string();
        if !note_id.is_empty() {
            payload.insert(note_id, unit);
        }
    }
    payload
}

/// 构建 chapter_id → ChapterRecord 映射。
///
/// ←→ Python `_chapter_meta_by_id()` (diagnostics.py:181)
pub fn chapter_meta_by_id(phase4: &Phase4Structure) -> HashMap<String, &ChapterRecord> {
    phase4
        .chapters
        .iter()
        .filter(|ch| !ch.chapter_id.trim().is_empty())
        .map(|ch| (ch.chapter_id.trim().to_string(), ch))
        .collect()
}

/// 构建 region_id → NoteRegionRecord 映射。
///
/// ←→ Python `_note_region_by_id()` (diagnostics.py:189)
pub fn note_region_by_id(phase4: &Phase4Structure) -> HashMap<String, &NoteRegionRecord> {
    phase4
        .note_regions
        .iter()
        .filter(|r| !r.region_id.trim().is_empty())
        .map(|r| (r.region_id.trim().to_string(), r))
        .collect()
}

/// 构建诊断投影。
///
/// ←→ Python `build_diagnostic_projection()` (diagnostics.py:197)
pub fn build_diagnostic_projection(
    phase4: &Phase4Structure,
    translation_units: &[TranslationUnitRecord],
    print_page_map: Option<&HashMap<i64, String>>,
    only_pages: Option<&[i64]>,
) -> (
    Vec<DiagnosticPageRecord>,
    Vec<DiagnosticNoteRecord>,
    serde_json::Value,
) {
    let empty_map = HashMap::new();
    let print_pages = print_page_map.unwrap_or(&empty_map);

    let visible_page_filter: std::collections::HashSet<i64> = only_pages
        .map(|pages| pages.iter().filter(|&&p| p > 0).copied().collect())
        .unwrap_or_default();

    let mut page_rows: HashMap<i64, DiagnosticPageRecord> = HashMap::new();

    // 处理 body units
    for unit in translation_units {
        if unit.kind != "body" {
            continue;
        }
        let source_meta = serde_json::json!({
            "section_id": unit.section_id,
            "section_title": unit.section_title,
            "section_start_page": unit.section_start_page,
            "section_end_page": unit.section_end_page,
            "unit_id": unit.unit_id,
        });

        for raw_segment in &unit.page_segments {
            let segment = if let Ok(s) = serde_json::from_value::<UnitPageSegmentRecord>(
                serde_json::to_value(raw_segment).unwrap_or_default(),
            ) {
                s
            } else {
                segment_from_any(&serde_json::to_value(raw_segment).unwrap_or_default())
            };

            let page_no = segment.page_no;
            if page_no <= 0 {
                continue;
            }
            if !visible_page_filter.is_empty() && !visible_page_filter.contains(&page_no) {
                continue;
            }

            let page_row = page_rows
                .entry(page_no)
                .or_insert_with(|| DiagnosticPageRecord {
                    _page_bp: page_no,
                    _status: "pending".to_string(),
                    pages: display_pages_label(page_no, print_pages),
                    _page_entries: Vec::new(),
                    _fnm_source: source_meta.clone(),
                });

            for paragraph in &segment.paragraphs {
                if paragraph.consumed_by_prev {
                    continue;
                }
                page_row._page_entries.push(build_diagnostic_entry(
                    page_no,
                    paragraph,
                    print_pages,
                ));
            }

            if page_row._page_entries.iter().any(|e| e._status == "error") {
                page_row._status = "error".to_string();
            } else if page_row._page_entries.iter().any(|e| e._status == "done") {
                page_row._status = "done".to_string();
            }
        }
    }

    let mut diagnostic_pages: Vec<DiagnosticPageRecord> = page_rows.into_values().collect();
    diagnostic_pages.sort_by_key(|p| p._page_bp);

    // 处理 notes
    let chapter_by_id = chapter_meta_by_id(phase4);
    let note_region_by_id_map = note_region_by_id(phase4);
    let note_units = note_unit_by_note_id(translation_units);

    let mut diagnostic_notes: Vec<DiagnosticNoteRecord> = Vec::new();
    for item in &phase4.note_items {
        let note_id = item.note_item_id.trim().to_string();
        if note_id.is_empty() {
            continue;
        }
        let chapter_id = item.chapter_id.trim().to_string();
        let chapter = chapter_by_id.get(&chapter_id);
        let region = note_region_by_id_map.get(item.region_id.trim());
        let unit = note_units.get(&note_id);

        let note_kind = region
            .map(|r| r.note_kind.as_str().to_string())
            .unwrap_or_else(|| item.note_kind.as_str().to_string());

        let start_page = item.page_no.max(unit.map(|u| u.page_start).unwrap_or(0));

        diagnostic_notes.push(DiagnosticNoteRecord {
            note_id,
            section_id: chapter_id.clone(),
            section_title: chapter
                .map(|ch| ch.title.clone())
                .unwrap_or_else(|| chapter_id),
            section_start_page: chapter.map(|ch| ch.start_page).unwrap_or(0),
            section_end_page: chapter.map(|ch| ch.end_page).unwrap_or(0),
            kind: note_kind,
            original_marker: item.marker.clone(),
            start_page,
            pages: if start_page > 0 {
                vec![start_page]
            } else {
                vec![]
            },
            source_text: {
                let text = item.text.trim();
                if !text.is_empty() {
                    text.to_string()
                } else {
                    unit.map(|u| u.source_text.clone()).unwrap_or_default()
                }
            },
            translated_text: unit.map(|u| u.translated_text.clone()).unwrap_or_default(),
            translate_status: unit
                .map(|u| u.status.clone())
                .unwrap_or_else(|| "pending".to_string()),
            region_id: item.region_id.clone(),
        });
    }

    diagnostic_notes.sort_by(|a, b| {
        a.section_start_page
            .cmp(&b.section_start_page)
            .then(a.start_page.cmp(&b.start_page))
            .then(a.kind.cmp(&b.kind))
            .then(a.note_id.cmp(&b.note_id))
    });

    // 统计
    let page_entry_count: usize = diagnostic_pages.iter().map(|p| p._page_entries.len()).sum();
    let translated_page_count = diagnostic_pages
        .iter()
        .filter(|p| {
            p._page_entries
                .iter()
                .any(|e| e._translation_source != "source")
        })
        .count();

    let note_count = diagnostic_notes.len();
    let translated_count = diagnostic_notes
        .iter()
        .filter(|n| {
            _DONE_UNIT_STATUSES.contains(&n.translate_status.as_str())
                || !n.translated_text.trim().is_empty()
        })
        .count();
    let pending_count = diagnostic_notes
        .iter()
        .filter(|n| {
            !_DONE_UNIT_STATUSES.contains(&n.translate_status.as_str())
                && !_ERROR_TRANSLATION_STATUSES.contains(&n.translate_status.as_str())
                && n.translated_text.trim().is_empty()
        })
        .count();
    let error_count = diagnostic_notes
        .iter()
        .filter(|n| _ERROR_TRANSLATION_STATUSES.contains(&n.translate_status.as_str()))
        .count();

    let diagnostic_summary = serde_json::json!({
        "diagnostic_page_summary": {
            "page_count": diagnostic_pages.len(),
            "entry_count": page_entry_count,
            "error_page_count": diagnostic_pages.iter().filter(|p| p._status == "error").count(),
            "translated_page_count": translated_page_count,
        },
        "diagnostic_note_summary": {
            "note_count": note_count,
            "translated_count": translated_count,
            "pending_count": pending_count,
            "error_count": error_count,
        },
    });

    (diagnostic_pages, diagnostic_notes, diagnostic_summary)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_print_page_map() {
        let pages = vec![
            serde_json::json!({"bookPage": 1, "printPageLabel": "i"}),
            serde_json::json!({"bookPage": 2, "printPage": 2}),
            serde_json::json!({"bookPage": 0}), // 应该被跳过
        ];
        let result = build_print_page_map(&pages);
        assert_eq!(result.len(), 2);
        assert_eq!(result.get(&1).unwrap(), "i");
        assert_eq!(result.get(&2).unwrap(), "2");
    }

    #[test]
    fn test_raw_print_page_label() {
        let mut pages = HashMap::new();
        pages.insert(1, "i".to_string());
        assert_eq!(raw_print_page_label(1, &pages), "i");
        assert_eq!(raw_print_page_label(99, &pages), "99");
    }

    #[test]
    fn test_display_pages_label() {
        let mut pages = HashMap::new();
        pages.insert(1, "i".to_string());
        assert_eq!(display_pages_label(1, &pages), "原书 p.i");
        assert_eq!(display_pages_label(99, &pages), "原书 p.99");
    }

    #[test]
    fn test_entry_status() {
        let mut p = UnitParagraphRecord::default();
        p.translation_status = "error".to_string();
        assert_eq!(entry_status(&p), "error");

        p.translation_status = "done".to_string();
        p.translated_text = "translated".to_string();
        assert_eq!(entry_status(&p), "done");

        p.translation_status = "pending".to_string();
        p.translated_text = "".to_string();
        assert_eq!(entry_status(&p), "pending");
    }

    #[test]
    fn test_note_unit_by_note_id() {
        let units = vec![
            TranslationUnitRecord {
                kind: "body".to_string(),
                note_id: "n1".to_string(),
                ..Default::default()
            },
            TranslationUnitRecord {
                kind: "footnote".to_string(),
                note_id: "n2".to_string(),
                ..Default::default()
            },
        ];
        let result = note_unit_by_note_id(&units);
        assert_eq!(result.len(), 1);
        assert!(result.contains_key("n2"));
    }

    #[test]
    fn test_chapter_meta_by_id() {
        let phase4 = Phase4Structure {
            chapters: vec![ChapterRecord {
                chapter_id: "ch1".to_string(),
                title: "Chapter 1".to_string(),
                start_page: 0,
                end_page: 0,
                pages: vec![],
                source: fnm_core::types::ChapterSource::Fallback,
                boundary_state: fnm_core::types::BoundaryState::Ready,
            }],
            ..Default::default()
        };
        let result = chapter_meta_by_id(&phase4);
        assert_eq!(result.len(), 1);
        assert!(result.contains_key("ch1"));
    }
}
