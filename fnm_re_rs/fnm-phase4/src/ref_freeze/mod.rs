//! ←→ Python `FNM_RE/modules/ref_freeze.py::build_frozen_units` (L196-678)
//! 引用冻结：注入 NOTE_REF token → body unit 切分 → note unit 生成 → 汇总。

pub mod chapter_index;
pub mod contract;
pub mod hash;
pub mod inject;

use fnm_core::records::{
    BodyAnchorRecord, FrozenRefEntry, FrozenUnit, FrozenUnits, NoteItemRecord, NoteLinkRecord,
    NoteRegionRecord,
};
use fnm_core::refs;
use fnm_phase2::chapter_split::{ChapterLayer, ChapterLayers};
use fnm_phase3::note_linking::NoteLinkTable;
use std::collections::{HashMap, HashSet};

use crate::segments;
use crate::segments::chunking;

/// 顶层编排：构建 frozen units（body + note）和 frozen refs。
///
/// ←→ Python `ref_freeze.py::build_frozen_units` (L196-678)
///
/// 7 个 Phase 严格按照 Python 行号顺序实现。
pub fn build_frozen_units(
    chapter_layers: &ChapterLayers,
    note_link_table: &NoteLinkTable,
    _book_structure_model: Option<&fnm_phase2::chapter_split::structure_model::BookStructureModel>,
    max_body_chars: i64,
    pipeline_run_id: &str,
) -> anyhow::Result<FrozenUnits> {
    let effective_max_chars = if max_body_chars <= 0 {
        6000
    } else {
        max_body_chars
    };

    // ── Phase 1: 索引构建 (L200-245) ─────────────────────────
    let chapter_order = chapter_index::chapter_order_map(chapter_layers);

    let chapter_by_id: HashMap<String, &ChapterLayer> = chapter_layers
        .chapter_layers
        .iter()
        .filter(|c| !c.chapter_id.trim().is_empty())
        .map(|c| (c.chapter_id.clone(), c))
        .collect();

    let valid_chapter_ids: HashSet<String> = chapter_by_id.keys().cloned().collect();

    let region_by_id: HashMap<String, &NoteRegionRecord> = chapter_layers
        .regions
        .iter()
        .filter(|r| !r.region_id.trim().is_empty())
        .map(|r| (r.region_id.clone(), r))
        .collect();

    let anchor_by_id: HashMap<String, &BodyAnchorRecord> = note_link_table
        .anchors
        .iter()
        .filter(|a| !a.anchor_id.trim().is_empty())
        .map(|a| (a.anchor_id.clone(), a))
        .collect();

    // matched_links: effective_links where status == "matched"
    let mut matched_links: Vec<&NoteLinkRecord> = note_link_table
        .effective_links
        .iter()
        .filter(|l| l.status.as_str() == "matched")
        .collect();

    // anchor_to_note_ids → conflict_anchor_ids (multiple note_ids for one anchor)
    let mut anchor_to_note_ids: HashMap<String, HashSet<String>> = HashMap::new();
    for link in &matched_links {
        let anchor_id = link.anchor_id.trim().to_string();
        let note_item_id = link.note_item_id.trim().to_string();
        if anchor_id.is_empty() || note_item_id.is_empty() {
            continue;
        }
        anchor_to_note_ids
            .entry(anchor_id)
            .or_default()
            .insert(note_item_id);
    }
    let conflict_anchor_ids: HashSet<String> = anchor_to_note_ids
        .iter()
        .filter(|(_, note_ids)| note_ids.len() > 1)
        .map(|(aid, _)| aid.clone())
        .collect();

    // 排序 matched_links: (chapter_order, page_no, -char_start, link_id)
    matched_links.sort_by(|a, b| {
        let order_a = chapter_order
            .get(&a.chapter_id)
            .copied()
            .unwrap_or(1_000_000);
        let order_b = chapter_order
            .get(&b.chapter_id)
            .copied()
            .unwrap_or(1_000_000);
        let page_a = anchor_by_id
            .get(&a.anchor_id)
            .map(|an| an.page_no)
            .unwrap_or(0);
        let page_b = anchor_by_id
            .get(&b.anchor_id)
            .map(|an| an.page_no)
            .unwrap_or(0);
        let char_a = anchor_by_id
            .get(&a.anchor_id)
            .map(|an| an.char_start)
            .unwrap_or(0);
        let char_b = anchor_by_id
            .get(&b.anchor_id)
            .map(|an| an.char_start)
            .unwrap_or(0);

        order_a
            .cmp(&order_b)
            .then_with(|| page_a.cmp(&page_b))
            .then_with(|| (-char_a).cmp(&(-char_b)))
            .then_with(|| a.link_id.cmp(&b.link_id))
    });

    // ── Phase 2: chapter body pages 收集 (L247-261) ──────────
    // chapter_body_pages[chapter_id][page_no] = {page_no, text}
    let mut chapter_body_pages: HashMap<String, HashMap<i64, serde_json::Value>> = HashMap::new();
    let mut chapter_body_page_order: HashMap<String, Vec<i64>> = HashMap::new();

    for chapter in &chapter_layers.chapter_layers {
        let chapter_id = chapter.chapter_id.clone();
        let mut page_map: HashMap<i64, serde_json::Value> = HashMap::new();
        let mut page_order: Vec<i64> = Vec::new();
        for page in &chapter.body_pages {
            let page_no = page.page_no;
            if page_no <= 0 {
                continue;
            }
            page_map.insert(
                page_no,
                serde_json::json!({"page_no": page_no, "text": page.text}),
            );
            if !page_order.contains(&page_no) {
                page_order.push(page_no);
            }
        }
        chapter_body_pages.insert(chapter_id.clone(), page_map);
        chapter_body_page_order.insert(chapter_id, page_order);
    }

    // ── Phase 3: inject loop (L263-368) ──────────────────────
    let mut ref_map: Vec<FrozenRefEntry> = Vec::new();
    let mut injected_anchor_ids: HashSet<String> = HashSet::new();
    let mut skipped_reason_counts: HashMap<String, i64> = HashMap::new();

    let skip_reason_to_category = |reason: &str| -> &str {
        match reason {
            "missing_anchor" | "synthetic_anchor" | "token_not_found" => "ceiling_skip",
            "conflict_anchor" | "missing_body_page" => "error_skip",
            "duplicate_anchor" => "policy_skip",
            _ => "error_skip",
        }
    };

    let mut record_skipped =
        |ref_map: &mut Vec<FrozenRefEntry>,
         link: &NoteLinkRecord,
         reason: &str,
         page_no: i64,
         target_ref: &str,
         chapter_body_pages: &mut HashMap<String, HashMap<i64, serde_json::Value>>,
         skipped_reason_counts: &mut HashMap<String, i64>,
         marker: &str| {
            let category = skip_reason_to_category(reason);
            *skipped_reason_counts.entry(reason.to_string()).or_insert(0) += 1;
            ref_map.push(FrozenRefEntry {
                link_id: link.link_id.clone(),
                chapter_id: link.chapter_id.clone(),
                anchor_id: link.anchor_id.clone(),
                note_item_id: link.note_item_id.clone(),
                target_ref: target_ref.to_string(),
                decision: "skipped".to_string(),
                reason: reason.to_string(),
                skip_category: category.to_string(),
                page_no,
            });
            // ceiling_skip / policy_skip → clean marker from body text
            if (category == "ceiling_skip" || category == "policy_skip") && page_no > 0 {
                if let Some(body_pages) = chapter_body_pages.get_mut(&link.chapter_id) {
                    if let Some(body_page) = body_pages.get_mut(&page_no) {
                        if let Some(text) = body_page.get("text").and_then(|v| v.as_str()) {
                            let cleaned = inject::clean_skipped_marker(text, marker);
                            body_page
                                .as_object_mut()
                                .unwrap()
                                .insert("text".to_string(), serde_json::Value::String(cleaned));
                        }
                    }
                }
            }
        };

    for link in &matched_links {
        let chapter_id = &link.chapter_id;
        let anchor_id = link.anchor_id.trim().to_string();
        let note_item_id = link.note_item_id.trim().to_string();
        let marker = &link.marker;
        let anchor = anchor_by_id.get(&anchor_id);
        let target_ref = refs::frozen_note_ref(&note_item_id);

        // skip reason 1: missing_anchor (ceiling_skip)
        let anchor = match anchor {
            Some(a) => a,
            None => {
                record_skipped(
                    &mut ref_map,
                    link,
                    "missing_anchor",
                    0,
                    &target_ref,
                    &mut chapter_body_pages,
                    &mut skipped_reason_counts,
                    marker,
                );
                continue;
            }
        };

        // skip reason 2: synthetic_anchor (ceiling_skip)
        if anchor.synthetic {
            let sm = anchor.source_marker.trim().to_string();
            let nm = anchor.normalized_marker.trim().to_string();
            if sm.is_empty() {
                record_skipped(
                    &mut ref_map,
                    link,
                    "synthetic_anchor",
                    anchor.page_no,
                    &target_ref,
                    &mut chapter_body_pages,
                    &mut skipped_reason_counts,
                    marker,
                );
                continue;
            }
            if sm == nm {
                record_skipped(
                    &mut ref_map,
                    link,
                    "synthetic_anchor",
                    anchor.page_no,
                    &target_ref,
                    &mut chapter_body_pages,
                    &mut skipped_reason_counts,
                    marker,
                );
                continue;
            }
        }

        // skip reason 3: conflict_anchor (error_skip)
        if conflict_anchor_ids.contains(&anchor_id) {
            record_skipped(
                &mut ref_map,
                link,
                "conflict_anchor",
                anchor.page_no,
                &target_ref,
                &mut chapter_body_pages,
                &mut skipped_reason_counts,
                marker,
            );
            continue;
        }

        // skip reason 4: duplicate_anchor (policy_skip)
        if injected_anchor_ids.contains(&anchor_id) {
            record_skipped(
                &mut ref_map,
                link,
                "duplicate_anchor",
                anchor.page_no,
                &target_ref,
                &mut chapter_body_pages,
                &mut skipped_reason_counts,
                marker,
            );
            continue;
        }

        // skip reason 5: missing_body_page (error_skip)
        let body_page = chapter_body_pages
            .get(chapter_id)
            .and_then(|pages| pages.get(&anchor.page_no));
        if body_page.is_none() {
            record_skipped(
                &mut ref_map,
                link,
                "missing_body_page",
                anchor.page_no,
                &target_ref,
                &mut chapter_body_pages,
                &mut skipped_reason_counts,
                marker,
            );
            continue;
        }

        // inject_token_once
        let text = body_page
            .unwrap()
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let (updated_text, injected) =
            inject::inject_token_once(text, anchor, marker, &note_item_id);

        if !injected {
            // skip reason 6: token_not_found (ceiling_skip)
            record_skipped(
                &mut ref_map,
                link,
                "token_not_found",
                anchor.page_no,
                &target_ref,
                &mut chapter_body_pages,
                &mut skipped_reason_counts,
                marker,
            );
            continue;
        }

        // Update body page text
        if let Some(pages) = chapter_body_pages.get_mut(chapter_id) {
            if let Some(page) = pages.get_mut(&anchor.page_no) {
                page.as_object_mut()
                    .unwrap()
                    .insert("text".to_string(), serde_json::Value::String(updated_text));
            }
        }
        injected_anchor_ids.insert(anchor_id.clone());
        ref_map.push(FrozenRefEntry {
            link_id: link.link_id.clone(),
            chapter_id: chapter_id.clone(),
            anchor_id: anchor_id.clone(),
            note_item_id: note_item_id.clone(),
            target_ref: target_ref.clone(),
            decision: "injected".to_string(),
            reason: String::new(),
            skip_category: String::new(),
            page_no: anchor.page_no,
        });
    }

    // ── Phase 4: cleanup_nested_note_refs (L370-376) ─────────
    for (_, pages) in chapter_body_pages.iter_mut() {
        for (_, page_data) in pages.iter_mut() {
            if let Some(text) = page_data.get("text").and_then(|v| v.as_str()) {
                let cleaned = refs::cleanup_nested_note_refs(text);
                if cleaned != text {
                    page_data
                        .as_object_mut()
                        .unwrap()
                        .insert("text".to_string(), serde_json::Value::String(cleaned));
                }
            }
        }
    }

    // ── Phase 5: body unit 构建 (L378-438) ──────────────────
    let mut body_units: Vec<FrozenUnit> = Vec::new();
    let mut chapter_unit_counts: HashMap<String, i64> = HashMap::new();
    let mut empty_body_chapter_count = 0;

    let chapter_bounds: HashMap<String, (i64, i64)> = chapter_layers
        .chapter_layers
        .iter()
        .map(|c| (c.chapter_id.clone(), chapter_index::chapter_page_bounds(c)))
        .collect();

    for chapter in &chapter_layers.chapter_layers {
        let chapter_id = chapter.chapter_id.clone();
        let order = chapter_body_page_order
            .get(&chapter_id)
            .cloned()
            .unwrap_or_default();
        let body_pages = chapter_body_pages.get(&chapter_id);
        let page_order: Vec<i64> = order
            .into_iter()
            .filter(|pno| body_pages.map_or(false, |bp| bp.contains_key(pno)))
            .collect();
        let frozen_body_pages: Vec<serde_json::Value> = page_order
            .iter()
            .filter_map(|pno| body_pages.and_then(|bp| bp.get(pno).cloned()))
            .collect();

        if frozen_body_pages.is_empty() {
            empty_body_chapter_count += 1;
            chapter_unit_counts.insert(chapter_id.clone(), 0);
            continue;
        }

        let obsidian_body_pages: Vec<serde_json::Value> = frozen_body_pages
            .iter()
            .map(|row| {
                let page_no = row.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
                let text = row.get("text").and_then(|v| v.as_str()).unwrap_or("");
                serde_json::json!({
                    "page_no": page_no,
                    "text": refs::replace_frozen_refs(text, fnm_core::refs::EndnoteMode::Standard)
                })
            })
            .collect();

        let page_segments = segments::segment_paragraphs_from_body_pages(
            &frozen_body_pages,
            &obsidian_body_pages,
            &chapter.title,
        );

        let chunks = chunking::chunk_body_page_segments(&page_segments, effective_max_chars);
        chapter_unit_counts.insert(chapter_id.clone(), chunks.len() as i64);

        let (section_start_page, section_end_page) =
            chapter_bounds.get(&chapter_id).copied().unwrap_or((0, 0));

        for (chunk_index, chunk) in chunks.iter().enumerate() {
            let ps = chunk
                .get("page_start")
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            let pe = chunk.get("page_end").and_then(|v| v.as_i64()).unwrap_or(ps);
            let cc = chunk
                .get("char_count")
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            let st = chunk
                .get("source_text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let segs = chunk
                .get("page_segments")
                .cloned()
                .unwrap_or(serde_json::Value::Array(Vec::new()));

            let page_nos: Vec<i64> = {
                let mut nos: HashSet<i64> = segs
                    .as_array()
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|s| s.get("page_no").and_then(|v| v.as_i64()))
                            .filter(|&n| n > 0)
                            .collect()
                    })
                    .unwrap_or_default();
                let mut vec: Vec<i64> = nos.into_iter().collect();
                vec.sort();
                vec
            };

            let (source_hash, plan_hash) = hash::compute_unit_hash(&st, ps, pe, cc, &page_nos);

            body_units.push(FrozenUnit {
                unit_id: format!("body-{}-{:04}", chapter_id, chunk_index + 1),
                kind: "body".to_string(),
                owner_kind: "chapter".to_string(),
                owner_id: chapter_id.clone(),
                section_id: chapter_id.clone(),
                section_title: chapter.title.clone(),
                section_start_page,
                section_end_page,
                note_id: String::new(),
                page_start: ps,
                page_end: pe,
                char_count: cc,
                source_text: st,
                translated_text: String::new(),
                status: "pending".to_string(),
                error_msg: String::new(),
                target_ref: String::new(),
                page_segments: Vec::new(), // JSON → 暂不反序列化
                source_hash,
                segment_plan_hash: plan_hash,
                pipeline_run_id: pipeline_run_id.to_string(),
            });
        }
    }

    // ── Phase 6: note unit 构建 (L440-534) ──────────────────
    let mut note_units: Vec<FrozenUnit> = Vec::new();
    let mut seen_note_unit_keys: HashSet<(String, String)> = HashSet::new();
    let mut unresolved_note_item_ids: Vec<String> = Vec::new();
    let mut unresolved_note_item_id_set: HashSet<String> = HashSet::new();
    let mut chapter_view_note_unit_count = 0;
    let mut owner_fallback_note_unit_count = 0;

    let append_note_unit = |note_units: &mut Vec<FrozenUnit>,
                            item: &NoteItemRecord,
                            resolved_chapter_id: &str,
                            chapter_by_id: &HashMap<String, &ChapterLayer>,
                            chapter_bounds: &HashMap<String, (i64, i64)>,
                            pipeline_run_id: &str,
                            seen: &mut HashSet<(String, String)>| {
        let note_item_id = item.note_item_id.trim().to_string();
        if note_item_id.is_empty() {
            return false;
        }
        let dedupe_key = (resolved_chapter_id.to_string(), note_item_id.clone());
        if seen.contains(&dedupe_key) {
            return false;
        }
        let chapter = chapter_by_id.get(resolved_chapter_id);
        let (section_start_page, section_end_page) = chapter_bounds
            .get(resolved_chapter_id)
            .copied()
            .unwrap_or((item.page_no, item.page_no));
        let n_ps = item.page_no;
        let n_pe = item.page_no;
        let n_cc = item.text.chars().count() as i64;
        let n_st = item.text.clone();
        let (n_src_hash, n_plan_hash) = hash::compute_unit_hash(&n_st, n_ps, n_pe, n_cc, &[n_ps]);

        note_units.push(FrozenUnit {
            unit_id: format!(
                "{}-{}-{}",
                item.note_kind.as_str(),
                resolved_chapter_id,
                note_item_id
            ),
            kind: item.note_kind.as_str().to_string(),
            owner_kind: "note_region".to_string(),
            owner_id: item.region_id.clone(),
            section_id: resolved_chapter_id.to_string(),
            section_title: chapter
                .map_or_else(|| resolved_chapter_id.to_string(), |c| c.title.clone()),
            section_start_page,
            section_end_page,
            note_id: note_item_id.clone(),
            page_start: n_ps,
            page_end: n_pe,
            char_count: n_cc,
            source_text: n_st,
            source_hash: n_src_hash,
            segment_plan_hash: n_plan_hash,
            pipeline_run_id: pipeline_run_id.to_string(),
            translated_text: String::new(),
            status: "pending".to_string(),
            error_msg: String::new(),
            target_ref: refs::frozen_note_ref(&note_item_id),
            page_segments: Vec::new(),
            ..Default::default()
        });
        seen.insert(dedupe_key);
        true
    };

    // Chapter view 路径
    for chapter in &chapter_layers.chapter_layers {
        let chapter_note_items: Vec<&NoteItemRecord> = chapter
            .footnote_items
            .iter()
            .chain(chapter.endnote_items.iter())
            .collect();
        for item in chapter_note_items {
            let (resolved_chapter_id, _source) =
                inject::resolve_note_item_owner(item, &region_by_id, &valid_chapter_ids);
            let note_item_id = item.note_item_id.clone();
            if resolved_chapter_id.is_empty() {
                if !note_item_id.is_empty() && !unresolved_note_item_id_set.contains(&note_item_id)
                {
                    unresolved_note_item_ids.push(note_item_id.clone());
                    unresolved_note_item_id_set.insert(note_item_id);
                }
                continue;
            }
            if append_note_unit(
                &mut note_units,
                item,
                &resolved_chapter_id,
                &chapter_by_id,
                &chapter_bounds,
                pipeline_run_id,
                &mut seen_note_unit_keys,
            ) {
                chapter_view_note_unit_count += 1;
            }
        }
    }

    // Fallback 路径
    let mut ordered_note_items: Vec<&NoteItemRecord> = chapter_layers.note_items.iter().collect();
    ordered_note_items.sort_by(|a, b| {
        a.page_no
            .cmp(&b.page_no)
            .then_with(|| a.note_item_id.cmp(&b.note_item_id))
    });
    for item in ordered_note_items {
        let (resolved_chapter_id, _source) =
            inject::resolve_note_item_owner(item, &region_by_id, &valid_chapter_ids);
        let note_item_id = item.note_item_id.clone();
        if resolved_chapter_id.is_empty() {
            if !note_item_id.is_empty() && !unresolved_note_item_id_set.contains(&note_item_id) {
                unresolved_note_item_ids.push(note_item_id.clone());
                unresolved_note_item_id_set.insert(note_item_id);
            }
            continue;
        }
        if append_note_unit(
            &mut note_units,
            item,
            &resolved_chapter_id,
            &chapter_by_id,
            &chapter_bounds,
            pipeline_run_id,
            &mut seen_note_unit_keys,
        ) {
            owner_fallback_note_unit_count += 1;
        }
    }

    // ── Phase 7: 排序 + summary 构建 (L536-678) ─────────────
    body_units.sort_by(|a, b| {
        let order_a = chapter_order
            .get(&a.section_id)
            .copied()
            .unwrap_or(1_000_000);
        let order_b = chapter_order
            .get(&b.section_id)
            .copied()
            .unwrap_or(1_000_000);
        order_a
            .cmp(&order_b)
            .then_with(|| a.page_start.cmp(&b.page_start))
            .then_with(|| a.unit_id.cmp(&b.unit_id))
    });

    note_units.sort_by(|a, b| {
        let order_a = chapter_order
            .get(&a.section_id)
            .copied()
            .unwrap_or(1_000_000);
        let order_b = chapter_order
            .get(&b.section_id)
            .copied()
            .unwrap_or(1_000_000);
        order_a
            .cmp(&order_b)
            .then_with(|| a.page_start.cmp(&b.page_start))
            .then_with(|| a.unit_id.cmp(&b.unit_id))
    });

    let matched_link_ids: HashSet<String> =
        matched_links.iter().map(|l| l.link_id.clone()).collect();

    let injected_rows: Vec<&FrozenRefEntry> = ref_map
        .iter()
        .filter(|r| r.decision == "injected")
        .collect();
    let skipped_rows: Vec<&FrozenRefEntry> =
        ref_map.iter().filter(|r| r.decision == "skipped").collect();
    let injected_count = injected_rows.len() as i64;
    let skipped_count = (ref_map.len() as i64) - injected_count;
    let synthetic_skipped_count = skipped_reason_counts
        .get("synthetic_anchor")
        .copied()
        .unwrap_or(0);
    let conflict_skipped_count = skipped_reason_counts
        .get("conflict_anchor")
        .copied()
        .unwrap_or(0);

    let mut skipped_note_item_ids: Vec<String> = skipped_rows
        .iter()
        .map(|r| r.note_item_id.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect::<HashSet<_>>()
        .into_iter()
        .collect();
    skipped_note_item_ids.sort();

    let mut contract_issues = contract::unit_contract_issues(&body_units, &note_units);
    for nid in &unresolved_note_item_ids {
        contract_issues.push(format!("unresolved_note_item:{}", nid));
    }

    let error_skip_count = ref_map
        .iter()
        .filter(|r| r.decision == "skipped" && r.skip_category == "error_skip")
        .count() as i64;
    let ceiling_skip_count = ref_map
        .iter()
        .filter(|r| r.decision == "skipped" && r.skip_category == "ceiling_skip")
        .count() as i64;
    let policy_skip_count = ref_map
        .iter()
        .filter(|r| r.decision == "skipped" && r.skip_category == "policy_skip")
        .count() as i64;

    let hard = serde_json::json!({
        "freeze.only_matched_frozen": injected_rows.iter().all(|r| matched_link_ids.contains(&r.link_id)),
        "freeze.no_duplicate_injection": injected_count == injected_rows.iter().map(|r| &r.anchor_id).collect::<HashSet<_>>().len() as i64,
        "freeze.closed_without_error": ref_map.len() == matched_links.len()
            && ref_map.iter().all(|r| r.decision == "injected" || r.decision == "skipped")
            && error_skip_count == 0,
        "freeze.unit_contract_valid": contract_issues.is_empty(),
    });

    let soft = serde_json::json!({
        "freeze.ceiling_skip_warn": ceiling_skip_count == 0,
        "freeze.policy_skip_warn": policy_skip_count == 0,
        "freeze.synthetic_skip_warn": synthetic_skipped_count == 0,
        "freeze.conflict_skip_warn": conflict_skipped_count == 0,
    });

    let freeze_summary = serde_json::json!({
        "matched_link_count": matched_links.len(),
        "injected_count": injected_count,
        "skipped_count": skipped_count,
        "skip_reason_counts": skipped_reason_counts,
        "skipped_note_item_count": skipped_note_item_ids.len(),
        "skipped_note_item_ids_preview": &skipped_note_item_ids[..24.min(skipped_note_item_ids.len())],
        "skipped_ref_preview": skipped_rows.iter().take(24).map(|r| serde_json::json!({
            "link_id": r.link_id,
            "chapter_id": r.chapter_id,
            "anchor_id": r.anchor_id,
            "note_item_id": r.note_item_id,
            "reason": r.reason,
            "skip_category": r.skip_category,
            "page_no": r.page_no,
        })).collect::<Vec<_>>(),
        "skip_category_counts": {
            "ceiling_skip": ceiling_skip_count,
            "policy_skip": policy_skip_count,
            "error_skip": error_skip_count,
        },
        "synthetic_skipped_count": synthetic_skipped_count,
        "conflict_anchor_count": conflict_anchor_ids.len(),
        "body_unit_count": body_units.len(),
        "note_unit_count": note_units.len(),
        "chapter_view_note_unit_count": chapter_view_note_unit_count,
        "owner_fallback_note_unit_count": owner_fallback_note_unit_count,
        "unresolved_note_item_count": unresolved_note_item_ids.len(),
        "unresolved_note_item_ids_preview": &unresolved_note_item_ids[..24.min(unresolved_note_item_ids.len())],
        "chapter_unit_counts": chapter_unit_counts,
        "empty_body_chapter_count": empty_body_chapter_count,
        "max_body_chars": effective_max_chars,
    });

    Ok(FrozenUnits {
        body_units,
        note_units,
        ref_map,
        freeze_summary,
    })
}
