//! ←→ FNM_RE/modules/_pdf_render_worker.py `_render_repair_page`
//! PDF 页 → data:image/jpeg;base64,...

/// 渲染 PDF 单页为 data URL，委托 fnm-core 的 pdfium 渲染。
///
/// ←→ Python `render_repair_page_data_url()`
pub fn render_repair_page_data_url(
    pdf_path: &str,
    page_index: i64,
    scale: f64,
) -> anyhow::Result<String> {
    fnm_core::vision::pdfium::render_page_to_data_url(pdf_path, page_index, scale)
}
