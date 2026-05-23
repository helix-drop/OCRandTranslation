//! ←→ Python `translation/translator.py` 行 1-138 的异常分类层（被 `llm_repair.py` 通过 `_classify_provider_exception` 复用）。
//!
//! Python 端把 OpenAI SDK 抛出的异常按 HTTP status / 错误关键字分成 4 类：
//! - `RateLimitedError`（429 / rate limit / too many requests）
//! - `QuotaExceededError`（402 / 余额不足类关键字）
//! - `TransientProviderError`（5xx / timeout / temporarily unavailable）
//! - `NonRetryableProviderError`（400/401/403/404/422 + detail）
//!
//! 上层（pipeline / mainline）根据这些类型决定重试策略。Rust 端必须复现，
//! 否则下游限流退避、配额耗尽提示等逻辑会全部 fail-closed 为通用错误。

use serde_json::Value;
use thiserror::Error;

/// Provider 错误分类。
///
/// ←→ Python `translation/translator.py:30-47` 的 4 个异常类
#[derive(Debug, Error)]
pub enum ProviderError {
    /// ←→ Python `RateLimitedError`（translator.py:30-36，HTTP 429 / "rate limit" / "too many requests"）
    #[error("触发模型限流，稍后自动重试。")]
    RateLimited { retry_after_s: Option<f64> },

    /// ←→ Python `QuotaExceededError`（translator.py:38，HTTP 402 / "insufficient_quota" / "余额不足" 等）
    #[error("模型额度已耗尽，请充值或更换 API Key 后重试。")]
    QuotaExceeded,

    /// ←→ Python `TransientProviderError`（translator.py:32-36，HTTP 5xx / timeout）
    #[error("模型服务暂时不可用，稍后自动重试。")]
    Transient { retry_after_s: Option<f64> },

    /// ←→ Python `NonRetryableProviderError`（translator.py:42-47，HTTP 4xx 但非 429/402）
    #[error("{message}")]
    NonRetryable {
        message: String,
        status_code: Option<u16>,
        detail: String,
    },

    /// 其它无法分类的错误（保留原始消息）。
    #[error("{0}")]
    Other(String),
}

impl ProviderError {
    /// 是否可重试（用于上游退避策略判定）。
    ///
    /// ←→ Python 端：RateLimited / Transient 通常被重试；QuotaExceeded / NonRetryable 不重试
    pub fn is_retryable(&self) -> bool {
        matches!(
            self,
            ProviderError::RateLimited { .. } | ProviderError::Transient { .. }
        )
    }

    /// 可选的 Retry-After 秒数（如果服务端给了）。
    pub fn retry_after_seconds(&self) -> Option<f64> {
        match self {
            ProviderError::RateLimited { retry_after_s } => *retry_after_s,
            ProviderError::Transient { retry_after_s } => *retry_after_s,
            _ => None,
        }
    }
}

/// ←→ Python `_parse_retry_after_seconds` (translator.py:50-59)
///
/// 从 `Retry-After` header 解析秒数；非数字、负数返回 None / 0.0。
pub fn parse_retry_after_seconds(value: Option<&str>) -> Option<f64> {
    let raw = value?.trim();
    raw.parse::<f64>().ok().map(|v| v.max(0.0))
}

/// ←→ Python `_extract_provider_error_detail` (translator.py:74-96)
///
/// 从 HTTP body（JSON）提取错误详情；截断到 280 字符。
pub fn extract_provider_error_detail(body: Option<&Value>, fallback: &str) -> String {
    let mut detail = fallback.trim().to_string();
    if let Some(Value::Object(map)) = body {
        if let Some(err) = map.get("error") {
            let from_err = match err {
                Value::Object(err_map) => err_map
                    .get("message")
                    .and_then(|v| v.as_str())
                    .or_else(|| err_map.get("status").and_then(|v| v.as_str()))
                    .map(|s| s.to_string())
                    .or_else(|| {
                        err_map.get("code").map(|v| {
                            v.as_str()
                                .map(|s| s.to_string())
                                .unwrap_or_else(|| v.to_string())
                        })
                    })
                    .or_else(|| serde_json::to_string(err).ok()),
                Value::String(s) => Some(s.clone()),
                _ => None,
            };
            if let Some(s) = from_err {
                let s = s.trim();
                if !s.is_empty() {
                    detail = s.to_string();
                }
            }
        }
    }
    if detail.chars().count() > 280 {
        let mut truncated: String = detail.chars().take(280).collect();
        truncated.push_str("...");
        detail = truncated;
    }
    detail
}

