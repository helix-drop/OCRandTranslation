//! 五遍 sanitize 清理流水线。←→ Python `_sanitize_visual_toc_semantic_rows()`。

use super::title_utils::*;
use fnm_core::title::normalize_title;

/// 五遍 sanitize：composite_root_duplicates → split_heading_merge →
/// prefixed_duplicates → numeric_root_noise → back_matter_demote。
pub fn sanitize_visual_toc_semantic_rows(rows: &mut [TocRow]) {
    suppress_composite_root_duplicates(rows);
    merge_split_heading_rows(rows);
    suppress_prefixed_duplicates(rows);
    suppress_numeric_root_noise(rows);
    demote_rows_after_back_matter_start(rows);
}

/// Pass 1: 抑制复合根重复（parent_key 包含 title_key 时去重）。
fn suppress_composite_root_duplicates(rows: &mut [TocRow]) {
    // 收集 chapter rows 的索引
    let chapter_indices: Vec<usize> = rows
        .iter()
        .enumerate()
        .filter(|(_, r)| {
            r.role_hint == "chapter"
                && r.body_candidate != Some(false)
                && r.export_candidate != Some(false)
                && !r.parent_title.is_empty()
                && r.page_no > 0
        })
        .map(|(i, _)| i)
        .collect();

    for &i in &chapter_indices {
        let title_key = semantic_visual_toc_title_key(&rows[i].title, false);
        let parent_key = semantic_visual_toc_title_key(&rows[i].parent_title, false);
        if title_key.is_empty() || parent_key.is_empty() || !title_key.contains(&parent_key) {
            continue;
        }
        for &j in &chapter_indices {
            if i == j {
                continue;
            }
            if rows[j].page_no != rows[i].page_no {
                continue;
            }
            let sibling_parent_key = semantic_visual_toc_title_key(&rows[j].parent_title, false);
            if sibling_parent_key != parent_key {
                continue;
            }
            let sibling_key = semantic_visual_toc_title_key(&rows[j].title, false);
            if sibling_key.is_empty()
                || sibling_key == title_key
                || sibling_key.contains(&parent_key)
            {
                continue;
            }
            if title_key.contains(&sibling_key) {
                suppress_row(&mut rows[i], "section");
                break;
            }
        }
    }
}

/// Pass 2: 合并分裂标题行。
fn merge_split_heading_rows(rows: &mut [TocRow]) {
    let chapter_indices: Vec<usize> = rows
        .iter()
        .enumerate()
        .filter(|(_, r)| {
            r.role_hint == "chapter"
                && r.body_candidate != Some(false)
                && r.export_candidate != Some(false)
                && r.page_no > 0
                && has_leading_toc_number_prefix(&r.title)
        })
        .map(|(i, _)| i)
        .collect();

    for &i in &chapter_indices {
        let short_title = strip_leading_toc_number_prefix(&rows[i].title);
        let short_title = normalize_title(&short_title);
        if short_title.is_empty() {
            continue;
        }
        // 找同页、不同标题、以 short_title 开头的 sibling
        let sibling_indices: Vec<usize> = rows
            .iter()
            .enumerate()
            .filter(|(j, r)| {
                *j != i
                    && r.role_hint == "chapter"
                    && r.body_candidate != Some(false)
                    && r.export_candidate != Some(false)
                    && r.page_no == rows[i].page_no
                    && normalize_title(&r.title) != short_title
            })
            .map(|(j, _)| j)
            .collect();

        let matching_long: Vec<usize> = sibling_indices
            .iter()
            .filter(|&&j| {
                let normalized = normalize_title(&rows[j].title);
                normalized.starts_with(&format!("{} ", short_title))
            })
            .copied()
            .collect();

        if matching_long.is_empty() {
            continue;
        }
        rows[i].title = short_title;
        // suppress matching_long rows
        for &j in &matching_long {
            suppress_row(&mut rows[j], "section");
        }
    }
}

