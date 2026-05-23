//! ←→ /Users/hao/OCRandTranslation/persistence/storage.py:560-810
//! `ResolvedModelSpec` + 5 家 provider 解析 + fnm/translation pool resolver。

use crate::config::*;
use crate::model_capabilities::*;
use serde_json::Value;

#[derive(Debug, Clone)]
pub struct ResolvedModelSpec {
    pub source: String, // "builtin" / "custom"
    pub model_key: String,
    pub model_id: String,
    pub provider: String,
    pub base_url: String,
    pub api_key: String,
    pub display_label: String,
    pub api_family: String,
    pub supports_translation: bool,
    pub supports_vision: bool,
    pub supports_stream: bool,
    pub stream_mode: String,
    pub companion_chat_model_key: String,
    pub request_overrides: Value, // {"extra_body": {...}}
    pub pool_name: String,
    pub slot_index: usize,
}

impl Default for ResolvedModelSpec {
    fn default() -> Self {
        Self {
            source: String::new(),
            model_key: String::new(),
            model_id: String::new(),
            provider: String::new(),
            base_url: String::new(),
            api_key: String::new(),
            display_label: String::new(),
            api_family: "chat".into(),
            supports_translation: true,
            supports_vision: false,
            supports_stream: true,
            stream_mode: "chat_json".into(),
            companion_chat_model_key: String::new(),
            request_overrides: Value::Null,
            pool_name: String::new(),
            slot_index: 0,
        }
    }
}

impl ResolvedModelSpec {
    /// 用于 sup_recovery client 缓存 dedup（≈ Python `_get_or_create_vision_client` 的 spec_hash）。
    pub fn spec_hash(&self) -> u64 {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};
        let mut h = DefaultHasher::new();
        self.api_key.hash(&mut h);
        self.base_url.hash(&mut h);
        self.model_id.hash(&mut h);
        h.finish()
    }
}

/// ←→ Python `_thinking_request_overrides`
fn thinking_request_overrides(
    provider: &str,
    model: &Option<ModelSpec>,
    thinking_enabled: bool,
) -> Value {
    let p = provider.trim().to_lowercase();
    let enabled = thinking_enabled;
    let (mut supports_toggle, mut request_format) = match model {
        Some(m) => (
            m.supports_thinking_toggle,
            m.thinking_request_format.clone(),
        ),
        None => (false, String::new()),
    };
    if p == "qwen"
        && model
            .as_ref()
            .map(|m| matches!(m.api_family, ApiFamily::Chat))
            .unwrap_or(false)
    {
        return serde_json::json!({
            "extra_body": thinking_payload_for_provider("qwen", enabled, &request_format)
        });
    }
    if !supports_toggle {
        match p.as_str() {
            "deepseek" => {
                supports_toggle = enabled;
                if request_format.is_empty() {
                    request_format = "thinking_type".into();
                }
            }
            "glm" | "kimi" => {
                supports_toggle = true;
                if request_format.is_empty() {
                    request_format = "thinking_type".into();
                }
            }
            "mimo" | "mimo_token_plan" if enabled => {
                supports_toggle = true;
                if request_format.is_empty() {
                    request_format = "thinking_type".into();
                }
            }
            _ => {}
        }
    }
    if !supports_toggle {
        return Value::Null;
    }
    if p == "deepseek" && !enabled {
        return Value::Null;
    }
    let payload = thinking_payload_for_provider(&p, enabled, &request_format);
    if payload.is_null() {
        Value::Null
    } else {
        serde_json::json!({ "extra_body": payload })
    }
}

