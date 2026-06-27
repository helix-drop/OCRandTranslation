//! ←→ FNM_RE/stages/heading_graph.py
//! TOC 锚点优化器：将 TOC 条目与页面 heading candidates 匹配，找到最佳物理页面锚点。

pub mod composite;
pub mod matching;
pub mod scoring;
pub mod title_key;

use fnm_core::records::HeadingCandidate;
use std::collections::HashMap;

/// 默认空 heading graph 摘要。
pub fn default_heading_graph_summary() -> serde_json::Value {
    serde_json::json!({
        "toc_body_item_count": 0,
        "resolved_anchor_count": 0,
        "provisional_anchor_count": 0,
        "section_node_count": 0,
        "unresolved_titles_preview": [],
        "boundary_conflict_titles_preview": [],
        "promoted_section_titles_preview": [],
        "demoted_chapter_titles_preview": [],
        "optimized_anchor_count": 0,
        "residual_provisional_count": 0,
        "residual_provisional_titles_preview": [],
        "expanded_window_hit_count": 0,
        "composite_heading_count": 0,
    })
}

/// Graph row：每个 TOC 条目的锚点解析结果。
#[derive(Debug, Clone, Default)]
pub struct GraphRow {
    pub title: String,
    pub page_no: i64,
    pub anchor_page: i64,
    pub anchor_state: String,    // "resolved" / "provisional" / "unresolved"
    pub anchor_strategy: String, // "local_exact" / "expanded_exact" / "monotonic_target" / "provisional" / "unresolved"
    pub anchor_candidate_source: String,
    pub optimized_anchor: bool,
    pub expanded_window_hit: bool,
    pub target_page: i64,
    pub semantic_role: String,
}

/// Heading graph 输出。
#[derive(Debug, Clone, Default)]
pub struct HeadingGraph {
    pub graph_rows: Vec<GraphRow>,
    pub family_by_id: HashMap<String, String>,
    pub depth_by_id: HashMap<String, i64>,
    pub summary: serde_json::Value,
}

const HEADING_GRAPH_PREVIEW_LIMIT: usize = 8;
const BODY_PAGE_ROLES: &[&str] = &["body", "front_matter"];

