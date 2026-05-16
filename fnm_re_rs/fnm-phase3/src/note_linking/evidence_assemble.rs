//! Phase 3 link 模块的 evidence + diagnostics 装配。
//!
//! ←→ Python `note_linking.py:build_note_link_table` 行 1584-1633
//!
//! 拆出原因：原 `mod.rs` 主编排内 evidence/diagnostics 装配约 100 行，
//! 与上下游解耦（只读输入 + 返回 HashMap），单独成文件减少 mod.rs 长度。

use super::chapter_meta;
use super::link_summary::{LinkSummary, QualityGateResult};
use crate::note_links::ReviewSeedSummary;
use fnm_core::records::ChapterLinkContract;
use fnm_phase2::chapter_split::ChapterLayers;
use serde_json::Value;
use std::collections::HashMap;

/// evidence 装配的所有输入（按 §11 借用为主，owned Value 字段语义上必须 move）。
pub(super) struct EvidenceInputs<'a> {
    pub book_type: &'a str,
    /// `anchor_summary_value` 已是 owned Value（来自 `merge_with_base`），直接 move 入 evidence。
    pub anchor_summary_value: Value,
    pub raw_link_summary: &'a LinkSummary,
    pub effective_link_summary: &'a LinkSummary,
    pub link_quality: &'a QualityGateResult,
    pub contracts: &'a [ChapterLinkContract],
    pub contract_evidence: &'a HashMap<String, Value>,
    pub applicable_contract_count: usize,
    pub contract_v2_failed_chapter_ids: Vec<String>,
    pub endnote_only_evidence: Value,
    pub chapter_layers: &'a ChapterLayers,
    pub review_seed: &'a ReviewSeedSummary,
}

/// 装配 evidence map。
///
/// ←→ Python 行 1584-1620
pub(super) fn build_evidence(inputs: EvidenceInputs<'_>) -> HashMap<String, Value> {
    let EvidenceInputs {
        book_type,
        anchor_summary_value,
        raw_link_summary,
        effective_link_summary,
        link_quality,
        contracts,
        contract_evidence,
        applicable_contract_count,
        contract_v2_failed_chapter_ids,
        endnote_only_evidence,
        chapter_layers,
        review_seed,
    } = inputs;

    let mut evidence: HashMap<String, Value> = HashMap::new();
    evidence.insert(
        "book_type".to_string(),
        Value::String(if book_type.is_empty() {
            "no_notes".to_string()
        } else {
            book_type.to_string()
        }),
    );
    evidence.insert("anchor_summary".to_string(), anchor_summary_value);
    evidence.insert(
        "raw_link_summary".to_string(),
        link_summary_to_value(raw_link_summary),
    );
    evidence.insert(
        "effective_link_summary".to_string(),
        link_summary_to_value(effective_link_summary),
    );
    evidence.insert(
        "link_quality".to_string(),
        link_quality_to_value(link_quality),
    );
    evidence.insert(
        "chapter_contracts".to_string(),
        serde_json::to_value(contract_evidence).unwrap_or(Value::Null),
    );
    evidence.insert(
        "chapter_link_contract_summary".to_string(),
        serde_json::json!({
            "chapter_count": contracts.len(),
            "contract_required_count": applicable_contract_count,
            "failed_chapter_ids": contracts.iter()
                .filter(|c| !(c.first_marker_is_one && c.endnotes_all_matched && c.no_ambiguous_left && c.no_orphan_note && c.endnote_only_no_orphan_anchor))
                .map(|c| c.chapter_id.clone())
                .collect::<Vec<_>>(),
            "contract_v2_failed_chapter_ids": contract_v2_failed_chapter_ids,
            "contract_v2_first_marker_violation_count": contracts.iter().filter(|c| !c.first_marker_is_one).count(),
            "contract_v2_marker_gap_violation_count": contracts.iter().filter(|c| c.has_marker_gap).count(),
            "contract_v2_def_anchor_mismatch_count": contracts.iter().filter(|c| c.def_anchor_mismatch).count(),
        }),
    );
    evidence.insert(
        "book_endnote_stream_summary".to_string(),
        book_endnote_stream_summary_to_value(&chapter_meta::build_book_endnote_stream_summary(
            &chapter_layers.chapter_layers,
        )),
    );
    evidence.insert(
        "endnote_only_no_orphan_anchor".to_string(),
        endnote_only_evidence,
    );
    // ←→ Python 行 1619：review_seed_summary 来自 note_links 内部构建
    evidence.insert(
        "review_seed_summary".to_string(),
        serde_json::json!({
            "boundary_review_required_count": review_seed.boundary_review_required_count,
            "uncertain_anchor_ids": review_seed.uncertain_anchor_ids,
            "orphan_link_ids": review_seed.orphan_link_ids,
            "ambiguous_link_ids": review_seed.ambiguous_link_ids,
            "synthetic_anchor_ids": review_seed.synthetic_anchor_ids,
        }),
    );
    evidence
}

