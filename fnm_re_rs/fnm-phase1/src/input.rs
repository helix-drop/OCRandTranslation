//! Phase1 输入类型：VisualTocBundle / ManualPageOverride。RawPage 和 TocItem 由
//! fnm_core::records 提供（此处 re-export 保持 import path 兼容）。
//!
//! 与 Python `raw_pages.json` 和 `visual_toc.json` 的 JSON schema 对齐。

pub use fnm_core::records::{RawPage, TocItem};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// 整本书的 visual TOC bundle（manual 标注 + auto 提取的混合）。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct VisualTocBundle {
    #[serde(default)]
    pub items: Vec<TocItem>,
    #[serde(default)]
    pub endnotes_start_page: Option<i64>,
    #[serde(default)]
    pub manual_page_items_debug: Value,
}

/// 手工 page override（review 工具产生）。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ManualPageOverride {
    #[serde(default)]
    pub page_role: Option<String>,
    #[serde(default)]
    pub section_hint: Option<String>,
    #[serde(default)]
    pub reason: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deserialize_raw_page_from_python_json() {
        let json = r##"{
            "bookPage": 1,
            "markdown": "# Title\nSome text",
            "prunedResult": {},
            "fnBlocks": {}
        }"##;
        let page: RawPage = serde_json::from_str(json).expect("parse");
        assert_eq!(page.book_page, 1);
        assert!(page.markdown.contains("Title"));
        assert!(page.pdf_page.is_none());
    }

    #[test]
    fn deserialize_toc_item() {
        let json = r#"{
            "item_id": "toc-1",
            "title": "Chapter One",
            "level": 1,
            "depth": 0,
            "role_hint": "chapter"
        }"#;
        let item: TocItem = serde_json::from_str(json).expect("parse");
        assert_eq!(item.item_id, "toc-1");
        assert_eq!(item.title, "Chapter One");
        assert_eq!(item.level, 1);
    }

    #[test]
    fn deserialize_manual_override() {
        let json = r#"{"page_role": "body", "reason": "manual fix"}"#;
        let ov: ManualPageOverride = serde_json::from_str(json).expect("parse");
        assert_eq!(ov.page_role.as_deref(), Some("body"));
        assert_eq!(ov.reason.as_deref(), Some("manual fix"));
    }

    #[test]
    fn visual_toc_bundle_default() {
        let bundle = VisualTocBundle::default();
        assert!(bundle.items.is_empty());
        assert!(bundle.endnotes_start_page.is_none());
    }
}
