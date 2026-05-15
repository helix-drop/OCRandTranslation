//! Composite heading 生成。←→ Python `_build_derived_heading_candidates()` 等。

use fnm_core::records::HeadingCandidate;

use super::title_key;

/// 判断两个 pdf_font_band 候选是否为同一多行标题。
fn same_style_pdf_pair(a: &HeadingCandidate, b: &HeadingCandidate) -> bool {
    if a.page_no != b.page_no {
        return false;
    }
    if a.source != "pdf_font_band" || b.source != "pdf_font_band" {
        return false;
    }
    // y 距离检查
    let y_a = a.y.unwrap_or(0.0);
    let y_b = b.y.unwrap_or(0.0);
    if (y_a - y_b).abs() > 54.0 {
        return false;
    }
    // align 兼容
    if a.align_hint != "unknown" && b.align_hint != "unknown" && a.align_hint != b.align_hint {
        return false;
    }
    // font family 相同
    let family_a = font_family_token(&a.font_name);
    let family_b = font_family_token(&b.font_name);
    if !family_a.is_empty() && !family_b.is_empty() && family_a != family_b {
        return false;
    }
    // x 距离检查
    let x_a = a.x.unwrap_or(0.0);
    let x_b = b.x.unwrap_or(0.0);
    let x_threshold = if a.align_hint == "center" {
        140.0
    } else {
        96.0
    };
    (x_a - x_b).abs() <= x_threshold
}

fn font_family_token(font_name: &str) -> String {
    let lower = font_name.to_lowercase();
    if lower.is_empty() {
        return String::new();
    }
    // 取第一个 token
    lower
        .split(|c: char| !c.is_alphanumeric())
        .find(|s| !s.is_empty())
        .unwrap_or("")
        .to_string()
}

/// 从同页 PDF 候选中合成多行标题。
fn build_same_style_pdf_composites(candidates: &[HeadingCandidate]) -> Vec<HeadingCandidate> {
    let mut composites = Vec::new();
    // 按 page_no 分组
    let mut by_page: std::collections::HashMap<i64, Vec<&HeadingCandidate>> =
        std::collections::HashMap::new();
    for c in candidates {
        if c.source == "pdf_font_band" {
            by_page.entry(c.page_no).or_default().push(c);
        }
    }

    for page_candidates in by_page.values() {
        if page_candidates.len() < 2 {
            continue;
        }
        // 滑动窗口合并
        let mut i = 0;
        while i < page_candidates.len() {
            let mut parts: Vec<&HeadingCandidate> = vec![page_candidates[i]];
            let mut j = i + 1;
            while j < page_candidates.len() {
                if same_style_pdf_pair(page_candidates[j - 1], page_candidates[j]) {
                    parts.push(page_candidates[j]);
                    j += 1;
                } else {
                    break;
                }
            }
            if parts.len() >= 2 {
                let composite = compose_heading_parts(&parts, "multiline");
                composites.push(composite);
            }
            i = j;
        }
    }
    composites
}

/// 从编号行+标题行模式构建 composite。
fn build_chapter_number_pairs(candidates: &[HeadingCandidate]) -> Vec<HeadingCandidate> {
    let mut composites = Vec::new();
    // 按 page_no 分组
    let mut by_page: std::collections::HashMap<i64, Vec<&HeadingCandidate>> =
        std::collections::HashMap::new();
    for c in candidates {
        by_page.entry(c.page_no).or_default().push(c);
    }

    for page_candidates in by_page.values() {
        for (i, num_candidate) in page_candidates.iter().enumerate() {
            if !title_key::is_chapter_number_candidate(&num_candidate.text) {
                continue;
            }
            // 找紧随其后的非编号候选
            if i + 1 >= page_candidates.len() {
                continue;
            }
            let title_candidate = page_candidates[i + 1];
            if title_key::is_chapter_number_candidate(&title_candidate.text) {
                continue;
            }
            // 检查 y 距离
            let y_num = num_candidate.y.unwrap_or(0.0);
            let y_title = title_candidate.y.unwrap_or(0.0);
            if (y_num - y_title).abs() > 80.0 {
                continue;
            }
            let composite =
                compose_heading_parts(&[num_candidate, title_candidate], "chapter_number_pair");
            composites.push(composite);
        }
    }
    composites
}

/// 将多行 parts 合成为一个 composite heading。
fn compose_heading_parts(parts: &[&HeadingCandidate], kind: &str) -> HeadingCandidate {
    let combined_text: String = parts
        .iter()
        .map(|p| p.text.as_str())
        .collect::<Vec<_>>()
        .join(" ");
    let combined_normalized: String = parts
        .iter()
        .map(|p| p.normalized_text.as_str())
        .collect::<Vec<_>>()
        .join(" ");

    let max_confidence = parts.iter().map(|p| p.confidence).fold(0.0f64, f64::max);
    let max_font_height = parts
        .iter()
        .filter_map(|p| p.font_height)
        .fold(0.0f64, f64::max);
    let min_x = parts
        .iter()
        .filter_map(|p| p.x)
        .fold(f64::INFINITY, f64::min);
    let min_y = parts
        .iter()
        .filter_map(|p| p.y)
        .fold(f64::INFINITY, f64::min);
    let first = parts[0];

    HeadingCandidate {
        heading_id: format!("composite-{}-{}", first.page_no, kind),
        page_no: first.page_no,
        text: combined_text,
        normalized_text: combined_normalized,
        source: "pdf_font_band_composite".into(),
        block_label: first.block_label.clone(),
        top_band: first.top_band,
        confidence: max_confidence,
        heading_family_guess: first.heading_family_guess.clone(),
        suppressed_as_chapter: false,
        reject_reason: String::new(),
        font_height: if max_font_height > 0.0 {
            Some(max_font_height)
        } else {
            None
        },
        x: if min_x < f64::INFINITY {
            Some(min_x)
        } else {
            None
        },
        y: if min_y < f64::INFINITY {
            Some(min_y)
        } else {
            None
        },
        width_estimate: None,
        font_name: first.font_name.clone(),
        font_weight_hint: first.font_weight_hint.clone(),
        align_hint: first.align_hint.clone(),
        width_ratio: None,
        heading_level_hint: first.heading_level_hint,
    }
}

/// 编排 multiline + chapter_number_pair 两路 composite 生成。
pub fn build_derived_heading_candidates(
    candidates: &[HeadingCandidate],
) -> (Vec<HeadingCandidate>, usize) {
    let multiline = build_same_style_pdf_composites(candidates);
    let number_pairs = build_chapter_number_pairs(candidates);
    let composite_count = multiline.len() + number_pairs.len();

    let mut derived = multiline;
    derived.extend(number_pairs);

    // 按 (page_no, title_key) 去重
    let mut seen = std::collections::HashSet::new();
    derived.retain(|c| {
        let key = (c.page_no, fnm_core::title::chapter_title_match_key(&c.text));
        seen.insert(key)
    });

    (derived, composite_count)
}
