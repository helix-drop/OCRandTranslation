//! ←→ FNM_RE/stages/export.py `_chapter_page_numbers()`

/// 提取章的实际页码列表。
///
/// ←→ Python `_chapter_page_numbers()` (export.py:345)
pub fn chapter_page_numbers(pages: &[i64], start_page: i64, end_page: i64) -> Vec<i64> {
    let filtered: Vec<i64> = pages.iter().copied().filter(|p| *p > 0).collect();
    if !filtered.is_empty() {
        let mut sorted = filtered;
        sorted.sort();
        sorted.dedup();
        return sorted;
    }
    let s = start_page.max(0);
    let e = end_page.max(s);
    if s > 0 && e >= s {
        (s..=e).collect()
    } else {
        vec![]
    }
}
