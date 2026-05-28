//! ←→ FNM_RE/modules/toc_structure.py
//! Phase1 顶层编排：组装所有子模块输出为 Phase1Structure。

use crate::chapter_skeleton::builder::build_chapter_skeleton;
use crate::heading_graph::build_heading_graph;
use crate::input::{ManualPageOverride, RawPage, TocItem};
use crate::page_partition::build_page_partitions;
use crate::page_roles::build_page_roles;
use crate::section_heads::build_section_heads;
use crate::toc_tree::build_toc_tree;
use fnm_core::db::Repository;
use fnm_core::records::{HeadingCandidate, Phase1Structure};
use fnm_core::types::ChapterSource;
use std::collections::HashMap;

/// TOC 门控报告，与 Python `GateReport` 对应。
/// ←→ FNM_RE/modules/contracts.py GateReport
#[derive(Debug, Clone, serde::Serialize)]
pub struct GateReport {
    pub hard: HashMap<String, bool>,
    pub soft: HashMap<String, bool>,
}

/// 已应用的覆写记录。
#[derive(Debug, Clone, serde::Serialize)]
pub struct OverrideRecord {
    pub kind: String,
    pub description: String,
}

#[derive(Debug, Clone)]
pub struct Phase1Config {
    pub manual_page_overrides: Option<HashMap<String, ManualPageOverride>>,
    /// VisualTOC bundle 中的 endnotes_start_page，用于 page_partition 的 front_matter 延续页修复。
    /// ←→ Python `build_toc_structure` 的 `endnotes_start_page`
    pub endnotes_start_page: Option<i64>,
    pub pdf_path: Option<String>,
    pub doc_id: Option<String>,
    /// LLM book-type 校验开关。当前 Rust 端 LLM 客户端尚未接入 phase1
    /// 主入口，默认 `true`（跳过）；传 `false` 触发 `anyhow::bail!`。
    pub skip_llm_verify: bool,
}

