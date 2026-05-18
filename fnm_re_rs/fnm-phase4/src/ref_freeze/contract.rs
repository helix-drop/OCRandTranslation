//! ←→ Python `ref_freeze.py`:
//!   - `_unit_contract_issues` (L159)
//!   - `_SKIP_REASON_TO_CATEGORY` dict (L267)
//!
//! Frozen unit 契约检查 + skip reason 分类。

use fnm_core::records::FrozenUnit;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SkipCategory {
    CeilingSkip,
    ErrorSkip,
    PolicySkip,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SkipReason {
    MissingAnchor,
    SyntheticAnchor,
    ConflictAnchor,
    DuplicateAnchor,
    MissingBodyPage,
    TokenNotFound,
}

/// ←→ Python `_SKIP_REASON_TO_CATEGORY` dict (ref_freeze.py:267-274)
pub fn skip_reason_to_category(reason: SkipReason) -> SkipCategory {
    match reason {
        SkipReason::MissingAnchor => SkipCategory::CeilingSkip,
        SkipReason::SyntheticAnchor => SkipCategory::CeilingSkip,
        SkipReason::ConflictAnchor => SkipCategory::ErrorSkip,
        SkipReason::DuplicateAnchor => SkipCategory::PolicySkip,
        SkipReason::MissingBodyPage => SkipCategory::ErrorSkip,
        SkipReason::TokenNotFound => SkipCategory::CeilingSkip,
    }
}

/// 检查 frozen units 的契约合法性（9 种 issue）。
///
/// ←→ Python `_unit_contract_issues` (ref_freeze.py:159-182)
pub fn unit_contract_issues(
    body_units: &[FrozenUnit],
    note_units: &[FrozenUnit],
) -> Vec<String> {
    let mut issues: Vec<String> = Vec::new();

    for row in body_units.iter().chain(note_units.iter()) {
        if row.unit_id.trim().is_empty() {
            issues.push("missing_unit_id".to_string());
        }
        if row.kind.trim().is_empty() {
            issues.push(format!("missing_kind:{}", row.unit_id));
        }
        if row.owner_kind.trim().is_empty() || row.owner_id.trim().is_empty() {
            issues.push(format!("missing_owner:{}", row.unit_id));
        }
        if row.section_id.trim().is_empty() {
            issues.push(format!("missing_section_id:{}", row.unit_id));
        }
    }

    for row in body_units {
        if !row.target_ref.trim().is_empty() {
            issues.push(format!("body_target_ref_not_empty:{}", row.unit_id));
        }
    }

    for row in note_units {
        let kind = row.kind.trim();
        if kind != "footnote" && kind != "endnote" {
            issues.push(format!("note_kind_invalid:{}", row.unit_id));
        }
        if row.note_id.trim().is_empty() {
            issues.push(format!("note_id_missing:{}", row.unit_id));
        }
        if !row.target_ref.trim().starts_with("{{NOTE_REF:") {
            issues.push(format!("note_target_ref_invalid:{}", row.unit_id));
        }
    }

    issues
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_skip_reason_to_category_ceiling() {
        assert_eq!(
            skip_reason_to_category(SkipReason::MissingAnchor),
            SkipCategory::CeilingSkip
        );
        assert_eq!(
            skip_reason_to_category(SkipReason::TokenNotFound),
            SkipCategory::CeilingSkip
        );
    }

    #[test]
    fn test_skip_reason_to_category_error() {
        assert_eq!(
            skip_reason_to_category(SkipReason::ConflictAnchor),
            SkipCategory::ErrorSkip
        );
        assert_eq!(
            skip_reason_to_category(SkipReason::MissingBodyPage),
            SkipCategory::ErrorSkip
        );
    }

    #[test]
    fn test_unit_contract_issues_valid() {
        let body = FrozenUnit {
            unit_id: "body-ch1-0001".into(),
            kind: "body".into(),
            owner_kind: "chapter".into(),
            owner_id: "ch1".into(),
            section_id: "ch1".into(),
            ..Default::default()
        };
        let issues = unit_contract_issues(&[body], &[]);
        assert!(issues.is_empty());
    }

    #[test]
    fn test_unit_contract_issues_missing_unit_id() {
        let body = FrozenUnit::default();
        let issues = unit_contract_issues(&[body], &[]);
        assert!(issues.iter().any(|i| i.contains("missing_unit_id")));
    }

    #[test]
    fn test_unit_contract_issues_note_invalid() {
        let note = FrozenUnit {
            unit_id: "footnote-ch1-n1".into(),
            kind: "body".into(), // note unit 不应有 kind="body"
            note_id: "".into(),
            target_ref: "not a ref".into(),
            ..Default::default()
        };
        let issues = unit_contract_issues(&[], &[note]);
        assert!(issues.iter().any(|i| i.contains("note_kind_invalid")));
        assert!(issues.iter().any(|i| i.contains("note_id_missing")));
        assert!(issues.iter().any(|i| i.contains("note_target_ref_invalid")));
    }
}