/// ←→ Python `_resolve_builtin_model_spec`
pub fn resolve_builtin_model_spec(
    key: &str,
    capability: Option<&str>,
    thinking_enabled: bool,
) -> ResolvedModelSpec {
    let builtin_key = if capability.is_some() {
        normalize_builtin_model_key(key, capability)
    } else {
        key.trim().to_string()
    };
    let final_key = if MODEL_SPECS.contains_key(&builtin_key) {
        builtin_key
    } else {
        normalize_builtin_model_key("", capability)
    };
    let model = MODEL_SPECS.get(&final_key).cloned();
    let provider = model
        .as_ref()
        .map(|m| m.provider.clone())
        .unwrap_or_else(|| "deepseek".into());
    let (api_key, base_url) = match provider.as_str() {
        "qwen" | "qwen_mt" => (get_dashscope_key(), QWEN_BASE_URLS["cn"].to_string()),
        "mimo" => (get_mimo_api_key(), MIMO_BASE_URL.to_string()),
        "glm" => (get_glm_api_key(), GLM_BASE_URL.to_string()),
        "kimi" => (get_kimi_api_key(), KIMI_BASE_URL.to_string()),
        _ => (get_deepseek_key(), DEEPSEEK_BASE_URL.to_string()),
    };
    let request_overrides = thinking_request_overrides(&provider, &model, thinking_enabled);
    let m_ref = model.clone();
    ResolvedModelSpec {
        source: "builtin".into(),
        model_key: final_key.clone(),
        model_id: m_ref.as_ref().map(|m| m.id.clone()).unwrap_or(final_key),
        provider,
        base_url,
        api_key,
        display_label: m_ref.as_ref().map(|m| m.label.clone()).unwrap_or_default(),
        api_family: m_ref
            .as_ref()
            .map(|m| m.api_family.as_str().to_string())
            .unwrap_or_else(|| "chat".into()),
        supports_translation: m_ref
            .as_ref()
            .map(|m| m.supports_translation)
            .unwrap_or(true),
        supports_vision: m_ref.as_ref().map(|m| m.supports_vision).unwrap_or(false),
        supports_stream: m_ref.as_ref().map(|m| m.supports_stream).unwrap_or(true),
        stream_mode: m_ref
            .as_ref()
            .map(|m| m.stream_mode.clone())
            .unwrap_or_else(|| "chat_json".into()),
        companion_chat_model_key: m_ref
            .as_ref()
            .map(|m| m.companion_chat_model_key.clone())
            .unwrap_or_default(),
        request_overrides,
        pool_name: String::new(),
        slot_index: 0,
    }
}

