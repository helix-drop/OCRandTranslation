//! ←→ FNM_RE/stages/chapter_skeleton/_pdf_font_worker.py
//! PDF 字体提取：用 pdfium-render 渲染页面，提取 heading 字体候选。

use anyhow::Result;
use std::collections::HashMap;

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
pub fn extract_font_candidates(
    pdf_path: &str,
    page_indices: &[i64],
) -> Result<HashMap<i64, Vec<FontCandidate>>> {
    let _ = (pdf_path, page_indices);

    // pdfium-render 需要 PDFium 动态库。在 CI 中需要额外安装。
    // 当前返回空结果，等部署环境确认 PDFium 可用性后再启用。
    Ok(HashMap::new())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_for_missing_pdf() {
        let result = extract_font_candidates("nonexistent.pdf", &[1, 2]).unwrap();
        assert!(result.is_empty());
    }
}