/// diagnostics 装配的所有输入。各 summary 都是 owned，全部 move 入 diagnostics。
pub(super) struct DiagnosticsInputs {
    pub override_summary: Value,
    pub note_item_override_summary: Value,
    pub anchor_override_summary: Value,
    pub contract_repair_summary: HashMap<String, i64>,
    pub footnote_anchor_repair_summary: HashMap<String, i64>,
    pub residual_suppression_summary: HashMap<String, i64>,
    pub unsupported_override_scopes: Vec<String>,
}

/// 装配 diagnostics map。
///
/// ←→ Python 行 1621-1633
pub(super) fn build_diagnostics(inputs: DiagnosticsInputs) -> HashMap<String, Value> {
    let DiagnosticsInputs {
        override_summary,
        note_item_override_summary,
        anchor_override_summary,
        contract_repair_summary,
        footnote_anchor_repair_summary,
        residual_suppression_summary,
        unsupported_override_scopes,
    } = inputs;

    let mut diagnostics: HashMap<String, Value> = HashMap::new();
    diagnostics.insert("override_summary".to_string(), override_summary);
    diagnostics.insert(
        "note_item_override_summary".to_string(),
        note_item_override_summary,
    );
    diagnostics.insert(
        "anchor_override_summary".to_string(),
        anchor_override_summary,
    );
    diagnostics.insert(
        "contract_repair_summary".to_string(),
        serde_json::to_value(&contract_repair_summary).unwrap_or(Value::Null),
    );
    diagnostics.insert(
        "footnote_anchor_repair_summary".to_string(),
        serde_json::to_value(&footnote_anchor_repair_summary).unwrap_or(Value::Null),
    );
    diagnostics.insert(
        "residual_suppression_summary".to_string(),
        serde_json::to_value(&residual_suppression_summary).unwrap_or(Value::Null),
    );
    diagnostics.insert(
        "unsupported_override_scopes".to_string(),
        Value::Array(
            unsupported_override_scopes
                .into_iter()
                .map(Value::String)
                .collect(),
        ),
    );
    diagnostics
}

// ── 内部 helpers（原 mod.rs 私有 helper，迁入这里使用更紧密） ─────

fn link_summary_to_value(summary: &LinkSummary) -> Value {
    serde_json::json!({
        "matched": summary.matched,
        "footnote_orphan_note": summary.footnote_orphan_note,
        "footnote_orphan_anchor": summary.footnote_orphan_anchor,
        "endnote_orphan_note": summary.endnote_orphan_note,
        "endnote_orphan_anchor": summary.endnote_orphan_anchor,
        "ambiguous": summary.ambiguous,
        "ignored": summary.ignored,
        "fallback_count": summary.fallback_count,
        "repair_count": summary.repair_count,
        "fallback_matched_count": summary.fallback_matched_count,
        "fallback_match_ratio": summary.fallback_match_ratio,
    })
}

fn link_quality_to_value(q: &QualityGateResult) -> Value {
    serde_json::json!({
        "quality_ok": q.quality_ok,
        "fallback_match_ratio": q.fallback_match_ratio,
        "orphan_anchor_total": q.orphan_anchor_total,
        "footnote_orphan_anchor_total": q.footnote_orphan_anchor_total,
        "endnote_orphan_anchor_total": q.endnote_orphan_anchor_total,
    })
}

fn book_endnote_stream_summary_to_value(s: &chapter_meta::BookEndnoteStreamSummary) -> Value {
    let chapters: Vec<Value> = s
        .chapters
        .iter()
        .map(|c| {
            let pm: HashMap<String, i64> = c
                .projection_mode_counts
                .iter()
                .map(|(k, v)| (k.clone(), *v as i64))
                .collect();
            serde_json::json!({
                "chapter_id": c.chapter_id,
                "item_count": c.item_count,
                "projection_mode_counts": pm,
            })
        })
        .collect();
    serde_json::json!({
        "chapter_count": s.chapter_count,
        "chapters_with_endnote_stream": s.chapters_with_endnote_stream,
        "high_concentration_chapter_ids": s.high_concentration_chapter_ids,
        "chapters": chapters,
    })
}

// 提供给 mod.rs 调用的公共 helper（用于 NoteLinkTable.link_summary 字段）。
pub(crate) fn link_summary_to_value_pub(summary: &LinkSummary) -> Value {
    link_summary_to_value(summary)
}
