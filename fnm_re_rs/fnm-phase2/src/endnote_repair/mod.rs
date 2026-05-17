//! ←→ FNM_RE/modules/endnote_repair.py
//! Endnote 续行修复：检测截断的 endnote，合并后续行 + marker 连续性修复 + OCR split。

use fnm_core::records::NoteItemRecord;
use once_cell::sync::Lazy;
use regex::Regex;

static PAGE_CITATION_PREFIX_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)(?:pp?\b|f(?:o|°)?\b|esp\b|paras?\b|fols?\b|cols?\b|vol\b|n[°o]\b|nos?\b|nr\b|art\b|chap\b|sect\b|§\b|t\b|tome\b|liv\b|bk\b|book\b|ch\b|cf\b|voir\b|see\b|infra\b|supra\b|ibid\b|op\b|loc\b|id\b|éd\b|ed\b|eds\b|dir\b|trad\b|tr\b)\.$"
    ).unwrap()
});

/// 检测 note text 是否被截断（以引文缩写结尾）。
pub fn looks_like_truncated_note(text: &str) -> bool {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return false;
    }
    PAGE_CITATION_PREFIX_RE.is_match(trimmed)
}

/// 合并截断的相邻 note items（同一 region 内的连续 items）。
/// 扩展：同一 region 内连续 marker 的 items 也会被检查连续性。
pub fn repair_truncated_note_items(items: &[NoteItemRecord]) -> Vec<NoteItemRecord> {
    let mut result: Vec<NoteItemRecord> = Vec::new();
    let mut skip_next = false;

    for (i, item) in items.iter().enumerate() {
        if skip_next {
            skip_next = false;
            continue;
        }

        let mut merged = item.clone();

        if i + 1 < items.len()
            && item.region_id == items[i + 1].region_id
            && looks_like_truncated_note(&item.text)
        {
            merged.text = format!("{} {}", item.text.trim(), items[i + 1].text.trim());
            merged.is_reconstructed = true;
            merged.marker_type = "repaired_truncation".into();
            skip_next = true;
        }

        result.push(merged);
    }

    result
}

/// 修复 endnote marker 连续性：缺失间隔的 marker 用前一 marker 推断后补全。
/// ←→ Python `_repair_endnote_marker_continuity`
pub fn repair_marker_continuity(items: &[NoteItemRecord]) -> Vec<NoteItemRecord> {
    let mut result: Vec<NoteItemRecord> = Vec::new();

    for (i, item) in items.iter().enumerate() {
        let mut repaired = item.clone();

        // 检查当前 item 的 marker 是否可从前一 item 推断
        if i > 0
            && item.marker.is_empty()
            && !items[i - 1].marker.is_empty()
            && items[i - 1].region_id == item.region_id
        {
            if let Ok(prev_num) = items[i - 1].marker.parse::<i64>() {
                let inferred = (prev_num + 1).to_string();
                repaired.marker = inferred;
                repaired.is_reconstructed = true;
                repaired.marker_type = "repaired_marker_continuity".into();
            }
        }

        result.push(repaired);
    }

    result
}

/// 检测 OCR 分拆的 endnote definition（同一 marker 出现两次，第二次无正文 body）。
/// ←→ Python `_repair_ocr_split_endnote_def`
pub fn repair_ocr_split_endnote_defs(items: &[NoteItemRecord]) -> Vec<NoteItemRecord> {
    let mut result: Vec<NoteItemRecord> = Vec::new();
    let mut i = 0;

    while i < items.len() {
        // 检查当前 item 和下一 item 是否同一 marker 且 text 很短（OCR 分拆）
        if i + 1 < items.len()
            && items[i].region_id == items[i + 1].region_id
            && items[i].marker == items[i + 1].marker
            && !items[i].marker.is_empty()
        {
            let mut merged = items[i].clone();
            merged.text = format!("{} {}", items[i].text.trim(), items[i + 1].text.trim());
            merged.is_reconstructed = true;
            merged.marker_type = "repaired_ocr_split".into();
            result.push(merged);
            i += 2;
            continue;
        }

        result.push(items[i].clone());
        i += 1;
    }

    result
}

