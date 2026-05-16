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

/// 判断两个 kind 是否兼容（相等或任一 unknown）。
///
/// ←→ Python `_anchor_kind_compatible`
pub fn anchor_kind_compatible(left: &str, right: &str) -> bool {
    let left = left.trim();
    let right = right.trim();
    left == right || left == "unknown" || right == "unknown"
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
        assert!(anchor_kind_compatible("footnote", "footnote"));
        assert!(anchor_kind_compatible("endnote", "unknown"));
        assert!(anchor_kind_compatible("unknown", "footnote"));
        assert!(!anchor_kind_compatible("footnote", "endnote"));
    }
}
