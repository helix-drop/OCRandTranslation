//! ←→ Python `note_linking.py:_chapter_body_text_by_page`

use fnm_phase2::chapter_split::ChapterLayer;
use std::collections::HashMap;

/// 构建每章每页的正文文本映射。
///
/// Returns: `(chapter_id, page_no) -> text`
///
/// ←→ Python `_chapter_body_text_by_page`
pub fn chapter_body_text_by_page(
    chapter_layers: &[ChapterLayer],
) -> HashMap<(String, i64), String> {
    let mut rows: HashMap<(String, i64), String> = HashMap::new();
    for chapter in chapter_layers {
        let chapter_id = chapter.chapter_id.trim();
        if chapter_id.is_empty() {
            continue;
        }
        for page in &chapter.body_pages {
            if page.page_no <= 0 {
                continue;
            }
            rows.insert((chapter_id.to_string(), page.page_no), page.text.clone());
        }
    }
    rows
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_phase2::chapter_split::BodyPageLayer;

    #[test]
    fn test_chapter_body_text_by_page() {
        let layers = vec![ChapterLayer {
            chapter_id: "ch-1".to_string(),
            body_pages: vec![
                BodyPageLayer {
                    page_no: 1,
                    text: "Page 1 text".to_string(),
                    ..Default::default()
                },
                BodyPageLayer {
                    page_no: 2,
                    text: "Page 2 text".to_string(),
                    ..Default::default()
                },
            ],
            ..Default::default()
        }];

        let map = chapter_body_text_by_page(&layers);
        assert_eq!(map.get(&("ch-1".to_string(), 1)).unwrap(), "Page 1 text");
        assert_eq!(map.get(&("ch-1".to_string(), 2)).unwrap(), "Page 2 text");
        assert!(!map.contains_key(&("ch-1".to_string(), 3)));
    }
}
