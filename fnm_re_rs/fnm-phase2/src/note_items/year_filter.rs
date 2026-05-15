//! ←→ note_items.py: _fix_year_markers_in_place / _fix_sequence_outlier_markers_in_place
//! 年份误标过滤 + 序列异常值修正。

use fnm_core::records::NoteItemRecord;

fn try_parse_int(s: &str) -> Option<i64> {
    let trimmed = s.trim();
    if trimmed.is_empty() {
        return None;
    }
    trimmed.parse::<i64>().ok()
}

/// 修正 OCR 将出版年份误作尾注 marker 的情况。
/// ←→ Python `_fix_year_markers_in_place`
///
/// - 若 marker 是年份（1500-2100）且夹在连续数字之间 → 删除该条目
/// - 若 marker 是年份且前后差一位 → 将年份替换为插值数字
pub fn fix_year_markers_in_place(records: Vec<NoteItemRecord>) -> Vec<NoteItemRecord> {
    if records.len() < 3 {
        return records;
    }

    let mut to_remove: Vec<usize> = Vec::new();
    let mut updated = records;

    let len = updated.len();
    for i in 1..len - 1 {
        let prev_val = try_parse_int(&updated[i - 1].marker);
        let curr_val = try_parse_int(&updated[i].marker);
        let next_val = try_parse_int(&updated[i + 1].marker);

        let (Some(prev), Some(curr), Some(next)) = (prev_val, curr_val, next_val) else {
            continue;
        };

        // 不在年份范围内则跳过
        if !(1500..=2100).contains(&curr) {
            continue;
        }

        if prev + 1 == next {
            // 年份夹在连续数字之间 → 幽灵条目，删除
            to_remove.push(i);
        } else if prev + 2 == next {
            // 年份占据了一个数字位 → 插值替换
            let corrected = (prev + 1).to_string();
            updated[i].marker = corrected;
        }
    }

    // 倒序移除以免移位
    to_remove.sort_unstable();
    to_remove.dedup();
    for &idx in to_remove.iter().rev() {
        updated.remove(idx);
    }

    updated
}

/// 修正序列异常值 marker（远大于预期值且同 region 内前后连续）。
/// ←→ Python `_fix_sequence_outlier_markers_in_place`
pub fn fix_sequence_outlier_markers_in_place(records: Vec<NoteItemRecord>) -> Vec<NoteItemRecord> {
    if records.len() < 3 {
        return records;
    }

    let len = records.len();
    let mut updated = records;

    for i in 1..len - 1 {
        // 检查 region_id 连续性
        if updated[i - 1].region_id != updated[i].region_id {
            continue;
        }
        if updated[i].region_id != updated[i + 1].region_id {
            continue;
        }

        // 检查 chapter_id 连续性
        if updated[i - 1].chapter_id != updated[i].chapter_id {
            continue;
        }
        if updated[i].chapter_id != updated[i + 1].chapter_id {
            continue;
        }

        let prev_val = try_parse_int(&updated[i - 1].marker);
        let curr_val = try_parse_int(&updated[i].marker);
        let next_val = try_parse_int(&updated[i + 1].marker);

        let (Some(prev), Some(curr), Some(next)) = (prev_val, curr_val, next_val) else {
            continue;
        };

        let expected = prev + 1;

        // 前后连续（prev+2 == next）但当前值不是预期值
        if next != prev + 2 {
            continue;
        }
        if curr == expected {
            continue;
        }
        // 只修真正的大离群值
        if curr <= next + 20 {
            continue;
        }

        updated[i].marker = expected.to_string();
    }

    updated
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::NoteKind;

    fn make_item(marker: &str, region_id: &str, chapter_id: &str) -> NoteItemRecord {
        NoteItemRecord {
            note_item_id: String::new(),
            region_id: region_id.into(),
            chapter_id: chapter_id.into(),
            page_no: 1,
            marker: marker.into(),
            marker_type: "num".into(),
            text: "test".into(),
            source: "markdown".into(),
            source_page_label: "p1".into(),
            is_reconstructed: false,
            review_required: false,
            note_kind: NoteKind::Endnote,
        }
    }

    // ── year filter ──

    #[test]
    fn short_list_unchanged() {
        let items = vec![make_item("1", "r1", "c1"), make_item("2", "r1", "c1")];
        assert_eq!(fix_year_markers_in_place(items).len(), 2);
    }

    #[test]
    fn remove_year_between_continuous() {
        // 3, 1976, 4 → 删除 1976
        let items = vec![
            make_item("3", "r1", "c1"),
            make_item("1976", "r1", "c1"),
            make_item("4", "r1", "c1"),
        ];
        let result = fix_year_markers_in_place(items);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].marker, "3");
        assert_eq!(result[1].marker, "4");
    }

    #[test]
    fn interpolate_year_with_gap() {
        // 3, 1976, 5 → prev+2 == 5 → 插值 4
        let items = vec![
            make_item("3", "r1", "c1"),
            make_item("1976", "r1", "c1"),
            make_item("5", "r1", "c1"),
        ];
        let result = fix_year_markers_in_place(items);
        assert_eq!(result.len(), 3);
        assert_eq!(result[1].marker, "4");
    }

    #[test]
    fn non_year_marker_unchanged() {
        let items = vec![
            make_item("1", "r1", "c1"),
            make_item("42", "r1", "c1"),
            make_item("2", "r1", "c1"),
        ];
        // 42 不在年份范围内，不处理
        // 但符合 ghost 条件: next(2)=prev(1)+1, curr!=next, curr>next+20? 42>22, yes.
        // 等等，42 不在 1500-2100 范围 → skip. 但移除逻辑只针对年份。
        // 所以 42 保留.
        let result = fix_year_markers_in_place(items);
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn non_numeric_skipped() {
        let items = vec![
            make_item("1", "r1", "c1"),
            make_item("Note", "r1", "c1"),
            make_item("2", "r1", "c1"),
        ];
        let result = fix_year_markers_in_place(items);
        assert_eq!(result.len(), 3);
    }

    // ── outlier filter ──

    #[test]
    fn outlier_fix() {
        // 1, 999, 3 → same region/chapter, prev+2=3, curr(999) > next+20=23 → fix to 2
        let items = vec![
            make_item("1", "r1", "c1"),
            make_item("999", "r1", "c1"),
            make_item("3", "r1", "c1"),
        ];
        let result = fix_sequence_outlier_markers_in_place(items);
        assert_eq!(result[1].marker, "2");
    }

    #[test]
    fn outlier_different_region_unchanged() {
        let items = vec![
            make_item("1", "r1", "c1"),
            make_item("999", "r2", "c1"),
            make_item("3", "r1", "c1"),
        ];
        let result = fix_sequence_outlier_markers_in_place(items);
        assert_eq!(result[1].marker, "999");
    }

    #[test]
    fn outlier_small_value_unchanged() {
        // 1, 5, 3 → prev+2=3, curr(5) ≤ next+20=23 → skip
        let items = vec![
            make_item("1", "r1", "c1"),
            make_item("5", "r1", "c1"),
            make_item("3", "r1", "c1"),
        ];
        let result = fix_sequence_outlier_markers_in_place(items);
        assert_eq!(result[1].marker, "5");
    }

    #[test]
    fn outlier_short_list_unchanged() {
        let items = vec![make_item("999", "r1", "c1"), make_item("2", "r1", "c1")];
        assert_eq!(fix_sequence_outlier_markers_in_place(items).len(), 2);
    }
}
