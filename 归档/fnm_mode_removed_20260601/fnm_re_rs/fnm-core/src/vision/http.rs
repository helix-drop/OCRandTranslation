//! HTTP 客户端单例 + Vision API 配置。
//!
//! 原 phase2 `sup_recovery/layer3.rs` 的 HTTP_CLIENT + VisionConfig 抽出。

use once_cell::sync::Lazy;
use reqwest::Client;
use std::time::Duration;

/// 全局 HTTP client（180s timeout，rustls-tls）。
/// 供所有 LLM/Vision 调用共享，避免每次新建。
pub static HTTP_CLIENT: Lazy<Client> = Lazy::new(|| {
    Client::builder()
        .timeout(Duration::from_secs(180))
        .build()
        .expect("构造 HTTP client 失败")
});

/// Vision LLM 配置（从环境变量或默认值构造）。
#[derive(Debug, Clone)]
pub struct VisionConfig {
    pub api_key: String,
    pub model: String,
    pub base_url: String,
}

impl Default for VisionConfig {
    fn default() -> Self {
        Self {
            api_key: std::env::var("OPENAI_API_KEY").unwrap_or_default(),
            model: "gpt-4o".into(),
            base_url: "https://api.openai.com/v1".into(),
        }
    }
}
