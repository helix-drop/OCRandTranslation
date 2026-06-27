//! ←→ heading_candidates.py: _normalize_font_weight_hint / _normalize_align_hint / _width_ratio / _align_hint / _heading_level_hint

/// 规范化字重提示。返回 "regular" | "bold" | "heavy" | "unknown"。
pub fn normalize_font_weight_hint(value: &str) -> &'static str {
    match value.trim().to_lowercase().as_str() {
        "regular" => "regular",
        "bold" => "bold",
        "heavy" => "heavy",
        _ => "unknown",
    }
}

/// 规范化对齐提示。返回 "left" | "center" | "right" | "unknown"。
pub fn normalize_align_hint(value: &str) -> &'static str {
    match value.trim().to_lowercase().as_str() {
        "left" => "left",
        "center" => "center",
        "right" => "right",
        _ => "unknown",
    }
}

/// 计算宽度比例（clamped 0.0~1.0）。与 Python `_width_ratio` 一致。
pub fn width_ratio(width_estimate: Option<f64>, page_width: f64) -> Option<f64> {
    let w = width_estimate?;
    if page_width <= 0.0 {
        return None;
    }
    let ratio = w / page_width;
    Some(ratio.clamp(0.0, 1.0))
}

/// 基于位置推断对齐。与 Python `_align_hint` 一致。
pub fn align_hint(x: Option<f64>, width_estimate: Option<f64>, page_width: f64) -> &'static str {
    let left = match x {
        Some(v) => v,
        None => return "unknown",
    };
    let width = match width_estimate {
        Some(v) => v,
        None => return "unknown",
    };
    if page_width <= 0.0 {
        return "unknown";
    }
    let right = left + width;
    let center = left + width / 2.0;
    let page_center = page_width / 2.0;
    if (center - page_center).abs() <= (40.0_f64).max(page_width * 0.08) {
        return "center";
    }
    if left <= page_width * 0.18 {
        return "left";
    }
    if right >= page_width * 0.82 {
        return "right";
    }
    "unknown"
}

/// 综合推断 heading level。与 Python `_heading_level_hint` 一致。
pub fn heading_level_hint(
    source: &str,
    block_label: &str,
    top_band: bool,
    markdown_level: usize,
) -> i64 {
    match source {
        "visual_toc" => 1,
        "note_heading" => 0,
        "ocr_block" => match block_label {
            "doc_title" if top_band => 1,
            "doc_title" => 2,
            "paragraph_title" => 2,
            _ => 2,
        },
        "markdown_heading" => std::cmp::max(1, markdown_level as i64),
        "pdf_font_band" => {
            if top_band {
                1
            } else {
                2
            }
        }
        _ => 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_font_weight_hint_known() {
        assert_eq!(normalize_font_weight_hint("bold"), "bold");
        assert_eq!(normalize_font_weight_hint("heavy"), "heavy");
        assert_eq!(normalize_font_weight_hint("regular"), "regular");
    }

    #[test]
    fn normalize_font_weight_hint_unknown() {
        assert_eq!(normalize_font_weight_hint("medium"), "unknown");
        assert_eq!(normalize_font_weight_hint(""), "unknown");
    }

    #[test]
    fn normalize_align_hint_known() {
        assert_eq!(normalize_align_hint("left"), "left");
        assert_eq!(normalize_align_hint("center"), "center");
        assert_eq!(normalize_align_hint("right"), "right");
    }

    #[test]
    fn width_ratio_basic() {
        let r = width_ratio(Some(300.0), 1000.0);
        assert!((r.unwrap() - 0.3).abs() < 1e-6);
    }

    #[test]
    fn width_ratio_zero_page() {
        assert!(width_ratio(Some(100.0), 0.0).is_none());
    }

    #[test]
    fn align_hint_center() {
        assert_eq!(align_hint(Some(350.0), Some(300.0), 1000.0), "center");
    }

    #[test]
    fn align_hint_left() {
        assert_eq!(align_hint(Some(50.0), Some(200.0), 1000.0), "left");
    }

    #[test]
    fn align_hint_right() {
        assert_eq!(align_hint(Some(720.0), Some(200.0), 1000.0), "right");
    }

    #[test]
    fn align_hint_unknown() {
        assert_eq!(align_hint(None, Some(200.0), 1000.0), "unknown");
    }

    #[test]
    fn heading_level_visual_toc() {
        assert_eq!(heading_level_hint("visual_toc", "", false, 0), 1);
    }

    #[test]
    fn heading_level_note() {
        assert_eq!(heading_level_hint("note_heading", "", false, 0), 0);
    }

    #[test]
    fn heading_level_ocr_top_band() {
        assert_eq!(heading_level_hint("ocr_block", "doc_title", true, 0), 1);
    }

    #[test]
    fn heading_level_ocr_not_top() {
        assert_eq!(heading_level_hint("ocr_block", "doc_title", false, 0), 2);
    }

    #[test]
    fn heading_level_markdown() {
        assert_eq!(heading_level_hint("markdown_heading", "", false, 3), 3);
    }
}
