//! ←→ FNM_RE/modules/llm_book_type_verify.py (1039 行)
//! LLM 视觉验证书型：用 Vision API 看代表性页面确认 book_type 判定。

use crate::book_note_type::BookNoteProfile;
use anyhow::{Context, Result};
use base64::Engine;
use fnm_core::records::Phase1Structure;
use once_cell::sync::Lazy;
use pdfium_render::prelude::*;
use reqwest::Client;
use serde_json::json;
use std::sync::Mutex;
use std::time::Duration;

// ── 全局单例 ──────────────────────────────────────────────────────

static PDFIUM: Lazy<Mutex<Pdfium>> = Lazy::new(|| {
    let bindings = Pdfium::bind_to_system_library()
        .or_else(|_| Pdfium::bind_to_library(Pdfium::pdfium_platform_library_name_at_path("./")))
        .expect("无法加载 PDFium 二进制库");
    Mutex::new(Pdfium::new(bindings))
});

static HTTP_CLIENT: Lazy<Client> = Lazy::new(|| {
    Client::builder()
        .timeout(Duration::from_secs(180))
        .build()
        .expect("构造 HTTP client 失败")
});

// ── 类型 ──────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct LlmConfig {
    pub api_key: String,
    pub model: String,
    pub base_url: String,
    pub timeout_secs: u64,
}

impl Default for LlmConfig {
    fn default() -> Self {
        Self {
            api_key: std::env::var("OPENAI_API_KEY").unwrap_or_default(),
            model: "gpt-4o".into(),
            base_url: "https://api.openai.com/v1".into(),
            timeout_secs: 180,
        }
    }
}

#[derive(Debug, Clone)]
pub struct LlmVerifyResult {
    pub llm_book_type: Option<String>,
    pub agreement_with_rules: bool,
    pub evidence: serde_json::Value,
}

// ── PDF 渲染 ──────────────────────────────────────────────────────

fn render_page_to_base64_png(pdf_path: &str, page_index: u16) -> Result<String> {
    let pdfium = PDFIUM.lock().expect("PDFIUM mutex poisoned");
    let document = pdfium
        .load_pdf_from_file(pdf_path, None)
        .with_context(|| format!("加载 PDF 失败: {}", pdf_path))?;
    let page = document
        .pages()
        .get(page_index)
        .with_context(|| format!("PDF 页 {} 不存在", page_index))?;
    let render_config = PdfRenderConfig::new()
        .set_target_width(2000)
        .render_form_data(false);
    let bitmap = page.render_with_config(&render_config)?;
    let image = bitmap.as_image();
    let mut png_bytes = Vec::new();
    image
        .write_to(
            &mut std::io::Cursor::new(&mut png_bytes),
            image::ImageFormat::Png,
        )
        .context("PNG 编码失败")?;
    Ok(base64::engine::general_purpose::STANDARD.encode(&png_bytes))
}

// ── 页面选择 ──────────────────────────────────────────────────────

/// 选择代表性页面用于 LLM 验证。
fn select_representative_pages(structure: &Phase1Structure) -> Vec<i64> {
    let mut pages: Vec<i64> = Vec::new();

    // 第 1 页（通常是书名页或版权页）
    if let Some(first) = structure.pages.first() {
        pages.push(first.page_no);
    }

    // 前 3 个不同 body 页
    for p in &structure.pages {
        if p.page_role.as_str() == "body" && !pages.contains(&p.page_no) && pages.len() < 4 {
            pages.push(p.page_no);
        }
    }

    // 最后 body 页
    if let Some(last_body) = structure
        .pages
        .iter()
        .rev()
        .find(|p| p.page_role.as_str() == "body" && !pages.contains(&p.page_no))
    {
        pages.push(last_body.page_no);
    }

    pages.sort();
    pages.dedup();

    pages
}

// ── Prompt ────────────────────────────────────────────────────────

fn build_book_type_prompt(page_count: usize) -> String {
    format!(
        "这是某本书的 {n} 页截图。请判断这本书的整体注释类型。\n\
        \n\
        选项：\n\
        1. \"footnote\" — 脚注为主（页末有小字号注释）\n\
        2. \"endnote\" — 尾注为主（每章或书末有集中的注释章节）\n\
        3. \"mixed\" — 脚注和尾注都有\n\
        4. \"no_notes\" — 没有注释\n\
        \n\
        回复 JSON: {{\"book_type\": \"footnote|endnote|mixed|no_notes\", \"confidence\": 0.0-1.0, \"reason\": \"观察摘要\"}}",
        n = page_count
    )
}

// ── Vision API ────────────────────────────────────────────────────

async fn call_vision_api(page_images: &[String], config: &LlmConfig) -> Result<serde_json::Value> {
    let prompt = build_book_type_prompt(page_images.len());

    let mut content = vec![json!({"type": "text", "text": prompt})];
    for b64 in page_images {
        content.push(json!({
            "type": "image_url",
            "image_url": {
                "url": format!("data:image/png;base64,{}", b64)
            }
        }));
    }

    let response = HTTP_CLIENT
        .post(format!("{}/chat/completions", config.base_url))
        .bearer_auth(&config.api_key)
        .json(&json!({
            "model": config.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 300,
            "temperature": 0.0,
        }))
        .send()
        .await
        .context("Vision API 请求失败")?;

    let body: serde_json::Value = response.json().await?;
    Ok(body)
}

