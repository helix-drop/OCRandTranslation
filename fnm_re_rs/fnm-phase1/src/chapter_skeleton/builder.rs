//! ←→ FNM_RE/stages/chapter_skeleton/builder.py (449 行)
//! 章节骨架主编排——visual TOC 优先，失败回退到 fallback；
//! 应用 back_matter trim、生成 dropped_titles 诊断、装配完整 meta。

use crate::chapter_skeleton::fallback;
use crate::input::{RawPage, TocItem};
use fnm_core::records::{ChapterRecord, HeadingCandidate, PagePartitionRecord, SectionHeadRecord};
use fnm_core::title::chapter_title_match_key;
use fnm_core::types::{ChapterSource, PageRole};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

// ── 公开输出 ────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct ChapterSkeleton {
    pub chapters: Vec<ChapterRecord>,
    pub heading_candidates: Vec<HeadingCandidate>,
    pub toc_semantics_section_heads: Vec<SectionHeadRecord>,
    pub fallback_sections: Vec<SectionHeadRecord>,
    pub diagnostics: Value,
}

/// ←→ Python `_compact_unique_titles`
fn compact_unique_titles(titles: &[String], cap: usize) -> Vec<String> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut out: Vec<String> = Vec::new();
    for t in titles {
        let key = t.trim().to_string();
        if key.is_empty() || seen.contains(&key) {
            continue;
        }
        seen.insert(key.clone());
        out.push(key);
        if out.len() >= cap {
            break;
        }
    }
    out
}

/// ←→ Python `default_heading_graph_summary`
fn default_heading_graph_summary() -> Value {
    json!({
        "boundary_conflict_count": 0,
        "boundary_conflict_titles_preview": Vec::<String>::new(),
        "round_1_match_count": 0,
        "round_2_match_count": 0,
        "round_3_match_count": 0,
        "total_match_count": 0,
        "unmatched_count": 0,
        "unmatched_titles_preview": Vec::<String>::new(),
    })
}

// ── 主入口 ──────────────────────────────────────────────────────