/// Pass 3: 抑制带数字前缀的重复。
fn suppress_prefixed_duplicates(rows: &mut [TocRow]) {
    // 按 canonical_key 分组
    let mut groups: std::collections::HashMap<String, Vec<usize>> =
        std::collections::HashMap::new();
    for (i, row) in rows.iter().enumerate() {
        if row.role_hint != "chapter" {
            continue;
        }
        if row.body_candidate == Some(false) || row.export_candidate == Some(false) {
            continue;
        }
        let canonical_key = semantic_visual_toc_title_key(&row.title, true);
        if canonical_key.len() < 6 {
            continue;
        }
        groups.entry(canonical_key).or_default().push(i);
    }

    for indices in groups.values() {
        let clean_indices: Vec<usize> = indices
            .iter()
            .filter(|&&i| !has_leading_toc_number_prefix(&rows[i].title))
            .copied()
            .collect();
        if clean_indices.is_empty() {
            continue;
        }
        for &i in indices {
            if clean_indices.contains(&i) {
                continue;
            }
            if !has_leading_toc_number_prefix(&rows[i].title) {
                continue;
            }
            // 检查是否有 nearby clean rows
            let nearby_clean: Vec<usize> = clean_indices
                .iter()
                .filter(|&&j| visual_toc_rows_are_nearby(rows[i].page_no, rows[j].page_no, 12))
                .copied()
                .collect();
            if nearby_clean.is_empty() {
                continue;
            }
            if prefixed_should_yield_to_clean(&rows[i]) {
                suppress_row(&mut rows[i], "section");
                continue;
            }
            // suppress nearby clean rows
            for &j in &nearby_clean {
                suppress_row(&mut rows[j], "section");
            }
        }
    }
}

/// Pass 4: 抑制纯数字根标题噪声。
fn suppress_numeric_root_noise(rows: &mut [TocRow]) {
    // 收集 child rows by parent
    let mut child_by_parent: std::collections::HashMap<String, Vec<usize>> =
        std::collections::HashMap::new();
    for (i, row) in rows.iter().enumerate() {
        if row.parent_title.is_empty() {
            continue;
        }
        let parent = normalize_title(&row.parent_title);
        if parent.is_empty() {
            continue;
        }
        child_by_parent.entry(parent).or_default().push(i);
    }

    // 找 root rows（无 parent 的 chapter）
    let root_indices: Vec<usize> = rows
        .iter()
        .enumerate()
        .filter(|(_, r)| {
            r.role_hint == "chapter"
                && r.body_candidate != Some(false)
                && r.export_candidate != Some(false)
                && r.parent_title.is_empty()
        })
        .map(|(i, _)| i)
        .collect();

    for &i in &root_indices {
        if !is_pure_number_toc_title(&rows[i].title) {
            continue;
        }
        let parent_key = normalize_title(&rows[i].title);
        let child_indices = child_by_parent
            .get(&parent_key)
            .cloned()
            .unwrap_or_default();
        let numeric_children: Vec<usize> = child_indices
            .iter()
            .filter(|&&j| {
                rows[j].body_candidate != Some(false) && is_pure_number_toc_title(&rows[j].title)
            })
            .copied()
            .collect();
        if numeric_children.len() < 2 || numeric_children.len() != child_indices.len() {
            continue;
        }
        // 检查附近是否有非纯数字的 root rows
        let nearby_semantic: Vec<usize> = root_indices
            .iter()
            .filter(|&&j| {
                j != i
                    && !is_pure_number_toc_title(&rows[j].title)
                    && visual_toc_rows_are_nearby(rows[i].page_no, rows[j].page_no, 12)
            })
            .copied()
            .collect();
        if !nearby_semantic.is_empty() {
            suppress_row(&mut rows[i], "section");
        }
    }
}

/// Pass 5: back_matter 之后的 chapter/section 降级。
fn demote_rows_after_back_matter_start(rows: &mut [TocRow]) {
    let back_matter_indices: Vec<usize> = rows
        .iter()
        .enumerate()
        .filter(|(_, r)| r.role_hint == "back_matter" && r.page_no > 0)
        .map(|(i, _)| i)
        .collect();

    if back_matter_indices.is_empty() {
        return;
    }
    let first_back_matter_page = back_matter_indices
        .iter()
        .map(|&i| rows[i].page_no)
        .min()
        .unwrap_or(0);

    let back_matter_title_keys: std::collections::HashSet<String> = back_matter_indices
        .iter()
        .map(|&i| semantic_visual_toc_title_key(&rows[i].title, false))
        .filter(|k| !k.is_empty())
        .collect();

    for row in rows.iter_mut() {
        if row.page_no < first_back_matter_page {
            continue;
        }
        if !matches!(row.role_hint.as_str(), "chapter" | "section") {
            continue;
        }
        let parent_key = semantic_visual_toc_title_key(&row.parent_title, false);
        if !parent_key.is_empty() && !back_matter_title_keys.contains(&parent_key) {
            continue;
        }
        suppress_row(row, "back_matter");
    }
}

fn suppress_row(row: &mut TocRow, role_hint: &str) {
    row.role_hint = role_hint.to_string();
    row.body_candidate = Some(false);
    row.export_candidate = Some(false);
}

fn prefixed_should_yield_to_clean(row: &TocRow) -> bool {
    let clean_title = normalize_title(&strip_leading_toc_number_prefix(&row.title));
    clean_title.is_empty() || is_toc_force_export_title(&clean_title)
}
