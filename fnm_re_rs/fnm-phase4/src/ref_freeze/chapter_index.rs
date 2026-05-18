//! ←→ Python `ref_freeze.py:_chapter_order_map` (L34) + `_chapter_page_bounds` (L41)
//! Chapter 索引辅助：顺序映射 + 页码范围。

use fnm_phase2::chapter_split::{ChapterLayer, ChapterLayers};
use std::collections::HashMap;

/// 构建 chapter_id → 序号 的映射（从 1 开始）。
///
/// ←→ Python `_chapter_order_map` (ref_freeze.py:34-39)
pub fn chapter_order_map(chapter_layers: &ChapterLayers) -> HashMap<String, i64> {
    chapter_layers
        .chapters
        .iter()
        .enumerate()
        .filter_map(|(index, chapter)| {
            let chapter_id = chapter.chapter_id.trim().to_string();
            if chapter_id.is_empty() {
                None
            } else {
                Some((chapter_id, (index + 1) as i64))
            }
        })
        .collect()
}

/// 收集 chapter 的所有页码（body_pages / footnote_items / endnote_items / endnote_regions），返回 (min, max)。
///
/// ←→ Python `_chapter_page_bounds` (ref_freeze.py:41-45)
pub fn chapter_page_bounds(chapter: &ChapterLayer) -> (i64, i64) {
    let mut page_nos: Vec<i64> = Vec::new();

    for page in &chapter.body_pages {
        if page.page_no > 0 {
            page_nos.push(page.page_no);
        }
    }
    for item in &chapter.footnote_items {
        if item.page_no > 0 {
            page_nos.push(item.page_no);
        }
    }
    for item in &chapter.endnote_items {
        if item.page_no > 0 {
            page_nos.push(item.page_no);
        }
    }
    for region in &chapter.endnote_regions {
        if region.page_start > 0 {
            page_nos.push(region.page_start);
        }
        if region.page_end > 0 {
            page_nos.push(region.page_end);
        }
    }

    if page_nos.is_empty() {
        return (0, 0);
    }
    page_nos.sort();
    (page_nos[0], page_nos[page_nos.len() - 1])
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::ChapterRecord;
    use fnm_phase2::chapter_split::BodyPageLayer;

    fn make_chapter(chapter_id: &str) -> ChapterRecord {
        ChapterRecord {
            chapter_id: chapter_id.into(),
            title: chapter_id.into(),
            start_page: 0,
            end_page: 0,
            pages: Vec::new(),
            source: fnm_core::types::ChapterSource::VisualToc,
            boundary_state: fnm_core::types::BoundaryState::Ready,
        }
    }

    fn make_chapter_layer(chapter_id: &str, page_nos: &[i64]) -> ChapterLayer {
        ChapterLayer {
            chapter_id: chapter_id.to_string(),
            body_pages: page_nos
                .iter()
                .map(|&p| BodyPageLayer {
                    page_no: p,
                    ..Default::default()
                })
                .collect(),
            ..Default::default()
        }
    }

    #[test]
    fn test_chapter_order_map_basic() {
        let layers = ChapterLayers {
            chapters: vec![make_chapter("ch1"), make_chapter("ch2")],
            ..Default::default()
        };
        let order = chapter_order_map(&layers);
        assert_eq!(order.get("ch1"), Some(&1));
        assert_eq!(order.get("ch2"), Some(&2));
    }

    #[test]
    fn test_chapter_order_map_skips_empty() {
        let layers = ChapterLayers {
            chapters: vec![
                make_chapter(""),   // chapter_id 为空，应被跳过
                make_chapter("ch1"),
            ],
            ..Default::default()
        };
        let order = chapter_order_map(&layers);
        assert!(!order.contains_key(""));
        assert_eq!(order.get("ch1"), Some(&2));
    }

    #[test]
    fn test_chapter_page_bounds_basic() {
        let ch = make_chapter_layer("ch1", &[5, 10, 15]);
        let (min, max) = chapter_page_bounds(&ch);
        assert_eq!(min, 5);
        assert_eq!(max, 15);
    }

    #[test]
    fn test_chapter_page_bounds_empty() {
        let ch = ChapterLayer::default();
        let (min, max) = chapter_page_bounds(&ch);
        assert_eq!((min, max), (0, 0));
    }
}
