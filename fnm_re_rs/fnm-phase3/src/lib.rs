//! `fnm-phase3` — FNM_RE Phase 3: body anchor 检测 + note link 匹配。
//!
//! ←→ Python: FNM_RE/stages/body_anchors.py, FNM_RE/stages/note_links.py,
//!            FNM_RE/stages/endnote_links.py, FNM_RE/stages/footnote_links.py,
//!            FNM_RE/stages/chapter_anchor_alignment.py,
//!            FNM_RE/stages/paragraph_footnotes.py, FNM_RE/stages/paragraph_endnotes.py,
//!            FNM_RE/stages/_link_utils.py, FNM_RE/modules/note_linking.py

pub mod body_anchors;
pub mod chapter_anchor_alignment;
pub mod endnote_links;
pub mod endnote_repair;
pub mod footnote_links;
pub mod input;
pub mod link_utils;
pub mod note_linking;
pub mod note_links;
pub mod output;
pub mod paragraph_endnotes;
pub mod paragraph_footnotes;

use fnm_core::{
    db::{Phase3Products, Repository},
    records::{NoteLinkRecord, Phase3Structure},
};
use fnm_phase2::chapter_split::build_chapter_layers;
use input::Phase3Input;
use output::Phase3Output;
use serde_json::Value;

/// 全局重编号 link_id，确保 (doc_id, link_id) 唯一约束满足。
///
/// 上游 `link_utils::link_new_link` 接受 `serial: usize` 但 caller 各自从 1 开始计数，
/// 跨章/跨 stage 时 ID 会重叠（注释明确 "由调用方重新编号"）。本函数在 phase3 出口
/// 统一按出现顺序重新分配 link-NNNNN。
fn renumber_link_ids(mut links: Vec<NoteLinkRecord>) -> Vec<NoteLinkRecord> {
    for (idx, link) in links.iter_mut().enumerate() {
        link.link_id = format!("link-{:05}", idx + 1);
    }
    links
}

/// 构建 Phase 3 结构。
///
/// ←→ Python `build_phase3_structure`（pipeline.py 调 modules/note_linking.py）
///
/// 核心流程：
/// 1. 从输入重建 ChapterLayers → Phase2Structure
/// 2. 调用 `build_note_link_table` 完成完整编排
/// 3. 将 NoteLinkTable 产物映射到 Phase3Structure
/// 4. 按章构建 paragraph_footnotes / paragraph_endnotes / chapter_anchor_alignment
pub fn build_phase3_structure(input: Phase3Input<'_>) -> anyhow::Result<Phase3Output> {
    // ←→ Phase3Config::skip_llm_verify：初版强制 true。
    // Rust 端无 vision LLM 客户端（属 Phase 3.5 fnm-llm-repair crate）。
    if !input.config.skip_llm_verify {
        anyhow::bail!(
            "Phase3Config::skip_llm_verify=false 暂不支持——\
             需 fnm-llm-repair crate（Phase 3.5）"
        );
    }

    // 1. 从输入重建 ChapterLayers
    let chapter_layers = build_chapter_layers(
        input.phase1_chapters,
        input.phase2_note_regions,
        input.phase2_note_items,
        input.phase1_pages,
        input.raw_pages,
    );

    // 2. 调用核心编排——返回的 result.phase2_build 已包含 materialize 后的 note 数据。
    // 传入 Phase2 权威 chapter_note_modes 确保内部诊断消费上游事实而非重建值。
    let result = note_linking::build_note_link_table(
        &chapter_layers,
        input.raw_pages,
        input.overrides,
        input.pdf_path.unwrap_or(""),
        input.phase1_chapters,
        input.phase1_pages,
        input.phase2_chapter_note_modes,
    );

    // 3. 按章产物：paragraph_footnotes / paragraph_endnotes / chapter_anchor_alignment
    // 数据来源从 raw markdown 改为 Phase2 NoteItem（铁律 §4：下游不重新构造上游事实）。
    let (paragraph_footnotes, footnote_summary) = paragraph_footnotes::build_paragraph_footnotes(
        input.phase1_chapters,
        input.phase1_pages,
        input.raw_pages,
        &result.phase2_build.note_items,
        "",
    );
    let (paragraph_endnotes, endnote_summary) = paragraph_endnotes::build_paragraph_endnotes(
        input.phase1_chapters,
        input.phase1_pages,
        input.raw_pages,
        &result.phase2_build.note_items,
        "",
    );
    let (chapter_anchor_alignments, alignment_summary) =
        chapter_anchor_alignment::dp_alignment::build_chapter_anchor_alignment(
            &result.data.anchors,
            &paragraph_endnotes,
            "",
        );

    // 5a. 装配合计摘要（←→ Python: 各类 summary 字典）
    let footnote_summary_value = serde_json::json!({
        "total_footnote_items": footnote_summary.total_footnote_items,
        "anchor_matched": footnote_summary.anchor_matched,
        "page_tail": footnote_summary.page_tail,
        "cross_page_tail": footnote_summary.cross_page_tail,
        "chapter_count": footnote_summary.chapter_count,
        "chapter_stats": footnote_summary.chapter_stats,
    });
    let endnote_summary_value = serde_json::json!({
        "total_endnote_items": endnote_summary.total_endnote_items,
        "chapter_count": endnote_summary.chapter_count,
        "reconstructed_count": endnote_summary.reconstructed_count,
        "chapter_stats": endnote_summary.chapter_stats,
    });
    let alignment_summary_value = serde_json::to_value(&alignment_summary).unwrap_or(Value::Null);

    // 5b. 组装 Phase3Structure：Phase1/2 事实来自原始输入，Phase3 产物来自 result
    let structure = Phase3Structure {
        pages: input.phase1_pages.to_vec(),
        heading_candidates: input.phase1_heading_candidates.to_vec(),
        chapters: input.phase1_chapters.to_vec(),
        section_heads: input.phase1_section_heads.to_vec(),
        note_regions: result.phase2_build.note_regions,
        note_items: result.phase2_build.note_items,
        // 透传 Phase2 权威的 chapter_note_modes，不依赖内部重建
        //（铁律 §1：Phase N 只能消费 Phase N-1 的事实，不能重建）。
        chapter_note_modes: input.phase2_chapter_note_modes.to_vec(),
        body_anchors: result.data.anchors.clone(),
        note_links: renumber_link_ids(result.data.effective_links.clone()),
        paragraph_footnotes,
        paragraph_endnotes,
        chapter_anchor_alignments,
        summary: fnm_core::records::Phase3Summary {
            body_anchor_summary: result
                .evidence
                .get("anchor_summary")
                .cloned()
                .unwrap_or(Value::Null),
            note_link_summary: result
                .evidence
                .get("effective_link_summary")
                .cloned()
                .unwrap_or(Value::Null),
            review_seed_summary: result
                .evidence
                .get("review_seed_summary")
                .cloned()
                .unwrap_or(Value::Null),
            paragraph_footnote_summary: footnote_summary_value,
            paragraph_endnote_summary: endnote_summary_value,
            chapter_anchor_alignment_summary: alignment_summary_value,
            ..fnm_core::records::Phase3Summary::default()
        },
    };

    Ok(Phase3Output {
        structure,
        note_link_table: result.data,
        evidence: result.evidence,
        diagnostics: result.diagnostics,
        gate_report: result.gate_report,
    })
}

