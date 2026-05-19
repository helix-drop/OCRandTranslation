//! Phase 4 输出类型契约。
//!
//! ←→ Python Phase4Output / Phase4Products

use fnm_core::records::{
    FrozenRefEntry, FrozenUnits, StructureReviewRecord, TranslationUnitRecord,
};
use serde_json::Value;

/// Phase 4 完整输出。
///
/// 包含 ref_freeze + units + reviews 的所有产物。
pub struct Phase4Output {
    /// frozen units（已注入 {{NOTE_REF:N}} token）
    pub frozen_units: FrozenUnits,
    /// frozen ref 条目（含 decision: injected/skipped + reason）
    pub frozen_refs: Vec<FrozenRefEntry>,
    /// 翻译单元（body chunk / footnote / endnote 三类）
    pub translation_units: Vec<TranslationUnitRecord>,
    /// 结构复核记录（9 类 review_type）
    pub structure_reviews: Vec<StructureReviewRecord>,
    /// 汇总信息（freeze_summary + units_summary + reviews_summary）
    pub summary: Value,
    /// 诊断信息
    pub diagnostics: Value,
}

impl Phase4Output {
    /// 转换为 Phase4Products（用于 DB 持久化）。
    pub fn to_products(&self) -> fnm_core::db::Phase4Products {
        fnm_core::db::Phase4Products {
            translation_units: self.translation_units.clone(),
            structure_reviews: self.structure_reviews.clone(),
        }
    }
}
