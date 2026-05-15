//! ←→ FNM_RE/modules/endnote_repair.py
//! Endnote 续行修复：检测截断的 endnote，合并后续行。

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
            skip_next = true;
        }

        result.push(merged);
    }

    result
}

/// 完整 endnote repair 流程。
pub fn repair_endnote_items(items: &[NoteItemRecord]) -> (Vec<NoteItemRecord>, serde_json::Value) {
    let repaired = repair_truncated_note_items(items);
    let stats = serde_json::json!({
        "original_count": items.len(),
        "repaired_count": repaired.len(),
        "truncations_found": items.len() - repaired.len(),
    });
    (repaired, stats)
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::NoteKind;

    #[test]
    fn detect_truncation() {
        assert!(looks_like_truncated_note("Some text, vol."));
        assert!(looks_like_truncated_note("Reference, cf."));
        assert!(!looks_like_truncated_note("Complete sentence."));
    }

    #[test]
    fn repair_merged() {
        let items = vec![
            NoteItemRecord {
                note_item_id: "ni-1".into(),
                region_id: "r-1".into(),
                chapter_id: "ch-1".into(),
                page_no: 1,
                marker: "1".into(),
                marker_type: "num".into(),
                text: "See vol.".into(),
                source: "scan".into(),
                source_page_label: "1".into(),
                is_reconstructed: false,
                review_required: false,
                note_kind: NoteKind::Endnote,
            },
            NoteItemRecord {
                note_item_id: "ni-2".into(),
                region_id: "r-1".into(),
                chapter_id: "ch-1".into(),
                page_no: 1,
                marker: "".into(),
                marker_type: "".into(),
                text: "III, p. 45.".into(),
                source: "scan".into(),
                source_page_label: "1".into(),
                is_reconstructed: false,
                review_required: false,
                note_kind: NoteKind::Endnote,
            },
        ];
        let (repaired, _stats) = repair_endnote_items(&items);
        assert_eq!(repaired.len(), 1);
        assert!(repaired[0].text.contains("vol."));
        assert!(repaired[0].text.contains("III"));
        assert!(repaired[0].is_reconstructed);
    }
}
