//! ←→ Python `FNM_RE/stages/units.py`（~868 行）
//!
//! 翻译单元构建：从 FrozenUnits 直接映射为 TranslationUnitRecord。
//!
//! 本模块是 FrozenUnits 的纯派生层，不再读取 raw_pages 或二次注入引用。
//!
//! # 子模块
//!
//! - `page_split` — 7 个文本切分 helper（P4.6）
//! - `endnote_lookup` — endnote 区起始页映射（P4.7，保留为阶段6使用）
//! - `body_pages` — 章级 body pages 结构化（保留为阶段6使用）
//! - `ref_inject` — ref 物化 + 注入（保留为阶段6使用）

pub mod endnote_lookup;
pub mod page_split;

use fnm_core::records::{FrozenUnit, FrozenUnits, TranslationUnitRecord};
use std::collections::HashMap;

/// ←→ Python `build_translation_units` (units.py:690-868)
///
/// 从 FrozenUnits 映射为 TranslationUnitRecord 列表。
///
/// # 参数
///
/// - `frozen_units` — ref_freeze 产出的冻结单元（含 body + note）
///
/// # 返回
///
/// `(Vec<TranslationUnitRecord>, serde_json::Value)` — 翻译单元列表 + summary
pub fn build_translation_units(
    frozen_units: &FrozenUnits,
) -> (Vec<TranslationUnitRecord>, serde_json::Value) {
    let mut units: Vec<TranslationUnitRecord> = Vec::new();
    let mut body_unit_ids: Vec<String> = Vec::new();

    // 1. Body units: 从 frozen_units.body_units 一对一映射
    for fu in &frozen_units.body_units {
        body_unit_ids.push(fu.unit_id.clone());
        units.push(frozen_unit_to_translation_unit(fu));
    }

    // 2. Note units: 从 frozen_units.note_units 一对一映射
    for fu in &frozen_units.note_units {
        units.push(frozen_unit_to_translation_unit(fu));
    }

    // 3. 排序: 保持 frozen units 的既有顺序
    //    (已按 chapter_order → page_start → unit_id 排序)
    //    在此再做一次等价排序确保一致性
    let section_order: HashMap<String, usize> = frozen_units
        .body_units
        .iter()
        .enumerate()
        .map(|(i, u)| (u.section_id.clone(), i))
        .collect();

    units.sort_by(|a, b| {
        let order_a = section_order
            .get(a.section_id.trim())
            .copied()
            .unwrap_or(1_000_000);
        let order_b = section_order
            .get(b.section_id.trim())
            .copied()
            .unwrap_or(1_000_000);
        let body_kind_a = if a.kind == "body" { 0 } else { 1 };
        let body_kind_b = if b.kind == "body" { 0 } else { 1 };
        order_a
            .cmp(&order_b)
            .then(body_kind_a.cmp(&body_kind_b))
            .then(a.page_start.cmp(&b.page_start))
            .then(a.unit_id.cmp(&b.unit_id))
    });

    // 4. 构建 summary
    let body_unit_count = units.iter().filter(|u| u.kind == "body").count();
    let note_unit_count = units.len() - body_unit_count;

    let mut chapter_unit_counts: HashMap<String, usize> = HashMap::new();
    for u in &units {
        if u.kind == "body" {
            *chapter_unit_counts.entry(u.section_id.clone()).or_default() += 1;
        }
    }

    let summary = serde_json::json!({
        "unit_planning_summary": {
            "body_unit_count": body_unit_count,
            "note_unit_count": note_unit_count,
            "chapter_unit_counts": chapter_unit_counts,
            "frozen_body_unit_count": frozen_units.body_units.len(),
            "frozen_note_unit_count": frozen_units.note_units.len(),
        },
    });

    (units, summary)
}

