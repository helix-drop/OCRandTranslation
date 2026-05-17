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
    BodyAnchorRecord, ChapterLinkContract, NoteItemRecord, NoteLinkRecord, NoteRegionRecord,
    PagePartitionRecord, Phase2Structure,
};
use fnm_phase1::input::RawPage;
use fnm_phase2::chapter_split::ChapterLayers;
use serde_json::Value;
use std::collections::HashMap;

// ── 输出类型 ────────────────────────────────────────────────────

/// Phase 3 模块级产物。
///
/// ←→ Python `NoteLinkTable`（modules/types.py）
#[derive(Debug, Clone, Default)]
pub struct NoteLinkTable {
    pub anchors: Vec<BodyAnchorRecord>,
    pub links: Vec<NoteLinkRecord>,
    pub effective_links: Vec<NoteLinkRecord>,
    pub chapter_link_contracts: Vec<ChapterLinkContract>,
    pub anchor_summary: Value,
    pub link_summary: Value,
}

/// ←→ Python `GateReport`（modules/contracts.py）
#[derive(Debug, Clone, Default)]
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
    /// Phase 2 重建产物，供 caller（如 lib.rs）复用以避免重复执行
    /// `phase2_from_chapter_layers`——它在 Biopolitics 370 页规模约 100ms。
    pub phase2: Phase2Structure,
}

/// 构建 note link table——完整编排。
///
/// ←→ Python `FNM_RE/modules/note_linking.py:build_note_link_table`（行 1430-1658）
///
/// 每一步对应 Python 行号，按铁律 §1 保真翻译，不合并步骤。
pub fn build_note_link_table(
    chapter_layers: &ChapterLayers,
    pages: &[RawPage],
    overrides: Option<&Value>,
    pdf_path: &str,
) -> NoteLinkTableResult {
    // Python 行 1437：_phase2_from_chapter_layers
    let (phase2, _chapter_mode_by_id, book_type) =
        phase2_rebuild::phase2_from_chapter_layers(chapter_layers);

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
        &phase2.note_items,
        &phase2.note_regions,
        note_item_overrides_group,
    );

    // 组装 phase2 with overrides
    let phase2_with_overrides = Phase2WithOverrides {
        note_items: phase2_note_items,
        note_regions: phase2_note_regions,
        chapters: phase2.chapters.clone(),
        chapter_note_modes: phase2.chapter_note_modes.clone(),
        pages: phase2.pages.clone(),
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
    // ←→ Python 行 1455-1459: LLM bare_digit 校验需要 vision 客户端。
    // Rust 端初版不支持 skip_llm_verify=false——需要 fnm-llm-repair crate。
    // 当前 pdf_path 仅做占位传参，bare_digit_verifier 永远为 None。
    // 若将来启用 LLM 验证，需新增 bare_digit_verifier 参数并在此处调用。
    let _pdf_path = pdf_path; // 初版：不使用 LLM bare digit verification

    // Python 行 1461：build_body_anchors
    let (body_anchors, base_anchor_summary) = crate::body_anchors::build_body_anchors(
        &phase2_with_overrides.chapters,
        &phase2_with_overrides.pages,
        &phase2_with_overrides.note_regions,
        &phase2_with_overrides.note_items,
        pages,
    );
    // ←→ Python 行 1479：base_anchor_summary 在 materialize 后 merge 进 refresh 结果
    let base_anchor_summary_value =
        serde_json::to_value(&base_anchor_summary).unwrap_or(Value::Null);

    // Python 行 1462：build_note_links
    let mut enhanced_anchors = body_anchors;
    let (note_links, note_link_meta) = crate::note_links::build_note_links(
        &mut enhanced_anchors,
        &phase2_with_overrides.note_items,
        pages,
        1,
        &phase2_with_overrides.chapter_note_modes,
        &phase2_with_overrides.note_regions,
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
        book_type: &book_type,
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
        book_type: &book_type,
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

    // 复用本函数已经构建过的 phase2——避免 caller 再调一次
    // `phase2_from_chapter_layers`（Biopolitics 370 页约 100ms）。
    // note_items / note_regions 用 materialize 后版本，与下游 effective_links
    // 一致（CLAUDE.md §12 分类源头唯一：override 已生效）。
    let final_phase2 = Phase2Structure {
        pages: phase2.pages,
        heading_candidates: phase2.heading_candidates,
        chapters: phase2.chapters,
        section_heads: phase2.section_heads,
        note_regions: phase2_with_overrides.note_regions,
        note_items: phase2_with_overrides.note_items,
        chapter_note_modes: phase2.chapter_note_modes,
        summary: phase2.summary,
    };

    NoteLinkTableResult {
        data,
        gate_report,
        evidence,
        overrides_used: all_override_logs,
        diagnostics,
        phase2: final_phase2,
    }
}

// ── 内部辅助类型 ──────────────────────────────────────────────────

struct Phase2WithOverrides {
    note_items: Vec<NoteItemRecord>,
    note_regions: Vec<NoteRegionRecord>,
    chapters: Vec<fnm_core::records::ChapterRecord>,
    #[allow(dead_code)]
    chapter_note_modes: Vec<fnm_core::records::ChapterNoteModeRecord>,
    pages: Vec<PagePartitionRecord>,
}

// 注：link_summary_to_value / link_quality_to_value / book_endnote_stream_summary_to_value
// 已迁入 evidence_assemble.rs，前者为 pub(crate) 供 NoteLinkTable.link_summary 字段调用。
