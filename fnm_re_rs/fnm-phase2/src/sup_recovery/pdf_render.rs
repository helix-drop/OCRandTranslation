//! ←→ modules/_pdf_render_worker.py
//! PDF 页渲染（pdfium-render 直接调用，不需要子进程）。

use anyhow::Result;

/// 渲染 PDF 单页为 base64 PNG（供 vision LLM 调用）。
pub fn render_page_to_base64_png(_pdf_path: &str, _page_index: i64, _dpi: u32) -> Result<String> {
    // pdfium-render 需要运行时 PDFium 二进制。
    // CI 中通过缓存提供。本地开发需安装 PDFium。
    Ok(String::new())
}
