//! ←→ note_items.py: _fix_year_markers_in_place / _fix_sequence_outlier_markers_in_place
//! 年份误标过滤 + 序列异常值修正。

use fnm_core::records::NoteItemRecord;
use fnm_core::types::NoteKind;

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
/// 只处理同一 `(chapter_id, region_id, note_kind)` 分组内的相邻 item，
/// 不允许跨 region/chapter 边界做 prev/curr/next 推断。
///
/// - 若 marker 是年份（1500-2100）→ 一律删除，不插值。
///   年份不是有效 note marker，插值会引入幽灵 marker。
pub fn fix_year_markers_in_place_grouped(
    groups: Vec<(String, String, NoteKind, Vec<NoteItemRecord>)>,
) -> Vec<NoteItemRecord> {
    let mut result = Vec::new();
    for (_chapter_id, _region_id, _kind, records) in groups {
        result.extend(fix_year_markers_in_group(records));
    }
    result
}

/// 单分组内的年份修复——不允许跨 region/chapter/kind 边界。
fn fix_year_markers_in_group(records: Vec<NoteItemRecord>) -> Vec<NoteItemRecord> {
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

        let (Some(_prev), Some(curr), Some(_next)) = (prev_val, curr_val, next_val) else {
            continue;
        };

        // 不在年份范围内则跳过
        if !(1500..=2100).contains(&curr) {
            continue;
        }

        // 年份一律删除，不插值
        to_remove.push(i);
    }

    // 倒序移除以免移位
    to_remove.sort_unstable();
    to_remove.dedup();
    for &idx in to_remove.iter().rev() {
        updated.remove(idx);
    }

    updated
}

/// 旧 API 包装器——内部按 `(chapter_id, region_id, note_kind)` 分组后调用 grouped 版本。
/// 保留此函数供现有调用者使用，确保边界安全。
pub fn fix_year_markers_in_place(records: Vec<NoteItemRecord>) -> Vec<NoteItemRecord> {
    if records.len() < 3 {
        return records;
    }
    // 自动分组
    let mut groups: std::collections::HashMap<(String, String, NoteKind), Vec<NoteItemRecord>> =
        std::collections::HashMap::new();
    for r in records {
        let key = (r.chapter_id.clone(), r.region_id.clone(), r.note_kind);
        groups.entry(key).or_default().push(r);
    }
    let grouped: Vec<_> = groups
        .into_iter()
        .map(|((chapter_id, region_id, kind), items)| (chapter_id, region_id, kind, items))
        .collect();
    fix_year_markers_in_place_grouped(grouped)
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
            projection_mode: None,
            owner_chapter_id: None,
            source_marker: None,
            normalized_marker: None,
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
    fn remove_year_even_with_gap() {
        // 3, 1976, 5 → 年份一律删除，不插值
        let items = vec![
            make_item("3", "r1", "c1"),
            make_item("1976", "r1", "c1"),
            make_item("5", "r1", "c1"),
        ];
        let result = fix_year_markers_in_place(items);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].marker, "3");
        assert_eq!(result[1].marker, "5");
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
    fn cross_region_boundary_no_remove() {
        // region A 末尾 33, region B 开头 1944, 35 不得跨 region 删除
        let items = vec![
            make_item("33", "r1", "c1"),
            make_item("1944", "r2", "c1"),
            make_item("35", "r2", "c1"),
        ];
        let result = fix_year_markers_in_place(items);
        // 1944 在 r2 内，prev=33 在 r1。分组后 r1: [33], r2: [1944, 35]
        // r1 长度 < 3 不处理，r2 长度 < 3 不处理 → 1944 保留
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn cross_chapter_boundary_no_remove() {
        // ch-A 末尾 33, ch-B 开头 1944, 35 不得跨章
        let items = vec![
            make_item("33", "r1", "ch-A"),
            make_item("1944", "r1", "ch-B"),
            make_item("35", "r1", "ch-B"),
        ];
        let result = fix_year_markers_in_place(items);
        // 分组后 ch-A: [33], ch-B: [1944, 35] → 都不足 3
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn endnote_region_year_between_normals_removed() {
        // endnote 内 33, 1944, 35 → 1944 移除
        let items = vec![
            make_item("33", "r1", "c1"),
            make_item("1944", "r1", "c1"),
            make_item("35", "r1", "c1"),
        ];
        let result = fix_year_markers_in_place(items);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].marker, "33");
        assert_eq!(result[1].marker, "35");
    }

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
