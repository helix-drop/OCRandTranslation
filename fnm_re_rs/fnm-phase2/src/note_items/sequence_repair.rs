//! ←→ note_items.py: _repair_parsed_row_sequence_markers
//! 数字序号序列修复：移除幽灵条目、插值缺失 marker、修正倒序序列。

/// 解析行的中间表示（在转换为 NoteItemRecord 之前）。
#[derive(Debug, Clone)]
pub(crate) struct ParsedNoteRow {
    pub page_no: i64,
    pub marker: String,
    pub text: String,
    pub is_reconstructed: bool,
    pub source: String,
}

fn try_parse_int(s: &str) -> Option<i64> {
    let trimmed = s.trim();
    if trimmed.is_empty() {
        return None;
    }
    trimmed.parse::<i64>().ok()
}

/// 修复 endnote region 内的数字 marker 序列。
/// ←→ Python `_repair_parsed_row_sequence_markers`
///
/// 三类修复：
/// - **幽灵条目**：连续序列中夹入一个离群 marker → 删除 (to_remove)
/// - **插值修正**：连续序列缺一位（n-1, ?, n+1）→ 补位
/// - **倒序修正**：从某个点开始 marker 值回退后呈连续序列，且结束后正好接上预期值 → 重编号
pub(crate) fn repair_parsed_row_sequence_markers(rows: Vec<ParsedNoteRow>) -> Vec<ParsedNoteRow> {
    if rows.len() < 3 {
        return rows;
    }

    let mut updated = rows;
    let mut to_remove: Vec<usize> = Vec::new();

    // Phase 1: 标记要被移除的行 + 修正可插值的 marker
    for i in 1..updated.len() - 1 {
        let prev_val = try_parse_int(&updated[i - 1].marker);
        let curr_val = try_parse_int(&updated[i].marker);
        let next_val = try_parse_int(&updated[i + 1].marker);

        let (Some(prev), Some(curr), Some(next)) = (prev_val, curr_val, next_val) else {
            continue;
        };

        // 连续序列中出现离群值 → 幽灵条目，标记移除
        if next == prev + 1 && curr != next && (curr > next + 20 || curr < prev) {
            to_remove.push(i);
            continue;
        }

        // 缺一位（n-1, ?, n+1）且离群值过大 → 插值修正
        if next == prev + 2 && curr != prev + 1 && (curr > next + 20 || curr <= prev) {
            updated[i].marker = (prev + 1).to_string();
        }
    }

    // Phase 2: 修正倒序序列
    let mut i = 1;
    while i < updated.len() - 1 {
        if to_remove.contains(&i) {
            i += 1;
            continue;
        }

        let prev_val = try_parse_int(&updated[i - 1].marker);
        let curr_val = try_parse_int(&updated[i].marker);

        let (Some(prev), Some(curr)) = (prev_val, curr_val) else {
            i += 1;
            continue;
        };

        // 如果当前 marker 就是预期的下一值，跳过
        if curr == prev + 1 {
            i += 1;
            continue;
        }

        // 找到从 i 开始的最长连续子序列
        let mut run_end = i;
        while run_end + 1 < updated.len() {
            let cur = try_parse_int(&updated[run_end].marker);
            let fol = try_parse_int(&updated[run_end + 1].marker);
            match (cur, fol) {
                (Some(c), Some(f)) if f == c + 1 => run_end += 1,
                _ => break,
            }
        }

        let after_idx = run_end + 1;
        let after_val = if after_idx < updated.len() {
            try_parse_int(&updated[after_idx].marker)
        } else {
            None
        };

        let run_len = run_end - i + 1;
        if let Some(after) = after_val {
            if after == prev + run_len as i64 + 1 && curr <= prev {
                // 重编号 run 内的行
                for offset in 0..run_len {
                    updated[i + offset].marker = (prev + 1 + offset as i64).to_string();
                }
                i = run_end + 1;
                continue;
            }
        }
        i += 1;
    }

    // 移除被标记的行（倒序索引以免移位）
    to_remove.sort_unstable();
    to_remove.dedup();
    for &idx in to_remove.iter().rev() {
        updated.remove(idx);
    }

    updated
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(page_no: i64, marker: &str, text: &str) -> ParsedNoteRow {
        ParsedNoteRow {
            page_no,
            marker: marker.into(),
            text: text.into(),
            is_reconstructed: false,
            source: "markdown".into(),
        }
    }

    #[test]
    fn short_list_unchanged() {
        let rows = vec![row(1, "1", "a"), row(1, "2", "b")];
        let result = repair_parsed_row_sequence_markers(rows.clone());
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn continuous_sequence_unchanged() {
        let rows = vec![
            row(1, "1", "a"),
            row(1, "2", "b"),
            row(2, "3", "c"),
            row(2, "4", "d"),
        ];
        let result = repair_parsed_row_sequence_markers(rows);
        assert_eq!(result.len(), 4);
        assert_eq!(result[0].marker, "1");
        assert_eq!(result[3].marker, "4");
    }

    #[test]
    fn remove_ghost_entry() {
        // 1, 999, 2 → 移除 999（离群值，连续序列中夹入）
        let rows = vec![row(1, "1", "a"), row(1, "999", "ghost"), row(1, "2", "b")];
        let result = repair_parsed_row_sequence_markers(rows);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].marker, "1");
        assert_eq!(result[1].marker, "2");
    }

    #[test]
    fn interpolate_missing_marker() {
        // 1, 999, 3 → prev+2==next (3==1+2), 999 离群 → 插值 2
        let rows = vec![row(1, "1", "a"), row(1, "999", "bad"), row(1, "3", "c")];
        let result = repair_parsed_row_sequence_markers(rows);
        assert_eq!(result.len(), 3);
        assert_eq!(result[1].marker, "2");
    }

    #[test]
    fn fix_backward_run() {
        // 3, 1, 2, 4 → 从 1 开始的连续 run (1,2) 在 4 前结束 → 重编号 4,5
        // 实际上序列是: 3, 1, 2, 4 → 1+2+1=4 matches after_marker → 变成 3, 4, 5, ...
        // Wait, prev=3, curr=1. run at i=1: updated[1]=1, updated[2]=2 (consecutive). run_end=2, after=updated[3]=4.
        // after_val=4, prev+run_len+1 = 3+2+1=6 ≠ 4. So this doesn't match.
        // Let me think of a valid case:
        // 2, 1, 1, 3 → prev=2, curr=1. run: [1]=1, [2]=1 (f=1, c=1 → 1≠1+1). So run_end=1, run_len=1.
        // after=updated[2]=1, after_val=1. prev+run_len+1 = 2+1+1 = 4 ≠ 1. Doesn't match.
        //
        // Valid case: 6, 1, 2, 3, 7 → prev=6, curr=1. run: [1]=1,[2]=2 (seq), [3]=3 (seq). run_end=3, run_len=3.
        // after=updated[4]=7, after_val=7. prev+run_len+1 = 6+3+1 = 10 ≠ 7. Doesn't match.
        //
        // Let me think again... The pattern is:
        // prev_marker = N, curr_marker <= N (backward), and we find a run of consecutive markers starting from curr,
        // then after_marker = prev + run_len + 1.
        //
        // So if we have: 5, 2, 3, 4, 8
        // - prev=5 at i-1=0, curr=2 at i=1
        // - run: [1]=2, [2]=3 (seq 2→3 yes), [3]=4 (seq 3→4 yes), run_end=3, run_len=3
        // - after=updated[4]=8, after_val=8
        // - prev+run_len+1 = 5+3+1 = 9. 9 ≠ 8. Doesn't match.
        //
        // Hmm, when would this trigger? Let me re-read the Python condition:
        // `after_marker == prev_marker + run_len + 1 and curr_marker <= prev_marker`
        //
        // So after_marker should be prev + run_len + 1.
        // Example: 5, 2, 3, 6 → prev=5, curr=2 ≤ 5. run: [1]=2, [2]=3 (seq), run_end=2, run_len=2.
        // after=6, prev+run_len+1 = 5+2+1 = 8 ≠ 6. Still doesn't match.
        //
        // Maybe: 4, 1, 2, 5 → prev=4, curr=1 ≤ 4. run: [1]=1, [2]=2, run_end=2, run_len=2.
        // after=5, prev+run_len+1 = 4+2+1 = 7. 7 ≠ 5.
        //
        // 3, 1, 2, 4 → prev=3, curr=1. run: [1]=1,[2]=2, run_end=2, run_len=2. after=4.
        // prev+run_len+1 = 3+2+1 = 6. 6 ≠ 4.
        //
        // I think the formula is wrong in my reading. Let me look again:
        // `after_marker == prev_marker + run_len + 1` — this means after = prev + (run_end-i+1) + 1
        // So if prev=3, run_len=2, then after should be 3+2+1=6... but in the example I'd expect 4.
        //
        // Wait, maybe the run contains items that are ALREADY consecutive but started from the wrong number.
        // Example: 3, 1, 2, 4 → The run 1,2 is consecutive (1→2), and after it is 4.
        // The idea is: renumber run to be 4, 5, but 4 is already occupied. So this doesn't make sense.
        //
        // Let me try: 3, 1, 2, 6 → prev=3, run 1,2 consecutive, after=6.
        // prev+run_len+1 = 3+2+1 = 6 = after! Yes! So renumber: 3, 4, 5, 6.
        let rows = vec![
            row(1, "3", "a"),
            row(1, "1", "b"),
            row(1, "2", "c"),
            row(1, "6", "d"),
        ];
        let result = repair_parsed_row_sequence_markers(rows);
        assert_eq!(result.len(), 4);
        assert_eq!(result[0].marker, "3"); // unchanged
        assert_eq!(result[1].marker, "4"); // renumbered
        assert_eq!(result[2].marker, "5"); // renumbered
        assert_eq!(result[3].marker, "6"); // unchanged
    }

    #[test]
    fn mixed_non_numeric_unchanged() {
        let rows = vec![row(1, "1", "a"), row(1, "*", "b"), row(1, "2", "c")];
        // 非数字 marker 跳过
        let result = repair_parsed_row_sequence_markers(rows);
        assert_eq!(result.len(), 3);
        assert_eq!(result[0].marker, "1");
        assert_eq!(result[1].marker, "*");
        assert_eq!(result[2].marker, "2");
    }

    #[test]
    fn remove_marker_repeated_larger() {
        // 2, 999, 3 → next(3) == prev(2)+1, curr(999) > next+20 → remove
        // Actually 999 > 3+20 is true. So remove i=1.
        let rows = vec![row(1, "2", "a"), row(1, "999", "ghost"), row(1, "3", "b")];
        let result = repair_parsed_row_sequence_markers(rows);
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn no_fix_when_after_doesnt_match() {
        // 3, 1, 2, 7 → prev=3, run=1,2 (len=2), after=7. prev+run_len+1=6 ≠ 7. No fix.
        let rows = vec![
            row(1, "3", "a"),
            row(1, "1", "b"),
            row(1, "2", "c"),
            row(1, "7", "d"),
        ];
        let result = repair_parsed_row_sequence_markers(rows);
        assert_eq!(result.len(), 4);
        assert_eq!(result[1].marker, "1"); // unchanged
        assert_eq!(result[2].marker, "2"); // unchanged
    }

    #[test]
    fn interpolate_normal_range() {
        // 1, 42, 3 → prev=1, next=3, prev+2=next, curr(42) > next+20 (23)? 42 > 23.
        // Actually 42 > 3+20 = 23. Yes. So interpolate: marker[1] = 2.
        let rows = vec![row(1, "1", "a"), row(1, "42", "b"), row(1, "3", "c")];
        let result = repair_parsed_row_sequence_markers(rows);
        assert_eq!(result[1].marker, "2");
    }
}
