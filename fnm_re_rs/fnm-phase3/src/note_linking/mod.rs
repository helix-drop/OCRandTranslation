//! `note_linking` — Phase 3 模块级编排。
//!
//! ←→ Python: FNM_RE/modules/note_linking.py
//!
//! 这是 1,730 行 Python 的 Rust 翻译，拆为 14 子模块。
//! 编排逻辑对应 Python `build_note_link_table`（行 1430-1658），
//! 严格按 Python 行号顺序逐步翻译。

pub mod anchor_overrides;
pub mod anchor_summary;
pub mod chapter_body_text;
pub mod chapter_contracts;
pub mod chapter_meta;
mod evidence_assemble;
pub mod for_chapter;
mod gate_compute;
pub mod layer_conversion;
pub mod link_overrides;
pub mod link_summary;
pub mod note_item_overrides;
pub mod note_kind_inference;
pub mod ocr_repair;
pub mod phase2_rebuild;

use fnm_core::records::{
    BodyAnchorRecord, ChapterLinkContract, ChapterNoteModeRecord, ChapterRecord, NoteItemRecord,
    NoteLinkRecord, NoteRegionRecord, PagePartitionRecord,
};
use fnm_phase1::input::RawPage;
use fnm_phase2::chapter_split::ChapterLayers;
use serde::Serialize;
use serde_json::Value;
use std::collections::{HashMap, HashSet};

// ── 输出类型 ────────────────────────────────────────────────────

/// Phase 3 模块级产物。
///
/// ←→ Python `NoteLinkTable`（modules/types.py）
#[derive(Debug, Clone, Default, Serialize)]
pub struct NoteLinkTable {
    pub anchors: Vec<BodyAnchorRecord>,
    pub links: Vec<NoteLinkRecord>,
    pub effective_links: Vec<NoteLinkRecord>,
    pub chapter_link_contracts: Vec<ChapterLinkContract>,
    pub anchor_summary: Value,
    pub link_summary: Value,
}

/// ←→ Python `GateReport`（modules/contracts.py）
#[derive(Debug, Clone, Default, Serialize)]
pub struct GateReport {
    pub module: String,
    pub hard: HashMap<String, bool>,
    pub soft: HashMap<String, bool>,
    pub reasons: Vec<String>,
    pub blockers: Vec<String>,
    pub warnings: Vec<String>,
    pub evidence: HashMap<String, Value>,
    pub overrides_used: Vec<Value>,
}

/// ←→ Python `ModuleResult[NoteLinkTable]`
#[derive(Debug, Clone, Default)]
pub struct NoteLinkTableResult {
    pub data: NoteLinkTable,
    pub gate_report: GateReport,
    pub evidence: HashMap<String, Value>,
    pub overrides_used: Vec<Value>,
    pub diagnostics: HashMap<String, Value>,
    /// Phase 2 note 数据（含 override 后的 note_items / note_regions），
    /// 供 caller 组装 Phase3Structure 用的 note 部分。
    pub phase2_build: phase2_rebuild::Phase2BuildOutput,
}

