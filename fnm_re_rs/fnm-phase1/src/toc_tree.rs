//! ←→ FNM_RE/modules/toc_structure.py `_build_toc_tree` + `_map_toc_role`
//! 从 TOC items + chapter rows + meta 构建 TOC 树节点列表。

use crate::input::TocItem;
use fnm_core::records::{ChapterRecord, TocNode};
use fnm_core::title::{chapter_title_match_key, normalize_title};
use std::collections::HashSet;

fn normalize_toc_node_role(value: &str) -> String {
    let role = value.trim().to_lowercase().replace('-', "_");
    if matches!(
        role.as_str(),
        "container"
            | "endnotes"
            | "chapter"
            | "section"
            | "post_body"
            | "back_matter"
            | "front_matter"
    ) {
        return role;
    }
    if role == "part" {
        return "container".into();
    }
    if role == "notes" {
        return "endnotes".into();
    }
    if role == "book_title" {
        return "front_matter".into();
    }
    if role == "content" {
        return "content".into();
    }
    String::new()
}

struct TocRoleKeySets<'a> {
    container_keys: &'a HashSet<String>,
    endnotes_keys: &'a HashSet<String>,
    post_body_keys: &'a HashSet<String>,
    back_matter_keys: &'a HashSet<String>,
    chapter_keys: &'a HashSet<String>,
}

fn map_toc_role(
    title: &str,
    explicit_role: &str,
    title_key: &str,
    keys: &TocRoleKeySets,
    is_likely_chapter: bool,
) -> String {
    let normalized = normalize_toc_node_role(explicit_role);
    if !normalized.is_empty() && normalized != "content" {
        return normalized;
    }
    if title_key.is_empty() {
        return "section".into();
    }
    if keys.container_keys.contains(title_key) {
        return "container".into();
    }
    if keys.endnotes_keys.contains(title_key) {
        return "endnotes".into();
    }
    if keys.post_body_keys.contains(title_key) {
        return "post_body".into();
    }
    if keys.back_matter_keys.contains(title_key) {
        return "back_matter".into();
    }
    if keys.chapter_keys.contains(title_key) {
        return if is_likely_chapter {
            "chapter"
        } else {
            "section"
        }
        .into();
    }
    let nl = normalize_title(title).to_lowercase();
    if nl.contains("endnote") || nl == "notes" || nl.starts_with("notes ") {
        return "endnotes".into();
    }
    if ["bibliograph", "index", "appendix", "references"]
        .iter()
        .any(|t| nl.contains(t))
    {
        return "back_matter".into();
    }
    if is_likely_chapter {
        "chapter"
    } else {
        "section"
    }
    .into()
}

fn json_str(v: &serde_json::Value, key: &str) -> String {
    v.get(key)
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string()
}

