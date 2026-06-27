//! LLM 响应 JSON 块提取（phase2 内多个 vision client 共用）。
//!
//! 原先 `sup_recovery/layer3`、`visual_anchor_recovery/vision_client`、
//! `llm_bare_digit_verify/llm_client` 各有一份逐字节相同的副本，B5-2 收敛至此。

/// 从 LLM 文本响应中提取首个 `{...}` JSON 块（容忍 markdown 围栏等前后噪声）。
/// 无花括号时原样返回。
pub(crate) fn extract_json_block(content: &str) -> String {
    if let Some(start) = content.find('{') {
        if let Some(end) = content.rfind('}') {
            return content[start..=end].to_string();
        }
    }
    content.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_json_from_markdown() {
        let resp = "```json\n{\"accepted\": true, \"confidence\": 0.9}\n```";
        let extracted = extract_json_block(resp);
        assert!(extracted.contains("\"accepted\": true"));
    }

    #[test]
    fn extract_plain_json() {
        let resp = r#"{"accepted": false, "confidence": 0.0}"#;
        let extracted = extract_json_block(resp);
        assert!(extracted.contains("accepted"));
    }

    #[test]
    fn extract_empty_returns_content() {
        let resp = "no json here";
        let extracted = extract_json_block(resp);
        assert_eq!(extracted, resp);
    }
}