/// ←→ Python `_resolve_custom_model_spec`
pub fn resolve_custom_model_spec(slot: &ModelPoolSlot, capability: &str) -> ResolvedModelSpec {
    let provider = if slot.provider_type.is_empty() {
        "qwen".into()
    } else {
        slot.provider_type.trim().to_lowercase()
    };
    let model_id = slot.model_id.trim().to_string();
    let builtin_key = infer_builtin_key_from_custom_model(&provider, &model_id, Some(capability));
    let builtin_spec = match provider.as_str() {
        "qwen" | "qwen_mt" | "deepseek" | "glm" | "kimi" | "mimo" | "mimo_token_plan" => {
            MODEL_SPECS.get(&builtin_key).cloned()
        }
        _ => None,
    };
    let (api_key, base_url) = match provider.as_str() {
        "qwen" | "qwen_mt" => {
            let region = if slot.qwen_region.is_empty() {
                "cn"
            } else {
                slot.qwen_region.as_str()
            };
            let url = QWEN_BASE_URLS
                .get(region)
                .copied()
                .unwrap_or(QWEN_BASE_URLS["cn"]);
            (get_dashscope_key(), url.to_string())
        }
        "deepseek" => (get_deepseek_key(), DEEPSEEK_BASE_URL.to_string()),
        "glm" => (get_glm_api_key(), GLM_BASE_URL.to_string()),
        "kimi" => (get_kimi_api_key(), KIMI_BASE_URL.to_string()),
        "mimo" => (get_mimo_api_key(), MIMO_BASE_URL.to_string()),
        "mimo_token_plan" => (
            slot.custom_api_key.clone(),
            if slot.base_url.is_empty() {
                MIMO_TOKEN_PLAN_BASE_URL_DEFAULT.to_string()
            } else {
                slot.base_url.clone()
            },
        ),
        _ => (slot.custom_api_key.clone(), slot.base_url.clone()),
    };
    let thinking_enabled = slot.thinking_enabled;
    let mut request_overrides =
        thinking_request_overrides(&provider, &builtin_spec, thinking_enabled);
    // 仅对明确支持的 builtin provider 继承 builtin request override
    match provider.as_str() {
        "qwen" => {
            let extra = if !slot.extra_body.is_null() {
                slot.extra_body.clone()
            } else {
                serde_json::json!({ "enable_thinking": thinking_enabled })
            };
            request_overrides = serde_json::json!({ "extra_body": extra });
        }
        "qwen_mt" => {
            let extra = if !slot.extra_body.is_null() {
                slot.extra_body.clone()
            } else {
                serde_json::json!({})
            };
            request_overrides = serde_json::json!({ "extra_body": extra });
        }
        "deepseek" | "glm" | "kimi" | "mimo" | "mimo_token_plan" => {
            // 这些 provider 的 builtin override 已由 thinking_request_overrides 计算
            // 保留 builtin_spec 的结果，不做额外覆盖
        }
        _ => {
            // Gemini 等自定义 provider：不继承任何 builtin request override
            // 只使用 custom slot 显式设置的 extra_body
            request_overrides = Value::Null;
            if let Value::Object(extra) = &slot.extra_body {
                if !extra.is_empty() {
                    request_overrides = serde_json::json!({ "extra_body": slot.extra_body });
                }
            }
        }
    }
    let default_api_family = if matches!(capability, "vision" | "fnm") {
        "vision"
    } else if provider == "qwen_mt" {
        "mt"
    } else {
        "chat"
    };
    let api_family = builtin_spec
        .as_ref()
        .map(|s| s.api_family.as_str().to_string())
        .unwrap_or_else(|| default_api_family.to_string());
    let display_label = if slot.display_name.is_empty() {
        model_id.clone()
    } else {
        slot.display_name.clone()
    };
    let stream_mode = builtin_spec
        .as_ref()
        .map(|s| s.stream_mode.clone())
        .unwrap_or_else(|| {
            if provider == "qwen_mt" {
                "mt_cumulative".into()
            } else {
                "chat_json".into()
            }
        });
    ResolvedModelSpec {
        source: "custom".into(),
        model_key: String::new(),
        model_id,
        provider,
        base_url,
        api_key,
        display_label,
        api_family,
        supports_translation: builtin_spec
            .as_ref()
            .map(|s| s.supports_translation)
            .unwrap_or(capability == "translation"),
        supports_vision: builtin_spec
            .as_ref()
            .map(|s| s.supports_vision)
            .unwrap_or(matches!(capability, "vision" | "fnm")),
        supports_stream: builtin_spec
            .as_ref()
            .map(|s| s.supports_stream)
            .unwrap_or(true),
        stream_mode,
        companion_chat_model_key: builtin_spec
            .as_ref()
            .map(|s| s.companion_chat_model_key.clone())
            .unwrap_or_default(),
        request_overrides,
        pool_name: String::new(),
        slot_index: 0,
    }
}

/// ←→ Python `_resolve_pool_slot_spec`
fn resolve_pool_slot_spec(
    slot: &ModelPoolSlot,
    capability: &str,
    pool_name: &str,
    slot_index: usize,
) -> Option<ResolvedModelSpec> {
    let mode = slot.mode.trim().to_lowercase();
    if mode == "empty" || mode.is_empty() {
        return None;
    }
    let mut spec = if mode == "builtin" {
        resolve_builtin_model_spec(&slot.builtin_key, Some(capability), slot.thinking_enabled)
    } else {
        resolve_custom_model_spec(slot, capability)
    };
    spec.pool_name = pool_name.to_string();
    spec.slot_index = slot_index;
    Some(spec)
}

/// ←→ Python `resolve_translation_model_pool_specs`
pub fn resolve_translation_model_pool_specs() -> Vec<ResolvedModelSpec> {
    let pool = get_translation_model_pool();
    pool.iter()
        .enumerate()
        .filter_map(|(i, slot)| resolve_pool_slot_spec(slot, "translation", "translation", i + 1))
        .collect()
}

/// ←→ Python `resolve_fnm_model_pool_specs`
pub fn resolve_fnm_model_pool_specs() -> Vec<ResolvedModelSpec> {
    let pool = get_fnm_model_pool();
    pool.iter()
        .enumerate()
        .filter_map(|(i, slot)| resolve_pool_slot_spec(slot, "fnm", "fnm", i + 1))
        .collect()
}