/// 将 FrozenUnit 一对一映射为 TranslationUnitRecord。
fn frozen_unit_to_translation_unit(fu: &FrozenUnit) -> TranslationUnitRecord {
    TranslationUnitRecord {
        unit_id: fu.unit_id.clone(),
        kind: fu.kind.clone(),
        owner_kind: fu.owner_kind.clone(),
        owner_id: fu.owner_id.clone(),
        section_id: fu.section_id.clone(),
        section_title: fu.section_title.clone(),
        section_start_page: fu.section_start_page,
        section_end_page: fu.section_end_page,
        note_id: fu.note_id.clone(),
        page_start: fu.page_start,
        page_end: fu.page_end,
        char_count: fu.char_count,
        source_text: fu.source_text.clone(),
        translated_text: fu.translated_text.clone(),
        status: "pending".to_string(),
        error_msg: String::new(),
        target_ref: fu.target_ref.clone(),
        page_segments: fu.page_segments.clone(),
        ..Default::default()
    }
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_frozen_body_unit(
        chapter_id: &str,
        index: usize,
        page_start: i64,
        page_end: i64,
        text: &str,
    ) -> FrozenUnit {
        FrozenUnit {
            unit_id: format!("body-{}-{:04}", chapter_id, index + 1),
            kind: "body".to_string(),
            owner_kind: "chapter".to_string(),
            owner_id: chapter_id.to_string(),
            section_id: chapter_id.to_string(),
            section_title: format!("Chapter {}", chapter_id),
            section_start_page: page_start,
            section_end_page: page_end,
            page_start,
            page_end,
            char_count: text.chars().count() as i64,
            source_text: text.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn test_build_translation_units_empty() {
        let frozen_units = FrozenUnits::default();
        let (units, summary) = build_translation_units(&frozen_units);
        assert!(units.is_empty());
        assert_eq!(summary["unit_planning_summary"]["body_unit_count"], 0);
    }

    #[test]
    fn test_build_translation_units_from_frozen_body_units() {
        let body_units = vec![
            make_frozen_body_unit("ch1", 0, 1, 2, "# Chapter 1\n\nBody text page 1."),
            make_frozen_body_unit("ch2", 0, 3, 3, "Body text page 2."),
        ];
        let frozen_units = FrozenUnits {
            body_units,
            ..Default::default()
        };
        let (units, _summary) = build_translation_units(&frozen_units);
        assert_eq!(units.len(), 2);
        assert!(units.iter().all(|u| u.kind == "body"));
        assert_eq!(units[0].unit_id, "body-ch1-0001");
        assert_eq!(units[1].unit_id, "body-ch2-0001");
        // 验证 source_text 一对一映射
        assert!(units[0].source_text.contains("# Chapter 1"));
        assert!(units[1].source_text.contains("Body text page 2."));
    }

    #[test]
    fn test_build_translation_units_preserves_note_units() {
        let note_units = vec![
            FrozenUnit {
                unit_id: "footnote-ch1-n1".to_string(),
                kind: "footnote".to_string(),
                owner_kind: "note_region".to_string(),
                owner_id: "r1".to_string(),
                section_id: "ch1".to_string(),
                note_id: "n1".to_string(),
                source_text: "A footnote.".to_string(),
                page_start: 1,
                page_end: 1,
                ..Default::default()
            },
            FrozenUnit {
                unit_id: "endnote-ch1-n2".to_string(),
                kind: "endnote".to_string(),
                owner_kind: "note_region".to_string(),
                owner_id: "r2".to_string(),
                section_id: "ch1".to_string(),
                note_id: "n2".to_string(),
                source_text: "An endnote.".to_string(),
                page_start: 5,
                page_end: 5,
                ..Default::default()
            },
        ];
        let frozen_units = FrozenUnits {
            note_units,
            ..Default::default()
        };
        let (units, _summary) = build_translation_units(&frozen_units);
        assert_eq!(units.len(), 2);
        assert_eq!(units[0].kind, "footnote");
        assert_eq!(units[0].note_id, "n1");
        assert_eq!(units[1].kind, "endnote");
        assert_eq!(units[1].note_id, "n2");
    }
}
