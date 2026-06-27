//! Phase 3 link 模块的硬门 / 软门 / blocker / warning 计算。
//!
//! ←→ Python `note_linking.py:build_note_link_table` 行 1498-1582
//!
//! 拆出原因：原 `mod.rs:build_note_link_table` 内的硬门软门段约 110 行，
//! 与上下文 mutable state 解耦清晰（只依赖只读 contracts/summaries），
//! 单独成文件提升可读性，满足 §4 < 400。

use super::anchor_summary::AnchorSummary;
use super::link_summary::{LinkSummary, QualityGateResult};
use fnm_core::records::ChapterLinkContract;
use serde_json::Value;
use std::collections::HashMap;

/// 计算硬门/软门所需的所有只读输入。
pub(super) struct GateInputs<'a> {
    pub contracts: &'a [ChapterLinkContract],
    pub book_type: &'a str,
    pub anchor_summary: &'a AnchorSummary,
    pub effective_link_summary: &'a LinkSummary,
    pub link_quality: &'a QualityGateResult,
}

/// 硬门/软门 + blockers/warnings 装配输出 + chapter_link_contract_summary 所需的中间值。
pub(super) struct GateOutputs {
    pub hard: HashMap<String, bool>,
    pub soft: HashMap<String, bool>,
    pub reasons: Vec<String>,
    pub blockers: Vec<String>,
    pub warnings: Vec<String>,
    pub applicable_contract_count: usize,
    pub contract_v2_failed_chapter_ids: Vec<String>,
    pub endnote_only_evidence: Value,
}

/// 计算 link 模块的 hard/soft gate 与 blocker/warning 列表。
///
/// ←→ Python 行 1498-1582
pub(super) fn compute_gates(inputs: GateInputs<'_>) -> GateOutputs {
    let GateInputs {
        contracts,
        book_type,
        anchor_summary,
        effective_link_summary,
        link_quality,
    } = inputs;

    let applicable_contracts: Vec<&ChapterLinkContract> = contracts
        .iter()
        .filter(|c| c.requires_endnote_contract)
        .collect();
    let hard_first_marker_is_one = applicable_contracts.iter().all(|c| c.first_marker_is_one);
    let hard_endnotes_all_matched = applicable_contracts.iter().all(|c| c.endnotes_all_matched);
    let hard_no_ambiguous_left = applicable_contracts.iter().all(|c| c.no_ambiguous_left);
    let hard_no_orphan_note = applicable_contracts.iter().all(|c| c.no_orphan_note);
    let is_book_endnotes = book_type == "endnote_only";
    let hard_endnote_only_no_orphan_anchor = if is_book_endnotes {
        applicable_contracts
            .iter()
            .all(|c| c.endnote_only_no_orphan_anchor)
    } else {
        true
    };

    // ←→ Python 行 1519-1529：工单 #3 契约 v2
    let contract_v2_first_marker_is_one =
        applicable_contracts.iter().all(|c| c.first_marker_is_one);
    let contract_v2_no_marker_gap = applicable_contracts.iter().all(|c| !c.has_marker_gap);
    let contract_v2_def_anchor_aligned =
        applicable_contracts.iter().all(|c| !c.def_anchor_mismatch);
    let contract_v2_failed_chapter_ids: Vec<String> = applicable_contracts
        .iter()
        .filter(|c| !c.first_marker_is_one || c.has_marker_gap || c.def_anchor_mismatch)
        .map(|c| c.chapter_id.clone())
        .collect();

    let soft_footnote_orphan_anchor_warn = effective_link_summary.footnote_orphan_anchor == 0;
    let soft_synthetic_anchor_warn = anchor_summary.synthetic_count == 0;

    // ←→ Python 行 1537-1582：装配 hard / soft
    let mut hard: HashMap<String, bool> = HashMap::new();
    hard.insert(
        "link.first_marker_is_one".to_string(),
        hard_first_marker_is_one,
    );
    hard.insert(
        "link.endnotes_all_matched".to_string(),
        hard_endnotes_all_matched,
    );
    hard.insert("link.no_ambiguous_left".to_string(), hard_no_ambiguous_left);
    hard.insert("link.no_orphan_note".to_string(), hard_no_orphan_note);
    hard.insert(
        "link.endnote_only_no_orphan_anchor".to_string(),
        hard_endnote_only_no_orphan_anchor,
    );
    hard.insert(
        "link.contract_first_marker_is_one".to_string(),
        contract_v2_first_marker_is_one,
    );
    hard.insert("link.no_marker_gap".to_string(), contract_v2_no_marker_gap);
    hard.insert(
        "link.def_anchor_aligned".to_string(),
        contract_v2_def_anchor_aligned,
    );
    hard.insert("link.quality_ok".to_string(), link_quality.quality_ok);

    let mut soft: HashMap<String, bool> = HashMap::new();
    soft.insert(
        "link.footnote_orphan_anchor_warn".to_string(),
        soft_footnote_orphan_anchor_warn,
    );
    soft.insert(
        "link.synthetic_anchor_warn".to_string(),
        soft_synthetic_anchor_warn,
    );

    let mut reasons: Vec<String> = Vec::new();
    let mut blockers: Vec<String> = Vec::new();
    let mut warnings: Vec<String> = Vec::new();

    let mut add_gate = |code: &str, blocker: bool| {
        reasons.push(code.to_string());
        if blocker {
            blockers.push(code.to_string());
        } else {
            warnings.push(code.to_string());
        }
    };

    if !hard_first_marker_is_one {
        add_gate("link_first_marker_not_one", !is_book_endnotes);
    }
    if !hard_endnotes_all_matched {
        add_gate("link_endnote_not_all_matched", true);
    }
    if !hard_no_ambiguous_left {
        add_gate("link_ambiguous_remaining", true);
    }
    if !hard_no_orphan_note {
        add_gate("link_orphan_note_remaining", true);
    }
    if !hard_endnote_only_no_orphan_anchor {
        add_gate("link_endnote_only_orphan_anchor_remaining", true);
    }
    if !contract_v2_first_marker_is_one {
        add_gate("contract_first_marker_not_one", !is_book_endnotes);
    }
    if !contract_v2_no_marker_gap {
        add_gate("contract_marker_gap", !is_book_endnotes);
    }
    if !contract_v2_def_anchor_aligned {
        add_gate("contract_def_anchor_mismatch", true);
    }
    if !link_quality.quality_ok {
        add_gate("link_quality_low", true);
    }

    let endnote_only_evidence = if is_book_endnotes {
        serde_json::json!({
            "status": "checked",
            "book_type": book_type,
            "applicable_contract_count": applicable_contracts.len(),
        })
    } else {
        serde_json::json!({
            "status": "not_applicable",
            "reason": format!("book_type={}", book_type),
        })
    };

    GateOutputs {
        hard,
        soft,
        reasons,
        blockers,
        warnings,
        applicable_contract_count: applicable_contracts.len(),
        contract_v2_failed_chapter_ids,
        endnote_only_evidence,
    }
}