/// ←→ Python `resolve_visual_model_spec`：返回 fnm pool 第一个 vision-capable spec。
pub fn resolve_visual_model_spec() -> Option<ResolvedModelSpec> {
    resolve_fnm_model_pool_specs()
        .into_iter()
        .find(|s| s.supports_vision)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builtin_qwen_routes_to_dashscope_base() {
        let spec = resolve_builtin_model_spec("qwen3.6-plus", Some("fnm"), false);
        assert_eq!(spec.provider, "qwen");
        assert!(spec.base_url.contains("dashscope"));
        assert!(spec.supports_vision);
    }

    #[test]
    fn builtin_deepseek_routes_to_deepseek_base() {
        let spec = resolve_builtin_model_spec("deepseek-chat", Some("translation"), false);
        assert_eq!(spec.provider, "deepseek");
        assert_eq!(spec.base_url, DEEPSEEK_BASE_URL);
    }

    #[test]
    fn custom_qwen_extra_body_thinking() {
        let slot = ModelPoolSlot {
            mode: "custom".into(),
            provider_type: "qwen".into(),
            model_id: "qwen3.6-plus".into(),
            qwen_region: "cn".into(),
            thinking_enabled: true,
            ..Default::default()
        };
        let spec = resolve_custom_model_spec(&slot, "fnm");
        assert_eq!(spec.provider, "qwen");
        assert_eq!(
            spec.request_overrides["extra_body"]["enable_thinking"],
            serde_json::json!(true)
        );
    }

    #[test]
    fn custom_gemini_has_no_enable_thinking() {
        let slot = ModelPoolSlot {
            mode: "custom".into(),
            provider_type: "gemini".into(),
            model_id: "gemini-3.1-flash-lite".into(),
            ..Default::default()
        };
        let spec = resolve_custom_model_spec(&slot, "fnm");
        assert_eq!(spec.provider, "gemini");
        // Gemini 自定义 provider 不应继承 Qwen 的 enable_thinking
        assert!(
            spec.request_overrides.is_null() || spec.request_overrides == serde_json::json!({}),
            "gemini should not inherit enable_thinking, got {:?}",
            spec.request_overrides
        );
        // api_key / base_url 应来自 custom slot，不走 Qwen builtin 路径
        assert!(
            !spec.base_url.contains("dashscope"),
            "gemini should not route to dashscope, got {}",
            spec.base_url
        );
    }

    #[test]
    fn custom_gemini_respects_explicit_extra_body() {
        let slot = ModelPoolSlot {
            mode: "custom".into(),
            provider_type: "gemini".into(),
            model_id: "gemini-3.1-flash-lite".into(),
            extra_body: serde_json::json!({"temperature": 0.0}),
            ..Default::default()
        };
        let spec = resolve_custom_model_spec(&slot, "fnm");
        assert_eq!(spec.provider, "gemini");
        // 显式设置的 extra_body 应保留
        assert!(
            spec.request_overrides["extra_body"]["temperature"] == serde_json::json!(0.0),
            "explicit extra_body should be preserved, got {:?}",
            spec.request_overrides
        );
        // 不应包含 enable_thinking
        let body_str = spec.request_overrides.to_string();
        assert!(
            !body_str.contains("enable_thinking"),
            "gemini should not have enable_thinking, got {}",
            body_str
        );
    }

    #[test]
    fn pool_filters_empty_slots() {
        // 默认 fnm pool 至少有一个 builtin 槽
        let specs = resolve_fnm_model_pool_specs();
        assert!(!specs.is_empty());
        assert!(specs.iter().all(|s| !s.model_id.is_empty()));
    }

    #[test]
    fn spec_hash_stable_for_same_spec() {
        let a = resolve_builtin_model_spec("qwen3.6-plus", Some("fnm"), false);
        let b = resolve_builtin_model_spec("qwen3.6-plus", Some("fnm"), false);
        assert_eq!(a.spec_hash(), b.spec_hash());
    }
}
