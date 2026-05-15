//! ←→ FNM_RE/modules/llm_book_type_verify.py
//! LLM 视觉验证书型：用 Vision API 看代表性页面确认 book_type 判定。

use crate::book_note_type::BookNoteProfile;
use fnm_core::records::Phase1Structure;

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

/// Phase1 LLM 验证入口（异步）。
/// 与 Python `verify_book_type_with_llm` 一致。
pub async fn verify_book_type_with_llm(
    toc_structure: &Phase1Structure,
    book_note_profile: &BookNoteProfile,
    pdf_path: &str,
    api_config: &LlmConfig,
) -> anyhow::Result<LlmVerifyResult> {
    let _ = (toc_structure, book_note_profile, pdf_path, api_config);

    // 延后实现：需要 pdfium-render 截图 + reqwest HTTP 调用 + prompt 模板。
    // 当前返回默认结果（agreement_with_rules = true），不阻塞主流程。
    Ok(LlmVerifyResult {
        llm_book_type: None,
        agreement_with_rules: true,
        evidence: serde_json::json!({
            "status": "deferred",
            "reason": "LLM verification not yet implemented in Rust"
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
}