/// 构建 note link table——完整编排。
///
/// ←→ Python `FNM_RE/modules/note_linking.py:build_note_link_table`（行 1430-1658）
///
/// 每一步对应 Python 行号，按铁律 §1 保真翻译，不合并步骤。
#[allow(clippy::too_many_arguments)]
pub fn build_note_link_table(
    chapter_layers: &ChapterLayers,
    pages: &[RawPage],
    overrides: Option<&Value>,
    pdf_path: &str,
    phase1_chapters: &[ChapterRecord],
    phase1_pages: &[PagePartitionRecord],
    // Phase2 权威 chapter_note_modes — 外部调用时直接传递输入层的事实，
    // 不依赖内部 phase2_rebuild 重建的值，确保 review_seed_summary 等内部
    // 诊断计数与上游一致。
    phase2_chapter_note_modes: &[ChapterNoteModeRecord],
    skip_llm_verify: bool,
) -> NoteLinkTableResult {
    // Python 行 1437：_phase2_from_chapter_layers
    // 本函数只返回 note 数据，不输出退化的 Phase1/2 facts。
    let phase2_build = phase2_rebuild::phase2_from_chapter_layers(chapter_layers);
    let book_type = &phase2_build.book_type;

    // Python 行 1438：_group_review_overrides
    let overrides_value = overrides.cloned().unwrap_or(Value::Null);
    let grouped_overrides = fnm_core::review_overrides::group_review_overrides(&overrides_value);
    let note_item_overrides_group = grouped_overrides.get("note_item");
    let anchor_overrides_group = grouped_overrides.get("anchor");
    let link_overrides_group = grouped_overrides.get("link");

    // Python 行 1439-1442：_materialize_note_item_overrides
    let (
        phase2_note_items,
        phase2_note_regions,
        note_item_override_summary,
        note_item_override_logs,
    ) = note_item_overrides::materialize_note_item_overrides(
        &phase2_build.note_items,
        &phase2_build.note_regions,
        note_item_overrides_group,
    );

    // 组装 phase2 with overrides：chapters/pages 来自原始 Phase1 输入，
    // chapter_note_modes 使用 Phase2 权威值而非内部重建值（铁律 §1：Phase N
    // 只能消费 Phase N-1 的事实）。此权威值通过 build_note_links 最终影响
    // review_seed_summary.boundary_review_required_count 等内部诊断度量。
    let phase2_with_overrides = Phase2WithOverrides {
        note_items: phase2_note_items,
        note_regions: phase2_note_regions,
        chapters: phase1_chapters.to_vec(),
        chapter_note_modes: phase2_chapter_note_modes.to_vec(),
        pages: phase1_pages.to_vec(),
    };

    // Python 行 1443-1453：_build_note_item_meta_by_id
    let mut note_item_meta_by_id =
        chapter_meta::build_note_item_meta_by_id(&phase2_with_overrides.note_items);
    for row in &phase2_with_overrides.note_items {
        let nid = row.note_item_id.trim();
        if !nid.is_empty() && !note_item_meta_by_id.contains_key(nid) {
            let meta = chapter_meta::NoteItemMeta {
                projection_mode: "native".to_string(),
                owner_chapter_id: row.chapter_id.trim().to_string(),
                source_marker: row.marker.trim().to_string(),
                normalized_marker: row.marker.trim().to_string(),
            };
            note_item_meta_by_id.insert(nid.to_string(), meta);
        }
    }

    // Python 行 1454-1460：bare_digit_verifier
    // skip_llm_verify=false 时，llm_candidates 将被传给 LLM 验证器裁决。
    // skip_llm_verify=true 时，llm_candidates 按现状保守丢弃。

    // Python 行 1461：build_body_anchors
    let (body_anchors, base_anchor_summary) = crate::body_anchors::build_body_anchors(
        &phase2_with_overrides.chapters,
        &phase2_with_overrides.pages,
        &phase2_with_overrides.note_regions,
        &phase2_with_overrides.note_items,
        pages,
        pdf_path,
        skip_llm_verify,
    );
    // ←→ Python 行 1479：base_anchor_summary 在 materialize 后 merge 进 refresh 结果
    let base_anchor_summary_value =
        serde_json::to_value(&base_anchor_summary).unwrap_or(Value::Null);

    // Python 行 1462：build_note_links
    // 从 chapter_layers 构建每章 body page 集合（用于端末 orphan recovery，
    // 不依赖已有 anchor 的位置——使无 anchor 的章也能做正文搜索恢复）。
    let chapter_body_pages: HashMap<String, HashSet<i64>> = chapter_layers
        .chapter_layers
        .iter()
        .map(|cl| {
            let pages: HashSet<i64> = cl.body_pages.iter().map(|bp| bp.page_no).collect();
            (cl.chapter_id.clone(), pages)
        })
        .collect();
    let mut enhanced_anchors = body_anchors;
    let (note_links, note_link_meta) = crate::note_links::build_note_links(
        &mut enhanced_anchors,
        &phase2_with_overrides.note_items,
        pages,
        1,
        &phase2_with_overrides.chapter_note_modes,
        &phase2_with_overrides.note_regions,
        &chapter_body_pages,
    );
    // 注：build_note_links 返回的 links 包含 synthetic anchor 修改，对应
    // Python 行 1462 把它赋值给 note_links 并在行 1463 传给 repair。
    // Rust 端 `&mut enhanced_anchors` 已就地接收 synthetic anchor 增量。

    // Python 行 1463-1468：_repair_endnote_links_for_contract
    // 直接传 &HashMap<String, NoteItemMeta>——endnote_repair 只读 projection_mode 一个字段，
    // 不必转换成 HashMap<String, HashMap<String, Value>>（省 4*N alloc，N ≈ 600）。
    // 注：book_type 已从 endnote_repair 签名删除——Rust 端用 has_footnote_links 数据驱动。
    let (repaired_links, contract_repair_summary) =
        crate::endnote_repair::repair_endnote_links_for_contract(
            &note_links,
            &mut enhanced_anchors,
            &note_item_meta_by_id,
        );

    // Python 行 1469-1472：_repair_explicit_footnote_anchor_ocr_variants
    let (repaired_anchors, repaired_links, footnote_anchor_repair_summary) =
        ocr_repair::repair_explicit_footnote_anchor_ocr_variants(
            &enhanced_anchors,
            &repaired_links,
            &phase2_with_overrides.note_items,
        );

    // Python 行 1474-1477：_materialize_anchor_overrides
    let chapter_body_text =
        chapter_body_text::chapter_body_text_by_page(&chapter_layers.chapter_layers);
    let (materialized_anchors, anchor_override_summary, anchor_override_logs) =
        anchor_overrides::materialize_anchor_overrides(
            &repaired_anchors,
            anchor_overrides_group,
            Some(&chapter_body_text),
        );

    // Python 行 1479：_refresh_anchor_summary
    let anchor_summary = anchor_summary::refresh_anchor_summary(&materialized_anchors);
    let anchor_summary_value =
        anchor_summary::merge_with_base(&anchor_summary, Some(base_anchor_summary_value));

    // Python 行 1480-1486：_apply_link_overrides
    let (effective_links, override_summary, override_logs) = link_overrides::apply_link_overrides(
        &repaired_links,
        link_overrides_group,
        &phase2_with_overrides.note_items,
        &materialized_anchors,
        &phase2_with_overrides.note_regions,
    );

    // Python 行 1487-1489：_suppress_endnote_residual_orphans
    // 注：book_type 已从 suppress_endnote_residual_orphans 签名删除——数据驱动判断。
    let (effective_links, residual_suppression_summary) =
        crate::endnote_repair::suppress_endnote_residual_orphans(&effective_links);

    // Python 行 1491：合并 override_logs
    let all_override_logs: Vec<Value> = note_item_override_logs
        .iter()
        .chain(anchor_override_logs.iter())
        .chain(override_logs.iter())
        .cloned()
        .collect();

    // Python 行 1493-1497：_chapter_contracts
    let (contracts, contract_evidence) = chapter_contracts::chapter_contracts(
        chapter_layers,
        &effective_links,
        &materialized_anchors,
    );

    // Python 行 1531-1533：link summary + quality gate（必须在 gate 计算前完成）
    let raw_link_summary = link_summary::summarize_links(&repaired_links);
    let effective_link_summary = link_summary::summarize_links(&effective_links);
    let link_quality = link_summary::link_quality_gate(&effective_links, 0.5, 50);

    // Python 行 1498-1582：硬门/软门 + blockers/warnings 装配
    let gate_outputs = gate_compute::compute_gates(gate_compute::GateInputs {
        contracts: &contracts,
        book_type,
        anchor_summary: &anchor_summary,
        effective_link_summary: &effective_link_summary,
        link_quality: &link_quality,
    });
    let gate_compute::GateOutputs {
        hard,
        soft,
        reasons,
        blockers,
        warnings,
        applicable_contract_count,
        contract_v2_failed_chapter_ids: contract_v2_failed_chapters,
        endnote_only_evidence,
    } = gate_outputs;

    // Python 行 1584-1620：evidence 装配（拆到 evidence_assemble.rs）
    let evidence = evidence_assemble::build_evidence(evidence_assemble::EvidenceInputs {
        book_type,
        anchor_summary_value,
        raw_link_summary: &raw_link_summary,
        effective_link_summary: &effective_link_summary,
        link_quality: &link_quality,
        contracts: &contracts,
        contract_evidence: &contract_evidence,
        applicable_contract_count,
        contract_v2_failed_chapter_ids: contract_v2_failed_chapters,
        endnote_only_evidence,
        chapter_layers,
        review_seed: &note_link_meta.review_seed,
    });

    // Python 行 1621-1633：diagnostics 装配（拆到 evidence_assemble.rs）
    let unsupported_override_scopes: Vec<String> = ["page", "chapter", "region", "llm_suggestion"]
        .iter()
        .filter(|s| grouped_overrides.contains_key(**s))
        .map(|s| s.to_string())
        .collect();
    let diagnostics = evidence_assemble::build_diagnostics(evidence_assemble::DiagnosticsInputs {
        override_summary,
        note_item_override_summary,
        anchor_override_summary,
        contract_repair_summary,
        footnote_anchor_repair_summary,
        residual_suppression_summary,
        unsupported_override_scopes,
    });

    // Python 行 1634-1658：gate_report + data + ModuleResult
    let overrides_for_gate = all_override_logs.clone();
    let gate_report = GateReport {
        module: "link".to_string(),
        hard,
        soft,
        reasons,
        blockers,
        warnings,
        evidence: evidence.clone(),
        overrides_used: overrides_for_gate,
    };

    let data = NoteLinkTable {
        anchors: materialized_anchors,
        links: repaired_links,
        effective_links: effective_links.clone(),
        chapter_link_contracts: contracts,
        anchor_summary: evidence
            .get("anchor_summary")
            .cloned()
            .unwrap_or(Value::Null),
        link_summary: evidence_assemble::link_summary_to_value(&effective_link_summary),
    };

    // note_items / note_regions 用 materialize 后版本，与下游 effective_links
    // 一致（CLAUDE.md §12 分类源头唯一：override 已生效）。
    let final_build = phase2_rebuild::Phase2BuildOutput {
        note_regions: phase2_with_overrides.note_regions,
        note_items: phase2_with_overrides.note_items,
        chapter_note_modes: phase2_build.chapter_note_modes,
        note_mode_by_chapter: phase2_build.note_mode_by_chapter,
        book_type: phase2_build.book_type,
    };

    NoteLinkTableResult {
        data,
        gate_report,
        evidence,
        overrides_used: all_override_logs,
        diagnostics,
        phase2_build: final_build,
    }
}

// ── 内部辅助类型 ──────────────────────────────────────────────────

struct Phase2WithOverrides {
    note_items: Vec<NoteItemRecord>,
    note_regions: Vec<NoteRegionRecord>,
    chapters: Vec<fnm_core::records::ChapterRecord>,
    chapter_note_modes: Vec<fnm_core::records::ChapterNoteModeRecord>,
    pages: Vec<PagePartitionRecord>,
}

// 注：link_summary_to_value / link_quality_to_value / book_endnote_stream_summary_to_value
// 已迁入 evidence_assemble.rs，前者为 pub(crate) 供 NoteLinkTable.link_summary 字段调用。
