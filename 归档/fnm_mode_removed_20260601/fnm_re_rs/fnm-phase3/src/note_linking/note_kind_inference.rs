//! ←→ Python `note_linking.py:_infer_note_kind_from_anchor / _anchor_kind_compatible`

use fnm_core::records::BodyAnchorRecord;

/// 根据 anchor_kind 推断 note_kind。
///
/// ←→ Python `_infer_note_kind_from_anchor`
pub fn infer_note_kind_from_anchor(anchor: &BodyAnchorRecord) -> &'static str {
    match anchor.anchor_kind.as_str() {
        "footnote" => "footnote",
        "endnote" => "endnote",
        _ => "unknown",
    }
}

/// 宽松的 kind 兼容性检查（用于 review/grouping）。
/// unknown 通配任意类型。
///
/// ←→ Python `_anchor_kind_compatible`
pub fn anchor_kind_compatible(left: &str, right: &str) -> bool {
    let left = left.trim();
    let right = right.trim();
    left == right || left == "unknown" || right == "unknown"
}

/// 严格的 kind 兼容性检查（用于 link matching / override 应用）。
/// unknown 只与 unknown 兼容，不自动匹配 footnote/endnote。
///
/// 铁律 §3：禁止广播——unknown 不应被默认当作 endnote 参与 link 匹配。
pub fn anchor_kind_compatible_for_link(left: &str, right: &str) -> bool {
    let left = left.trim();
    let right = right.trim();
    left == right
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_infer_note_kind() {
        let a = BodyAnchorRecord {
            anchor_kind: fnm_core::types::AnchorKind::Footnote,
            ..Default::default()
        };
        assert_eq!(infer_note_kind_from_anchor(&a), "footnote");

        let a = BodyAnchorRecord {
            anchor_kind: fnm_core::types::AnchorKind::Endnote,
            ..Default::default()
        };
        assert_eq!(infer_note_kind_from_anchor(&a), "endnote");

        let a = BodyAnchorRecord {
            anchor_kind: fnm_core::types::AnchorKind::Unknown,
            ..Default::default()
        };
        assert_eq!(infer_note_kind_from_anchor(&a), "unknown");
    }

    #[test]
    fn test_anchor_kind_compatible() {
        // review/grouping：宽松
        assert!(anchor_kind_compatible("footnote", "footnote"));
        assert!(anchor_kind_compatible("endnote", "unknown"));
        assert!(anchor_kind_compatible("unknown", "footnote"));
        assert!(!anchor_kind_compatible("footnote", "endnote"));
        // link matching：严格
        assert!(anchor_kind_compatible_for_link("footnote", "footnote"));
        assert!(anchor_kind_compatible_for_link("endnote", "endnote"));
        assert!(anchor_kind_compatible_for_link("unknown", "unknown"));
        assert!(!anchor_kind_compatible_for_link("endnote", "unknown"));
        assert!(!anchor_kind_compatible_for_link("footnote", "endnote"));
    }
}