/// ←→ Python `_classify_provider_exception` (translator.py:99-138)
///
/// 按 HTTP status + 错误消息关键字分类。Rust 端调用方传入：
/// - `status`：HTTP status code（若 reqwest 在 send/json 阶段失败则为 None）
/// - `retry_after_header`：Retry-After header 原始字符串（可选）
/// - `body`：JSON body（若服务端返回了 JSON，可选）
/// - `message`：原始错误文本（用于关键字匹配 + fallback detail）
pub fn classify_provider_error(
    status: Option<u16>,
    retry_after_header: Option<&str>,
    body: Option<&Value>,
    message: &str,
) -> ProviderError {
    let retry_after = parse_retry_after_seconds(retry_after_header);
    let normalized = message.to_lowercase();

    // 1. 429 / rate limit
    if status == Some(429)
        || normalized.contains("rate limit")
        || normalized.contains("too many requests")
    {
        return ProviderError::RateLimited {
            retry_after_s: retry_after,
        };
    }

    // 2. 402 / quota keywords（含中文）
    const QUOTA_KEYWORDS: &[&str] = &[
        "insufficient_quota",
        "quota exceeded",
        "quota is exceeded",
        "exceeded your current quota",
        "余额不足",
        "额度不足",
        "额度已用尽",
        "账户额度已用尽",
    ];
    if status == Some(402) || QUOTA_KEYWORDS.iter().any(|kw| normalized.contains(kw)) {
        return ProviderError::QuotaExceeded;
    }

    // 3. 5xx / timeout / temporarily unavailable
    if matches!(status, Some(500) | Some(502) | Some(503) | Some(504))
        || normalized.contains("timeout")
        || normalized.contains("temporarily unavailable")
    {
        return ProviderError::Transient {
            retry_after_s: retry_after,
        };
    }

    // 4. 4xx 非 429/402 → NonRetryable
    if matches!(
        status,
        Some(400) | Some(401) | Some(403) | Some(404) | Some(422)
    ) {
        let detail = extract_provider_error_detail(body, message);
        let mut composed = String::from("模型请求失败");
        if let Some(s) = status {
            composed.push_str(&format!("（HTTP {s}）"));
        }
        if !detail.is_empty() {
            composed.push('：');
            composed.push_str(&detail);
        }
        return ProviderError::NonRetryable {
            message: composed,
            status_code: status,
            detail,
        };
    }

    // Fallback
    ProviderError::Other(message.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_rate_limited_by_status() {
        let err = classify_provider_error(Some(429), Some("3"), None, "rate limited");
        match err {
            ProviderError::RateLimited { retry_after_s } => {
                assert_eq!(retry_after_s, Some(3.0));
            }
            _ => panic!("expected RateLimited"),
        }
    }

    #[test]
    fn test_rate_limited_by_keyword() {
        let err = classify_provider_error(None, None, None, "Too Many Requests");
        assert!(matches!(err, ProviderError::RateLimited { .. }));
    }

    #[test]
    fn test_quota_exceeded_by_402() {
        let err = classify_provider_error(Some(402), None, None, "payment required");
        assert!(matches!(err, ProviderError::QuotaExceeded));
    }

    #[test]
    fn test_quota_exceeded_by_chinese_keyword() {
        let err = classify_provider_error(None, None, None, "用户账户余额不足，请充值");
        assert!(matches!(err, ProviderError::QuotaExceeded));
    }

    #[test]
    fn test_transient_5xx() {
        let err = classify_provider_error(Some(503), None, None, "service unavailable");
        assert!(matches!(err, ProviderError::Transient { .. }));
        assert!(err.is_retryable());
    }

    #[test]
    fn test_transient_timeout_keyword() {
        let err = classify_provider_error(None, None, None, "request timeout after 30s");
        assert!(matches!(err, ProviderError::Transient { .. }));
    }

    #[test]
    fn test_non_retryable_400() {
        let body = json!({"error": {"message": "invalid model id"}});
        let err = classify_provider_error(Some(400), None, Some(&body), "Bad Request");
        match err {
            ProviderError::NonRetryable {
                message,
                status_code,
                detail,
            } => {
                assert_eq!(status_code, Some(400));
                assert_eq!(detail, "invalid model id");
                assert!(message.contains("HTTP 400"));
                assert!(message.contains("invalid model id"));
            }
            _ => panic!("expected NonRetryable"),
        }
    }

    #[test]
    fn test_non_retryable_401_no_body() {
        let err = classify_provider_error(Some(401), None, None, "Unauthorized");
        assert!(matches!(err, ProviderError::NonRetryable { .. }));
    }

    #[test]
    fn test_other_fallback() {
        let err = classify_provider_error(None, None, None, "connection refused");
        assert!(matches!(err, ProviderError::Other(_)));
        assert!(!err.is_retryable());
    }

    #[test]
    fn test_parse_retry_after_basic() {
        assert_eq!(parse_retry_after_seconds(Some("3.5")), Some(3.5));
        assert_eq!(parse_retry_after_seconds(Some("  10 ")), Some(10.0));
        assert_eq!(parse_retry_after_seconds(Some("-5")), Some(0.0));
        assert_eq!(parse_retry_after_seconds(Some("garbage")), None);
        assert_eq!(parse_retry_after_seconds(None), None);
    }

    #[test]
    fn test_extract_detail_truncates() {
        let long = "x".repeat(400);
        let body = json!({"error": {"message": long}});
        let detail = extract_provider_error_detail(Some(&body), "fallback");
        assert!(detail.ends_with("..."));
        assert_eq!(detail.chars().count(), 283); // 280 + "..."
    }

    #[test]
    fn test_extract_detail_falls_back() {
        let detail = extract_provider_error_detail(None, "  fallback message  ");
        assert_eq!(detail, "fallback message");
    }

    #[test]
    fn test_gemini_400_invalid_argument() {
        // Gemini 特有的错误格式：code 为 number，status 为 string
        let body = json!({
            "error": {
                "code": 400,
                "message": "Request contains an invalid argument.",
                "status": "INVALID_ARGUMENT"
            }
        });
        let detail = extract_provider_error_detail(Some(&body), "fallback");
        assert_eq!(detail, "Request contains an invalid argument.");
    }

    #[test]
    fn test_gemini_400_code_number() {
        // code 为 number 类型（非 string）
        let body = json!({
            "error": {
                "code": 400,
                "message": "Some invalid param"
            }
        });
        let detail = extract_provider_error_detail(Some(&body), "fallback");
        assert_eq!(detail, "Some invalid param");
    }

    #[test]
    fn test_gemini_400_fallback_to_status() {
        // 有 status 但无 message
        let body = json!({
            "error": {
                "code": 400,
                "status": "INVALID_ARGUMENT"
            }
        });
        let detail = extract_provider_error_detail(Some(&body), "fallback");
        assert_eq!(detail, "INVALID_ARGUMENT");
    }

    #[test]
    fn test_gemini_400_unknown_field() {
        // enable_thinking unknown field 场景：extra_body 里有不认识的字段
        let body = json!({
            "error": {
                "code": 400,
                "message": "Unknown field: enable_thinking",
                "status": "INVALID_ARGUMENT",
                "details": [{
                    "@type": "google.rpc.BadRequest"
                }]
            }
        });
        let detail = extract_provider_error_detail(Some(&body), "fallback");
        assert_eq!(detail, "Unknown field: enable_thinking");
    }

    #[test]
    fn test_openai_compatible_error() {
        let body = json!({
            "error": {
                "message": "The model `nonexistent` does not exist.",
                "type": "invalid_request_error",
                "code": "model_not_found"
            }
        });
        let err = classify_provider_error(Some(400), None, Some(&body), "Bad Request");
        assert!(matches!(err, ProviderError::NonRetryable { .. }));
    }
}