/// 构建 TOC 树。←→ Python `_build_toc_tree`
pub fn build_toc_tree(
    toc_items: &[TocItem],
    _chapter_rows: &[ChapterRecord],
    meta: &serde_json::Value,
) -> Vec<TocNode> {
    let title_keys: HashSet<String> = _chapter_rows
        .iter()
        .map(|r| chapter_title_match_key(&r.title))
        .filter(|k| !k.is_empty())
        .collect();

    let extract_keys = |k: &str| -> HashSet<String> {
        meta.get(k)
            .and_then(|v| v.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|v| {
                        let s = v.as_str()?;
                        let k = chapter_title_match_key(s);
                        if k.is_empty() {
                            None
                        } else {
                            Some(k)
                        }
                    })
                    .collect()
            })
            .unwrap_or_default()
    };

    let container_keys = extract_keys("container_titles");
    let endnotes_keys = extract_keys("endnotes_titles");
    let post_body_keys = extract_keys("post_body_titles");
    let back_matter_keys = extract_keys("back_matter_titles");

    // 处理 normalized_toc_rows（可能来自 meta）
    let normalized_rows: Vec<serde_json::Value> = meta
        .get("normalized_toc_rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    // 构建 page/hint fallback 映射
    let mut page_by_key: std::collections::HashMap<String, i64> = std::collections::HashMap::new();
    let mut hint_by_key: std::collections::HashMap<String, String> =
        std::collections::HashMap::new();
    for item in toc_items {
        let tk = chapter_title_match_key(&normalize_title(&item.title));
        if tk.is_empty() {
            continue;
        }
        if let Some(pn) = item.target_pdf_page {
            if pn > 0 {
                page_by_key.insert(tk.clone(), pn);
            }
        }
        let rh = item.role_hint.trim().to_string();
        if !rh.is_empty() {
            hint_by_key.insert(tk, rh);
        }
    }

    // 用 normalized_rows 或 toc_items 作为 source
    let use_normalized = !normalized_rows.is_empty();
    let count = if use_normalized {
        normalized_rows.len()
    } else {
        toc_items.len()
    };
    let mut nodes: Vec<TocNode> = Vec::new();
    let mut prev_page: Option<i64> = None;

    for idx in 0..count {
        let (title_str, item_id, level, role_hint, parent_title, target_page) = if use_normalized {
            let row = &normalized_rows[idx];
            (
                json_str(row, "title"),
                json_str(row, "item_id"),
                row.get("level")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(1)
                    .max(1),
                json_str(row, "role_hint"),
                json_str(row, "parent_title"),
                row.get("target_pdf_page")
                    .or(row.get("page_no"))
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0),
            )
        } else {
            let item = &toc_items[idx];
            (
                item.title.clone(),
                item.item_id.clone(),
                item.level.max(1),
                item.role_hint.clone(),
                item.parent_title.clone(),
                item.target_pdf_page.unwrap_or(0),
            )
        };

        let title = normalize_title(&title_str);
        if title.is_empty() {
            continue;
        }
        let title_key = chapter_title_match_key(&title);

        // explicit_role
        let explicit_role = if use_normalized {
            let row = &normalized_rows[idx];
            let sem = json_str(row, "semantic_role");
            let rh = json_str(row, "role_hint");
            let eh = json_str(row, "explicit_role_hint");
            let hint_lower = rh.to_lowercase();
            let mut er = if !sem.is_empty() {
                sem
            } else if !rh.is_empty() {
                rh
            } else {
                eh
            };
            // skeleton "chapter" with visual_toc "content" → discard
            if er.trim().to_lowercase() == "chapter"
                && (hint_lower == "content"
                    || hint_by_key.get(&title_key).map(|s| s.as_str()) == Some("content"))
            {
                er = "content".into();
            }
            er
        } else {
            role_hint.clone()
        };

        let target_pdf_page = if target_page > 0 {
            target_page
        } else {
            page_by_key.get(&title_key).copied().unwrap_or(0)
        };

        // is_likely_chapter
        let nl = title.to_lowercase();
        let has_number_prefix =
            nl.chars().take(2).all(|c| c.is_ascii_digit()) && nl.chars().nth(2) == Some('.');
        let has_chapter_kw = [
            "chapter", "chapitre", "leçon", "lecture", "prologue", "epilogue",
        ]
        .iter()
        .any(|kw| nl.contains(kw));
        let page_changed = target_pdf_page > 0 && (prev_page != Some(target_pdf_page));
        let is_likely_chapter = has_number_prefix || has_chapter_kw || page_changed;

        let role = map_toc_role(
            &title,
            &explicit_role,
            &title_key,
            &TocRoleKeySets {
                container_keys: &container_keys,
                endnotes_keys: &endnotes_keys,
                post_body_keys: &post_body_keys,
                back_matter_keys: &back_matter_keys,
                chapter_keys: &title_keys,
            },
            is_likely_chapter,
        );

        if target_pdf_page > 0 {
            prev_page = Some(target_pdf_page);
        }

        let node_id = if !item_id.trim().is_empty() {
            item_id.trim().to_string()
        } else {
            format!("toc-node-{:04}", idx + 1)
        };

        nodes.push(TocNode {
            node_id,
            title,
            role,
            level,
            target_pdf_page,
            parent_id: parent_title.trim().to_string(),
        });
    }

    nodes
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_input() {
        let nodes = build_toc_tree(&[], &[], &serde_json::json!({}));
        assert!(nodes.is_empty());
    }

    #[test]
    fn normalize_role_basic() {
        assert_eq!(normalize_toc_node_role("part"), "container");
        assert_eq!(normalize_toc_node_role("notes"), "endnotes");
        assert_eq!(normalize_toc_node_role("chapter"), "chapter");
    }
}