fn parse_vision_response(body: &serde_json::Value) -> Result<(String, f64, String)> {
    let content = body["choices"][0]["message"]["content"]
        .as_str()
        .context("Vision API 响应格式错误")?;

    let json_str = content
        .find('{')
        .and_then(|start| content.rfind('}').map(|end| &content[start..=end]))
        .unwrap_or(content);

    let parsed: serde_json::Value =
        serde_json::from_str(json_str).context("无法解析 LLM 响应为 JSON")?;

    let book_type = parsed["book_type"]
        .as_str()
        .unwrap_or("unknown")
        .to_string();
    let confidence = parsed["confidence"].as_f64().unwrap_or(0.0);
    let reason = parsed["reason"].as_str().unwrap_or("").to_string();

    Ok((book_type, confidence, reason))
}

// ── 入口 ──────────────────────────────────────────────────────────

/// Phase1 LLM 验证入口（异步）。
///
/// 1. 选择代表性页面
/// 2. 渲染为 PNG → base64
/// 3. 调 Vision API 问书型
/// 4. 与 rule-based 结果比较
pub async fn verify_book_type_with_llm(
    toc_structure: &Phase1Structure,
    book_note_profile: &BookNoteProfile,
    pdf_path: &str,
    api_config: &LlmConfig,
) -> anyhow::Result<LlmVerifyResult> {
    if api_config.api_key.is_empty() {
        return Ok(LlmVerifyResult {
            llm_book_type: None,
            agreement_with_rules: true,
            evidence: json!({"status": "skipped", "reason": "OPENAI_API_KEY not set"}),
        });
    }

    // 1. 选择代表性页面
    let pages = select_representative_pages(toc_structure);
    if pages.is_empty() {
        return Ok(LlmVerifyResult {
            llm_book_type: None,
            agreement_with_rules: true,
            evidence: json!({"status": "skipped", "reason": "no pages to verify"}),
        });
    }

    // 2. 渲染所有页面
    let mut images: Vec<(i64, String)> = Vec::new();
    for &page_no in &pages {
        match render_page_to_base64_png(pdf_path, page_no.max(1) as u16 - 1) {
            Ok(b64) => images.push((page_no, b64)),
            Err(e) => {
                tracing::warn!("页面 {} 渲染失败: {:?}", page_no, e);
            }
        }
    }
    if images.is_empty() {
        anyhow::bail!("所有页面渲染失败: {}", pdf_path);
    }

    // 3. 调 Vision API
    let b64_list: Vec<String> = images.iter().map(|(_, b)| b.clone()).collect();
    let body = call_vision_api(&b64_list, api_config).await?;

    // 4. 解析响应
    let (llm_book_type, confidence, reason) = parse_vision_response(&body)?;

    let rule_type = book_note_profile.book_type.clone();
    let agreement = llm_book_type == rule_type;

    Ok(LlmVerifyResult {
        llm_book_type: Some(llm_book_type.clone()),
        agreement_with_rules: agreement,
        evidence: json!({
            "representative_pages": pages,
            "rendered_count": images.len(),
            "llm_book_type": llm_book_type,
            "rule_based_type": rule_type,
            "agreement": agreement,
            "confidence": confidence,
            "reason": reason,
        }),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn config_default_from_env() {
        let config = LlmConfig::default();
        assert_eq!(config.model, "gpt-4o");
    }

    #[test]
    fn select_representative_pages_empty() {
        let structure = Phase1Structure::default();
        let pages = select_representative_pages(&structure);
        assert!(pages.is_empty());
    }

    #[test]
    fn select_representative_pages_body_only() {
        use fnm_core::types::PageRole;

        let rec = |no: i64, role: PageRole| -> fnm_core::records::PagePartitionRecord {
            fnm_core::records::PagePartitionRecord {
                page_no: no,
                target_pdf_page: no,
                page_role: role,
                confidence: 1.0,
                reason: String::new(),
                section_hint: String::new(),
                has_note_heading: false,
                note_scan_summary: serde_json::Value::Null,
            }
        };
        let structure = Phase1Structure {
            pages: vec![
                rec(1, PageRole::FrontMatter),
                rec(10, PageRole::Body),
                rec(20, PageRole::Body),
            ],
            ..Default::default()
        };
        let pages = select_representative_pages(&structure);
        assert!(pages.contains(&1));
        assert!(pages.contains(&10));
    }

    #[tokio::test]
    #[ignore = "需要真实 OPENAI_API_KEY + PDFium 二进制"]
    async fn real_book_type_verify() {
        use fnm_core::records::*;
        use fnm_core::types::PageRole;

        let structure = Phase1Structure {
            pages: vec![PagePartitionRecord {
                page_no: 1,
                target_pdf_page: 1,
                page_role: PageRole::FrontMatter,
                confidence: 1.0,
                reason: "test".into(),
                section_hint: String::new(),
                has_note_heading: false,
                note_scan_summary: serde_json::Value::Null,
            }],
            ..Default::default()
        };
        let profile = BookNoteProfile {
            book_type: "endnote".into(),
            chapter_modes: vec![],
            evidence: json!({}),
        };
        let config = LlmConfig::default();
        let pdf = "/Users/hao/OCRandTranslation/test_example/Biopolitics/Biopolitics.pdf";
        let result = verify_book_type_with_llm(&structure, &profile, pdf, &config)
            .await
            .unwrap();
        assert!(result.llm_book_type.is_some());
    }
}