/// 从 TOC items + page_partitions 构建章节骨架。
/// ←→ Python `build_chapter_skeleton`
pub fn build_chapter_skeleton(
    pages: &[RawPage],
    toc_items: Option<&[TocItem]>,
    page_partitions: &[PagePartitionRecord],
    heading_graph: &crate::heading_graph::HeadingGraph,
    mut heading_candidates: Vec<HeadingCandidate>,
) -> ChapterSkeleton {
    let total_pages = pages.len() as i64;
    let visual_toc_items: Vec<TocItem> = toc_items.map(|items| items.to_vec()).unwrap_or_default();

    // page_roles map (string-keyed，给 fallback helper 用)
    let page_roles_str: HashMap<i64, String> = page_partitions
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str().to_string()))
        .collect();
    let page_roles_enum: HashMap<i64, PageRole> = page_partitions
        .iter()
        .map(|p| (p.page_no, p.page_role))
        .collect();
    let all_pages = fallback::all_page_numbers(page_partitions);

    // ── Step 1: 跑 fallback section/chapter（Python 端总是先跑 fallback，再决定）─

    let section_rows =
        fallback::candidate_section_rows(&heading_candidates, &all_pages, &page_roles_str);
    let classified_sections = fallback::classify_fallback_sections(
        section_rows,
        &page_roles_str,
        std::cmp::max(1, all_pages.len() as i64),
        &heading_candidates,
    );
    fallback::mark_suppressed_candidates(&classified_sections, &mut heading_candidates);
    let (fallback_chapters_raw, fallback_section_heads_raw) =
        fallback::build_fallback_chapters_and_sections(
            classified_sections,
            &all_pages,
            &page_roles_str,
        );

    // ── Step 2: visual TOC 路径 ──────────────────────────────────

    let visual_toc_result = if visual_toc_items.is_empty() {
        None
    } else {
        Some(crate::chapter_skeleton::toc_semantics::build_toc_semantics(
            &visual_toc_items,
            &[],
            pages,
            page_partitions,
            &heading_candidates,
            Some(heading_graph),
        ))
    };

    let visual_chapters_raw: Vec<ChapterRecord> = visual_toc_result
        .as_ref()
        .map(|r| r.aligned_chapters.clone())
        .unwrap_or_default();
    let visual_section_heads_raw: Vec<SectionHeadRecord> = visual_toc_result
        .as_ref()
        .map(|r| r.section_heads.clone())
        .unwrap_or_default();
    let visual_meta: Value = visual_toc_result
        .as_ref()
        .map(|r| r.meta.clone())
        .unwrap_or(Value::Null);

    // ── Step 3: 选择 visual / fallback / empty ──────────────────

    let (mut chapters_raw, merged_section_fallbacks, chapter_source_summary, source_hint) =
        if !visual_chapters_raw.is_empty() {
            let mut summary = visual_meta
                .get("chapter_source_summary")
                .cloned()
                .and_then(|v| v.as_object().cloned())
                .unwrap_or_default();
            summary
                .entry("source".to_string())
                .or_insert_with(|| json!("visual_toc"));
            summary
                .entry("chapter_level".to_string())
                .or_insert(Value::Null);
            summary
                .entry("visual_toc_chapter_count".to_string())
                .or_insert(json!(visual_chapters_raw.len()));
            summary
                .entry("legacy_chapter_count".to_string())
                .or_insert(json!(fallback_chapters_raw.len()));
            summary
                .entry("fallback_used".to_string())
                .or_insert(json!(false));
            summary
                .entry("body_section_fallback_suppressed".to_string())
                .or_insert(json!(fallback_section_heads_raw.len() as i64));
            (
                visual_chapters_raw.clone(),
                visual_section_heads_raw.clone(),
                Value::Object(summary),
                ChapterSource::VisualToc,
            )
        } else if !fallback_chapters_raw.is_empty() {
            let summary = json!({
                "source": "fallback",
                "chapter_level": Value::Null,
                "visual_toc_chapter_count": 0,
                "legacy_chapter_count": fallback_chapters_raw.len(),
                "fallback_used": true,
                "body_section_fallback_suppressed": 0,
            });
            (
                fallback_chapters_raw.clone(),
                fallback_section_heads_raw.clone(),
                summary,
                ChapterSource::Fallback,
            )
        } else {
            // 兜底：连续 body 页打包为单章（←→ Python `simple_fallback`）。
            let simple = fallback::simple_fallback(page_partitions);
            if !simple.is_empty() {
                let summary = json!({
                    "source": "fallback",
                    "chapter_level": Value::Null,
                    "visual_toc_chapter_count": 0,
                    "legacy_chapter_count": simple.len(),
                    "fallback_used": true,
                    "body_section_fallback_suppressed": 0,
                    "simple_fallback": true,
                });
                (
                    simple,
                    Vec::<SectionHeadRecord>::new(),
                    summary,
                    ChapterSource::Fallback,
                )
            } else {
                let summary = json!({
                    "source": "fallback",
                    "chapter_level": Value::Null,
                    "visual_toc_chapter_count": 0,
                    "legacy_chapter_count": 0,
                    "fallback_used": false,
                    "body_section_fallback_suppressed": 0,
                    "no_chapter_candidate": true,
                });
                (
                    Vec::<ChapterRecord>::new(),
                    Vec::<SectionHeadRecord>::new(),
                    summary,
                    ChapterSource::Fallback,
                )
            }
        };

    // ── Step 4: back matter trim ───────────────────────────────

    let post_body_titles: Vec<String> = visual_meta
        .get("post_body_titles")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    let preserved_post_body_title_keys: HashSet<String> = post_body_titles
        .iter()
        .map(|t| chapter_title_match_key(t))
        .filter(|k| !k.is_empty())
        .collect();

    let file_idx_map: HashMap<i64, i64> = pages
        .iter()
        .filter_map(|p| p.file_idx.map(|fi| (fi, p.book_page)))
        .collect();
    let back_matter_start_page = fallback::infer_back_matter_start_page(
        page_partitions,
        Some(&visual_toc_items),
        0,
        &file_idx_map,
    );

    // 转 ChapterRecord → ChapterRowDraft → trim → ChapterRecord
    let drafts: Vec<fallback::ChapterRowDraft> = chapters_raw
        .iter()
        .map(|ch| fallback::ChapterRowDraft {
            chapter_id: ch.chapter_id.clone(),
            title: ch.title.clone(),
            pages: ch.pages.clone(),
            source: ch.source.as_str().to_string(),
        })
        .collect();
    let trimmed_drafts = fallback::trim_chapter_rows(
        drafts,
        &page_roles_str,
        back_matter_start_page,
        &preserved_post_body_title_keys,
    );

    let raw_titles_by_id: HashMap<String, String> = chapters_raw
        .iter()
        .map(|ch| (ch.chapter_id.clone(), ch.title.clone()))
        .collect();
    let raw_chapters_by_id: HashMap<String, ChapterRecord> = chapters_raw
        .iter()
        .map(|ch| (ch.chapter_id.clone(), ch.clone()))
        .collect();
    let kept_ids: HashSet<String> = trimmed_drafts
        .iter()
        .map(|d| d.chapter_id.clone())
        .collect();
    // 重建 chapters_raw（应用 trim）
    chapters_raw = trimmed_drafts
        .iter()
        .filter_map(|d| {
            raw_chapters_by_id.get(&d.chapter_id).map(|orig| {
                let mut ch = orig.clone();
                ch.start_page = *d.pages.first().unwrap_or(&orig.start_page);
                ch.end_page = *d.pages.last().unwrap_or(&orig.end_page);
                ch.pages = d.pages.clone();
                ch
            })
        })
        .collect();

    // ── Step 5: dropped_titles 处理（visual 路径专用） ──────────

    let mut visual_meta_obj = visual_meta.as_object().cloned().unwrap_or_default();
    if !visual_chapters_raw.is_empty() {
        let dropped_titles: Vec<String> = raw_titles_by_id
            .iter()
            .filter_map(|(id, t)| {
                if !kept_ids.contains(id) && !t.is_empty() {
                    Some(t.clone())
                } else {
                    None
                }
            })
            .collect();
        if !dropped_titles.is_empty() {
            // heading_graph_summary.boundary_conflict_titles_preview += dropped
            let mut heading_graph_summary = visual_meta_obj
                .get("heading_graph_summary")
                .cloned()
                .unwrap_or_else(default_heading_graph_summary);
            let existing: Vec<String> = heading_graph_summary
                .get("boundary_conflict_titles_preview")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default();
            let mut combined = existing;
            combined.extend(dropped_titles.iter().cloned());
            let compacted = compact_unique_titles(&combined, 8);
            if let Value::Object(ref mut map) = heading_graph_summary {
                map.insert("boundary_conflict_titles_preview".into(), json!(compacted));
            }
            visual_meta_obj.insert("heading_graph_summary".into(), heading_graph_summary);

            // toc_alignment_summary.missing_chapter_titles_preview += dropped
            let mut toc_alignment_summary = visual_meta_obj
                .get("toc_alignment_summary")
                .cloned()
                .unwrap_or_else(|| {
                    fallback::default_toc_alignment_summary(chapters_raw.len() as i64)
                });
            if let Value::Object(ref mut map) = toc_alignment_summary {
                map.insert(
                    "exported_chapter_count".into(),
                    json!(chapters_raw.len() as i64),
                );
                let existing: Vec<String> = map
                    .get("missing_chapter_titles_preview")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(String::from))
                            .collect()
                    })
                    .unwrap_or_default();
                let mut combined = existing;
                combined.extend(dropped_titles.iter().cloned());
                map.insert(
                    "missing_chapter_titles_preview".into(),
                    json!(compact_unique_titles(&combined, 8)),
                );
            }
            visual_meta_obj.insert("toc_alignment_summary".into(), toc_alignment_summary);

            // toc_export_coverage_summary.missing_body_items_preview += dropped
            let mut coverage_summary = visual_meta_obj
                .get("toc_export_coverage_summary")
                .cloned()
                .unwrap_or_else(|| json!({}));
            if let Value::Object(ref mut map) = coverage_summary {
                map.insert(
                    "exported_body_items".into(),
                    json!(chapters_raw.len() as i64),
                );
                let existing: Vec<String> = map
                    .get("missing_body_items_preview")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(String::from))
                            .collect()
                    })
                    .unwrap_or_default();
                let mut combined = existing;
                combined.extend(dropped_titles.iter().cloned());
                map.insert(
                    "missing_body_items_preview".into(),
                    json!(compact_unique_titles(&combined, 8)),
                );
            }
            visual_meta_obj.insert("toc_export_coverage_summary".into(), coverage_summary);

            // toc_semantic_blocking_reasons += heading_graph_boundary_conflict
            let mut blocking: Vec<String> = visual_meta_obj
                .get("toc_semantic_blocking_reasons")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default();
            if !blocking
                .iter()
                .any(|r| r == "heading_graph_boundary_conflict")
            {
                blocking.push("heading_graph_boundary_conflict".into());
            }
            visual_meta_obj.insert("toc_semantic_blocking_reasons".into(), json!(blocking));
            visual_meta_obj.insert("toc_semantic_contract_ok".into(), json!(false));
        }
    }

    // 当 visual_chapters_raw 是空且 fallback 也空且 simple 也空（即 chapters 真空）时，设置 toc_no_exportable_chapter
    let truly_empty = visual_chapters_raw.is_empty()
        && fallback_chapters_raw.is_empty()
        && chapters_raw.is_empty();
    if truly_empty {
        let mut blocking: Vec<String> = visual_meta_obj
            .get("toc_semantic_blocking_reasons")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        if !blocking.iter().any(|r| r == "toc_no_exportable_chapter") {
            blocking.push("toc_no_exportable_chapter".into());
        }
        visual_meta_obj.insert("toc_semantic_blocking_reasons".into(), json!(blocking));
        visual_meta_obj.insert("toc_semantic_contract_ok".into(), json!(false));
        visual_meta_obj
            .entry("chapter_title_alignment_ok".to_string())
            .or_insert(json!(true));
        visual_meta_obj
            .entry("chapter_section_alignment_ok".to_string())
            .or_insert(json!(true));
    } else if !visual_chapters_raw.is_empty() {
        // visual 路径默认 alignment ok（除非上游已 set）
        visual_meta_obj
            .entry("chapter_title_alignment_ok".to_string())
            .or_insert(json!(true));
        visual_meta_obj
            .entry("chapter_section_alignment_ok".to_string())
            .or_insert(json!(true));
    } else {
        // pure fallback
        visual_meta_obj
            .entry("chapter_title_alignment_ok".to_string())
            .or_insert(json!(true));
        visual_meta_obj
            .entry("chapter_section_alignment_ok".to_string())
            .or_insert(json!(true));
        visual_meta_obj
            .entry("toc_semantic_contract_ok".to_string())
            .or_insert(json!(true));
    }

    // ── Step 6: normalize chapters + sections ───────────────────

    let chapters = fallback::normalize_chapters(chapters_raw);
    let _ = source_hint; // ChapterSource set by upstream visual or fallback paths
    let _ = merged_section_fallbacks; // fallback_sections 在下方独立暴露
    let heading_candidates_normalized = normalize_heading_candidates(heading_candidates.clone());
    let fallback_sections = fallback::normalize_sections(fallback_section_heads_raw.clone());

    // ── Step 7: 装配完整 meta（10+ 字段，对齐 Python）──────────

    let toc_alignment_summary = visual_meta_obj
        .get("toc_alignment_summary")
        .cloned()
        .unwrap_or_else(|| fallback::default_toc_alignment_summary(chapters.len() as i64));
    let toc_semantic_summary = visual_meta_obj
        .get("toc_semantic_summary")
        .cloned()
        .unwrap_or_else(|| fallback::default_toc_semantic_summary(chapters.len() as i64));
    let toc_role_summary_raw = visual_meta_obj
        .get("toc_role_summary")
        .cloned()
        .unwrap_or_else(|| {
            fallback::default_toc_role_summary(
                chapters.len() as i64,
                fallback_sections.len() as i64,
            )
        });
    let heading_graph_summary = visual_meta_obj
        .get("heading_graph_summary")
        .cloned()
        .unwrap_or_else(default_heading_graph_summary);
    let container_titles = visual_meta_obj
        .get("container_titles")
        .cloned()
        .unwrap_or(json!([]));
    let endnotes_titles = visual_meta_obj
        .get("endnotes_titles")
        .cloned()
        .unwrap_or(json!([]));
    let back_matter_titles = visual_meta_obj
        .get("back_matter_titles")
        .cloned()
        .unwrap_or(json!([]));
    let normalized_toc_rows = visual_meta_obj
        .get("normalized_toc_rows")
        .cloned()
        .unwrap_or(json!([]));
    let visual_toc_conflict_count = visual_meta_obj
        .get("visual_toc_conflict_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    let toc_semantic_blocking_reasons = visual_meta_obj
        .get("toc_semantic_blocking_reasons")
        .cloned()
        .unwrap_or(json!([]));
    let toc_semantic_contract_ok = visual_meta_obj
        .get("toc_semantic_contract_ok")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let chapter_title_alignment_ok = visual_meta_obj
        .get("chapter_title_alignment_ok")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let chapter_section_alignment_ok = visual_meta_obj
        .get("chapter_section_alignment_ok")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);

    // 合并 toc_role_summary 与 visual_meta 计算结果
    let mut toc_role_summary_map = toc_role_summary_raw
        .as_object()
        .cloned()
        .unwrap_or_default();
    // 用 max(existing, computed)
    if let Some(Value::Object(visual_roles)) = visual_meta_obj.get("toc_role_summary").cloned() {
        for (role, val) in &visual_roles {
            let existing = toc_role_summary_map
                .get(role)
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            let computed = val.as_i64().unwrap_or(0);
            toc_role_summary_map.insert(role.clone(), json!(std::cmp::max(existing, computed)));
        }
    }

    let _ = page_roles_enum; // unused but preserved for future stricter typing

    let diagnostics = json!({
        "chapter_source_summary": chapter_source_summary,
        "visual_toc_conflict_count": visual_toc_conflict_count,
        "back_matter_start_page": back_matter_start_page,
        "toc_alignment_summary": toc_alignment_summary,
        "toc_semantic_summary": toc_semantic_summary,
        "heading_graph_summary": heading_graph_summary,
        "toc_role_summary": Value::Object(toc_role_summary_map),
        "container_titles": container_titles,
        "endnotes_titles": endnotes_titles,
        "post_body_titles": post_body_titles,
        "back_matter_titles": back_matter_titles,
        "normalized_toc_rows": normalized_toc_rows,
        "chapter_title_alignment_ok": chapter_title_alignment_ok,
        "chapter_section_alignment_ok": chapter_section_alignment_ok,
        "toc_semantic_contract_ok": toc_semantic_contract_ok,
        "toc_semantic_blocking_reasons": toc_semantic_blocking_reasons,
        "total_pages": total_pages,
        "source": chapter_source_summary
            .get("source")
            .and_then(|v| v.as_str())
            .unwrap_or("fallback"),
    });

    ChapterSkeleton {
        chapters,
        heading_candidates: heading_candidates_normalized,
        toc_semantics_section_heads: visual_section_heads_raw,
        fallback_sections,
        diagnostics,
    }
}