/// 从 exportable_rows + heading_candidates + page_roles 构建 heading graph。
/// 对齐 Python `build_heading_graph()`。
pub fn build_heading_graph(
    exportable_rows: &[(String, i64, String)], // (title, page_no, semantic_role)
    heading_candidates: &[HeadingCandidate],
    page_roles: &[(i64, String)], // (page_no, page_role)
) -> HeadingGraph {
    if exportable_rows.is_empty() {
        return HeadingGraph {
            summary: default_heading_graph_summary(),
            ..Default::default()
        };
    }

    let page_role_map: HashMap<i64, &str> =
        page_roles.iter().map(|(p, r)| (*p, r.as_str())).collect();

    let stop_pages = matching::body_stop_pages(
        &page_roles
            .iter()
            .map(|(p, r)| (*p, r.as_str()))
            .collect::<Vec<_>>(),
    );

    // 生成 composite candidates
    let (derived_candidates, composite_heading_count) =
        composite::build_derived_heading_candidates(heading_candidates);

    // 合并原始 + derived，过滤为 anchor candidates
    let page_role_pairs: Vec<(i64, &str)> =
        page_roles.iter().map(|(p, r)| (*p, r.as_str())).collect();
    let all_candidates: Vec<HeadingCandidate> = heading_candidates
        .iter()
        .chain(derived_candidates.iter())
        .cloned()
        .collect();
    let anchor_candidates: Vec<HeadingCandidate> = all_candidates
        .into_iter()
        .filter(|c| matching::is_anchor_candidate(c, &page_role_pairs))
        .collect();

    let mut graph_rows: Vec<GraphRow> = Vec::new();
    let mut unresolved_titles: Vec<String> = Vec::new();
    let mut promoted_section_titles: Vec<String> = Vec::new();
    let mut prev_anchor_page = 0i64;

    // Round 1: local_exact
    for (index, (title, target_page, semantic_role)) in exportable_rows.iter().enumerate() {
        let title_key = title_key::heading_graph_title_key(title);
        let local_start = if *target_page > 0 { target_page - 1 } else { 1 };
        let local_start = local_start.max(1);
        let local_end = if *target_page > 0 {
            (target_page + 2).max(local_start)
        } else {
            0
        };
        let next_target_page = if index + 1 < exportable_rows.len() {
            exportable_rows[index + 1].1
        } else {
            0
        };

        let local_candidate = if !title_key.is_empty() && local_end > 0 {
            matching::best_candidate(
                &title_key,
                &anchor_candidates,
                local_start,
                local_end,
                *target_page,
                (prev_anchor_page, next_target_page),
                false,
            )
        } else {
            None
        };

        let (anchor_page, anchor_state, anchor_strategy, optimized_anchor) =
            if let Some(candidate) = local_candidate {
                let is_section = matching::is_section_style_candidate(&candidate);
                if is_section {
                    promoted_section_titles.push(title.clone());
                }
                (
                    candidate.page_no,
                    "resolved".to_string(),
                    "local_exact".to_string(),
                    candidate.page_no != *target_page || is_section,
                )
            } else if *target_page > 0
                && page_role_map
                    .get(target_page)
                    .is_some_and(|r| BODY_PAGE_ROLES.contains(r))
            {
                let strategy = if semantic_role == "post_body" {
                    "post_body_target"
                } else {
                    "provisional"
                };
                let state = if semantic_role == "post_body" {
                    "resolved"
                } else {
                    "provisional"
                };
                (*target_page, state.to_string(), strategy.to_string(), false)
            } else {
                unresolved_titles.push(title.clone());
                (0, "unresolved".to_string(), "unresolved".to_string(), false)
            };

        graph_rows.push(GraphRow {
            title: title.clone(),
            page_no: *target_page,
            anchor_page,
            anchor_state,
            anchor_strategy,
            anchor_candidate_source: String::new(),
            optimized_anchor,
            expanded_window_hit: false,
            target_page: *target_page,
            semantic_role: semantic_role.clone(),
        });
        if anchor_page > 0 {
            prev_anchor_page = anchor_page;
        }
    }

    // Round 2: expanded_exact（对 provisional 行扩大搜索窗口）
    for index in 0..graph_rows.len() {
        if graph_rows[index].anchor_state != "provisional" {
            continue;
        }
        let title = graph_rows[index].title.clone();
        let title_key = title_key::heading_graph_title_key(&title);
        if title_key.is_empty() {
            continue;
        }
        let target_page = graph_rows[index].target_page;

        // 找前一个 resolved anchor
        let prev_final_anchor = graph_rows[..index]
            .iter()
            .rev()
            .find(|r| r.anchor_page > 0)
            .map(|r| r.anchor_page)
            .unwrap_or(0);
        // 找后一个 anchor 或 target
        let next_anchor_or_target = if index + 1 < graph_rows.len() {
            let next = &graph_rows[index + 1];
            if next.anchor_page > 0 {
                next.anchor_page
            } else {
                next.target_page
            }
        } else {
            0
        };

        let left = (prev_final_anchor + 1).max(target_page - 6);
        let mut right_candidates = vec![target_page + 10];
        if next_anchor_or_target > 0 {
            right_candidates.push(next_anchor_or_target - 1);
        }
        let next_stop = matching::next_stop_page(&stop_pages, target_page);
        if next_stop > 0 {
            right_candidates.push(next_stop - 1);
        }
        let right = right_candidates.into_iter().min().unwrap_or(0);
        if left <= 0 || right <= 0 || right < left {
            continue;
        }

        let expanded = matching::best_candidate(
            &title_key,
            &anchor_candidates,
            left,
            right,
            target_page,
            (prev_final_anchor, next_anchor_or_target),
            true,
        );

        if let Some(candidate) = expanded {
            let is_section = matching::is_section_style_candidate(&candidate);
            if is_section {
                promoted_section_titles.push(title);
            }
            graph_rows[index].anchor_page = candidate.page_no;
            graph_rows[index].anchor_state = "resolved".to_string();
            graph_rows[index].anchor_strategy = "expanded_exact".to_string();
            graph_rows[index].expanded_window_hit = true;
            graph_rows[index].optimized_anchor = true;
        }
    }

    // Round 3: monotonic_target（对剩余 provisional 行用 target_page）
    let monotonic_enabled = exportable_rows.len() >= 2;
    if monotonic_enabled {
        for index in 0..graph_rows.len() {
            if graph_rows[index].anchor_state != "provisional" {
                continue;
            }
            let target_page = graph_rows[index].target_page;
            if target_page <= 0 {
                continue;
            }
            if !page_role_map
                .get(&target_page)
                .is_some_and(|r| BODY_PAGE_ROLES.contains(r))
            {
                continue;
            }
            let prev_final_anchor = graph_rows[..index]
                .iter()
                .rev()
                .find(|r| r.anchor_page > 0)
                .map(|r| r.anchor_page)
                .unwrap_or(0);
            let next_anchor_or_target = if index + 1 < graph_rows.len() {
                let next = &graph_rows[index + 1];
                if next.anchor_page > 0 {
                    next.anchor_page
                } else {
                    next.target_page
                }
            } else {
                0
            };
            if prev_final_anchor > 0 && target_page <= prev_final_anchor {
                continue;
            }
            if next_anchor_or_target > 0 && target_page >= next_anchor_or_target {
                continue;
            }
            graph_rows[index].anchor_page = target_page;
            graph_rows[index].anchor_state = "resolved".to_string();
            graph_rows[index].anchor_strategy = "monotonic_target".to_string();
            graph_rows[index].optimized_anchor = true;
        }
    }

    // Boundary conflict 检测
    let mut boundary_conflict_titles: Vec<String> = Vec::new();
    let mut previous_anchor_page = 0i64;
    for row in &graph_rows {
        if row.anchor_page <= 0 {
            continue;
        }
        if row.anchor_page <= previous_anchor_page {
            boundary_conflict_titles.push(row.title.clone());
        }
        previous_anchor_page = row.anchor_page;
    }

    // Summary
    let resolved_count = graph_rows
        .iter()
        .filter(|r| r.anchor_state == "resolved")
        .count();
    let provisional_count = graph_rows
        .iter()
        .filter(|r| r.anchor_state == "provisional")
        .count();
    let optimized_count = graph_rows.iter().filter(|r| r.optimized_anchor).count();
    let expanded_hit_count = graph_rows.iter().filter(|r| r.expanded_window_hit).count();

    let residual_provisional: Vec<String> = graph_rows
        .iter()
        .filter(|r| r.anchor_state == "provisional")
        .map(|r| r.title.clone())
        .take(HEADING_GRAPH_PREVIEW_LIMIT)
        .collect();

    // family/depth 映射
    let mut family_by_id = HashMap::new();
    let mut depth_by_id = HashMap::new();
    for c in heading_candidates {
        if !c.heading_id.is_empty() {
            family_by_id
                .entry(c.heading_id.clone())
                .or_insert_with(|| c.heading_family_guess.clone());
            depth_by_id
                .entry(c.heading_id.clone())
                .or_insert(c.heading_level_hint);
        }
    }

    let summary = serde_json::json!({
        "toc_body_item_count": exportable_rows.len(),
        "resolved_anchor_count": resolved_count,
        "provisional_anchor_count": provisional_count,
        "section_node_count": 0,
        "unresolved_titles_preview": unresolved_titles,
        "boundary_conflict_titles_preview": boundary_conflict_titles,
        "promoted_section_titles_preview": promoted_section_titles,
        "demoted_chapter_titles_preview": [],
        "optimized_anchor_count": optimized_count,
        "residual_provisional_count": provisional_count,
        "residual_provisional_titles_preview": residual_provisional,
        "expanded_window_hit_count": expanded_hit_count,
        "composite_heading_count": composite_heading_count,
    });

    HeadingGraph {
        graph_rows,
        family_by_id,
        depth_by_id,
        summary,
    }
}

