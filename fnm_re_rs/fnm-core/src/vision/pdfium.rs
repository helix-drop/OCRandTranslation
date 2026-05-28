//! PDFIUM 单例 + PDF 页渲染。
//! ←→ FNM_RE/modules/_pdf_render_worker.py
//!
//! 原 phase1 `llm_book_type_verify/mod.rs` / phase2 `sup_recovery/pdf_render.rs` 重复，
//! 抽取到 fnm-core 统一提供。

use anyhow::{Context, Result};
use base64::Engine;
use image::ImageFormat;
use once_cell::sync::Lazy;
use pdfium_render::prelude::*;
use std::sync::Mutex;

/// 全局 Pdfium 实例（懒加载、线程安全）。
///
/// **为什么用全局 Mutex**：PDFium 绑定的线程安全边界未知，其 C 库可能使用全局状态。
/// 移除此锁可能导致并发崩溃。这是资源管理例外，不是普通业务状态 Mutex。
/// 相关真实测试受 `FNM_PDFIUM_ENABLED=1` 环境变量控制。
pub static PDFIUM: Lazy<Mutex<Pdfium>> = Lazy::new(|| {
    let bindings = Pdfium::bind_to_system_library()
        .or_else(|_| Pdfium::bind_to_library(Pdfium::pdfium_platform_library_name_at_path("./")))
        .expect("无法加载 PDFium 二进制库");
    Mutex::new(Pdfium::new(bindings))
});

/// 渲染 PDF 单页为 data URL（JPEG，可调缩放）。
///
/// ←→ Python `_pdf_render_worker._render_repair_page`
pub fn render_page_to_data_url(pdf_path: &str, page_index: i64, scale: f64) -> Result<String> {
    let pdfium = PDFIUM.lock().expect("PDFIUM mutex poisoned");
    let document = pdfium
        .load_pdf_from_file(pdf_path, None)
        .with_context(|| format!("加载 PDF 失败: {}", pdf_path))?;

    let page = document
        .pages()
        .get(page_index as u16)
        .with_context(|| format!("PDF 页 {} 不存在", page_index))?;

    // PDF size ≈ 612pt wide (letter), scale to desired pixel width
    let target_width = (612.0 * scale).max(200.0) as i32;
    let render_config = PdfRenderConfig::new()
        .set_target_width(target_width)
        .render_form_data(false);

    let bitmap = page.render_with_config(&render_config)?;
    let image = bitmap.as_image();

    let mut jpeg_bytes: Vec<u8> = Vec::new();
    image
        .write_to(
            &mut std::io::Cursor::new(&mut jpeg_bytes),
            ImageFormat::Jpeg,
        )
        .context("JPEG 编码失败")?;

    let b64 = base64::engine::general_purpose::STANDARD.encode(&jpeg_bytes);
    Ok(format!("data:image/jpeg;base64,{}", b64))
}

/// 渲染 PDF 单页为 base64 PNG（供 vision LLM 调用）。
///
/// ←→ Python `_pdf_render_worker.render_page_to_image_png_base64()`
pub fn render_page_to_base64_png(pdf_path: &str, page_index: i64, _dpi: u32) -> Result<String> {
    let pdfium = PDFIUM.lock().expect("PDFIUM mutex poisoned");
    let document = pdfium
        .load_pdf_from_file(pdf_path, None)
        .with_context(|| format!("加载 PDF 失败: {}", pdf_path))?;

    let page = document
        .pages()
        .get(page_index as u16)
        .with_context(|| format!("PDF 页 {} 不存在", page_index))?;

    let render_config = PdfRenderConfig::new()
        .set_target_width(2000)
        .render_form_data(false);

    let bitmap = page.render_with_config(&render_config)?;
    let image = bitmap.as_image();

    let mut png_bytes: Vec<u8> = Vec::new();
    image
        .write_to(
            &mut std::io::Cursor::new(&mut png_bytes),
            image::ImageFormat::Png,
        )
        .context("PNG 编码失败")?;

    Ok(base64::engine::general_purpose::STANDARD.encode(&png_bytes))
}

/// 从 PDF 单页提取纯文本。
/// ←→ Python `extract_pdf_text_by_page` (document/pdf_extract.py)
pub fn extract_pdf_text_by_page(pdf_path: &str, page_index: i64) -> Result<String> {
    let pdfium = PDFIUM.lock().expect("PDFIUM mutex poisoned");
    let document = pdfium
        .load_pdf_from_file(pdf_path, None)
        .with_context(|| format!("加载 PDF 失败: {}", pdf_path))?;

    let page = document
        .pages()
        .get(page_index as u16)
        .with_context(|| format!("PDF 页 {} 不存在", page_index))?;

    let pdf_page_text = page
        .text()
        .with_context(|| format!("提取 PDF 页 {} 文本失败", page_index))?;
    Ok(pdf_page_text.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn render_biopolitics_page_1() {
        if std::env::var("FNM_PDFIUM_ENABLED").is_err() {
            eprintln!("skipping: set FNM_PDFIUM_ENABLED=1 to enable PDFium tests");
            return;
        }
        let pdf_path = "/Users/hao/OCRandTranslation/test_example/Biopolitics/Biopolitics.pdf";
        let result = render_page_to_base64_png(pdf_path, 0, 150).unwrap();
        assert!(!result.is_empty());
        assert!(result.starts_with("iVBOR")); // PNG base64 头
    }
}
