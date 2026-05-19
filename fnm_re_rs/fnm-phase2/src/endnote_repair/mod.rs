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

/// 修复跨页 OCR split：当 region_id 相同但 page_no 跳跃且 next.marker 异常
/// （例如 OCR 把跨页续行误识别为新 marker）时，把 next 合并到 current。
/// ←→ 对齐 Python `_repair_parsed_row_sequence_markers` 跨页分支
pub fn repair_cross_page_continuation(items: &[NoteItemRecord]) -> Vec<NoteItemRecord> {
    if items.len() < 2 {
        return items.to_vec();
    }
    let mut result: Vec<NoteItemRecord> = Vec::new();
    let mut skip_next = false;
    for i in 0..items.len() {
        if skip_next {
            skip_next = false;
            continue;
        }
        let mut current = items[i].clone();
        if i + 1 < items.len() {
            let next = &items[i + 1];
            if current.region_id == next.region_id
                && next.page_no > current.page_no
                && next.page_no - current.page_no <= 2
            {
                let curr_marker = current.marker.parse::<i64>().ok();
                let next_marker = next.marker.parse::<i64>().ok();
                // 检测 OCR split 跨页续行：next.marker 与 curr 差距过大（≥ 20）
                // 且后面还有合理的下一 marker（curr+1）。
                let following = items.get(i + 2);
                let following_marker = following.and_then(|r| r.marker.parse::<i64>().ok());
                let drift_detected = match (curr_marker, next_marker, following_marker) {
                    (Some(c), Some(n), Some(f)) => {
                        // next 是异常跳变，但 following 接回 curr+1
                        (n - c).abs() >= 20 && f == c + 1
                    }
                    (Some(c), Some(n), None) => {
                        // 没有 following：仅当 next 异常大才合并
                        (n - c).abs() >= 20
                    }
                    _ => false,
                };
                if drift_detected {
                    current.text = format!("{} {}", current.text.trim(), next.text.trim());
                    current.is_reconstructed = true;
                    current.marker_type = "repaired_cross_page".into();
                    skip_next = true;
                }
            }
        }
        result.push(current);
    }
    result
}

/// 修复序列异常值 marker（drift 修复）。
/// ←→ Python `_fix_sequence_outlier_markers_in_place`
///
/// 当 (prev=N, curr=异常, next=N+2) 且 curr > next+20 时，把 curr 设为 N+1。
pub fn repair_sequence_outlier_markers(items: &[NoteItemRecord]) -> Vec<NoteItemRecord> {
    if items.len() < 3 {
        return items.to_vec();
    }
    let mut updated = items.to_vec();
    for i in 1..updated.len() - 1 {
        let prev = &updated[i - 1];
        let curr = &updated[i];
        let next = &updated[i + 1];
        if prev.region_id != curr.region_id || curr.region_id != next.region_id {
            continue;
        }
        if prev.chapter_id != curr.chapter_id || curr.chapter_id != next.chapter_id {
            continue;
        }
        let prev_m = match prev.marker.parse::<i64>() {
            Ok(v) => v,
            Err(_) => continue,
        };
        let curr_m = match curr.marker.parse::<i64>() {
            Ok(v) => v,
            Err(_) => continue,
        };
        let next_m = match next.marker.parse::<i64>() {
            Ok(v) => v,
            Err(_) => continue,
        };
        let expected = prev_m + 1;
        if next_m != prev_m + 2 {
            continue;
        }
        if curr_m == expected {
            continue;
        }
        if curr_m <= next_m + 20 {
            continue;
        }
        let mut fixed = curr.clone();
        fixed.marker = expected.to_string();
        fixed.is_reconstructed = true;
        fixed.marker_type = "repaired_sequence_outlier".into();
        updated[i] = fixed;
    }
    updated
}