/// 旧签名兼容：只做 family/depth 推断。
pub fn build_heading_graph_simple(candidates: &[HeadingCandidate]) -> HeadingGraph {
    let mut graph = HeadingGraph::default();
    for c in candidates {
        if !c.heading_id.is_empty() {
            graph
                .family_by_id
                .insert(c.heading_id.clone(), c.heading_family_guess.clone());
            graph
                .depth_by_id
                .insert(c.heading_id.clone(), c.heading_level_hint);
        }
    }
    graph.summary = default_heading_graph_summary();
    graph
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::HeadingCandidate;

    fn make_candidate(
        id: &str,
        page: i64,
        text: &str,
        source: &str,
        family: &str,
    ) -> HeadingCandidate {
        HeadingCandidate {
            heading_id: id.into(),
            page_no: page,
            text: text.into(),
            normalized_text: text.to_lowercase(),
            source: source.into(),
            block_label: String::new(),
            top_band: false,
            confidence: 0.8,
            heading_family_guess: family.into(),
            suppressed_as_chapter: false,
            reject_reason: String::new(),
            font_height: None,
            x: None,
            y: None,
            width_estimate: None,
            font_name: String::new(),
            font_weight_hint: "unknown".into(),
            align_hint: "unknown".into(),
            width_ratio: None,
            heading_level_hint: 1,
        }
    }

    #[test]
    fn graph_builds_from_candidates() {
        let candidates = vec![make_candidate("h1", 1, "Ch 1", "ocr_block", "chapter")];
        let graph = build_heading_graph_simple(&candidates);
        assert_eq!(graph.family_by_id.get("h1"), Some(&"chapter".into()));
        assert_eq!(graph.depth_by_id.get("h1"), Some(&1));
    }

    #[test]
    fn empty_exportable_rows_returns_default() {
        let graph = build_heading_graph(&[], &[], &[]);
        assert!(graph.graph_rows.is_empty());
    }

    #[test]
    fn local_exact_match() {
        let candidates = vec![make_candidate(
            "h1",
            10,
            "Chapter One",
            "markdown_heading",
            "chapter",
        )];
        let exportable = vec![("Chapter One".into(), 10, "chapter".into())];
        let page_roles = vec![(10, "body".into())];
        let graph = build_heading_graph(&exportable, &candidates, &page_roles);
        assert_eq!(graph.graph_rows.len(), 1);
        assert_eq!(graph.graph_rows[0].anchor_page, 10);
        assert_eq!(graph.graph_rows[0].anchor_state, "resolved");
    }
}