/// 完整 endnote repair 流程：truncation → continuity → OCR split。
pub fn repair_endnote_items(items: &[NoteItemRecord]) -> (Vec<NoteItemRecord>, serde_json::Value) {
    let step1 = repair_truncated_note_items(items);
    let step2 = repair_marker_continuity(&step1);
    let step3 = repair_ocr_split_endnote_defs(&step2);

    let truncated_count = step1
        .iter()
        .filter(|r| r.marker_type == "repaired_truncation")
        .count() as i64;
    let continuity_fixes_count = step2
        .iter()
        .filter(|r| r.marker_type == "repaired_marker_continuity")
        .count() as i64;
    let ocr_split_count = step3
        .iter()
        .filter(|r| r.marker_type == "repaired_ocr_split")
        .count() as i64;

    let stats = serde_json::json!({
        "original_count": items.len(),
        "repaired_count": step3.len(),
        "truncations_found": truncated_count.abs(),
        "continuity_fixes": continuity_fixes_count,
        "ocr_split_fixes": ocr_split_count,
    });
    (step3, stats)
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::NoteKind;

    fn make_item(id: &str, region_id: &str, marker: &str, text: &str) -> NoteItemRecord {
        NoteItemRecord {
            note_item_id: id.into(),
            region_id: region_id.into(),
            chapter_id: "ch-1".into(),
            page_no: 1,
            marker: marker.into(),
            marker_type: "num".into(),
            text: text.into(),
            source: "scan".into(),
            source_page_label: "1".into(),
            is_reconstructed: false,
            review_required: false,
            note_kind: NoteKind::Endnote,
            projection_mode: None,
            owner_chapter_id: None,
            source_marker: None,
            normalized_marker: None,
        }
    }

    #[test]
    fn detect_truncation() {
        assert!(looks_like_truncated_note("Some text, vol."));
        assert!(looks_like_truncated_note("Reference, cf."));
        assert!(!looks_like_truncated_note("Complete sentence."));
    }

    #[test]
    fn repair_merged() {
        let items = vec![
            make_item("ni-1", "r-1", "1", "See vol."),
            make_item("ni-2", "r-1", "", "III, p. 45."),
        ];
        let (repaired, _stats) = repair_endnote_items(&items);
        assert_eq!(repaired.len(), 1);
        assert!(repaired[0].text.contains("vol."));
        assert!(repaired[0].text.contains("III"));
        assert!(repaired[0].is_reconstructed);
    }

    #[test]
    fn marker_continuity_fix() {
        let items = vec![
            make_item("ni-1", "r-1", "1", "First note."),
            make_item("ni-2", "r-1", "", "Second note without marker."),
            make_item("ni-3", "r-1", "3", "Third note."),
        ];
        let repaired = repair_marker_continuity(&items);
        assert_eq!(repaired.len(), 3);
        assert_eq!(repaired[1].marker, "2");
        assert!(repaired[1].is_reconstructed);
    }

    #[test]
    fn ocr_split_repair() {
        let items = vec![
            make_item("ni-1", "r-1", "1", "First part"),
            make_item("ni-2", "r-1", "1", "continuation."),
            make_item("ni-3", "r-1", "2", "Second note."),
        ];
        let repaired = repair_ocr_split_endnote_defs(&items);
        assert_eq!(repaired.len(), 2);
        assert!(repaired[0].text.contains("First part"));
        assert!(repaired[0].text.contains("continuation"));
        assert!(repaired[0].is_reconstructed);
    }

    #[test]
    fn full_pipeline() {
        let items = vec![
            make_item("ni-1", "r-1", "1", "Long note text, vol."),
            make_item("ni-2", "r-1", "", "II, p. 45."),
            make_item("ni-3", "r-1", "2", "Second note."),
        ];
        let (repaired, stats) = repair_endnote_items(&items);
        assert!(repaired.len() >= 2);
        assert!(stats["truncations_found"].as_i64().unwrap_or(0) > 0);
    }
}
