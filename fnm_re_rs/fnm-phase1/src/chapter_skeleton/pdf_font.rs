//! ←→ FNM_RE/stages/chapter_skeleton/_pdf_font_worker.py
//! PDF 字体提取：用 pdfium-render 提取页面文本对象的位置/字体元数据。

use anyhow::Result;
use pdfium_render::prelude::*;
use std::collections::HashMap;

/// 归一化 PDF 字体名称，提取 family 并附带 weight 提示。
fn font_weight_hint(name: &str) -> &'static str {
    let lower = name.to_lowercase();
    if lower.contains("bold") || lower.contains("heavy") || lower.contains("black") {
        if lower.contains("italic") || lower.contains("oblique") {
            return "bolditalic";
        }
        return "bold";
    }
    if lower.contains("italic") || lower.contains("oblique") {
        return "italic";
    }
    "regular"
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct FontCandidate {
    pub text: String,
    pub font_name: String,
    pub font_size: f64,
    pub is_bold: bool,
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

/// 从 PDF 文件中提取指定页面的字体候选信息。
/// 与 Python `_pdf_font_worker.py` 输出 schema 兼容。
/// 复用 `fnm_core::vision::PDFIUM` 全局单例，避免重复绑定。
pub fn extract_font_candidates(
    pdf_path: &str,
    page_indices: &[i64],
) -> Result<HashMap<i64, Vec<FontCandidate>>> {
    if page_indices.is_empty() || pdf_path.is_empty() {
        return Ok(HashMap::new());
    }

    // 复用 C1 抽取的 PDFIUM 单例（线程安全、懒加载）。
    // PDFIUM 不可用时 Lazy::new 会 panic——这是 C1 的 fail-fast 设计。
    // 调用方应在 pdf_path 为空时提前返回（见 collect_pdf_font_band_candidates）。
    let pdfium = fnm_core::vision::PDFIUM
        .lock()
        .map_err(|_| anyhow::anyhow!("PDFIUM mutex poisoned"))?;

    let doc = match pdfium.load_pdf_from_file(pdf_path, None) {
        Ok(d) => d,
        Err(_) => return Ok(HashMap::new()),
    };

    let pages = doc.pages();
    let mut result: HashMap<i64, Vec<FontCandidate>> = HashMap::new();

    // 构建 lookup set
    let page_idx_set: std::collections::HashSet<i64> = page_indices.iter().copied().collect();

    for idx in page_idx_set {
        let page = match pages.get(idx as u16) {
            Ok(p) => p,
            Err(_) => continue,
        };

        let page_objects = page.objects();
        let page_height = page.height().value as f64;

        let mut candidates: Vec<FontCandidate> = Vec::new();

        for obj in page_objects.iter() {
            let text_obj = match obj.as_text_object() {
                Some(t) => t,
                None => continue,
            };

            let text = text_obj.text().trim().to_string();
            if text.is_empty() || text.len() > 400 {
                continue;
            }

            let bounds = match obj.bounds() {
                Ok(b) => b,
                Err(_) => continue,
            };

            let font = text_obj.font();
            let font_name = font.name();
            let fwh = font_weight_hint(&font_name);
            let fs = text_obj.scaled_font_size().value as f64;
            let is_bold = font.is_bold_reenforced() || fwh == "bold" || fwh == "bolditalic";

            // PDF 坐标系：原点在左下角，Y 轴向上。
            // 转换为 Python 兼容的 top-left 坐标系。
            let x = bounds.left().value as f64;
            let y = page_height - bounds.top().value as f64;
            let w = (bounds.right().value - bounds.left().value).max(1.0) as f64;
            let h = (bounds.top().value - bounds.bottom().value).max(1.0) as f64;

            candidates.push(FontCandidate {
                text,
                font_name,
                font_size: fs.max(1.0),
                is_bold,
                x,
                y,
                width: w,
                height: h,
            });
        }

        if !candidates.is_empty() {
            result.insert(idx, candidates);
        }
    }

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_for_missing_pdf() {
        if std::env::var("FNM_PDFIUM_ENABLED").is_err() {
            eprintln!("skipping: set FNM_PDFIUM_ENABLED=1 to enable PDFium tests");
            return;
        }
        let result = extract_font_candidates("nonexistent.pdf", &[1, 2]).unwrap();
        assert!(result.is_empty());
    }

    #[test]
    fn empty_for_empty_indices() {
        // 不访问 PDFIUM — 提前在 page_indices.is_empty() 返回
        let result = extract_font_candidates("some.pdf", &[]).unwrap();
        assert!(result.is_empty());
    }
}