// ── Heading candidates normalization helper ─────────────────────

fn normalize_heading_candidates(mut candidates: Vec<HeadingCandidate>) -> Vec<HeadingCandidate> {
    candidates.sort_by_key(|c| (c.page_no, c.text.clone()));
    candidates
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::heading_graph::HeadingGraph;
    use fnm_core::types::PageRole;

    fn pp(page_no: i64, role: PageRole, reason: &str) -> PagePartitionRecord {
        PagePartitionRecord {
            page_no,
            target_pdf_page: page_no,
            page_role: role,
            confidence: 1.0,
            reason: reason.into(),
            section_hint: String::new(),
            has_note_heading: false,
            note_scan_summary: serde_json::Value::Null,
        }
    }

    #[test]
    fn empty_inputs_yield_no_chapter_candidate_meta() {
        let result = build_chapter_skeleton(&[], None, &[], &HeadingGraph::default(), vec![]);
        assert!(result.chapters.is_empty());
        let css = &result.diagnostics["chapter_source_summary"];
        assert_eq!(css["no_chapter_candidate"], json!(true));
        let blocking = result.diagnostics["toc_semantic_blocking_reasons"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        assert!(blocking.iter().any(|v| v == "toc_no_exportable_chapter"));
    }

    #[test]
    fn fallback_path_with_body_pages() {
        let parts = vec![
            pp(1, PageRole::Body, "body"),
            pp(2, PageRole::Body, "body"),
            pp(3, PageRole::Body, "body"),
        ];
        let result = build_chapter_skeleton(&[], None, &parts, &HeadingGraph::default(), vec![]);
        assert_eq!(result.chapters.len(), 1);
        assert_eq!(
            result.diagnostics["chapter_source_summary"]["source"],
            json!("fallback")
        );
    }

    #[test]
    fn meta_contains_required_fields() {
        let result = build_chapter_skeleton(&[], None, &[], &HeadingGraph::default(), vec![]);
        for key in [
            "chapter_source_summary",
            "back_matter_start_page",
            "toc_alignment_summary",
            "toc_semantic_summary",
            "heading_graph_summary",
            "toc_role_summary",
            "container_titles",
            "endnotes_titles",
            "post_body_titles",
            "back_matter_titles",
            "normalized_toc_rows",
            "chapter_title_alignment_ok",
            "chapter_section_alignment_ok",
            "toc_semantic_contract_ok",
            "toc_semantic_blocking_reasons",
        ] {
            assert!(
                result.diagnostics.get(key).is_some(),
                "diagnostics missing key: {key}"
            );
        }
    }
}
