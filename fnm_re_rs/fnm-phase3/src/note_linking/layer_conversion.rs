//! ←→ Python `note_linking.py:_to_anchor_layers / _to_link_layers`
//!
//! Rust 中 `NoteLinkTable` 直接使用 `BodyAnchorRecord` / `NoteLinkRecord`，
//! 但为了与 Python 架构对齐，保留转换层函数（当前为 identity/cloning）。

use fnm_core::records::{BodyAnchorRecord, NoteLinkRecord};

/// 将 `BodyAnchorRecord` 列表转换为 layer 输出格式。
///
/// ←→ Python `_to_anchor_layers`
pub fn to_anchor_layers(rows: &[BodyAnchorRecord]) -> Vec<BodyAnchorRecord> {
    rows.to_vec()
}

/// 将 `NoteLinkRecord` 列表转换为 layer 输出格式。
///
/// ←→ Python `_to_link_layers`
pub fn to_link_layers(rows: &[NoteLinkRecord]) -> Vec<NoteLinkRecord> {
    rows.to_vec()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_to_anchor_layers_identity() {
        let anchors = vec![BodyAnchorRecord {
            anchor_id: "a-1".to_string(),
            ..Default::default()
        }];
        let layers = to_anchor_layers(&anchors);
        assert_eq!(layers.len(), 1);
        assert_eq!(layers[0].anchor_id, "a-1");
    }

    #[test]
    fn test_to_link_layers_identity() {
        let links = vec![NoteLinkRecord {
            link_id: "l-1".to_string(),
            ..Default::default()
        }];
        let layers = to_link_layers(&links);
        assert_eq!(layers.len(), 1);
        assert_eq!(layers[0].link_id, "l-1");
    }
}