/// 将 Phase 3 产物持久化到数据库。
///
/// ←→ Python `persist_phase3`（phase_runner.py 行 442-500）
///
/// 写入策略：
/// - 2 批写入：`replace_fnm_phase3_products`（body_anchors + note_links）
/// - 3 按章 scope 写入：
///   - `upsert_fnm_chapter_anchor_alignment`
///   - `replace_fnm_paragraph_footnotes`
///   - `replace_fnm_chapter_endnotes`
pub fn persist_phase3(
    repo: &dyn Repository,
    doc_id: &str,
    output: &Phase3Output,
) -> anyhow::Result<()> {
    // Batch 1: body_anchors + note_links (Phase3Products)
    let payload = Phase3Products {
        body_anchors: output.structure.body_anchors.clone(),
        note_links: output.structure.note_links.clone(),
    };
    repo.replace_fnm_phase3_products(doc_id, &payload)?;

    // Per-chapter scope: chapter_anchor_alignment
    for alignment in &output.structure.chapter_anchor_alignments {
        let mismatch = alignment
            .mismatch
            .as_ref()
            .filter(|v| !v.is_null())
            .cloned();
        repo.upsert_fnm_chapter_anchor_alignment(
            doc_id,
            &alignment.chapter_id,
            &alignment.alignment_status,
            alignment.body_anchor_count,
            alignment.endnote_count,
            mismatch,
        )?;
    }

    // Per-chapter scope: paragraph_footnotes
    use std::collections::HashMap;
    let mut footnotes_by_chapter: HashMap<&str, Vec<fnm_core::records::ParagraphFootnoteRecord>> =
        HashMap::new();
    for pf in &output.structure.paragraph_footnotes {
        footnotes_by_chapter
            .entry(&pf.chapter_id)
            .or_default()
            .push(pf.clone());
    }
    for (chapter_id, footnotes) in footnotes_by_chapter {
        repo.replace_fnm_paragraph_footnotes(doc_id, chapter_id, &footnotes)?;
    }

    // Per-chapter scope: paragraph_endnotes
    let mut endnotes_by_chapter: HashMap<&str, Vec<fnm_core::records::ChapterEndnoteRecord>> =
        HashMap::new();
    for ce in &output.structure.paragraph_endnotes {
        endnotes_by_chapter
            .entry(&ce.chapter_id)
            .or_default()
            .push(ce.clone());
    }
    for (chapter_id, endnotes) in endnotes_by_chapter {
        repo.replace_fnm_chapter_endnotes(doc_id, chapter_id, &endnotes)?;
    }

    Ok(())
}
