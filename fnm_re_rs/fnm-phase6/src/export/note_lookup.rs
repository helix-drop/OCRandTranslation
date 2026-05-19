//! ←→ FNM_RE/stages/export.py `_build_note_text_by_id_for_chapter()`,
//! `_build_note_kind_by_id_for_chapter()`, `_build_marker_by_note_id_for_chapter()`

use std::collections::HashMap;

use fnm_core::export_constants::should_replace_definition_text;
use fnm_core::note_lookup::sanitize_note_text;
use fnm_core::records::{NoteLinkRecord, TranslationUnitRecord};

/// 按章构建 note_id → 清洗后 note_text 映射。
///
/// ←→ Python `_build_note_text_by_id_for_chapter()` (export.py:176)
pub fn build_note_text_by_id_for_chapter(
    chapter_id: Option<&str>,
    note_units: &[TranslationUnitRecord],
) -> HashMap<String, String> {
    let mut payload: HashMap<String, String> = HashMap::new();
    for unit in note_units {
        if let Some(cid) = chapter_id {
            if unit.section_id != cid {
                continue;
            }
        }
        if unit.kind != "footnote" && unit.kind != "endnote" {
            continue;
        }
        let note_id = unit.note_id.trim().to_string();
        if note_id.is_empty() {
            continue;
        }
        let source = if !unit.translated_text.trim().is_empty() {
            &unit.translated_text
        } else {
            &unit.source_text
        };
        let note_text = sanitize_note_text(source);
        if should_replace_definition_text(
            payload.get(&note_id).map_or("", |s| s.as_str()),
            &note_text,
        ) {
            payload.insert(note_id, note_text);
        }
    }
    payload
}

/// 按章构建 note_id → note_kind 映射。
///
/// ←→ Python `_build_note_kind_by_id_for_chapter()` (export.py:196)
pub fn build_note_kind_by_id_for_chapter(
    chapter_id: Option<&str>,
    note_units: &[TranslationUnitRecord],
) -> HashMap<String, String> {
    let mut payload: HashMap<String, String> = HashMap::new();
    for unit in note_units {
        if let Some(cid) = chapter_id {
            if unit.section_id != cid {
                continue;
            }
        }
        let kind = unit.kind.trim().to_lowercase();
        if kind != "footnote" && kind != "endnote" {
            continue;
        }
        let note_id = unit.note_id.trim().to_string();
        if !note_id.is_empty() && !payload.contains_key(&note_id) {
            payload.insert(note_id, kind);
        }
    }
    payload
}

/// 从 matched_links 构建 note_id → original_marker 映射。
///
/// ←→ Python `_build_marker_by_note_id_for_chapter()` (export.py:214)
pub fn build_marker_by_note_id_for_chapter(
    chapter_id: &str,
    matched_links: &[NoteLinkRecord],
) -> HashMap<String, String> {
    let mut payload: HashMap<String, String> = HashMap::new();
    for link in matched_links {
        if link.chapter_id != chapter_id {
            continue;
        }
        let note_id = link.note_item_id.trim().to_string();
        let marker = link.marker.trim().to_string();
        if note_id.is_empty() || marker.is_empty() {
            continue;
        }
        payload.entry(note_id).or_insert(marker);
    }
    payload
}