impl Default for Phase1Config {
    fn default() -> Self {
        Self {
            manual_page_overrides: None,
            endnotes_start_page: None,
            pdf_path: None,
            doc_id: None,
            skip_llm_verify: true,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Phase1Output {
    pub structure: Phase1Structure,
    pub diagnostics: serde_json::Value,
    /// 门控报告：硬 gate → 阻断管线，软 gate → 告警。
    pub gate_report: GateReport,
    /// 已应用的手动覆写记录。
    pub overrides_used: Vec<OverrideRecord>,
}

/// 检测 TOC 条目是否包含 OCR 乱码（控制字符比例 ≥5% 的条目占 ≥30%）。
/// ←→ FNM_RE/modules/toc_structure.py `_toc_items_look_garbled`
fn toc_items_look_garbled(toc_items: &[TocItem]) -> bool {
    if toc_items.is_empty() {
        return false;
    }
    let garbled_count = toc_items
        .iter()
        .filter(|item| {
            let title = &item.title;
            if title.is_empty() {
                return false;
            }
            let ctrl_count = title.chars().filter(|c| c.is_control()).count();
            ctrl_count > 0 && ctrl_count as f64 / title.len() as f64 > 0.05
        })
        .count();
    garbled_count > 0 && garbled_count as f64 >= toc_items.len() as f64 * 0.3
}

/// Phase1 主入口：从原始页面构建章节骨架。
pub fn build_phase1_structure(
    pages: &[RawPage],
    toc_items: Option<&[TocItem]>,
    config: &Phase1Config,
) -> anyhow::Result<Phase1Output> {
    let total_pages = pages.len() as i64;

    // 0. TOC 乱码检测
    let toc_garbled = toc_items.is_some_and(toc_items_look_garbled);

    // 1. LLM book-type 校验：Rust 端 LLM 客户端尚未接入主入口（FNM_PHASE12_AUDIT G5）。
    //    config.skip_llm_verify=false 时显式 bail 防误用（AGENTS.md §9）。
    if !config.skip_llm_verify {
        anyhow::bail!(
            "Phase1Config::skip_llm_verify=false 暂不支持——\
             LLM book-type 校验需 vision client 接入主入口（FNM_PHASE12_AUDIT G5）"
        );
    }

    // 2. build_page_partitions —— 把 manual_page_overrides 真传下去（原 None 静默忽略 F7）
    let partitions_result = build_page_partitions(
        pages,
        config.manual_page_overrides.as_ref(),
        config.endnotes_start_page,
    );
    let page_partitions = partitions_result.partitions;

    // 3. 构建 heading candidates（page_rows → collect → normalize）
    let page_rows = crate::chapter_skeleton::heading_candidates::page_rows::legacy_page_rows(
        &page_partitions,
        Some(pages),
    );
    let heading_candidates: Vec<HeadingCandidate> =
        crate::chapter_skeleton::heading_candidates::collect_heading_candidate_rows(
            &page_rows,
            toc_items,
            0,
            &config.pdf_path.clone().unwrap_or_default(),
            None,
            Some(&partitions_result.file_idx_map),
            &config.doc_id.clone().unwrap_or_default(),
        );

    // 4. build_heading_graph（完整版：local_exact + expanded_exact 锚点解析）
    let toc_exportable: Vec<(String, i64, String)> = toc_items
        .map(|items| {
            items
                .iter()
                .filter(|item| item.export_candidate.unwrap_or(true))
                .map(|item| {
                    (
                        item.title.clone(),
                        item.target_pdf_page.unwrap_or(0),
                        item.role_hint.clone(),
                    )
                })
                .collect()
        })
        .unwrap_or_default();
    let page_role_pairs: Vec<(i64, String)> = page_partitions
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str().to_string()))
        .collect();
    let heading_graph = build_heading_graph(&toc_exportable, &heading_candidates, &page_role_pairs);

    // 6. build_chapter_skeleton
    let skeleton = build_chapter_skeleton(
        pages,
        toc_items,
        &page_partitions,
        &heading_graph,
        heading_candidates,
    );

    // 注：`build_book_note_profile` 不在主入口调用——
    // 它推断的 `chapter_modes` 在 phase2 `chapter_split` 内会重新生成
    // （CLAUDE.md §12 分类源头唯一：note_mode 是 phase2 决策权）。
    // phase1 的 book_note_type 模块保留给 LLM book-type verify 用作 prior
    // （FNM_PHASE12_AUDIT G5）。

    // 7. build_section_heads（传入 toc_semantics 输出的 section_heads 作为 fallback sections）
    let fallback_secs: Vec<serde_json::Value> = skeleton
        .toc_semantics_section_heads
        .iter()
        .map(|sh| {
            serde_json::json!({
                "chapter_id": sh.chapter_id,
                "title": sh.title,
                "page_no": sh.page_no,
                "level": sh.level,
                "source": sh.source,
            })
        })
        .collect();
    let (section_heads, _) = build_section_heads(
        &skeleton.chapters,
        &skeleton.heading_candidates,
        &page_partitions,
        Some(&fallback_secs),
    );

    // 8. 构建 overrides_used（←→ Python `build_toc_structure` 行 494-517）
    let mut overrides_used: Vec<OverrideRecord> = Vec::new();
    if let Some(ref overrides) = config.manual_page_overrides {
        for page_str in overrides.keys() {
            overrides_used.push(OverrideRecord {
                kind: "page_override".to_string(),
                description: format!("manual page override for page {}", page_str),
            });
        }
    }

    // 9. 构建 chapter_source_summary 诊断
    let visual_toc_count = skeleton
        .chapters
        .iter()
        .filter(|c| c.source == ChapterSource::VisualToc)
        .count();
    let fallback_count = skeleton
        .chapters
        .iter()
        .filter(|c| c.source == ChapterSource::Fallback)
        .count();
    let chapter_source = if visual_toc_count > 0 {
        "visual_toc"
    } else {
        "fallback"
    };

    // 10. 组装 Phase1Structure（page_partitions 已 owned，零 clone）
    // builder.rs 把 toc_semantics 的完整 meta 写入 diagnostics 顶层，不再嵌套 toc_semantic_meta
    let toc_tree = build_toc_tree(
        toc_items.unwrap_or(&[]),
        &skeleton.chapters,
        &skeleton.diagnostics,
    );

    // D5: TOC tree 过滤/补入（←→ Python toc_structure.py:401-449）
    let mut filtered_chapters = skeleton.chapters.clone();
    if !toc_tree.is_empty() {
        // 构建非章 TOC node 的 title key set
        let toc_non_chapter_keys: std::collections::HashSet<String> = toc_tree
            .iter()
            .filter(|n| !matches!(n.role.as_str(), "chapter" | "container" | "endnotes"))
            .map(|n| fnm_core::title::chapter_title_match_key(&n.title))
            .filter(|k| !k.is_empty())
            .collect();
        // 从章节列表剔除匹配的条目
        if !toc_non_chapter_keys.is_empty() {
            filtered_chapters.retain(|ch| {
                !toc_non_chapter_keys.contains(&fnm_core::title::chapter_title_match_key(&ch.title))
            });
        }
        // 补入 post_body / back_matter 条目
        let existing_keys: std::collections::HashSet<String> = filtered_chapters
            .iter()
            .map(|ch| fnm_core::title::chapter_title_match_key(&ch.title))
            .filter(|k| !k.is_empty())
            .collect();
        let mut extra_nodes: Vec<&fnm_core::records::TocNode> = toc_tree
            .iter()
            .filter(|n| n.role == "post_body" || n.role == "back_matter")
            .collect();
        extra_nodes.sort_by(|a, b| {
            let pa = if a.target_pdf_page > 0 {
                a.target_pdf_page
            } else {
                9999
            };
            let pb = if b.target_pdf_page > 0 {
                b.target_pdf_page
            } else {
                9999
            };
            pa.cmp(&pb).then(a.title.cmp(&b.title))
        });
        let total_pages = page_partitions.len().max(1) as i64;
        let all_starts: Vec<i64> = {
            let mut s: Vec<i64> = filtered_chapters
                .iter()
                .filter_map(|ch| {
                    if ch.start_page > 0 {
                        Some(ch.start_page)
                    } else {
                        None
                    }
                })
                .collect();
            s.sort();
            s
        };
        for node in &extra_nodes {
            let tk = fnm_core::title::chapter_title_match_key(&node.title);
            if tk.is_empty() || existing_keys.contains(&tk) {
                continue;
            }
            let start = if node.target_pdf_page > 0 {
                node.target_pdf_page
            } else {
                0
            };
            let next = all_starts
                .iter()
                .find(|&&s| s > start)
                .copied()
                .unwrap_or(total_pages + 1);
            let end = next - 1;
            let pages: Vec<i64> = if start > 0 && end >= start {
                (start..=end).collect()
            } else {
                vec![]
            };
            filtered_chapters.push(fnm_core::records::ChapterRecord {
                chapter_id: format!(
                    "toc-ch-{:03}-{}",
                    filtered_chapters.len() + 1,
                    &tk[..tk.len().min(20)]
                ),
                title: node.title.clone(),
                start_page: start,
                end_page: end,
                pages,
                source: fnm_core::types::ChapterSource::VisualToc,
                boundary_state: fnm_core::types::BoundaryState::Ready,
            });
        }
    }

    let page_roles = build_page_roles(&page_partitions, &filtered_chapters, 0);

    // 构建 gate_report（在 Phase1Structure 消耗数据前计算）
    let pages_classified = page_partitions.iter().all(|p| {
        let role = p.page_role.as_str();
        !matches!(role, "unknown" | "noise")
    });
    let toc_semantic_contract_ok = skeleton
        .diagnostics
        .get("toc_semantic_contract_ok")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let first_back_matter_page = page_roles
        .iter()
        .filter(|pr| pr.role == "back_matter")
        .map(|pr| pr.page_no)
        .min()
        .unwrap_or(0);
    let no_chapter_after_back_matter = first_back_matter_page <= 0
        || !page_roles
            .iter()
            .any(|pr| pr.role == "chapter" && pr.page_no > first_back_matter_page);
    let role_semantics_valid = toc_semantic_contract_ok && no_chapter_after_back_matter;

    let toc_chapter_order_monotonic = if !toc_tree.is_empty() {
        let chapter_targets: Vec<i64> = toc_tree
            .iter()
            .filter(|n| n.target_pdf_page > 0 && (n.role == "chapter" || n.role == "post_body"))
            .map(|n| n.target_pdf_page)
            .collect();
        if chapter_targets.len() >= 2 {
            chapter_targets.windows(2).all(|w| w[0] <= w[1])
        } else {
            let chs: Vec<i64> = filtered_chapters.iter().map(|c| c.start_page).collect();
            chs.windows(2).all(|w| w[0] <= w[1])
        }
    } else {
        toc_items.map_or(true, |items| {
            let mut prev_page: Option<i64> = None;
            items
                .iter()
                .filter(|t| t.role_hint != "container")
                .all(|t| {
                    let ok =
                        prev_page.map_or(true, |p| t.target_pdf_page.map_or(true, |tp| tp >= p));
                    prev_page = t.target_pdf_page;
                    ok
                })
        })
    };
    let has_exportable_chapters = !filtered_chapters.is_empty();
    let chapter_titles_aligned = skeleton
        .diagnostics
        .get("chapter_title_alignment_ok")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);

