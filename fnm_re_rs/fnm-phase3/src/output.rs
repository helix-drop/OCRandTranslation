//! Phase 3 输出类型契约。
//!
//! ←→ Python: FNM_RE/models.py Phase3Structure / Phase3Summary
//!
//! 注意：BodyAnchorRecord / NoteLinkRecord / ChapterAnchorAlignmentRecord /
//! ParagraphFootnoteRecord / ChapterEndnoteRecord / Phase3Structure / Phase3Summary
//! 全部在 fnm-core 已定义，此处仅做薄包装或重新导出。

use fnm_core::records::Phase3Structure;
use std::collections::HashMap;

/// Phase 3 模块级输出。
///
/// 与 Python `build_note_link_table` 返回的 `ModuleResult` 对应。
/// ←→ Python `FNM_RE/modules/contracts.py:ModuleResult[NoteLinkTable]`
pub struct Phase3Output {
    pub structure: Phase3Structure,
    /// ←→ Python `ModuleResult.data`（NoteLinkTable 层）
    pub note_link_table: crate::note_linking::NoteLinkTable,
    /// ←→ Python `ModuleResult.evidence`
    pub evidence: HashMap<String, serde_json::Value>,
    /// ←→ Python `ModuleResult.diagnostics`
    pub diagnostics: HashMap<String, serde_json::Value>,
    /// ←→ Python `ModuleResult.gate_report`
    pub gate_report: crate::note_linking::GateReport,
}
