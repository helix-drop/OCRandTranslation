//! 尾注 link 修复：OCR repair、fallback 匹配、endnote_only 孤儿配对、残存孤儿 suppress。
//!
//! ←→ Python: FNM_RE/modules/endnote_repair.py
//!
//! # 子模块划分
//!
//! - [`contract_repair`]: `repair_endnote_links_for_contract` 主体（4 段顺序流程）
//! - [`mod@self`]: 入口 + `project_priority` 工具 + `suppress_endnote_residual_orphans`
//!
//! 翻译的函数：
//! - `project_priority` ←→ Python `project_priority`
//! - `repair_endnote_links_for_contract` ←→ Python `repair_endnote_links_for_contract`
//! - `suppress_endnote_residual_orphans` ←→ Python `suppress_endnote_residual_orphans`

pub mod contract_repair;

pub use contract_repair::repair_endnote_links_for_contract;

use fnm_core::records::NoteLinkRecord;
use fnm_core::types::{LinkResolver, LinkStatus, NoteKind};
use std::collections::HashMap;

/// note_item projection_mode → 排序优先级。book_projected 优先保留。
///
/// ←→ Python `project_priority`
pub fn project_priority(projection_mode: &str) -> i32 {
    match projection_mode.trim().to_lowercase().as_str() {
        "book_projected" => 3,
        "book_marker_projected" => 2,
        "book_fallback_projected" => 1,
        _ => 0,
    }
}

/// 抑制尾注残存孤儿。
///
/// ←→ Python `suppress_endnote_residual_orphans`
///
/// 数据驱动：存在 footnote link 时不抑制（非纯尾注书）。
/// 仅对纯尾注书，将 orphan_note / orphan_anchor 标为 ignored。
///
/// 注：Python 端接 `book_type` 参数但内部未使用，由 `has_footnote` 判断决定
/// 是否抑制。Rust 端删除该参数避免死参。
pub fn suppress_endnote_residual_orphans(
    links: &[NoteLinkRecord],
) -> (Vec<NoteLinkRecord>, HashMap<String, i64>) {
    let has_footnote = links.iter().any(|row| row.note_kind == NoteKind::Footnote);
    if has_footnote {
        let mut summary = HashMap::new();
        summary.insert("suppressed_orphan_note_count".to_string(), 0);
        summary.insert("suppressed_orphan_anchor_count".to_string(), 0);
        return (links.to_vec(), summary);
    }
    let mut updated: Vec<NoteLinkRecord> = links.to_vec();
    let mut suppressed_orphan_note_count: i64 = 0;
    let mut suppressed_orphan_anchor_count: i64 = 0;
    for link in updated.iter_mut() {
        if link.note_kind != NoteKind::Endnote {
            continue;
        }
        match link.status {
            LinkStatus::OrphanNote => suppressed_orphan_note_count += 1,
            LinkStatus::OrphanAnchor => suppressed_orphan_anchor_count += 1,
            _ => continue,
        }
        link.status = LinkStatus::Ignored;
        link.resolver = LinkResolver::Fallback;
        link.confidence = 1.0;
    }
    let mut summary = HashMap::new();
    summary.insert(
        "suppressed_orphan_note_count".to_string(),
        suppressed_orphan_note_count,
    );
    summary.insert(
        "suppressed_orphan_anchor_count".to_string(),
        suppressed_orphan_anchor_count,
    );
    (updated, summary)
}

#[cfg(test)]
mod tests;