    let section_alignment_warn = chapter_titles_aligned;
    let visual_toc_conflict_count = skeleton
        .diagnostics
        .get("visual_toc_conflict_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    let visual_toc_conflict_warn = visual_toc_conflict_count == 0;

    let gate_report = GateReport {
        hard: HashMap::from([
            ("toc.pages_classified".into(), pages_classified),
            (
                "toc.chapter_order_monotonic".into(),
                toc_chapter_order_monotonic,
            ),
            ("toc.role_semantics_valid".into(), role_semantics_valid),
            (
                "toc.has_exportable_chapters".into(),
                has_exportable_chapters,
            ),
            ("toc.chapter_titles_aligned".into(), chapter_titles_aligned),
        ]),
        soft: HashMap::from([
            ("toc.section_alignment_warn".into(), section_alignment_warn),
            (
                "toc.visual_toc_conflict_warn".into(),
                visual_toc_conflict_warn,
            ),
        ]),
    };

    let structure = Phase1Structure {
        pages: page_partitions,
        heading_candidates: skeleton.heading_candidates,
        chapters: filtered_chapters,
        section_heads,
        endnote_explorer_hints: Default::default(),
        summary: Default::default(),
        toc_tree,
        page_roles,
    };

    Ok(Phase1Output {
        structure,
        diagnostics: serde_json::json!({
            "total_pages": total_pages,
            "toc_garbled": toc_garbled,
            "chapter_source_summary": {
                "source": chapter_source,
                "visual_toc_chapter_count": visual_toc_count,
                "fallback_chapter_count": fallback_count,
            },
        }),
        gate_report,
        overrides_used,
    })
}

/// 把 Phase1Output 持久化到 DB（消耗 ownership，零 clone）。
pub fn persist_phase1(
    repo: &dyn Repository,
    doc_id: &str,
    output: Phase1Output,
) -> anyhow::Result<()> {
    repo.replace_fnm_phase1_products(
        doc_id,
        &fnm_core::db::Phase1Products {
            pages: output.structure.pages,
            chapters: output.structure.chapters,
            heading_candidates: output.structure.heading_candidates,
            section_heads: output.structure.section_heads,
        },
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::input::RawPage;

    #[test]
    fn build_structure_empty_pages() {
        let config = Phase1Config::default();
        let output = build_phase1_structure(&[], None, &config).unwrap();
        assert!(output.structure.pages.is_empty());
        assert!(output.structure.chapters.is_empty());
    }

    #[test]
    fn build_structure_single_page() {
        let pages = vec![RawPage {
            book_page: 1,
            markdown: "# Test\nContent".into(),
            ..Default::default()
        }];
        let config = Phase1Config::default();
        let output = build_phase1_structure(&pages, None, &config).unwrap();
        assert_eq!(output.structure.pages.len(), 1);
        assert_eq!(output.structure.pages[0].page_no, 1);
    }
}