/// 推断缺失 markers：检测 region 内单调递增序列中的洞，补合成 placeholder。
/// 仅当洞 ≤ 2 且 region.note_kind == endnote 时生效。
pub fn infer_missing_markers(items: &[NoteItemRecord]) -> Vec<NoteItemRecord> {
    if items.len() < 2 {
        return items.to_vec();
    }
    let mut result: Vec<NoteItemRecord> = Vec::new();
    for i in 0..items.len() {
        let curr = items[i].clone();
        if i + 1 < items.len() {
            let next = &items[i + 1];
            if curr.region_id == next.region_id
                && curr.note_kind == fnm_core::types::NoteKind::Endnote
            {
                if let (Ok(c), Ok(n)) = (curr.marker.parse::<i64>(), next.marker.parse::<i64>()) {
                    let gap = n - c;
                    if gap >= 2 && gap <= 3 {
                        result.push(curr.clone());
                        for k in 1..gap {
                            let mut placeholder = curr.clone();
                            placeholder.note_item_id =
                                format!("{}-inferred-{}", curr.note_item_id, k);
                            placeholder.marker = (c + k).to_string();
                            placeholder.text = String::new();
                            placeholder.is_reconstructed = true;
                            placeholder.marker_type = "repaired_inferred_missing".into();
                            placeholder.review_required = true;
                            result.push(placeholder);
                        }
                        continue;
                    }
                }
            }
        }
        result.push(curr);
    }
    result
}

/// 完整 endnote repair 流程：truncation → continuity → OCR split → cross-page → outlier → infer-missing。
pub fn repair_endnote_items(items: &[NoteItemRecord]) -> (Vec<NoteItemRecord>, serde_json::Value) {
    let step1 = repair_truncated_note_items(items);
    let step2 = repair_marker_continuity(&step1);
    let step3 = repair_ocr_split_endnote_defs(&step2);
    let step4 = repair_cross_page_continuation(&step3);
    let step5 = repair_sequence_outlier_markers(&step4);
    let step6 = infer_missing_markers(&step5);

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
    let cross_page_count = step4
        .iter()
        .filter(|r| r.marker_type == "repaired_cross_page")
        .count() as i64;
    let outlier_count = step5
        .iter()
        .filter(|r| r.marker_type == "repaired_sequence_outlier")
        .count() as i64;
    let inferred_count = step6
        .iter()
        .filter(|r| r.marker_type == "repaired_inferred_missing")
        .count() as i64;

    let stats = serde_json::json!({
        "original_count": items.len(),
        "repaired_count": step6.len(),
        "truncations_found": truncated_count,
        "continuity_fixes": continuity_fixes_count,
        "ocr_split_fixes": ocr_split_count,
        "cross_page_fixes": cross_page_count,
        "sequence_outlier_fixes": outlier_count,
        "inferred_missing": inferred_count,
    });
    (step6, stats)
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

    fn make_item_page(
        id: &str,
        region_id: &str,
        marker: &str,
        text: &str,
        page: i64,
    ) -> NoteItemRecord {
        let mut i = make_item(id, region_id, marker, text);
        i.page_no = page;
        i
    }

    #[test]
    fn cross_page_merges_drifted_marker() {
        let items = vec![
            make_item_page("ni-1", "r-1", "1", "first part", 10),
            make_item_page("ni-2", "r-1", "47", "continuation on next page", 11),
            make_item_page("ni-3", "r-1", "2", "second note", 11),
        ];
        let result = repair_cross_page_continuation(&items);
        // 47 应被合并到 1
        assert!(result
            .iter()
            .any(|i| i.marker_type == "repaired_cross_page"));
    }

    #[test]
    fn outlier_marker_fixed_when_neighbors_consecutive() {
        let items = vec![
            make_item("ni-1", "r-1", "5", "five"),
            make_item("ni-2", "r-1", "99", "six?"),
            make_item("ni-3", "r-1", "7", "seven"),
        ];
        let result = repair_sequence_outlier_markers(&items);
        assert_eq!(result[1].marker, "6");
        assert!(result[1].is_reconstructed);
    }

    #[test]
    fn infer_missing_adds_placeholder() {
        let items = vec![
            make_item("ni-1", "r-1", "1", "one"),
            make_item("ni-2", "r-1", "3", "three"),
        ];
        let result = infer_missing_markers(&items);
        assert_eq!(result.len(), 3);
        assert_eq!(result[1].marker, "2");
        assert_eq!(result[1].marker_type, "repaired_inferred_missing");
        assert!(result[1].review_required);
    }
}
